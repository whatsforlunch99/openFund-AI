"""WebSocket handler (Layer 1): same flow as REST with streaming."""

from typing import Any


def handle_websocket(websocket: Any) -> None:
    """
    Handle WebSocket /ws connection.

    Same semantics as POST /chat: receive query (and optional
    conversation_id, user_profile), run through SafetyGateway,
    post to MessageBus, stream partial responses back.

    Args:
        websocket: WebSocket connection object (e.g. FastAPI WebSocket).
    """
    raise NotImplementedError
