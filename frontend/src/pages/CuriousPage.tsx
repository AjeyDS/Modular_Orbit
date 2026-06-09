import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { ArrowUp, Settings, Sparkles } from 'lucide-react'
import {
  askCompanionQuestion,
  endCompanionSession,
  fetchCompanionState,
  fetchShellState,
  sendCompanionEndBeacon,
  sendCompanionMessage,
  skipCompanionQuestion,
  updateModuleInstanceSettings,
  type CompanionMessageItem,
  type CompanionState,
  type ModuleInstanceItem,
} from '../lib/api'
import { pageContentClass } from '../layout/pageShell'

const CURIOUS_IDLE_WEAVE_MS = 2 * 60 * 1000
const easeOut = [0.23, 1, 0.32, 1] as const

type QuickReply = { id?: string; label: string }

export default function CuriousPage() {
  const [companion, setCompanion] = useState<CompanionState | null>(null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [optimisticMessages, setOptimisticMessages] = useState<CompanionMessageItem[]>([])
  const [weaving, setWeaving] = useState(false)
  const [hasPendingWeave, setHasPendingWeave] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [curiousInstance, setCuriousInstance] = useState<ModuleInstanceItem | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const pendingWeaveRef = useRef(false)
  const idleTimerRef = useRef<number | null>(null)
  const flushingRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  async function load() {
    setError('')
    try {
      const [next, shell] = await Promise.all([fetchCompanionState(), fetchShellState()])
      setCompanion(next)
      setOptimisticMessages([])
      setCuriousInstance(shell.enabled_modules.find((module) => module.module_id === 'curious') ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Curious')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }, [draft])

  const clearIdleWeave = useCallback(() => {
    if (idleTimerRef.current !== null) {
      window.clearTimeout(idleTimerRef.current)
      idleTimerRef.current = null
    }
  }, [])

  const flushCuriousSession = useCallback(
    async (reason: 'done' | 'idle' | 'leave') => {
      if (!pendingWeaveRef.current || flushingRef.current) return
      flushingRef.current = true
      pendingWeaveRef.current = false
      setHasPendingWeave(false)
      clearIdleWeave()
      if (reason === 'done') {
        setWeaving(true)
        setStatus('')
        setError('')
      }
      try {
        const result = await endCompanionSession()
        const mergedCount = result.results.reduce((total, item) => total + item.merged_count, 0)
        if (reason === 'done') {
          setStatus(
            mergedCount > 0
              ? `Updated ${mergedCount} bucket note${mergedCount === 1 ? '' : 's'}.`
              : 'Buckets are already up to date.',
          )
        }
        await load()
      } catch (err) {
        pendingWeaveRef.current = true
        setHasPendingWeave(true)
        if (reason === 'done') {
          setError(err instanceof Error ? err.message : 'Unable to update buckets')
        }
      } finally {
        flushingRef.current = false
        if (reason === 'done') setWeaving(false)
      }
    },
    [clearIdleWeave],
  )

  const scheduleIdleWeave = useCallback(() => {
    clearIdleWeave()
    idleTimerRef.current = window.setTimeout(() => {
      void flushCuriousSession('idle')
    }, CURIOUS_IDLE_WEAVE_MS)
  }, [clearIdleWeave, flushCuriousSession])

  useEffect(() => {
    const flushOnPageHide = () => {
      if (!pendingWeaveRef.current) return
      pendingWeaveRef.current = false
      setHasPendingWeave(false)
      sendCompanionEndBeacon()
    }
    window.addEventListener('pagehide', flushOnPageHide)
    return () => {
      window.removeEventListener('pagehide', flushOnPageHide)
      clearIdleWeave()
      if (pendingWeaveRef.current) {
        pendingWeaveRef.current = false
        setHasPendingWeave(false)
        sendCompanionEndBeacon()
      }
    }
  }, [clearIdleWeave])

  const threadMessages = useMemo(() => {
    if (!companion) return optimisticMessages
    const persisted = companion.pending_checkin
      ? companion.messages.filter((message) => message.id !== companion.pending_checkin?.id)
      : companion.messages
    return [...persisted, ...optimisticMessages]
  }, [companion, optimisticMessages])

  async function sendMessage(text: string) {
    const trimmed = text.trim()
    if (!trimmed || sending) return
    setSending(true)
    setError('')
    setStatus('')
    const optimisticUser: CompanionMessageItem = {
      id: `optimistic-user-${Date.now()}`,
      role: 'user',
      content: trimmed,
      meta: {},
      created_at: new Date().toISOString(),
    }
    setOptimisticMessages((prev) => [...prev, optimisticUser])
    setDraft('')
    try {
      const response = await sendCompanionMessage(trimmed)
      if (response.reply.kind === 'ended') {
        pendingWeaveRef.current = false
        setHasPendingWeave(false)
        clearIdleWeave()
        await load()
        return
      }
      const optimisticAssistant: CompanionMessageItem = {
        id: `optimistic-assistant-${Date.now()}`,
        role: 'assistant',
        content: response.reply.message,
        meta: {
          kind: response.reply.kind,
          quick_replies: response.reply.quick_replies,
          target_bucket_key: response.reply.target_bucket_key,
        },
        created_at: new Date().toISOString(),
      }
      setOptimisticMessages((prev) => [...prev, optimisticAssistant])
      pendingWeaveRef.current = true
      setHasPendingWeave(true)
      scheduleIdleWeave()
      const refreshed = await fetchCompanionState()
      setCompanion(refreshed)
      setOptimisticMessages([])
    } catch (err) {
      setOptimisticMessages((prev) => prev.filter((message) => message.id !== optimisticUser.id))
      setError(err instanceof Error ? err.message : 'Unable to send message')
    } finally {
      setSending(false)
    }
  }

  async function askQuestion() {
    if (sending) return
    setSending(true)
    setError('')
    setStatus('')
    try {
      await askCompanionQuestion()
      const refreshed = await fetchCompanionState()
      setCompanion(refreshed)
      setOptimisticMessages([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to ask a question')
    } finally {
      setSending(false)
    }
  }

  async function skipQuestion(bucketKey?: string | null) {
    if (sending) return
    setSending(true)
    setError('')
    try {
      await skipCompanionQuestion(bucketKey)
      const refreshed = await fetchCompanionState()
      setCompanion(refreshed)
      setOptimisticMessages([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to skip question')
    } finally {
      setSending(false)
    }
  }

  async function endAndClearThread() {
    await flushCuriousSession('done')
  }

  async function talkLater() {
    if (sending) return
    setSending(true)
    setError('')
    try {
      await sendCompanionMessage('talk to you later')
      pendingWeaveRef.current = false
      setHasPendingWeave(false)
      clearIdleWeave()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to end conversation')
    } finally {
      setSending(false)
    }
  }

  async function updateCuriousSettings(partial: Record<string, unknown>) {
    if (!curiousInstance) return
    const nextSettings = { ...curiousInstance.settings, ...partial }
    setCuriousInstance({ ...curiousInstance, settings: nextSettings })
    try {
      const updated = await updateModuleInstanceSettings(curiousInstance.id, nextSettings)
      setCuriousInstance(updated)
      const refreshed = await fetchCompanionState()
      setCompanion(refreshed)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update Curious settings')
    }
  }

  if (!companion) {
    return (
      <div className="min-h-[calc(100vh-3rem)] bg-gray-50 dark:bg-[#18181A]">
        <div className={`${pageContentClass} py-8 text-center text-[14px] text-gray-400`}>Loading Curious…</div>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} flex min-h-[calc(100vh-3rem)] flex-col py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2">
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Curious</h1>
          <div className="relative flex items-center gap-2">
            <button
              type="button"
              disabled={sending || weaving}
              onClick={() => void askQuestion()}
              className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-[12px] font-medium text-blue-700 transition-colors hover:bg-blue-100 disabled:opacity-50 dark:border-blue-900/70 dark:bg-blue-950/30 dark:text-blue-200 dark:hover:bg-blue-950/50"
              style={{ borderWidth: '0.5px' }}
            >
              Ask me something
            </button>
            <button
              type="button"
              disabled={weaving}
              onClick={() => void endAndClearThread()}
              className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[12px] font-medium text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-50 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200 dark:hover:bg-emerald-950/50"
              style={{ borderWidth: '0.5px' }}
            >
              {weaving ? 'Updating…' : 'Done'}
            </button>
            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              aria-label="Curious settings"
              className="rounded-md p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
            >
              <Settings size={15} />
            </button>
            {settingsOpen && curiousInstance && (
              <CuriousSettingsPopover
                settings={curiousInstance.settings}
                onClose={() => setSettingsOpen(false)}
                onChange={(partial) => void updateCuriousSettings(partial)}
              />
            )}
          </div>
        </header>

        {error && (
          <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        )}
        {status && !error && (
          <div className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200">
            {status}
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col gap-5">
          {companion.pending_checkin && (
            <PendingCheckinGreeting
              message={companion.pending_checkin}
              onQuickReply={(label) => void sendMessage(label)}
            />
          )}

          <section
            className="flex min-h-[20rem] flex-1 flex-col rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
            style={{ borderWidth: '0.5px' }}
          >
            <CompanionThread
              messages={threadMessages}
              onQuickReply={(label) => void sendMessage(label)}
              onSkip={(bucketKey) => void skipQuestion(bucketKey)}
              onTalkLater={() => void talkLater()}
            />
            <div className="border-t border-gray-100 p-3 dark:border-gray-800">
              <div
                className="relative rounded-2xl border border-gray-200 bg-white shadow-sm transition-colors focus-within:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:focus-within:border-gray-600"
                style={{ borderWidth: '0.5px' }}
              >
                <textarea
                  ref={textareaRef}
                  value={draft}
                  rows={1}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      void sendMessage(draft)
                    }
                  }}
                  placeholder="Share an update or answer…"
                  className="w-full resize-none overflow-y-auto bg-transparent px-4 py-3 text-[14px] leading-6 text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-200 dark:placeholder:text-gray-500"
                  style={{ maxHeight: '140px', minHeight: '2.75rem' }}
                />
                <div className="flex items-center justify-end px-3 pb-2 pt-1">
                  <button
                    type="button"
                    onClick={() => void sendMessage(draft)}
                    disabled={!draft.trim() || sending}
                    aria-label="Send"
                    className={`rounded-lg p-1.5 transition-[color,transform,background-color] duration-150 ease-out ${
                      draft.trim()
                        ? 'bg-blue-500 text-white hover:bg-blue-600 active:scale-[0.97]'
                        : 'cursor-default bg-gray-100 text-gray-300 dark:bg-gray-800 dark:text-gray-600'
                    }`}
                  >
                    <ArrowUp size={16} />
                  </button>
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function PendingCheckinGreeting({
  message,
  onQuickReply,
}: {
  message: CompanionMessageItem
  onQuickReply: (label: string) => void
}) {
  const quickReplies = parseQuickReplies(message.meta)
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: easeOut }}
      className="rounded-2xl border border-violet-200 bg-violet-50/70 p-5 shadow-sm dark:border-violet-900/50 dark:bg-violet-950/20"
      style={{ borderWidth: '0.5px' }}
    >
      <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.14em] text-violet-500 dark:text-violet-300">
        Check-in
      </p>
      <p className="text-[15px] leading-7 text-gray-800 dark:text-gray-100">{message.content}</p>
      <QuickReplyChips replies={quickReplies} onSelect={onQuickReply} />
    </motion.div>
  )
}

function CompanionThread({
  messages,
  onQuickReply,
  onSkip,
  onTalkLater,
}: {
  messages: CompanionMessageItem[]
  onQuickReply: (label: string) => void
  onSkip: (bucketKey?: string | null) => void
  onTalkLater: () => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 text-center">
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-500 dark:bg-blue-950/40 dark:text-blue-300">
          <Sparkles size={18} />
        </div>
        <h3 className="text-[15px] font-medium text-gray-800 dark:text-gray-200">Your companion is listening</h3>
        <p className="mx-auto mt-1 max-w-sm text-[13px] leading-6 text-gray-500 dark:text-gray-500">
          Share an update, answer a question, or just say what&apos;s on your mind.
        </p>
      </div>
    )
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-5">
      {messages.map((message) => (
        <article
          key={message.id}
          className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
        >
          <div
            className={`max-w-[min(85%,42rem)] px-4 py-3 text-[14px] leading-7 ${
              message.role === 'user'
                ? 'rounded-2xl rounded-br-sm bg-blue-500 text-white'
                : 'rounded-2xl rounded-bl-sm bg-gray-50 text-gray-800 dark:bg-gray-800/30 dark:text-gray-200'
            }`}
          >
            <p className="whitespace-pre-wrap">{message.content}</p>
            {message.role === 'assistant' && (
              <>
                {parseMessageKind(message.meta) === 'question' && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <LifecycleChip label="Skip" onClick={() => onSkip(readBucketKey(message.meta))} />
                    <LifecycleChip label="Talk later" onClick={onTalkLater} />
                  </div>
                )}
                <QuickReplyChips replies={parseQuickReplies(message.meta)} onSelect={onQuickReply} />
              </>
            )}
          </div>
        </article>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

function LifecycleChip({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full border border-gray-200 bg-white px-3 py-1 text-[12px] text-gray-600 transition-colors hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-[#1C1C1E] dark:text-gray-400 dark:hover:border-gray-600"
      style={{ borderWidth: '0.5px' }}
    >
      {label}
    </button>
  )
}

function QuickReplyChips({
  replies,
  onSelect,
}: {
  replies: QuickReply[]
  onSelect: (label: string) => void
}) {
  if (replies.length === 0) return null
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {replies.map((reply) => (
        <button
          key={reply.id ?? reply.label}
          type="button"
          onClick={() => onSelect(reply.label)}
          className="rounded-full border border-gray-200 bg-white px-3 py-1 text-[12px] text-gray-700 transition-colors hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-[#1C1C1E] dark:text-gray-300 dark:hover:border-gray-600"
          style={{ borderWidth: '0.5px' }}
        >
          {reply.label}
        </button>
      ))}
    </div>
  )
}

function CuriousSettingsPopover({
  settings,
  onChange,
  onClose,
}: {
  settings: Record<string, unknown>
  onChange: (partial: Record<string, unknown>) => void
  onClose: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const notify = settings.notify_questions_enabled !== false
  const paused = settings.curious_paused === true
  const maxWeekly = typeof settings.max_new_questions_per_week === 'number' ? settings.max_new_questions_per_week : 3
  const personaPreset =
    typeof settings.companion_persona_preset === 'string' ? settings.companion_persona_preset : 'warm'
  const personaOverride =
    typeof settings.companion_persona_override === 'string' ? settings.companion_persona_override : ''
  const checkinsPerDay =
    typeof settings.companion_checkins_per_day === 'number' ? settings.companion_checkins_per_day : 0

  useEffect(() => {
    function onDocClick(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) onClose()
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  return (
    <div
      ref={containerRef}
      role="menu"
      className="absolute right-0 top-full z-20 mt-2 w-[20rem] rounded-xl border border-gray-200 bg-white p-4 shadow-xl dark:border-gray-800 dark:bg-[#1C1C1E]"
      style={{ borderWidth: '0.5px' }}
    >
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-gray-400">Curious settings</p>
      <div className="mt-4 space-y-4">
        <label className="grid gap-2">
          <span className="text-[13px] font-medium text-gray-800 dark:text-gray-200">Companion persona</span>
          <select
            value={personaPreset}
            onChange={(event) => onChange({ companion_persona_preset: event.target.value })}
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-[13px] text-gray-800 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200"
            style={{ borderWidth: '0.5px' }}
          >
            <option value="warm">Warm</option>
            <option value="coach">Coach</option>
            <option value="gentle">Gentle</option>
            <option value="direct">Direct</option>
          </select>
        </label>

        <label className="grid gap-2">
          <span className="text-[13px] font-medium text-gray-800 dark:text-gray-200">Persona override</span>
          <textarea
            value={personaOverride}
            onChange={(event) => onChange({ companion_persona_override: event.target.value })}
            rows={3}
            placeholder="Optional instructions for your companion…"
            className="resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-[13px] text-gray-800 outline-none placeholder:text-gray-400 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200"
            style={{ borderWidth: '0.5px' }}
          />
        </label>

        <label className="grid gap-2">
          <span className="flex items-center justify-between text-[13px] font-medium text-gray-800 dark:text-gray-200">
            <span>Check-ins per day</span>
            <span className="text-gray-400">{checkinsPerDay === 0 ? 'Off' : checkinsPerDay}</span>
          </span>
          <input
            type="range"
            min={0}
            max={6}
            value={checkinsPerDay}
            onChange={(event) => onChange({ companion_checkins_per_day: Number(event.target.value) })}
            className="w-full accent-violet-500"
          />
          <span className="text-[12px] leading-5 text-gray-400">0 turns proactive check-ins off.</span>
        </label>

        <label className="flex items-start justify-between gap-4">
          <span>
            <span className="block text-[13px] font-medium text-gray-800 dark:text-gray-200">Notify me when new questions appear</span>
            <span className="mt-0.5 block text-[12px] leading-5 text-gray-400">Default on. For future dynamic questions.</span>
          </span>
          <input
            type="checkbox"
            checked={notify}
            onChange={(event) => onChange({ notify_questions_enabled: event.target.checked })}
            className="mt-1 h-4 w-4 accent-blue-500"
          />
        </label>

        <label className="grid gap-2">
          <span className="flex items-center justify-between text-[13px] font-medium text-gray-800 dark:text-gray-200">
            <span>Max new questions per week</span>
            <span className="text-gray-400">{maxWeekly}</span>
          </span>
          <input
            type="range"
            min={0}
            max={10}
            value={maxWeekly}
            onChange={(event) => onChange({ max_new_questions_per_week: Number(event.target.value) })}
            className="w-full accent-blue-500"
          />
        </label>

        <label className="flex items-start justify-between gap-4">
          <span>
            <span className="block text-[13px] font-medium text-gray-800 dark:text-gray-200">Pause Curious</span>
            <span className="mt-0.5 block text-[12px] leading-5 text-gray-400">Stops future dynamic generation. Pending questions stay available.</span>
          </span>
          <input
            type="checkbox"
            checked={paused}
            onChange={(event) => onChange({ curious_paused: event.target.checked })}
            className="mt-1 h-4 w-4 accent-blue-500"
          />
        </label>
      </div>
    </div>
  )
}

function parseMessageKind(meta: Record<string, unknown>): string {
  return typeof meta.kind === 'string' ? meta.kind : ''
}

function readBucketKey(meta: Record<string, unknown>): string | null {
  return typeof meta.target_bucket_key === 'string' ? meta.target_bucket_key : null
}

function parseQuickReplies(meta: Record<string, unknown>): QuickReply[] {
  const raw = meta.quick_replies
  if (!Array.isArray(raw)) return []
  return raw
    .map((item) => {
      if (typeof item === 'string') return { label: item }
      if (item && typeof item === 'object' && 'label' in item && typeof item.label === 'string') {
        return {
          id: typeof item.id === 'string' ? item.id : undefined,
          label: item.label,
        }
      }
      return null
    })
    .filter((item): item is QuickReply => item !== null)
}

