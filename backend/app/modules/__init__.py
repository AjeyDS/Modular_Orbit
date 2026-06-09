"""Developer-created module registry."""
"""Developer-created module registry."""

from app.modules.contracts import FrontendBlock, ModuleDefinition, RetrievalPolicy
from app.modules.definitions import INITIAL_MODULES
from app.modules.registry import (
    ModuleRegistryError,
    get_module_definition,
    list_module_definitions,
    restore_module_instance_defaults,
    sync_module_registry,
    validate_module_registry,
)
from app.modules.shell import (
    enable_module,
    get_shell_state,
    list_module_catalog,
    list_module_instances,
)

__all__ = [
    "FrontendBlock",
    "INITIAL_MODULES",
    "ModuleDefinition",
    "ModuleRegistryError",
    "RetrievalPolicy",
    "get_module_definition",
    "enable_module",
    "get_shell_state",
    "list_module_catalog",
    "list_module_definitions",
    "list_module_instances",
    "restore_module_instance_defaults",
    "sync_module_registry",
    "validate_module_registry",
]
