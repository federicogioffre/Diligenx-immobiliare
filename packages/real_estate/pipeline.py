"""The real-estate analysis pipeline: stages in order, with their labels.

Single source of truth for the stage list. The orchestrator runs it, the
resume checkpoint walks it, the SSE stream reports it and
``GET /deals/stages`` hands it to the frontend, so none of them keeps a copy.
"""
from __future__ import annotations

from typing import NamedTuple


class Stage(NamedTuple):
    key: str          # key in the pipeline summary dict
    agent_name: str   # AgentRun.agent_name
    label_it: str
    label_en: str
    reports_progress: bool = False


STAGE_LIST: tuple[Stage, ...] = (
    Stage("intake", "intake", "Inventario documenti", "Document intake"),
    Stage("document_routing", "document_router", "Classificazione documenti", "Document classification"),
    Stage("property_identity", "property_identity", "Identificazione dell'immobile", "Property identification"),
    Stage("title_chain_review", "title_chain_review", "Provenienza", "Title and chain of ownership", True),
    Stage("encumbrances_review", "encumbrances_review", "Ipoteche e gravami", "Mortgages and encumbrances", True),
    Stage("building_cadastral_review", "building_cadastral_review",
          "Urbanistica e catasto", "Planning and cadastre", True),
    Stage("condominium_occupancy_review", "condominium_occupancy_review",
          "Condominio e occupazione", "Condominium and occupancy", True),
    Stage("consistency_check", "consistency_check", "Confronto tra documenti", "Cross-document checks"),
    Stage("red_flag_aggregation", "red_flag_aggregation", "Rilievi", "Findings"),
    Stage("report_generation", "report_generation", "Relazione", "Report"),
)

#: ``(key, agent_name)`` pairs — the shape ``analysis_checkpoint`` walks.
STAGES: tuple[tuple[str, str], ...] = tuple((s.key, s.agent_name) for s in STAGE_LIST)

AGENT_NAMES: tuple[str, ...] = tuple(s.agent_name for s in STAGE_LIST)

#: Stages that publish batch progress (``analysis_progress``).
PROGRESS_AGENTS: tuple[str, ...] = tuple(s.agent_name for s in STAGE_LIST if s.reports_progress)

STAGE_LABELS: dict[str, tuple[str, str]] = {s.agent_name: (s.label_it, s.label_en) for s in STAGE_LIST}
