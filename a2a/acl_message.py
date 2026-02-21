"""FIPA-ACL message type for agent-to-agent communication."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
import uuid


@dataclass
class ACLMessage:
    """
    FIPA-ACL message exchanged between agents.

    Attributes:
        performative: Communication intent (e.g. request, inform, stop).
        sender: Name of the sending agent.
        receiver: Name of the receiving agent.
        content: Structured payload of the message.
        conversation_id: Unique conversation identifier.
        reply_to: Optional agent name to reply to.
        in_reply_to: Optional message id this message replies to.
        timestamp: Optional send time.
    """

    performative: str
    sender: str
    receiver: str
    content: Dict[str, Any]
    conversation_id: Optional[str] = None
    reply_to: Optional[str] = None
    in_reply_to: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __post_init__(self) -> None:
        """Assign a unique conversation ID if not provided."""
        if not self.conversation_id:
            self.conversation_id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
