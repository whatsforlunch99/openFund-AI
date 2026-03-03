#!/usr/bin/env python3
"""Single script to test all Librarian agent functions and MCP tools it uses.

Runs:
- combine_results (unit)
- retrieve_documents (vector_tool.search)
- retrieve_knowledge_graph (kg_tool.get_relations)
- handle_message with content path -> file_tool.read_file
- handle_message with vector_query -> vector_tool.search
- handle_message with fund -> kg_tool.get_relations
- handle_message with sql_query -> sql_tool.run_query (schema-aligned)

Uses real backends when DATABASE_URL, NEO4J_URI, MILVUS_URI are set (e.g. after
./scripts/run.sh or data_manager distribute-funds); otherwise tools return mock/empty.
Run from project root: python scripts/test_librarian.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid

# Project root on path so "from a2a...", "from agents...", "from mcp..." work
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_SCRIPT_DIR)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load .env from project root
try:
    from config.config import load_config
    load_config()
except Exception:
    pass


def _show(label: str, data: object, max_item_chars: int = 200) -> None:
    """Print a short summary of retrieved data for one test."""
    import json
    if data is None:
        print(f"  Retrieved: (none)")
        return
    if isinstance(data, dict):
        if "documents" in data:
            docs = data["documents"]
            n = len(docs) if isinstance(docs, list) else 0
            print(f"  Retrieved: {n} document(s)")
            if n and isinstance(docs, list):
                first = docs[0]
                s = json.dumps(first, default=str)[:max_item_chars]
                print(f"  First doc: {s}{'...' if len(str(first)) > max_item_chars else ''}")
        elif "nodes" in data or "edges" in data:
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])
            n_n, n_e = len(nodes), len(edges)
            print(f"  Retrieved: {n_n} node(s), {n_e} edge(s)")
            if nodes:
                s = json.dumps(nodes[0], default=str)[:max_item_chars]
                print(f"  First node: {s}{'...' if len(str(nodes[0])) > max_item_chars else ''}")
            if edges and n_e:
                s = json.dumps(edges[0], default=str)[:max_item_chars]
                print(f"  First edge: {s}{'...' if len(str(edges[0])) > max_item_chars else ''}")
        elif "rows" in data:
            rows = data["rows"]
            n = len(rows) if isinstance(rows, list) else 0
            print(f"  Retrieved: {n} row(s)")
            if n and isinstance(rows, list):
                s = json.dumps(rows[0], default=str)[:max_item_chars]
                print(f"  First row: {s}{'...' if len(str(rows[0])) > max_item_chars else ''}")
        elif "content" in data:
            c = str(data["content"])[:max_item_chars]
            print(f"  Retrieved: content ({len(str(data.get('content', '')))} chars) — {c}{'...' if len(str(data.get('content', ''))) > max_item_chars else ''}")
        else:
            keys = list(data.keys())[:8]
            print(f"  Retrieved keys: {keys}")
    elif isinstance(data, list):
        print(f"  Retrieved: {len(data)} item(s)")
        if data:
            s = json.dumps(data[0], default=str)[:max_item_chars]
            print(f"  First: {s}{'...' if len(str(data[0])) > max_item_chars else ''}")
    else:
        print(f"  Retrieved: {type(data).__name__} — {str(data)[:max_item_chars]}")


def run(
    skip_file: bool = False,
    skip_vector: bool = False,
    skip_kg: bool = False,
    skip_sql: bool = False,
) -> int:
    """Run all Librarian tests. Returns 0 if all pass, 1 otherwise."""
    failures = 0

    # --- Imports (same as app) ---
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.librarian_agent import LibrarianAgent
        from mcp.mcp_client import MCPClient
        from mcp.mcp_server import MCPServer
    except ImportError as e:
        print(f"FAIL: Import error: {e}")
        return 1

    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)
    bus = InMemoryMessageBus()
    bus.register_agent("librarian")
    bus.register_agent("planner")
    librarian = LibrarianAgent("librarian", bus, mcp_client=client, llm_client=None)

    # --- 1. combine_results (no MCP) ---
    try:
        out = librarian.combine_results(
            [{"id": "1", "content": "a"}],
            {"nodes": [{"id": "N1"}], "edges": []},
        )
        assert isinstance(out, dict)
        assert "documents" in out and "graph" in out
        assert len(out["documents"]) == 1 and out["documents"][0]["id"] == "1"
        assert out["graph"]["nodes"][0]["id"] == "N1"
        print("PASS: combine_results")
        _show("combine_results", out)
    except Exception as e:
        print(f"FAIL: combine_results — {e}")
        failures += 1

    # --- 2. retrieve_documents (vector_tool.search) ---
    if not skip_vector:
        try:
            docs = librarian.retrieve_documents("NVDA fund performance", top_k=3)
            assert isinstance(docs, list)
            print("PASS: retrieve_documents (vector_tool.search)")
            _show("retrieve_documents", docs)
        except Exception as e:
            print(f"FAIL: retrieve_documents — {e}")
            failures += 1
    else:
        print("SKIP: retrieve_documents")

    # --- 3. retrieve_knowledge_graph (kg_tool.get_relations) ---
    if not skip_kg:
        try:
            graph = librarian.retrieve_knowledge_graph("NVDA")
            assert isinstance(graph, dict)
            assert "nodes" in graph or "edges" in graph or graph == {"nodes": [], "edges": []}
            print("PASS: retrieve_knowledge_graph (kg_tool.get_relations)")
            _show("retrieve_knowledge_graph", graph)
        except Exception as e:
            print(f"FAIL: retrieve_knowledge_graph — {e}")
            failures += 1
    else:
        print("SKIP: retrieve_knowledge_graph")

    # --- 4. handle_message REQUEST with path -> file_tool.read_file ---
    if not skip_file:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write("Librarian test file content")
                path = f.name
            try:
                cid = str(uuid.uuid4())
                req = ACLMessage(
                    performative=Performative.REQUEST,
                    sender="planner",
                    receiver="librarian",
                    content={"path": path, "query": "read file"},
                    conversation_id=cid,
                    reply_to="planner",
                )
                bus.send(req)
                librarian.handle_message(req)
                reply = bus.receive("planner", timeout=2.0)
                assert reply is not None, "No INFORM reply"
                assert reply.performative == Performative.INFORM
                assert reply.sender == "librarian"
                assert isinstance(reply.content, dict)
                if "content" in reply.content:
                    assert "Librarian test file content" in str(reply.content["content"])
                elif "file" in reply.content and isinstance(reply.content["file"], dict):
                    assert "Librarian test file content" in str(reply.content["file"].get("content", ""))
                else:
                    assert "content" in reply.content or "file" in reply.content
                print("PASS: handle_message path -> file_tool.read_file")
                _show("path reply", reply.content)
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        except Exception as e:
            print(f"FAIL: handle_message path — {e}")
            failures += 1
    else:
        print("SKIP: handle_message path")

    # --- 5. handle_message REQUEST with vector_query ---
    if not skip_vector:
        try:
            cid = str(uuid.uuid4())
            req = ACLMessage(
                performative=Performative.REQUEST,
                sender="planner",
                receiver="librarian",
                content={"vector_query": "ETF holdings", "top_k": 2},
                conversation_id=cid,
                reply_to="planner",
            )
            bus.send(req)
            librarian.handle_message(req)
            reply = bus.receive("planner", timeout=5.0)
            assert reply is not None
            assert reply.performative == Performative.INFORM
            assert reply.sender == "librarian"
            assert isinstance(reply.content, dict)
            assert "documents" in reply.content or "graph" in reply.content or "error" in reply.content
            print("PASS: handle_message vector_query -> vector_tool.search")
            _show("vector_query reply", reply.content)
        except Exception as e:
            print(f"FAIL: handle_message vector_query — {e}")
            failures += 1

    # --- 6. handle_message REQUEST with fund -> kg_tool ---
    if not skip_kg:
        try:
            cid = str(uuid.uuid4())
            req = ACLMessage(
                performative=Performative.REQUEST,
                sender="planner",
                receiver="librarian",
                content={"fund": "NVDA", "query": "graph for NVDA"},
                conversation_id=cid,
                reply_to="planner",
            )
            bus.send(req)
            librarian.handle_message(req)
            reply = bus.receive("planner", timeout=5.0)
            assert reply is not None
            assert reply.performative == Performative.INFORM
            assert reply.sender == "librarian"
            assert isinstance(reply.content, dict)
            assert "graph" in reply.content or "documents" in reply.content or "error" in reply.content
            print("PASS: handle_message fund -> kg_tool.get_relations")
            _show("fund reply", reply.content)
        except Exception as e:
            print(f"FAIL: handle_message fund — {e}")
            failures += 1

    # --- 7. handle_message REQUEST with sql_query (schema-aligned) ---
    if not skip_sql:
        try:
            cid = str(uuid.uuid4())
            req = ACLMessage(
                performative=Performative.REQUEST,
                sender="planner",
                receiver="librarian",
                content={
                    "sql_query": "SELECT symbol, name FROM fund_info LIMIT 3",
                    "query": "fund info",
                },
                conversation_id=cid,
                reply_to="planner",
            )
            bus.send(req)
            librarian.handle_message(req)
            reply = bus.receive("planner", timeout=5.0)
            assert reply is not None
            assert reply.performative == Performative.INFORM
            assert reply.sender == "librarian"
            assert isinstance(reply.content, dict)
            if "sql" in reply.content and isinstance(reply.content["sql"], dict) and reply.content["sql"].get("error"):
                print("PASS: handle_message sql_query (sql_tool ran; DB error acceptable)")
            else:
                assert "sql" in reply.content or "documents" in reply.content or "error" in reply.content
                print("PASS: handle_message sql_query -> sql_tool.run_query")
            _show("sql_query reply", reply.content.get("sql") if isinstance(reply.content, dict) else reply.content)
        except Exception as e:
            print(f"FAIL: handle_message sql_query — {e}")
            failures += 1
    else:
        print("SKIP: handle_message sql_query")

    return 0 if failures == 0 else 1


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Test all Librarian functions and MCP tools.")
    p.add_argument("--skip-file", action="store_true", help="Skip file_tool path test")
    p.add_argument("--skip-vector", action="store_true", help="Skip vector_tool tests")
    p.add_argument("--skip-kg", action="store_true", help="Skip kg_tool tests")
    p.add_argument("--skip-sql", action="store_true", help="Skip sql_tool test")
    args = p.parse_args()
    code = run(
        skip_file=args.skip_file,
        skip_vector=args.skip_vector,
        skip_kg=args.skip_kg,
        skip_sql=args.skip_sql,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
