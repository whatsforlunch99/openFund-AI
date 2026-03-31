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
