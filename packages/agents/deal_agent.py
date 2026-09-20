from dataclasses import dataclass
from packages.llm_config import DEFAULT_ANALYSIS_MODEL
from .deal_analysis_agent import create_llm_provider

from .base import BaseAgent
from packages.prompts.deal_prompts import DEAL_ANALYSIS_PROMPT


@dataclass
class DealAnalysisResult:
    summary: str
    score: float
    risks: list[str]
    opportunities: list[str]


class DealAnalysisAgent(BaseAgent):
    """Legacy summary interface using the same configured provider contract."""

    def __init__(self, api_key: str, model: str = DEFAULT_ANALYSIS_MODEL):
        super().__init__(model)
        self.provider = create_llm_provider(api_key, model)

    async def run(self, title: str, description: str, value: float | None = None) -> DealAnalysisResult:
        prompt = DEAL_ANALYSIS_PROMPT.format(
            title=title,
            description=description or "No description provided.",
            value=f"${value:,.2f}" if value else "Not specified",
        )

        raw = self.provider.complete(prompt, max_tokens=1536)

        # Simple parsing — extend with structured output as needed
        return DealAnalysisResult(
            summary=raw,
            score=0.75,
            risks=[],
            opportunities=[],
        )
