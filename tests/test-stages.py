"""Stage tests as specified in docs/test_plan.md.

One test function per stage, named test_stage_N_M (e.g. test_stage_1_2), so that:
  pytest tests/test-stages.py -k stage_1_2 -v
matches and runs the correct stage test. No classes; per clarification A2.
"""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from io import StringIO
from unittest.mock import patch

import pytest

# --- Stage 1.1: Config and minimal main ---


def test_stage_1_1() -> None:
    """Stage 1.1: load_config returns config; main() logs ready and exits 0."""
    import logging

    from config.config import Config, load_config

    cfg = load_config()
    assert isinstance(cfg, Config)
    assert hasattr(cfg, "milvus_uri")
    assert hasattr(cfg, "analyst_api_url")

    from main import main

    log_buf = StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.INFO)
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        main()
        out = log_buf.getvalue()
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert "OpenFund-AI ready (config loaded)" in out


# --- Stage 1.2: In-memory MessageBus ---


def test_stage_1_2() -> None:
    """Stage 1.2: MessageBus register_agent, send, receive, receive timeout, broadcast, broadcast scope (C1)."""
    try:
        from a2a.message_bus import InMemoryMessageBus
    except ImportError:
        pytest.skip("InMemoryMessageBus not implemented (Stage 1.2)")

    bus = InMemoryMessageBus()
    bus.register_agent("a")
    bus.register_agent("b")

    from a2a.acl_message import ACLMessage, Performative

    msg = ACLMessage(
        performative=Performative.REQUEST, sender="x", receiver="a", content={"q": 1}
    )
    bus.send(msg)
    received = bus.receive("a", timeout=0.5)
    assert received is not None
    assert received.content == {"q": 1}

    assert bus.receive("empty_agent", timeout=0.1) is None

    broadcast_msg = ACLMessage(
        performative=Performative.STOP, sender="x", receiver="*", content={}
    )
    bus.broadcast(broadcast_msg)
    assert bus.receive("unregistered_agent", timeout=0.1) is None
    r_a = bus.receive("a", timeout=0.5)
    r_b = bus.receive("b", timeout=0.5)
    assert r_a is not None and r_b is not None
    assert r_a.performative is Performative.STOP


# --- Stage 1.3: ConversationManager ---


def test_stage_1_3() -> None:
    """Stage 1.3: All functionalities per test_plan.md (lines 57–67): ConversationState (B2), create/get, register_reply, persistence, MEMORY_STORE_PATH, anonymous, broadcast_stop."""
    try:
        from a2a.conversation_manager import ConversationManager
        from a2a.message_bus import InMemoryMessageBus
    except ImportError:
        pytest.skip("InMemoryMessageBus not implemented (Stage 1.3)")

    from a2a.acl_message import ACLMessage, Performative

    bus = InMemoryMessageBus()
    bus.register_agent("observer")
    mgr = ConversationManager(bus)

    try:
        cid = mgr.create_conversation("user1", "What is fund X?")
    except NotImplementedError:
        pytest.skip(
            "ConversationManager.create_conversation not implemented (Stage 1.3)"
        )

    assert isinstance(cid, str)
    assert len(cid) > 0
    try:
        uuid.UUID(cid)
    except ValueError:
        pytest.fail("conversation_id must be a valid UUID string")

    state = mgr.get_conversation(cid)
    assert state is not None
    state_id = getattr(state, "id", None) or getattr(state, "conversation_id", None)
    assert state_id == cid
    assert state.user_id == "user1"
    assert hasattr(state, "messages")
    assert isinstance(state.messages, list)
    if hasattr(state, "initial_query"):
        assert state.initial_query == "What is fund X?"
    if hasattr(state, "status"):
        assert state.status == "active"
    if hasattr(state, "final_response"):
        assert state.final_response is None
    if hasattr(state, "created_at"):
        assert state.created_at is not None
    if hasattr(state, "completion_event"):
        assert not state.completion_event.is_set()

    reply = ACLMessage(
        performative=Performative.INFORM,
        sender="responder",
        receiver="api",
        content={"final_response": "Here is the answer."},
    )
    try:
        mgr.register_reply(cid, reply)
    except NotImplementedError:
        pytest.skip("ConversationManager.register_reply not implemented (Stage 1.3)")

    state2 = mgr.get_conversation(cid)
    assert state2 is not None
    assert len(state2.messages) >= 1
    if hasattr(state2, "status"):
        assert state2.status == "complete"
    if hasattr(state2, "final_response"):
        assert state2.final_response is not None
    if hasattr(state2, "completion_event"):
        assert state2.completion_event.is_set()

    assert mgr.get_conversation("nonexistent-id") is None

    persistence_ok = False
    memory_root = os.environ.get("MEMORY_STORE_PATH", "memory/").rstrip("/")
    default_path = os.path.join(memory_root, "user1", "conversations.json")
    if os.path.exists(default_path):
        with open(default_path) as f:
            data = json.load(f)
        assert isinstance(data, (list, dict))
        persistence_ok = True
    if not persistence_ok:
        with tempfile.TemporaryDirectory() as tmp:
            prev = os.environ.get("MEMORY_STORE_PATH")
            os.environ["MEMORY_STORE_PATH"] = tmp
            try:
                mgr2 = ConversationManager(bus)
                try:
                    _ = mgr2.create_conversation("u2", "Query")
                    path2 = os.path.join(tmp, "u2", "conversations.json")
                    if os.path.exists(path2):
                        with open(path2) as f:
                            json.load(f)
                        persistence_ok = True
                except NotImplementedError:
                    pass
            finally:
                if prev is not None:
                    os.environ["MEMORY_STORE_PATH"] = prev
                else:
                    os.environ.pop("MEMORY_STORE_PATH", None)
    if persistence_ok and os.path.exists(default_path):
        assert os.path.isdir(os.path.dirname(default_path)), (
            "Persistence (D2): dir auto-created for memory/<user_id>/conversations.json"
        )

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("MEMORY_STORE_PATH")
        os.environ["MEMORY_STORE_PATH"] = tmp
        try:
            mgr3 = ConversationManager(bus)
            try:
                _ = mgr3.create_conversation("u3", "Q")
                custom_path = os.path.join(tmp, "u3", "conversations.json")
                assert os.path.exists(custom_path), (
                    "MEMORY_STORE_PATH should configure root dir (D2)"
                )
            except NotImplementedError:
                pass
        finally:
            if prev is not None:
                os.environ["MEMORY_STORE_PATH"] = prev
            else:
                os.environ.pop("MEMORY_STORE_PATH", None)

    if persistence_ok:
        try:
            _ = mgr.create_conversation("", "Anonymous query")
        except NotImplementedError:
            pass
        else:
            anon_path = os.path.join(memory_root, "anonymous", "conversations.json")
            assert os.path.exists(anon_path), (
                "user_id='' must persist to memory/anonymous/conversations.json (D2)"
            )

    try:
        mgr.broadcast_stop(cid)
    except NotImplementedError:
        pytest.skip("ConversationManager.broadcast_stop not implemented (Stage 1.3)")
    stop_msg = bus.receive("observer", timeout=0.5)
    assert stop_msg is not None
    assert stop_msg.performative is Performative.STOP


# --- Placeholder stages: one function per stage so -k stage_N_M always matches ---


def test_stage_2_1() -> None:
    """Stage 2.1: MCP server and client, file_tool.read_file."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello stage 2.1")
        path = f.name
    try:
        result = client.call_tool("file_tool.read_file", {"path": path})
        assert isinstance(result, dict)
        assert "content" in result
        assert result["content"] == "hello stage 2.1"
        assert result.get("path") == path
    finally:
        os.unlink(path)

    missing_result = client.call_tool(
        "file_tool.read_file", {"path": "/nonexistent/file.txt"}
    )
    assert isinstance(missing_result, dict)
    assert (
        "error" in missing_result
        or "content" not in missing_result
        or missing_result.get("content") is None
    )


def test_stage_2_2_trading_tools() -> None:
    """Stage 2.2: TradingAgents-integrated MCP tools (fundamental, news, market) in market_tool."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)

    # market_tool.get_fundamentals (vendor-routed)
    r = client.call_tool("market_tool.get_fundamentals", {"ticker": "AAPL"})
    assert isinstance(r, dict)
    assert "error" in r or "content" in r
    if "content" in r:
        assert "timestamp" in r
        if "No data" not in r["content"] and "unavailable" not in r["content"].lower():
            assert "AAPL" in r["content"] or "apple" in r["content"].lower()

    # market_tool.get_stock_data (recent range)
    r2 = client.call_tool(
        "market_tool.get_stock_data",
        {"symbol": "AAPL", "start_date": "2024-01-02", "end_date": "2024-01-10"},
    )
    assert isinstance(r2, dict)
    assert "error" in r2 or "content" in r2
    if "content" in r2:
        assert "timestamp" in r2
        if "No data found" not in r2["content"] and "unavailable" not in r2["content"].lower():
            assert "Open" in r2["content"] or "Close" in r2["content"]

    # market_tool.get_news (vendor-routed; AV needs start_date/end_date)
    r3 = client.call_tool(
        "market_tool.get_news",
        {"symbol": "AAPL", "limit": 3, "start_date": "2024-01-01", "end_date": "2024-01-10"},
    )
    assert isinstance(r3, dict)
    assert "error" in r3 or "content" in r3
    if "content" in r3:
        assert "timestamp" in r3

    # analyst_tool.get_indicators (vendor-routed)
    r4 = client.call_tool(
        "analyst_tool.get_indicators",
        {
            "symbol": "AAPL",
            "indicator": "close_50_sma",
            "as_of_date": "2024-01-15",
            "look_back_days": 10,
        },
    )
    assert isinstance(r4, dict)
    assert "error" in r4 or "content" in r4
    if "content" in r4:
        assert "timestamp" in r4

    # Missing required param returns error
    r5 = client.call_tool("market_tool.get_global_news", {})
    assert isinstance(r5, dict)
    assert "error" in r5

    # Vendor-routed tools (alpha_vantage or finnhub via config)
    r6 = client.call_tool(
        "market_tool.get_stock_data",
        {"symbol": "AAPL", "start_date": "2024-01-02", "end_date": "2024-01-10"},
    )
    assert isinstance(r6, dict)
    assert "error" in r6 or "content" in r6
    if "content" in r6:
        assert "timestamp" in r6

    r7 = client.call_tool(
        "analyst_tool.get_indicators",
        {
            "symbol": "AAPL",
            "indicator": "close_50_sma",
            "as_of_date": "2024-01-15",
            "look_back_days": 10,
        },
    )
    assert isinstance(r7, dict)
    assert "error" in r7 or "content" in r7
    if "content" in r7:
        assert "timestamp" in r7


# --- Vendor config: MCP_MARKET_VENDOR / MCP_INDICATOR_VENDOR (env-based switching) ---


def test_vendor_config_get_market_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_market_vendor() reads MCP_MARKET_VENDOR; default alpha_vantage; invalid/unset -> alpha_vantage."""
    try:
        from mcp.tools.market_tool import get_market_vendor
    except ImportError as e:
        pytest.skip(f"MCP market_tool not available: {e}")

    monkeypatch.delenv("MCP_MARKET_VENDOR", raising=False)
    assert get_market_vendor() == "alpha_vantage"

    monkeypatch.setenv("MCP_MARKET_VENDOR", "alpha_vantage")
    assert get_market_vendor() == "alpha_vantage"

    monkeypatch.setenv("MCP_MARKET_VENDOR", "ALPHA_VANTAGE")
    assert get_market_vendor() == "alpha_vantage"

    monkeypatch.setenv("MCP_MARKET_VENDOR", "other")
    assert get_market_vendor() == "alpha_vantage"

    monkeypatch.setenv("MCP_MARKET_VENDOR", "finnhub")
    assert get_market_vendor() == "finnhub"

    monkeypatch.setenv("MCP_MARKET_VENDOR", "")
    assert get_market_vendor() == "alpha_vantage"


def test_vendor_config_get_indicator_vendor(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_indicator_vendor() reads MCP_INDICATOR_VENDOR; default alpha_vantage; invalid -> alpha_vantage."""
    try:
        from mcp.tools.market_tool import get_indicator_vendor
    except ImportError as e:
        pytest.skip(f"MCP market_tool not available: {e}")

    monkeypatch.delenv("MCP_INDICATOR_VENDOR", raising=False)
    assert get_indicator_vendor() == "alpha_vantage"

    monkeypatch.setenv("MCP_INDICATOR_VENDOR", "alpha_vantage")
    assert get_indicator_vendor() == "alpha_vantage"

    monkeypatch.setenv("MCP_INDICATOR_VENDOR", "invalid")
    assert get_indicator_vendor() == "alpha_vantage"


def test_vendor_config_route_stock_data_av_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP_MARKET_VENDOR=alpha_vantage, _route_stock_data tries AV; on failure returns error."""
    try:
        from mcp.tools import market_tool
        from mcp.tools.market_tool import AlphaVantageRateLimitError
    except ImportError as e:
        pytest.skip(f"MCP market_tool not available: {e}")

    monkeypatch.setenv("MCP_MARKET_VENDOR", "alpha_vantage")
    av_called = []

    def fake_av(symbol: str, start_date: str, end_date: str) -> dict:
        av_called.append(1)
        raise AlphaVantageRateLimitError("rate limit")

    monkeypatch.setattr(market_tool, "get_stock_data_av", fake_av)

    result = market_tool._route_stock_data("AAPL", "2024-01-01", "2024-01-10")
    assert av_called == [1]
    assert "error" in result
    assert "unavailable" in result["error"].lower() or "rate limit" in result["error"].lower()


def test_vendor_config_route_indicators_av_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When AV fails, _route_indicators returns error."""
    try:
        from mcp.tools import analyst_tool
        from mcp.tools.market_tool import AlphaVantageRateLimitError
    except ImportError as e:
        pytest.skip(f"MCP analyst_tool not available: {e}")

    monkeypatch.setenv("MCP_INDICATOR_VENDOR", "alpha_vantage")
    av_called = []

    def fake_av(
        symbol: str, indicator: str, as_of_date: str, look_back_days: int
    ) -> dict:
        av_called.append(1)
        raise AlphaVantageRateLimitError("rate limit")

    monkeypatch.setattr(analyst_tool, "get_indicators_av", fake_av)

    result = analyst_tool._route_indicators("AAPL", "close_50_sma", "2024-01-15", 10)
    assert av_called == [1]
    assert "error" in result
    assert "unavailable" in result["error"].lower() or "rate limit" in result["error"].lower()


# --- Stage 2.3: Situation memory (BM25 + persistence) ---


def test_stage_2_3_situation_memory() -> None:
    """Stage 2.3: FinancialSituationMemory add_situations, get_memories, clear, save/load, missing file."""
    try:
        from memory.situation_memory import (
            SITUATION_MEMORY_FILENAME,
            FinancialSituationMemory,
        )
    except ImportError as e:
        pytest.skip(f"Situation memory not available: {e}")

    mem = FinancialSituationMemory("test")
    assert mem.get_memories("any situation", n_matches=1) == []

    pairs = [
        ("High inflation and rising rates", "Consider defensive sectors."),
        ("Tech volatility and institutional selling", "Reduce growth exposure."),
    ]
    mem.add_situations(pairs)
    results = mem.get_memories("inflation and interest rates", n_matches=2)
    assert len(results) >= 1
    for r in results:
        assert "matched_situation" in r
        assert "recommendation" in r
        assert "similarity_score" in r
        assert isinstance(r["similarity_score"], (int, float))

    mem.clear()
    assert mem.get_memories("inflation", n_matches=1) == []

    mem.add_situations(pairs)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, SITUATION_MEMORY_FILENAME)
        mem.save(path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["situation"] == pairs[0][0]
        assert data[0]["recommendation"] == pairs[0][1]

        mem2 = FinancialSituationMemory("test2")
        mem2.load(path)
        results2 = mem2.get_memories("inflation and rates", n_matches=1)
        assert len(results2) >= 1
        assert results2[0]["matched_situation"] == pairs[0][0]
        assert results2[0]["recommendation"] == pairs[0][1]

    mem3 = FinancialSituationMemory("test3")
    mem3.load_from_dir("/nonexistent_dir_12345")
    mem3.load(
        os.path.join(tempfile.gettempdir(), "nonexistent_situation_memory_12345.json")
    )
    assert mem3.get_memories("anything", n_matches=1) == []


def test_stage_2_3_situation_memory_load_from_dir_missing() -> None:
    """Stage 2.3: load_from_dir with missing dir/file does not raise."""
    try:
        from memory.situation_memory import FinancialSituationMemory
    except ImportError as e:
        pytest.skip(f"Situation memory not available: {e}")

    mem = FinancialSituationMemory("test")
    mem.load_from_dir("/nonexistent/path/12345")
    assert mem.get_memories("query", n_matches=1) == []


def test_stage_3_1() -> None:
    """Stage 3.1: PlannerAgent (Slice 3 subset)."""
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.planner_agent import PlannerAgent, TaskStep
    except ImportError as e:
        pytest.skip(f"Stage 3.1 deps not available: {e}")

    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    planner = PlannerAgent("planner", bus)

    steps = planner.decompose_task("What is fund X?")
    assert isinstance(steps, list)
    assert len(steps) >= 1
    step = steps[0]
    assert isinstance(step, TaskStep)
    assert step.agent in ("librarian", "websearcher", "analyst")
    assert isinstance(step.params, dict)

    msg = planner.create_research_request("What is fund X?", step)
    assert isinstance(msg, ACLMessage)
    assert msg.performative == Performative.REQUEST
    assert msg.receiver == step.agent
    assert msg.sender == "planner"
    assert isinstance(msg.content, dict)

    bus.register_agent("librarian")
    start = ACLMessage(
        performative=Performative.REQUEST,
        sender="api",
        receiver="planner",
        content={"query": "What is fund X?", "conversation_id": str(uuid.uuid4())},
    )
    bus.send(start)
    received = bus.receive("planner", timeout=0.5)
    assert received is not None
    planner.handle_message(received)
    request_to_lib = bus.receive("librarian", timeout=0.5)
    assert request_to_lib is not None
    assert request_to_lib.performative == Performative.REQUEST


def test_stage_3_2() -> None:
    """Stage 3.2: LibrarianAgent (Slice 3 subset) — file_tool.read_file."""
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.librarian_agent import LibrarianAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 3.2 deps not available: {e}")

    server = MCPServer()
    server.register_tool(
        "file_tool.read_file",
        lambda p: (
            {"content": "hello from file", "path": p["path"]}
            if "path" in p
            else {"error": "Missing path"}
        ),
    )
    client = MCPClient(server)
    bus = InMemoryMessageBus()
    bus.register_agent("librarian")
    bus.register_agent("planner")
    librarian = LibrarianAgent("librarian", bus, mcp_client=client)

    cid = str(uuid.uuid4())
    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "read file", "path": "/tmp/test.txt"},
        conversation_id=cid,
        reply_to="planner",
    )
    bus.send(req)
    librarian.handle_message(req)
    reply = bus.receive("planner", timeout=0.5)
    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "librarian"
    assert isinstance(reply.content, dict)
    assert (
        "content" in reply.content
        or "result" in reply.content
        or "data" in reply.content
    )
    if "content" in reply.content:
        assert reply.content["content"] == "hello from file"


def test_stage_3_3() -> None:
    """Stage 3.3: ResponderAgent (Slice 3 subset) — stub registers reply and broadcasts STOP."""
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.conversation_manager import ConversationManager
        from a2a.message_bus import InMemoryMessageBus
        from agents.responder_agent import ResponderAgent
    except ImportError as e:
        pytest.skip(f"Stage 3.3 deps not available: {e}")

    bus = InMemoryMessageBus()
    bus.register_agent("responder")
    bus.register_agent("planner")
    bus.register_agent("observer")

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("MEMORY_STORE_PATH")
        os.environ["MEMORY_STORE_PATH"] = tmp
        try:
            mgr = ConversationManager(bus)
            cid = mgr.create_conversation("u1", "Query")
            responder = ResponderAgent("responder", bus, conversation_manager=mgr)

            inform = ACLMessage(
                performative=Performative.INFORM,
                sender="planner",
                receiver="responder",
                content={
                    "final_response": "Here is your answer.",
                    "conversation_id": cid,
                },
                conversation_id=cid,
            )
            responder.handle_message(inform)

            state = mgr.get_conversation(cid)
            assert state is not None
            assert state.final_response == "Here is your answer."
            assert state.status == "complete"

            stop_msg = bus.receive("observer", timeout=0.5)
            assert stop_msg is not None
            assert stop_msg.performative == Performative.STOP
        finally:
            if prev is not None:
                os.environ["MEMORY_STORE_PATH"] = prev
            else:
                os.environ.pop("MEMORY_STORE_PATH", None)


def test_stage_4_1() -> None:
    """Stage 4.1: vector_tool (Milvus)."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    # Use mock when MILVUS_URI not set
    env_milvus = os.environ.pop("MILVUS_URI", None)
    try:
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        result = client.call_tool(
            "vector_tool.search", {"query": "test query", "top_k": 3}
        )
        assert isinstance(result, dict)
        assert "error" not in result
        docs = result.get("documents", result)
        assert isinstance(docs, list)
        assert len(docs) >= 1
        assert "content" in docs[0] or "score" in docs[0]
    finally:
        if env_milvus is not None:
            os.environ["MILVUS_URI"] = env_milvus


def test_stage_4_2() -> None:
    """Stage 4.2: kg_tool (Neo4j)."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    env_neo4j = os.environ.pop("NEO4J_URI", None)
    try:
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        result = client.call_tool("kg_tool.get_relations", {"entity": "FUND1"})
        assert isinstance(result, dict)
        assert "error" not in result
        assert "nodes" in result
        result2 = client.call_tool(
            "kg_tool.query_graph", {"cypher": "MATCH (n) RETURN n", "params": {}}
        )
        assert isinstance(result2, dict)
        assert "error" not in result2
    finally:
        if env_neo4j is not None:
            os.environ["NEO4J_URI"] = env_neo4j


def test_stage_4_3() -> None:
    """Stage 4.3: sql_tool (PostgreSQL)."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    env_db = os.environ.pop("DATABASE_URL", None)
    try:
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        result = client.call_tool(
            "sql_tool.run_query", {"query": "SELECT 1", "params": {}}
        )
        assert isinstance(result, dict)
        assert "error" not in result
        assert "rows" in result
    finally:
        if env_db is not None:
            os.environ["DATABASE_URL"] = env_db


def test_stage_5_1() -> None:
    """Stage 5.1: market_tool (mocked to avoid network/yfinance)."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    stub = {"content": "mock fundamentals", "timestamp": "2024-01-01T00:00:00Z"}
    with patch("mcp.tools.market_tool._route_fundamentals", return_value=stub):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        result = client.call_tool("market_tool.get_fundamentals", {"ticker": "AAPL"})
    assert isinstance(result, dict)
    assert "error" in result or "content" in result
    if "error" not in result:
        assert "timestamp" in result or "content" in result


def test_stage_5_2() -> None:
    """Stage 5.2: analyst_tool (mocked to avoid network/yfinance)."""
    try:
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    stub = {"content": "mock indicators", "timestamp": "2024-01-01T00:00:00Z"}
    with patch("mcp.tools.analyst_tool._route_indicators", return_value=stub):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        result = client.call_tool(
            "analyst_tool.get_indicators",
            {
                "symbol": "AAPL",
                "indicator": "sma_50",
                "as_of_date": "2024-01-15",
                "look_back_days": 10,
            },
        )
    assert isinstance(result, dict)
    assert "error" in result or "content" in result
    if "error" not in result:
        assert "timestamp" in result or "content" in result


def test_stage_5_3() -> None:
    """Stage 5.3: WebSearcherAgent (market tools mocked to avoid network/yfinance)."""
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.websearch_agent import WebSearcherAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 5.3 deps not available: {e}")

    stub = {"content": "mock", "timestamp": "2024-01-01T00:00:00Z"}
    with patch("mcp.tools.market_tool._route_fundamentals", return_value=stub), patch(
        "mcp.tools.market_tool._route_news", return_value=stub
    ), patch("mcp.tools.market_tool._route_global_news", return_value=stub):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        bus = InMemoryMessageBus()
        bus.register_agent("websearcher")
        bus.register_agent("planner")
        agent = WebSearcherAgent("websearcher", bus, mcp_client=client)
        cid = str(uuid.uuid4())
        req = ACLMessage(
            performative=Performative.REQUEST,
            sender="planner",
            receiver="websearcher",
            content={"query": "AAPL", "fund": "AAPL"},
            conversation_id=cid,
            reply_to="planner",
        )
        bus.send(req)
        agent.handle_message(req)
        reply = bus.receive("planner", timeout=2.0)
    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "websearcher"
    assert isinstance(reply.content, dict)
    assert "market_data" in reply.content or "sentiment" in reply.content


def test_stage_5_4() -> None:
    """Stage 5.4: AnalystAgent (analyst_tool mocked to avoid network/yfinance)."""
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.analyst_agent import AnalystAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 5.4 deps not available: {e}")

    stub = {"content": "mock indicators", "timestamp": "2024-01-01T00:00:00Z"}
    with patch("mcp.tools.analyst_tool._route_indicators", return_value=stub):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        bus = InMemoryMessageBus()
        bus.register_agent("analyst")
        bus.register_agent("planner")
        agent = AnalystAgent("analyst", bus, mcp_client=client)
        cid = str(uuid.uuid4())
        req = ACLMessage(
            performative=Performative.REQUEST,
            sender="planner",
            receiver="analyst",
            content={"query": "analyze", "structured_data": {}, "market_data": {}},
            conversation_id=cid,
            reply_to="planner",
        )
        bus.send(req)
        agent.handle_message(req)
        reply = bus.receive("planner", timeout=2.0)
    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "analyst"
    assert isinstance(reply.content, dict)
    assert "analysis" in reply.content


def test_websearcher_news_searcher() -> None:
    """News Searcher: WebSearcher returns news and citations (per docs/news-searcher-design.md)."""
    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.websearch_agent import WebSearcherAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"News Searcher deps not available: {e}")

    rss_stub = {
        "items": [
            {"title": "Nvidia rally lifts semiconductor ETFs", "link": "https://example.com/1", "source": "Yahoo Finance", "date": "2026-03-10"},
            {"title": "AI ETFs see strong inflows", "link": "https://example.com/2", "source": "Bloomberg", "date": "2026-03-09"},
        ],
        "timestamp": "2026-03-10T08:00:00Z",
    }
    market_stub = {"content": "mock", "timestamp": "2026-03-10T08:00:00Z"}
    with patch("mcp.tools.news_tool.search_rss", return_value=rss_stub), patch(
        "mcp.tools.market_tool._route_fundamentals", return_value=market_stub
    ), patch("mcp.tools.market_tool._route_news", return_value=market_stub), patch(
        "mcp.tools.market_tool._route_global_news", return_value=market_stub
    ):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        bus = InMemoryMessageBus()
        bus.register_agent("websearcher")
        bus.register_agent("planner")
        agent = WebSearcherAgent("websearcher", bus, mcp_client=client)
        cid = str(uuid.uuid4())
        req = ACLMessage(
            performative=Performative.REQUEST,
            sender="planner",
            receiver="websearcher",
            content={"query": "NVDA ETF news", "fund": "NVDA"},
            conversation_id=cid,
            reply_to="planner",
        )
        bus.send(req)
        agent.handle_message(req)
        reply = bus.receive("planner", timeout=5.0)

    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "websearcher"
    content = reply.content
    assert isinstance(content, dict)
    assert "news" in content
    assert "citations" in content
    news = content["news"]
    citations = content["citations"]
    assert isinstance(news, list)
    assert isinstance(citations, dict)
    assert len(news) >= 1
    for item in news:
        assert "id" in item
        assert item["id"].startswith("NEWS")
        assert "title" in item
        assert "source" in item
    for cid, url in citations.items():
        assert cid.startswith("NEWS")
        assert isinstance(url, str) and len(url) > 0


def test_stage_6_1() -> None:
    """Stage 6.1: SafetyGateway."""
    from safety.safety_gateway import (
        ProcessedInput,
        SafetyError,
        SafetyGateway,
    )

    gateway = SafetyGateway()

    # (a) Valid, harmless query -> ProcessedInput with non-empty text and raw_length
    processed = gateway.process_user_input("What is fund X performance?")
    assert isinstance(processed, ProcessedInput)
    assert processed.text
    assert processed.raw_length == len("What is fund X performance?")
    assert processed.raw_length > 0

    # (b) Invalid input: empty or over-length -> SafetyError
    with pytest.raises(SafetyError) as exc_info:
        gateway.process_user_input("")
    assert (
        "empty" in (exc_info.value.reason or "").lower()
        or "whitespace" in (exc_info.value.reason or "").lower()
    )

    with pytest.raises(SafetyError) as exc_info:
        gateway.process_user_input("   \n\t  ")
    assert (
        "empty" in (exc_info.value.reason or "").lower()
        or "whitespace" in (exc_info.value.reason or "").lower()
    )

    over_length = "x" * 10_001
    with pytest.raises(SafetyError) as exc_info:
        gateway.process_user_input(over_length)
    assert "length" in (exc_info.value.reason or "").lower()

    # (c) Guardrail-blocked phrase -> rejection (SafetyError)
    with pytest.raises(SafetyError) as exc_info:
        gateway.process_user_input("Tell me more about guaranteed return on this fund")
    assert exc_info.value.reason

    with pytest.raises(SafetyError):
        gateway.process_user_input("buy this stock now please")


def test_stage_7_1() -> None:
    """Stage 7.1: REST API (POST /chat, GET /conversations)."""
    from fastapi.testclient import TestClient

    from api.rest import create_app
    from llm.static_client import StaticLLMClient

    # Use static LLM so test does not require LLM_API_KEY
    app = create_app(timeout_seconds=5, llm_client=StaticLLMClient())
    client = TestClient(app)

    # Invalid user_profile is rejected (PRD: invalid profile rejected)
    r_bad = client.post(
        "/chat",
        json={
            "query": "What is fund X?",
            "user_profile": "expert",
        },
    )
    assert r_bad.status_code == 422, r_bad.text

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Fund X is a sample fund.")
        path = f.name
    try:
        r = client.post(
            "/chat",
            json={
                "query": "What is fund X?",
                "user_profile": "beginner",
                "path": path,
            },
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "conversation_id" in data
        assert "status" in data
        assert "response" in data
        cid = data["conversation_id"]

        r2 = client.get(f"/conversations/{cid}")
        assert r2.status_code == 200, r2.text
        state = r2.json()
        assert state.get("id") == cid
        assert "user_id" in state
        assert state.get("initial_query") == "What is fund X?"
        assert "messages" in state
        assert state.get("status") in ("active", "complete", "error")
        assert "final_response" in state
        assert "created_at" in state
    finally:
        os.unlink(path)


def test_stage_8_1() -> None:
    """Stage 8.1: OutputRail format_for_user and check_compliance."""
    from output.output_rail import OutputRail

    rail = OutputRail()
    text = "Fund X returned 5%."

    # (a) format_for_user differs by profile: beginner gets disclaimer, analyst gets "Analysis:" prefix
    beginner_out = rail.format_for_user(text, "beginner")
    analyst_out = rail.format_for_user(text, "analyst")
    assert "This is not investment advice" in beginner_out
    assert beginner_out != analyst_out
    assert analyst_out.startswith("Analysis:")
    assert "Fund X returned 5%" in analyst_out

    # (b) check_compliance: safe text passes; buy/sell advice fails
    assert rail.check_compliance("Fund X is stable.").passed is True
    comp = rail.check_compliance("Buy this stock now.")
    assert comp.passed is False
    assert comp.reason is not None


def test_stage_9_1() -> None:
    """Stage 9.1: WebSocket /ws — same flow as POST /chat; one event then close."""
    from fastapi.testclient import TestClient

    from api.rest import create_app
    from llm.static_client import StaticLLMClient

    app = create_app(timeout_seconds=5, llm_client=StaticLLMClient())
    client = TestClient(app)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("What is fund X? (stage 9.1)")
        path = f.name
    try:
        with client.websocket_connect("/ws") as ws:
            ws.send_json(
                {
                    "query": "What is fund X?",
                    "user_profile": "beginner",
                    "path": path,
                }
            )
            data = ws.receive_json()
            while data.get("event") == "flow":
                data = ws.receive_json()
        assert "event" in data
        assert data["event"] in ("response", "timeout", "error")
        if data["event"] == "response":
            assert "conversation_id" in data
            assert "response" in data
        elif data["event"] == "timeout":
            assert "conversation_id" in data
            assert data.get("response") is None
        else:
            assert "detail" in data
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_stage_10_1() -> None:
    """Stage 10.1: E2E smoke — main.py --e2e-once completes one conversation and exits 0."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "PYTHONPATH": root}
    result = subprocess.run(
        [sys.executable, "main.py", "--e2e-once"],
        cwd=root,
        env=env,
        timeout=60,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"E2E exited {result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
    )


def test_stage_10_2_llm_static_mock() -> None:
    """Stage 10.2: get_llm_client requires LLM_API_KEY; Planner with StaticLLMClient returns runnable steps."""
    from config.config import Config, load_config
    from llm.factory import get_llm_client
    from llm.static_client import StaticLLMClient

    cfg = load_config()
    cfg_no_key = Config(**{**vars(cfg), "llm_api_key": None})
    with pytest.raises((ValueError, ImportError)):
        get_llm_client(cfg_no_key)

    # Planner with StaticLLMClient (e.g. for tests/E2E) still produces runnable steps
    client = StaticLLMClient()
    steps = client.decompose_to_steps("What is fund X?")
    assert isinstance(steps, list)
    assert len(steps) == 3
    agents = [s["agent"] for s in steps]
    assert agents == ["librarian", "websearcher", "analyst"]
    for s in steps:
        assert "query" in (s.get("params") or {})
        assert (s.get("params") or {})["query"] == "What is fund X?"

    from a2a.message_bus import InMemoryMessageBus
    from agents.planner_agent import PlannerAgent, TaskStep

    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    planner = PlannerAgent("planner", bus, llm_client=client)
    plan_steps = planner.decompose_task("What is fund X?")
    assert len(plan_steps) == 3
    assert all(isinstance(s, TaskStep) for s in plan_steps)
    assert [s.agent for s in plan_steps] == ["librarian", "websearcher", "analyst"]


def test_stage_10_2_planner_uses_prompts_module() -> None:
    """Stage 10.2: LiveLLMClient uses PLANNER_DECOMPOSE from llm.prompts as system message."""
    from unittest.mock import MagicMock, patch

    from llm.live_client import LiveLLMClient
    from llm.prompts import PLANNER_DECOMPOSE

    mock_create = MagicMock()
    mock_create.return_value.choices = [
        MagicMock(
            message=MagicMock(
                content='[{"agent":"librarian","action":"read_file","params":{"query":"q"}}]'
            )
        )
    ]
    mock_openai_instance = MagicMock()
    mock_openai_instance.chat.completions.create = mock_create
    with patch.object(LiveLLMClient, "_get_client", return_value=mock_openai_instance):
        client = LiveLLMClient(api_key="test-key", model="gpt-4o-mini")
        client.decompose_to_steps("q")
    assert mock_create.called
    call_kw = mock_create.call_args[1]
    messages = call_kw.get("messages", [])
    assert len(messages) >= 1
    system_content = messages[0].get("content")
    assert system_content == PLANNER_DECOMPOSE


def test_stage_10_2_static_client_complete_passthrough() -> None:
    """Stage 10.2: StaticLLMClient.complete returns user_content unchanged."""
    from llm.static_client import StaticLLMClient

    client = StaticLLMClient()
    out = client.complete("system prompt", "user content")
    assert out == "user content"


def test_stage_10_2_responder_llm_prompt() -> None:
    """Stage 10.2: ResponderAgent with llm_client calls complete with RESPONDER_SYSTEM and user_profile."""
    from unittest.mock import MagicMock

    from llm.prompts import RESPONDER_SYSTEM

    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="Formatted answer.")

    from a2a.acl_message import ACLMessage, Performative
    from a2a.message_bus import InMemoryMessageBus
    from agents.responder_agent import ResponderAgent
    from output.output_rail import OutputRail

    bus = InMemoryMessageBus()
    bus.register_agent("responder")
    mgr = MagicMock()
    responder = ResponderAgent(
        "responder",
        bus,
        output_rail=OutputRail(),
        conversation_manager=mgr,
        llm_client=mock_llm,
    )
    responder.handle_message(
        ACLMessage(
            performative=Performative.INFORM,
            sender="planner",
            receiver="responder",
            content={
                "final_response": "Librarian: data. Analyst: analysis.",
                "conversation_id": "cid-1",
                "user_profile": "long_term",
            },
            conversation_id="cid-1",
        )
    )
    assert mock_llm.complete.called
    call_args = mock_llm.complete.call_args[0]
    assert len(call_args) >= 2
    system_prompt, user_content = call_args[0], call_args[1]
    assert system_prompt == RESPONDER_SYSTEM
    assert "long_term" in user_content
    assert "Librarian: data" in user_content


def test_stage_10_2_librarian_llm_prompt() -> None:
    """Stage 10.2: LibrarianAgent with llm_client calls complete with LIBRARIAN_SYSTEM (after tool selection or fallback)."""
    from unittest.mock import MagicMock

    from llm.prompts import LIBRARIAN_SYSTEM

    mock_llm = MagicMock()
    mock_llm.select_tools = MagicMock(return_value=[])  # fall back to content-key dispatch
    mock_llm.complete = MagicMock(return_value="Brief summary of docs and graph.")

    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.librarian_agent import LibrarianAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 10.2 librarian deps not available: {e}")

    server = MCPServer()
    server.register_tool(
        "file_tool.read_file",
        lambda p: {"content": "file content", "path": p.get("path", "")},
    )
    client = MCPClient(server)
    bus = InMemoryMessageBus()
    bus.register_agent("librarian")
    bus.register_agent("planner")
    librarian = LibrarianAgent("librarian", bus, mcp_client=client, llm_client=mock_llm)
    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "fund X", "path": "/tmp/x.txt"},
        conversation_id="cid-lib",
        reply_to="planner",
    )
    bus.send(req)
    librarian.handle_message(req)
    assert mock_llm.complete.called
    call_args = mock_llm.complete.call_args[0]
    assert len(call_args) >= 2
    assert call_args[0] == LIBRARIAN_SYSTEM
    assert "fund X" in call_args[1] or "/tmp/x.txt" in call_args[1]


def test_stage_10_2_websearcher_llm_prompt() -> None:
    """Stage 10.2: WebSearcherAgent with llm_client calls complete with WEBSEARCHER_SYSTEM (after tool selection or fallback)."""
    from unittest.mock import MagicMock

    from llm.prompts import WEBSEARCHER_SYSTEM

    mock_llm = MagicMock()
    mock_llm.select_tools = MagicMock(return_value=[])  # fall back to content-based dispatch
    mock_llm.complete = MagicMock(return_value="Market and sentiment brief.")

    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.websearch_agent import WebSearcherAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 10.2 websearcher deps not available: {e}")

    stub = {"content": "mock", "timestamp": "2024-01-01T00:00:00Z"}
    with patch("mcp.tools.market_tool._route_fundamentals", return_value=stub), patch(
        "mcp.tools.market_tool._route_news", return_value=stub
    ), patch("mcp.tools.market_tool._route_global_news", return_value=stub):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        bus = InMemoryMessageBus()
        bus.register_agent("websearcher")
        bus.register_agent("planner")
        agent = WebSearcherAgent("websearcher", bus, mcp_client=client, llm_client=mock_llm)
        req = ACLMessage(
            performative=Performative.REQUEST,
            sender="planner",
            receiver="websearcher",
            content={"query": "AAPL", "fund": "AAPL"},
            conversation_id="cid-ws",
            reply_to="planner",
        )
        bus.send(req)
        agent.handle_message(req)
    assert mock_llm.complete.called
    call_args = mock_llm.complete.call_args[0]
    assert len(call_args) >= 2
    assert call_args[0] == WEBSEARCHER_SYSTEM
    assert "AAPL" in call_args[1]


def test_stage_10_2_analyst_llm_prompt() -> None:
    """Stage 10.2: AnalystAgent with llm_client calls complete with ANALYST_SYSTEM (after tool selection or fallback)."""
    from unittest.mock import MagicMock

    from llm.prompts import ANALYST_SYSTEM

    mock_llm = MagicMock()
    mock_llm.select_tools = MagicMock(return_value=[])  # fall back to content-based flow
    mock_llm.complete = MagicMock(return_value="Analysis summary with confidence.")

    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.analyst_agent import AnalystAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 10.2 analyst deps not available: {e}")

    stub = {"content": "mock indicators", "timestamp": "2024-01-01T00:00:00Z"}
    with patch("mcp.tools.analyst_tool._route_indicators", return_value=stub):
        server = MCPServer()
        server.register_default_tools()
        client = MCPClient(server)
        bus = InMemoryMessageBus()
        bus.register_agent("analyst")
        bus.register_agent("planner")
        agent = AnalystAgent("analyst", bus, mcp_client=client, llm_client=mock_llm)
        req = ACLMessage(
            performative=Performative.REQUEST,
            sender="planner",
            receiver="analyst",
            content={
                "query": "analyze",
                "structured_data": {"documents": []},
                "market_data": {"price": 100},
            },
            conversation_id="cid-an",
            reply_to="planner",
        )
        bus.send(req)
        agent.handle_message(req)
    assert mock_llm.complete.called
    call_args = mock_llm.complete.call_args[0]
    assert len(call_args) >= 2
    assert call_args[0] == ANALYST_SYSTEM
    assert "structured_data" in call_args[1] or "market_data" in call_args[1]


def test_stage_10_2_static_client_select_tools_returns_empty() -> None:
    """Stage 10.2: StaticLLMClient.select_tools returns [] so specialists fall back to content-key dispatch."""
    from llm.static_client import StaticLLMClient

    client = StaticLLMClient()
    tool_calls = client.select_tools("system", "user", "tool list")
    assert tool_calls == []


def test_stage_10_2_planner_sends_only_to_chosen_agents_with_decomposed_query() -> None:
    """Planner sends REQUEST only to agents in decomposed steps; each REQUEST content includes that step's query."""
    from a2a.acl_message import ACLMessage, Performative
    from a2a.message_bus import InMemoryMessageBus
    from agents.planner_agent import PlannerAgent, TaskStep
    from llm.static_client import StaticLLMClient

    # Custom steps: only librarian and websearcher (no analyst). StaticLLMClient injects user query into params.
    custom_steps = [
        {"agent": "librarian", "params": {"query": "Find NVDA fund facts"}},
        {"agent": "websearcher", "params": {"query": "NVDA stock price and news"}},
    ]
    client = StaticLLMClient(steps=custom_steps)
    bus = InMemoryMessageBus()
    for name in ("planner", "librarian", "websearcher", "analyst"):
        bus.register_agent(name)
    planner = PlannerAgent("planner", bus, llm_client=client)
    user_query = "What about NVDA?"
    steps = planner.decompose_task(user_query)
    assert len(steps) == 2
    assert [s.agent for s in steps] == ["librarian", "websearcher"]
    # StaticLLMClient overwrites params["query"] with user query
    assert steps[0].params.get("query") == user_query
    assert steps[1].params.get("query") == user_query

    msg_lib = planner.create_research_request(user_query, steps[0])
    assert msg_lib.receiver == "librarian"
    assert msg_lib.content.get("query") == user_query
    msg_ws = planner.create_research_request(user_query, steps[1])
    assert msg_ws.receiver == "websearcher"
    assert msg_ws.content.get("query") == user_query


def test_stage_10_2_live_client_parse_steps_per_agent_query() -> None:
    """LiveLLMClient._parse_steps uses per-step query from params.query or top-level query; only setdefaults user query when step has neither."""
    pytest.importorskip("openai")
    from llm.live_client import LiveLLMClient

    client = LiveLLMClient(api_key="test-key", model="gpt-4o-mini")
    user_query = "Should I invest in AAPL?"

    # Two agents with params.query: each step keeps its own query
    text1 = '[{"agent":"librarian","action":"read_file","params":{"query":"AAPL fundamentals and holdings"}},{"agent":"analyst","action":"analyze","params":{"query":"Risk and return for AAPL"}}]'
    steps1 = client._parse_steps(text1, user_query)
    assert steps1 is not None
    assert len(steps1) == 2
    assert steps1[0]["params"]["query"] == "AAPL fundamentals and holdings"
    assert steps1[1]["params"]["query"] == "Risk and return for AAPL"

    # Top-level "query" per step (no params.query): should be used
    text2 = '[{"agent":"websearcher","action":"fetch_market","query":"AAPL latest price and news"}]'
    steps2 = client._parse_steps(text2, user_query)
    assert steps2 is not None
    assert len(steps2) == 1
    assert steps2[0]["params"]["query"] == "AAPL latest price and news"

    # Parse failure: returns None
    assert client._parse_steps("not json", user_query) is None
    assert client._parse_steps("{}", user_query) is None
    assert client._parse_steps("null", user_query) is None

    # Valid empty array: returns []
    steps_empty = client._parse_steps("[]", user_query)
    assert steps_empty is not None
    assert steps_empty == []


def test_stage_10_2_planner_empty_list_single_analyst_fallback() -> None:
    """When LLM returns empty list, planner returns single analyst step so pipeline does not stall."""
    from unittest.mock import MagicMock

    from a2a.message_bus import InMemoryMessageBus
    from agents.planner_agent import PlannerAgent, TaskStep

    mock_llm = MagicMock()
    mock_llm.decompose_to_steps = MagicMock(return_value=[])
    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    planner = PlannerAgent("planner", bus, llm_client=mock_llm)
    steps = planner.decompose_task("What is NVDA?")
    assert len(steps) == 1
    assert steps[0].agent == "analyst"
    assert steps[0].params.get("query") == "What is NVDA?"


def test_planner_decompose_sample_output() -> None:
    """Run planner task decomposition with live LLM and print sample output (run with -s to see). Skips if LLM_API_KEY unset or openai not installed."""
    pytest.importorskip("openai")
    from config.config import load_config
    from llm.factory import get_llm_client

    cfg = load_config()
    if not (cfg.llm_api_key and cfg.llm_api_key.strip()):
        pytest.skip("LLM_API_KEY not set")
    try:
        llm_client = get_llm_client(cfg)
    except (ValueError, ImportError):
        pytest.skip("Live LLM not available")

    from a2a.message_bus import InMemoryMessageBus
    from agents.planner_agent import PlannerAgent, TaskStep

    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    planner = PlannerAgent("planner", bus, llm_client=llm_client)
    user_query = "Should I invest in AAPL given the latest news and fundamentals?"
    steps = planner.decompose_task(user_query)

    assert len(steps) >= 1
    for step in steps:
        assert isinstance(step, TaskStep)
        assert step.agent in ("librarian", "websearcher", "analyst")
        assert "query" in step.params

    print("\n--- Task decomposition sample output (live LLM) ---")
    print(f"User query: {user_query!r}")
    for i, step in enumerate(steps, 1):
        q = step.params.get("query", "")
        print(f"Step {i}: agent={step.agent} query={q!r}")
    print("---\n")


def test_stage_10_2_librarian_tool_selection_when_llm_returns_tool_calls() -> None:
    """Librarian with llm_client uses tool selection when select_tools returns non-empty list."""
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.select_tools = MagicMock(
        return_value=[
            {"tool": "file_tool.read_file", "payload": {"path": "/data/fund.txt"}},
            {"tool": "vector_tool.search", "payload": {"query": "NVDA", "top_k": 3}},
        ]
    )
    mock_llm.complete = MagicMock(return_value="Summary of file and vector results.")

    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.librarian_agent import LibrarianAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 10.2 librarian deps not available: {e}")

    server = MCPServer()
    server.register_tool(
        "file_tool.read_file",
        lambda p: {"content": "fund content", "path": p.get("path", "")},
    )
    server.register_tool(
        "vector_tool.search",
        lambda p: {"documents": [{"id": "1", "text": "NVDA doc", "score": 0.9}]},
    )
    client = MCPClient(server)
    bus = InMemoryMessageBus()
    bus.register_agent("librarian")
    bus.register_agent("planner")
    librarian = LibrarianAgent("librarian", bus, mcp_client=client, llm_client=mock_llm)

    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "Get NVDA fund facts and docs"},
        conversation_id="cid-tool",
        reply_to="planner",
    )
    librarian.handle_message(req)

    assert mock_llm.select_tools.called
    reply = bus.receive("planner", timeout=0.5)
    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "librarian"
    assert isinstance(reply.content, dict)
    assert "file" in reply.content or "documents" in reply.content or "content" in reply.content
    assert mock_llm.complete.called


def test_stage_10_2_websearcher_tool_selection_when_llm_returns_tool_calls() -> None:
    """WebSearcher with llm_client runs parallel flow and sends INFORM; may call complete for summary."""
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.complete = MagicMock(return_value="Market and news brief.")

    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.websearch_agent import WebSearcherAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 10.2 websearcher deps not available: {e}")

    server = MCPServer()
    server.register_tool(
        "market_tool.get_fundamentals",
        lambda p: {"content": "P/E 25", "timestamp": "2024-01-01T00:00:00"},
    )
    server.register_tool(
        "market_tool.get_news",
        lambda p: {"content": "AAPL news", "timestamp": "2024-01-01T00:00:00"},
    )
    client = MCPClient(server)
    bus = InMemoryMessageBus()
    bus.register_agent("websearcher")
    bus.register_agent("planner")
    agent = WebSearcherAgent("websearcher", bus, mcp_client=client, llm_client=mock_llm)

    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="websearcher",
        content={"query": "AAPL stock and news"},
        conversation_id="cid-ws-tool",
        reply_to="planner",
    )
    agent.handle_message(req)

    reply = bus.receive("planner", timeout=0.5)
    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "websearcher"
    assert isinstance(reply.content, dict)
    assert "market_data" in reply.content or "sentiment" in reply.content
    # WebSearcher uses parallel flow (no select_tools); may call complete for summary/conflict
    assert mock_llm.complete.called


def test_stage_10_2_analyst_tool_selection_when_llm_returns_tool_calls() -> None:
    """Analyst with llm_client uses tool selection when select_tools returns non-empty list."""
    from unittest.mock import MagicMock

    mock_llm = MagicMock()
    mock_llm.select_tools = MagicMock(
        return_value=[
            {
                "tool": "analyst_tool.get_indicators",
                "payload": {
                    "symbol": "NVDA",
                    "indicator": "rsi",
                    "as_of_date": "2024-12-31",
                    "look_back_days": 30,
                },
            },
        ]
    )
    mock_llm.complete = MagicMock(return_value="RSI analysis summary.")

    try:
        from a2a.acl_message import ACLMessage, Performative
        from a2a.message_bus import InMemoryMessageBus
        from agents.analyst_agent import AnalystAgent
        from mcp.mcp_client import MCPClient
        from openfund_mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"Stage 10.2 analyst deps not available: {e}")

    server = MCPServer()
    server.register_tool(
        "analyst_tool.get_indicators",
        lambda p: {"content": "RSI 55", "timestamp": "2024-12-31T00:00:00"},
    )
    client = MCPClient(server)
    bus = InMemoryMessageBus()
    bus.register_agent("analyst")
    bus.register_agent("planner")
    agent = AnalystAgent("analyst", bus, mcp_client=client, llm_client=mock_llm)

    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="analyst",
        content={"query": "NVDA RSI analysis"},
        conversation_id="cid-an-tool",
        reply_to="planner",
    )
    agent.handle_message(req)

    assert mock_llm.select_tools.called
    reply = bus.receive("planner", timeout=0.5)
    assert reply is not None
    assert reply.performative == Performative.INFORM
    assert reply.sender == "analyst"
    assert isinstance(reply.content, dict)
    assert "analysis" in reply.content
    assert mock_llm.complete.called


# --- Data populate (demo seed): no backends configured ---


def test_data_populate_skips_when_no_backends() -> None:
    """data populate exits 0 and skips each backend when DATABASE_URL, NEO4J_URI, MILVUS_URI are unset."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("DATABASE_URL", "NEO4J_URI", "MILVUS_URI")
    }
    env["PYTHONPATH"] = root
    # Force backends unset so populate skips them even if .env is loaded in subprocess
    env["DATABASE_URL"] = ""
    env["NEO4J_URI"] = ""
    env["MILVUS_URI"] = ""
    result = subprocess.run(
        [sys.executable, "-m", "data", "populate"],
        cwd=root,
        env=env,
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"data populate exited {result.returncode}; stderr={result.stderr!r}"
    )
    out = result.stdout + result.stderr
    assert "skipping PostgreSQL" in out or "DATABASE_URL" in out
    assert "skipping Neo4j" in out or "NEO4J_URI" in out
    assert "skipping Milvus" in out or "MILVUS_URI" in out


# --- Stage 10.3: tool call filtering ---

def test_stage_10_3_filter_drops_disallowed_tools():
    """filter_tool_calls_to_allowed removes tool names not in the allowed set."""
    from llm.tool_descriptions import (
        ANALYST_ALLOWED_TOOL_NAMES,
        LIBRARIAN_ALLOWED_TOOL_NAMES,
        WEBSEARCHER_ALLOWED_TOOL_NAMES,
        filter_tool_calls_to_allowed,
    )

    # All three allowed sets are non-empty and disjoint in the right ways
    assert "vector_tool.search" in LIBRARIAN_ALLOWED_TOOL_NAMES
    assert "market_tool.get_fundamentals" in WEBSEARCHER_ALLOWED_TOOL_NAMES
    assert "analyst_tool.get_indicators" in ANALYST_ALLOWED_TOOL_NAMES

    # Cross-agent hallucination is rejected
    assert "market_tool.get_fundamentals" not in LIBRARIAN_ALLOWED_TOOL_NAMES
    assert "vector_tool.search" not in WEBSEARCHER_ALLOWED_TOOL_NAMES
    assert "vector_tool.search" not in ANALYST_ALLOWED_TOOL_NAMES

    tool_calls = [
        {"tool": "vector_tool.search", "payload": {"query": "Q"}},
        {"tool": "market_tool.get_fundamentals", "payload": {"ticker": "AAPL"}},  # not librarian
        {"tool_name": "sql_tool.run_query", "payload": {"query": "SELECT 1"}},
    ]
    filtered = filter_tool_calls_to_allowed(tool_calls, LIBRARIAN_ALLOWED_TOOL_NAMES)
    names = [tc.get("tool") or tc.get("tool_name") for tc in filtered]
    assert "vector_tool.search" in names
    assert "sql_tool.run_query" in names
    assert "market_tool.get_fundamentals" not in names


def test_stage_10_3_filter_allows_all_when_all_valid():
    """filter_tool_calls_to_allowed passes through every call when all are in allowed set."""
    from llm.tool_descriptions import WEBSEARCHER_ALLOWED_TOOL_NAMES, filter_tool_calls_to_allowed

    tool_calls = [
        {"tool": "market_tool.get_fundamentals", "payload": {"ticker": "TSLA"}},
        {"tool": "market_tool.get_news", "payload": {"symbol": "TSLA", "limit": 3}},
    ]
    filtered = filter_tool_calls_to_allowed(tool_calls, WEBSEARCHER_ALLOWED_TOOL_NAMES)
    assert len(filtered) == 2


def test_stage_10_3_filter_empty_list():
    """filter_tool_calls_to_allowed returns [] when no tool calls are provided."""
    from llm.tool_descriptions import ANALYST_ALLOWED_TOOL_NAMES, filter_tool_calls_to_allowed

    assert filter_tool_calls_to_allowed([], ANALYST_ALLOWED_TOOL_NAMES) == []


# --- Stage 10.4: tool call normalization ---

def test_stage_10_4_normalize_mixed_tool_and_tool_name():
    """normalize_tool_calls outputs only 'tool' key; accepts both 'tool' and 'tool_name'."""
    from llm.tool_descriptions import normalize_tool_calls

    raw = [
        {"tool": "vector_tool.search", "payload": {"query": "Q"}},
        {"tool_name": "sql_tool.run_query", "payload": {"query": "SELECT 1"}},
    ]
    out = normalize_tool_calls(raw)
    assert len(out) == 2
    assert all("tool" in tc and "payload" in tc and "tool_name" not in tc for tc in out)
    assert out[0]["tool"] == "vector_tool.search"
    assert out[0]["payload"] == {"query": "Q"}
    assert out[1]["tool"] == "sql_tool.run_query"
    assert out[1]["payload"] == {"query": "SELECT 1"}


def test_stage_10_4_normalize_skips_non_dict_and_invalid_tool():
    """normalize_tool_calls skips non-dict items, non-string tool, empty tool."""
    from llm.tool_descriptions import normalize_tool_calls

    raw = [
        {"tool": "a_tool.foo", "payload": {}},
        "not a dict",
        {"tool": "", "payload": {}},
        {"tool": "  ", "payload": {}},
        {"tool": 123, "payload": {}},
        {"tool_name": None, "payload": {}},
    ]
    out = normalize_tool_calls(raw)
    assert len(out) == 1
    assert out[0]["tool"] == "a_tool.foo"


def test_stage_10_4_normalize_payload_default_and_copy():
    """normalize_tool_calls uses {} for missing/non-dict payload; payload is shallow copy."""
    from llm.tool_descriptions import normalize_tool_calls

    raw = [
        {"tool": "x.y", "payload": {"a": 1}},
        {"tool": "z.w"},  # no payload
        {"tool": "p.q", "payload": "not a dict"},
    ]
    out = normalize_tool_calls(raw)
    assert len(out) == 3
    assert out[0]["payload"] == {"a": 1}
    assert out[0]["payload"] is not raw[0]["payload"]  # shallow copy
    assert out[1]["payload"] == {}
    assert out[2]["payload"] == {}


def test_stage_10_4_normalize_empty_list():
    """normalize_tool_calls returns [] for empty input."""
    from llm.tool_descriptions import normalize_tool_calls

    assert normalize_tool_calls([]) == []
