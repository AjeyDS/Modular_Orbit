import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { Archive, CheckCircle2, Circle, Flame, ListChecks } from 'lucide-react'
import {
  archiveRoutineItem,
  completeRoutineItem,
  createRoutineItem,
  fetchRoutineState,
  uncompleteRoutineItem,
  updateRoutineItem,
  type RoutineItem,
  type RoutineState,
} from '../lib/api'
import { AsyncStatusPills } from '../components/status'
import { pageContentClass } from '../layout/pageShell'

function todayISODate() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export default function RoutinePage() {
  const todayISO = useMemo(todayISODate, [])
  const todayLabel = useMemo(
    () =>
      new Date(`${todayISO}T00:00:00`).toLocaleDateString(undefined, {
        weekday: 'long',
        month: 'long',
        day: 'numeric',
      }),
    [todayISO],
  )
  const [state, setState] = useState<RoutineState | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      setState(await fetchRoutineState(todayISO))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load routine')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function handleAdd(event?: FormEvent) {
    event?.preventDefault()
    const title = newTitle.trim()
    if (!title || saving) return
    setSaving(true)
    setError('')
    try {
      await createRoutineItem({
        title,
        position: state?.items.length ?? 0,
      })
      setNewTitle('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create routine item')
    } finally {
      setSaving(false)
    }
  }

  const items = state?.items ?? []
  const completed = state?.completed_count ?? 0
  const total = state?.total_count ?? 0

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Routine</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{completed}</span>/<span className="tabular-nums">{total}</span> done
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
          <RoutineComposer
            title={newTitle}
            saving={saving}
            onTitleChange={setNewTitle}
            onSubmit={handleAdd}
          />

          <div className="mt-3 space-y-1">
            {loading && items.length === 0 ? (
              <div className="py-10 text-center text-[14px] text-gray-400">Loading routine…</div>
            ) : items.length === 0 ? (
              <EmptyRoutineState />
            ) : (
              items.map((item) => (
                <RoutineRow
                  key={item.id}
                  item={item}
                  date={todayISO}
                  onChanged={() => void load()}
                  onError={setError}
                />
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function RoutineComposer({
  title,
  saving,
  onTitleChange,
  onSubmit,
}: {
  title: string
  saving: boolean
  onTitleChange: (value: string) => void
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
        placeholder="Add routine item…"
        className="min-w-0 flex-1 bg-transparent text-[14px] text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-200 dark:placeholder:text-gray-500"
      />
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

function RoutineRow({
  item,
  date,
  onChanged,
  onError,
}: {
  item: RoutineItem
  date: string
  onChanged: () => void
  onError: (message: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(item.title)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setTitle(item.title)
  }, [item.title])

  async function toggleComplete() {
    if (busy) return
    setBusy(true)
    onError('')
    try {
      if (item.today_completed) {
        await uncompleteRoutineItem(item.id, date)
      } else {
        await completeRoutineItem(item.id, date)
      }
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Unable to update routine item')
    } finally {
      setBusy(false)
    }
  }

  async function saveTitle() {
    const next = title.trim()
    if (next && next !== item.title) {
      try {
        await updateRoutineItem(item.id, { title: next })
        onChanged()
      } catch (err) {
        onError(err instanceof Error ? err.message : 'Unable to rename routine item')
      }
    }
    setEditing(false)
  }

  async function archiveItem() {
    if (busy) return
    setBusy(true)
    onError('')
    try {
      await archiveRoutineItem(item.id)
      onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Unable to archive routine item')
    } finally {
      setBusy(false)
    }
  }

  return (
    <article
      className={
        item.today_completed
          ? 'group rounded-xl border border-emerald-200 bg-emerald-50/70 transition-colors hover:border-emerald-300 dark:border-emerald-950/70 dark:bg-emerald-950/20'
          : 'group rounded-xl border border-gray-200 bg-white transition-colors hover:border-gray-300 dark:border-gray-800 dark:bg-[#1C1C1E] dark:hover:border-gray-700'
      }
      style={{ borderWidth: '0.5px' }}
    >
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => void toggleComplete()}
          className={
            item.today_completed
              ? 'shrink-0 text-[#1D9E75] transition-colors disabled:opacity-50'
              : 'shrink-0 text-gray-300 transition-colors hover:text-[#1D9E75] disabled:opacity-50'
          }
          aria-label={item.today_completed ? `Uncheck ${item.title}` : `Check ${item.title}`}
        >
          {item.today_completed ? <CheckCircle2 size={20} strokeWidth={1.7} /> : <Circle size={20} strokeWidth={1.7} />}
        </button>

        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onBlur={() => void saveTitle()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void saveTitle()
                if (event.key === 'Escape') {
                  setTitle(item.title)
                  setEditing(false)
                }
              }}
              className="w-full bg-transparent text-[15px] font-medium text-gray-700 outline-none dark:text-gray-300"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditing(true)}
              className={`block max-w-full truncate text-left text-[15px] font-medium leading-snug ${
                item.today_completed
                  ? 'text-gray-500 line-through decoration-emerald-400/70 dark:text-gray-400'
                  : 'text-gray-700 dark:text-gray-300'
              }`}
            >
              {item.title}
            </button>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-gray-400">
            {item.description && <span className="truncate">{item.description}</span>}
            <AsyncStatusPills connection={item.connection_status} chunk={item.chunk_status} bucketUpdate={item.bucket_update_status} />
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <div
            className={
              item.streak_count > 0
                ? 'inline-flex min-w-12 items-center justify-end gap-1 text-orange-500 dark:text-orange-300'
                : 'inline-flex min-w-12 items-center justify-end gap-1 text-gray-300 dark:text-gray-600'
            }
            aria-label={`${item.streak_count} day streak`}
          >
            <Flame size={16} fill="currentColor" strokeWidth={1.7} />
            <span className="text-[13px] font-semibold tabular-nums">{item.streak_count}</span>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void archiveItem()}
            className="rounded-md p-1.5 text-gray-300 opacity-0 transition-[color,opacity] hover:bg-gray-100 hover:text-gray-600 group-hover:opacity-100 focus-visible:opacity-100 disabled:opacity-30 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            aria-label={`Archive ${item.title}`}
          >
            <Archive size={14} />
          </button>
        </div>
      </div>
    </article>
  )
}

function EmptyRoutineState() {
  return (
    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 py-10 text-center dark:border-gray-700 dark:bg-[#18181A]">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-white text-gray-400 dark:bg-gray-800 dark:text-gray-500">
        <ListChecks size={18} />
      </div>
      <h3 className="text-[14px] font-medium text-gray-700 dark:text-gray-300">No routine items yet.</h3>
      <p className="mx-auto mt-1 max-w-xs text-[12px] leading-5 text-gray-500 dark:text-gray-500">
        Add the first thing you want to check off each day.
      </p>
    </div>
  )
}
