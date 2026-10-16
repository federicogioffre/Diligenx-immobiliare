"""The frontend's copies of the pipeline and of the vocabularies match the backend.

``apps/web/src/lib/pipeline.ts`` lists the stages so the deal page can render
the progress bar before any request returns; ``apps/web/src/lib/api.ts`` types
the areas, remedies and impacts. These tests fail when either side changes
without the other.
"""
import re
from pathlib import Path

from packages.agents.red_flag_aggregator import _VALID_IMPACTS, _VALID_REMEDY_TYPES
from packages.real_estate.areas import AREA_ORDER
from packages.real_estate.pipeline import STAGE_LIST

WEB = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def _union(source: str, anchor: str) -> list[str]:
    block = source[source.index(anchor):]
    block = block[:block.index("\n\n")]
    return re.findall(r"'([a-z_]+)'", block)


def test_pipeline_stages_match():
    source = (WEB / "lib" / "pipeline.ts").read_text(encoding="utf-8")
    stages = re.findall(r"agent_name: '([a-z_]+)', label: (['\"])(.+?)\2", source)
    assert [(name, label) for name, _, label in stages] == [(s.agent_name, s.label_it) for s in STAGE_LIST]


def test_area_remedy_and_impact_types_match():
    source = (WEB / "lib" / "api.ts").read_text(encoding="utf-8")
    assert _union(source, "export type DueDiligenceArea") == list(AREA_ORDER)
    assert _union(source, "  remedy_type:")[:len(_VALID_REMEDY_TYPES)] == list(_VALID_REMEDY_TYPES)
    impact_line = next(line for line in source.splitlines() if line.strip().startswith("impact:"))
    assert re.findall(r"'([a-z_]+)'", impact_line) == list(_VALID_IMPACTS)
