"""Abstract base agent for the A2A system."""

from abc import ABC, abstractmethod

from a2a.acl_message import ACLMessage, Performative
from a2a.message_bus import MessageBus


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Agents listen on the message bus and process incoming ACL messages.
    """

    def __init__(self, name: str, message_bus: MessageBus) -> None:
        """Initialize the agent.

        Args:
            name: Unique agent name (used as receiver address).
            message_bus: Shared A2A transport layer.
        """
        self.name = name
        self.bus = message_bus

    def run(self) -> None:
        """Start the agent event loop.

        Continuously receives messages for this agent and delegates
        to handle_message. Exits cleanly when a STOP message is received
        (e.g. after Responder calls broadcast_stop).
        """
        while True:
            # Blocking receive loop: each agent processes only messages addressed to itself.
            message = self.bus.receive(self.name)
            if message is None:
                continue
            # Exit loop on STOP so this agent thread shuts down cleanly
            if message.performative == Performative.STOP:
                break
            self.handle_message(message)

    @abstractmethod
    def handle_message(self, message: ACLMessage) -> None:
        """Process an incoming ACL message.

        Args:
            message: The received ACL message.
        """
        raise NotImplementedError
