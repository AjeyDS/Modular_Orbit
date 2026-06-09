"""Developer-authored module contract types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


LifecycleStatus = Literal["active", "completed", "archived", "deleted"]
ModuleRole = Literal["capture", "output", "query", "transform", "dashboard", "external_intake"]
StorageStrategy = Literal["generalized", "extended"]
RetrievalMode = Literal["none", "summary", "full_text", "selective"]
RetrievalMinSignal = Literal["always", "meaningful_only", "confirmed_only"]
RetrievalDeleteBehavior = Literal["delete", "archive"]


class FrontendBlock(BaseModel):
    """A fixed-size frontend block a module can render later."""

    block_id: str
    name: str
    size: Literal["small", "medium", "large", "wide", "full"]
    description: str = ""


class RetrievalPolicy(BaseModel):
    """How a module's Life Items participate in retrieval."""

    mode: RetrievalMode = "summary"
    chunk_source: tuple[str, ...] = ("title", "description", "payload")
    min_signal: RetrievalMinSignal = "meaningful_only"
    delete_behavior: RetrievalDeleteBehavior = "delete"
    create_chunks: bool = True
    create_bucket_updates: bool = True
    default_chunk_status: Literal["not_needed", "pending"] = "pending"
    notes: str = ""

    @model_validator(mode="after")
    def validate_policy(self) -> RetrievalPolicy:
        if self.mode == "none":
            self.create_chunks = False
            self.default_chunk_status = "not_needed"
        if not self.create_chunks:
            self.default_chunk_status = "not_needed"
        if self.create_chunks and self.default_chunk_status == "not_needed":
            raise ValueError("retrievable policies cannot default chunk_status to not_needed")
        return self


class ModuleDefinition(BaseModel):
    """The stable declaration for a developer-created module."""

    module_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    description: str
    roles: tuple[ModuleRole, ...]
    storage_strategy: StorageStrategy
    valid_lifecycle_statuses: tuple[LifecycleStatus, ...]
    retrieval_policy: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    suggestion_threshold: float | None = Field(default=0.8, ge=0.0, le=1.0)
    item_chat_enabled: bool = True
    item_chat_system_prompt: str | None = None
    frontend_blocks: tuple[FrontendBlock, ...] = ()
    default_settings: dict[str, object] = Field(default_factory=dict)
    side_table: str | None = None
    side_table_rationale: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> ModuleDefinition:
        statuses = set(self.valid_lifecycle_statuses)
        if "active" not in statuses or "deleted" not in statuses:
            raise ValueError("modules must support at least active and deleted lifecycle statuses")

        if len(self.roles) != len(set(self.roles)):
            raise ValueError("module roles must be unique")

        if self.storage_strategy == "extended":
            if not self.side_table:
                raise ValueError("extended modules must declare a Side Table")
            if not self.side_table_rationale:
                raise ValueError("extended modules must explain the Side Table rationale")
        elif self.side_table or self.side_table_rationale:
            raise ValueError("generalized modules must not declare Side Table fields")

        return self

    @property
    def id(self) -> str:
        return self.module_id
