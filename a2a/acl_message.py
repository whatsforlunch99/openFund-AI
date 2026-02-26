"""FIPA-ACL message type for agent-to-agent communication."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class Performative(str, Enum):
    """FIPA-ACL performatives (B1).

    Uses (str, Enum) for Python 3.9 compatibility (StrEnum is 3.11+).
    Values are string names so they serialize cleanly.
    """

    REQUEST = "REQUEST"
    INFORM = "INFORM"
    STOP = "STOP"
    FAILURE = "FAILURE"
    ACK = "ACK"
    REFUSE = "REFUSE"
    CANCEL = "CANCEL"


@dataclass
class ACLMessage:
    """FIPA-ACL message exchanged between agents.

    Attributes:
        performative: Communication intent (Performative enum per B1).
        sender: Name of the sending agent.
        receiver: Name of the receiving agent.
        content: Structured payload of the message.
        conversation_id: Unique conversation identifier.
        reply_to: Optional agent name to reply to.
        in_reply_to: Optional message id this message replies to.
        timestamp: Optional send time.
    """

    performative: Performative | str
    sender: str
    receiver: str
    content: dict[str, Any]
    conversation_id: Optional[str] = None
    reply_to: Optional[str] = None
    in_reply_to: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Normalize performative to enum; set conversation_id and timestamp if missing."""
        if isinstance(self.performative, str):
            self.performative = Performative(self.performative.upper())
        # One conversation_id per thread so agents can route replies; timestamp for ordering
        if not self.conversation_id:
            self.conversation_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict for persistence (D2).

        Converts performative to string and timestamp to ISO format for
        serialization to memory/<user_id>/conversations.json.

        Returns:
            Dict suitable for json.dumps (e.g. in state.messages).
        """
        return {
            "performative": (
                self.performative.value
                if hasattr(self.performative, "value")
                else str(self.performative)
            ),
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "conversation_id": self.conversation_id,
            "reply_to": self.reply_to,
            "in_reply_to": self.in_reply_to,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
