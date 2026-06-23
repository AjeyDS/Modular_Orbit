import { useEffect, useMemo, useState } from 'react'
import { Archive, CheckCircle2, Circle, Flame, Plus } from 'lucide-react'
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
import {
  CollectionRow,
  CollectionView,
  Composer,
  EditableTitle,
  EmptyState,
  RowActions,
  useToast,
} from '../components/ui'
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
  const [error, setError] = useState('')
  const { toast, undoToast } = useToast()

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

  const items = state?.items ?? []
  const completed = state?.completed_count ?? 0
  const total = state?.total_count ?? 0

  async function handleAdd() {
    const title = newTitle.trim()
    if (!title) return
    setError('')
    try {
      const created = await createRoutineItem({ title, position: items.length })
      setNewTitle('')
      // Append the server-derived item so streak / status fields are correct.
      setState((current) =>
        current
          ? {
              ...current,
              items: [...current.items, created],
              total_count: current.total_count + 1,
              completed_count: current.completed_count + (created.today_completed ? 1 : 0),
            }
          : current,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create routine item')
    }
  }

  // Optimistic toggle: flip today_completed + nudge the streak and the done
  // count immediately, then reconcile to the server's item on success (the API
  // returns the authoritative streak). Reload on error.
  function handleToggle(item: RoutineItem) {
    const willComplete = !item.today_completed
    const optimistic: RoutineItem = {
      ...item,
      today_completed: willComplete,
      streak_count: Math.max(0, item.streak_count + (willComplete ? 1 : -1)),
    }
    setState((current) =>
      current
        ? {
            ...current,
            items: current.items.map((it) => (it.id === item.id ? optimistic : it)),
            completed_count: current.completed_count + (willComplete ? 1 : -1),
          }
        : current,
    )

    const request = willComplete
      ? completeRoutineItem(item.id, todayISO)
      : uncompleteRoutineItem(item.id, todayISO)
    void request
      .then((server) => {
        // Reconcile against the authoritative streak the server returned.
        setState((current) =>
          current
            ? { ...current, items: current.items.map((it) => (it.id === server.id ? server : it)) }
            : current,
        )
      })
      .catch((err) => {
        toast({ message: err instanceof Error ? err.message : 'Unable to update routine item', tone: 'danger' })
        void load()
      })
  }

  // Optimistic rename: patch local state then persist in the background.
  function handleRename(id: string, title: string) {
    setState((current) =>
      current
        ? { ...current, items: current.items.map((it) => (it.id === id ? { ...it, title } : it)) }
        : current,
    )
    void updateRoutineItem(id, { title }).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to rename routine item', tone: 'danger' })
      void load()
    })
  }

  // Optimistic archive + undo: remove immediately, restore on undo, persist on commit.
  function handleArchive(item: RoutineItem) {
    const index = items.findIndex((it) => it.id === item.id)
    setState((current) =>
      current
        ? {
            ...current,
            items: current.items.filter((it) => it.id !== item.id),
            total_count: Math.max(0, current.total_count - 1),
            completed_count: Math.max(0, current.completed_count - (item.today_completed ? 1 : 0)),
          }
        : current,
    )

    undoToast({
      message: 'Routine archived',
      onUndo: () => {
        setState((current) => {
          if (!current) return current
          const next = [...current.items]
          next.splice(Math.min(index < 0 ? next.length : index, next.length), 0, item)
          return {
            ...current,
            items: next,
            total_count: current.total_count + 1,
            completed_count: current.completed_count + (item.today_completed ? 1 : 0),
          }
        })
      },
      onCommit: () => {
        void archiveRoutineItem(item.id).catch((err) => {
          toast({ message: err instanceof Error ? err.message : 'Unable to archive routine item', tone: 'danger' })
          void load()
        })
      },
    })
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Routine</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{completed}</span>/<span className="tabular-nums">{total}</span> done
            </p>
          </div>
          <p className="text-caption text-fg-tertiary">{todayLabel}</p>
        </header>

        {error && (
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}

        <CollectionView
          divided
          composer={
            <div className="border-b border-hairline pb-2">
              <Composer
                value={newTitle}
                onChange={setNewTitle}
                onSubmit={handleAdd}
                placeholder="Add routine item…"
                bare
                submitIcon={<Plus size={16} />}
              />
            </div>
          }
          loading={loading && items.length === 0}
          isEmpty={items.length === 0}
          empty={
            <EmptyState
              icon={<Flame size={18} />}
              title="No routine items yet."
              body="Add the first thing you want to check off each day."
            />
          }
        >
          {items.map((item) => (
            <RoutineRow
              key={item.id}
              item={item}
              onToggle={handleToggle}
              onRename={handleRename}
              onArchive={handleArchive}
            />
          ))}
        </CollectionView>
      </div>
    </div>
  )
}

function RoutineRow({
  item,
  onToggle,
  onRename,
  onArchive,
}: {
  item: RoutineItem
  onToggle: (item: RoutineItem) => void
  onRename: (id: string, title: string) => void
  onArchive: (item: RoutineItem) => void
}) {
  return (
    <CollectionRow variant="plain">
      <div className="flex items-center gap-3 px-1 py-3">
        <button
          type="button"
          onClick={() => onToggle(item)}
          className={
            item.today_completed
              ? 'shrink-0 text-success transition-colors'
              : 'shrink-0 text-fg-tertiary transition-colors hover:text-success'
          }
          aria-label={item.today_completed ? `Uncheck ${item.title}` : `Check ${item.title}`}
        >
          {item.today_completed ? (
            <CheckCircle2 size={20} strokeWidth={1.7} />
          ) : (
            <Circle size={20} strokeWidth={1.7} />
          )}
        </button>

        <div className="min-w-0 flex-1">
          <EditableTitle
            value={item.title}
            onSave={(next) => onRename(item.id, next)}
            className={
              item.today_completed
                ? 'block max-w-full truncate text-body font-medium leading-snug text-fg-secondary line-through'
                : 'block max-w-full truncate text-body font-medium leading-snug text-fg'
            }
          />
          <div className="mt-1 flex flex-wrap items-center gap-2 text-caption text-fg-tertiary">
            {item.description && <span className="truncate">{item.description}</span>}
            <AsyncStatusPills
              connection={item.connection_status}
              chunk={item.chunk_status}
              bucketUpdate={item.bucket_update_status}
            />
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <div
            className={
              item.streak_count > 0
                ? 'inline-flex min-w-12 items-center justify-end gap-1 text-warn'
                : 'inline-flex min-w-12 items-center justify-end gap-1 text-fg-tertiary'
            }
            aria-label={`${item.streak_count} day streak`}
          >
            <Flame size={16} fill="currentColor" strokeWidth={1.7} />
            <span className="text-label font-semibold tabular-nums">{item.streak_count}</span>
          </div>
          <RowActions>
            <button
              type="button"
              onClick={() => onArchive(item)}
              className="rounded-md p-1.5 text-fg-tertiary transition-colors hover:text-fg-secondary"
              aria-label={`Archive ${item.title}`}
            >
              <Archive size={14} />
            </button>
          </RowActions>
        </div>
      </div>
    </CollectionRow>
  )
}
