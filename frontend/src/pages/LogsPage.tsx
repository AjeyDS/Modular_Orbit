import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { Archive, ListChecks, RefreshCw, Trash2 } from 'lucide-react'
import { archiveLog, createLog, deleteLog, fetchLogs, type LogItem } from '../lib/api'
import { AsyncStatusPills } from '../components/status'
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
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

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

  async function submitLog() {
    const text = draft.trim()
    if (!text || saving) return
    setSaving(true)
    setError('')
    try {
      await createLog({ text })
      setDraft('')
      await loadLogs()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create log')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Logs</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{stats.total}</span>{' '}
              {stats.total === 1 ? 'entry' : 'entries'}
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{stats.today}</span> today
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{stats.week}</span> this week
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
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search logs…"
              className="min-w-0 flex-1 rounded-lg bg-gray-100 px-3 py-1.5 text-[13px] text-gray-800 outline-none placeholder:text-gray-400 transition-colors focus:bg-white focus:ring-1 focus:ring-gray-300 dark:bg-gray-800 dark:text-gray-200 dark:placeholder:text-gray-500 dark:focus:bg-[#1E1E20] dark:focus:ring-gray-700"
            />
            <button
              type="button"
              onClick={() => void loadLogs()}
              aria-label="Refresh logs"
              title="Refresh"
              className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            >
              <RefreshCw size={15} />
            </button>
          </div>

          <LogComposer
            value={draft}
            saving={saving}
            onChange={setDraft}
            onSubmit={() => void submitLog()}
          />

          <div className="mt-4">
            {loading && logs.length === 0 ? (
              <div className="py-10 text-center text-[14px] text-gray-400">Loading logs…</div>
            ) : grouped.length === 0 ? (
              <EmptyLogsState />
            ) : (
              <div className="space-y-6">
                {grouped.map((group) => (
                  <section key={group.date}>
                    <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">
                      {formatDateHeader(group.date)}
                    </p>
                    <div className="divide-y divide-gray-100 dark:divide-gray-800">
                      {group.items.map((log) => (
                        <LogRow
                          key={log.id}
                          log={log}
                          onArchive={async () => {
                            await archiveLog(log.id)
                            setLogs((current) => current.filter((item) => item.id !== log.id))
                          }}
                          onDelete={async () => {
                            if (!confirm('Delete this log entry?')) return
                            await deleteLog(log.id)
                            setLogs((current) => current.filter((item) => item.id !== log.id))
                          }}
                        />
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function LogComposer({
  value,
  saving,
  onChange,
  onSubmit,
}: {
  value: string
  saving: boolean
  onChange: (value: string) => void
  onSubmit: () => void
}) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }, [value])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      onSubmit()
    }
  }

  return (
    <div
      className="rounded-xl border border-gray-200 bg-white px-3 py-2 transition-colors focus-within:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:focus-within:border-gray-600"
      style={{ borderWidth: '0.5px' }}
    >
      <textarea
        ref={textareaRef}
        rows={1}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Capture a log… (event, thought, observation, useful context)"
        className="block w-full resize-none bg-transparent text-[14px] leading-6 text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-200 dark:placeholder:text-gray-500"
      />
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <p className="text-[11px] text-gray-400 dark:text-gray-500">
          ⌘/Ctrl + Enter to capture
        </p>
        <button
          type="button"
          disabled={saving || !value.trim()}
          onClick={onSubmit}
          className="rounded-lg bg-blue-500 px-3 py-1.5 text-[12px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
        >
          {saving ? 'Capturing…' : 'Capture'}
        </button>
      </div>
    </div>
  )
}

function EmptyLogsState() {
  const copy = { title: 'Nothing captured yet.', body: 'Drop your first thought above. Cmd+Enter saves it.' }
  return (
    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 py-10 text-center dark:border-gray-700 dark:bg-[#18181A]">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-white text-gray-400 dark:bg-gray-800 dark:text-gray-500">
        <ListChecks size={18} />
      </div>
      <h3 className="text-[14px] font-medium text-gray-700 dark:text-gray-300">{copy.title}</h3>
      <p className="mx-auto mt-1 max-w-xs text-[12px] leading-5 text-gray-500 dark:text-gray-500">{copy.body}</p>
    </div>
  )
}

function LogRow({
  log,
  onArchive,
  onDelete,
}: {
  log: LogItem
  onArchive: () => void | Promise<void>
  onDelete: () => void | Promise<void>
}) {
  const hasPendingWork =
    log.connection_status !== 'complete' ||
    (log.chunk_status !== 'complete' && log.chunk_status !== 'not_needed') ||
    (log.bucket_update_status !== 'complete' && log.bucket_update_status !== 'not_needed')

  return (
    <article className="group flex items-start justify-between gap-4 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] leading-6 text-gray-800 dark:text-gray-200">{log.text}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
          <span className="tabular-nums">{formatTime(log.occurred_at)}</span>
          {hasPendingWork && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-medium text-amber-800 dark:bg-amber-950/50 dark:text-amber-200">
              connections {log.connection_status}
            </span>
          )}
          <AsyncStatusPills connection={log.connection_status} chunk={log.chunk_status} bucketUpdate={log.bucket_update_status} />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
        <button
          type="button"
          onClick={() => void onArchive()}
          title="Archive log"
          className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
        >
          <Archive size={14} />
        </button>
        <button
          type="button"
          onClick={() => void onDelete()}
          title="Delete log"
          className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-red-500 dark:hover:bg-gray-800"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </article>
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
