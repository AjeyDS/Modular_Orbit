"""Phase 1 schema primitives for Modular Orbit."""

from __future__ import annotations

from app.core.config import settings
from app.db.connection import connect


LIFECYCLE_STATUSES = ("active", "completed", "archived", "deleted")
ASYNC_STATUSES = ("pending", "complete", "failed")
OPTIONAL_ASYNC_STATUSES = ("not_needed", "pending", "complete", "failed")
BUCKET_UPDATE_STATUSES = ("pending", "merged", "superseded", "ignored", "failed")
STORY_BUCKET_STATUSES = ("active", "archived")
STORAGE_STRATEGIES = ("generalized", "extended")


def ensure_schema() -> None:
    """Create the fresh Modular Orbit schema if it does not already exist."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS modules (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
                    storage_strategy TEXT NOT NULL
                        CHECK (storage_strategy IN ('generalized', 'extended')),
                    valid_lifecycle_statuses JSONB NOT NULL DEFAULT '["active", "deleted"]'::jsonb,
                    retrieval_policy JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    suggestion_threshold DOUBLE PRECISION DEFAULT 0.8,
                    item_chat_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    item_chat_system_prompt TEXT,
                    frontend_blocks JSONB NOT NULL DEFAULT '[]'::jsonb,
                    default_settings JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    side_table TEXT,
                    side_table_rationale TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    CHECK (
                        jsonb_typeof(valid_lifecycle_statuses) = 'array'
                        AND valid_lifecycle_statuses ? 'active'
                        AND valid_lifecycle_statuses ? 'deleted'
                    )
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE modules
                ALTER COLUMN suggestion_threshold DROP NOT NULL
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS module_instances (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    module_id TEXT NOT NULL REFERENCES modules(id) ON DELETE RESTRICT,
                    display_name TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS life_items (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    parent_life_item_id UUID REFERENCES life_items(id) ON DELETE CASCADE,
                    module_instance_id UUID NOT NULL REFERENCES module_instances(id) ON DELETE RESTRICT,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    lifecycle_status TEXT NOT NULL DEFAULT 'active'
                        CHECK (lifecycle_status IN ('active', 'completed', 'archived', 'deleted')),
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    source JSONB NOT NULL DEFAULT '{}'::jsonb,
                    request_id TEXT NOT NULL UNIQUE,
                    connection_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (connection_status IN ('pending', 'complete', 'failed')),
                    chunk_status TEXT NOT NULL DEFAULT 'not_needed'
                        CHECK (chunk_status IN ('not_needed', 'pending', 'complete', 'failed')),
                    bucket_update_status TEXT NOT NULL DEFAULT 'not_needed'
                        CHECK (bucket_update_status IN ('not_needed', 'pending', 'complete', 'failed')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    deleted_at TIMESTAMPTZ
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE life_items
                ADD COLUMN IF NOT EXISTS parent_life_item_id UUID REFERENCES life_items(id) ON DELETE CASCADE
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS task_items (
                    life_item_id UUID PRIMARY KEY REFERENCES life_items(id) ON DELETE CASCADE,
                    due_date DATE,
                    priority INTEGER,
                    completed_at TIMESTAMPTZ,
                    module_status TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE task_items
                ADD COLUMN IF NOT EXISTS due_window TEXT NOT NULL DEFAULT 'this_week'
                    CHECK (due_window IN ('this_week', 'this_month', 'someday', 'exact'))
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS task_priority_suggestion_runs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'invalidated', 'failed')),
                    suggestion_text TEXT NOT NULL DEFAULT '',
                    ranked JSONB NOT NULL DEFAULT '[]'::jsonb,
                    skippable JSONB NOT NULL DEFAULT '[]'::jsonb,
                    sort_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    panel_visible BOOLEAN NOT NULL DEFAULT TRUE,
                    task_snapshot_hash TEXT NOT NULL DEFAULT '',
                    context_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    invalidated_at TIMESTAMPTZ
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_items (
                    life_item_id UUID PRIMARY KEY REFERENCES life_items(id) ON DELETE CASCADE,
                    unique_name TEXT NOT NULL UNIQUE
                        CHECK (unique_name ~ '^[a-z][a-z0-9_]*$'),
                    original_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT 'text/plain',
                    byte_size INTEGER NOT NULL DEFAULT 0,
                    content_sha256 TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE document_items
                ADD COLUMN IF NOT EXISTS category_tag TEXT NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS connection_summary TEXT NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS tag_status TEXT NOT NULL DEFAULT 'pending'
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_items (
                    life_item_id UUID PRIMARY KEY REFERENCES life_items(id) ON DELETE CASCADE,
                    progress_percent INTEGER NOT NULL DEFAULT 0
                        CHECK (progress_percent >= 0 AND progress_percent <= 100),
                    completed_steps INTEGER NOT NULL DEFAULT 0,
                    total_steps INTEGER NOT NULL DEFAULT 0,
                    completed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_steps (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    life_item_id UUID NOT NULL REFERENCES life_items(id) ON DELETE CASCADE,
                    parent_step_id UUID REFERENCES plan_steps(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'completed', 'archived')),
                    completed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS plan_step_items (
                    life_item_id UUID PRIMARY KEY REFERENCES life_items(id) ON DELETE CASCADE,
                    plan_life_item_id UUID NOT NULL REFERENCES life_items(id) ON DELETE CASCADE,
                    parent_step_life_item_id UUID REFERENCES life_items(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL DEFAULT 0,
                    completed_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS story_buckets (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    stable_key TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    is_splittable BOOLEAN NOT NULL DEFAULT FALSE,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'archived')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE story_buckets
                ADD COLUMN IF NOT EXISTS last_user_edit_at TIMESTAMPTZ
                """
            )
            cur.execute(
                """
                ALTER TABLE story_buckets
                ADD COLUMN IF NOT EXISTS content TEXT NOT NULL DEFAULT ''
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS goals (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    goal_id TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'tentative')),
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                "ALTER TABLE goals ADD COLUMN IF NOT EXISTS horizon TEXT NOT NULL DEFAULT 'long_term'"
            )
            cur.execute("ALTER TABLE goals ADD COLUMN IF NOT EXISTS target_date DATE")
            cur.execute("ALTER TABLE goals ADD COLUMN IF NOT EXISTS target_note TEXT")

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS item_connections (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    source_life_item_id UUID NOT NULL REFERENCES life_items(id) ON DELETE CASCADE,
                    target_type TEXT NOT NULL
                        CHECK (target_type IN (
                            'story_bucket', 'active_goal', 'tentative_goal',
                            'life_item', 'module_instance', 'document'
                        )),
                    target_id TEXT NOT NULL,
                    target_label TEXT NOT NULL DEFAULT '',
                    strength DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    connection_note TEXT NOT NULL DEFAULT '',
                    review_source TEXT NOT NULL DEFAULT 'connection_review',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(source_life_item_id, target_type, target_id)
                )
                """
            )

            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    life_item_id UUID NOT NULL REFERENCES life_items(id) ON DELETE CASCADE,
                    content TEXT NOT NULL,
                    embedding vector({settings.embedding_dimension}),
                    source_type TEXT NOT NULL DEFAULT 'life_item',
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS bucket_updates (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    story_bucket_id UUID NOT NULL REFERENCES story_buckets(id) ON DELETE CASCADE,
                    life_item_id UUID REFERENCES life_items(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'merged', 'superseded', 'ignored', 'failed')),
                    update_text TEXT NOT NULL,
                    source_event JSONB NOT NULL DEFAULT '{}'::jsonb,
                    weave_run_id UUID,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS story_weave_runs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    story_bucket_id UUID NOT NULL REFERENCES story_buckets(id) ON DELETE CASCADE,
                    snapshot_cutoff TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running', 'complete', 'skipped_locked', 'failed')),
                    merged_count INTEGER NOT NULL DEFAULT 0,
                    superseded_count INTEGER NOT NULL DEFAULT 0,
                    ignored_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_layouts (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name TEXT NOT NULL,
                    layout JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS module_settings (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    module_instance_id UUID NOT NULL
                        REFERENCES module_instances(id) ON DELETE CASCADE,
                    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    UNIQUE(module_instance_id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id TEXT PRIMARY KEY,
                    surfaced_suggestion_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                ALTER TABLE chat_sessions
                ADD COLUMN IF NOT EXISTS title TEXT
                """
            )
            cur.execute(
                """
                ALTER TABLE chat_sessions
                ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL
                        CHECK (role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    mode TEXT,
                    suggestions JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_messages (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id UUID NOT NULL REFERENCES life_items(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('assistant', 'user')),
                    content TEXT NOT NULL,
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_companion_messages_session
                    ON companion_messages (session_id, created_at)
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS capture_proposals (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
                    module_id TEXT NOT NULL REFERENCES modules(id) ON DELETE RESTRICT,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    source JSONB NOT NULL DEFAULT '{}'::jsonb,
                    confidence_bucket TEXT NOT NULL
                        CHECK (confidence_bucket IN ('low', 'medium', 'high')),
                    confidence_score DOUBLE PRECISION NOT NULL,
                    explicit_request BOOLEAN NOT NULL DEFAULT FALSE,
                    status TEXT NOT NULL DEFAULT 'previewed'
                        CHECK (status IN ('previewed', 'accepted', 'rejected')),
                    created_life_item_id UUID REFERENCES life_items(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_outputs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    module_id TEXT NOT NULL REFERENCES modules(id) ON DELETE RESTRICT,
                    prompt TEXT NOT NULL,
                    output_text TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                    status TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'accepted', 'rejected')),
                    retry_of UUID REFERENCES generated_outputs(id) ON DELETE SET NULL,
                    created_life_item_id UUID REFERENCES life_items(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

            cur.execute(
                """
                CREATE OR REPLACE FUNCTION enforce_life_item_lifecycle_status()
                RETURNS trigger AS $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM module_instances mi
                        JOIN modules m ON m.id = mi.module_id
                        WHERE mi.id = NEW.module_instance_id
                            AND m.valid_lifecycle_statuses ? NEW.lifecycle_status
                    ) THEN
                        RAISE EXCEPTION
                            'Lifecycle status % is not valid for module instance %',
                            NEW.lifecycle_status,
                            NEW.module_instance_id
                            USING ERRCODE = '23514';
                    END IF;

                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
            cur.execute(
                """
                DROP TRIGGER IF EXISTS trg_life_items_lifecycle_status
                ON life_items
                """
            )
            cur.execute(
                """
                CREATE TRIGGER trg_life_items_lifecycle_status
                BEFORE INSERT OR UPDATE OF lifecycle_status, module_instance_id
                ON life_items
                FOR EACH ROW
                EXECUTE FUNCTION enforce_life_item_lifecycle_status()
                """
            )

            cur.execute("CREATE INDEX IF NOT EXISTS idx_life_items_module_instance ON life_items(module_instance_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_life_items_parent ON life_items(parent_life_item_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_life_items_lifecycle_status ON life_items(lifecycle_status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_life_items_connection_status ON life_items(connection_status)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_task_priority_suggestion_runs_status_created "
                "ON task_priority_suggestion_runs(status, created_at DESC)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_document_items_unique_name ON document_items(unique_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_plan_steps_life_item ON plan_steps(life_item_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_plan_step_items_plan ON plan_step_items(plan_life_item_id)")
            cur.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_module_instances_unique_display "
                "ON module_instances(module_id, display_name)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_item_connections_source ON item_connections(source_life_item_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_item_connections_target ON item_connections(target_type, target_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_life_item ON knowledge_chunks(life_item_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source_type ON knowledge_chunks(source_type)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bucket_updates_bucket_status ON bucket_updates(story_bucket_id, status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_story_weave_runs_bucket ON story_weave_runs(story_bucket_id, created_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_capture_proposals_session ON capture_proposals(session_id, status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_generated_outputs_module_status ON generated_outputs(module_id, status)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created "
                "ON chat_messages(session_id, created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_last_message "
                "ON chat_sessions(last_message_at DESC NULLS LAST)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_goals_status_position "
                "ON goals(status, position)"
            )

        conn.commit()
