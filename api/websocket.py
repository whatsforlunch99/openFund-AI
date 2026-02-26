"""WebSocket handler (Layer 1): same flow as REST with event response."""

from __future__ import annotations

import asyncio
from typing import Any

from a2a.acl_message import ACLMessage, Performative
from a2a.conversation_manager import ConversationManager
from a2a.message_bus import MessageBus
from safety.safety_gateway import SafetyError, SafetyGateway

VALID_USER_PROFILES = ("beginner", "long_term", "analyst")


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
    optional conversation_id, user_profile, user_id, path), validate,
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
    path = body.get("path")

    try:
        safety_gateway.process_user_input(query)
    except SafetyError as e:
        await websocket.send_json({"event": "error", "detail": e.reason})
        await websocket.close()
        return

    if conversation_id:
        state = manager.get_conversation(conversation_id)
        if state is None:
            await websocket.send_json(
                {"event": "error", "detail": "Conversation not found"}
            )
            await websocket.close()
            return
    else:
        conversation_id = manager.create_conversation(user_id, query)
        state = manager.get_conversation(conversation_id)
        if state is None:
            await websocket.send_json(
                {"event": "error", "detail": "Failed to create conversation"}
            )
            await websocket.close()
            return

    content = {
        "query": query,
        "conversation_id": conversation_id,
        "user_profile": user_profile,
    }
    if path is not None:
        content["path"] = path

    bus.send(
        ACLMessage(
            performative=Performative.REQUEST,
            sender="api",
            receiver="planner",
            content=content,
            conversation_id=conversation_id,
        )
    )

    loop = asyncio.get_running_loop()
    signaled = await loop.run_in_executor(
        None, lambda: state.completion_event.wait(timeout=timeout_seconds)
    )

    if signaled:
        await websocket.send_json(
            {
                "event": "response",
                "conversation_id": conversation_id,
                "status": state.status,
                "response": state.final_response or "",
            }
        )
    else:
        await websocket.send_json(
            {
                "event": "timeout",
                "conversation_id": conversation_id,
                "response": None,
            }
        )

    await websocket.close()
