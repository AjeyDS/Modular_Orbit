import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Settings, Sparkles } from 'lucide-react'
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
import {
  ChatComposer,
  ChatThread,
  Chip,
  GlassPanel,
  MessageBubble,
  QuickReplyChips,
  SegmentedControl,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'

const CURIOUS_IDLE_WEAVE_MS = 2 * 60 * 1000
const easeOut = [0.23, 1, 0.32, 1] as const

const personaOptions = [
  { value: 'warm', label: 'Warm' },
  { value: 'coach', label: 'Coach' },
  { value: 'gentle', label: 'Gentle' },
  { value: 'direct', label: 'Direct' },
] as const

type PersonaPreset = (typeof personaOptions)[number]['value']

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
      <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
        <div className={`${pageContentClass} py-8 text-center text-body text-fg-tertiary`}>Loading Curious…</div>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} flex min-h-[calc(100vh-3rem)] flex-col py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2">
          <h1 className="text-display font-semibold tracking-[-0.02em] text-fg">Curious</h1>
          <div className="relative flex items-center gap-2">
            <button
              type="button"
              disabled={sending || weaving}
              onClick={() => void askQuestion()}
              className="rounded-control border border-accent/30 bg-accent/10 px-3 py-1.5 text-label font-medium text-accent transition-colors hover:bg-accent/15 disabled:opacity-50"
            >
              Ask me something
            </button>
            <button
              type="button"
              disabled={weaving}
              onClick={() => void endAndClearThread()}
              className="rounded-control border border-hairline bg-surface px-3 py-1.5 text-label font-medium text-fg-secondary transition-colors hover:text-fg disabled:opacity-50"
            >
              {weaving ? 'Updating…' : 'Done'}
            </button>
            <button
              type="button"
              onClick={() => setSettingsOpen((open) => !open)}
              aria-label="Curious settings"
              className="rounded-control p-1.5 text-fg-tertiary transition-colors hover:text-fg"
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
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}
        {status && !error && (
          <div className="mb-3 rounded-control border border-success/30 bg-success/10 px-4 py-3 text-label text-success">
            {status}
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col">
          {companion.pending_checkin && (
            <PendingCheckinGreeting
              message={companion.pending_checkin}
              onQuickReply={(label) => void sendMessage(label)}
            />
          )}

          <ChatThread
            scrollKey={threadMessages.length}
            isEmpty={threadMessages.length === 0}
            empty={
              <div className="px-6 py-12 text-center">
                <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-control bg-surface-inset text-accent">
                  <Sparkles size={18} />
                </div>
                <h3 className="text-body font-medium text-fg">Your companion is listening</h3>
                <p className="mx-auto mt-1 max-w-sm text-caption leading-6 text-fg-secondary">
                  Share an update, answer a question, or just say what&apos;s on your mind.
                </p>
              </div>
            }
          >
            {threadMessages.map((message) => (
              <MessageBubble key={message.id} role={message.role === 'user' ? 'user' : 'assistant'}>
                <p className="whitespace-pre-wrap">{message.content}</p>
                {message.role === 'assistant' && (
                  <>
                    {parseMessageKind(message.meta) === 'question' && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Chip onClick={() => void skipQuestion(readBucketKey(message.meta))}>Skip</Chip>
                        <Chip onClick={() => void talkLater()}>Talk later</Chip>
                      </div>
                    )}
                    <QuickReplyChips
                      replies={parseQuickReplies(message.meta)}
                      onSelect={(label) => void sendMessage(label)}
                    />
                  </>
                )}
              </MessageBubble>
            ))}
          </ChatThread>

          <div className="shrink-0 border-t border-hairline pt-3">
            <ChatComposer
              value={draft}
              onChange={setDraft}
              onSend={() => void sendMessage(draft)}
              placeholder="Share an update or answer…"
              sending={sending}
            />
          </div>
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
      className="mb-4 rounded-card border border-accent/20 ai-wash p-5"
    >
      <p className="mb-1 text-caption uppercase tracking-wide text-accent">Check-in</p>
      <p className="text-body leading-7 text-fg">{message.content}</p>
      <QuickReplyChips replies={quickReplies} onSelect={onQuickReply} />
    </motion.div>
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
  const personaPreset: PersonaPreset =
    typeof settings.companion_persona_preset === 'string' &&
    personaOptions.some((option) => option.value === settings.companion_persona_preset)
      ? (settings.companion_persona_preset as PersonaPreset)
      : 'warm'
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
    <div ref={containerRef}>
      <GlassPanel elevated role="menu" className="absolute right-0 top-full z-20 mt-2 w-[20rem] p-4">
        <p className="text-caption uppercase tracking-wide text-fg-tertiary">Curious settings</p>
        <div className="mt-4 space-y-4">
          <div className="grid gap-2">
            <span className="text-label font-medium text-fg">Companion persona</span>
            <SegmentedControl
              options={personaOptions.map((option) => ({ value: option.value, label: option.label }))}
              value={personaPreset}
              onChange={(value) => onChange({ companion_persona_preset: value })}
              size="sm"
              ariaLabel="Companion persona"
            />
          </div>

          <label className="grid gap-2">
            <span className="text-label font-medium text-fg">Persona override</span>
            <textarea
              value={personaOverride}
              onChange={(event) => onChange({ companion_persona_override: event.target.value })}
              rows={3}
              placeholder="Optional instructions for your companion…"
              className="resize-none rounded-control border border-hairline bg-surface px-3 py-2 text-label text-fg outline-none transition-colors placeholder:text-fg-tertiary focus:border-hairline-strong"
            />
          </label>

          <label className="grid gap-2">
            <span className="flex items-center justify-between text-label font-medium text-fg">
              <span>Check-ins per day</span>
              <span className="text-fg-tertiary">{checkinsPerDay === 0 ? 'Off' : checkinsPerDay}</span>
            </span>
            <input
              type="range"
              min={0}
              max={6}
              value={checkinsPerDay}
              onChange={(event) => onChange({ companion_checkins_per_day: Number(event.target.value) })}
              className="w-full"
              style={{ accentColor: 'var(--accent)' }}
            />
            <span className="text-caption leading-5 text-fg-tertiary">0 turns proactive check-ins off.</span>
          </label>

          <label className="flex items-start justify-between gap-4">
            <span>
              <span className="block text-label font-medium text-fg">Notify me when new questions appear</span>
              <span className="mt-0.5 block text-caption leading-5 text-fg-tertiary">
                Default on. For future dynamic questions.
              </span>
            </span>
            <input
              type="checkbox"
              checked={notify}
              onChange={(event) => onChange({ notify_questions_enabled: event.target.checked })}
              className="mt-1 h-4 w-4"
              style={{ accentColor: 'var(--accent)' }}
            />
          </label>

          <label className="grid gap-2">
            <span className="flex items-center justify-between text-label font-medium text-fg">
              <span>Max new questions per week</span>
              <span className="text-fg-tertiary">{maxWeekly}</span>
            </span>
            <input
              type="range"
              min={0}
              max={10}
              value={maxWeekly}
              onChange={(event) => onChange({ max_new_questions_per_week: Number(event.target.value) })}
              className="w-full"
              style={{ accentColor: 'var(--accent)' }}
            />
          </label>

          <label className="flex items-start justify-between gap-4">
            <span>
              <span className="block text-label font-medium text-fg">Pause Curious</span>
              <span className="mt-0.5 block text-caption leading-5 text-fg-tertiary">
                Stops future dynamic generation. Pending questions stay available.
              </span>
            </span>
            <input
              type="checkbox"
              checked={paused}
              onChange={(event) => onChange({ curious_paused: event.target.checked })}
              className="mt-1 h-4 w-4"
              style={{ accentColor: 'var(--accent)' }}
            />
          </label>
        </div>
      </GlassPanel>
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
