"""Conversation state and STOP broadcast for A2A flows."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Optional

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus
from util.trace_log import trace
from util import interaction_log

logger = logging.getLogger(__name__)


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
        flow_events: Append-only list of flow step dicts for UI (e.g. {"step": "...", "message": "...", "detail": {...}}).
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
        self.flow_events: list[dict[str, Any]] = []
        self._flow_lock = threading.Lock()

    def append_flow(self, event: dict[str, Any]) -> None:
        """Append a flow step (thread-safe). event: at least 'step' and 'message'; optional 'detail'."""
        with self._flow_lock:
            self.flow_events.append(event)


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
        # Write JSON so conversations survive restart
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_user_conversations(self, user_id: str) -> int:
        """Load persisted conversations for a user into memory.

        Args:
            user_id: User whose conversations should be loaded.

        Returns:
            Number of conversations loaded into in-memory state.
        """
        if not user_id:
            return 0
        path = os.path.join(self._user_dir(user_id), "conversations.json")
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return 0

        if not isinstance(data, dict):
            return 0

        # Parse persisted JSON map into in-memory ConversationState objects.
        loaded = 0
        for cid, raw in data.items():
            if not isinstance(cid, str) or not isinstance(raw, dict):
                continue
            if cid in self._conversations:
                continue

            created_at = datetime.utcnow()
            created_raw = raw.get("created_at")
            if isinstance(created_raw, str) and created_raw.strip():
                try:
                    created_at = datetime.fromisoformat(created_raw)
                except ValueError:
                    pass

            # Declare state fields from JSON record, then restore completion marker if finished.
            state = ConversationState(
                conversation_id=raw.get("id") or cid,
                user_id=raw.get("user_id") or user_id,
                initial_query=raw.get("initial_query") or "",
                messages=raw.get("messages") if isinstance(raw.get("messages"), list) else [],
                status=raw.get("status") or "active",
                final_response=raw.get("final_response"),
                created_at=created_at,
            )
            if state.status == "complete" or state.final_response:
                state.status = "complete"
                state.completion_event.set()
            self._conversations[cid] = state
            loaded += 1

        return loaded

    def get_user_memory_context(
        self, user_id: str, max_conversations: int = 3, max_chars: int = 3000
    ) -> str:
        """Build a compact memory context from recent completed conversations.

        Args:
            user_id: User identifier.
            max_conversations: Max number of historical conversations to include.
            max_chars: Max output characters.

        Returns:
            Memory context text for planner input; empty string when unavailable.
        """
        if not user_id:
            return ""
        self.load_user_conversations(user_id)

        # Gather completed conversations only; these are useful as planner memory.
        history = [
            s
            for s in self._conversations.values()
            if s.user_id == user_id and (s.final_response or s.status == "complete")
        ]
        if not history:
            return ""

        history.sort(key=lambda s: s.created_at or datetime.utcnow(), reverse=True)
        selected = history[: max(1, max_conversations)]

        # Build compact Q/A memory blocks until char budget is reached.
        parts: list[str] = []
        current_len = 0
        for state in selected:
            q = (state.initial_query or "").strip()
            a = (state.final_response or "").strip()
            if not q and not a:
                continue
            block = f"- Q: {q}\n  A: {a}"
            add_len = len(block) + (1 if parts else 0)
            if current_len + add_len > max_chars:
                break
            parts.append(block)
            current_len += add_len

        if not parts:
            return ""
        return "Recent user memory:\n" + "\n".join(parts)

    def create_conversation(self, user_id: str, initial_query: str) -> str:
        """Create a new conversation and return its id.

        State is kept in memory and persisted via _save_user (conversations.json).

        Args:
            user_id: User identifier.
            initial_query: Initial user query.

        Returns:
            New conversation_id (UUID string).
        """
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.create_conversation",
            params={"user_id": user_id, "initial_query_len": len(initial_query)},
        )
        self.load_user_conversations(user_id)
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
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.create_conversation",
            result={"conversation_id": cid, "status": "created"},
        )
        trace(
            3,
            "create_conversation",
            in_={"user_id": user_id, "initial_query": initial_query[:50]},
            out=f"conversation_id={cid}",
            next_="return to API",
        )
        return cid

    def append_flow(self, conversation_id: str, event: dict[str, Any]) -> None:
        """Append a flow step for a conversation (for UI). Safe if state not found."""
        state = self._conversations.get(conversation_id)
        if state is not None and hasattr(state, "append_flow"):
            state.append_flow(event)

    def get_flow_events(self, conversation_id: str) -> list[dict[str, Any]]:
        """Return a copy of flow_events for the conversation (for polling). Thread-safe when state has _flow_lock."""
        state = self._conversations.get(conversation_id)
        if state is None or not hasattr(state, "flow_events"):
            return []
        lock = getattr(state, "_flow_lock", None)
        if lock is not None:
            with lock:
                return list(state.flow_events)
        return list(getattr(state, "flow_events", []))

    def get_conversation(self, conversation_id: str) -> Optional[ConversationState]:
        """Return current state for a conversation.

        Args:
            conversation_id: Conversation to look up.

        Returns:
            ConversationState if found, else None.
        """
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.get_conversation",
            params={"conversation_id": conversation_id},
        )
        state = self._conversations.get(conversation_id)
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.get_conversation",
            result={
                "found": state is not None,
                "status": getattr(state, "status", None) if state else None,
            },
        )
        return state

    def register_reply(self, conversation_id: str, message: ACLMessage) -> None:
        """Record a reply message for a conversation.

        Appends the message to state.messages. If the message carries
        final_response (from Responder), marks the conversation complete
        and sets completion_event so API/E2E callers blocking on event.wait() can proceed.

        Args:
            conversation_id: Conversation to update.
            message: The reply ACL message.
        """
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.register_reply",
            params={"conversation_id": conversation_id},
        )
        state = self._conversations.get(conversation_id)
        if not state:
            interaction_log.log_call(
                "a2a.conversation_manager.ConversationManager.register_reply",
                result={"skipped": True, "reason": "state not found"},
            )
            return
        state.messages.append(message.to_dict())
        content = message.content or {}
        # If Responder sent final_response, mark conversation complete and unblock API waiters
        if "final_response" in content:
            state.final_response = content["final_response"]
            state.status = "complete"
            state.completion_event.set()  # Unblock POST /chat or --e2e-once waiting on event.wait()
            interaction_log.log_call(
                "a2a.conversation_manager.ConversationManager.register_reply",
                result={
                    "status": "complete",
                    "response_len": len(state.final_response or ""),
                },
            )
            trace(
                13,
                "register_reply",
                in_={"conversation_id": conversation_id},
                out=f"status=complete response_len={len(state.final_response or '')}",
                next_="save_user, then API unblocks",
            )
        else:
            interaction_log.log_call(
                "a2a.conversation_manager.ConversationManager.register_reply",
                result={"appended": True},
            )
        self._save_user(state.user_id)

    def broadcast_stop(self, conversation_id: str) -> None:
        """Send STOP via MessageBus so agents stop processing this conversation.

        receiver="*" is broadcast: every registered agent gets STOP and exits its run() loop.

        Args:
            conversation_id: Conversation to terminate.
        """
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.broadcast_stop",
            params={"conversation_id": conversation_id},
        )
        msg = ACLMessage(
            performative=Performative.STOP,
            sender="conversation_manager",
            receiver="*",
            content={"conversation_id": conversation_id},
        )
        self._bus.broadcast(msg)
        interaction_log.log_call(
            "a2a.conversation_manager.ConversationManager.broadcast_stop",
            result={"sent": True},
        )
        trace(
            13,
            "broadcast_stop",
            in_={"conversation_id": conversation_id},
            out="STOP sent to all agents",
            next_="agents exit run loop",
        )
