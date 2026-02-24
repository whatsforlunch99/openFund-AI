"""Abstract message transport for agent-to-agent communication."""

from abc import ABC, abstractmethod
from typing import Optional

from a2a.acl_message import ACLMessage


class MessageBus(ABC):
    """
    Abstract message transport layer for A2A communication.

    Backends may use Redis, Kafka, NATS, or in-memory queues.
    """

    @abstractmethod
    def register_agent(self, name: str) -> None:
        """
        Register an agent by name. Required for receive and for broadcast delivery.

        Args:
            name: Unique agent name (e.g. "planner", "librarian", "responder").
        """
        raise NotImplementedError

    @abstractmethod
    def send(self, message: ACLMessage) -> None:
        """
        Send an ACL message to the designated receiver.

        Args:
            message: The message to dispatch.
        """
        raise NotImplementedError

    @abstractmethod
    def receive(self, agent_name: str, timeout: Optional[float] = None) -> Optional[ACLMessage]:
        """
        Wait for a message addressed to the given agent.

        Args:
            agent_name: Name of the agent waiting for messages.
            timeout: Optional max seconds to wait; None means block indefinitely.

        Returns:
            The received message, or None if timeout elapsed.
        """
        raise NotImplementedError

    @abstractmethod
    def broadcast(self, message: ACLMessage) -> None:
        """
        Send a message to all agents (e.g. STOP).

        Args:
            message: The message to broadcast.
        """
        raise NotImplementedError
