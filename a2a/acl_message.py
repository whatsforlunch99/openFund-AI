"""FIPA-ACL message type for agent-to-agent communication."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, Optional, Union
import uuid


class Performative(StrEnum):
    """
    FIPA-ACL performatives (B1). Complete set for current stages.
    New values added only when a stage explicitly requires them.
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
    """
    FIPA-ACL message exchanged between agents.

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

    performative: Union[Performative, str]
    sender: str
    receiver: str
    content: Dict[str, Any]
    conversation_id: Optional[str] = None
    reply_to: Optional[str] = None
    in_reply_to: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Normalize performative to Performative enum; assign conversation_id and timestamp if not provided."""
        if isinstance(self.performative, str):
            self.performative = Performative(self.performative.upper())
        if not self.conversation_id:
            self.conversation_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """
        Return a JSON-serializable dict for persistence (D2).

        Converts performative to string and timestamp to ISO format so
        json.dumps() can serialize state.messages when persisting to
        memory/<user_id>/conversations.json.
        """
        return {
            "performative": self.performative.value if hasattr(self.performative, "value") else str(self.performative),
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "conversation_id": self.conversation_id,
            "reply_to": self.reply_to,
            "in_reply_to": self.in_reply_to,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }
