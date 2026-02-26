"""Conversation state and STOP broadcast for A2A flows."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus


class ConversationState:
    """Snapshot of one conversation for API blocking and persistence.

    Attributes:
        id: Conversation UUID (conversation_id).
        user_id: User identifier; empty string if anonymous.
        initial_query: Original user query.
        messages: Append-only log of ACLMessage dicts.
        status: "active" | "complete" | "error".
        final_response: Set by register_reply when Responder delivers answer; None until then.
        created_at: Creation datetime.
        completion_event: threading.Event set when final_response is written; callers block with event.wait(timeout=...).
    """

    def __init__(
        self,
        conversation_id: str,
        user_id: str,
        initial_query: str,
        messages: Optional[list[dict[str, Any]]] = None,
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
        self.completion_event = (
            completion_event if completion_event is not None else threading.Event()
        )


class ConversationManager:
    """Tracks conversations and sends STOP broadcasts via the message bus.

    Responsibilities: create conversation, get state, register replies,
    broadcast STOP so agents stop processing a conversation.
    """

    def __init__(self, message_bus: MessageBus) -> None:
        """Initialize the conversation manager.

        Args:
            message_bus: MessageBus implementation for send/broadcast.
        """
        self._bus = message_bus
        self._conversations: dict[str, ConversationState] = {}
        # Root directory for per-user JSON persistence (backend: memory/<user_id>/conversations.json)
        self._memory_root = os.environ.get("MEMORY_STORE_PATH", "memory").rstrip("/")

    def _user_dir(self, user_id: str) -> str:
        """Directory path for this user's conversations.

        Args:
            user_id: User identifier. Empty string maps to "anonymous".

        Returns:
            Path under _memory_root for this user (e.g. memory/u1).
        """
        key = user_id if user_id else "anonymous"
        return os.path.join(self._memory_root, key)

    def _save_user(self, user_id: str) -> None:
        """Persist all conversations for this user to conversations.json.

        Called from create_conversation and register_reply. Writes one
        JSON file per user keyed by conversation_id.

        Args:
            user_id: User whose conversations to persist.
        """
        dir_path = self._user_dir(user_id)
        os.makedirs(dir_path, exist_ok=True)
        path = os.path.join(dir_path, "conversations.json")
        # Build one dict keyed by conversation_id for this user only (one file per user)
        data = {}
        for cid, state in self._conversations.items():
            if state.user_id == user_id:
                data[cid] = {
                    "id": state.id,
                    "user_id": state.user_id,
                    "initial_query": state.initial_query,
                    "messages": state.messages,
                    "status": state.status,
                    "final_response": state.final_response,
                    "created_at": (
                        state.created_at.isoformat() if state.created_at else None
                    ),
                }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def create_conversation(self, user_id: str, initial_query: str) -> str:
        """Create a new conversation and return its id.

        State is kept in memory and persisted via _save_user (conversations.json).

        Args:
            user_id: User identifier.
            initial_query: Initial user query.

        Returns:
            New conversation_id (UUID string).
        """
        cid = str(uuid.uuid4())
        state = ConversationState(
            conversation_id=cid,
            user_id=user_id,
            initial_query=initial_query,
            messages=[],
            status="active",
            final_response=None,
        )
        self._conversations[cid] = state
        self._save_user(user_id)
        return cid

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        """Return current state for a conversation.

        Args:
            conversation_id: Conversation to look up.

        Returns:
            ConversationState if found, else None.
        """
        return self._conversations.get(conversation_id)

    def register_reply(self, conversation_id: str, message: ACLMessage) -> None:
        """Record a reply message for a conversation.

        Appends the message to state.messages. If the message carries
        final_response (from Responder), marks the conversation complete
        and sets completion_event so API/E2E callers blocking on event.wait() can proceed.

        Args:
            conversation_id: Conversation to update.
            message: The reply ACL message.
        """
        state = self._conversations.get(conversation_id)
        if not state:
            return
        state.messages.append(message.to_dict())
        content = message.content or {}
        if "final_response" in content:
            state.final_response = content["final_response"]
            state.status = "complete"
            state.completion_event.set()  # Unblock POST /chat or --e2e-once waiting on event.wait()
        self._save_user(state.user_id)

    def broadcast_stop(self, conversation_id: str) -> None:
        """Send STOP via MessageBus so agents stop processing this conversation.

        receiver="*" is broadcast: every registered agent gets STOP and exits its run() loop.

        Args:
            conversation_id: Conversation to terminate.
        """
        msg = ACLMessage(
            performative=Performative.STOP,
            sender="conversation_manager",
            receiver="*",
            content={"conversation_id": conversation_id},
        )
        self._bus.broadcast(msg)
