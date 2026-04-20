"""Responder behavior when planner sends partial_insufficient."""

from unittest.mock import MagicMock

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import InMemoryMessageBus

from agents.responder_agent import ResponderAgent


def test_responder_partial_insufficient_preserves_planner_final() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    body = "WebSearcher: price: SPY $400.0. Partial context."
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": body,
            "conversation_id": "c1",
            "insufficient": True,
            "partial_insufficient": True,
        },
        conversation_id="c1",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    assert registered.content["final_response"] == body


def test_responder_insufficient_without_partial_forces_short_message() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": "Should be replaced",
            "conversation_id": "c2",
            "insufficient": True,
        },
        conversation_id="c2",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    assert registered.content["final_response"] == "Insufficient information."


def test_responder_uses_final_response_object_without_recommendation_when_blocked() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": "fallback text",
            "conversation_id": "c3",
            "final_response_object": {
                "summary": "Summary from planner object",
                "evidence": [
                    {
                        "fact": "Fact A",
                        "source": "websearcher",
                        "timestamp": "2026-04-20",
                    }
                ],
                "recommendation": {
                    "allowed": False,
                    "action": "buy",
                    "reason": "blocked by gate",
                },
            },
        },
        conversation_id="c3",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    out = registered.content["final_response"]
    assert "Summary from planner object" in out
    assert "Fact A" in out
    assert "Recommendation:" not in out


def test_responder_uses_final_response_object_with_recommendation_when_allowed() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": "fallback text",
            "conversation_id": "c4",
            "final_response_object": {
                "summary": "Allowed recommendation summary",
                "evidence": [
                    {
                        "fact": "Fact B",
                        "source": "analyst",
                        "timestamp": "2026-04-20",
                    }
                ],
                "recommendation": {
                    "allowed": True,
                    "action": "hold",
                    "reason": "confidence and evidence gate passed",
                },
            },
        },
        conversation_id="c4",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    out = registered.content["final_response"]
    assert "Allowed recommendation summary" in out
    assert "Fact B" in out
    assert "Recommendation: HOLD" in out


def test_responder_insufficient_overrides_final_response_object() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": "fallback text",
            "conversation_id": "c5",
            "insufficient": True,
            "partial_insufficient": False,
            "final_response_object": {
                "summary": "Should never leak when fully insufficient",
                "evidence": [{"fact": "hidden"}],
                "recommendation": {"allowed": True, "action": "buy", "reason": "bad"},
            },
        },
        conversation_id="c5",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    assert registered.content["final_response"] == "Insufficient information."


def test_responder_includes_next_info_needed_when_insufficient() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": "fallback",
            "conversation_id": "c6",
            "insufficient": True,
            "partial_insufficient": False,
            "next_info_needed": ["Specify ticker and exchange", "Provide time horizon"],
        },
        conversation_id="c6",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    out = registered.content["final_response"]
    assert out == "Insufficient information."


def test_responder_renders_risks_and_limitations_from_structured_object() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "final_response": "fallback",
            "conversation_id": "c7",
            "final_response_object": {
                "summary": "Summary text",
                "evidence": [{"fact": "Fact C"}],
                "risks": ["High macro sensitivity"],
                "limitations": ["No verified intraday feed"],
                "recommendation": {"allowed": False, "action": "none", "reason": ""},
            },
        },
        conversation_id="c7",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    out = registered.content["final_response"]
    assert "Risks:" in out
    assert "High macro sensitivity" in out
    assert "Limitations:" in out
    assert "No verified intraday feed" in out


def test_responder_accepts_final_response_object_without_fallback_text() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "conversation_id": "c8",
            "final_response_object": {
                "summary": "Object-only response",
                "evidence": [{"fact": "Fact D"}],
                "recommendation": {"allowed": False},
            },
        },
        conversation_id="c8",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    assert "Object-only response" in registered.content["final_response"]


def test_responder_evidence_line_includes_source_and_timestamp_when_present() -> None:
    bus = InMemoryMessageBus()
    cm = MagicMock()
    r = ResponderAgent("responder", bus, output_rail=None, conversation_manager=cm)
    msg = ACLMessage(
        performative=Performative.INFORM,
        sender="planner",
        receiver="responder",
        content={
            "conversation_id": "c9",
            "final_response": "fallback",
            "final_response_object": {
                "summary": "Evidence metadata",
                "evidence": [
                    {
                        "fact": "Fact E",
                        "source": "websearcher",
                        "timestamp": "2026-04-20",
                        "citation_id": "NEWS1",
                    }
                ],
                "recommendation": {"allowed": False},
            },
        },
        conversation_id="c9",
    )
    r.handle_message(msg)
    registered = cm.register_reply.call_args[0][1]
    out = registered.content["final_response"]
    assert "websearcher" in out
    assert "2026-04-20" in out
    assert "NEWS1" in out
