# Orbit Modular Architecture Spec

## Vision

Orbit is a modular life-data system. A person should be able to organize the data of their life, connect it to their goals, and use AI to make better decisions, plans, and recommendations.

The product should feel configurable like Obsidian, Notion, Airtable, Linear, or ClickUp, but the backend should stay centered on one stable loop:

```text
Capture -> Life Item -> Connection Review -> optional Knowledge Chunks -> Bucket Update -> Story Weave -> Context Chat
```

Modules may vary widely, but every meaningful piece of life data should pass through the same core language and lifecycle.

## Value Moments

Orbit's architecture exists to serve four recurring situations where the person gets concrete benefit:

- **Capture**: the person throws life data in without organizing it.
- **Focus**: the person knows what to do next and why.
- **Decide**: the person chooses between options with goals in view.
- **Discuss**: the person talks to a specific Task, Plan, or Document in context.

Future features must declare which Value Moment they serve. Features that cannot trace themselves to a Value Moment should be challenged before being added.

## Non-Negotiable Invariants

- A **Module** is optional; the core lifecycle is not.
- A **Life Item** is the source of truth for structured life data.
- Every **Life Item** has a row in `life_items`, regardless of whether the module uses extended storage.
- A **Life Item** and its Side Table row must be written in one Postgres transaction.
- Storage Strategy is immutable after the module has created its first Life Item, unless the module author ships an explicit migration.
- A **Knowledge Chunk** is a retrieval artifact, not the source of truth.
- A **Story Bucket** is the editable narrative layer of the **User Model**.
- Story Buckets and Goals are connection targets with stable IDs; filenames and display names are not identifiers.
- **Bucket Updates** are append-only records in a **Bucket Update Log**.
- **Story Weave** merges the **Bucket Update Log** into **Story Bucket** prose under **User Edit Lock** rules.
- Every meaningful **Life Item** should receive a **Connection Review**.
- A **Document** should receive one document-level **Document Connection** even if it produces many **Knowledge Chunks**.
- Chat-created data must use a **Capture Proposal**, **Preview**, and **Confirmation** before writing a **Life Item**.
- Deleting a **Life Item** cascade-deletes its Side Table row, derived Knowledge Chunks, and Connections in a single transaction.
- Completing a **Life Item** preserves history instead of deleting it.
- Lifecycle writes must be idempotent by Request ID.
- Async lifecycle steps must expose status, retry policy, and reconciliation behavior.
- Every asynchronous lifecycle step (Connection Review, Bucket Update, derived chunk generation) writes its Async Step Status to the Life Item it operates on. UI surfaces must display `pending` and `failed` states explicitly and must not render incomplete state as complete.
- Defaults must exist for every tunable setting, and the person should be able to restore defaults.

## Ubiquitous Language

This spec uses the terms defined in [UBIQUITOUS_LANGUAGE.md](../UBIQUITOUS_LANGUAGE.md).

Key distinctions:

- **Capture**: new incoming life data.
- **Life Item**: durable normalized record.
- **Item Payload**: flexible module-specific fields on a Life Item.
- **Knowledge Chunk**: retrievable text derived from a Life Item or Document.
- **Connection**: meaningful relationship to goals, buckets, modules, or other items.
- **Bucket Update**: small factual update recorded for markdown story memory.
- **Bucket Update Log**: append-only stream of Bucket Updates pending integration.
- **Story Weave**: periodic narrative synthesis of accumulated Bucket Updates.
- **Lifecycle Status**: cross-module state used for broad queries.
- **Request ID**: retry-safe identifier for lifecycle writes.
- **Value Moment**: recurring situation where Orbit gives concrete benefit.
- **Module**: optional capability bundle.
- **Block**: frontend surface for a Module Instance.

## Core Data Lifecycle

### 1. Capture

A **Capture** is any new life data entering Orbit.

Examples:

- A task entered manually.
- A plan imported from text.
- A log typed into the timeline.
- A document uploaded.
- A note saved from a vault module.
- An email imported through External Intake.
- A chat message that becomes a confirmed Capture Proposal.

Captures are not automatically trusted as durable records. A module's **Ingestion Rule** decides whether the Capture should become a Life Item, only update an existing item, produce a recommendation, or be ignored.

### 2. Life Item

A **Life Item** is the source of truth. It stores:

- owner Module Instance
- item type
- title
- description
- status
- source
- Item Payload
- timestamps
- optional parent/child references

Life Items have one normalized Lifecycle Status:

| Lifecycle Status | Meaning |
| --- | --- |
| `active` | Current and actionable or relevant. |
| `completed` | Finished and preserved as history. |
| `archived` | No longer active but intentionally retained. |
| `deleted` | Removed from normal use and pending or completed cleanup. |

Cross-module queries use only normalized Lifecycle Status. Module-specific status belongs in Item Payload or Side Tables and is used by module views and module logic.

The default architecture should use a hybrid storage model:

- Shared `life_items` table for common fields.
- Flexible JSON `payload` for module-specific data.
- Optional module-specific Side Tables only when a module needs strict relational behavior.

Tasks and Plans may use Side Tables because they need exact querying and status updates. New modules such as Brainstorms, Strategies, Notes, Prompts, and Learning Entries can start as generalized Life Items.

For modules with extended storage, `life_items` and the Side Table row are written in the same Postgres transaction. The base `life_items` row is inserted first, the Side Table row is inserted second, and the transaction commits only after both succeed. Deletes cascade from `life_items` to Side Tables, derived Knowledge Chunks, and Connections.

Editing a Life Item is assumed. Meaningful edits update the payload or Side Table, refresh derived Knowledge Chunks, and rerun Connection Review when fields relevant to meaning changed.

### 3. Connection Review

Every meaningful Life Item goes through **Connection Review**.

Connection Review produces:

- connected Story Buckets
- connected Active Goals or Tentative Goals when relevant
- connected Life Items when useful
- connected Module Instances when useful
- Connection Note
- relevance score
- whether the item should update Story Buckets
- whether the item should produce Knowledge Chunks

Connection Review runs asynchronously after the Life Item commit. Life Item surfaces must show `connection_status` whenever it is not `complete`; UI components should never silently render incomplete context as if it were complete.

The scoring prompt or scoring mechanism must be tunable in Settings. Orbit should ship with defaults and support restoring defaults.

### 4. Retrieval Policy

Not every Capture should be chunked for RAG.

The rule is:

```text
Every accepted Capture becomes or updates a Life Item. Only retrieval-worthy material becomes Knowledge Chunks.
```

Each Module defines a **Retrieval Policy**:

| Field | Meaning |
| --- | --- |
| `mode` | `none`, `summary`, `full_text`, or `selective` |
| `chunk_source` | Which fields become retrievable text |
| `min_signal` | `always`, `meaningful_only`, or `confirmed_only` |
| `delete_behavior` | Whether derived chunks are deleted or archived when the Life Item changes |

Suggested defaults:

| Module | Retrieval Policy |
| --- | --- |
| Task | `summary`, `meaningful_only` |
| Plan | `summary`, `always` |
| Log | `selective`, `meaningful_only` |
| Document | `full_text`, `always` |
| Brainstorm | `selective`, `confirmed_only` |
| Strategy | `summary`, `confirmed_only` |
| Recommendation | `summary`, `confirmed_only` |
| Prompt | `summary`, `always` |
| Learning Entry | `summary`, `meaningful_only` |

Structured module queries should answer exact state questions. RAG should answer semantic context questions. Context Chat should use both.

### 5. Bucket Update

Meaningful module data should create a **Bucket Update** record.

Bucket Updates should be small, factual, and append-only. They do not rewrite Story Bucket prose directly. Their job is to preserve pending story facts until Story Weave integrates them.

The story layer has three parts:

- Story Bucket markdown is the current narrative state.
- Bucket Update Log is the append-only stream of pending, merged, superseded, ignored, or failed factual updates.
- Story Weave is the merger that integrates pending updates into Story Bucket prose under User Edit Lock rules.

Bucket Updates are never physically pruned in v0. They are marked with status:

| Bucket Update Status | Meaning |
| --- | --- |
| `pending` | Waiting for Story Weave. |
| `merged` | Integrated into Story Bucket prose. |
| `superseded` | Replaced by a clearer later update. |
| `ignored` | Reviewed and intentionally left out of prose. |
| `failed` | Could not be processed and should be retried or reviewed. |

Story Weave processes a snapshot cutoff. When a run starts, it selects pending updates up to a fixed timestamp or id. Bucket Updates created while the run is in progress wait for the next run.

Contradictions are treated as evolving thinking by default. Sequential opinions on the same subject should be preserved as a narrative arc unless an update explicitly corrects a prior one with markers such as "actually," "I changed my mind," or "I was wrong." The default favors preserving the person's reasoning arc over collapsing to latest-wins.

Bucket Update behavior should be tunable:

- minimum meaningfulness score
- prompt text
- source/module eligibility
- per-bucket rules
- whether low-signal items skip bucket updates

User edits to Story Buckets should influence future Connection Reviews directly. The markdown story layer is not only output; it is also context for future enrichment.

### 6. Story Weave

**Story Weave** turns accumulated Bucket Updates into coherent narrative prose.

Story Weave should be slower and more deliberate than Bucket Update. It may run by:

- time interval
- number of Bucket Updates
- token-size threshold
- manual trigger
- module-specific trigger

These thresholds should be tunable in Settings with restore-default support.

Story Weave must respect User Edit Lock. Recent user-edited sections should be protected unless the person explicitly allows a rewrite.

Bucket creation and splitting are part of the product's core value, not distant platform work. v0 should keep seeded buckets, but it should also support reviewed bucket creation or splitting when a Story Bucket repeatedly accumulates separable themes. Connections point to bucket IDs, so renames or file moves do not break history.

## LLM Call Structure

The lifecycle describes what happens. This section describes how AI-heavy lifecycle steps should be structured as model calls.

Modules and shared services should follow these principles instead of inventing a new call pattern per feature.

### Principles

1. **Independent decisions are separate calls.**
   When a step produces multiple outputs and those outputs do not share reasoning, split them. Bucket relevance and goal relevance can be judged independently.

2. **Coupled decisions stay together.**
   When outputs share the same reasoning, keep them in one call. A relevance score and its Connection Note should be produced together.

3. **Cheap classifiers gate expensive generators.**
   Steps that often produce no output should run a cheap detection or threshold call first. Only run the more expensive generation call when the cheap call says yes.

4. **Parallelize independent fan-out.**
   When a step evaluates multiple candidates or themes, run those calls in parallel.

5. **Retrieve before generating.**
   Use structured queries or vector retrieval to find candidates before asking the model to judge them. Prefer model judgment over model invention.

6. **Make call outputs small and typed.**
   Each model call should return the smallest structured output that the next deterministic step needs.

### Recommended Call Structure

| Lifecycle Step | Recommended Call Structure |
| --- | --- |
| Capture Proposal generation | Two calls: shape detection first, then payload extraction only if Life-Item-Shaped Intent is detected. |
| Connection Review | Three logical stages: retrieval-based routing, parallel per-candidate scoring plus Connection Note, then threshold booleans. |
| Bucket Update writing | One small call per update, producing short factual text for the Bucket Update Log. |
| Story Weave | Multi-call: theme clustering, per-theme drafting in parallel, then integration under User Edit Lock. |
| Item Chat | One call per turn, scoped to the anchored Life Item plus its one-hop Connections. |
| Context Chat | One routed answer flow using Story Buckets, selected module tools, Connections, and Knowledge Chunks. |
| Deep Chat | Multi-query retrieval plus synthesis; slower and more deliberate than Context Chat. |
| Decision Mode | Multi-call when useful: option generation, per-option tradeoff analysis in parallel, then goal-alignment summary. |

### Connection Review Structure

Connection Review is the lifecycle step most likely to become too large if implemented as one prompt.

Recommended structure:

1. **Routing stage**
   Retrieve candidate Story Buckets, Goals, Module Instances, Documents, and Life Items from structured queries and embeddings.

   Candidate selection is retrieval-based, not generation-based. The default bounds are top 5 Story Buckets, top 5 Goals, top 5 Life Items, and top 3 Documents or Module Instances. Candidates are selected by vector similarity and structured filters, then judged by model calls.

2. **Candidate judgment stage**
   Score each candidate and write its Connection Note. Candidate judgments are independent and may run in parallel.

3. **Threshold stage**
   Decide whether the Life Item should produce Knowledge Chunks, create Bucket Updates, or skip optional outputs.

This keeps candidate discovery deterministic, candidate judgment focused, and lifecycle side effects explicit.

If one candidate judgment times out, Connection Review should persist successful judgments and mark the failed candidate for retry. Connection Review should not roll back the durable Life Item.

### Agentic Behavior

Orbit's lifecycle is orchestrated, not agentic. The model does not decide whether to run Connection Review, Bucket Update, Story Weave, or storage writes. The lifecycle decides.

Within a step, the model may have Scoped Agency. It may choose which candidate best fits a Connection, how to phrase a Connection Note, or which retrieved facts matter for an answer.

Chat is the main place where bounded tool use is allowed. Context Chat, Deep Chat, and Item Chat may use a constrained Retrieval Toolset, but free-form tool selection across the full system is out of scope.

## Module Contract

For v0, modules are developer-created. A later version may support shared community modules or plugin packs.

A Module declares:

- name
- description
- Module Roles
- Storage Strategy
- Side Table rationale when extended storage is used
- `valid_lifecycle_statuses: Array<'active' | 'completed' | 'archived' | 'deleted'>`
- Item Shapes
- Ingestion Rules
- Retrieval Policy
- Connection Review guidance
- frontend Blocks
- Module View behavior
- `suggestion_threshold`
- `item_chat_enabled`
- optional `item_chat_system_prompt`
- chat actions it supports
- default settings
- restore-default settings

Recommended Module Roles:

| Role | Meaning |
| --- | --- |
| `capture` | Accepts new Captures and creates Life Items. |
| `output` | Produces generated outputs from existing life data. |
| `query` | Provides tools for exact state lookup. |
| `transform` | Converts existing Life Items into new Life Items or outputs. |
| `dashboard` | Provides Blocks for the Dashboard. |
| `external_intake` | Accepts data from outside Orbit. |

Modules can have multiple roles. A Recommendation module may be mostly `output` and `query`. A Task module may be `capture`, `query`, and `dashboard`.

`valid_lifecycle_statuses` declares the subset of normalized statuses this module supports for its Life Items. It must include at least `active` and `deleted`. A module's UI should not offer status transitions outside this declared subset.

Suggested defaults:

| Module | Valid Lifecycle Statuses |
| --- | --- |
| Task | `active`, `completed`, `archived`, `deleted` |
| Plan | `active`, `completed`, `archived`, `deleted` |
| Note | `active`, `archived`, `deleted` |
| Log | `active`, `archived`, `deleted` |
| Document | `active`, `archived`, `deleted` |
| Brainstorm | `active`, `archived`, `deleted` |
| Strategy | `active`, `completed`, `archived`, `deleted` |
| Recommendation | `active`, `archived`, `deleted` |
| Prompt | `active`, `archived`, `deleted` |
| Learning Entry | `active`, `completed`, `archived`, `deleted` |

### Storage Strategy Criterion

Every Life Item has a base row in `life_items`. A module's Storage Strategy decides whether that base row is enough or whether the module also needs a Side Table joined by `life_item_id`.

The module declaration must include:

```text
storage_strategy: "generalized" | "extended"
```

If `storage_strategy` is `extended`, the module declaration must explain why a Side Table is needed.

Use extended storage if any of the following are true:

- The module needs to query individual fields, not just full text, at scale.
- The module has status transitions that need transactional integrity.
- The module's data will be joined on a hot path with another module's Side Table.

If all three are false, use generalized Life Items with Item Payload.

## Frontend Composition

Orbit's frontend should be organized around Module Instances and Blocks.

The person can:

- enable developer-created modules
- configure module behavior
- see module instances in the sidebar
- arrange Blocks on a Dashboard
- open a Module View for detailed work
- use Chat Actions to create or update Life Items

Blocks should use fixed size classes at first:

| Block Size | Meaning |
| --- | --- |
| `small` | Compact status or quick action. |
| `wide` | Horizontal summary. |
| `tall` | Vertical feed or list. |
| `large` | Main working block. |
| `full` | Page-width module surface. |

Avoid starting with a complex freeform layout engine. A fixed-grid dashboard with configurable slots is enough for the first modular version.

### Item Chat Surface

Every Life Item should be discussable in chat without leaving its context.

The minimum viable surface is:

- Web: hover-reveal chat icon on each Life Item row; clicking opens a side panel with Item Chat.
- Mobile: long-press on a Life Item opens an action sheet with Discuss as one option.

Persistent buttons next to every item are unnecessary for v0. Selection mode is reserved for later bulk actions. Keyboard shortcuts and command-palette scoping are deferred until there is real friction.

Item Chat is anchored on one Life Item and may traverse that item's Connection graph one hop. It may use the item's payload, connected Story Buckets, connected Goals, connected Documents, connected Life Items, and derived Knowledge Chunks. Broader context belongs to Context Chat or Deep Chat.

When Item Chat detects a question requiring multi-hop or broad context, it should surface an inline "Open in Context Chat" action instead of escalating silently.

Item Chat should reload the current Life Item payload and connection status on every turn. If Connection Review is still pending, Item Chat may answer from the payload but should show that connected context is still processing.

The minimum Item Chat Retrieval Toolset is:

- `get_life_item`
- `get_item_connections`
- `get_connected_bucket_text`
- `get_connected_goal`
- `get_connected_item`
- `get_connected_document`
- `get_derived_chunks`

## Chat And Creation Flow

Orbit should support multiple chat modes:

| Mode | Purpose |
| --- | --- |
| **Free Chat** | Conversational answer with minimal structured context. |
| **Context Chat** | Uses Story Buckets, Connections, structured module tools, and RAG. |
| **Deep Chat** | Uses broader retrieval and more deliberate reasoning. |
| **Decision Mode** | Produces options, tradeoffs, and goal-alignment. |
| **Item Chat** | Conversation anchored to a single Life Item and its one-hop Connection graph. |

Chat can create Life Items through **Chat Actions**, but only after confirmation.

Two creation paths are allowed:

- Explicit: the person says "add this to tasks" or "make this a plan."
- Suggested: Orbit ends a response with a restrained proposal such as "Add this to Tasks?"

Suggested creation must be tuned carefully. It should not appear after every useful answer. Suggested Chat Actions surface only when the response contains a Life-Item-Shaped Intent and the Capture Proposal confidence exceeds the module's `suggestion_threshold`. A global `max_suggestions_per_session` setting caps total suggestions regardless of individual confidence.

For v0, Capture Proposal confidence is produced by a cheap shape-detection call returning a discrete bucket: `low`, `medium`, or `high`. Numeric thresholds are derived from those buckets, not from LLM-reported probabilities.

Silent ignore is treated as no signal in v0. This means a noisy module produces no automatic correction. Threshold tuning remains a manual setting until dismissal feedback is deliberately designed.

The Preview should show:

- target Module Instance
- Life Item type
- title
- description
- Item Payload fields
- connected Story Buckets
- Connection Note
- whether Knowledge Chunks will be created
- whether Story Buckets will be updated

## Connection Model

Connections should become first-class records.

A Connection may relate a Life Item to:

- Story Bucket
- Active Goal
- Tentative Goal
- Life Item
- Module Instance
- Document

Each Connection should store:

- source Life Item or Document
- target type
- target id or path
- strength or relevance score
- Connection Note
- created timestamp
- review source

Connection Notes should be short and time-aware. They should explain why the relationship matters to the person now.

## Goals

Goals are connection targets and therefore need stable IDs.

### Goal Storage

Goals are stored in `goals.md` as structured markdown with stable goal IDs, using an HTML comment or YAML frontmatter per goal. The person reads goals as a coherent story. The system reads goal IDs for Connection integrity.

Example structure:

```markdown
<!-- goal: stay-in-dallas -->
## Stay in Dallas through OPT
Reason and context for the goal...

<!-- goal: build-data-career -->
## Build a data engineering career
Reason and context for the goal...
```

Renaming a goal's heading or rewording its prose does not break Connections because IDs are stable. Reorganizing goals within the file does not break Connections.

Manual promotion remains the rule. Tentative Goals and Active Goals share the stable-ID convention; promotion changes the goal's status or section, not its identity.

## Documents

Documents are special because they are usually coherent sources.

Document ingestion should produce:

- one durable Document record
- one unique document name
- one Document Connection
- many Knowledge Chunks when the document is retrieval-worthy
- optional Bucket Updates based on the document-level meaning

Do not require chunk-level Connection Notes for normal documents. Chunk-level notes can be added later only if there is a proven retrieval-quality need.

## Output-Heavy Modules

Some Modules mostly produce outputs instead of accepting many Captures.

Examples:

- Recommendation
- Strategy
- weekly review
- focus allocation
- decision summary

Output-heavy modules should support module-specific save behavior:

- save only after user accepts
- retry before saving
- save as Recommendation
- save as Strategy
- produce no Life Item unless confirmed

This should be tunable per module.

## External Intake

External Intake is the future path for email, files, APIs, webhooks, and app imports.

External Intake should normalize outside data into Captures and then use the same lifecycle. External sources should not bypass Connection Review, Retrieval Policy, or Bucket Update rules.

For now, External Intake can remain a module role and interface design. Full plugin security and community sharing can be deferred.

## Failure, Retry, And Erasure

All lifecycle orchestration is server-side in v0. Offline client creation is out of scope, but server writes still need to be safe to retry.

### Idempotency

Capture, Connection Review, Bucket Update, and Story Weave operations are idempotent at the Request ID level. Retrying the same Request ID must not duplicate Life Items, Connections, Knowledge Chunks, or Bucket Updates.

### Async Statuses

Every async lifecycle step needs:

- a status field on the target row or job row
- retry metadata
- a retry policy
- a reconciliation job

Implementation should enumerate the exact matrix of step, status field, retry policy, and reconciliation job before coding the shared lifecycle service.

Minimum statuses:

| Step | Status Field | Statuses |
| --- | --- | --- |
| Connection Review | `connection_status` | `pending`, `complete`, `failed` |
| Knowledge Chunk creation | `chunk_status` | `not_needed`, `pending`, `complete`, `failed` |
| Bucket Update writing | `bucket_update_status` | `not_needed`, `pending`, `complete`, `failed` |
| Story Weave | `weave_status` | `queued`, `running`, `complete`, `failed` |

Connection Review failure does not roll back the Life Item. Bucket Update failure does not roll back Connections. Failed steps are retried or surfaced for review.

### Deletion And Erasure

Normal delete removes the Life Item, Side Table row, derived Knowledge Chunks, and Connections. Completed items should use Lifecycle Status `completed`, not delete.

Privacy erasure is stronger than normal delete. It creates a system-generated Review Entry visible to the person, listing affected Story Buckets and any already-merged prose that may contain the erased subject. The person must review and accept proposed bucket edits before merged prose is rewritten. This is intentionally manual to avoid silent changes to the User Model.

## Settings And Tunability

Orbit should prefer configurable defaults over hardcoded behavior.

Settings should eventually support:

- meaningfulness scoring prompt or scoring mechanism
- Bucket Update threshold
- Story Weave interval
- Story Weave update-count threshold
- Story Weave token threshold
- Connection Review candidate limits
- per-module Retrieval Policy
- per-module Chat Action suggestions
- per-module Suggestion Thresholds
- global `max_suggestions_per_session`
- per-module Item Chat enablement and system prompt
- per-module output save behavior
- restore defaults

Settings should not make the first version heavy. The initial implementation can store defaults in code and expose only the most important settings first.

## Implementation Phases

### Phase 0: Smallest Testable Version

The first implementation should prove the architecture with the fewest moving parts.

Ship:

- `life_items`
- module registry
- Tasks as one extended-storage module
- Logs as one generalized module
- stable Story Buckets with reviewed creation or splitting
- goals.md with stable IDs for Active and Tentative Goals
- Connection Review status
- Item Chat

Defer:

- full dashboard layout
- community modules
- External Intake beyond current uploads
- full Story Weave automation
- advanced suggestion feedback

This slice should answer whether the Life Item identity, Connection Review, and Item Chat loop actually feels useful.

### Phase 1: Spec And Language

- Define ubiquitous language.
- Write modular architecture spec.
- Identify existing fixed-app concepts that map to new language.

### Phase 2: Core Tables And Registry

- Add modules table.
- Add module_instances table.
- Add life_items table.
- Add item_connections table.
- Add dashboard_layouts table.
- Add stable Story Bucket IDs separate from filenames.
- Add stable goal IDs in `goals.md`.
- Seed existing Tasks, Plans, Logs, Documents, and Chat modes as developer-created modules.

### Phase 3: Unified Lifecycle

- Create a shared Capture-to-Life-Item service.
- Implement shared LLM call orchestration for Capture Proposal generation, Connection Review, Bucket Update writing, and Story Weave.
- Implement Request ID idempotency for lifecycle writes.
- Enumerate async lifecycle status fields, retry policies, and reconciliation jobs.
- Add module Retrieval Policy handling.
- Add Connection Review output shape.
- Keep existing task/plan/document behavior working through adapters.

### Phase 4: Story Layer

- Make Bucket Update consume Connection Review output.
- Add tunable meaningfulness threshold.
- Add Bucket Update Log statuses and Story Weave snapshot cutoff.
- Add Story Weave job or manual trigger.
- Make user-edited Story Buckets influence future Connection Reviews.
- Add reviewed bucket creation and splitting.

### Phase 5: Modular Frontend

- Add frontend module registry.
- Add sidebar rendering from enabled Module Instances.
- Add Dashboard with fixed-size Blocks.
- Add Module View routing.
- Surface non-complete lifecycle statuses in Life Item views, dashboard blocks, and Item Chat.

### Phase 6: Chat Actions

- Add Capture Proposal generation.
- Add Preview UI.
- Add Confirmation flow.
- Add module-specific suggestion rules.
- Add `suggestion_threshold` enforcement.
- Add global `max_suggestions_per_session` cap.
- Add explicit and suggested creation paths.
- Add Item Chat surface: hover icon on web, long-press on mobile, side panel.
- Wire Item Chat retrieval to one Life Item plus its one-hop Connections.

### Phase 7: External Intake And Sharing

- Define External Intake adapter interface.
- Add first external source only when needed.
- Design module pack sharing/versioning later.

## Open Decisions

- How strict should Item Shape validation be for generalized Life Items?
- When community modules exist, should they run backend code or only declare data shapes, prompts, tools, and frontend blocks?
- How should shared module packs be versioned and updated?
- Which Strategy behaviors should become Life Items, which should remain generated views, and which should be saved only after confirmation?
- Should dismissed Suggested Chat Actions tune per-module Suggestion Thresholds over time?

## Current Recommendations

- Use a hybrid schema: common Life Item fields plus flexible Item Payload.
- Use Side Tables to extend `life_items` only when exact querying or workflow complexity demands it.
- Keep Storage Strategy immutable after first item unless a module author ships an explicit migration.
- Keep RAG optional through Retrieval Policy.
- Use normalized Lifecycle Status for cross-module queries; keep module-specific status internal to module logic.
- Make Connections first-class before adding more frontend modules.
- Keep module creation developer-owned for v0.
- Treat community modules as a later plugin-pack problem.
- Let Settings expose tunables gradually, with defaults and restore-default behavior from the start.
- Connection enrichment favors recall over precision; proactive suggestions favor precision over recall.
- Item Chat ships in v0 with hover-icon and side-panel behavior only.
- Use explicit "Open in Context Chat" escalation when Item Chat needs broader context.
- Treat privacy erasure as a manual Review Entry flow in v0.
