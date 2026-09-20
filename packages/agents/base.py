from abc import ABC, abstractmethod
from typing import Any
from packages.llm_config import DEFAULT_ANALYSIS_MODEL


class BaseAgent(ABC):
    """Base class for all Diligenx agents."""

    def __init__(self, model: str = DEFAULT_ANALYSIS_MODEL):
        self.model = model

    @abstractmethod
    async def run(self, **kwargs) -> Any:
        """Execute the agent's main task."""
        ...
