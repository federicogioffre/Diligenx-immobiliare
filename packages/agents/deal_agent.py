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

    def __init__(self, api_key: str, model: str = "claude-sonnet-5"):
        super().__init__(model)
        self.client = anthropic.Anthropic(api_key=api_key)

    async def run(self, title: str, description: str, value: float | None = None) -> DealAnalysisResult:
        prompt = DEAL_ANALYSIS_PROMPT.format(
            title=title,
            description=description or "No description provided.",
            value=f"${value:,.2f}" if value else "Not specified",
        )

        thinking_options = (
            {"thinking": {"type": "disabled"}}
            if self.model == "claude-sonnet-5" or self.model.startswith("claude-sonnet-5-")
            else {}
        )
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1536,
            **thinking_options,
            messages=[{"role": "user", "content": prompt}],
        )

        from .deal_analysis_agent import LLMResponseError

        if message.stop_reason in {"max_tokens", "refusal"}:
            raise LLMResponseError(f"AI response stopped with {message.stop_reason}")
        raw = "".join(
            block.text for block in message.content
            if isinstance(getattr(block, "text", None), str)
        )
        if not raw.strip():
            raise LLMResponseError("AI response contained no text")

        # Simple parsing — extend with structured output as needed
        return DealAnalysisResult(
            summary=raw,
            score=0.75,
            risks=[],
            opportunities=[],
        )
