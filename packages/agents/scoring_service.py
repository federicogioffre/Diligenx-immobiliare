"""Deterministic deal risk scoring.

Computes a 0–100 risk score from the deal's existing analysis outputs
(RedFlag rows, AgentFinding observations/info-requests, MissingDocument rows)
**without any LLM call**.  Fast enough to run on every page load.

Score formula
-------------
Start at 100 and subtract deduction points:

  Critical red flag  → −25 pts each
  High red flag      → −15 pts each
  Medium red flag    → −5  pts each  (rare: aggregator mostly emits high/critical)
  Low red flag       → −2  pts each

  Medium observation → −3  pts each
  Low observation    → −1  pt  each

  Information request → −1 pt each
  Missing document    → −3 pts each

Score is clamped to [0, 100].

Risk levels
-----------
  80–100  → "low"
  60–79   → "medium"
  40–59   → "high"
  0–39    → "critical"
"""

from __future__ import annotations

from sqlalchemy.orm import Session


# ── Weight tables ─────────────────────────────────────────────────────────

_RED_FLAG_WEIGHTS: dict[str, int] = {
    "critical": 25,
    "high": 15,
    "medium": 5,
    "low": 2,
}

_OBSERVATION_WEIGHTS: dict[str, int] = {
    "critical": 5,   # shouldn't occur — aggregator caps observations at medium
    "high": 4,
    "medium": 3,
    "low": 1,
}

_INFO_REQUEST_WEIGHT = 1
_MISSING_DOC_WEIGHT = 3

# Severity ordering for max-severity tracking
_SEV_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ── Public function ────────────────────────────────────────────────────────

def compute_risk_score(deal_id: int, db: Session) -> dict:
    """Compute and return the risk score dict for *deal_id*.

    Returns::

        {
            "deal_id": int,
            "score": int,                # 0–100
            "risk_level": str,           # "low" | "medium" | "high" | "critical"
            "deductions": {
                "red_flags":           {"count": int, "impact": int},
                "observations":        {"count": int, "impact": int},
                "information_requests":{"count": int, "impact": int},
                "missing_documents":   {"count": int, "impact": int},
            },
            "categories": [             # sorted by impact descending
                {
                    "category": str,
                    "count": int,
                    "impact": int,
                    "max_severity": str,
                },
                ...
            ],
        }

    Raises ``ValueError`` if the deal does not exist.
    """
    from app.models.deal import Deal
    from app.models.red_flag import RedFlag
    from app.models.agent_finding import AgentFinding
    from app.models.missing_document import MissingDocument

    # Validate deal exists
    if db.query(Deal).filter(Deal.id == deal_id).first() is None:
        raise ValueError(f"Deal {deal_id} not found")

    red_flags = (
        db.query(RedFlag)
        .filter(RedFlag.deal_id == deal_id)
        .all()
    )

    observations = (
        db.query(AgentFinding)
        .filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.category == "observation",
        )
        .all()
    )

    info_requests = (
        db.query(AgentFinding)
        .filter(
            AgentFinding.deal_id == deal_id,
            AgentFinding.category == "information_request",
        )
        .all()
    )

    missing_docs = (
        db.query(MissingDocument)
        .filter(MissingDocument.deal_id == deal_id)
        .all()
    )

    # ── Compute deductions ────────────────────────────────────────────────

    rf_impact = sum(
        _RED_FLAG_WEIGHTS.get(rf.severity.value, 0) for rf in red_flags
    )
    obs_impact = sum(
        _OBSERVATION_WEIGHTS.get(obs.severity.value if obs.severity else "low", 0)
        for obs in observations
    )
    ir_impact = len(info_requests) * _INFO_REQUEST_WEIGHT
    md_impact = len(missing_docs) * _MISSING_DOC_WEIGHT

    total_deduction = rf_impact + obs_impact + ir_impact + md_impact
    score = max(0, 100 - total_deduction)

    if score >= 80:
        risk_level = "low"
    elif score >= 60:
        risk_level = "medium"
    elif score >= 40:
        risk_level = "high"
    else:
        risk_level = "critical"

    # ── Category breakdown (red flags drive the categories) ───────────────

    categories: dict[str, dict] = {}
    for rf in red_flags:
        cat = (rf.category or "other").strip().lower()
        weight = _RED_FLAG_WEIGHTS.get(rf.severity.value, 0)
        sev_val = rf.severity.value

        if cat not in categories:
            categories[cat] = {"count": 0, "impact": 0, "max_severity": sev_val}
        categories[cat]["count"] += 1
        categories[cat]["impact"] += weight
        if _SEV_ORDER.get(sev_val, 0) > _SEV_ORDER.get(categories[cat]["max_severity"], 0):
            categories[cat]["max_severity"] = sev_val

    categories_list = sorted(
        [{"category": cat, **data} for cat, data in categories.items()],
        key=lambda x: (-x["impact"], x["category"]),
    )

    return {
        "deal_id": deal_id,
        "score": score,
        "risk_level": risk_level,
        "deductions": {
            "red_flags":            {"count": len(red_flags),    "impact": rf_impact},
            "observations":         {"count": len(observations), "impact": obs_impact},
            "information_requests": {"count": len(info_requests),"impact": ir_impact},
            "missing_documents":    {"count": len(missing_docs), "impact": md_impact},
        },
        "categories": categories_list,
    }
