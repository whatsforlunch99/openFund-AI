"""Abstract message transport for agent-to-agent communication."""

import queue
from abc import ABC, abstractmethod
from typing import Optional

from a2a.acl_message import ACLMessage
from util import interaction_log


# agents do not communicate directly with each other, they communicate through the message bus -  there could be async and comcurrent agents

# changing the implementation of an agent does not affect the other agents
# "separation of concerns" :the message bus is responsible for the communication between the agents, while the agents are responsible for the business logic

# adding any new abstract method will require the subclasses to implement it, else raise TypeError
# "open/closed" principle: the message bus is open for extension, but closed for modification, and the agents are closed for modification, but open for extension

# ABC here means Abstract Base Class: it’s the Python mechanism for defining a class that can’t be instantiated by itself and that declares methods subclasses must implement.

class MessageBus(ABC):
    """Abstract message transport layer for A2A communication.

    Backends may use Redis, Kafka, NATS later on without rewriting agents, or in-memory queues for now.
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


# this could be swapped out for a different implementation such as Redis, Kafka, NATS later on without rewriting agents 
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
        # Queue creation is idempotent so repeated register calls are safe.
        if name not in self._queues:
            self._queues[name] = queue.Queue()

    def send(self, message: ACLMessage) -> None:
        """Enqueue message only for message.receiver.

        Args:
            message: ACL message. No-op if receiver not registered.
        """
        cid = getattr(message, "conversation_id", None) or (
            (message.content or {}).get("conversation_id")
        )
        interaction_log.log_call(
            "a2a.message_bus.InMemoryMessageBus.send",
            params={
                "sender": message.sender,
                "receiver": message.receiver,
                "conversation_id": cid or "",
            },
            result=None,
        )
        # Declare receiver once, then enqueue only to that target queue.
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
        cid = getattr(message, "conversation_id", None) or (
            (message.content or {}).get("conversation_id")
        )
        # Write one copy into each registered queue for fan-out semantics.
        for name in self._queues:
            self._queues[name].put(message)

        interaction_log.log_call(
        "a2a.message_bus.InMemoryMessageBus.broadcast",
        params={
            "sender": message.sender,
            "conversation_id": cid or "",
        },
        result=None,
        )
