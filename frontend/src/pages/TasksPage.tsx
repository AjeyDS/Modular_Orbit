import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { CalendarDays, CheckCircle2, ChevronDown, ListTodo, RotateCcw, Sparkles, Trash2, X } from 'lucide-react'
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
import { pageContentClass } from '../layout/pageShell'

type TaskFilter = Extract<LifecycleStatus, 'active' | 'completed'>
type DueWindow = TaskItem['due_window']

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
  const [dueWindow, setDueWindow] = useState<DueWindow>('this_week')
  const [dueDate, setDueDate] = useState('')
  const [loading, setLoading] = useState(false)
  const [suggesting, setSuggesting] = useState(false)
  const [prioritySuggestion, setPrioritySuggestion] = useState<TaskPrioritySuggestionState>(emptyPrioritySuggestion)
  const [error, setError] = useState('')

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
        const aDue = effectiveDueSort(a)
        const bDue = effectiveDueSort(b)
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

  async function handleAdd(event?: FormEvent) {
    event?.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    try {
      await createTask({ title, due_window: dueWindow, due_date: dueWindow === 'exact' ? dueDate || null : null })
      setNewTitle('')
      setDueWindow('this_week')
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

  async function handleGeneratePrioritySuggestion() {
    setSuggesting(true)
    setError('')
    try {
      const suggestion = await generateTaskPrioritySuggestion()
      setPrioritySuggestion(suggestion)
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

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Tasks</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{activeTasks.length}</span> active
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{dueTodayCount}</span> due today
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{completedTasks.length}</span> completed
            </p>
          </div>
          <p className="text-[12px] text-gray-400 dark:text-gray-500">{todayLabel}</p>
        </header>

        {error && (
          <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        )}

        <section
          className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
          style={{ borderWidth: '0.5px' }}
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <FilterTabs value={filter} onChange={setFilter} />
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
                className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3 py-1.5 text-[12px] font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-gray-800 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
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

          <TaskComposer
            title={newTitle}
            dueWindow={dueWindow}
            dueDate={dueDate}
            onTitleChange={setNewTitle}
            onDueWindowChange={setDueWindow}
            onDueDateChange={setDueDate}
            onSubmit={handleAdd}
          />

          <div className="mt-3 space-y-1">
            {loading && tasks.length === 0 ? (
              <div className="py-10 text-center text-[14px] text-gray-400">Loading tasks…</div>
            ) : sortedTasks.length === 0 ? (
              <EmptyTasksState filter={filter} />
            ) : (
              sortedTasks.map((task) => {
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
                    onChanged={() => void load()}
                  />
                )
              })
            )}
          </div>
        </section>
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
          ? 'inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-[12px] font-medium text-blue-700 transition-colors disabled:opacity-40 dark:border-blue-900/60 dark:bg-blue-950/40 dark:text-blue-200'
          : 'inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-[12px] font-medium text-gray-500 transition-colors hover:text-gray-700 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-400 dark:hover:text-gray-200'
      }
    >
      Sort by AI priority
      <span
        className={
          enabled
            ? 'h-2 w-2 rounded-full bg-blue-500 shadow-[0_0_0_3px_rgba(59,130,246,0.18)]'
            : 'h-2 w-2 rounded-full bg-gray-300 dark:bg-gray-600'
        }
      />
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
  const shouldShow = loading || (state.panel_visible && (state.ranked.length > 0 || state.skippable.length > 0 || state.suggestion_text))
  if (!shouldShow) return null

  return (
    <div className="mb-3 overflow-hidden rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-emerald-50 shadow-sm dark:border-blue-950/70 dark:from-blue-950/30 dark:via-[#1C1C1E] dark:to-emerald-950/20">
      <div className="flex items-start justify-between gap-3 border-b border-blue-100/70 px-4 py-3 dark:border-blue-950/70">
        <div>
          <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-300">
            <Sparkles size={14} />
            Priority plan
          </div>
          <p className="mt-1 text-[12px] leading-5 text-gray-500 dark:text-gray-400">
            Advisory focus order only. Your stored task priorities stay untouched.
          </p>
        </div>
        {!loading && (
          <button
            type="button"
            onClick={onClose}
            className="rounded-full p-1 text-gray-400 transition-colors hover:bg-white/80 hover:text-gray-600 dark:hover:bg-gray-900/70 dark:hover:text-gray-200"
            aria-label="Hide priority suggestions"
          >
            <X size={15} />
          </button>
        )}
      </div>

      {loading ? (
        <div className="space-y-2 px-4 py-4">
          {[0, 1, 2].map((item) => (
            <div key={item} className="h-14 animate-pulse rounded-xl bg-white/70 dark:bg-white/5" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 px-4 py-4 lg:grid-cols-[1fr_0.7fr]">
          <div className="space-y-2">
            {state.ranked.map((entry, index) => (
              <div
                key={entry.task_id}
                className="rounded-xl border border-white/80 bg-white/75 p-3 shadow-sm dark:border-white/10 dark:bg-white/5"
              >
                <div className="mb-1 flex items-center gap-2">
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-blue-600 text-[11px] font-semibold text-white">
                    P{index + 1}
                  </span>
                  <h3 className="truncate text-[14px] font-semibold text-gray-800 dark:text-gray-100">{entry.title}</h3>
                </div>
                <p className="text-[12px] leading-5 text-gray-500 dark:text-gray-400">{entry.reason}</p>
              </div>
            ))}
          </div>

          <div className="rounded-xl border border-amber-100 bg-amber-50/80 p-3 dark:border-amber-900/50 dark:bg-amber-950/20">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:text-amber-300">
              Low alignment
            </p>
            {state.skippable.length > 0 ? (
              state.skippable.map((entry) => (
                <div key={entry.task_id} className="mt-2">
                  <h3 className="text-[13px] font-semibold text-gray-800 dark:text-gray-100">{entry.title}</h3>
                  <p className="mt-1 text-[12px] leading-5 text-gray-500 dark:text-gray-400">{entry.reason}</p>
                </div>
              ))
            ) : (
              <p className="mt-2 text-[12px] leading-5 text-gray-500 dark:text-gray-400">
                Nothing was clearly worth skipping in this pass.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function TaskComposer({
  title,
  dueWindow,
  dueDate,
  onTitleChange,
  onDueWindowChange,
  onDueDateChange,
  onSubmit,
}: {
  title: string
  dueWindow: DueWindow
  dueDate: string
  onTitleChange: (value: string) => void
  onDueWindowChange: (value: DueWindow) => void
  onDueDateChange: (value: string) => void
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
        placeholder="Add a task…"
        className="min-w-0 flex-1 bg-transparent text-[14px] text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-200 dark:placeholder:text-gray-500"
      />
      <DueWindowPicker
        dueWindow={dueWindow}
        dueDate={dueDate}
        onDueWindowChange={onDueWindowChange}
        onDueDateChange={onDueDateChange}
      />
      <button
        type="submit"
        disabled={!title.trim()}
        className="rounded-lg bg-blue-500 px-3 py-1.5 text-[13px] font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:opacity-40"
      >
        Add
      </button>
    </form>
  )
}

function DueWindowPicker({
  dueWindow,
  dueDate,
  disabled = false,
  onDueWindowChange,
  onDueDateChange,
}: {
  dueWindow: DueWindow
  dueDate: string
  disabled?: boolean
  onDueWindowChange: (value: DueWindow) => void
  onDueDateChange: (value: string) => void
}) {
  const dateInputRef = useRef<HTMLInputElement | null>(null)
  const [open, setOpen] = useState(false)

  function chooseWindow(next: DueWindow) {
    onDueWindowChange(next)
    if (next !== 'exact') onDueDateChange('')
    setOpen(false)
    if (next === 'exact') {
      window.setTimeout(() => dateInputRef.current?.showPicker?.(), 0)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative">
        <button
          type="button"
          disabled={disabled}
          onClick={() => setOpen((value) => !value)}
          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 bg-gray-50 px-2.5 py-1.5 text-[12px] font-medium text-gray-500 transition-colors hover:border-gray-300 hover:text-gray-700 disabled:cursor-default disabled:opacity-50 dark:border-gray-700 dark:bg-[#202024] dark:text-gray-400 dark:hover:text-gray-200"
          style={{ borderWidth: '0.5px' }}
        >
          <CalendarDays size={13} />
          {dueWindowButtonLabel(dueWindow, dueDate, todayISODate())}
          <ChevronDown size={12} />
        </button>
        {open && !disabled && (
          <div
            className="absolute right-0 top-full z-10 mt-1 w-40 rounded-xl border border-gray-200 bg-white p-1 shadow-lg dark:border-gray-800 dark:bg-[#1C1C1E]"
            style={{ borderWidth: '0.5px' }}
          >
            {([
              ['this_week', 'This week'],
              ['this_month', 'This month'],
              ['someday', 'Someday'],
              ['exact', 'Pick a date...'],
            ] as Array<[DueWindow, string]>).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => chooseWindow(value)}
                className="block w-full rounded-lg px-3 py-2 text-left text-[12px] text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
      {dueWindow === 'exact' && !disabled && (
        <input
          ref={dateInputRef}
          type="date"
          value={dueDate}
          onChange={(event) => onDueDateChange(event.target.value)}
          className="w-32 bg-transparent text-[12px] text-gray-400 outline-none"
        />
      )}
    </div>
  )
}

function EmptyTasksState({ filter }: { filter: TaskFilter }) {
  const copy =
    filter === 'active'
      ? { title: 'Nothing on your plate.', body: 'Capture something above and it’ll land here.' }
      : { title: 'No completed tasks yet.', body: 'Finished tasks will appear here once you check them off.' }
  return (
    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 py-10 text-center dark:border-gray-700 dark:bg-[#18181A]">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-white text-gray-400 dark:bg-gray-800 dark:text-gray-500">
        <ListTodo size={18} />
      </div>
      <h3 className="text-[14px] font-medium text-gray-700 dark:text-gray-300">{copy.title}</h3>
      <p className="mx-auto mt-1 max-w-xs text-[12px] leading-5 text-gray-500 dark:text-gray-500">{copy.body}</p>
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
  onChanged,
}: {
  task: TaskItem
  todayISO: string
  priorityRank: number | null
  priorityReason: string | null
  isBestNext: boolean
  isSkippable: boolean
  onChanged: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [title, setTitle] = useState(task.title)
  const [dueWindow, setDueWindow] = useState<DueWindow>(task.due_window)
  const [dueDate, setDueDate] = useState(task.due_date ?? '')

  useEffect(() => {
    setTitle(task.title)
    setDueWindow(task.due_window)
    setDueDate(task.due_date ?? '')
  }, [task.title, task.due_window, task.due_date])

  async function saveTitle() {
    const next = title.trim()
    if (next && next !== task.title) {
      await updateTask(task.id, { title: next })
      onChanged()
    }
    setEditing(false)
  }

  async function saveDue(nextWindow: DueWindow, nextDate: string) {
    setDueWindow(nextWindow)
    setDueDate(nextDate)
    await updateTask(task.id, {
      due_window: nextWindow,
      due_date: nextWindow === 'exact' ? nextDate || null : null,
    })
    onChanged()
  }

  const wasRewritten = task.rewrite_status === 'complete' && Boolean(task.original_title) && task.original_title !== task.title

  return (
    <article
      className={
        isBestNext
          ? 'group rounded-xl border border-blue-300 bg-blue-50/70 shadow-[0_0_0_1px_rgba(59,130,246,0.12),0_16px_34px_-28px_rgba(37,99,235,0.9)] transition-colors hover:border-blue-400 dark:border-blue-900/80 dark:bg-blue-950/20'
          : 'group rounded-xl border border-gray-200 bg-white transition-colors hover:border-gray-300 dark:border-gray-800 dark:bg-[#1C1C1E] dark:hover:border-gray-700'
      }
      style={{ borderWidth: isBestNext ? '1px' : '0.5px' }}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          disabled={task.lifecycle_status === 'completed'}
          onClick={async () => {
            await completeTask(task.id)
            onChanged()
          }}
          className="shrink-0 text-gray-300 transition-colors hover:text-[#1D9E75] disabled:opacity-40"
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
              className="shrink-0 rounded-md p-0.5 text-gray-300 transition-colors hover:text-gray-500 dark:hover:text-gray-200"
            >
              <ChevronDown size={14} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
            </button>
            {editing ? (
              <input
                autoFocus
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                onBlur={() => void saveTitle()}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void saveTitle()
                  if (event.key === 'Escape') {
                    setTitle(task.title)
                    setEditing(false)
                  }
                }}
                className="w-full bg-transparent text-[15px] font-medium text-gray-700 outline-none dark:text-gray-300"
              />
            ) : (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="block max-w-full truncate text-left text-[15px] font-medium leading-snug text-gray-700 dark:text-gray-300"
              >
                {task.title}
              </button>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-gray-400">
            {isBestNext && (
              <span className="rounded-full bg-blue-600 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-white">
                Best next
              </span>
            )}
            {priorityRank && (
              <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-200">
                P{priorityRank}
              </span>
            )}
            {isSkippable && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:bg-amber-950 dark:text-amber-200">
                Low alignment
              </span>
            )}
            {wasRewritten && (
              <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-semibold text-violet-700 dark:bg-violet-950/40 dark:text-violet-200">
                rewritten
              </span>
            )}
            <AsyncStatusPills connection={task.connection_status} chunk={task.chunk_status} bucketUpdate={task.bucket_update_status} />
          </div>
          {expanded && task.description && (
            <p className="mt-2 whitespace-pre-wrap rounded-lg bg-gray-50 px-3 py-2 text-[13px] leading-6 text-gray-600 dark:bg-white/5 dark:text-gray-300">
              {task.description}
            </p>
          )}
          {expanded && wasRewritten && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-gray-500 dark:text-gray-400">
              <span>Original: {task.original_title}</span>
              <button
                type="button"
                onClick={async () => {
                  await revertTaskRewrite(task.id)
                  onChanged()
                }}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-blue-600 transition-colors hover:bg-blue-50 dark:text-blue-300 dark:hover:bg-blue-950/30"
              >
                <RotateCcw size={12} />
                Revert
              </button>
            </div>
          )}
          {priorityReason && (
            <p className="mt-2 rounded-lg bg-white/65 px-3 py-2 text-[12px] leading-5 text-gray-500 dark:bg-white/5 dark:text-gray-400">
              {priorityReason}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 self-start pt-0.5">
          {task.lifecycle_status === 'active' ? (
            <DueWindowPicker
              dueWindow={dueWindow}
              dueDate={dueDate}
              onDueWindowChange={(nextWindow) => {
                if (nextWindow === 'exact') {
                  setDueWindow(nextWindow)
                  return
                }
                void saveDue(nextWindow, '')
              }}
              onDueDateChange={(nextDate) => {
                void saveDue('exact', nextDate)
              }}
            />
          ) : (
            <span
              className={`text-[12px] text-gray-400 ${
                task.due_window === 'exact' && task.due_date === todayISO
                  ? 'font-medium text-blue-500 dark:text-blue-400'
                  : ''
              }`}
            >
              {dueWindowButtonLabel(task.due_window, task.due_date, todayISO)}
            </span>
          )}
          <button
            type="button"
            onClick={async () => {
              await deleteTask(task.id)
              onChanged()
            }}
            className="text-gray-300 opacity-0 transition-[color,opacity] hover:text-red-400 group-hover:opacity-100 focus-visible:opacity-100"
            aria-label={`Delete ${task.title}`}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
    </article>
  )
}

function FilterTabs({ value, onChange }: { value: TaskFilter; onChange: (value: TaskFilter) => void }) {
  return (
    <div className="flex items-center rounded-lg bg-gray-100 p-0.5 dark:bg-gray-800">
      {(['active', 'completed'] as const).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onChange(item)}
          className={
            value === item
              ? 'rounded-md bg-white px-3 py-1 text-[12px] font-medium capitalize text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
              : 'rounded-md px-3 py-1 text-[12px] capitalize text-gray-400 transition-colors hover:text-gray-600 dark:hover:text-gray-300'
          }
        >
          {item}
        </button>
      ))}
    </div>
  )
}

function dueWindowLabel(window: DueWindow, dueDate: string | null, todayISO: string) {
  if (window === 'this_week') return 'This week'
  if (window === 'this_month') return 'This month'
  if (window === 'someday') return null
  if (!dueDate) return 'Pick a date'
  return dueDate === todayISO ? 'today' : dueDate
}

function dueWindowButtonLabel(window: DueWindow, dueDate: string | null, todayISO: string) {
  return dueWindowLabel(window, dueDate, todayISO) ?? 'Someday'
}

function effectiveDueSort(task: TaskItem) {
  const now = new Date()
  if (task.due_window === 'someday') return null
  if (task.due_window === 'exact') return task.due_date
  if (task.due_window === 'this_week') {
    const end = new Date(now)
    const day = end.getDay() === 0 ? 6 : end.getDay() - 1
    end.setDate(end.getDate() + (6 - day))
    return isoDate(end)
  }
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  return isoDate(end)
}

function isoDate(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
