"""WebSocket handler (Layer 1): same flow as REST with event response."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from a2a.acl_message import ACLMessage, Performative
from a2a.conversation_manager import ConversationManager
from a2a.message_bus import MessageBus
from safety.safety_gateway import SafetyError, SafetyGateway
from util import interaction_log

VALID_USER_PROFILES = ("beginner", "long_term", "analyst")
FLOW_POLL_INTERVAL = 0.2
COMPLETION_POLL_INTERVAL = 0.25


async def handle_websocket(
    websocket: Any,
    bus: MessageBus,
    manager: ConversationManager,
    safety_gateway: SafetyGateway,
    timeout_seconds: float,
) -> None:
    """
    Handle WebSocket /ws connection.

    Same flow as POST /chat: receive one JSON message (query required;
    optional conversation_id, user_profile, user_id), validate,
    run SafetyGateway.process_user_input, create or get conversation,
    send REQUEST to planner, wait on completion_event, then send one
    event (response, timeout, or error) and close.

    Args:
        websocket: WebSocket connection (e.g. FastAPI WebSocket); accept()
            is called by the route before this.
        bus: MessageBus for sending to planner.
        manager: ConversationManager for create/get.
        safety_gateway: For process_user_input.
        timeout_seconds: Max wait for completion.
    """
    try:
        body = await websocket.receive_json()
    except Exception as e:
        await websocket.send_json({"event": "error", "detail": str(e)})
        await websocket.close()
        return

    # Validation phase: declare required fields and reject malformed input early.
    query = body.get("query")
    if query is None or (isinstance(query, str) and not query.strip()):
        await websocket.send_json(
            {"event": "error", "detail": "query is required and must be non-empty"}
        )
        await websocket.close()
        return

    user_profile = (body.get("user_profile") or "beginner").strip().lower()
    if user_profile not in VALID_USER_PROFILES:
        await websocket.send_json(
            {
                "event": "error",
                "detail": f"user_profile must be one of {list(VALID_USER_PROFILES)}",
            }
        )
        await websocket.close()
        return

    user_id = body.get("user_id")
    if user_id is None:
        user_id = ""
    else:
        user_id = str(user_id).strip()

    conversation_id = body.get("conversation_id")
    if conversation_id is not None:
        conversation_id = str(conversation_id).strip() or None
    user_memory = ""
    if user_id:
        # Load persisted user history and compute planner memory context.
        manager.load_user_conversations(user_id)
        user_memory = manager.get_user_memory_context(user_id)

    interaction_log.log_call(
        "api.websocket.handle_websocket",
        params={
            "query_len": len(query or ""),
            "user_profile": user_profile,
            "conversation_id": conversation_id or "(new)",
        },
    )

    # Safety gate phase: input must pass guardrails before any agent dispatch.
    try:
        safety_gateway.process_user_input(query)
    except SafetyError as e:
        interaction_log.log_call(
            "api.websocket.handle_websocket",
            result={"event": "error", "error": e.reason},
        )
        await websocket.send_json({"event": "error", "detail": e.reason})
        await websocket.close()
        return

    if conversation_id:
        state = manager.get_conversation(conversation_id)

        interaction_log.set_conversation_id(conversation_id)
        manager.append_flow(
            conversation_id,
            {
                "step": "reload_conversation",
                "message": "Conversation loaded. You can ask your question below.",
                "detail": {
                    "user_id": user_id or "anonymous",
                    "conversation_id": conversation_id,
                },
            },
        )
    else:
        conversation_id = manager.create_conversation(user_id, query)
        state = manager.get_conversation(conversation_id)

        interaction_log.set_conversation_id(conversation_id)
        display = f" (welcome, user {user_id})" if user_id else ""
        manager.append_flow(
            conversation_id,
            {
                "step": "user_created",
                "message": f"New conversation started.{display} You can ask your question below.",
                "detail": {
                    "user_id": user_id or "anonymous",
                    "conversation_id": conversation_id,
                },
            },
        )

    # Dispatch phase: compose planner payload and send REQUEST via message bus.
    content = {
        "query": query,
        "conversation_id": conversation_id,
        "user_profile": user_profile,
    }
    if user_memory:
        content["user_memory"] = user_memory

    bus.send(
        ACLMessage(
            performative=Performative.REQUEST,
            sender="api",
            receiver="planner",
            content=content,
            conversation_id=conversation_id,
        )
    )
    manager.append_flow(
        conversation_id,
        {
            "step": "request_sent",
            "message": "Query received. Sent to Planner; you will see decomposition and agent steps as they run.",
            "detail": {"query_preview": (query or "")[:100]},
        },
    )

    # Streaming phase: emit incremental flow events while waiting for completion.
    loop = asyncio.get_running_loop()
    sent_count = 0
    start = time.monotonic()
    signaled = False
    # Poll completion_event in executor so async loop stays responsive; stream flow as it arrives
    while (time.monotonic() - start) < timeout_seconds:

        # Compute delta flow slice and stream only new events.
        flow = manager.get_flow_events(conversation_id)
        for i in range(sent_count, len(flow)):
            await websocket.send_json({"event": "flow", **flow[i]})
        sent_count = len(flow)

        # Poll completion_event using a short blocking window in executor.
        remaining = timeout_seconds - (time.monotonic() - start)
        if remaining <= 0:
            break

        # wait for the completion event
        wait_time = min(COMPLETION_POLL_INTERVAL, remaining)
        def _wait() -> bool:
            return state.completion_event.wait(timeout=wait_time)

        signaled = await loop.run_in_executor(None, _wait)

        # if the completion event is signaled, break the loop
        if signaled:
            break
        await asyncio.sleep(FLOW_POLL_INTERVAL)

    # Flush final flow events before terminal response/timeout event.
    flow = manager.get_flow_events(conversation_id)
    for i in range(sent_count, len(flow)):
        await websocket.send_json({"event": "flow", **flow[i]})

    if signaled:
        interaction_log.log_call(
            "api.websocket.handle_websocket",
            result={
                "event": "response",
                "conversation_id": conversation_id,
                "status": state.status,
                "response_len": len(state.final_response or ""),
            },
        )
        await websocket.send_json(
            {
                "event": "response",
                "conversation_id": conversation_id,
                "status": state.status,
                "response": state.final_response or "",
                "flow": manager.get_flow_events(conversation_id),
            }
        )
    else:
        interaction_log.log_call(
            "api.websocket.handle_websocket",
            result={"event": "timeout", "conversation_id": conversation_id},
        )
        await websocket.send_json(
            {
                "event": "timeout",
                "conversation_id": conversation_id,
                "response": None,
                "flow": manager.get_flow_events(conversation_id),
            }
        )

    await websocket.close()
