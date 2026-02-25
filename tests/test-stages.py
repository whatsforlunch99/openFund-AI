"""Stage tests as specified in docs/test_plan.md.

One test function per stage, named test_stage_N_M (e.g. test_stage_1_2), so that:
  pytest tests/test-stages.py -k stage_1_2 -v
matches and runs the correct stage test. No classes; per clarification A2.
"""

import json
import os
import sys
import tempfile
import uuid
from io import StringIO

import pytest

# --- Stage 1.1: Config and minimal main ---


def test_stage_1_1() -> None:
    """Stage 1.1: load_config returns config; main() prints ready and exits 0."""
    from config.config import Config, load_config

    cfg = load_config()
    assert isinstance(cfg, Config)
    assert hasattr(cfg, "milvus_uri")
    assert hasattr(cfg, "analyst_api_url")

    from main import main

    buf = StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        main()
        out = buf.getvalue()
    finally:
        sys.stdout = old_stdout
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
        assert os.path.isdir(
            os.path.dirname(default_path)
        ), "Persistence (D2): dir auto-created for memory/<user_id>/conversations.json"

    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("MEMORY_STORE_PATH")
        os.environ["MEMORY_STORE_PATH"] = tmp
        try:
            mgr3 = ConversationManager(bus)
            try:
                _ = mgr3.create_conversation("u3", "Q")
                custom_path = os.path.join(tmp, "u3", "conversations.json")
                assert os.path.exists(
                    custom_path
                ), "MEMORY_STORE_PATH should configure root dir (D2)"
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
            assert os.path.exists(
                anon_path
            ), "user_id='' must persist to memory/anonymous/conversations.json (D2)"

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
        from mcp.mcp_server import MCPServer
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
        from mcp.mcp_server import MCPServer
    except ImportError as e:
        pytest.skip(f"MCP not available: {e}")

    server = MCPServer()
    server.register_default_tools()
    client = MCPClient(server)

    # market_tool.get_fundamentals
    r = client.call_tool("market_tool.get_fundamentals", {"ticker": "AAPL"})
    assert isinstance(r, dict)
    assert "error" in r or "content" in r
    if "content" in r:
        assert "AAPL" in r["content"] or "Apple" in r["content"].lower()
        assert "timestamp" in r

    # market_tool.get_stock_data (recent range)
    r2 = client.call_tool(
        "market_tool.get_stock_data",
        {"symbol": "AAPL", "start_date": "2024-01-02", "end_date": "2024-01-10"},
    )
    assert isinstance(r2, dict)
    assert "error" in r2 or "content" in r2
    if "content" in r2:
        assert "Open" in r2["content"] or "Close" in r2["content"]
        assert "timestamp" in r2

    # market_tool.get_news (symbol and limit required)
    r3 = client.call_tool("market_tool.get_news", {"symbol": "AAPL", "limit": 3})
    assert isinstance(r3, dict)
    assert "error" in r3 or "content" in r3
    if "content" in r3:
        assert "timestamp" in r3

    # analyst_tool.get_indicators (symbol, indicator, as_of_date, look_back_days)
    r4 = client.call_tool(
        "analyst_tool.get_indicators",
        {
            "symbol": "AAPL",
            "indicator": "sma_50",
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
    pytest.skip("Stage 3.1 not implemented yet")


def test_stage_3_2() -> None:
    """Stage 3.2: LibrarianAgent (Slice 3 subset)."""
    pytest.skip("Stage 3.2 not implemented yet")


def test_stage_3_3() -> None:
    """Stage 3.3: ResponderAgent (Slice 3 subset)."""
    pytest.skip("Stage 3.3 not implemented yet")


def test_stage_4_1() -> None:
    """Stage 4.1: vector_tool (Milvus)."""
    pytest.skip("Stage 4.1 not implemented yet")


def test_stage_4_2() -> None:
    """Stage 4.2: kg_tool (Neo4j)."""
    pytest.skip("Stage 4.2 not implemented yet")


def test_stage_4_3() -> None:
    """Stage 4.3: sql_tool (PostgreSQL)."""
    pytest.skip("Stage 4.3 not implemented yet")


def test_stage_5_1() -> None:
    """Stage 5.1: market_tool."""
    pytest.skip("Stage 5.1 not implemented yet")


def test_stage_5_2() -> None:
    """Stage 5.2: analyst_tool."""
    pytest.skip("Stage 5.2 not implemented yet")


def test_stage_5_3() -> None:
    """Stage 5.3: WebSearcherAgent."""
    pytest.skip("Stage 5.3 not implemented yet")


def test_stage_5_4() -> None:
    """Stage 5.4: AnalystAgent."""
    pytest.skip("Stage 5.4 not implemented yet")


def test_stage_6_1() -> None:
    """Stage 6.1: SafetyGateway."""
    pytest.skip("Stage 6.1 not implemented yet")


def test_stage_7_1() -> None:
    """Stage 7.1: REST API (POST /chat, GET /conversations)."""
    pytest.skip("Stage 7.1 not implemented yet")


def test_stage_8_1() -> None:
    """Stage 8.1: OutputRail."""
    pytest.skip("Stage 8.1 not implemented yet")


def test_stage_9_1() -> None:
    """Stage 9.1: WebSocket."""
    pytest.skip("Stage 9.1 not implemented yet")
