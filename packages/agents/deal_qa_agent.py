"""Deal question-answering agent (RAG).

Retrieves the most relevant document chunks for a user question, builds
a context window, and asks the LLM to answer with citations.

Pipeline::

    question → embed → similarity search → top-k chunks
              → build prompt with context → LLM → answer + cited_chunks
              → map cited indices back to document/page sources
"""
import json
import logging

from sqlalchemy.orm import Session

from packages.agents.deal_analysis_agent import (
    LLMProvider,
    get_llm_provider,
    _safe_json,
)
from packages.retrieval.embedding_service import (
    EmbeddingProvider,
)
from packages.retrieval.retrieval_service import (
    ChunkMatch,
    search_similar_chunks,
)

logger = logging.getLogger(__name__)

# Maximum number of chunks to include in the LLM context
_DEFAULT_TOP_K = 5


def answer_deal_question(
    deal_id: int,
    question: str,
    db: Session,
    *,
    top_k: int = _DEFAULT_TOP_K,
    llm_provider: LLMProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict:
    """Answer a question about a deal using retrieval-augmented generation.

    Returns::

        {
            "answer": str,
            "sources": [
                {"document_id": int, "page_number": int | None, "excerpt": str},
                ...
            ],
        }

    Raises ``ValueError`` if the deal does not exist.
    """
    from app.models.deal import Deal
    from packages.prompts.deal_prompts import DEAL_QA_PROMPT

    # ── Validate deal ─────────────────────────────────────────────────── #
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal is None:
        raise ValueError(f"Deal {deal_id} not found")

    llm = llm_provider or get_llm_provider()

    logger.info(
        "Answering question for deal %d: %r",
        deal_id,
        question[:80],
    )

    # ── 1. Retrieve relevant chunks ───────────────────────────────────── #
    matches: list[ChunkMatch] = search_similar_chunks(
        deal_id=deal_id,
        query=question,
        db=db,
        top_k=top_k,
        provider=embedding_provider,
    )

    if not matches:
        logger.info("No chunks found for deal %d — returning fallback.", deal_id)
        return {
            "answer": (
                "No document content is available for this deal yet. "
                "Please upload and process documents before asking questions."
            ),
            "sources": [],
        }

    # ── 2. Build context string ───────────────────────────────────────── #
    context_parts: list[str] = []
    for idx, m in enumerate(matches):
        header = f"[{idx}] (doc_id={m.document_id}, page={m.page_number})"
        context_parts.append(f"{header}\n{m.content}")

    context = "\n\n".join(context_parts)

    # ── 3. Ask the LLM ───────────────────────────────────────────────── #
    prompt = DEAL_QA_PROMPT.format(context=context, question=question)
    raw = llm.complete(prompt, max_tokens=1024)

    try:
        parsed = _safe_json(raw)
    except Exception:
        logger.warning("QA response parse error: %r", raw)
        parsed = {"answer": raw, "cited_chunks": []}

    answer_text: str = parsed.get("answer", raw) if isinstance(parsed, dict) else raw
    cited_indices: list[int] = (
        parsed.get("cited_chunks", []) if isinstance(parsed, dict) else []
    )

    # ── 4. Map cited chunk indices → sources ──────────────────────────── #
    sources: list[dict] = []
    seen = set()
    for idx in cited_indices:
        if not isinstance(idx, int) or idx < 0 or idx >= len(matches):
            continue
        m = matches[idx]
        key = (m.document_id, m.page_number)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "document_id": m.document_id,
            "page_number": m.page_number,
            "excerpt": m.content[:300],
        })

    # If LLM didn't cite anything but we have matches, include the top hit
    if not sources and matches:
        m = matches[0]
        sources.append({
            "document_id": m.document_id,
            "page_number": m.page_number,
            "excerpt": m.content[:300],
        })

    logger.info(
        "QA for deal %d: %d sources cited, answer length=%d.",
        deal_id,
        len(sources),
        len(answer_text),
    )

    return {
        "answer": answer_text,
        "sources": sources,
    }
