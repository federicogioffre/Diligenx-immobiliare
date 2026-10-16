"""End-to-end real-estate pipeline on a synthetic property dossier.

The fixture dossier is built to trigger every kind of output:

* the deed identifies the flat as sub. 5, the cadastral extract as sub. 7
  (cross-document identifier mismatch);
* the deed recites a donation of 2010 (still within the twenty-year window);
* the registry search shows a mortgage and a transcribed foreclosure (the
  foreclosure is raised by the keyword floor and must end up high);
* the minutes approve extraordinary works;
* there is no floor plan, permit or energy certificate (missing documents).
"""
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.models.agent_finding import AgentFinding
from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.deal import Deal, DealStatus
from app.models.document import Document, DocumentStatus
from app.models.missing_document import MissingDocument
from app.models.property_profile import PropertyProfile
from app.models.red_flag import RedFlag, Severity
from app.models.report import Report
from packages.agents.deal_analysis_agent import set_llm_provider
from packages.agents.orchestrator import run_deal_analysis_pipeline
from packages.real_estate.consistency import compare_profiles
from packages.real_estate.fake_provider import FakeRealEstateLLMProvider
from packages.real_estate.pipeline import STAGES

DEED = (
    "ATTO DI COMPRAVENDITA\n"
    "Repertorio n. 1234. L'anno duemilaquindici, in data 12/03/2015, avanti a me notaio Rossi.\n"
    "Oggetto: appartamento in Milano, censito al Catasto Fabbricati al Foglio 12 particella 345 sub. 5, "
    "categoria A/2, superficie catastale 95 mq.\n"
    "ACQUIRENTI: Mario Rossi; Anna Bianchi\n"
    + "Clausole di rito. " * 30 + "\n"
    "PROVENIENZA: l'immobile è pervenuto alla parte venditrice per atto di donazione "
    "trascritto il 10/05/2010 dalla madre.\n"
)
VISURA = (
    "VISURA CATASTALE STORICA per immobile\n"
    "Catasto Fabbricati, Comune di Milano, Foglio 12 particella 345 sub. 7 categoria A/2 "
    "superficie catastale 98 mq.\n"
    "INTESTATI: Mario Rossi; Luigi Verdi\n"
)
REGISTRY = (
    "ISPEZIONE IPOTECARIA - elenco sintetico delle formalità\n"
    "Ipoteca volontaria iscritta in data 01/06/2015 a favore di Banca Esempio S.p.A. "
    "a garanzia di mutuo.\n"
    + "Annotazioni varie. " * 20 + "\n"
    "Pignoramento immobiliare trascritto il 03/02/2024 a favore di Creditore S.r.l.\n"
)
MINUTES = (
    "VERBALE DI ASSEMBLEA del condominio di via Roma 1.\n"
    "L'assemblea approva all'unanimità i lavori straordinari di rifacimento della facciata.\n"
)


@pytest.fixture(autouse=True)
def fake_llm():
    set_llm_provider(FakeRealEstateLLMProvider())
    yield
    set_llm_provider(None)


def _doc(db: Session, deal: Deal, filename: str, text: str) -> Document:
    doc = Document(
        deal_id=deal.id, filename=filename, file_path=f"/tmp/{filename}", mime_type="text/plain",
        file_size=len(text), status=DocumentStatus.processed, raw_text=text, language="it", page_count=1,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@pytest.fixture
def dossier(db: Session, test_deal: Deal):
    return {
        "deed": _doc(db, test_deal, "Atto_compravendita_2015.txt", DEED),
        "visura": _doc(db, test_deal, "Visura_storica.txt", VISURA),
        "registry": _doc(db, test_deal, "Ispezione_ipotecaria.txt", REGISTRY),
        "minutes": _doc(db, test_deal, "Verbale_assemblea_2025.txt", MINUTES),
    }


def test_pipeline_completes_every_stage(db: Session, test_deal: Deal, dossier):
    result = run_deal_analysis_pipeline(test_deal.id, db)

    assert result["completed"], result["stages"]
    assert list(result["stages"]) == [key for key, _ in STAGES]
    runs = {r.agent_name: r for r in db.query(AgentRun).filter_by(deal_id=test_deal.id)}
    assert set(runs) == {name for _, name in STAGES}
    assert all(r.status == AgentRunStatus.completed for r in runs.values())
    db.refresh(test_deal)
    assert test_deal.status == DealStatus.reviewed


def test_routing_and_identity(db: Session, test_deal: Deal, dossier):
    result = run_deal_analysis_pipeline(test_deal.id, db)
    types = {c["document_id"]: c["document_type"] for c in result["stages"]["document_routing"]["classifications"]}
    assert types[dossier["visura"].id] == "visura_catastale"
    assert types[dossier["deed"].id] == "atto_provenienza"

    profiles = db.query(PropertyProfile).filter_by(deal_id=test_deal.id).all()
    by_doc = {p.source_document_id: p for p in profiles}
    assert by_doc[dossier["deed"].id].subalterno == "5"
    assert by_doc[dossier["visura"].id].subalterno == "7"
    assert by_doc[dossier["visura"].id].source_kind == "visura_catastale"


def test_cross_document_and_specialist_findings(db: Session, test_deal: Deal, dossier):
    run_deal_analysis_pipeline(test_deal.id, db)
    findings = db.query(AgentFinding).filter_by(deal_id=test_deal.id).all()
    categories = {(f.agent_name, f.category) for f in findings}

    assert ("consistency_check", "cadastral_identifier_mismatch") in categories
    assert ("title_chain_review", "donation_in_chain") in categories
    assert ("encumbrances_review", "mortgage") in categories
    assert ("encumbrances_review", "foreclosure") in categories
    assert ("condominium_occupancy_review", "approved_extraordinary_works") in categories

    donation = next(f for f in findings if f.category == "donation_in_chain" and f.agent_name == "title_chain_review"
                    and f.structured_payload_json.get("source") == "llm")
    assert donation.structured_payload_json["donation_window_open"] is True
    assert donation.severity == Severity.high


def test_red_flags_use_property_areas_and_floors(db: Session, test_deal: Deal, dossier):
    run_deal_analysis_pipeline(test_deal.id, db)
    flags = db.query(RedFlag).filter_by(deal_id=test_deal.id).all()
    assert flags
    areas = {f.area.value for f in flags if f.area}
    assert {"encumbrances", "cadastral", "title_chain"} <= areas
    foreclosure = next(f for f in flags if f.category == "foreclosure")
    assert foreclosure.severity == Severity.high
    mortgage = next(f for f in flags if f.category == "mortgage")
    assert mortgage.remedy_type == "seller_undertaking"


def test_missing_documents_follow_the_property_checklist(db: Session, test_deal: Deal, dossier):
    run_deal_analysis_pipeline(test_deal.id, db)
    missing = {m.document_category for m in db.query(MissingDocument).filter_by(deal_id=test_deal.id)}
    assert {"C.2", "D.1", "D.3", "F.1"} <= missing
    assert "C.1" not in missing and "B.1" not in missing and "E.2" not in missing


def test_report_is_a_property_report(db: Session, test_deal: Deal, dossier):
    run_deal_analysis_pipeline(test_deal.id, db)
    report = db.query(Report).filter_by(deal_id=test_deal.id).one()
    content = report.content
    assert content.startswith("# Relazione di Due Diligence Immobiliare")
    assert "## 2. Identificazione dell'Immobile" in content
    assert "Foglio | 12" in content and "Subalterno | 5" in content
    assert "Ipoteche, Trascrizioni Pregiudizievoli e Gravami" in content
    assert "12 marzo 2015" in content and "non è coperta" in content
    assert "### C. Catasto" in content
    assert "Corporate" not in content and "Societari" not in content


def test_resume_reuses_completed_stages(db: Session, test_deal: Deal, dossier):
    from packages.agents.analysis_checkpoint import CheckpointError, validate_resume

    run_deal_analysis_pipeline(test_deal.id, db)
    with pytest.raises(CheckpointError):
        validate_resume(db, test_deal.id)  # already complete

    db.query(AgentRun).filter_by(deal_id=test_deal.id, agent_name="red_flag_aggregation").one().status = "failed"
    db.commit()
    plan = validate_resume(db, test_deal.id)
    assert plan.completed[-1] == "consistency_check"
    result = run_deal_analysis_pipeline(test_deal.id, db, resume=True)
    assert result["completed"]
    assert result["stages"]["title_chain_review"] == {"resumed_from_checkpoint": True}


# ── Consistency check, unit level ────────────────────────────────────────────

def _profile(pid, kind, sub="5", holders=("Mario Rossi",), categoria="A/2", superficie="95 mq",
             data_titolo=None, doc=None):
    return SimpleNamespace(
        id=pid, source_kind=kind, source_document_id=doc or pid,
        source_document=SimpleNamespace(filename=f"{kind}.pdf"),
        foglio="12", particella="345", subalterno=sub, categoria=categoria, superficie=superficie,
        intestatari=[{"name": name} for name in holders], data_titolo=data_titolo,
    )


def test_owner_mismatch_is_high_without_overlap_and_medium_with_one():
    deed = _profile(1, "atto_provenienza", holders=("Mario Rossi",))
    visura = _profile(2, "visura_catastale", holders=("Luigi Verdi",))
    found = compare_profiles([deed, visura], as_of=date(2026, 10, 16))
    owner = next(f for f in found if f["category"] == "cadastral_owner_mismatch")
    assert owner["severity"] == "high"
    assert {d["document_id"] for d in owner["payload"]["compared_documents"]} == {1, 2}

    deed = _profile(1, "atto_provenienza", holders=("Rossi Mario", "Anna Bianchi"))
    found = compare_profiles([deed, _profile(2, "visura_catastale", holders=("Mario Rossi",))])
    assert next(f for f in found if f["category"] == "cadastral_owner_mismatch")["severity"] == "medium"


def test_name_order_and_case_do_not_make_a_mismatch():
    deed = _profile(1, "atto_provenienza", holders=("ROSSI Mario",))
    visura = _profile(2, "visura_catastale", holders=("Mario Rossi",))
    assert not [f for f in compare_profiles([deed, visura]) if f["category"] == "cadastral_owner_mismatch"]


def test_category_and_surface():
    deed = _profile(1, "atto_provenienza", categoria="A/2", superficie="95 mq")
    visura = _profile(2, "visura_catastale", categoria="A/3", superficie="120 mq")
    categories = {f["category"] for f in compare_profiles([deed, visura])}
    assert {"cadastral_category_mismatch", "surface_mismatch"} <= categories

    close = _profile(2, "visura_catastale", superficie="98 mq")
    assert "surface_mismatch" not in {f["category"] for f in compare_profiles([deed, close])}


def test_chain_coverage_finding():
    recent = _profile(1, "atto_provenienza", data_titolo="12/03/2015")
    assert "chain_gap_20y" in {f["category"] for f in compare_profiles([recent], as_of=date(2026, 10, 16))}
    old = _profile(2, "successione", data_titolo="01/01/2001")
    assert "chain_gap_20y" not in {f["category"] for f in compare_profiles([recent, old], as_of=date(2026, 10, 16))}


def test_no_cadastral_extract_means_no_identifier_finding():
    assert not compare_profiles([_profile(1, "atto_provenienza")])


# ── API ──────────────────────────────────────────────────────────────────────

def test_pipeline_stages_endpoint(client, auth_headers):
    response = client.get("/deals/pipeline-stages", headers=auth_headers)
    assert response.status_code == 200
    assert [s["agent_name"] for s in response.json()] == [name for _, name in STAGES]
    assert client.get("/deals/pipeline-stages").status_code == 401


def test_property_profiles_endpoint_consolidates_units(client, auth_headers, db, test_deal, dossier):
    run_deal_analysis_pipeline(test_deal.id, db)
    response = client.get(f"/deals/{test_deal.id}/property-profiles", headers=auth_headers)
    assert response.status_code == 200
    units = response.json()
    subs = sorted(unit["values"].get("subalterno") for unit in units)
    assert subs == ["5", "7"]
    deed_unit = next(unit for unit in units if unit["values"].get("subalterno") == "5")
    assert deed_unit["source_filenames"] == ["Atto_compravendita_2015.txt"]
    assert [h["name"] for h in deed_unit["intestatari"]] == ["Mario Rossi", "Anna Bianchi"]
