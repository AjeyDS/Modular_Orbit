# Unified Frontend — Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the foundation for the unified frontend — a tokenized visual system, the shared component kit, and the removal of all Tasks due-window buckets — without breaking the running app.

**Architecture:** Foundation-first, incremental. Establish a CSS-variable token layer surfaced through Tailwind v4 `@theme`, then build a shared primitive kit on top of it, and remove the `due_window` concept end-to-end (backend + frontend), leaving Tasks with an optional `due_date` only. The app stays shippable after every task. Full per-module migration onto the kit is a later roadmap (section "Remaining phases").

**Tech Stack:** React 19, Vite 7, Tailwind v4 (`@tailwindcss/vite`), framer-motion 12, lucide-react, react-router 7 (frontend); FastAPI + Postgres/psycopg + pydantic + pytest (backend).

**Source of truth:** `docs/plans/2026-06-23-unified-frontend-design.md`.

---

## Conventions & toolset notes

- **Backend tasks use real TDD** (pytest red → green → commit). Running backend
  tests needs the local Postgres described in `README.md`
  (`createdb modular_orbit --owner=orbit` + `vector`/`pgcrypto` extensions).
  Run from `backend/`: `python -m pytest <file>::<test> -v`.
- **The frontend has no test runner** (no vitest/jest in `package.json`; do NOT
  add one — YAGNI). Frontend verification per task is:
  1. `cd frontend && npx tsc -b` → expect no type errors.
  2. `cd frontend && npm run build` → expect a clean build.
  3. Visual check via the `run` skill (launch Vite dev server, open the relevant
     route, confirm light + dark).
- **Commit after every task.** Use the message shown in each task's final step.
- All new UI components live under `frontend/src/components/ui/` and are exported
  from `frontend/src/components/ui/index.ts`.
- Co-author trailer on every commit:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## Phase 0 — Token layer & app shell

### Task 0.1: Define the token layer in `styles.css`

**Files:**
- Modify: `frontend/src/styles.css`

**Step 1: Add semantic CSS variables (light + dark) and the Tailwind `@theme` mapping.**

Replace the current `@theme { … }` block (lines 3-8) and add variable blocks so the
file begins like this:

```css
@import "tailwindcss";

:root {
  --bg: #f7f7f8;
  --surface: #ffffff;
  --surface-inset: #f2f2f4;
  --surface-overlay: #ffffff;
  --border-hairline: rgba(0, 0, 0, 0.08);
  --border-strong: rgba(0, 0, 0, 0.14);
  --fg: #18181b;
  --fg-secondary: #6b7280;
  --fg-tertiary: #9ca3af;
  --accent: #4a9eff;
  --accent-hover: #3b8af0;
  --accent-wash: rgba(74, 158, 255, 0.06);
  --success: #1d9e75;
  --warn: #d97706;
  --danger: #dc2626;
}

.dark {
  --bg: #0e0e10;
  --surface: #1c1c1e;
  --surface-inset: #1e1e20;
  --surface-overlay: #1c1c1e;
  --border-hairline: rgba(255, 255, 255, 0.09);
  --border-strong: rgba(255, 255, 255, 0.16);
  --fg: #f4f4f5;
  --fg-secondary: #a1a1aa;
  --fg-tertiary: #71717a;
  --accent: #4a9eff;
  --accent-hover: #5ba8ff;
  --accent-wash: rgba(74, 158, 255, 0.1);
  --success: #1d9e75;
  --warn: #fbbf24;
  --danger: #f87171;
}

@theme inline {
  --font-sans: 'Inter', ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Consolas, monospace;
  --ease-orbit-out: cubic-bezier(0.23, 1, 0.32, 1);
  --ease-orbit-in-out: cubic-bezier(0.77, 0, 0.175, 1);

  --color-bg: var(--bg);
  --color-surface: var(--surface);
  --color-surface-inset: var(--surface-inset);
  --color-surface-overlay: var(--surface-overlay);
  --color-hairline: var(--border-hairline);
  --color-hairline-strong: var(--border-strong);
  --color-fg: var(--fg);
  --color-fg-secondary: var(--fg-secondary);
  --color-fg-tertiary: var(--fg-tertiary);
  --color-accent: var(--accent);
  --color-accent-hover: var(--accent-hover);
  --color-accent-wash: var(--accent-wash);
  --color-success: var(--success);
  --color-warn: var(--warn);
  --color-danger: var(--danger);

  --radius-control: 10px;
  --radius-card: 16px;
  --radius-modal: 20px;

  --text-caption: 11px;
  --text-label: 13px;
  --text-body: 15px;
  --text-heading: 17px;
  --text-title: 22px;
  --text-display: 28px;
}
```

Keep the existing `@custom-variant dark`, `box-sizing`, `body`, keyframes, and
scrollbar rules below.

**Step 2: Add the single canonical glass utility and the accent-wash helper.**

Append to `styles.css`:

```css
@utility glass {
  background-color: color-mix(in srgb, var(--surface-overlay) 72%, transparent);
  backdrop-filter: blur(20px) saturate(1.4);
  -webkit-backdrop-filter: blur(20px) saturate(1.4);
}

@utility ai-wash {
  background-image: linear-gradient(180deg, var(--accent-wash), transparent 72%);
}
```

**Step 3: Verify.**

Run: `cd frontend && npx tsc -b && npm run build`
Expected: clean build, no errors.

**Step 4: Commit.**

```bash
git add frontend/src/styles.css
git commit -m "feat(frontend): add tokenized design system (colors, radius, type, glass)"
```

---

### Task 0.2: Move the app shell onto tokens + canonical glass

**Files:**
- Modify: `frontend/src/App.tsx:64-89` (the `min-h-screen` wrapper + sticky `nav`)

**Step 1: Replace hardcoded shell colors with tokens and apply `glass` to the nav.**

In `AppContent`, change the outer wrapper and nav:

```tsx
<div className="min-h-screen bg-bg font-sans text-fg selection:bg-accent/30">
  <nav className="glass sticky top-0 z-50 border-b border-hairline transition-[border-color,background-color] duration-200 ease-out">
```

(Leave the logo/title markup unchanged except swapping `text-gray-900 dark:text-gray-100`
→ `text-fg`, and the "Modular" chip's `border-gray-200 dark:border-gray-800` →
`border-hairline`, `text-gray-400` → `text-fg-tertiary`.)

Update the error banner (lines 86-88) to tokens:
`border-danger/30 bg-danger/10 text-danger` (replacing the red-200/red-50/red-700 set).

**Step 2: Verify (type + build + visual).**

Run: `cd frontend && npx tsc -b && npm run build`
Then use the `run` skill: open `/chat`, toggle dark mode in Settings → confirm the
nav is frosted glass and the page background uses the new `--bg` in both themes.

**Step 3: Commit.**

```bash
git add frontend/src/App.tsx
git commit -m "feat(frontend): move app shell onto tokens + canonical glass nav"
```

---

### Task 0.3: Move the Sidebar onto tokens + glass

**Files:**
- Modify: `frontend/src/layout/Sidebar.tsx:68` (the `<aside>`), and the gray-* classes
  in `ChatPane`, `RecentRow`, `ModulesPane`.

**Step 1: Apply glass + tokens to the aside and replace `gray-*` neutrals.**

- `<aside>`: `className="glass sticky top-12 flex h-[calc(100vh-3rem)] shrink-0 flex-col self-start border-r border-hairline px-3 py-4 lg:px-4"`.
- Segmented tab background `bg-gray-100 dark:bg-gray-800` → `bg-surface-inset`.
- Active pill `bg-white dark:bg-gray-700` → `bg-surface`.
- Hover/active text and row backgrounds: `text-gray-*` → `text-fg` / `text-fg-secondary`
  / `text-fg-tertiary`; `hover:bg-gray-100 dark:hover:bg-gray-800` →
  `hover:bg-surface-inset`; active row `bg-gray-100 dark:bg-gray-800` → `bg-surface-inset`.
- Delete-confirm chip keeps semantic red but via `text-danger` / `bg-danger/10`.
- Borders `border-gray-100/800` → `border-hairline`.

**Step 2: Verify (type + build + visual).**

Run: `cd frontend && npx tsc -b && npm run build`; visually confirm sidebar glass +
recents legibility in light/dark via the `run` skill.

**Step 3: Commit.**

```bash
git add frontend/src/layout/Sidebar.tsx
git commit -m "feat(frontend): move sidebar onto tokens + glass"
```

---

## Phase A — Backend: remove all due-window buckets (TDD)

### Task A.1: Rewrite the due-window tests to assert the new contract

**Files:**
- Modify: `backend/tests/test_tasks_module.py:88-117`
- Modify: `backend/tests/test_schema.py:142-152`

**Step 1: Replace the two due-window task tests.**

Replace `test_create_task_defaults_due_window_this_week` (88-97) and
`test_create_task_exact_window_with_date` (100-117) with:

```python
def test_create_task_defaults_due_date_none(tmp_path) -> None:
    task = create_task(
        TaskCreate(title="ship it", request_id=_request_id("task-due-default")),
        review=False,
        review_root=tmp_path,
    )

    assert task.due_date is None
    assert not hasattr(task, "due_window")

    remove_task(task.id)


def test_create_task_with_due_date(tmp_path) -> None:
    from datetime import date

    task = create_task(
        TaskCreate(
            title="dentist",
            due_date=date(2026, 7, 1),
            request_id=_request_id("task-due-date"),
        ),
        review=False,
        review_root=tmp_path,
    )

    assert task.due_date == date(2026, 7, 1)

    remove_task(task.id)
```

**Step 2: Replace the schema test to assert the column is gone.**

Replace `test_task_items_has_due_window` (142-152) with:

```python
def test_task_items_has_no_due_window() -> None:
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'task_items' AND column_name = 'due_window'
                """
            )
            assert cur.fetchone() is None
```

**Step 3: Run to verify they fail.**

Run: `cd backend && python -m pytest tests/test_tasks_module.py::test_create_task_defaults_due_date_none tests/test_schema.py::test_task_items_has_no_due_window -v`
Expected: FAIL (`due_window` still defaults/exists; `due_window` attr still present).

**Step 4: Commit (red).**

```bash
git add backend/tests/test_tasks_module.py backend/tests/test_schema.py
git commit -m "test(tasks): expect due_date-only task model (no due_window)"
```

---

### Task A.2: Remove `due_window` from the Tasks service

**Files:**
- Modify: `backend/app/modules/tasks.py`

**Step 1: Make the edits.**

- Delete line 32: `DueWindow = Literal[...]`.
- `TaskCreate` (35-43): remove the `due_window` field (38).
- `TaskUpdate` (46-52): remove the `due_window` field (49).
- `TaskItem` (55-72): remove `due_window: DueWindow` (63).
- `create_task` (100-138): drop `due_window=payload.due_window` from the
  `_task_payload(...)` call (104) and `"due_window": payload.due_window,` from
  `side_table_data` (125).
- `update_task` (141-207): delete `next_due_window` (146); drop `due_window=...`
  from `_task_payload(...)` (153); in the `task_items` UPDATE (191-202) remove the
  `due_window = %s,` line and the `next_due_window` parameter.
- `list_tasks` (290-321): change the SELECT (299) to
  `SELECT li.*, ti.due_date, ti.priority, ti.module_status, ti.completed_at`
  and replace the `ORDER BY` (306-316) with:

  ```sql
  ORDER BY
      ti.completed_at DESC NULLS LAST,
      ti.due_date ASC NULLS LAST,
      li.created_at DESC
  ```
- `get_task` SELECT (456): same column change (drop `ti.due_window,`).
- `_row_to_task` (471-491): remove `due_window=row["due_window"],` (481).
- `_task_snapshot_hash` (699-713): remove the `"due_window": task.due_window,` line (705).
- `_task_payload` (725-743): remove the `due_window: DueWindow` parameter (727) and
  the `"due_window": due_window,` entry (736).
- `_effective_due_date` (746-754): replace the whole body with `return task.due_date`.
- Delete `_week_delta` (757-760) and the now-unused `import calendar` (9).

**Step 2: Run the targeted tests.**

Run: `cd backend && python -m pytest tests/test_tasks_module.py -v`
Expected: all pass (including the two rewritten in A.1).

**Step 3: Commit.**

```bash
git add backend/app/modules/tasks.py
git commit -m "feat(tasks): drop due_window from the Tasks service (due_date only)"
```

---

### Task A.3: Drop `due_window` from the side-table insert

**Files:**
- Modify: `backend/app/lifecycle/life_items.py:349-361`

**Step 1: Edit the `task_items` INSERT.**

```python
cur.execute(
    """
    INSERT INTO task_items (life_item_id, due_date, priority, module_status)
    VALUES (%s, %s, %s, %s)
    """,
    (
        life_item_id,
        side_table_data.get("due_date"),
        side_table_data.get("priority"),
        side_table_data.get("module_status"),
    ),
)
return
```

**Step 2: Verify (covered by the task suite).**

Run: `cd backend && python -m pytest tests/test_tasks_module.py -v`
Expected: pass.

**Step 3: Commit.**

```bash
git add backend/app/lifecycle/life_items.py
git commit -m "feat(tasks): drop due_window from task_items insert"
```

---

### Task A.4: Drop the `due_window` column in the schema

**Files:**
- Modify: `backend/app/db/schema.py:119-125`

**Step 1: Replace the add-column block with an idempotent drop.**

```python
cur.execute(
    """
    ALTER TABLE task_items
    DROP COLUMN IF EXISTS due_window
    """
)
```

(The `due_date DATE` column in the `CREATE TABLE task_items` at lines 108-117 stays.)

**Step 2: Run the schema + tasks suites.**

Run: `cd backend && python -m pytest tests/test_schema.py tests/test_tasks_module.py -v`
Expected: all pass (including `test_task_items_has_no_due_window`).

**Step 3: Commit.**

```bash
git add backend/app/db/schema.py
git commit -m "feat(tasks): drop due_window column from task_items schema"
```

---

## Phase B — Frontend: Tasks due-window removal

### Task B.1: Remove `due_window` from the API types

**Files:**
- Modify: `frontend/src/lib/api.ts:75` (TaskItem), `:110` (CreateTaskRequest)

**Step 1:** Delete the `due_window: 'this_week' | 'this_month' | 'someday' | 'exact'`
line from `TaskItem` (75) and the optional `due_window?` line from
`CreateTaskRequest` (110). Keep `due_date`.

**Step 2: Verify.** `cd frontend && npx tsc -b` → expect errors ONLY in
`TasksPage.tsx` (fixed in B.2). Do not commit yet.

---

### Task B.2: Replace the DueWindowPicker with an optional date chip

**Files:**
- Modify: `frontend/src/pages/TasksPage.tsx`

**Step 1: Rip out the due-window machinery.**

- Remove `type DueWindow` (23) and all `dueWindow` state/props.
- Delete `DueWindowPicker` (456-529), `dueWindowLabel` (769-775),
  `dueWindowButtonLabel` (777-779), `effectiveDueSort` (781-793). Keep `isoDate`.
- `useState<DueWindow>('this_week')` (50) → `const [dueDate, setDueDate] = useState('')`.
- `handleAdd` (140-158): `createTask({ title, due_date: dueDate || null })`; reset
  `setDueDate('')` instead of `setDueWindow('this_week')`.
- `sortedTasks` (113-133): replace the `effectiveDueSort` comparison with a direct
  `due_date` compare — tasks with a `due_date` sort ascending before tasks without:

  ```ts
  const aDue = a.due_date
  const bDue = b.due_date
  if (aDue && bDue) return aDue.localeCompare(bDue)
  if (aDue) return -1
  if (bDue) return 1
  return b.created_at.localeCompare(a.created_at)
  ```

**Step 2: Add a minimal optional date control.**

Add a `DateChip` component (composer + per-row) — a single clearable button that
opens the native date picker, replacing the dropdown:

```tsx
function DateChip({
  value,
  onChange,
}: {
  value: string
  onChange: (next: string) => void
}) {
  const ref = useRef<HTMLInputElement | null>(null)
  return (
    <div className="relative inline-flex items-center">
      <button
        type="button"
        onClick={() => ref.current?.showPicker?.()}
        className="inline-flex items-center gap-1 rounded-control border border-hairline bg-surface-inset px-2.5 py-1.5 text-label font-medium text-fg-secondary transition-colors hover:text-fg"
      >
        <CalendarDays size={13} />
        {value ? (value === todayISODate() ? 'Today' : value) : 'Add date'}
      </button>
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          aria-label="Clear date"
          className="ml-1 rounded-md p-0.5 text-fg-tertiary hover:text-danger"
        >
          <X size={12} />
        </button>
      )}
      <input
        ref={ref}
        type="date"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="sr-only"
      />
    </div>
  )
}
```

Wire `DateChip` into `TaskComposer` (replacing `DueWindowPicker`) and into the active
`TaskRow` (replacing the per-row `DueWindowPicker`), calling `saveDue` →
`updateTask(task.id, { due_date: next || null })`. Replace the `TaskComposer` `＋`
glyph (432) with `<Plus size={15} className="text-fg-tertiary" />`.

**Step 3: Verify (type + build + visual).**

Run: `cd frontend && npx tsc -b && npm run build`
Use the `run` skill: open `/modules/tasks`, add a task with and without a date, edit a
row's date, clear a date, toggle completed — confirm sort by date and the "due today"
count still work.

**Step 4: Commit.**

```bash
git add frontend/src/lib/api.ts frontend/src/pages/TasksPage.tsx
git commit -m "feat(tasks): remove due-window buckets; optional clearable due date"
```

---

## Phase 1 — Shared primitive kit

All under `frontend/src/components/ui/`. Each task: create the component, add it to
`index.ts`, verify `tsc -b` + `npm run build`, commit. These are built but not yet
wired into every module (that is the roadmap). Where a task replaces an existing
component, migrate its current consumers in the same task.

### Task 1.1: `cn` class helper + `index.ts`

**Files:** Create `frontend/src/components/ui/cn.ts`, `frontend/src/components/ui/index.ts`

```ts
// cn.ts
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
```

`index.ts` re-exports each component as it is added. Commit:
`feat(ui): add cn helper and ui kit barrel`.

### Task 1.2: `Surface`, `Card`, `GlassPanel`

**Files:** Create `frontend/src/components/ui/Surface.tsx`

- `<Card>`: flat opaque content — `bg-surface border border-hairline rounded-card`.
- `<Surface variant="inset">`: `bg-surface-inset`.
- `<GlassPanel>`: floating chrome — `glass border border-hairline`.

Specs: each forwards `className`, `children`; `Card`/`GlassPanel` accept an `as` prop
defaulting to `div`. No shadows except an optional `elevated` prop on `GlassPanel`
(`shadow-[0_24px_64px_-24px_rgba(0,0,0,0.28)]`). Commit:
`feat(ui): add Surface/Card/GlassPanel primitives`.

### Task 1.3: `Banner`

**Files:** Create `frontend/src/components/ui/Banner.tsx`

`<Banner type="error"|"success"|"info" onClose? autoDismissMs?>`. Tokenized:
error `bg-danger/10 text-danger border-danger/30`, success
`bg-success/10 text-success border-success/30`, info `bg-accent/10 text-accent
border-accent/30`. `rounded-control`, optional close `X`, optional auto-dismiss via
`setTimeout`. Replaces the inline banners in App/Tasks/etc. (migrate App.tsx's error
banner here). Commit: `feat(ui): add Banner with optional close + auto-dismiss`.

### Task 1.4: Toast host + `useToast` + `UndoToast`

**Files:** Create `frontend/src/components/ui/Toast.tsx`; modify `frontend/src/App.tsx`
(wrap `AppContent` in `<ToastProvider>`).

- `ToastProvider` holds a queue; `useToast()` returns `{ toast, undoToast }`.
- `undoToast({ message, onUndo, durationMs = 5000 })` shows a `GlassPanel` toast
  bottom-center with an "Undo" button; if not undone before `durationMs`, it resolves
  (caller has already applied the optimistic change and runs the real delete on
  expiry). Uses framer-motion `AnimatePresence` (slide+fade, `--ease-orbit-out`).
- This is the single destructive-action pattern (replaces native `confirm()`,
  inline confirm chips, and instant deletes during the roadmap migration).

Commit: `feat(ui): add toast host with undo toast`.

### Task 1.5: `StatusPill` / `Pill` (refactor `components/status.tsx`)

**Files:** Create `frontend/src/components/ui/Pill.tsx`; modify
`frontend/src/components/status.tsx` to re-export from the kit.

- `<Pill tone="neutral"|"success"|"warn"|"danger"|"accent">` — `rounded-full px-2
  py-0.5 text-caption font-semibold`, tokenized tones (retire slate/emerald/violet).
- `<StatusPill>` / `<AsyncStatusPills>` keep their current API but render via `Pill`
  and route raw backend stage strings through a single `humanizeStage(stage)` map
  (no raw identifiers in the UI). Keep `LifecyclePill` working; drop slate.

Verify the existing consumers (`TasksPage`, `LogsPage`, etc.) still type-check.
Commit: `feat(ui): tokenize status pills and humanize stage labels`.

### Task 1.6: `SegmentedControl` / `FilterTabs`

**Files:** Create `frontend/src/components/ui/SegmentedControl.tsx`

- `<SegmentedControl options={[{value,label,icon?}]} value onChange>` — the
  `bg-surface-inset` track + `bg-surface` active pill with a framer-motion
  `layoutId` slider (mirror the Sidebar tab animation). `role="tablist"`,
  arrow-key navigation, `focus-visible` ring.
- `<FilterTabs>` is a thin wrapper for string options.

Migrate `TasksPage` `FilterTabs` (748-767) to this component in the same task.
Commit: `feat(ui): add SegmentedControl/FilterTabs`.

### Task 1.7: `Composer`

**Files:** Create `frontend/src/components/ui/Composer.tsx`

Auto-grow textarea (cap configurable, default 140px) + optional `leftToolbar` slot +
optional `trailing` slot + primary submit button; Enter submits (Shift+Enter
newline), optional `submitOnModEnter`; calls `onSubmit(value)`, clears, and
re-focuses the textarea. Tokenized (`bg-surface-inset`, `border-hairline`,
`rounded-card`, accent submit). Commit: `feat(ui): add Composer primitive`.

### Task 1.8: `EmptyState` + `Skeleton`

**Files:** Create `frontend/src/components/ui/EmptyState.tsx`,
`frontend/src/components/ui/Skeleton.tsx`

- `<EmptyState icon title body action?>` — centered, muted lucide icon tile, one-line
  copy, optional CTA. Dashed `border-hairline`.
- `<Skeleton variant="row"|"card"|"text" count?>` — `animate-pulse bg-surface-inset
  rounded-control` blocks matching content shape (replaces "Loading…" text lines).

Commit: `feat(ui): add EmptyState and Skeleton`.

### Task 1.9: `Dialog`

**Files:** Create `frontend/src/components/ui/Dialog.tsx`

Portal + `GlassPanel` scrim (`bg-black/30 glass`), centered `rounded-modal` panel with
`header`/`body`/`footer` slots, `role="dialog"` + `aria-modal` + `aria-labelledby`,
focus-trap, Escape/scrim close, framer-motion enter/exit, and a built-in
`confirmOnClose` discard bar. This becomes the base for the Plans/Documents modals
and the standard confirm. Commit: `feat(ui): add accessible Dialog with discard-confirm`.

### Task 1.10: `CollectionView`

**Files:** Create `frontend/src/components/ui/CollectionView.tsx`

The highest-leverage primitive. Compose existing kit parts:

- `<CollectionView composer rows loading empty>` renders `Composer` (slot) → either
  `Skeleton` (loading) → `EmptyState` (empty) → an animated `RowList`.
- `<Row leading title meta actions editableTitle?>`:
  - `editableTitle`: click-to-edit (single affordance) — text becomes an input,
    saves on blur/Enter, cancels on Escape.
  - `actions`: hover-revealed cluster that is ALSO visible on `focus-within` and
    always visible at touch/`sm` widths (`opacity-100 sm:opacity-0
    sm:group-hover:opacity-100 sm:group-focus-within:opacity-100`).
  - framer-motion `layout` + enter/exit for add/remove.
- Document the optimistic-mutation contract in a top-of-file comment: callers update
  local state immediately and reconcile in the background; deletes go through
  `useToast().undoToast`.

Commit: `feat(ui): add CollectionView (composer + editable rows + empty/loading)`.

### Task 1.11: `PageHeader` / `ModulePageShell` (retire orphan `ui.tsx`)

**Files:** Create `frontend/src/components/ui/PageHeader.tsx`; delete
`frontend/src/components/ui.tsx`; update any importers.

**Step 1:** `grep -rn "components/ui'" frontend/src` and
`grep -rn "PageHeader\|Panel" frontend/src` to find importers of the old `ui.tsx`.

**Step 2:** Build `<PageHeader title count? actions?>` (tokenized: `title` size,
`text-fg`, count summary in `text-fg-secondary`) and `<ModulePageShell>` (wraps
`pageContentClass` + header slot + banner slot). Migrate importers; delete the old
`ui.tsx` (slate/emerald/glass/rounded-3xl orphan).

**Step 3:** `cd frontend && npx tsc -b && npm run build` → clean.

Commit: `feat(ui): add PageHeader/ModulePageShell and retire orphan ui.tsx`.

### Task 1.12: `ChatThread` / `MessageBubble` / `QuickReplyChips`

**Files:** Create `frontend/src/components/ui/ChatThread.tsx`

Message list (assistant-left flat bubble / user-right `bg-accent` bubble),
streaming/optimistic indicator slot, per-message action slot, centered empty/hero
slot. Pairs with `Composer` (Task 1.7) which already has the left-toolbar slot for
Chat's mode control. Commit: `feat(ui): add ChatThread/MessageBubble/QuickReplyChips`.

### Task 1.13: `MasterDetail`

**Files:** Create `frontend/src/components/ui/MasterDetail.tsx`

`lg` two-column grid: selectable `NavList` (left) + `DetailPanel` (right) with a
`dirtyGuard` callback that intercepts selection changes when the detail panel has
unsaved edits. Commit: `feat(ui): add MasterDetail layout with dirty-guard`.

---

## Verification gate (end of foundation)

Before declaring the foundation done (see superpowers:verification-before-completion):

1. `cd backend && python -m pytest tests/test_tasks_module.py tests/test_schema.py -v`
   → all pass.
2. `cd frontend && npx tsc -b && npm run build` → clean.
3. `run` skill: `/chat`, `/modules/tasks`, and one more module render correctly in
   light + dark; nav + sidebar are glass; Tasks has no due-window UI and the optional
   date chip works.
4. `git status` clean; the kit components all live under `components/ui/` and export
   from `index.ts`.

---

## Remaining phases (roadmap — separate plans)

These migrate existing modules onto the kit; each is its own plan/PR. Order:

- **Phase 2 — CollectionView migration:** fully migrate Tasks, then Routine, Goals,
  Logs, Documents onto `CollectionView` + optimistic mutations + `undoToast`;
  replace native `confirm()` and `＋` glyphs; add `Skeleton`/`EmptyState`.
- **Phase 3 — Chat surfaces:** Chat + Curious onto `ChatThread`/`Composer`; inline
  `SegmentedControl` for mode/persona; in-place "Saved ✓" capture; Curious "Done"
  becomes passive.
- **Phase 4 — Plans / Modules / MasterDetail:** unify the two plan trees into one
  `<PlanTree mode>`; Plans + Documents modals onto `Dialog`; Modules drag-reorder
  (framer Reorder) + undo; UserModel + Settings onto `MasterDetail` ("Add & re-weave",
  dirty-guard).
- **Phase 5 — Polish pass:** uniform motion, every error gets Retry, all empty/loading
  states use the kit, humanize remaining jargon, `focus-visible` rings everywhere,
  fix affordance honesty (Chat source chips, Plans grip handle).

---

## Execution

Plan saved to `docs/plans/2026-06-23-unified-frontend-implementation.md`.
