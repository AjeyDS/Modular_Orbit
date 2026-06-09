"""Registry persistence for developer-created modules."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.db.connection import connect
from app.modules.contracts import ModuleDefinition
from app.modules.definitions import INITIAL_MODULES


class ModuleRegistryError(ValueError):
    """Raised when developer-authored module declarations are invalid."""


def list_module_definitions() -> tuple[ModuleDefinition, ...]:
    return INITIAL_MODULES


def get_module_definition(module_id: str) -> ModuleDefinition:
    for definition in INITIAL_MODULES:
        if definition.module_id == module_id:
            return definition
    raise ModuleRegistryError(f"Unknown module: {module_id}")


def validate_module_registry(definitions: Iterable[ModuleDefinition] = INITIAL_MODULES) -> None:
    seen: set[str] = set()
    for definition in definitions:
        if definition.module_id in seen:
            raise ModuleRegistryError(f"Duplicate module id: {definition.module_id}")
        seen.add(definition.module_id)


def sync_module_registry(conn: Connection | None = None) -> None:
    """Upsert developer-authored module declarations into Postgres."""
    validate_module_registry()

    if conn is None:
        with connect() as owned_conn:
            sync_module_registry(owned_conn)
            owned_conn.commit()
        return

    with conn.cursor() as cur:
        for definition in INITIAL_MODULES:
            cur.execute(
                """
                INSERT INTO modules (
                    id, name, description, roles, storage_strategy,
                    valid_lifecycle_statuses, retrieval_policy,
                    suggestion_threshold, item_chat_enabled, item_chat_system_prompt,
                    frontend_blocks, default_settings, side_table, side_table_rationale,
                    updated_at
                )
                VALUES (
                    %(id)s, %(name)s, %(description)s, %(roles)s, %(storage_strategy)s,
                    %(valid_lifecycle_statuses)s, %(retrieval_policy)s,
                    %(suggestion_threshold)s, %(item_chat_enabled)s, %(item_chat_system_prompt)s,
                    %(frontend_blocks)s, %(default_settings)s, %(side_table)s,
                    %(side_table_rationale)s, now()
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    roles = EXCLUDED.roles,
                    storage_strategy = EXCLUDED.storage_strategy,
                    valid_lifecycle_statuses = EXCLUDED.valid_lifecycle_statuses,
                    retrieval_policy = EXCLUDED.retrieval_policy,
                    suggestion_threshold = EXCLUDED.suggestion_threshold,
                    item_chat_enabled = EXCLUDED.item_chat_enabled,
                    item_chat_system_prompt = EXCLUDED.item_chat_system_prompt,
                    frontend_blocks = EXCLUDED.frontend_blocks,
                    default_settings = EXCLUDED.default_settings,
                    side_table = EXCLUDED.side_table,
                    side_table_rationale = EXCLUDED.side_table_rationale,
                    updated_at = now()
                """,
                {
                    "id": definition.module_id,
                    "name": definition.name,
                    "description": definition.description,
                    "roles": Jsonb(list(definition.roles)),
                    "storage_strategy": definition.storage_strategy,
                    "valid_lifecycle_statuses": Jsonb(list(definition.valid_lifecycle_statuses)),
                    "retrieval_policy": Jsonb(definition.retrieval_policy.model_dump()),
                    "suggestion_threshold": definition.suggestion_threshold,
                    "item_chat_enabled": definition.item_chat_enabled,
                    "item_chat_system_prompt": definition.item_chat_system_prompt,
                    "frontend_blocks": Jsonb([block.model_dump() for block in definition.frontend_blocks]),
                    "default_settings": Jsonb(definition.default_settings),
                    "side_table": definition.side_table,
                    "side_table_rationale": definition.side_table_rationale,
                },
            )


def restore_module_instance_defaults(conn: Connection, module_instance_id: UUID | str) -> dict[str, object]:
    """Reset a Module Instance's settings to its Module's declared defaults."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.default_settings
            FROM module_instances mi
            JOIN modules m ON m.id = mi.module_id
            WHERE mi.id = %s
            """,
            (module_instance_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ModuleRegistryError(f"Unknown module instance: {module_instance_id}")

        default_settings = row["default_settings"]
        cur.execute(
            """
            UPDATE module_instances
            SET settings = %s, updated_at = now()
            WHERE id = %s
            """,
            (Jsonb(default_settings), module_instance_id),
        )
        cur.execute(
            """
            INSERT INTO module_settings (module_instance_id, settings, updated_at)
            VALUES (%s, %s, now())
            ON CONFLICT (module_instance_id) DO UPDATE SET
                settings = EXCLUDED.settings,
                updated_at = now()
            """,
            (module_instance_id, Jsonb(default_settings)),
        )

    return default_settings
