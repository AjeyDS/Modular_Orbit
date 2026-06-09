# Ubiquitous Language

## Core purpose

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Orbit** | A personal AI system for organizing life data and using it to make better decisions. | App, tool, assistant |
| **Life Data** | Information from the person's life that Orbit can organize, remember, retrieve, or reason over. | Data, stuff, content |
| **User Model** | Orbit's editable understanding of the person, expressed as Story Buckets, goals, and the Connection graph linking Life Items to story. | Profile, memory, persona |
| **Knowledge Base** | The retrievable store of information used to answer questions and ground AI reasoning. | RAG DB, vector store, memory |
| **Orchestrated Lifecycle** | The fixed sequence Orbit uses to turn Captures into connected, retrievable, and story-aware Life Items. | Agent flow, pipeline |
| **Value Moment** | A recurring situation where Orbit gives the person concrete benefit: Capture, Focus, Decide, or Discuss. | Use case, workflow, feature |

## People

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Person** | The human whose life data, goals, and context Orbit is organizing. | Customer, user, owner |
| **User** | The authentication identity operating Orbit. | Account, login, person |
| **Domain Expert** | The person deciding how Orbit should model life data and behavior. | Stakeholder, product owner |

## Modular workspace

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Module** | An optional capability that defines a kind of life data, how it is captured, and how it appears in Orbit. | Feature, plugin, app, block |
| **Module Instance** | A configured copy of a module that the person has added to their workspace. | Installed module, enabled feature |
| **Module Role** | A capability a module is allowed to perform, such as capture, output, query, transform, dashboard, or external intake. | Permission, type, mode |
| **Storage Strategy** | A module-level declaration of whether its Life Items use only the generalized `life_items` row or also use a module-specific Side Table. | Schema choice, table type |
| **Side Table** | A module-specific relational table that extends `life_items` for fields needing exact queries or transactional integrity; rows are cascade-deleted with their parent `life_items` row. | Dedicated table, custom schema |
| **Item Shape** | The module-specific fields expected for a Life Item. | Schema, form, payload spec |
| **Suggestion Threshold** | The minimum Capture Proposal confidence required for a module's Suggested Chat Action to surface. | Confidence cutoff, suggestion filter |
| **Block** | A visual surface for a Module Instance that can be placed in the workspace or dashboard. | Widget, card, tile, panel |
| **Dashboard** | A configurable workspace where Blocks are arranged for repeated use. | Home, board, canvas |
| **Block Size** | A fixed layout footprint that controls how much space a Block occupies. | Widget size, grid size, shape |
| **Module View** | The full page or focused surface for working with one Module Instance. | Screen, tab, page |

## Information lifecycle

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Capture** | A new piece of Life Data entering Orbit from a person, chat, file, or external source. | Input, entry, raw data |
| **Intake** | A configured path that accepts Captures into Orbit. | Import, ingestion, upload |
| **External Intake** | An Intake that receives Captures from outside Orbit, such as email, files, APIs, or other apps. | Integration, sync, connector |
| **Source** | The origin of a Capture. | Provider, channel, module |
| **Life Item** | A durable record created from a Capture and owned by a Module Instance. | Item, record, object, entity |
| **Item Payload** | The flexible structured fields stored on a Life Item according to its Item Shape. | JSON, metadata, body |
| **Lifecycle Status** | The normalized cross-module state of a Life Item: `active`, `completed`, `archived`, or `deleted`; each module declares which subset is valid. | Status, state, module status |
| **Knowledge Chunk** | A retrievable excerpt derived from a Life Item or Document. | Chunk, embedding, snippet |
| **Retrieval Policy** | A module rule that decides whether a Life Item should produce Knowledge Chunks and what text should become retrievable. | RAG setting, chunking rule |
| **Ingestion Rule** | A module-specific condition that decides whether a Capture should become a Life Item or Knowledge Chunk. | Filter, trigger, condition |
| **Capture Proposal** | An AI-generated suggestion to create or update a Life Item from conversation or another Capture. | Suggestion, nudge, action |
| **Life-Item-Shaped Intent** | A clear verb-object intent that maps to a module's Life Item type. | Intent shape, action signal |
| **Capture Proposal Confidence** | A discrete confidence score for a Capture Proposal, produced by a shape-detection call returning `low`, `medium`, or `high`, not by LLM-reported probability. | Probability, LLM confidence |
| **Async Step Status** | The state of an asynchronous lifecycle step on a Life Item: `pending`, `complete`, or `failed`, applied to deferred steps such as Connection Review and Bucket Update. | Job status, async state |
| **Preview** | A confirmation surface showing the Life Item that would be created or updated. | Draft, modal, confirmation card |
| **Confirmation** | The person's approval that applies a Preview. | Accept, submit, save |
| **Request ID** | A stable identifier that makes repeated lifecycle writes safe to retry. | Idempotency key, retry key |

The four canonical Value Moments are **Capture** (throwing life data into Orbit without organizing it perfectly), **Focus** (knowing what to do next and why), **Decide** (choosing between options with goals in view), and **Discuss** (talking to a Task, Plan, or Document in context). Future features should declare which Value Moment they serve.

Module-specific richer states such as `blocked`, `wont_do`, or `in_progress` live in Item Payload, not in Lifecycle Status.

## Story and memory

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Story Bucket** | An editable markdown file that describes part of the person's ongoing story. | Bucket, facet, profile file |
| **Bucket Update** | A small factual change recorded for later integration into a Story Bucket. | Append, memory write, note |
| **Bucket Update Log** | An append-only stream of factual updates pending integration into a Story Bucket. | Append log, pending memory, update stream |
| **Story Weave** | A periodic synthesis that turns accumulated Bucket Updates into coherent narrative prose. | Rewrite, compression, summary |
| **Active Goal** | A goal the person has explicitly committed to, stored as a structured markdown entry in `goals.md` with a stable goal ID. | Priority, objective, target |
| **Tentative Goal** | A goal-shaped thought that has not yet been promoted by the person, stored alongside Active Goals with the same stable-ID convention. | Maybe goal, idea, consideration |
| **User Edit Lock** | A temporary protection window that prevents AI rewrites from changing recently edited Story Bucket sections. | Freeze, lock, manual override |

In practice, Connection Review and chat modes interact with Story Buckets directly. The User Model is the conceptual whole; Story Buckets are the concrete pieces.

## Connections

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Connection** | A meaningful relationship between Life Data and the person's goals, Story Buckets, modules, or other Life Items. | Link, relation, edge |
| **Connection Note** | A short explanation of why a Connection matters to the person at that point in time. | Reason, description, relevance |
| **Connected Bucket** | A Story Bucket that a Life Item meaningfully informs. | Facet match, bucket link |
| **Connected Item** | A Life Item related to another Life Item. | Related record, linked object |
| **Document Connection** | A document-level explanation of how an uploaded Document relates to the person. | Document summary, file relevance |
| **Connection Review** | The AI step that decides and explains the Connections for new Life Data. | Enrichment, classification, routing |
| **Review Entry** | A system-generated item asking the person to inspect and approve a sensitive or ambiguous model change. | Review task, moderation item |

## Modules and life data

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Task** | A Life Item representing a concrete action the person may do. | Todo, action, chore |
| **Plan** | A structured Life Item representing a multi-step effort. | Project, roadmap, checklist |
| **Note** | A Life Item representing reference material or written thought. | Vault note, doc, memo |
| **Log** | A timestamped Capture of something that happened or was observed. | Journal entry, history item |
| **Brainstorm** | A Life Item containing exploratory ideas that may later become Tasks, Plans, Notes, or Strategies. | Ideation, scratchpad, blabber |
| **Strategy** | A Life Item or output that describes how attention, time, or effort should be allocated across goals and work. | Recommendation, priority plan, schedule |
| **Recommendation** | An output-heavy module result generated from existing Life Data. | Suggestion, advice, insight |
| **Document** | An uploaded file treated as one coherent source of Life Data. | File, resource, attachment |
| **Prompt** | A reusable instruction or thinking pattern the person wants Orbit to remember or apply. | Template, command, instruction |
| **Learning Entry** | A Life Item representing something the person is studying or trying to understand. | Lesson, study note, learning log |

## Chat and reasoning

| Term | Definition | Aliases to avoid |
| --- | --- | --- |
| **Free Chat** | A conversation mode that answers conversationally with minimal structured context. | Plain chat, normal chat |
| **Context Chat** | A conversation mode that uses Story Buckets, Connections, module tools, and retrieved Knowledge Chunks. | Standard chat, intelligent chat |
| **Deep Chat** | A slower conversation mode that performs broader retrieval and more deliberate reasoning. | Deep mode, research chat |
| **Decision Mode** | A structured mode that produces options, tradeoffs, and goal-alignment before the person chooses. | Decision chat, MCQ mode |
| **Item Chat** | A conversation mode anchored to a single Life Item and scoped to its one-hop Connection graph. | Item discussion, focused chat, single-item chat |
| **Chat Action** | A confirmed operation proposed from chat, such as creating a Task or updating a Plan. | Tool call, command, action |
| **Suggested Chat Action** | A Chat Action proposed by Orbit without an explicit user command, gated by Life-Item-Shaped Intent and Suggestion Threshold. | Suggestion, proactive action, nudge |
| **Retrieval Mode** | The chat setting that controls how much context Orbit gathers before answering. | Query mode, RAG mode |
| **Scoped Agency** | Model freedom limited to a specific step, context boundary, and toolset. | Agentic behavior, autonomous flow |
| **Retrieval Toolset** | The constrained set of lookup tools a chat mode may use to gather context. | Tools, agent tools, retrieval tools |

## Relationships

- A **Person** owns one **User Model**.
- A **User Model** contains one or more **Story Buckets**.
- An **Orchestrated Lifecycle** governs how **Captures** become **Life Items**, **Connections**, **Knowledge Chunks**, and **Bucket Updates**.
- A **Module** can have many **Module Instances**.
- A **Module Instance** owns zero or more **Life Items**.
- A **Module** defines one or more **Module Roles**.
- A **Module** declares exactly one **Storage Strategy**.
- A **Module** may use one or more **Side Tables** when its **Storage Strategy** requires extended storage.
- A **Module** defines one or more **Item Shapes**.
- A **Module** may declare a **Suggestion Threshold** for its **Suggested Chat Actions**.
- A **Capture** may produce zero or more **Life Items**.
- A **Life Item** may produce zero or more **Knowledge Chunks**.
- A **Life Item** always has one row in `life_items`, even when a **Side Table** extends it.
- A **Life Item** has exactly one normalized **Lifecycle Status**.
- Deleting a **Life Item** cascade-deletes its **Side Table** row, derived **Knowledge Chunks**, and **Connections**.
- A **Retrieval Policy** controls which **Life Items** produce **Knowledge Chunks**.
- A **Document** usually has one **Document Connection**.
- A **Life Item** can have many **Connections**.
- A **Connection** may point to a **Story Bucket**, **Life Item**, **Module Instance**, or **Active Goal**.
- **Active Goals** and **Tentative Goals** are stored in `goals.md` with stable IDs. **Connections** point at goal IDs, not headings or text positions.
- A **Bucket Update** targets exactly one **Story Bucket**.
- A **Bucket Update Log** contains zero or more **Bucket Updates**.
- A **Story Weave** rewrites one or more **Story Buckets** from accumulated **Bucket Updates**.
- A **Block** belongs to exactly one **Module Instance**.
- A **Dashboard** contains zero or more **Blocks**.
- A **Capture Proposal** must produce a **Preview** before **Confirmation**.
- **Capture Proposal Confidence** is mapped to numeric thresholds for comparison against a module's **Suggestion Threshold**.
- A **Request ID** makes repeated lifecycle operations safe to retry.
- Every async lifecycle step writes its **Async Step Status** to the **Life Item** it operates on.
- UI surfaces must not silently render non-`complete` **Async Step Status** as complete.
- A **Chat Action** can create, update, or connect **Life Items** only after **Confirmation**.
- A **Suggested Chat Action** requires both a **Life-Item-Shaped Intent** and confidence above the module's **Suggestion Threshold**.
- **Item Chat** is scoped to exactly one **Life Item** and its one-hop **Connections**.
- **Context Chat**, **Deep Chat**, and **Item Chat** may use **Scoped Agency** through a constrained **Retrieval Toolset**.
- **Context Chat**, **Deep Chat**, and **Decision Mode** may use **Connections**, **Story Buckets**, module tools, and **Knowledge Chunks**.

## Example dialogue

> **Dev:** "If the person talks about needing to prepare the modular architecture, do we create a **Task** immediately?"
> **Domain expert:** "No. Chat should create a **Capture Proposal** with a **Preview** first, because a passing thought is not always a **Task**."
> **Dev:** "If they confirm the Preview, does that become a **Life Item** owned by the Tasks **Module Instance**?"
> **Domain expert:** "Exactly. Then the **Connection Review** explains how the new **Life Item** connects to the relevant **Story Bucket** and goals."
> **Dev:** "Should that same item also become a **Knowledge Chunk**?"
> **Domain expert:** "Only if its **Ingestion Rule** says it is useful for retrieval; the **Bucket Update** and the **Knowledge Chunk** are related but not the same thing."

## Flagged ambiguities

- "Module" and "block" were used interchangeably. Use **Module** for the capability and **Block** for the visual dashboard surface.
- "Data" was used to mean incoming information, durable records, and retrievable excerpts. Use **Capture** for incoming information, **Life Item** for the durable record, and **Knowledge Chunk** for retrieval units.
- "Schema" was discussed as both database tables and module-specific fields. Use **Item Shape** for module-specific fields and reserve database schema for implementation discussions.
- "Connection" was used for both bucket updates and graph relationships. Use **Connection** for the relationship and **Bucket Update** for the markdown story change.
- "Chat" was used for free conversation, context-aware answering, and structured creation. Use **Free Chat**, **Context Chat**, **Deep Chat**, **Decision Mode**, and **Chat Action** for those separate behaviors.
- "Discuss this item" was ambiguous between opening chat, navigating to item detail, and adding a comment. Use **Item Chat** for scoped conversation, and reserve "comment" for any future async annotation feature.
- "Agentic" was ambiguous between model-controlled workflow and model-assisted steps. Use **Orchestrated Lifecycle** for the fixed system flow and **Scoped Agency** for bounded model choices inside a step.
- "Strategy" and "recommendation" overlapped. Use **Strategy** when the result allocates attention, time, or effort, and **Recommendation** for a generated output that advises without becoming an allocation plan.
- "Source" and "module" overlapped. Use **Source** for where a Capture came from and **Module** for the Orbit capability that owns or uses Life Items.
- "Document summary" and "document connection" overlapped. Use **Document Connection** for how the Document relates to the person, and use summary only for what the Document contains.
