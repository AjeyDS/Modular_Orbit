import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUpCircle, Pencil, RefreshCw, Trash2 } from 'lucide-react'
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

export default function GoalsPage() {
  const [goals, setGoals] = useState<GoalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<GoalDraft>(emptyDraft)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<GoalDraft>(emptyDraft)

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

  const activeGoals = useMemo(() => goals.filter((g) => g.status === 'active'), [goals])
  const tentativeGoals = useMemo(() => goals.filter((g) => g.status === 'tentative'), [goals])

  async function submitNewGoal(event?: FormEvent) {
    event?.preventDefault()
    const title = draft.title.trim()
    if (!title || saving) return

    const optimistic: GoalItem = {
      goal_id: `temp-${Date.now()}`,
      title,
      body: draft.body.trim(),
      status: draft.status,
      horizon: draft.horizon,
      target_date: draft.target_date || null,
      target_note: draft.target_note.trim() || null,
    }

    setSaving(true)
    setError('')
    setGoals((current) => [...current, optimistic])
    setDraft(emptyDraft())

    try {
      const created = await createGoal({
        title,
        body: optimistic.body || undefined,
        status: draft.status,
        horizon: draft.horizon,
        target_date: draft.target_date || null,
        target_note: optimistic.target_note,
      })
      setGoals((current) => current.map((g) => (g.goal_id === optimistic.goal_id ? created : g)))
    } catch (err) {
      setGoals((current) => current.filter((g) => g.goal_id !== optimistic.goal_id))
      setError(err instanceof Error ? err.message : 'Unable to create goal')
    } finally {
      setSaving(false)
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

    setGoals((current) =>
      current.map((g) =>
        g.goal_id === goalId
          ? {
              ...g,
              ...patch,
            }
          : g,
      ),
    )
    setEditingId(null)

    try {
      const updated = await updateGoal(goalId, patch)
      setGoals((current) => current.map((g) => (g.goal_id === goalId ? updated : g)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update goal')
      await loadGoals()
    }
  }

  async function handlePromote(goalId: string) {
    setGoals((current) =>
      current.map((g) => (g.goal_id === goalId ? { ...g, status: 'active' as const } : g)),
    )
    try {
      const promoted = await promoteGoal(goalId)
      setGoals((current) => current.map((g) => (g.goal_id === goalId ? promoted : g)))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to promote goal')
      await loadGoals()
    }
  }

  async function handleDelete(goalId: string) {
    if (!confirm('Delete this goal?')) return
    setGoals((current) => current.filter((g) => g.goal_id !== goalId))
    try {
      await deleteGoal(goalId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to delete goal')
      await loadGoals()
    }
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Goals</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{activeGoals.length}</span> active
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{tentativeGoals.length}</span> tentative
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadGoals()}
            aria-label="Refresh goals"
            title="Refresh"
            className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
          >
            <RefreshCw size={15} />
          </button>
        </header>

        {error && (
          <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        )}

        <section
          className="mb-5 rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
          style={{ borderWidth: '0.5px' }}
        >
          <GoalComposer
            title={draft.title}
            status={draft.status}
            horizon={draft.horizon}
            saving={saving}
            onTitleChange={(title) => setDraft((current) => ({ ...current, title }))}
            onStatusChange={(status) => setDraft((current) => ({ ...current, status }))}
            onHorizonChange={(horizon) => setDraft((current) => ({ ...current, horizon }))}
            onSubmit={(event) => void submitNewGoal(event)}
          />
        </section>

        {loading && goals.length === 0 ? (
          <div className="py-10 text-center text-[14px] text-gray-400">Loading goals…</div>
        ) : (
          <div className="space-y-6">
            <GoalSection
              title="Active"
              goals={activeGoals}
              editingId={editingId}
              editDraft={editDraft}
              onStartEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onEditDraftChange={setEditDraft}
              onSaveEdit={(id) => void saveEdit(id)}
              onPromote={(id) => void handlePromote(id)}
              onDelete={(id) => void handleDelete(id)}
            />
            <GoalSection
              title="Tentative"
              goals={tentativeGoals}
              editingId={editingId}
              editDraft={editDraft}
              onStartEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onEditDraftChange={setEditDraft}
              onSaveEdit={(id) => void saveEdit(id)}
              onPromote={(id) => void handlePromote(id)}
              onDelete={(id) => void handleDelete(id)}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function GoalSection({
  title,
  goals,
  editingId,
  editDraft,
  onStartEdit,
  onCancelEdit,
  onEditDraftChange,
  onSaveEdit,
  onPromote,
  onDelete,
}: {
  title: string
  goals: GoalItem[]
  editingId: string | null
  editDraft: GoalDraft
  onStartEdit: (goal: GoalItem) => void
  onCancelEdit: () => void
  onEditDraftChange: (draft: GoalDraft) => void
  onSaveEdit: (goalId: string) => void
  onPromote: (goalId: string) => void
  onDelete: (goalId: string) => void
}) {
  const sortedGoals = [...goals].sort((a, b) => {
    if (a.horizon !== b.horizon) {
      return a.horizon === 'short_term' ? -1 : 1
    }
    return a.title.localeCompare(b.title)
  })

  if (goals.length === 0) {
    return (
      <section
        className="rounded-2xl border border-dashed border-gray-200 bg-white/60 px-6 py-8 text-center dark:border-gray-700 dark:bg-[#1C1C1E]/60"
        style={{ borderWidth: '0.5px' }}
      >
        <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">{title}</p>
        <p className="mt-2 text-[13px] text-gray-500 dark:text-gray-500">No {title.toLowerCase()} goals yet.</p>
      </section>
    )
  }

  return (
    <section
      className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
      style={{ borderWidth: '0.5px' }}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="text-[12px] font-semibold uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">{title}</p>
        <HorizonLegend />
      </div>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        {sortedGoals.map((goal) => (
          <GoalRow
            key={goal.goal_id}
            goal={goal}
            editing={editingId === goal.goal_id}
            editDraft={editDraft}
            onStartEdit={() => onStartEdit(goal)}
            onCancelEdit={onCancelEdit}
            onEditDraftChange={onEditDraftChange}
            onSaveEdit={() => onSaveEdit(goal.goal_id)}
            onPromote={() => onPromote(goal.goal_id)}
            onDelete={() => onDelete(goal.goal_id)}
            showPromote={title === 'Tentative'}
          />
        ))}
      </div>
    </section>
  )
}

function GoalComposer({
  title,
  status,
  horizon,
  saving,
  onTitleChange,
  onStatusChange,
  onHorizonChange,
  onSubmit,
}: {
  title: string
  status: GoalStatus
  horizon: GoalHorizon
  saving: boolean
  onTitleChange: (value: string) => void
  onStatusChange: (value: GoalStatus) => void
  onHorizonChange: (value: GoalHorizon) => void
  onSubmit: (event?: FormEvent) => void
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 transition-colors focus-within:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:focus-within:border-gray-600"
      style={{ borderWidth: '0.5px' }}
    >
      <span className="text-gray-300 dark:text-gray-600">＋</span>
      <input
        value={title}
        onChange={(event) => onTitleChange(event.target.value)}
        placeholder="Add a goal…"
        className="min-w-0 flex-1 bg-transparent text-[14px] text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-200 dark:placeholder:text-gray-500"
      />
      <StatusToggle value={status} onChange={onStatusChange} compact />
      <HorizonToggle value={horizon} onChange={onHorizonChange} compact />
      <button
        type="submit"
        disabled={saving || !title.trim()}
        className="rounded-lg bg-blue-500 px-3 py-1.5 text-[13px] font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:opacity-40"
      >
        {saving ? 'Adding…' : 'Add'}
      </button>
    </form>
  )
}

function HorizonLegend() {
  return (
    <div className="flex items-center gap-3 text-[11px] text-gray-400 dark:text-gray-500">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-amber-400 dark:bg-amber-300" />
        Short-term
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-violet-400 dark:bg-violet-300" />
        Long-term
      </span>
    </div>
  )
}

function horizonAccentClass(horizon: GoalHorizon) {
  return horizon === 'short_term'
    ? 'border-l-amber-400 dark:border-l-amber-300'
    : 'border-l-violet-400 dark:border-l-violet-300'
}

function GoalRow({
  goal,
  editing,
  editDraft,
  onStartEdit,
  onCancelEdit,
  onEditDraftChange,
  onSaveEdit,
  onPromote,
  onDelete,
  showPromote,
}: {
  goal: GoalItem
  editing: boolean
  editDraft: GoalDraft
  onStartEdit: () => void
  onCancelEdit: () => void
  onEditDraftChange: (draft: GoalDraft) => void
  onSaveEdit: () => void
  onPromote: () => void
  onDelete: () => void
  showPromote: boolean
}) {
  if (editing) {
    return (
      <article className={`border-l-2 py-3 pl-3 ${horizonAccentClass(editDraft.horizon)}`}>
        <div className="space-y-2">
          <input
            value={editDraft.title}
            onChange={(event) => onEditDraftChange({ ...editDraft, title: event.target.value })}
            className="w-full rounded-lg bg-gray-100 px-3 py-1.5 text-[13px] outline-none focus:bg-white focus:ring-1 focus:ring-gray-300 dark:bg-gray-800 dark:focus:bg-[#1E1E20] dark:focus:ring-gray-700"
          />
          <textarea
            value={editDraft.body}
            onChange={(event) => onEditDraftChange({ ...editDraft, body: event.target.value })}
            rows={2}
            className="w-full resize-none rounded-lg bg-gray-100 px-3 py-1.5 text-[13px] leading-6 outline-none focus:bg-white focus:ring-1 focus:ring-gray-300 dark:bg-gray-800 dark:focus:bg-[#1E1E20] dark:focus:ring-gray-700"
          />
          <div className="flex flex-wrap items-center gap-2">
            <StatusToggle
              value={editDraft.status}
              onChange={(status) => onEditDraftChange({ ...editDraft, status })}
            />
            <HorizonToggle
              value={editDraft.horizon}
              onChange={(horizon) => onEditDraftChange({ ...editDraft, horizon })}
            />
            <input
              type="date"
              value={editDraft.target_date}
              onChange={(event) => onEditDraftChange({ ...editDraft, target_date: event.target.value })}
              className="rounded-lg bg-gray-100 px-2 py-1 text-[12px] outline-none dark:bg-gray-800"
            />
            <input
              value={editDraft.target_note}
              onChange={(event) => onEditDraftChange({ ...editDraft, target_note: event.target.value })}
              placeholder="Timeframe note"
              className="min-w-0 flex-1 rounded-lg bg-gray-100 px-2 py-1 text-[12px] outline-none dark:bg-gray-800"
            />
            <button
              type="button"
              onClick={onSaveEdit}
              className="rounded-lg bg-blue-500 px-2.5 py-1 text-[12px] font-medium text-white hover:bg-blue-600"
            >
              Save
            </button>
            <button
              type="button"
              onClick={onCancelEdit}
              className="rounded-lg px-2.5 py-1 text-[12px] text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800"
            >
              Cancel
            </button>
          </div>
        </div>
      </article>
    )
  }

  return (
    <article
      className={`group flex items-start justify-between gap-3 border-l-2 py-3 pl-3 ${horizonAccentClass(goal.horizon)}`}
    >
      <div className="min-w-0 flex-1">
        <h3 className="text-[14px] font-medium text-gray-900 dark:text-gray-100">{goal.title}</h3>
        {goal.body && (
          <p className="mt-1 text-[13px] leading-6 text-gray-500 dark:text-gray-400">{goal.body}</p>
        )}
        {(goal.target_date || goal.target_note) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
            {goal.target_date && <span className="tabular-nums">Target {goal.target_date}</span>}
            {goal.target_note && <span>{goal.target_note}</span>}
          </div>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        {showPromote && (
          <button
            type="button"
            onClick={onPromote}
            title="Promote to active"
            className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-blue-500 dark:hover:bg-gray-800"
          >
            <ArrowUpCircle size={14} />
          </button>
        )}
        <button
          type="button"
          onClick={onStartEdit}
          title="Edit goal"
          className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
        >
          <Pencil size={14} />
        </button>
        <button
          type="button"
          onClick={onDelete}
          title="Delete goal"
          className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-red-500 dark:hover:bg-gray-800"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </article>
  )
}

function StatusToggle({
  value,
  onChange,
  compact = false,
}: {
  value: GoalStatus
  onChange: (status: GoalStatus) => void
  compact?: boolean
}) {
  return (
    <div className="flex rounded-lg bg-gray-100 p-0.5 dark:bg-gray-800">
      {(['active', 'tentative'] as const).map((status) => {
        const active = value === status
        const activeClass =
          status === 'active'
            ? active
              ? 'bg-emerald-100 text-emerald-900 shadow-sm dark:bg-emerald-950/50 dark:text-emerald-100'
              : 'text-gray-500 dark:text-gray-400'
            : active
              ? 'bg-slate-200 text-slate-800 shadow-sm dark:bg-slate-700 dark:text-slate-100'
              : 'text-gray-500 dark:text-gray-400'
        return (
          <button
            key={status}
            type="button"
            onClick={() => onChange(status)}
            className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${activeClass}`}
          >
            {status === 'active' ? 'Active' : compact ? 'Tent.' : 'Tentative'}
          </button>
        )
      })}
    </div>
  )
}

function HorizonToggle({
  value,
  onChange,
  compact = false,
}: {
  value: GoalHorizon
  onChange: (horizon: GoalHorizon) => void
  compact?: boolean
}) {
  return (
    <div className="flex rounded-lg bg-gray-100 p-0.5 dark:bg-gray-800">
      {(['short_term', 'long_term'] as const).map((horizon) => {
        const active = value === horizon
        const shortLabel = compact ? 'Short' : 'Short-term'
        const longLabel = compact ? 'Long' : 'Long-term'
        const activeClass =
          horizon === 'short_term'
            ? active
              ? 'bg-amber-100 text-amber-900 shadow-sm dark:bg-amber-950/50 dark:text-amber-100'
              : 'text-gray-500 dark:text-gray-400'
            : active
              ? 'bg-violet-100 text-violet-900 shadow-sm dark:bg-violet-950/50 dark:text-violet-100'
              : 'text-gray-500 dark:text-gray-400'
        return (
          <button
            key={horizon}
            type="button"
            onClick={() => onChange(horizon)}
            className={`rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors ${activeClass}`}
          >
            {horizon === 'short_term' ? shortLabel : longLabel}
          </button>
        )
      })}
    </div>
  )
}
