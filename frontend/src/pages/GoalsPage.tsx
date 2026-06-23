import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { ArrowUpCircle, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import {
  createGoal,
  deleteGoal,
  listGoals,
  promoteGoal,
  updateGoal,
  type GoalHorizon,
  type GoalItem,
  type GoalStatus,
} from '../lib/api'
import {
  CollectionRow,
  Composer,
  EditableTitle,
  Pill,
  RowActions,
  SegmentedControl,
  SkeletonRows,
  useToast,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'

type GoalDraft = {
  title: string
  body: string
  status: GoalStatus
  horizon: GoalHorizon
  target_date: string
  target_note: string
}

const emptyDraft = (): GoalDraft => ({
  title: '',
  body: '',
  status: 'tentative',
  horizon: 'long_term',
  target_date: '',
  target_note: '',
})

const statusOptions: { value: GoalStatus; label: string }[] = [
  { value: 'active', label: 'Active' },
  { value: 'tentative', label: 'Tentative' },
]

const horizonOptions: { value: GoalHorizon; label: string }[] = [
  { value: 'short_term', label: 'Short-term' },
  { value: 'long_term', label: 'Long-term' },
]

// Render an ISO date (YYYY-MM-DD) as a human-friendly "Jun 25".
function formatTargetDate(value: string) {
  return new Date(`${value}T00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export default function GoalsPage() {
  const [goals, setGoals] = useState<GoalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [composerStatus, setComposerStatus] = useState<GoalStatus>('tentative')
  const [composerHorizon, setComposerHorizon] = useState<GoalHorizon>('long_term')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<GoalDraft>(emptyDraft)
  const { toast, undoToast } = useToast()

  async function loadGoals() {
    setLoading(true)
    setError('')
    try {
      setGoals(await listGoals())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load goals')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadGoals()
  }, [])

  const activeGoals = useMemo(() => sortGoals(goals.filter((g) => g.status === 'active')), [goals])
  const tentativeGoals = useMemo(() => sortGoals(goals.filter((g) => g.status === 'tentative')), [goals])

  // Optimistic create through the kit composer; defaults to tentative + long_term
  // so a bare title + Enter/Plus adds. Reconcile to the server item on success.
  async function handleAdd() {
    const title = newTitle.trim()
    if (!title) return

    const optimistic: GoalItem = {
      goal_id: `temp-${Date.now()}`,
      title,
      body: '',
      status: composerStatus,
      horizon: composerHorizon,
      target_date: null,
      target_note: null,
    }

    setError('')
    setGoals((current) => [...current, optimistic])
    setNewTitle('')

    try {
      const created = await createGoal({
        title,
        status: composerStatus,
        horizon: composerHorizon,
      })
      setGoals((current) => current.map((g) => (g.goal_id === optimistic.goal_id ? created : g)))
    } catch (err) {
      setGoals((current) => current.filter((g) => g.goal_id !== optimistic.goal_id))
      toast({ message: err instanceof Error ? err.message : 'Unable to create goal', tone: 'danger' })
    }
  }

  function startEdit(goal: GoalItem) {
    setEditingId(goal.goal_id)
    setEditDraft({
      title: goal.title,
      body: goal.body,
      status: goal.status,
      horizon: goal.horizon,
      target_date: goal.target_date ?? '',
      target_note: goal.target_note ?? '',
    })
  }

  // Optimistic edit-save: patch local state (may move the goal between the
  // Active / Tentative groups), persist in the background, reconcile on error.
  async function saveEdit(goalId: string) {
    const title = editDraft.title.trim()
    if (!title) return

    const patch = {
      title,
      body: editDraft.body.trim(),
      status: editDraft.status,
      horizon: editDraft.horizon,
      target_date: editDraft.target_date || null,
      target_note: editDraft.target_note.trim() || null,
    }

    setGoals((current) => current.map((g) => (g.goal_id === goalId ? { ...g, ...patch } : g)))
    setEditingId(null)

    try {
      const updated = await updateGoal(goalId, patch)
      setGoals((current) => current.map((g) => (g.goal_id === goalId ? updated : g)))
    } catch (err) {
      toast({ message: err instanceof Error ? err.message : 'Unable to update goal', tone: 'danger' })
      await loadGoals()
    }
  }

  // Optimistic quick rename from the row title.
  function handleRename(goalId: string, title: string) {
    setGoals((current) => current.map((g) => (g.goal_id === goalId ? { ...g, title } : g)))
    void updateGoal(goalId, { title }).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to rename goal', tone: 'danger' })
      void loadGoals()
    })
  }

  // Optimistic promote: flip status to active (moves the goal from Tentative to
  // Active), then reconcile to the server item.
  async function handlePromote(goalId: string) {
    setGoals((current) =>
      current.map((g) => (g.goal_id === goalId ? { ...g, status: 'active' as const } : g)),
    )
    try {
      const promoted = await promoteGoal(goalId)
      setGoals((current) => current.map((g) => (g.goal_id === goalId ? promoted : g)))
    } catch (err) {
      toast({ message: err instanceof Error ? err.message : 'Unable to promote goal', tone: 'danger' })
      await loadGoals()
    }
  }

  // Optimistic delete + undo: drop immediately, restore at the original index on
  // undo, persist the deletion on commit.
  function handleDelete(goal: GoalItem) {
    const removed = goal
    const index = goals.findIndex((g) => g.goal_id === removed.goal_id)
    if (editingId === removed.goal_id) setEditingId(null)

    setGoals((current) => current.filter((g) => g.goal_id !== removed.goal_id))

    undoToast({
      message: 'Goal deleted',
      onUndo: () => {
        setGoals((current) => {
          const next = [...current]
          next.splice(Math.min(index < 0 ? next.length : index, next.length), 0, removed)
          return next
        })
      },
      onCommit: () => {
        void deleteGoal(removed.goal_id).catch((err) => {
          toast({ message: err instanceof Error ? err.message : 'Unable to delete goal', tone: 'danger' })
          void loadGoals()
        })
      },
    })
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Goals</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{activeGoals.length}</span> active
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{tentativeGoals.length}</span> tentative
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadGoals()}
            aria-label="Refresh goals"
            title="Refresh"
            className="rounded-md p-1.5 text-fg-tertiary transition-colors hover:text-fg"
          >
            <RefreshCw size={15} />
          </button>
        </header>

        {error && (
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}

        <div className="border-b border-hairline pb-2">
          <Composer
            value={newTitle}
            onChange={setNewTitle}
            onSubmit={handleAdd}
            placeholder="Add a goal…"
            bare
            submitIcon={<Plus size={16} />}
            trailing={
              <div className="flex flex-wrap items-center gap-1.5">
                <SegmentedControl
                  options={statusOptions}
                  value={composerStatus}
                  onChange={setComposerStatus}
                  ariaLabel="Goal status"
                  size="sm"
                />
                <SegmentedControl
                  options={horizonOptions}
                  value={composerHorizon}
                  onChange={setComposerHorizon}
                  ariaLabel="Goal horizon"
                  size="sm"
                />
              </div>
            }
          />
        </div>

        {loading && goals.length === 0 ? (
          <div className="mt-4">
            <SkeletonRows count={4} />
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            <GoalSection
              title="Active"
              goals={activeGoals}
              showPromote={false}
              editingId={editingId}
              editDraft={editDraft}
              onStartEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onEditDraftChange={setEditDraft}
              onSaveEdit={(id) => void saveEdit(id)}
              onRename={handleRename}
              onPromote={(id) => void handlePromote(id)}
              onDelete={handleDelete}
            />
            <GoalSection
              title="Tentative"
              goals={tentativeGoals}
              showPromote
              editingId={editingId}
              editDraft={editDraft}
              onStartEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onEditDraftChange={setEditDraft}
              onSaveEdit={(id) => void saveEdit(id)}
              onRename={handleRename}
              onPromote={(id) => void handlePromote(id)}
              onDelete={handleDelete}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function sortGoals(goals: GoalItem[]) {
  return [...goals].sort((a, b) => {
    if (a.horizon !== b.horizon) {
      return a.horizon === 'short_term' ? -1 : 1
    }
    return a.title.localeCompare(b.title)
  })
}

function GoalSection({
  title,
  goals,
  showPromote,
  editingId,
  editDraft,
  onStartEdit,
  onCancelEdit,
  onEditDraftChange,
  onSaveEdit,
  onRename,
  onPromote,
  onDelete,
}: {
  title: string
  goals: GoalItem[]
  showPromote: boolean
  editingId: string | null
  editDraft: GoalDraft
  onStartEdit: (goal: GoalItem) => void
  onCancelEdit: () => void
  onEditDraftChange: (draft: GoalDraft) => void
  onSaveEdit: (goalId: string) => void
  onRename: (goalId: string, title: string) => void
  onPromote: (goalId: string) => void
  onDelete: (goal: GoalItem) => void
}) {
  return (
    <section>
      <p className="mb-1 text-caption font-medium uppercase tracking-wider text-fg-tertiary">{title}</p>
      {goals.length === 0 ? (
        <p className="py-2 text-caption text-fg-tertiary">No {title.toLowerCase()} goals yet.</p>
      ) : (
        <div className="divide-y divide-hairline">
          <AnimatePresence initial={false}>
            {goals.map((goal) => (
              <GoalRow
                key={goal.goal_id}
                goal={goal}
                editing={editingId === goal.goal_id}
                editDraft={editDraft}
                showPromote={showPromote}
                onStartEdit={() => onStartEdit(goal)}
                onCancelEdit={onCancelEdit}
                onEditDraftChange={onEditDraftChange}
                onSaveEdit={() => onSaveEdit(goal.goal_id)}
                onRename={(title) => onRename(goal.goal_id, title)}
                onPromote={() => onPromote(goal.goal_id)}
                onDelete={() => onDelete(goal)}
              />
            ))}
          </AnimatePresence>
        </div>
      )}
    </section>
  )
}

function HorizonPill({ horizon }: { horizon: GoalHorizon }) {
  return horizon === 'short_term' ? (
    <Pill tone="warn">short-term</Pill>
  ) : (
    <Pill tone="neutral">long-term</Pill>
  )
}

function GoalRow({
  goal,
  editing,
  editDraft,
  showPromote,
  onStartEdit,
  onCancelEdit,
  onEditDraftChange,
  onSaveEdit,
  onRename,
  onPromote,
  onDelete,
}: {
  goal: GoalItem
  editing: boolean
  editDraft: GoalDraft
  showPromote: boolean
  onStartEdit: () => void
  onCancelEdit: () => void
  onEditDraftChange: (draft: GoalDraft) => void
  onSaveEdit: () => void
  onRename: (title: string) => void
  onPromote: () => void
  onDelete: () => void
}) {
  if (editing) {
    return (
      <CollectionRow variant="plain">
        <div className="space-y-2 rounded-control bg-surface-inset p-3">
          <input
            value={editDraft.title}
            onChange={(event) => onEditDraftChange({ ...editDraft, title: event.target.value })}
            placeholder="Goal title"
            className="w-full rounded-control bg-surface px-3 py-1.5 text-body text-fg outline-none transition-shadow focus:ring-1 focus:ring-hairline-strong"
          />
          <textarea
            value={editDraft.body}
            onChange={(event) => onEditDraftChange({ ...editDraft, body: event.target.value })}
            rows={2}
            placeholder="Notes"
            className="w-full resize-none rounded-control bg-surface px-3 py-1.5 text-label leading-6 text-fg outline-none transition-shadow focus:ring-1 focus:ring-hairline-strong placeholder:text-fg-tertiary"
          />
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl
              options={statusOptions}
              value={editDraft.status}
              onChange={(status) => onEditDraftChange({ ...editDraft, status })}
              ariaLabel="Goal status"
              size="sm"
            />
            <SegmentedControl
              options={horizonOptions}
              value={editDraft.horizon}
              onChange={(horizon) => onEditDraftChange({ ...editDraft, horizon })}
              ariaLabel="Goal horizon"
              size="sm"
            />
            <input
              type="date"
              value={editDraft.target_date}
              onChange={(event) => onEditDraftChange({ ...editDraft, target_date: event.target.value })}
              className="rounded-control bg-surface px-2 py-1 text-caption text-fg outline-none"
            />
            <input
              value={editDraft.target_note}
              onChange={(event) => onEditDraftChange({ ...editDraft, target_note: event.target.value })}
              placeholder="Timeframe note"
              className="min-w-0 flex-1 rounded-control bg-surface px-2 py-1 text-caption text-fg outline-none placeholder:text-fg-tertiary"
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onSaveEdit}
              className="rounded-control bg-accent px-3 py-1 text-label font-medium text-white transition-colors hover:bg-accent-hover"
            >
              Save
            </button>
            <button
              type="button"
              onClick={onCancelEdit}
              className="rounded-control px-3 py-1 text-label text-fg-secondary transition-colors hover:text-fg"
            >
              Cancel
            </button>
          </div>
        </div>
      </CollectionRow>
    )
  }

  return (
    <CollectionRow variant="plain">
      <div className="flex items-start justify-between gap-3 px-1 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <EditableTitle
              value={goal.title}
              onSave={onRename}
              className="max-w-full truncate text-body font-medium leading-snug text-fg"
            />
            <HorizonPill horizon={goal.horizon} />
          </div>
          {goal.body && (
            <p className="mt-1 text-label leading-6 text-fg-secondary">{goal.body}</p>
          )}
          {(goal.target_date || goal.target_note) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-caption text-fg-tertiary">
              {goal.target_date && (
                <span className="tabular-nums">Target {formatTargetDate(goal.target_date)}</span>
              )}
              {goal.target_note && <span>{goal.target_note}</span>}
            </div>
          )}
        </div>
        <RowActions className="self-start pt-0.5">
          {showPromote && (
            <button
              type="button"
              onClick={onPromote}
              title="Promote to active"
              aria-label={`Promote ${goal.title} to active`}
              className="text-fg-tertiary transition-colors hover:text-accent"
            >
              <ArrowUpCircle size={14} />
            </button>
          )}
          <button
            type="button"
            onClick={onStartEdit}
            title="Edit goal"
            aria-label={`Edit ${goal.title}`}
            className="text-fg-tertiary transition-colors hover:text-fg"
          >
            <Pencil size={14} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            title="Delete goal"
            aria-label={`Delete ${goal.title}`}
            className="text-fg-tertiary transition-colors hover:text-danger"
          >
            <Trash2 size={14} />
          </button>
        </RowActions>
      </div>
    </CollectionRow>
  )
}
