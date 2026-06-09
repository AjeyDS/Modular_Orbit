from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import connect, ensure_schema
from app.main import app
from app.modules import sync_module_registry
from app.modules.logs import LogCreate, create_log, remove_log
from app.modules.shell import (
    enable_module,
    get_shell_state,
    list_module_catalog,
    list_module_instances,
    restore_module_instance_settings,
    set_module_instance_enabled,
    update_module_instance_settings,
)


def _ready() -> None:
    ensure_schema()
    sync_module_registry()


def _request_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def test_catalog_exposes_developer_created_modules() -> None:
    _ready()

    catalog = list_module_catalog()
    by_id = {module.id: module for module in catalog}

    assert {"logs", "tasks", "plans", "documents", "chat"} <= set(by_id)
    assert by_id["tasks"].storage_strategy == "extended"
    assert by_id["logs"].frontend_blocks[0]["block_id"] == "recent_logs"


def test_enable_disable_modules_drives_shell_state() -> None:
    _ready()
    logs = enable_module("logs", display_name=f"Logs {uuid4().hex}")
    tasks = enable_module("tasks", display_name=f"Tasks {uuid4().hex}")

    state = get_shell_state()
    sidebar_ids = {item.module_instance_id for item in state.sidebar}
    block_module_ids = {block.module_id for block in state.dashboard_blocks}

    assert logs.id in sidebar_ids
    assert tasks.id in sidebar_ids
    assert {"logs", "tasks"} <= block_module_ids

    set_module_instance_enabled(logs.id, enabled=False)
    next_state = get_shell_state()
    next_sidebar_ids = {item.module_instance_id for item in next_state.sidebar}

    assert logs.id not in next_sidebar_ids
    assert tasks.id in next_sidebar_ids
    assert all(block.module_instance_id != logs.id for block in next_state.dashboard_blocks)


def test_disabling_module_instance_does_not_delete_life_items() -> None:
    _ready()
    log = create_log(
        LogCreate(
            text="This Life Item should remain after disabling Logs.",
            request_id=_request_id("shell-log"),
        ),
        review=False,
    )

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT mi.id
                FROM life_items li
                JOIN module_instances mi ON mi.id = li.module_instance_id
                WHERE li.id = %s
                """,
                (log.id,),
            )
            instance_id = cur.fetchone()["id"]

    set_module_instance_enabled(instance_id, enabled=False)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM life_items WHERE id = %s", (log.id,))
            assert cur.fetchone()["count"] == 1

    remove_log(log.id)


def test_settings_update_and_restore_defaults() -> None:
    _ready()
    instance = enable_module("tasks", display_name=f"Tasks {uuid4().hex}")

    updated = update_module_instance_settings(
        instance.id,
        {"default_priority": 4, "show_completed_days": 30},
    )
    assert updated.settings["default_priority"] == 4
    assert updated.settings["show_completed_days"] == 30

    restored = restore_module_instance_settings(instance.id)
    assert restored.settings == {
        "default_priority": None,
        "show_completed_days": 7,
    }


def test_list_module_instances_enabled_only() -> None:
    _ready()
    enabled = enable_module("documents", display_name=f"Documents {uuid4().hex}")
    disabled = enable_module("plans", display_name=f"Plans {uuid4().hex}")
    set_module_instance_enabled(disabled.id, enabled=False)

    enabled_ids = {instance.id for instance in list_module_instances(enabled_only=True)}

    assert enabled.id in enabled_ids
    assert disabled.id not in enabled_ids


def test_shell_api_enable_disable_settings_and_state() -> None:
    _ready()
    client = TestClient(app)

    enable_response = client.post("/shell/modules/logs/enable")
    assert enable_response.status_code == 200
    instance = enable_response.json()
    assert instance["module_id"] == "logs"
    assert instance["enabled"] is True

    state_response = client.get("/shell/state")
    assert state_response.status_code == 200
    assert any(item["module_instance_id"] == instance["id"] for item in state_response.json()["sidebar"])

    settings_response = client.patch(
        f"/shell/instances/{instance['id']}/settings",
        json={"settings": {"bucket_updates_enabled": False, "meaningfulness_threshold": "high"}},
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["settings"]["meaningfulness_threshold"] == "high"

    restore_response = client.post(f"/shell/instances/{instance['id']}/restore-defaults")
    assert restore_response.status_code == 200
    assert restore_response.json()["settings"]["meaningfulness_threshold"] == "medium"

    disable_response = client.post(f"/shell/instances/{instance['id']}/disable")
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False
