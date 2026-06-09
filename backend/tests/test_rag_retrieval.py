from __future__ import annotations

from uuid import uuid4

from app.core.config import settings
from app.db import connect, ensure_schema
from app.modules import sync_module_registry
from app.modules.documents import DocumentCreate, create_document, remove_document
from app.rag import backfill_missing_embeddings, retrieve_chunks
from app.rag.backfill import embedding_status
from app.user_model import ensure_goals_seed, ensure_story_buckets


def _ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _vector(axis: int) -> list[float]:
    values = [0.0] * settings.embedding_dimension
    values[axis] = 1.0
    return values


def test_document_chunks_store_embeddings_and_vector_retrieval(monkeypatch, tmp_path) -> None:
    _ready(tmp_path)

    def fake_embed(contents, *, task_type: str):
        if isinstance(contents, list):
            return [_vector(5) if "warehouse" in content.lower() else _vector(6) for content in contents]
        return _vector(5) if "warehouse" in contents.lower() else _vector(6)

    monkeypatch.setattr("app.rag.retrieval.embed_content", fake_embed)

    matching = create_document(
        DocumentCreate(
            original_name="Warehouse Notes.md",
            content="Warehouse modeling, dbt lineage, and analytics engineering notes.",
            request_id=f"rag-matching-{uuid4().hex}",
        ),
        review=False,
    )
    other = create_document(
        DocumentCreate(
            original_name="Garden Notes.md",
            content="Garden planning, soil, watering cadence, and tomato seedlings.",
            request_id=f"rag-other-{uuid4().hex}",
        ),
        review=False,
    )

    chunks = retrieve_chunks("warehouse lineage", limit=1)

    assert chunks
    assert chunks[0].title == "Warehouse Notes.md"
    assert chunks[0].retrieval_mode == "vector"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT metadata, embedding IS NOT NULL AS has_embedding FROM knowledge_chunks WHERE life_item_id = %s", (matching.id,))
            row = cur.fetchone()
    assert row["has_embedding"] is True
    assert row["metadata"]["embedding_status"] == "complete"

    remove_document(matching.id)
    remove_document(other.id)


def test_retrieval_falls_back_to_text_when_embeddings_unavailable(tmp_path) -> None:
    _ready(tmp_path)
    document = create_document(
        DocumentCreate(
            original_name="Fallback Notes.md",
            content="Fallback retrieval should find this modular upload using plain lexical matching.",
            request_id=f"rag-fallback-{uuid4().hex}",
        ),
        review=False,
    )

    chunks = retrieve_chunks("lexical modular upload", limit=1)

    assert chunks
    assert chunks[0].title == "Fallback Notes.md"
    assert chunks[0].retrieval_mode == "text"

    remove_document(document.id)


def test_text_retrieval_can_find_document_by_metadata_when_query_mentions_resume(tmp_path) -> None:
    _ready(tmp_path)
    document = create_document(
        DocumentCreate(
            original_name="Resume.pdf",
            content="Python machine learning RAG pipelines and data science project experience.",
            unique_name="resume",
            request_id=f"rag-resume-{uuid4().hex}",
        ),
        review=False,
    )

    chunks = retrieve_chunks("what does my resume say about machine learning", limit=1)

    assert chunks
    assert chunks[0].title == "Resume.pdf"
    assert chunks[0].retrieval_mode == "text"

    remove_document(document.id)


def test_backfill_missing_embeddings(monkeypatch, tmp_path) -> None:
    _ready(tmp_path)
    document = create_document(
        DocumentCreate(
            original_name="Backfill Notes.md",
            content="Backfill this existing chunk after it was created without embeddings.",
            request_id=f"rag-backfill-{uuid4().hex}",
        ),
        review=False,
    )

    def fake_embed(contents, *, task_type: str):
        if isinstance(contents, list):
            return [_vector(0) for _ in contents]
        return _vector(0)

    monkeypatch.setattr("app.rag.retrieval.embed_content", fake_embed)

    updated = backfill_missing_embeddings(limit=10000)

    assert updated >= 1
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT metadata, embedding IS NOT NULL AS has_embedding FROM knowledge_chunks WHERE life_item_id = %s", (document.id,))
            row = cur.fetchone()

    assert row["has_embedding"] is True
    assert row["metadata"]["embedding_status"] == "complete"
    assert embedding_status()["missing_embeddings"] == 0

    remove_document(document.id)
