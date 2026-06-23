# Unified Frontend Design — Modular Orbit

Date: 2026-06-23
Status: Approved (direction); implementation phased
Scope: Frontend visual system, shared component vocabulary, per-module redesign,
click/interaction reduction, plus removal of the Tasks "due-window" concept
(which touches the backend).

## 1. Goal

Refine the whole frontend to Apple/Meta-grade minimal polish with tasteful
transparency and restrained gradient, and unify the modules that currently
re-implement the same UI shapes. The driving problem is not "lack of polish" —
it is **lack of a system**. Fix the system and polish follows.

## 2. Approved direction (decisions)

These were decided with the user and are fixed for this work:

- **Deliverable:** design doc + implementation plan, then build the foundation
  (token layer + shared primitives) and the Tasks due-window removal.
- **Visual intensity:** **Apple-restrained.** Frosted glass on floating chrome
  only; content surfaces stay flat/opaque; gradients are barely-there,
  single-hue washes reserved for AI surfaces.
- **Accent:** keep `#4A9EFF` blue as the single primary. `--success` green,
  `--warn` amber, `--danger` red are the only semantic colors. Violet and slate
  are retired.
- **"Remove This Week" means:** remove **all** due-window buckets
  (`this_week` / `this_month` / `someday` / `exact`). Tasks keep only an
  optional, clearable exact `due_date`.
- **Rollout:** **Foundation-first, then incremental per-module migration.** The
  app stays working and shippable at every step.

## 3. Audit findings (why this is needed)

A full inventory of all 11 modules surfaced the following systemic issues.

### 3.1 Two competing design systems
`src/components/ui.tsx` (`PageHeader` / `Panel`) uses slate neutrals + emerald
accent + glass (`bg-white/72 backdrop-blur`) + `rounded-3xl`, but it is
effectively **orphaned** (imported only by `ui.tsx` itself and `TasksPage`).
The real app — `App.tsx`, `Sidebar.tsx`, and all 11 module pages — runs on gray
neutrals + a blue accent (`#4A9EFF`) + flat fills + `rounded-2xl` max. The
"designed" language never reaches users.

### 3.2 No single primary accent
Blue simultaneously means *primary action*, *AI/priority*, and *selected*. The
final/primary CTA in Tasks ("AI suggestions") and Plans ("Save plan") is
gray-900/black — i.e. the most important button is the least prominent. Green is
expressed three incompatible ways for one concept (`#1D9E75`, `emerald-*`, a
literal `green`). Violet (Chat mode, Curious check-ins, long-term horizon),
amber (status/short-term/warnings), and slate (status pills, Goals tentative)
all fight with no semantic rule.

### 3.3 Untokenized foundation
Dark mode is built from scattered hardcoded hex literals (`#18181A`, `#1C1C1E`,
`#1E1E20`, `#202024`, `#101312`, plus opacity variants) inlined across every
module. Hairline borders are faked with inline `style={{ borderWidth: '0.5px' }}`
in 30+ places. Type sizes use arbitrary `text-[Npx]` brackets. None of this is
tokenized, so a theme change requires hand-editing dozens of files.

### 3.4 Repeated UI shapes (the "similar modules")
| Shared shape | Modules | Unify into |
| --- | --- | --- |
| Chat thread + composer | Chat, Curious | `<ChatThread>` + `<Composer>` |
| List + add-composer + inline-edit rows | Tasks, Routine, Goals, Logs, Documents | `<CollectionView>` (highest leverage) |
| Master-detail editor | UserModel, Settings | `<MasterDetail>` |
| Recursive tree (two divergent renderers) | Plans | one `<PlanTree mode>` |
| Header + FilterTabs + card grid | Tasks, Plans, Modules, Documents | `<ModulePageShell>` |
| Portal modal + discard-confirm | Plans, Documents | one `<Dialog>` |
| Status pills / banners | 7 modules | `<StatusPill>` / `<Banner>` kit |

### 3.5 Inconsistent interaction patterns
Four different deletion UXes (native `confirm()`, instant no-confirm, inline
confirm chip, slide-up discard bar). Mutations trigger a full refetch instead of
optimistic update (latency + flicker). Two-click dropdowns where one-click
segmented controls fit. Motion applied in 5 modules, absent in 6. Affordance
mismatches (inert Chat source chips styled as interactive; a Plans drag handle
wired to nothing). Raw backend stage strings leak into the UI.

### 3.6 Where "This Week" lives (none is a dedicated view)
- **Tasks** — the `this_week` due-window enum value and the **default** for new
  tasks. Picker option, label, and `effectiveDueSort` end-of-week computation.
- **Logs** — a read-only "N this week" header stat (7-day rolling count).
- **Curious** — "max questions per week" rate-limit slider (unrelated concept;
  left as-is).

## 4. Visual system (token layer)

Defined as CSS custom properties in `src/styles.css` and surfaced through the
Tailwind v4 `@theme`. Establishing this retires the orphan `ui.tsx` system, all
scattered dark-mode hex, and the inline `0.5px` border hacks.

| Token | Light | Dark | Replaces |
| --- | --- | --- | --- |
| `--bg` (app) | `#F7F7F8` | `#0E0E10` | `bg-gray-50` / `#18181A` |
| `--surface` (cards) | `#FFFFFF` | `#1C1C1E` | scattered hex |
| `--surface-inset` (composers/insets) | `#F2F2F4` | `#1E1E20` | scattered hex |
| `--surface-overlay` (popovers/menus) | `#FFFFFF` (+glass) | `#1C1C1E` (+glass) | scattered hex |
| `--border-hairline` | `rgba(0,0,0,.08)` | `rgba(255,255,255,.09)` | inline `0.5px` |
| `--text` | gray-900 | gray-100 | — |
| `--text-secondary` | gray-500 | gray-400 | — |
| `--text-tertiary` | gray-400 | gray-500 | — |
| `--accent` (primary) | `#4A9EFF` | `#4A9EFF` | blue-500 / gray-900 CTAs |
| `--accent-hover` | `#3B8AF0` | `#5BA8FF` | — |
| `--accent-wash` | `rgba(74,158,255,.06)` | `rgba(74,158,255,.10)` | AI-panel gradient |
| `--success` | `#1D9E75` | `#1D9E75` | `#1D9E75` + `emerald-*` + `green` (3→1) |
| `--warn` | amber-500 | amber-400 | amber |
| `--danger` | red-500 | red-400 | red |

Notes:
- **Retired:** violet and slate, folded into neutral or accent. Chat's
  Understanding/Fast mode loses its violet theming; Goals "tentative" loses
  slate.
- `#1D9E75` already exists in the palette (teal-400) and is the existing
  completion color, so it becomes the one canonical "done/active" green. The
  exact value is tunable, but there must be exactly one.
- The hairline token uses a low-alpha 1px border (renders crisply and scales)
  instead of the fragile `0.5px`.

### 4.1 Glass — the Apple rule
Exactly one glass treatment: `bg-[--surface-overlay]/70 backdrop-blur-xl` +
`--border-hairline`. Reserved for **floating chrome only**: top nav, sidebar,
dropdowns, popovers, modal scrim + panel, toasts. **Content cards stay flat and
opaque** (`--surface`). Blur communicates "floating above content," nothing else.

### 4.2 Gradient — barely there
A single-hue `--accent-wash → transparent` wash, used only on AI surfaces:
- the Tasks priority panel (replacing its current blue→white→emerald two-hue
  mix with one accent wash),
- optionally the "best next" focus row's left edge.

No gradient buttons, no multi-hue gradients, no decorative washes anywhere else.

### 4.3 Scales
- **Radius:** `control 10px / card 16px / modal 20px / pill full`. Retires
  `rounded-3xl` and the one-off `rounded-[1.25rem]` modals.
- **Type:** `display 28 / title 22 / heading 17 / body 15 / label 13 / caption 11`,
  with role-aware line-height. Retires arbitrary `text-[Npx]`.
- **Spacing:** 4px base rhythm.

## 5. Motion

One easing token (`--ease-orbit-out`, already defined) plus durations
`--dur-fast 120ms` / `--dur 200ms`. Applied uniformly via framer-motion to: list
add/remove, panel reveal, toasts, and page transitions. Fades + small
translate/scale only; no bounce/spring overshoot.

## 6. Shared component vocabulary

New kit under `src/components/ui/` (replaces the orphan `ui.tsx`):

- `<GlassPanel>` / `<Surface>` / `<Card>` — floating-chrome glass vs flat content.
- `<Banner>` + `<Toast>` / `<UndoToast>` + a toast host — replaces inline banners
  that shift layout, the native `confirm()`, and the inline delete-confirm chip.
- `<StatusPill>` / `<Pill>` — tokenized lifecycle + async-pipeline + chips;
  humanizes raw backend stage strings in one place; Logs drops its hand-rolled
  amber pill.
- `<SegmentedControl>` / `<FilterTabs>` — the segmented pill control, defined once
  (Tasks, Plans, Modules, Goals, Settings, Chat-mode, Curious-persona).
- `<Composer>` — auto-grow textarea + optional left-toolbar slot + trailing
  controls + primary button; Enter/⌘Enter submit; auto-restores focus after
  submit.
- `<CollectionView>` — `Composer + RowList + Row{leading, editableTitle, meta,
  actions} + EmptyState + Skeleton`. Highest-leverage primitive. Standardizes
  click-to-edit titles, hover-reveal actions (visible on touch + via
  focus-within), and an optimistic mutation contract.
- `<Dialog>` — portal, focus-trap, `role=dialog` / `aria-modal`, tokenized scrim
  + shadow, header/body/footer slots, built-in discard-confirm.
- `<ChatThread>` + `<MessageBubble>` + `<QuickReplyChips>`.
- `<MasterDetail>` — selectable nav list + detail panel with a dirty-guard.
- `<PageHeader>` / `<ModulePageShell>` — header (title + count summary + action
  slot) + banner slot + content.
- `<EmptyState>` + `<Skeleton>` — consistent empty/loading treatments.

## 7. Per-module redesign + click reductions

| Module(s) | Unified onto | Interaction wins |
| --- | --- | --- |
| **Tasks** | CollectionView | Remove all due-window buckets → one optional clearable date chip. Click-to-edit titles. Auto-enable AI sort after generating suggestions. Optimistic complete/delete + undo toast. |
| **Routine, Goals, Logs, Documents** | CollectionView | Optimistic mutations (no full refetch). Delete → 1-click + undo (removes native `confirm()`). Click-to-edit titles. `lucide Plus` replaces the `＋` glyph. |
| **Chat, Curious** | ChatThread + Composer | Mode + persona become 1-click inline segmented controls (were 2-click dropdowns). Capture cards morph to "Saved ✓" in place (no extra system bubble). Curious "Done" becomes passive status (it already auto-weaves on idle + pagehide). |
| **Plans** | CardGrid + one `<PlanTree mode>` + Dialog | Merge the two divergent tree renderers; delete the orphan tan/stone palette. Surface primary actions on the collapsed card. Wire up or remove the dead grip handle. |
| **Modules** | ModulePageShell | Drag-to-reorder (framer-motion Reorder, already a dependency) replaces N up/down clicks. Undo on disable. |
| **UserModel, Settings** | MasterDetail | UserModel: "Add & re-weave" in one action; dirty-guard prevents silent loss of unsaved bucket edits. |

### 7.1 Global interaction contract
- Optimistic UI everywhere; reconcile with the server in the background.
- One undo-toast pattern for all destructive actions (no native `confirm()`, no
  silent instant-delete).
- Skeletons for loading; a Retry affordance on every error.
- Humanize all surfaced strings (backend stage identifiers, `storage_strategy`,
  and jargon such as "User Edit Lock" / "high-salience facts").
- `focus-visible` rings on every interactive element; `role`/`aria` wiring on
  dialogs and segmented controls.

## 8. Removing all due-window buckets (concrete)

### 8.1 Frontend
- `src/lib/api.ts`: drop `due_window` from `TaskItem` (line ~75) and the create
  payload (line ~110); keep `due_date: string | null`.
- `src/pages/TasksPage.tsx`: delete `DueWindowPicker`, `dueWindowLabel`,
  `dueWindowButtonLabel`, and the `effectiveDueSort` window branches. The
  composer gets a single optional, clearable date chip (opens the native date
  picker via `showPicker()`); rows show/edit `due_date` only; sort by `due_date`
  ascending, nulls last; keep the "due today" header count.

### 8.2 Backend
- `app/modules/tasks.py`: remove the `DueWindow` literal (line ~32) and the
  `due_window` field from `TaskCreate` / `TaskUpdate` / `TaskItem`; drop it from
  create/update writes; replace the `ORDER BY CASE ti.due_window …` ranking
  (lines ~308-315) with `ti.due_date ASC NULLS LAST`; simplify
  `_effective_due_date` (lines ~746-754) to just `task.due_date`; drop
  `due_window` from serialization. `_due_summary` / urgency logic is unchanged
  in behavior (already driven by the effective due date).
- `app/lifecycle/life_items.py` (line ~351): drop `due_window` from the
  `task_items` INSERT.
- `app/db/schema.py` (lines ~122-123): remove the `due_window` column add + CHECK
  constraint, and add a guarded `ALTER TABLE task_items DROP COLUMN IF EXISTS
  due_window` (explicit and idempotent, never an implicit DB reset).
- Tests: update `test_create_task_defaults_due_window_this_week`,
  `test_task_items_has_due_window`, and the `due_window="exact"` case in
  `test_tasks_module.py` to use `due_date` only.
- Chat-created tasks already use `due_date` (`app/chat/actions.py`), so that path
  is unaffected.

## 9. Phasing

0. **Tokens + motion + glass utility.** Define the token layer, motion tokens,
   radius/type scales; apply to the App shell + Sidebar; retire the orphan
   `ui.tsx` system. No intended visual regressions — plumbing only.
1. **Primitive kit.** Build the shared components in section 6 on top of the
   tokens.
2. **CollectionView migration.** Tasks (including the due-window removal +
   backend changes), Routine, Goals, Logs, Documents. Optimistic mutations +
   undo toast.
3. **Chat surfaces.** Chat + Curious onto ChatThread/Composer; inline segmented
   mode/persona; in-place capture confirmation.
4. **Remaining.** Plans (unify trees, Dialog), Modules (drag + undo),
   MasterDetail (UserModel + Settings).
5. **Polish pass.** Skeletons, empty/error states, Retry, jargon humanization,
   uniform motion, accessibility (focus rings, aria).

Foundation to build first per the approved deliverable: **Phase 0 + Phase 1 +
the Tasks due-window removal.**

## 10. Risks & notes

- Fresh database is expected; no legacy data migration is planned. The
  `due_window` column drop is explicit and idempotent — it does not reset data.
- Removing `due_window` changes task sort order (now purely by `due_date`); the
  "due today" count is preserved.
- Incremental migration means the token layer and the old per-module styles
  coexist briefly; each migrated module fully moves onto tokens to avoid a
  half-themed state lingering.
