import { useEffect, useMemo, useState } from 'react'
import { Archive, Plus, RefreshCw, ScrollText, Trash2 } from 'lucide-react'
import { AnimatePresence } from 'framer-motion'
import { archiveLog, createLog, deleteLog, fetchLogs, type LogItem } from '../lib/api'
import { AsyncStatusPills } from '../components/status'
import {
  CollectionRow,
  Composer,
  EmptyState,
  RowActions,
  SkeletonRows,
  useToast,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'

function todayISODate() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

function isoForDate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function LogsPage() {
  const [logs, setLogs] = useState<LogItem[]>([])
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const { toast, undoToast } = useToast()

  async function loadLogs() {
    setLoading(true)
    setError('')
    try {
      setLogs(await fetchLogs())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load logs')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadLogs()
  }, [])

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

  const visibleLogs = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return logs
    return logs.filter((log) => `${log.title} ${log.text}`.toLowerCase().includes(normalized))
  }, [logs, query])

  const grouped = useMemo(() => groupLogs(visibleLogs), [visibleLogs])

  const stats = useMemo(() => {
    const weekAgo = new Date()
    weekAgo.setDate(weekAgo.getDate() - 7)
    let today = 0
    let week = 0
    for (const log of logs) {
      const occurred = new Date(log.occurred_at)
      if (isoForDate(occurred) === todayISO) today++
      if (occurred.getTime() >= weekAgo.getTime()) week++
    }
    return { total: logs.length, today, week }
  }, [logs, todayISO])

  // Optimistic capture: prepend a placeholder log so it lands under Today
  // instantly, then reconcile against the server-returned item (whose async
  // status fields update via the refresh path). Roll back on failure.
  async function handleAdd() {
    const text = draft.trim()
    if (!text) return
    const now = new Date().toISOString()
    const tempId = `temp-${now}-${Math.random().toString(36).slice(2)}`
    const optimistic: LogItem = {
      id: tempId,
      title: text,
      text,
      lifecycle_status: 'active',
      connection_status: 'pending',
      chunk_status: 'pending',
      bucket_update_status: 'pending',
      occurred_at: now,
      created_at: now,
      updated_at: now,
    }
    setDraft('')
    setError('')
    setLogs((current) => [optimistic, ...current])
    try {
      const created = await createLog({ text })
      setLogs((current) => current.map((log) => (log.id === tempId ? created : log)))
    } catch (err) {
      setLogs((current) => current.filter((log) => log.id !== tempId))
      setError(err instanceof Error ? err.message : 'Unable to create log')
    }
  }

  // Optimistic archive + undo: drop the log immediately, restore it into its
  // original slot on undo, persist on commit.
  function handleArchive(log: LogItem) {
    const index = logs.findIndex((item) => item.id === log.id)

    setLogs((current) => current.filter((item) => item.id !== log.id))

    undoToast({
      message: 'Log archived',
      onUndo: () => {
        setLogs((current) => {
          const next = [...current]
          next.splice(Math.min(index < 0 ? next.length : index, next.length), 0, log)
          return next
        })
      },
      onCommit: () => {
        void archiveLog(log.id).catch((err) => {
          toast({ message: err instanceof Error ? err.message : 'Unable to archive log', tone: 'danger' })
          void loadLogs()
        })
      },
    })
  }

  // Optimistic delete + undo: same pattern as archive, restoring the exact
  // removed log into the right day group via its original index.
  function handleDelete(log: LogItem) {
    const index = logs.findIndex((item) => item.id === log.id)

    setLogs((current) => current.filter((item) => item.id !== log.id))

    undoToast({
      message: 'Log deleted',
      onUndo: () => {
        setLogs((current) => {
          const next = [...current]
          next.splice(Math.min(index < 0 ? next.length : index, next.length), 0, log)
          return next
        })
      },
      onCommit: () => {
        void deleteLog(log.id).catch((err) => {
          toast({ message: err instanceof Error ? err.message : 'Unable to delete log', tone: 'danger' })
          void loadLogs()
        })
      },
    })
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Logs</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{stats.total}</span>{' '}
              {stats.total === 1 ? 'entry' : 'entries'}
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{stats.today}</span> today
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{stats.week}</span> this week
            </p>
          </div>
          <p className="text-caption text-fg-tertiary">{todayLabel}</p>
        </header>

        {error && (
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search logs…"
            className="min-w-0 flex-1 rounded-control bg-surface-inset px-3 py-1.5 text-label text-fg outline-none transition-colors placeholder:text-fg-tertiary focus:bg-surface focus:ring-1 focus:ring-hairline-strong"
          />
          <button
            type="button"
            onClick={() => void loadLogs()}
            aria-label="Refresh logs"
            title="Refresh"
            className="rounded-control p-1.5 text-fg-tertiary transition-colors hover:text-fg"
          >
            <RefreshCw size={15} />
          </button>
        </div>

        <div className="border-b border-hairline pb-2">
          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => void handleAdd()}
            placeholder="Capture a log…"
            bare
            multiline
            submitIcon={<Plus size={16} />}
          />
        </div>

        {loading && logs.length === 0 ? (
          <div className="mt-3">
            <SkeletonRows count={3} />
          </div>
        ) : grouped.length === 0 ? (
          <div className="mt-3">
            <EmptyState
              icon={<ScrollText size={18} />}
              title="Nothing captured yet."
              body="Drop your first thought above."
            />
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            {grouped.map((group) => (
              <section key={group.date}>
                <p className="mb-1 text-caption font-medium uppercase tracking-wider text-fg-tertiary">
                  {formatDateHeader(group.date)}
                </p>
                <div className="divide-y divide-hairline">
                  <AnimatePresence initial={false}>
                    {group.items.map((log) => (
                      <LogRow
                        key={log.id}
                        log={log}
                        onArchive={() => handleArchive(log)}
                        onDelete={() => handleDelete(log)}
                      />
                    ))}
                  </AnimatePresence>
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function LogRow({
  log,
  onArchive,
  onDelete,
}: {
  log: LogItem
  onArchive: () => void
  onDelete: () => void
}) {
  return (
    <CollectionRow variant="plain">
      <div className="flex items-start justify-between gap-4 px-1 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="whitespace-pre-wrap text-body leading-6 text-fg">{log.text}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-caption text-fg-tertiary">
            <span className="tabular-nums">{formatTime(log.occurred_at)}</span>
            <AsyncStatusPills
              connection={log.connection_status}
              chunk={log.chunk_status}
              bucketUpdate={log.bucket_update_status}
            />
          </div>
        </div>
        <RowActions className="self-start pt-0.5">
          <button
            type="button"
            onClick={onArchive}
            aria-label="Archive log"
            className="text-fg-tertiary transition-colors hover:text-fg"
          >
            <Archive size={14} />
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label="Delete log"
            className="text-fg-tertiary transition-colors hover:text-danger"
          >
            <Trash2 size={14} />
          </button>
        </RowActions>
      </div>
    </CollectionRow>
  )
}

function groupLogs(logs: LogItem[]) {
  const groups = new Map<string, LogItem[]>()
  for (const log of logs) {
    const occurred = new Date(log.occurred_at)
    const key = isoForDate(occurred)
    groups.set(key, [...(groups.get(key) ?? []), log])
  }
  return [...groups.entries()].map(([date, items]) => ({ date, items }))
}

function formatDateHeader(date: string) {
  const value = new Date(`${date}T00:00:00`)
  const today = new Date()
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)

  const sameDate = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()

  if (sameDate(value, today)) return 'Today'
  if (sameDate(value, yesterday)) return 'Yesterday'

  const weekday = value.toLocaleDateString('en-US', { weekday: 'short' })
  const label = value.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return `${weekday} · ${label}`
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
  })
}
