"""Conversation state and STOP broadcast for A2A flows."""

from typing import Dict, List, Optional

from a2a.acl_message import ACLMessage
from a2a.message_bus import MessageBus


class ConversationState:
    """
    Immutable snapshot of a conversation's state.

    Attributes:
        conversation_id: Unique conversation id.
        user_id: Optional user identifier.
        messages: Ordered list of ACL messages in this conversation.
        terminated: Whether Responder has broadcast STOP.
    """

    def __init__(
        self,
        conversation_id: str,
        user_id: str = "",
        messages: Optional[List[ACLMessage]] = None,
        terminated: bool = False,
    ) -> None:
        self.conversation_id = conversation_id
        self.user_id = user_id
        self.messages = list(messages) if messages else []
        self.terminated = terminated


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
