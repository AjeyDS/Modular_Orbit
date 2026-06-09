from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.main import app
from app.modules import sync_module_registry
from app.modules.documents import (
    DocumentAnnotation,
    DocumentCreate,
    DocumentNameConflictError,
    DocumentParseError,
    archive_document,
    create_document,
    create_document_from_upload,
    list_documents,
    remove_document,
    rename_document,
    update_document_annotation,
)
from app.user_model import ensure_goals_seed, ensure_story_buckets


@pytest.fixture(autouse=True)
def documents_ready(tmp_path) -> None:
    ensure_schema()
    sync_module_registry()
    with connect() as conn:
        ensure_story_buckets(tmp_path, conn)
        conn.commit()
    ensure_goals_seed(tmp_path)


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_create_document_writes_life_item_side_table_chunks_and_review(tmp_path) -> None:
    document = create_document(
        DocumentCreate(
            original_name="Career Notes.md",
            content="Career work identity, professional context, and role direction notes.",
            request_id=_request_id("document-create"),
        ),
        review_root=tmp_path,
    )

    assert document.unique_name == "career_notes"
    assert document.lifecycle_status == "active"
    assert document.connection_status == "complete"
    assert document.byte_size > 0

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.id AS module_id, di.unique_name
                FROM life_items li
                JOIN document_items di ON di.life_item_id = li.id
                JOIN module_instances mi ON mi.id = li.module_instance_id
                JOIN modules m ON m.id = mi.module_id
                WHERE li.id = %s
                """,
                (document.id,),
            )
            row = cur.fetchone()
            assert row["module_id"] == "documents"
            assert row["unique_name"] == "career_notes"

            cur.execute("SELECT COUNT(*) AS count FROM knowledge_chunks WHERE life_item_id = %s", (document.id,))
            assert cur.fetchone()["count"] >= 1

            cur.execute("SELECT COUNT(*) AS count FROM item_connections WHERE source_life_item_id = %s", (document.id,))
            assert cur.fetchone()["count"] >= 1

    remove_document(document.id)


def test_create_document_populates_annotation_fallback(tmp_path) -> None:
    document = create_document(
        DocumentCreate(
            original_name="career_notes.md",
            content="Planning a transition into staff engineering and mentoring.",
            request_id=_request_id("document-annotation"),
        ),
        review_root=tmp_path,
    )

    assert document.tag_status in {"complete", "failed"}
    assert document.category_tag != ""
    assert document.connection_summary != ""

    remove_document(document.id)


def test_update_document_annotation(tmp_path) -> None:
    document = create_document(
        DocumentCreate(
            original_name="n.md",
            content="hello world content",
            request_id=_request_id("document-annotation-update"),
        ),
        review_root=tmp_path,
    )

    updated = update_document_annotation(
        document.id,
        DocumentAnnotation(category_tag="job-search", connection_summary="Relates to your career goal."),
    )

    assert updated.category_tag == "job-search"
    assert updated.connection_summary == "Relates to your career goal."
    assert updated.tag_status == "complete"

    remove_document(document.id)


def test_create_document_auto_weaves_connected_buckets(tmp_path) -> None:
    document = create_document(
        DocumentCreate(
            original_name="career.md",
            content="Career work identity, professional context, role direction, promotion, mentoring, and leadership team.",
            request_id=_request_id("document-auto-weave"),
        ),
        review_root=tmp_path,
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM bucket_updates WHERE life_item_id = %s AND status = 'pending'",
                (document.id,),
            )
            pending = cur.fetchone()["n"]
            cur.execute(
                """
                SELECT sb.content
                FROM item_connections ic
                JOIN story_buckets sb ON sb.id = ic.target_id::uuid
                WHERE ic.source_life_item_id = %s
                    AND ic.target_type = 'story_bucket'
                LIMIT 1
                """,
                (document.id,),
            )
            row = cur.fetchone()
            woven_content = row["content"] if row else ""

    assert pending == 0
    assert document.connection_summary in woven_content

    remove_document(document.id)


def test_auto_unique_name_suffixes_existing_names() -> None:
    first = create_document(
        DocumentCreate(
            original_name="Same Name.md",
            content="First document about Orbit.",
            request_id=_request_id("same-name-one"),
        ),
        review=False,
    )
    second = create_document(
        DocumentCreate(
            original_name="Same Name.md",
            content="Second document about Orbit.",
            request_id=_request_id("same-name-two"),
        ),
        review=False,
    )

    assert first.unique_name == "same_name"
    assert second.unique_name == "same_name_2"

    remove_document(first.id)
    remove_document(second.id)


def test_vague_content_uses_untitled_fallback() -> None:
    document = create_document(
        DocumentCreate(
            original_name="123.txt",
            content="???",
            request_id=_request_id("vague-doc"),
        ),
        review=False,
    )

    assert document.unique_name.startswith("untitled_doc_")

    remove_document(document.id)


def test_create_document_from_markdown_upload_extracts_text() -> None:
    document = create_document_from_upload(
        original_name="Uploaded Notes.md",
        data=b"# Uploaded Notes\n\nOrbit should read files, create chunks, and keep the source name.",
        mime_type="text/markdown",
        review=False,
    )

    assert document.original_name == "Uploaded Notes.md"
    assert document.unique_name == "uploaded_notes"
    assert document.mime_type == "text/markdown"
    assert document.byte_size > 0

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT content FROM knowledge_chunks WHERE life_item_id = %s LIMIT 1", (document.id,))
            assert "Orbit should read files" in cur.fetchone()["content"]

    remove_document(document.id)


def test_unsupported_upload_type_raises_clear_parse_error() -> None:
    with pytest.raises(DocumentParseError, match="Unsupported document type"):
        create_document_from_upload(
            original_name="deck.pptx",
            data=b"not a real presentation",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            review=False,
        )


def test_explicit_duplicate_unique_name_conflicts() -> None:
    first = create_document(
        DocumentCreate(
            original_name="First.md",
            unique_name="conflict_doc",
            content="First document.",
            request_id=_request_id("conflict-one"),
        ),
        review=False,
    )

    with pytest.raises(DocumentNameConflictError) as exc:
        create_document(
            DocumentCreate(
                original_name="Second.md",
                unique_name="conflict_doc",
                content="Second document.",
                request_id=_request_id("conflict-two"),
            ),
            review=False,
        )

    assert str(exc.value) == "conflict_doc"
    remove_document(first.id)


def test_rename_document_updates_payload_chunks_and_releases_old_name() -> None:
    first = create_document(
        DocumentCreate(
            original_name="Rename Me.md",
            unique_name="rename_me",
            content="Rename document content.",
            request_id=_request_id("rename-one"),
        ),
        review=False,
    )

    renamed = rename_document(first.id, "renamed_doc")
    reused = create_document(
        DocumentCreate(
            original_name="Reuse.md",
            unique_name="rename_me",
            content="Old unique name can be reused after rename.",
            request_id=_request_id("rename-reuse"),
        ),
        review=False,
    )

    assert renamed.unique_name == "renamed_doc"
    assert reused.unique_name == "rename_me"

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT payload FROM life_items WHERE id = %s", (first.id,))
            assert cur.fetchone()["payload"]["unique_name"] == "renamed_doc"

            cur.execute("SELECT metadata FROM knowledge_chunks WHERE life_item_id = %s LIMIT 1", (first.id,))
            assert cur.fetchone()["metadata"]["unique_name"] == "renamed_doc"

    remove_document(first.id)
    remove_document(reused.id)


def test_rename_document_conflict_reports_name() -> None:
    first = create_document(
        DocumentCreate(
            original_name="One.md",
            unique_name="doc_one",
            content="One.",
            request_id=_request_id("rename-conflict-one"),
        ),
        review=False,
    )
    second = create_document(
        DocumentCreate(
            original_name="Two.md",
            unique_name="doc_two",
            content="Two.",
            request_id=_request_id("rename-conflict-two"),
        ),
        review=False,
    )

    with pytest.raises(DocumentNameConflictError) as exc:
        rename_document(second.id, "doc_one")

    assert str(exc.value) == "doc_one"

    remove_document(first.id)
    remove_document(second.id)


def test_list_archive_and_delete_documents() -> None:
    active = create_document(
        DocumentCreate(
            original_name="Active.md",
            content="Active document.",
            request_id=_request_id("active-document"),
        ),
        review=False,
    )
    archived = create_document(
        DocumentCreate(
            original_name="Archived.md",
            content="Archived document.",
            request_id=_request_id("archived-document"),
        ),
        review=False,
    )
    archive_document(archived.id)

    active_ids = {document.id for document in list_documents(status="active")}
    archived_ids = {document.id for document in list_documents(status="archived")}

    assert active.id in active_ids
    assert archived.id not in active_ids
    assert archived.id in archived_ids

    remove_document(active.id)
    remove_document(archived.id)


def test_delete_document_cascades_side_table_chunks_and_connections(tmp_path) -> None:
    document = create_document(
        DocumentCreate(
            original_name="Delete.md",
            content="Delete document about Orbit goals and decisions.",
            request_id=_request_id("delete-document"),
        ),
        review_root=tmp_path,
    )

    remove_document(document.id)

    with connect() as conn:
        with conn.cursor() as cur:
            for table, key in (
                ("life_items", "id"),
                ("document_items", "life_item_id"),
                ("knowledge_chunks", "life_item_id"),
                ("item_connections", "source_life_item_id"),
            ):
                cur.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {key} = %s", (document.id,))
                assert cur.fetchone()["count"] == 0


def test_documents_api_create_rename_conflict_without_archive_delete_routes() -> None:
    client = TestClient(app)
    request_id = _request_id("api-document")

    create_response = client.post(
        "/modules/documents",
        json={
            "original_name": "API Document.md",
            "content": "API document content for Orbit.",
            "unique_name": "api_document",
            "request_id": request_id,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["unique_name"] == "api_document"

    conflict_response = client.post(
        "/modules/documents",
        json={
            "original_name": "Conflict.md",
            "content": "Conflict document.",
            "unique_name": "api_document",
            "request_id": _request_id("api-document-conflict"),
        },
    )
    assert conflict_response.status_code == 409
    assert conflict_response.json()["detail"]["conflicting_name"] == "api_document"

    rename_response = client.patch(
        f"/modules/documents/{created['id']}/unique-name",
        json={"unique_name": "api_document_renamed"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["unique_name"] == "api_document_renamed"

    archive_response = client.post(f"/modules/documents/{created['id']}/archive")
    assert archive_response.status_code == 404

    delete_response = client.delete(f"/modules/documents/{created['id']}")
    assert delete_response.status_code == 405

    archived_list_response = client.get("/modules/documents", params={"status": "archived"})
    assert archived_list_response.status_code == 422

    remove_document(created["id"])


def test_documents_api_upload_markdown_file() -> None:
    client = TestClient(app)

    response = client.post(
        "/modules/documents/upload",
        files={"file": ("api_upload.md", b"# API Upload\n\nThis file came through multipart upload.", "text/markdown")},
    )

    assert response.status_code == 201
    created = response.json()
    assert created["original_name"] == "api_upload.md"
    assert created["unique_name"] == "api_upload"
    assert created["mime_type"] == "text/markdown"

    remove_document(created["id"])


def test_life_relevant_document_enriches_buckets(tmp_path, monkeypatch) -> None:
    import app.modules.documents as docs

    monkeypatch.setattr(docs, "_route_document_buckets", lambda content, summary: ["career"])
    create_document(
        DocumentCreate(original_name="plan.md", content="LLC self-employment action plan"),
        review=False,
        review_root=tmp_path,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM bucket_updates WHERE source_event->>'source' = 'documents'"
            )
            assert cur.fetchone()["c"] == 1


def test_reference_document_enriches_nothing(tmp_path, monkeypatch) -> None:
    import app.modules.documents as docs

    monkeypatch.setattr(docs, "_route_document_buckets", lambda content, summary: [])
    create_document(
        DocumentCreate(original_name="fee.pdf", content="SEVIS fee receipt number 123"),
        review=False,
        review_root=tmp_path,
    )
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM bucket_updates WHERE source_event->>'source' = 'documents'"
            )
            assert cur.fetchone()["c"] == 0


def test_documents_api_upload_rejects_unsupported_file() -> None:
    client = TestClient(app)

    response = client.post(
        "/modules/documents/upload",
        files={"file": ("archive.zip", b"zip-ish", "application/zip")},
    )

    assert response.status_code == 415
    assert "Unsupported document type" in response.json()["detail"]
