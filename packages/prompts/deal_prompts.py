DEAL_ANALYSIS_PROMPT = """You are a senior deal analyst. Analyze the following deal and provide:
1. A concise executive summary (2-3 sentences)
2. A score from 0.0 to 1.0 (1.0 = excellent deal)
3. Top 3 risks
4. Top 3 opportunities

Deal Title: {title}
Description: {description}
Estimated Value: {value}

Respond in a structured, professional tone.
"""

DEAL_SCORING_PROMPT = """Score the following deal on a scale from 0 to 100 based on:
- Market opportunity
- Risk level (lower risk = higher score)
- Financial viability
- Strategic fit

Deal: {title}
Details: {description}

Return ONLY a JSON object: {{"score": <number>, "rationale": "<one sentence>"}}
"""
