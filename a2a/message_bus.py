"""Abstract message transport for agent-to-agent communication."""

import queue
from abc import ABC, abstractmethod
from typing import Optional

from a2a.acl_message import ACLMessage


class MessageBus(ABC):
    """Abstract message transport layer for A2A communication.

    Backends may use Redis, Kafka, NATS, or in-memory queues.
    """

    @abstractmethod
    def register_agent(self, name: str) -> None:
        """Register an agent by name.

        Required for receive and for broadcast delivery.

        Args:
            name: Unique agent name (e.g. "planner", "librarian", "responder").
        """
        raise NotImplementedError

    @abstractmethod
    def send(self, message: ACLMessage) -> None:
        """Send an ACL message to the designated receiver.

        Args:
            message: The message to dispatch.
        """
        raise NotImplementedError

    @abstractmethod
    def receive(
        self, agent_name: str, timeout: Optional[float] = None
    ) -> Optional[ACLMessage]:
        """Wait for a message addressed to the given agent.

        Args:
            agent_name: Name of the agent waiting for messages.
            timeout: Optional max seconds to wait; None means block indefinitely.

        Returns:
            The received message, or None if timeout elapsed.
        """
        raise NotImplementedError

    @abstractmethod
    def broadcast(self, message: ACLMessage) -> None:
        """Send a message to all agents (e.g. STOP).

        Args:
            message: The message to broadcast.
        """
        raise NotImplementedError


class InMemoryMessageBus(MessageBus):
    """In-memory message transport using one queue per registered agent.

    send() delivers only to the named receiver; broadcast() puts a copy
    into every registered agent's queue so all agents can react (e.g. to STOP).
    """

    def __init__(self) -> None:
        """Initialize empty agent queues."""
        self._queues: dict[str, queue.Queue[ACLMessage]] = {}

    def register_agent(self, name: str) -> None:
        """Create a dedicated queue for this agent.

        Args:
            name: Agent name. receive(agent_name) will block on this queue.
        """
        if name not in self._queues:
            self._queues[name] = queue.Queue()

    def send(self, message: ACLMessage) -> None:
        """Enqueue message only for message.receiver.

        Args:
            message: ACL message. No-op if receiver not registered.
        """
        receiver = message.receiver
        if receiver in self._queues:
            self._queues[receiver].put(message)

    def receive(
        self, agent_name: str, timeout: Optional[float] = None
    ) -> Optional[ACLMessage]:
        """Block until a message for this agent arrives or timeout.

        Args:
            agent_name: Name of the agent receiving.
            timeout: Max seconds to wait; None blocks indefinitely.

        Returns:
            The next message for this agent, or None on timeout.
        """
        q = self._queues.get(agent_name)
        if q is None:
            return None
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            # Timeout elapsed with no message
            return None

    def broadcast(self, message: ACLMessage) -> None:
        """Deliver the same message to every registered agent.

        Args:
            message: Message to send (e.g. STOP for shutdown).
        """
        for name in self._queues:
            self._queues[name].put(message)
