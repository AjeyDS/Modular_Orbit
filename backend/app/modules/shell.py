"""Modular shell services for module enablement and dashboard composition."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel
from psycopg.types.json import Jsonb

from app.db import transaction
from app.modules.registry import ModuleRegistryError, restore_module_instance_defaults


class ModuleCatalogItem(BaseModel):
    id: str
    name: str
    description: str
    roles: list[str]
    storage_strategy: str
    valid_lifecycle_statuses: list[str]
    frontend_blocks: list[dict[str, Any]]
    default_settings: dict[str, Any]


class ModuleInstanceItem(BaseModel):
    id: UUID
    module_id: str
    module_name: str
    display_name: str
    enabled: bool
    settings: dict[str, Any]
    frontend_blocks: list[dict[str, Any]]


class SidebarItem(BaseModel):
    module_instance_id: UUID
    module_id: str
    label: str


class DashboardBlock(BaseModel):
    module_instance_id: UUID
    module_id: str
    block_id: str
    name: str
    size: str
    description: str = ""


class ShellState(BaseModel):
    sidebar: list[SidebarItem]
    dashboard_blocks: list[DashboardBlock]
    enabled_modules: list[ModuleInstanceItem]


class ModuleInstanceSettingsUpdate(BaseModel):
    settings: dict[str, Any]


def list_module_catalog() -> list[ModuleCatalogItem]:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, description, roles, storage_strategy,
                    valid_lifecycle_statuses, frontend_blocks, default_settings
                FROM modules
                ORDER BY name
                """
            )
            return [
                ModuleCatalogItem(
                    id=row["id"],
                    name=row["name"],
                    description=row["description"],
                    roles=row["roles"],
                    storage_strategy=row["storage_strategy"],
                    valid_lifecycle_statuses=row["valid_lifecycle_statuses"],
                    frontend_blocks=row["frontend_blocks"],
                    default_settings=row["default_settings"],
                )
                for row in cur.fetchall()
            ]


def list_module_instances(*, enabled_only: bool = False) -> list[ModuleInstanceItem]:
    with transaction() as conn:
        return _list_module_instances(conn, enabled_only=enabled_only)


def enable_module(module_id: str, *, display_name: str | None = None) -> ModuleInstanceItem:
    """Create or re-enable a Module Instance for a developer-created module."""
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM modules WHERE id = %s", (module_id,))
            module = cur.fetchone()
            if module is None:
                raise ModuleRegistryError(f"Unknown module: {module_id}")

            desired_name = display_name or module["name"]
            cur.execute(
                """
                SELECT mi.*, m.name AS module_name, m.frontend_blocks
                FROM module_instances mi
                JOIN modules m ON m.id = mi.module_id
                WHERE mi.module_id = %s AND mi.display_name = %s
                """,
                (module_id, desired_name),
            )
            existing = cur.fetchone()
            if existing is not None:
                cur.execute(
                    """
                    UPDATE module_instances
                    SET enabled = TRUE, updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (existing["id"],),
                )
                return get_module_instance(existing["id"], conn=conn)

            cur.execute(
                """
                INSERT INTO module_instances (module_id, display_name, enabled, settings)
                VALUES (%s, %s, TRUE, %s)
                RETURNING id
                """,
                (module_id, desired_name, Jsonb(module["default_settings"])),
            )
            instance_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO module_settings (module_instance_id, settings)
                VALUES (%s, %s)
                ON CONFLICT (module_instance_id) DO UPDATE SET
                    settings = EXCLUDED.settings,
                    updated_at = now()
                """,
                (instance_id, Jsonb(module["default_settings"])),
            )
            return get_module_instance(instance_id, conn=conn)


def set_module_instance_enabled(
    module_instance_id: UUID | str,
    *,
    enabled: bool,
) -> ModuleInstanceItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE module_instances
                SET enabled = %s, updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (enabled, module_instance_id),
            )
            if cur.fetchone() is None:
                raise ModuleRegistryError(f"Unknown module instance: {module_instance_id}")
            return get_module_instance(module_instance_id, conn=conn)


def update_module_instance_settings(
    module_instance_id: UUID | str,
    settings: dict[str, Any],
) -> ModuleInstanceItem:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE module_instances
                SET settings = %s, updated_at = now()
                WHERE id = %s
                RETURNING id
                """,
                (Jsonb(settings), module_instance_id),
            )
            if cur.fetchone() is None:
                raise ModuleRegistryError(f"Unknown module instance: {module_instance_id}")
            cur.execute(
                """
                INSERT INTO module_settings (module_instance_id, settings)
                VALUES (%s, %s)
                ON CONFLICT (module_instance_id) DO UPDATE SET
                    settings = EXCLUDED.settings,
                    updated_at = now()
                """,
                (module_instance_id, Jsonb(settings)),
            )
            return get_module_instance(module_instance_id, conn=conn)


def restore_module_instance_settings(module_instance_id: UUID | str) -> ModuleInstanceItem:
    with transaction() as conn:
        restore_module_instance_defaults(conn, module_instance_id)
        return get_module_instance(module_instance_id, conn=conn)


def get_shell_state() -> ShellState:
    enabled_modules = list_module_instances(enabled_only=True)
    sidebar = [
        SidebarItem(
            module_instance_id=instance.id,
            module_id=instance.module_id,
            label=instance.display_name,
        )
        for instance in enabled_modules
    ]
    dashboard_blocks = [
        DashboardBlock(
            module_instance_id=instance.id,
            module_id=instance.module_id,
            block_id=block["block_id"],
            name=block["name"],
            size=block["size"],
            description=block.get("description", ""),
        )
        for instance in enabled_modules
        for block in instance.frontend_blocks
    ]
    return ShellState(
        sidebar=sidebar,
        dashboard_blocks=dashboard_blocks,
        enabled_modules=enabled_modules,
    )


def get_module_instance(
    module_instance_id: UUID | str,
    *,
    conn=None,
) -> ModuleInstanceItem:
    if conn is None:
        with transaction() as owned_conn:
            return get_module_instance(module_instance_id, conn=owned_conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT mi.id, mi.module_id, m.name AS module_name, mi.display_name,
                mi.enabled, mi.settings, m.frontend_blocks
            FROM module_instances mi
            JOIN modules m ON m.id = mi.module_id
            WHERE mi.id = %s
            """,
            (module_instance_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ModuleRegistryError(f"Unknown module instance: {module_instance_id}")
        return _row_to_instance(row)


def _list_module_instances(conn, *, enabled_only: bool) -> list[ModuleInstanceItem]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT mi.id, mi.module_id, m.name AS module_name, mi.display_name,
                mi.enabled, mi.settings, m.frontend_blocks
            FROM module_instances mi
            JOIN modules m ON m.id = mi.module_id
            WHERE (%s = FALSE OR mi.enabled = TRUE)
            ORDER BY mi.enabled DESC, mi.display_name
            """,
            (enabled_only,),
        )
        return [_row_to_instance(row) for row in cur.fetchall()]


def _row_to_instance(row: dict[str, Any]) -> ModuleInstanceItem:
    return ModuleInstanceItem(
        id=row["id"],
        module_id=row["module_id"],
        module_name=row["module_name"],
        display_name=row["display_name"],
        enabled=row["enabled"],
        settings=row["settings"],
        frontend_blocks=row["frontend_blocks"],
    )
