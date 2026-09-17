"""Regression checks for bounded retrieval and deal isolation."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.deal import Deal
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import DocumentChunk, EMBEDDING_DIM
from packages.retrieval.retrieval_service import (
    _postgres_search_statement,
    search_similar_chunks,
)


def test_sqlite_top_k_excludes_other_deals_and_unprocessed_documents(db, test_deal):
    other_deal = Deal(workspace_id=test_deal.workspace_id, title="Other deal")
    db.add(other_deal)
    db.flush()
    expected_ids = []
    for index, (deal_id, status, vector) in enumerate([
        (test_deal.id, DocumentStatus.processed, [0.0, 1.0]),
        (test_deal.id, DocumentStatus.processed, [1.0, 0.0]),
        (test_deal.id, DocumentStatus.processed, [0.8, 0.2]),
        (test_deal.id, DocumentStatus.failed, [1.0, 0.0]),
        (other_deal.id, DocumentStatus.processed, [1.0, 0.0]),
    ]):
        doc = Document(deal_id=deal_id, filename=f"{index}.txt", file_path=f"{index}.txt",
                       mime_type="text/plain", file_size=10, status=status)
        db.add(doc)
        db.flush()
        chunk = DocumentChunk(document_id=doc.id, chunk_index=0, content=str(index),
                              page_number=1, embedding=vector)
        db.add(chunk)
        db.flush()
        if index in (1, 2):
            expected_ids.append(chunk.id)
    db.commit()
    provider = Mock()
    provider.embed_texts.return_value = [[1.0, 0.0]]
    results = search_similar_chunks(test_deal.id, "needle", db, top_k=2, provider=provider)
    assert [result.chunk_id for result in results] == expected_ids
    assert [result.score for result in results] == [1.0, 0.9701]


@pytest.mark.parametrize("top_k", [0, -1])
def test_empty_top_k_does_not_call_external_embedding_provider(db, top_k):
    provider = Mock()
    assert search_similar_chunks(1, "query", db, top_k=top_k, provider=provider) == []
    provider.embed_texts.assert_not_called()


def test_postgres_query_bounds_rows_and_scopes_before_ranking():
    vector = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    statement = _postgres_search_statement(42, vector, 7)
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "documents.deal_id =" in sql
    assert "documents.status =" in sql
    assert "document_chunks.embedding IS NOT NULL" in sql
    assert "<=>" in sql
    assert "ORDER BY" in sql and "LIMIT" in sql
    assert compiled.params["query_embedding"] == vector
    assert 42 in compiled.params.values() and 7 in compiled.params.values()
    # The vector participates only in SQL distance calculation, never as a
    # selected result column that would transfer all 1536 floats per match.
    assert list(statement.selected_columns.keys()) == [
        "chunk_id", "document_id", "content", "page_number", "distance"
    ]


def test_postgres_path_executes_one_bounded_query_without_loading_orm_vectors():
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.execute.return_value = [SimpleNamespace(
        chunk_id=11, document_id=3, content="clause", page_number=2, distance=0.125
    )]
    provider = Mock()
    provider.embed_texts.return_value = [[1.0] + [0.0] * (EMBEDDING_DIM - 1)]
    result = search_similar_chunks(12, "clause", db, top_k=1, provider=provider)
    assert result[0].score == 0.875
    assert result[0].document_id == 3
    db.query.assert_not_called()
    db.execute.assert_called_once()


def test_postgres_dimension_mismatch_fails_before_database_query():
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    provider = Mock()
    provider.embed_texts.return_value = [[1.0, 0.0]]
    with pytest.raises(ValueError, match="dimension"):
        search_similar_chunks(1, "query", db, provider=provider)
    db.execute.assert_not_called()


@pytest.mark.parametrize("vector", [[float("nan")], [float("inf")], []])
def test_invalid_query_vectors_are_rejected(db, vector):
    provider = Mock()
    provider.embed_texts.return_value = [vector]
    with pytest.raises(ValueError, match="finite"):
        search_similar_chunks(1, "query", db, provider=provider)


@pytest.mark.parametrize("response", [
    "not valid JSON",
    json.dumps({"answer": "Unsupported claim", "cited_chunks": []}),
    json.dumps({"answer": "Unsupported claim", "cited_chunks": [99, -1, True, "0"]}),
    json.dumps({"answer": "Unsupported claim", "cited_chunks": None}),
    json.dumps({"answer": "Unsupported claim", "cited_chunks": "0"}),
    json.dumps({"answer": {"not": "text"}, "cited_chunks": [0]}),
    json.dumps({"answer": "", "cited_chunks": [0]}),
])
def test_qa_does_not_manufacture_citations(db, test_deal, monkeypatch, response):
    from packages.agents import deal_qa_agent
    from packages.retrieval.retrieval_service import ChunkMatch
    monkeypatch.setattr(deal_qa_agent, "search_similar_chunks", lambda **kwargs: [
        ChunkMatch(1, 10, "Potentially relevant text", 2, 0.9)
    ])
    provider = Mock()
    provider.complete.return_value = response
    result = deal_qa_agent.answer_deal_question(test_deal.id, "Question", db,
                                               llm_provider=provider)
    assert result["sources"] == []
    assert "does not support a verifiable answer" in result["answer"]
    assert "Unsupported claim" not in result["answer"]


def test_qa_keeps_only_valid_model_citations(db, test_deal, monkeypatch):
    from packages.agents import deal_qa_agent
    from packages.retrieval.retrieval_service import ChunkMatch
    monkeypatch.setattr(deal_qa_agent, "search_similar_chunks", lambda **kwargs: [
        ChunkMatch(1, 10, "Thirty days notice", 2, 0.9),
        ChunkMatch(2, 11, "Unrelated clause", 3, 0.8),
    ])
    provider = Mock()
    provider.complete.return_value = json.dumps({
        "answer": "Thirty days notice", "cited_chunks": [0, 0, True, 99]
    })
    result = deal_qa_agent.answer_deal_question(test_deal.id, "Notice?", db,
                                               llm_provider=provider)
    assert result == {"answer": "Thirty days notice", "sources": [
        {"document_id": 10, "page_number": 2, "excerpt": "Thirty days notice"}
    ]}


def test_load_runner_retries_same_upload_bytes_without_logging_secrets(monkeypatch):
    import io
    from urllib.error import HTTPError
    from scripts.beta_load import API, Metrics
    monkeypatch.setattr("scripts.beta_load.time.sleep", lambda _: None)
    api = API("https://staging.example.test", Metrics(), 30)
    api.token = "private-token"
    response = Mock()
    response.status = 201
    response.read.return_value = b'{"id": 123}'
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    api.opener.open = Mock(side_effect=[
        HTTPError("private-url", 503, "private-message", {}, io.BytesIO(b"private-body")),
        response,
    ])
    result = api.request("POST", "/documents/upload?deal_id=1", "upload",
                         body=b"same-document", expected=(201,), replay_safe=True)
    assert result == {"id": 123}
    requests = [call.args[0] for call in api.opener.open.call_args_list]
    assert [request.data for request in requests] == [b"same-document"] * 2
    summary = api.metrics.summary()
    assert summary["retries"] == 1
    assert "private" not in json.dumps(summary)


def test_load_runner_does_not_replay_ambiguous_creations(monkeypatch):
    from urllib.error import URLError
    from scripts.beta_load import API, CheckFailed, Metrics
    api = API("https://staging.example.test", Metrics(), 30)
    api.opener.open = Mock(side_effect=URLError("private credential in upstream error"))
    with pytest.raises(CheckFailed, match="unexpected HTTP status 0") as caught:
        api.request("POST", "/workspaces/", "create_workspace",
                    payload={"name": "test"}, expected=(201,))
    assert "private" not in str(caught.value)
    api.opener.open.assert_called_once()


def test_load_runner_dry_run_does_not_contact_staging(tmp_path, monkeypatch, capsys):
    from scripts import beta_load
    accounts = [{"token_env": f"BETA_TOKEN_{i}"} for i in range(5)]
    for account in accounts:
        monkeypatch.setenv(account["token_env"], "private-token")
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"accounts": accounts}), encoding="utf-8")
    network = Mock(side_effect=AssertionError("dry run contacted network"))
    monkeypatch.setattr(beta_load.API, "request", network)
    assert beta_load.main(["--base-url", "https://staging.example.test",
                           "--accounts", str(path), "--provider-mode", "fake"]) == 0
    network.assert_not_called()
    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["total_documents"] == 500
