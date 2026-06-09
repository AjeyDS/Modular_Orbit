# Orbit Modular Implementation Plan

## Goal

Build Orbit's modular base application from a fresh database, then convert the currently hardcoded features into developer-created modules one by one.

This plan assumes no legacy data migration. Existing code can be reused, but the new runtime model should be built around the modular architecture in [modular-architecture.md](./modular-architecture.md).

## Product Stance

Orbit v0 is a personal tool first and a platform later.

The implementation should prove these value moments before expanding the module system:

- **Capture**: throw life data into Orbit without organizing it perfectly.
- **Focus**: know what matters next and why.
- **Decide**: choose between options with goals in view.
- **Discuss**: talk to a Task, Plan, Document, or Note in context.

## Non-Goals For This Build

- No legacy data migration.
- No community module marketplace.
- No arbitrary user-authored backend code.
- No full drag-and-drop dashboard engine in the first slice.
- No offline-first client sync.
- No fully automatic privacy erasure rewrite.
- No broad refactor of visual design until the modular shell exists.

## Reuse Map

Reuse:

- `src/db.py` connection and schema style.
- `src/gemini_client.py` embedding and Gemini helpers.
- `src/llm_client.py` provider dispatch.
- `src/model_config.py` call-site registry.
- document parsing/chunking logic from `src/ingest.py`.
- useful task/plan behavior from `src/task_db.py` and `src/routers/plans.py`.
- current Decision Mode concepts from `src/decision.py`.
- current Settings/User Model UI concepts.
- existing React page/component patterns where they fit.

Do not preserve as primary architecture:

- fixed `/tasks`, `/log`, `/kb` assumptions as top-level concepts.
- `facets` as public naming.
- old folder/category graph taxonomy.
- any path where a feature bypasses `life_items`, Connection Review, or module registry.

## Prerequisites

Before coding:

- Confirm fresh database reset is acceptable.
- Do not reset the database implicitly; perform reset only as an explicit implementation step when we begin schema work.
- Confirm Postgres + pgvector remains the storage base.
- Confirm Gemini remains the first wired provider.
- Keep `UBIQUITOUS_LANGUAGE.md` and `docs/modular-architecture.md` as source-of-truth docs.
- Decide initial enabled modules: `logs`, `tasks`, `goals`, `documents`, `chat`.

Recommended first branch state:

- Keep current branch: `codex-modular-application`.
- Commit docs before implementation if you want a clean checkpoint.

## Phase 0: Foundation Slice

Purpose: prove the new spine with the smallest useful system.

Build:

- `life_items`
- developer module registry
- Logs as generalized module
- Tasks as extended-storage module
- stable Story Buckets
- `goals.md` with stable goal IDs
- Connection Review status
- Item Chat

Defer:

- Plans
- full Documents module
- Dashboard layout
- Story Weave automation
- community modules
- advanced suggestion feedback

Success criteria:

- A Log can become a Life Item.
- A Task can become a Life Item plus Side Table row in one transaction.
- Connection Review runs asynchronously and exposes status.
- Item Chat can discuss a Task using its payload and one-hop Connections.
- Deleting a Life Item cascades derived data.

## Phase 1: Core Schema

Add fresh schema primitives.

Tables:

- `modules`
- `module_instances`
- `life_items`
- `item_connections`
- `knowledge_chunks`
- `story_buckets`
- `bucket_updates`
- `dashboard_layouts`
- `module_settings`

Likely Side Tables:

- `task_items`

Important fields:

- `life_items.id`
- `life_items.module_instance_id`
- `life_items.item_type`
- `life_items.title`
- `life_items.description`
- `life_items.payload`
- `life_items.lifecycle_status`
- `life_items.connection_status`
- `life_items.chunk_status`
- `life_items.bucket_update_status`
- `life_items.source`
- `life_items.request_id`
- timestamps

Rules:

- `life_items.request_id` makes creates idempotent.
- Side Tables reference `life_items(id)` with cascade delete.
- Connections reference stable IDs, not names or file paths.
- Story Buckets have stable IDs separate from markdown filenames.

Validation:

- Unit test schema creation.
- Unit test idempotent Life Item create.
- Unit test Side Table cascade delete.
- Unit test allowed lifecycle status validation per module.

## Phase 2: Backend Module Registry

Create a developer-authored module registry.

Each module declares:

- `module_id`
- `name`
- `description`
- `roles`
- `storage_strategy`
- `valid_lifecycle_statuses`
- `retrieval_policy`
- `suggestion_threshold`
- `item_chat_enabled`
- optional `item_chat_system_prompt`
- frontend block metadata
- default settings

Initial modules:

- `logs`: generalized, capture/query/dashboard
- `tasks`: extended, capture/query/dashboard
- `goals`: markdown-backed with stable IDs, query
- `chat`: query/output
- `documents`: placeholder until Phase 7

Validation:

- Registry loads all modules.
- Module IDs are unique.
- Every module declares `active` and `deleted`.
- Extended modules declare Side Table rationale.
- Defaults can be restored.

## Phase 3: Life Item Service

Create the shared backend service that all modules use.

Flow:

```text
create_capture
  -> validate module
  -> create/update Life Item
  -> enqueue Connection Review
  -> apply Retrieval Policy
  -> create Bucket Update if needed
```

Rules:

- Life Item writes are transactional.
- Extended module writes insert `life_items` first, Side Table second, same transaction.
- Server-side lifecycle writes use Request IDs.
- Meaningful edits rerun Connection Review and refresh chunks.

Validation:

- Create generalized Life Item.
- Create extended Life Item plus Side Table.
- Retry create with same Request ID does not duplicate.
- Edit meaningful fields queues Connection Review.
- Delete removes Side Table, derived chunks, and Connections.

## Phase 4: Story Buckets And Goals

Build stable story identity before heavy retrieval work.

Story Buckets:

- seed initial buckets
- store stable bucket IDs
- map bucket IDs to markdown files
- support reviewed bucket creation/splitting
- keep filenames/display names editable without breaking Connections

Goals:

- keep `goals.md`
- add stable goal IDs with HTML comments or YAML frontmatter
- preserve manual promotion
- Connections point at goal IDs, not headings/text positions

Validation:

- Rename bucket file/display name without breaking Connections.
- Reorder goals in `goals.md` without breaking goal IDs.
- Promote Tentative Goal to Active while preserving ID.
- Connection Review can target bucket IDs and goal IDs.

## Phase 5: Connection Review

Implement async Connection Review.

Structure:

1. retrieval-based routing
2. parallel candidate scoring plus Connection Note
3. threshold decisions

Default candidate bounds:

- top 5 Story Buckets
- top 5 Goals
- top 5 Life Items
- top 3 Documents or Module Instances

Outputs:

- Connections
- Connection Notes
- relevance scores
- `should_create_chunks`
- `should_create_bucket_update`

Status:

- `connection_status`: `pending`, `complete`, `failed`
- failed candidates are retryable
- Life Item remains durable even if Connection Review fails

Validation:

- Pending status appears immediately after Life Item create.
- Successful review creates Connections.
- Failed review marks status failed and can retry.
- Candidate bounds are enforced.
- UI/API does not pretend pending status is complete.

## Phase 6: Logs Module

Convert Logs first because it is the simplest generalized module.

Build:

- capture log text
- create generalized Life Item
- apply Retrieval Policy
- run Connection Review
- create Bucket Update when meaningful
- list logs through module view

Validation:

- Create log.
- Log appears as Life Item.
- Log can create Knowledge Chunk if retrieval-worthy.
- Log can produce Bucket Update.
- Log can be archived/deleted but not completed.

## Phase 7: Tasks Module

Convert Tasks second because it proves extended storage.

Build:

- `task_items` Side Table
- create task
- update task
- complete task
- archive/delete task
- task list view
- task Item Chat entry point

Rules:

- Tasks support `active`, `completed`, `archived`, `deleted`.
- Module-specific state such as `blocked` lives in payload or Side Table.
- Completing preserves history.
- Deleting cascades derived data.

Validation:

- Task create writes `life_items` and `task_items` in one transaction.
- Complete changes Lifecycle Status to `completed`.
- Delete cascades.
- Task Item Chat sees current payload after edits.

## Phase 8: Item Chat

Build the Discuss value moment.

Scope:

- anchored to one Life Item
- one-hop Connection graph
- reload current payload and status each turn

Minimum Retrieval Toolset:

- `get_life_item`
- `get_item_connections`
- `get_connected_bucket_text`
- `get_connected_goal`
- `get_connected_item`
- `get_connected_document`
- `get_derived_chunks`

UI:

- web hover-reveal chat icon on Life Item rows
- side panel chat
- pending connection state visible
- inline "Open in Context Chat" action for broader questions

Validation:

- Item Chat answers from Task payload.
- Item Chat includes one-hop Connections.
- Item Chat does not silently run broad Context Chat.
- Payload edits are visible on next turn.

## Phase 9: Documents Module

Convert document upload into module form.

Build:

- Document Life Item
- document metadata
- unique document name
- document-level Connection Note
- full-text chunks by Retrieval Policy
- optional Bucket Update from document-level meaning

Reuse:

- parsing and chunking from `src/ingest.py`
- classifier pieces where useful

Validation:

- Upload document creates Life Item.
- Document has one Document Connection.
- Chunks point back to document Life Item.
- Rename unique name without breaking identity.
- Delete removes chunks and Connections.

## Phase 10: Plans Module

Convert Plans after Tasks and Documents.

Build:

- Plan Life Item
- plan Side Tables for tree/items
- progress tracking
- plan Item Chat
- plan summaries as retrievable chunks

Reuse:

- `src/routers/plans.py`
- `src/services/plan_parser.py`
- plan frontend components

Validation:

- Plan create writes Life Item and Side Tables.
- Plan progress is queryable exactly.
- Completing plan preserves history.
- Plan Item Chat can discuss progress and next steps.

## Phase 11: Chat Modes And Suggested Chat Actions

Add creation from chat after core modules work.

Modes:

- Free Chat
- Context Chat
- Deep Chat
- Decision Mode
- Item Chat

Suggested Chat Action flow:

```text
shape detection -> confidence bucket -> payload extraction -> Preview -> Confirmation -> Life Item
```

Rules:

- confidence is `low`, `medium`, or `high`
- numeric thresholds map from buckets
- ignore is no signal in v0
- explicit user requests bypass suggestion threshold but still require Preview

Validation:

- Explicit "add this to tasks" creates Preview.
- Suggested action appears only above threshold.
- `max_suggestions_per_session` is enforced.
- Confirmation writes through Life Item Service.

## Phase 12: Modular Frontend Shell

Only after core module flows work.

Build:

- sidebar from enabled Module Instances
- module settings
- enable/disable modules
- simple dashboard fixed slots
- module blocks
- module views

Rules:

- user selects from developer-created modules
- disabled modules disappear from sidebar/dashboard
- existing Life Items remain stored when module is disabled

Validation:

- Enable/disable Logs and Tasks.
- Sidebar reflects enabled modules.
- Dashboard renders blocks for enabled modules.
- Module settings restore defaults.

## Phase 13: Story Weave

Add the synthesis layer after enough Bucket Updates exist.

Build:

- Bucket Update Log statuses
- Story Weave manual trigger
- snapshot cutoff
- contradiction handling
- User Edit Lock enforcement
- reviewed bucket split/create suggestions

Validation:

- Pending updates merge into Story Bucket prose.
- New updates during run wait for next run.
- Contradictory updates preserve evolving thinking unless explicit correction.
- User-locked sections are not silently rewritten.

## Phase 14: Recommendations And Strategy

Add output-heavy modules later.

Build:

- Recommendation module
- Strategy module
- save only after confirmation
- retry before saving
- optional Life Item output

Validation:

- Generated output is not stored unless accepted.
- Accepted Strategy can become Life Item.
- Strategy can use Tasks, Plans, Goals, and Connections.

## Phase 15: React Modular Frontend

Replace the dependency-free static shell with a real React/Vite frontend that reuses the best parts of the legacy Orbit UI while speaking the modular backend contract.

Purpose:

- restore the old app's usability and polish
- keep the modular backend as the source of truth
- avoid compatibility shims that preserve old `/tasks`, `/log`, or `/kb` assumptions
- make module enablement visible in navigation, dashboard, and settings

Reuse:

- shell/navigation/theme patterns from `frontend/src/App.tsx`
- Chat page structure from `frontend/src/pages/ChatPage.tsx`
- task list, inline edit, completed/undo, and plan components from `frontend/src/components/tasks`
- log timeline/filter/capture components from `frontend/src/components/logs`
- knowledge upload/list components from `frontend/src/components/knowledge`
- Settings/User Model page concepts from `frontend/src/pages/SettingsPage.tsx`

Do not reuse unchanged:

- old `frontend/src/api.ts` endpoint assumptions
- integer Task IDs
- fixed top-level routes as the source of truth
- old folder/category Knowledge graph naming
- any UI path that creates data without the modular Life Item APIs

Build sequence:

1. Scaffold `modular-orbit/frontend` as a Vite React app.
2. Create a new typed API client for modular endpoints.
3. Build the modular app shell from `/shell/state`, `/shell/catalog`, and `/shell/instances`.
4. Port Logs as the first React module view.
5. Port Tasks as the first extended-storage React module view.
6. Add Item Chat side panel and hover/row actions for Life Items.
7. Port Plans using the modular `/modules/plans` API.
8. Port Documents/Knowledge with a modular document upload endpoint.
9. Port Chat modes and Capture Proposal preview/confirmation.
10. Port Settings/User Model after exposing missing Story Bucket APIs.
11. Add dashboard blocks for enabled modules.
12. Remove the old static shell once React reaches parity.

Rules:

- React routes are presentation, not domain identity. Module IDs and Module Instances come from the backend.
- The API client should expose modular concepts such as `LifeItemId`, `LifecycleStatus`, `AsyncStepStatus`, and module-specific view models.
- Components may be reused visually, but data types must be rewritten for UUID Life Items and normalized Lifecycle Status.
- Disabled modules disappear from sidebar/dashboard, but their existing Life Items remain queryable if re-enabled.
- Every Life Item row should show non-complete `connection_status`, `chunk_status`, or `bucket_update_status`.
- Item Chat is available only for modules where `item_chat_enabled` is true.

Backend gaps to close before or during this phase:

- Story Bucket/User Model HTTP APIs for bucket list, content edit, history, recent updates, revert, goal promotion, and Story Weave trigger.
- Modular document upload endpoint that accepts real files, parses them, creates Document Life Items, and reports upload status.
- Chat streaming endpoint or React fallback behavior for non-streaming `/chat/respond`.
- Task suggestion equivalent using the modular query/connection layer, if AI suggestions remain in the Tasks page.
- Plan parser endpoint compatible with modular Plan creation.

Validation:

- React build succeeds.
- Module catalog enable/disable changes sidebar and dashboard.
- Logs can be created, listed, archived, and deleted from React.
- Tasks can be created, edited, completed, archived, deleted, and discussed through Item Chat.
- Plans can be imported/created and progress can be updated.
- Documents can be uploaded, renamed, listed, archived, deleted, and discussed.
- Chat can produce Capture Proposal previews and confirmations.
- Settings can edit Story Buckets and promote goals without breaking stable IDs.
- The old static shell can be deleted without losing functionality.

## Phase 15A: Frontend Parity Matrix

Before implementing Phase 15, create a parity matrix that maps legacy frontend features to modular endpoints and identifies missing backend APIs.

Required columns:

- Legacy UI surface
- Legacy component/page
- Old endpoint
- Modular module or surface
- New endpoint
- Status: `ready`, `needs_backend`, `needs_adapter`, or `defer`

Initial matrix:

| Legacy UI Surface | Legacy Component/Page | Old Endpoint | Modular Surface | New Endpoint | Status |
| --- | --- | --- | --- | --- | --- |
| Chat streaming | `ChatPage` | `/chat/stream` | Chat modes | `/chat/respond` | `needs_adapter` |
| Decision Mode | `DecisionFrame` | `/decision/generate`, `/decision/submit` | Chat Decision Mode | not fully exposed | `needs_backend` |
| Log timeline | `LogPage`, log components | `/log` | Logs module | `/modules/logs` | `ready` |
| Task list | `TaskPage`, task components | `/tasks` | Tasks module | `/modules/tasks` | `needs_adapter` |
| AI task suggestions | `SuggestionsPanel` | `/suggest` | Tasks/query layer | not exposed | `needs_backend` |
| Plan import/detail | task plan components | `/plans`, `/plans/parse` | Plans module | `/modules/plans` | `needs_backend` |
| Knowledge upload/list | `KnowledgePage` | `/kb/upload`, `/kb/files` | Documents module | `/modules/documents` | `needs_backend` |
| Knowledge graph | `GraphView` | `/kb/graph` | Connections graph | not exposed | `defer` |
| User Model settings | `SettingsPage` | `/user-model/*` | Story Buckets/goals | not exposed | `needs_backend` |
| Module catalog | none in legacy | none | Shell | `/shell/*` | `ready` |

## Suggested Work Order

The first engineering run should stop after Phase 8.

That gives:

- fresh modular base
- Logs
- Tasks
- Story Buckets
- stable Goals
- Connection Review
- Item Chat

Then convert:

1. Documents
2. Plans
3. Chat creation
4. Frontend shell/dashboard
5. Story Weave
6. Recommendations/Strategy
7. React Modular Frontend

React Modular Frontend should start with Phase 15A, then implement one vertical slice at a time. Do not port all pages first and wire data later; each slice should become usable before the next one starts.

## Testing Strategy

Minimum test categories:

- schema creation
- module registry validation
- Life Item lifecycle
- idempotent Request IDs
- Side Table transactions
- cascade deletes
- valid Lifecycle Status enforcement
- Connection Review status transitions
- Retrieval Policy behavior
- Bucket Update creation
- Item Chat context boundaries
- module enable/disable behavior
- React API client contract tests
- React build checks
- frontend smoke tests for each module view

Prefer focused backend tests before frontend polish. The module spine should be boring, testable, and hard to bypass.
