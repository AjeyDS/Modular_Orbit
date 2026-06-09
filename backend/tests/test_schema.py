from __future__ import annotations

from uuid import uuid4

import pytest
from psycopg.errors import CheckViolation, UniqueViolation

from app.db import connect, ensure_schema


def _module_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _insert_module(cur, *, storage_strategy: str = "generalized") -> str:
    module_id = _module_id("test_module")
    cur.execute(
        """
        INSERT INTO modules (
            id, name, description, roles, storage_strategy,
            valid_lifecycle_statuses, side_table, side_table_rationale
        )
        VALUES (
            %s, %s, 'test module', '["capture"]'::jsonb, %s,
            '["active", "completed", "archived", "deleted"]'::jsonb,
            %s, %s
        )
        """,
        (
            module_id,
            module_id,
            storage_strategy,
            "task_items" if storage_strategy == "extended" else None,
            "required for test exact queries" if storage_strategy == "extended" else None,
        ),
    )
    return module_id


def _insert_note_module(cur) -> str:
    module_id = _module_id("note_module")
    cur.execute(
        """
        INSERT INTO modules (
            id, name, description, roles, storage_strategy,
            valid_lifecycle_statuses
        )
        VALUES (
            %s, %s, 'note module', '["capture"]'::jsonb, 'generalized',
            '["active", "archived", "deleted"]'::jsonb
        )
        """,
        (module_id, module_id),
    )
    return module_id


def _insert_module_instance(cur, module_id: str) -> str:
    cur.execute(
        """
        INSERT INTO module_instances (module_id, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (module_id, module_id),
    )
    return str(cur.fetchone()["id"])


def _insert_life_item(cur, module_instance_id: str, request_id: str | None = None) -> str:
    cur.execute(
        """
        INSERT INTO life_items (
            module_instance_id, item_type, title, description, request_id
        )
        VALUES (%s, 'test_item', 'Test item', 'Test description', %s)
        RETURNING id
        """,
        (module_instance_id, request_id or f"test-request-{uuid4().hex}"),
    )
    return str(cur.fetchone()["id"])


@pytest.fixture(autouse=True)
def schema_ready() -> None:
    ensure_schema()


def test_phase_one_tables_exist() -> None:
    expected = {
        "modules",
        "module_instances",
        "life_items",
        "task_items",
        "document_items",
        "plan_items",
        "plan_steps",
        "item_connections",
        "knowledge_chunks",
        "story_buckets",
        "bucket_updates",
        "dashboard_layouts",
        "module_settings",
        "chat_sessions",
        "capture_proposals",
        "story_weave_runs",
        "generated_outputs",
    }

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                    AND table_name = ANY(%s)
                """,
                (list(expected),),
            )
            found = {row["table_name"] for row in cur.fetchall()}

    assert expected <= found


def test_document_items_has_annotation_columns() -> None:
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'document_items'
                    AND column_name IN ('category_tag', 'connection_summary', 'tag_status')
                """
            )
            cols = {row["column_name"] for row in cur.fetchall()}

    assert cols == {"category_tag", "connection_summary", "tag_status"}


def test_task_items_has_due_window() -> None:
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'task_items' AND column_name = 'due_window'
                """
            )
            assert cur.fetchone() is not None


def test_life_item_request_id_is_unique() -> None:
    request_id = f"duplicate-request-{uuid4().hex}"

    with connect() as conn:
        with conn.cursor() as cur:
            module_id = _insert_module(cur)
            instance_id = _insert_module_instance(cur, module_id)
            _insert_life_item(cur, instance_id, request_id=request_id)
            with pytest.raises(UniqueViolation):
                _insert_life_item(cur, instance_id, request_id=request_id)
        conn.rollback()


def test_lifecycle_status_is_normalized() -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            module_id = _insert_module(cur)
            instance_id = _insert_module_instance(cur, module_id)
            life_item_id = _insert_life_item(cur, instance_id)

            cur.execute(
                "UPDATE life_items SET lifecycle_status = 'completed' WHERE id = %s",
                (life_item_id,),
            )
            cur.execute(
                "SELECT lifecycle_status FROM life_items WHERE id = %s",
                (life_item_id,),
            )
            assert cur.fetchone()["lifecycle_status"] == "completed"

            with pytest.raises(CheckViolation):
                cur.execute(
                    "UPDATE life_items SET lifecycle_status = 'blocked' WHERE id = %s",
                    (life_item_id,),
                )
        conn.rollback()


def test_lifecycle_status_must_be_valid_for_module() -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            module_id = _insert_note_module(cur)
            instance_id = _insert_module_instance(cur, module_id)
            life_item_id = _insert_life_item(cur, instance_id)

            cur.execute(
                "UPDATE life_items SET lifecycle_status = 'archived' WHERE id = %s",
                (life_item_id,),
            )
            cur.execute(
                "SELECT lifecycle_status FROM life_items WHERE id = %s",
                (life_item_id,),
            )
            assert cur.fetchone()["lifecycle_status"] == "archived"

            with pytest.raises(CheckViolation):
                cur.execute(
                    "UPDATE life_items SET lifecycle_status = 'completed' WHERE id = %s",
                    (life_item_id,),
                )
        conn.rollback()


def test_life_item_delete_cascades_side_table_chunks_and_connections() -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            module_id = _insert_module(cur, storage_strategy="extended")
            instance_id = _insert_module_instance(cur, module_id)
            life_item_id = _insert_life_item(cur, instance_id)

            cur.execute(
                "INSERT INTO task_items (life_item_id, priority) VALUES (%s, 1)",
                (life_item_id,),
            )
            cur.execute(
                """
                INSERT INTO knowledge_chunks (life_item_id, content)
                VALUES (%s, 'retrievable test content')
                RETURNING id
                """,
                (life_item_id,),
            )
            chunk_id = str(cur.fetchone()["id"])
            cur.execute(
                """
                INSERT INTO item_connections (
                    source_life_item_id, target_type, target_id, target_label, strength
                )
                VALUES (%s, 'story_bucket', 'bucket-test', 'Bucket Test', 0.9)
                RETURNING id
                """,
                (life_item_id,),
            )
            connection_id = str(cur.fetchone()["id"])

            cur.execute("DELETE FROM life_items WHERE id = %s", (life_item_id,))

            for table, key, value in (
                ("task_items", "life_item_id", life_item_id),
                ("knowledge_chunks", "id", chunk_id),
                ("item_connections", "id", connection_id),
            ):
                cur.execute(f"SELECT COUNT(*) AS count FROM {table} WHERE {key} = %s", (value,))
                assert cur.fetchone()["count"] == 0
        conn.rollback()
