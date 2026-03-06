import anthropic
from dataclasses import dataclass

from .base import BaseAgent
from packages.prompts.deal_prompts import DEAL_ANALYSIS_PROMPT


@dataclass
class DealAnalysisResult:
    summary: str
    score: float
    risks: list[str]
    opportunities: list[str]


class DealAnalysisAgent(BaseAgent):
    """Analyzes deals using Claude AI."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        super().__init__(model)
        self.client = anthropic.Anthropic(api_key=api_key)

    async def run(self, title: str, description: str, value: float | None = None) -> DealAnalysisResult:
        prompt = DEAL_ANALYSIS_PROMPT.format(
            title=title,
            description=description or "No description provided.",
            value=f"${value:,.2f}" if value else "Not specified",
        )

        message = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text

        # Simple parsing — extend with structured output as needed
        return DealAnalysisResult(
            summary=raw,
            score=0.75,
            risks=[],
            opportunities=[],
        )
