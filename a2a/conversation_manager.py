"""Conversation state and STOP broadcast for A2A flows."""

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus


class ConversationState:
    """
    Snapshot of one conversation for API blocking and persistence.

    Attributes:
        id: Conversation UUID (conversation_id).
        user_id: User identifier; empty string if anonymous.
        initial_query: Original user query.
        messages: Append-only log of ACLMessage dicts.
        status: "active" | "complete" | "error".
        final_response: Set by register_reply when Responder delivers answer; None until then.
        created_at: Creation datetime.
        completion_event: threading.Event; set when final_response is written; callers block with event.wait(timeout=...).
    """

    def __init__(
        self,
        conversation_id: str,
        user_id: str,
        initial_query: str,
        messages: Optional[List[Dict[str, Any]]] = None,
        status: str = "active",
        final_response: Optional[str] = None,
        created_at: Optional[datetime] = None,
        completion_event: Optional[threading.Event] = None,
    ) -> None:
        self.id = conversation_id
        self.user_id = user_id
        self.initial_query = initial_query
        self.messages = list(messages) if messages else []
        self.status = status
        self.final_response = final_response
        self.created_at = created_at if created_at is not None else datetime.utcnow()
        self.completion_event = completion_event if completion_event is not None else threading.Event()


class ConversationManager:
    """
    Tracks conversations and sends STOP broadcasts via the message bus.

    Responsibilities: create conversation, get state, register replies,
    broadcast STOP so agents stop processing a conversation.
    """

    def __init__(self, message_bus: MessageBus) -> None:
        """
        Initialize the conversation manager.

        Args:
            message_bus: MessageBus implementation for send/broadcast.
        """
        self._bus = message_bus
        self._conversations: Dict[str, ConversationState] = {}

    def create_conversation(self, user_id: str, initial_query: str) -> str:
        """
        Create a new conversation and return its id.

        Args:
            user_id: User identifier.
            initial_query: Initial user query.

        Returns:
            New conversation_id.
        """
        raise NotImplementedError

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        """
        Return current state for a conversation.

        Args:
            conversation_id: Conversation to look up.

        Returns:
            ConversationState if found, else None.
        """
        raise NotImplementedError

    def register_reply(self, conversation_id: str, message: ACLMessage) -> None:
        """
        Record a reply message for a conversation.

        Args:
            conversation_id: Conversation to update.
            message: The reply ACL message.
        """
        raise NotImplementedError

    def broadcast_stop(self, conversation_id: str) -> None:
        """
        Send STOP via MessageBus so agents stop processing this conversation.

        Args:
            conversation_id: Conversation to terminate.
        """
        raise NotImplementedError
