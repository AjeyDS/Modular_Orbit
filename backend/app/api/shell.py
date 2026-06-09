"""HTTP API for the modular shell."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.modules.registry import ModuleRegistryError
from app.modules.shell import (
    ModuleCatalogItem,
    ModuleInstanceItem,
    ModuleInstanceSettingsUpdate,
    ShellState,
    enable_module,
    get_shell_state,
    list_module_catalog,
    list_module_instances,
    restore_module_instance_settings,
    set_module_instance_enabled,
    update_module_instance_settings,
)


router = APIRouter(prefix="/shell", tags=["shell"])


@router.get("/catalog", response_model=list[ModuleCatalogItem])
def catalog_endpoint() -> list[ModuleCatalogItem]:
    return list_module_catalog()


@router.get("/instances", response_model=list[ModuleInstanceItem])
def module_instances_endpoint(enabled_only: bool = False) -> list[ModuleInstanceItem]:
    return list_module_instances(enabled_only=enabled_only)


@router.get("/state", response_model=ShellState)
def shell_state_endpoint() -> ShellState:
    return get_shell_state()


@router.post("/modules/{module_id}/enable", response_model=ModuleInstanceItem)
def enable_module_endpoint(module_id: str) -> ModuleInstanceItem:
    try:
        return enable_module(module_id)
    except ModuleRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/instances/{module_instance_id}/enable", response_model=ModuleInstanceItem)
def enable_instance_endpoint(module_instance_id: UUID) -> ModuleInstanceItem:
    try:
        return set_module_instance_enabled(module_instance_id, enabled=True)
    except ModuleRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/instances/{module_instance_id}/disable", response_model=ModuleInstanceItem)
def disable_instance_endpoint(module_instance_id: UUID) -> ModuleInstanceItem:
    try:
        return set_module_instance_enabled(module_instance_id, enabled=False)
    except ModuleRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/instances/{module_instance_id}/settings", response_model=ModuleInstanceItem)
def update_settings_endpoint(
    module_instance_id: UUID,
    payload: ModuleInstanceSettingsUpdate,
) -> ModuleInstanceItem:
    try:
        return update_module_instance_settings(module_instance_id, payload.settings)
    except ModuleRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/instances/{module_instance_id}/restore-defaults", response_model=ModuleInstanceItem)
def restore_settings_endpoint(module_instance_id: UUID) -> ModuleInstanceItem:
    try:
        return restore_module_instance_settings(module_instance_id)
    except ModuleRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
