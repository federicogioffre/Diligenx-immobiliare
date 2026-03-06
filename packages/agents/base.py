from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Base class for all DealMind agents."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    @abstractmethod
    async def run(self, **kwargs) -> Any:
        """Execute the agent's main task."""
        ...
