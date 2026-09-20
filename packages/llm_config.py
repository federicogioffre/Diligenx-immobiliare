"""Shared analysis defaults and explicit provider selection."""

DEFAULT_ANALYSIS_MODEL = "gpt-5.6-luna"


def analysis_api_key_name(model: str) -> str:
    if model.startswith("gpt-"):
        return "OPENAI_API_KEY"
    if model.startswith("claude-"):
        return "ANTHROPIC_API_KEY"
    raise ValueError(f"Unsupported ANALYSIS_MODEL: {model}")
