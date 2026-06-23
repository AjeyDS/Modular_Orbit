import { useEffect, useMemo, useRef, useState } from 'react'
import { CalendarDays, CheckCircle2, ChevronDown, ListTodo, Plus, RotateCcw, Sparkles, Trash2, X } from 'lucide-react'
import {
  completeTask,
  createTask,
  deleteTask,
  fetchTasks,
  fetchTaskPrioritySuggestion,
  generateTaskPrioritySuggestion,
  revertTaskRewrite,
  updateTaskPrioritySuggestion,
  updateTask,
  type LifecycleStatus,
  type TaskItem,
  type TaskPrioritySuggestionEntry,
  type TaskPrioritySuggestionState,
} from '../lib/api'
import { AsyncStatusPills } from '../components/status'
import {
  Card,
  CollectionRow,
  CollectionView,
  Composer,
  EditableTitle,
  EmptyState,
  FilterTabs,
  Pill,
  RowActions,
  Skeleton,
  useToast,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'

type TaskFilter = Extract<LifecycleStatus, 'active' | 'completed'>

type TaskEditPatch = { title?: string; due_date?: string | null }

const emptyPrioritySuggestion: TaskPrioritySuggestionState = {
  id: null,
  status: 'empty',
  suggestion_text: '',
  ranked: [],
  skippable: [],
  sort_enabled: false,
  panel_visible: false,
  task_snapshot_hash: '',
  context_summary: {},
  created_at: null,
  updated_at: null,
}

function todayISODate() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([])
  const [activeTasks, setActiveTasks] = useState<TaskItem[]>([])
  const [completedTasks, setCompletedTasks] = useState<TaskItem[]>([])
  const [filter, setFilter] = useState<TaskFilter>('active')
  const [newTitle, setNewTitle] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [prioritySuggestion, setPrioritySuggestion] = useState<TaskPrioritySuggestionState>(emptyPrioritySuggestion)
  const [error, setError] = useState('')
  const { toast, undoToast } = useToast()

  async function load(nextFilter = filter) {
    setLoading(true)
    setError('')
    try {
      const [visible, active, completed] = await Promise.all([
        fetchTasks(nextFilter),
        fetchTasks('active'),
        fetchTasks('completed'),
      ])
      setTasks(visible)
      setActiveTasks(active)
      setCompletedTasks(completed)
      try {
        setPrioritySuggestion(await fetchTaskPrioritySuggestion())
      } catch {
        // AI priority is advisory; an unavailable suggestion endpoint should not break Tasks.
        setPrioritySuggestion(emptyPrioritySuggestion)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load tasks')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(filter)
  }, [filter])

  const todayLabel = useMemo(
    () =>
      new Date().toLocaleDateString(undefined, {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
      }),
    [],
  )
  const todayISO = useMemo(todayISODate, [])

  const rankedMap = useMemo(() => {
    const map = new Map<string, { rank: number; entry: TaskPrioritySuggestionEntry }>()
    prioritySuggestion.ranked.forEach((entry, index) => {
      map.set(entry.task_id, { rank: index + 1, entry })
    })
    return map
  }, [prioritySuggestion.ranked])

  const skippableMap = useMemo(() => {
    const map = new Map<string, TaskPrioritySuggestionEntry>()
    prioritySuggestion.skippable.forEach((entry) => {
      map.set(entry.task_id, entry)
    })
    return map
  }, [prioritySuggestion.skippable])

  const sortedTasks = useMemo(
    () => {
      const rankedIndex = new Map(prioritySuggestion.ranked.map((entry, index) => [entry.task_id, index]))
      return [...tasks].sort((a, b) => {
        if (prioritySuggestion.sort_enabled && rankedIndex.size > 0) {
          const aRank =
            a.lifecycle_status === 'active' && rankedIndex.has(a.id) ? rankedIndex.get(a.id)! : Number.POSITIVE_INFINITY
          const bRank =
            b.lifecycle_status === 'active' && rankedIndex.has(b.id) ? rankedIndex.get(b.id)! : Number.POSITIVE_INFINITY
          if (aRank !== bRank) return aRank - bRank
        }
        const aDue = a.due_date
        const bDue = b.due_date
        if (aDue && bDue) return aDue.localeCompare(bDue)
        if (aDue) return -1
        if (bDue) return 1
        return b.created_at.localeCompare(a.created_at)
      })
    },
    [tasks, prioritySuggestion.ranked, prioritySuggestion.sort_enabled],
  )

  const dueTodayCount = useMemo(
    () => activeTasks.filter((task) => task.due_date === todayISO).length,
    [activeTasks, todayISO],
  )

  async function handleAdd() {
    const title = newTitle.trim()
    if (!title) return
    try {
      await createTask({ title, due_date: dueDate || null })
      setNewTitle('')
      setDueDate('')
      setPrioritySuggestion(emptyPrioritySuggestion)
      if (filter !== 'active') {
        setFilter('active')
      } else {
        await load('active')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create task')
    }
  }

  // Optimistic complete: move the task out of the active list / into completed
  // instantly so header counts and the active view update without a refetch.
  function handleComplete(id: string) {
    const target = tasks.find((task) => task.id === id) ?? activeTasks.find((task) => task.id === id)
    if (!target || target.lifecycle_status === 'completed') return
    const completed: TaskItem = { ...target, lifecycle_status: 'completed' }

    setTasks((current) =>
      filter === 'active'
        ? current.filter((task) => task.id !== id)
        : current.map((task) => (task.id === id ? completed : task)),
    )
    setActiveTasks((current) => current.filter((task) => task.id !== id))
    setCompletedTasks((current) => [completed, ...current.filter((task) => task.id !== id)])

    void completeTask(id).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to complete task', tone: 'danger' })
      void load()
    })
  }

  // Optimistic delete: drop the task from every list immediately, then surface
  // an undo affordance. The exact removed object is restored on undo.
  function handleDelete(task: TaskItem) {
    const removed = task
    const visibleIndex = tasks.findIndex((item) => item.id === removed.id)
    const activeIndex = activeTasks.findIndex((item) => item.id === removed.id)
    const completedIndex = completedTasks.findIndex((item) => item.id === removed.id)

    setTasks((current) => current.filter((item) => item.id !== removed.id))
    setActiveTasks((current) => current.filter((item) => item.id !== removed.id))
    setCompletedTasks((current) => current.filter((item) => item.id !== removed.id))

    undoToast({
      message: 'Task deleted',
      onUndo: () => {
        const insert = (list: TaskItem[], index: number) => {
          if (index < 0) return list
          const next = [...list]
          next.splice(Math.min(index, next.length), 0, removed)
          return next
        }
        setTasks((current) => insert(current, visibleIndex))
        setActiveTasks((current) => insert(current, activeIndex))
        setCompletedTasks((current) => insert(current, completedIndex))
      },
      onCommit: () => {
        void deleteTask(removed.id).catch((err) => {
          toast({ message: err instanceof Error ? err.message : 'Unable to delete task', tone: 'danger' })
          void load()
        })
        // The active set changed; drop any stale AI priority ordering.
        setPrioritySuggestion(emptyPrioritySuggestion)
      },
    })
  }

  // Optimistic edit (title / due date): patch local state, persist in the
  // background, reconcile via load() on failure.
  function handleEdit(id: string, patch: TaskEditPatch) {
    const apply = (task: TaskItem): TaskItem => ({
      ...task,
      ...(patch.title !== undefined ? { title: patch.title } : {}),
      ...(patch.due_date !== undefined ? { due_date: patch.due_date } : {}),
    })
    setTasks((current) => current.map((task) => (task.id === id ? apply(task) : task)))
    setActiveTasks((current) => current.map((task) => (task.id === id ? apply(task) : task)))
    setCompletedTasks((current) => current.map((task) => (task.id === id ? apply(task) : task)))

    void updateTask(id, patch).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to update task', tone: 'danger' })
      void load()
    })
  }

  async function handleGeneratePrioritySuggestion() {
    setSuggesting(true)
    setError('')
    try {
      const suggestion = await generateTaskPrioritySuggestion()
      // Click reduction: if the pass produced an ordering, auto-enable the sort
      // so the new order applies without a second click. The toggle still lets
      // the user turn it back off.
      if (suggestion.ranked.length > 0) {
        if (suggestion.id) {
          try {
            setPrioritySuggestion(await updateTaskPrioritySuggestion(suggestion.id, { sort_enabled: true }))
          } catch {
            setPrioritySuggestion({ ...suggestion, sort_enabled: true })
          }
        } else {
          setPrioritySuggestion({ ...suggestion, sort_enabled: true })
        }
      } else {
        setPrioritySuggestion(suggestion)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to generate AI suggestions')
    } finally {
      setSuggesting(false)
    }
  }

  async function handleTogglePrioritySort(next: boolean) {
    if (!prioritySuggestion.id) {
      setPrioritySuggestion((current) => ({ ...current, sort_enabled: next }))
      return
    }
    try {
      const suggestion = await updateTaskPrioritySuggestion(prioritySuggestion.id, { sort_enabled: next })
      setPrioritySuggestion(suggestion)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update AI priority sort')
    }
  }

  async function handleClosePriorityPanel() {
    if (!prioritySuggestion.id) {
      setPrioritySuggestion((current) => ({ ...current, panel_visible: false }))
      return
    }
    try {
      const suggestion = await updateTaskPrioritySuggestion(prioritySuggestion.id, { panel_visible: false })
      setPrioritySuggestion(suggestion)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to hide AI suggestions')
    }
  }

  const emptyCopy =
    filter === 'active'
      ? { title: 'Nothing on your plate.', body: 'Capture something above and it’ll land here.' }
      : { title: 'No completed tasks yet.', body: 'Finished tasks will appear here once you check them off.' }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Tasks</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{activeTasks.length}</span> active
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{dueTodayCount}</span> due today
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{completedTasks.length}</span> completed
            </p>
          </div>
          <p className="text-caption text-fg-tertiary">{todayLabel}</p>
        </header>

        {error && (
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}

        <Card className="p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <FilterTabs
              options={['active', 'completed']}
              value={filter}
              onChange={(value) => setFilter(value as TaskFilter)}
              ariaLabel="Task filter"
            />
            <div className="flex flex-wrap items-center gap-2">
              <PrioritySortToggle
                enabled={prioritySuggestion.sort_enabled}
                disabled={prioritySuggestion.ranked.length === 0}
                onChange={(next) => void handleTogglePrioritySort(next)}
              />
              <button
                type="button"
                onClick={() => void handleGeneratePrioritySuggestion()}
                disabled={suggesting || activeTasks.length === 0}
                className="inline-flex items-center gap-2 rounded-control bg-accent px-3 py-1.5 text-label font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Sparkles size={13} />
                {suggesting ? 'Thinking…' : 'AI suggestions'}
              </button>
            </div>
          </div>

          <PrioritySuggestionsPanel
            state={prioritySuggestion}
            loading={suggesting}
            onClose={() => void handleClosePriorityPanel()}
          />

          <CollectionView
            composer={
              <Composer
                value={newTitle}
                onChange={setNewTitle}
                onSubmit={handleAdd}
                placeholder="Add a task…"
                leading={<Plus size={15} className="text-fg-tertiary" />}
                trailing={<DateChip value={dueDate} onChange={setDueDate} />}
                submitLabel="Add"
              />
            }
            loading={loading && tasks.length === 0}
            isEmpty={sortedTasks.length === 0}
            empty={<EmptyState icon={<ListTodo size={18} />} title={emptyCopy.title} body={emptyCopy.body} />}
          >
            {sortedTasks.map((task) => {
              const canShowAiPriority = task.lifecycle_status === 'active'
              const ranked = canShowAiPriority ? rankedMap.get(task.id) : undefined
              const skippable = canShowAiPriority ? skippableMap.get(task.id) : undefined
              return (
                <TaskRow
                  key={task.id}
                  task={task}
                  todayISO={todayISO}
                  priorityRank={ranked?.rank ?? null}
                  priorityReason={ranked?.entry.reason ?? skippable?.reason ?? null}
                  isBestNext={ranked?.rank === 1}
                  isSkippable={Boolean(skippable)}
                  onComplete={handleComplete}
                  onDelete={handleDelete}
                  onEdit={handleEdit}
                />
              )
            })}
          </CollectionView>
        </Card>
      </div>
    </div>
  )
}

function PrioritySortToggle({
  enabled,
  disabled,
  onChange,
}: {
  enabled: boolean
  disabled: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(!enabled)}
      className={
        enabled
          ? 'inline-flex items-center gap-2 rounded-control border border-accent/40 bg-accent/10 px-3 py-1.5 text-label font-medium text-accent transition-colors disabled:opacity-40'
          : 'inline-flex items-center gap-2 rounded-control border border-hairline bg-surface px-3 py-1.5 text-label font-medium text-fg-secondary transition-colors hover:text-fg disabled:cursor-not-allowed disabled:opacity-40'
      }
    >
      Sort by AI priority
      <span className={enabled ? 'h-2 w-2 rounded-full bg-accent' : 'h-2 w-2 rounded-full bg-fg-tertiary'} />
    </button>
  )
}

function PrioritySuggestionsPanel({
  state,
  loading,
  onClose,
}: {
  state: TaskPrioritySuggestionState
  loading: boolean
  onClose: () => void
}) {
  const shouldShow =
    loading || (state.panel_visible && (state.ranked.length > 0 || state.skippable.length > 0 || state.suggestion_text))
  if (!shouldShow) return null

  return (
    <div className="ai-wash mb-3 overflow-hidden rounded-card border border-accent/30">
      <div className="flex items-start justify-between gap-3 border-b border-accent/20 px-4 py-3">
        <div>
          <div className="flex items-center gap-2 text-caption font-semibold uppercase tracking-[0.18em] text-accent">
            <Sparkles size={14} />
            Priority plan
          </div>
          <p className="mt-1 text-caption leading-5 text-fg-secondary">
            Advisory focus order only. Your stored task priorities stay untouched.
          </p>
        </div>
        {!loading && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 text-fg-tertiary transition-colors hover:text-fg-secondary"
            aria-label="Hide priority suggestions"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-2 px-4 py-4">
          {[0, 1, 2].map((item) => (
            <Skeleton key={item} className="h-14" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 px-4 py-4 lg:grid-cols-[1fr_0.7fr]">
          <div className="space-y-2">
            {state.ranked.map((entry, index) => (
              <div key={entry.task_id} className="rounded-control border border-hairline bg-surface/75 p-3">
                <div className="mb-1 flex items-center gap-2">
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent text-caption font-semibold text-white">
                    P{index + 1}
                  </span>
                  <h3 className="truncate text-body font-semibold text-fg">{entry.title}</h3>
                </div>
                <p className="text-caption leading-5 text-fg-secondary">{entry.reason}</p>
              </div>
            ))}
          </div>

          <div className="rounded-control border border-warn/30 bg-warn/10 p-3">
            <p className="text-caption font-semibold uppercase tracking-[0.16em] text-warn">Low alignment</p>
            {state.skippable.length > 0 ? (
              state.skippable.map((entry) => (
                <div key={entry.task_id} className="mt-2">
                  <h3 className="text-label font-semibold text-fg">{entry.title}</h3>
                  <p className="mt-1 text-caption leading-5 text-fg-secondary">{entry.reason}</p>
                </div>
              ))
            ) : (
              <p className="mt-2 text-caption leading-5 text-fg-secondary">
                Nothing was clearly worth skipping in this pass.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

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
      <input ref={ref} type="date" value={value} onChange={(e) => onChange(e.target.value)} className="sr-only" />
    </div>
  )
}

function TaskRow({
  task,
  todayISO,
  priorityRank,
  priorityReason,
  isBestNext,
  isSkippable,
  onComplete,
  onDelete,
  onEdit,
}: {
  task: TaskItem
  todayISO: string
  priorityRank: number | null
  priorityReason: string | null
  isBestNext: boolean
  isSkippable: boolean
  onComplete: (id: string) => void
  onDelete: (task: TaskItem) => void
  onEdit: (id: string, patch: TaskEditPatch) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const wasRewritten =
    task.rewrite_status === 'complete' && Boolean(task.original_title) && task.original_title !== task.title

  return (
    <CollectionRow accent={isBestNext}>
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          disabled={task.lifecycle_status === 'completed'}
          onClick={() => onComplete(task.id)}
          className="shrink-0 text-fg-tertiary transition-colors hover:text-success disabled:opacity-40"
          aria-label={`Complete ${task.title}`}
        >
          <CheckCircle2 size={20} strokeWidth={1.6} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              aria-label={expanded ? `Collapse ${task.title}` : `Expand ${task.title}`}
              className="shrink-0 rounded-md p-0.5 text-fg-tertiary transition-colors hover:text-fg-secondary"
            >
              <ChevronDown size={14} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
            </button>
            <EditableTitle
              value={task.title}
              onSave={(next) => onEdit(task.id, { title: next })}
              className="block max-w-full truncate text-body font-medium leading-snug text-fg"
            />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-caption text-fg-tertiary">
            {isBestNext && <Pill tone="accent">Best next</Pill>}
            {priorityRank && <Pill tone="accent">P{priorityRank}</Pill>}
            {isSkippable && <Pill tone="warn">Low alignment</Pill>}
            {wasRewritten && <Pill tone="neutral">rewritten</Pill>}
            <AsyncStatusPills
              connection={task.connection_status}
              chunk={task.chunk_status}
              bucketUpdate={task.bucket_update_status}
            />
          </div>
          {expanded && task.description && (
            <p className="mt-2 whitespace-pre-wrap rounded-control bg-surface-inset px-3 py-2 text-label leading-6 text-fg-secondary">
              {task.description}
            </p>
          )}
          {expanded && wasRewritten && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-caption text-fg-secondary">
              <span>Original: {task.original_title}</span>
              <button
                type="button"
                onClick={async () => {
                  await revertTaskRewrite(task.id)
                  onEdit(task.id, { title: task.original_title ?? task.title })
                }}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-accent transition-colors hover:bg-accent/10"
              >
                <RotateCcw size={12} />
                Revert
              </button>
            </div>
          )}
          {priorityReason && (
            <p className="mt-2 rounded-control bg-surface-inset px-3 py-2 text-caption leading-5 text-fg-secondary">
              {priorityReason}
            </p>
          )}
        </div>
        <RowActions className="self-start pt-0.5">
          {task.lifecycle_status === 'active' ? (
            <DateChip value={task.due_date ?? ''} onChange={(next) => onEdit(task.id, { due_date: next || null })} />
          ) : (
            <span
              className={`text-caption text-fg-tertiary ${task.due_date === todayISO ? 'font-medium text-accent' : ''}`}
            >
              {task.due_date ? (task.due_date === todayISO ? 'today' : task.due_date) : 'Someday'}
            </span>
          )}
          <button
            type="button"
            onClick={() => onDelete(task)}
            className="text-fg-tertiary transition-colors hover:text-danger"
            aria-label={`Delete ${task.title}`}
          >
            <Trash2 size={14} />
          </button>
        </RowActions>
      </div>
    </CollectionRow>
  )
}
