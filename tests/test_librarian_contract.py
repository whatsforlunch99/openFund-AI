"""Librarian contract tests for roles_and_responsibilities schema."""

from unittest.mock import MagicMock

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import InMemoryMessageBus
from agents.librarian_agent import LibrarianAgent


def test_librarian_contract_adds_key_facts_evidence_confidence_and_citations() -> None:
    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    lib = LibrarianAgent("librarian", bus, mcp_client=MagicMock())
    reply = {
        "documents": [
            {"doc_id": "DOC1", "snippet": "NVIDIA has high data-center exposure."},
            {"doc_id": "DOC2", "snippet": "Gross margin has expanded over 4 quarters."},
        ],
        "graph": {"nodes": [{"id": "nvda"}], "edges": []},
        "summary": "Stable facts from internal docs.",
    }
    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "nvda fundamentals"},
        conversation_id="cid-lib-1",
        reply_to="planner",
    )
    lib._send_inform(req, reply, "cid-lib-1")
    out = bus.receive("planner", timeout=0.2)
    assert out is not None
    c = out.content
    assert isinstance(c.get("key_facts"), list)
    assert isinstance(c.get("evidence"), dict)
    assert isinstance(c.get("citations"), list)
    assert c.get("confidence") is not None
    assert "DOC1" in c.get("evidence")


def test_librarian_contract_sets_low_confidence_when_no_documents() -> None:
    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    lib = LibrarianAgent("librarian", bus, mcp_client=MagicMock())
    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "empty docs case"},
        conversation_id="cid-lib-2",
        reply_to="planner",
    )
    lib._send_inform(req, {"documents": [], "graph": {}, "summary": ""}, "cid-lib-2")
    out = bus.receive("planner", timeout=0.2)
    assert out is not None
    c = out.content
    assert c.get("confidence") == 0.0
    assert isinstance(c.get("errors"), list)


def test_librarian_contract_normalizes_string_errors_to_list() -> None:
    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    lib = LibrarianAgent("librarian", bus, mcp_client=MagicMock())
    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "error normalization"},
        conversation_id="cid-lib-3",
        reply_to="planner",
    )
    lib._send_inform(
        req,
        {"documents": [], "graph": {}, "summary": "", "errors": "timeout"},
        "cid-lib-3",
    )
    out = bus.receive("planner", timeout=0.2)
    assert out is not None
    assert out.content.get("errors") == ["timeout"]


def test_librarian_contract_keeps_citations_consistent_with_evidence() -> None:
    bus = InMemoryMessageBus()
    bus.register_agent("planner")
    lib = LibrarianAgent("librarian", bus, mcp_client=MagicMock())
    req = ACLMessage(
        performative=Performative.REQUEST,
        sender="planner",
        receiver="librarian",
        content={"query": "citation mapping"},
        conversation_id="cid-lib-4",
        reply_to="planner",
    )
    lib._send_inform(
        req,
        {
            "documents": [
                {"doc_id": "DOC1", "snippet": ""},
                {"doc_id": "DOC2", "snippet": "valid excerpt"},
            ],
            "graph": {},
        },
        "cid-lib-4",
    )
    out = bus.receive("planner", timeout=0.2)
    assert out is not None
    evidence = out.content.get("evidence") or {}
    citations = out.content.get("citations") or []
    assert set(citations) == set(evidence.keys())
