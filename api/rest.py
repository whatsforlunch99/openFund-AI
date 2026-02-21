"""REST API (Layer 1): chat and conversation endpoints."""

from typing import Any, Optional


def create_app() -> Any:
    """
    Create FastAPI application with chat and conversation routes.

    Returns:
        FastAPI app instance.
    """
    raise NotImplementedError


def post_chat(body: dict) -> dict:
    """
    Handle POST /chat (or POST /research).

    Flow: validate body -> SafetyGateway.process_user_input ->
    create/load conversation -> send ACLMessage to Planner ->
    wait for response (or stream) -> return.

    Args:
        body: Request body with 'query'; optional 'conversation_id', 'user_profile'.

    Returns:
        Response dict with conversation_id, message_id, status, response.
    """
    raise NotImplementedError


def get_conversation(conversation_id: str) -> Optional[dict]:
    """
    Handle GET /conversations/{id}.

    Args:
        conversation_id: Conversation to fetch.

    Returns:
        Conversation state/messages or None if not found.
    """
    raise NotImplementedError
