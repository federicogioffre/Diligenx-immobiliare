"""Real-estate due diligence domain: the purchase of an Italian residential property.

Everything specific to the property purchase lives here — the documents a
buyer should receive, the document types the router recognises, the report
areas, the dated rules, the specialist reviewers and the deterministic
cross-document checks. The engine (ingestion, LLM fan-out, source-fidelity
review, credits, auth, RLS) is shared with Diligenx and stays in
``packages/agents`` and ``apps/api``.
"""
