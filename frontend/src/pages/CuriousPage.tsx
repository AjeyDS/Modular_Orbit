import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronDown, Settings, Sparkles } from 'lucide-react'
import {
  answerCuriousPendingQuestion,
  fetchShellState,
  fetchCuriousState,
  sendCuriousWeaveBeacon,
  updateModuleInstanceSettings,
  weavePendingCuriousUpdates,
  type CuriousAnsweredGroup,
  type CuriousPageState,
  type CuriousPendingQuestion,
  type ModuleInstanceItem,
} from '../lib/api'
import { pageContentClass } from '../layout/pageShell'

const CURIOUS_IDLE_WEAVE_MS = 2 * 60 * 1000
const easeOut = [0.23, 1, 0.32, 1] as const

export default function CuriousPage() {
  const [state, setState] = useState<CuriousPageState | null>(null)
  const [skippedIds, setSkippedIds] = useState<Set<string>>(() => new Set())
  const [selectedOption, setSelectedOption] = useState('')
  const [saving, setSaving] = useState(false)
  const [weaving, setWeaving] = useState(false)
  const [hasPendingWeave, setHasPendingWeave] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [learnedOpen, setLearnedOpen] = useState(false)
  const [curiousInstance, setCuriousInstance] = useState<ModuleInstanceItem | null>(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const pendingWeaveRef = useRef(false)
  const idleTimerRef = useRef<number | null>(null)
  const flushingRef = useRef(false)

  async function load() {
    setError('')
    try {
      const [next, shell] = await Promise.all([fetchCuriousState(), fetchShellState()])
      setState(next)
      setCuriousInstance(shell.enabled_modules.find((module) => module.module_id === 'curious') ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Curious')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  // Drop skipped IDs that are no longer in the pending list (after a save brings new state).
  useEffect(() => {
    if (!state) return
    setSkippedIds((prev) => {
      const liveIds = new Set(state.pending_questions.map((p) => p.question.id))
      const next = new Set([...prev].filter((id) => liveIds.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [state])

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
        const result = await weavePendingCuriousUpdates()
        const mergedCount = result.results.reduce((total, item) => total + item.merged_count, 0)
        if (reason === 'done') {
          setStatus(
            mergedCount > 0
              ? `Updated ${mergedCount} bucket note${mergedCount === 1 ? '' : 's'}.`
              : 'Buckets are already up to date.',
          )
        }
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
      sendCuriousWeaveBeacon()
    }
    window.addEventListener('pagehide', flushOnPageHide)
    return () => {
      window.removeEventListener('pagehide', flushOnPageHide)
      clearIdleWeave()
      if (pendingWeaveRef.current) {
        pendingWeaveRef.current = false
        setHasPendingWeave(false)
        sendCuriousWeaveBeacon()
      }
    }
  }, [clearIdleWeave])

  const focusQueue = useMemo(() => {
    if (!state) return [] as CuriousPendingQuestion[]
    const nonSkipped = state.pending_questions.filter((p) => !skippedIds.has(p.question.id))
    const skipped = state.pending_questions.filter((p) => skippedIds.has(p.question.id))
    return [...nonSkipped, ...skipped]
  }, [state, skippedIds])

  const focus = focusQueue[0] ?? null
  const remainingAfter = Math.max(focusQueue.length - 1, 0)

  // Reset the selected option whenever the focus question changes.
  const focusId = focus?.question.id ?? null
  useEffect(() => {
    setSelectedOption('')
  }, [focusId])

  const answeredCount = useMemo(
    () => (state ? state.answered_groups.reduce((sum, group) => sum + group.answers.length, 0) : 0),
    [state],
  )

  async function answerQuestion(pending: CuriousPendingQuestion) {
    if (!selectedOption || saving) return
    setSaving(true)
    setError('')
    setStatus('')
    try {
      const next = await answerCuriousPendingQuestion({
        question_life_item_id: pending.life_item_id,
        session_id: state?.onboarding.session_id ?? null,
        question_id: pending.question.id,
        option_id: selectedOption,
      })
      setState(next)
      setSelectedOption('')
      if (pending.question.tier !== 'onboarding') {
        pendingWeaveRef.current = true
        setHasPendingWeave(true)
        scheduleIdleWeave()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save answer')
    } finally {
      setSaving(false)
    }
  }

  function skipFocus() {
    if (!focus || focusQueue.length <= 1) return
    setSkippedIds((prev) => {
      const next = new Set(prev)
      next.add(focus.question.id)
      return next
    })
  }

  async function updateCuriousSettings(partial: Record<string, unknown>) {
    if (!curiousInstance) return
    const nextSettings = { ...curiousInstance.settings, ...partial }
    setCuriousInstance({ ...curiousInstance, settings: nextSettings })
    try {
      const updated = await updateModuleInstanceSettings(curiousInstance.id, nextSettings)
      setCuriousInstance(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update Curious settings')
    }
  }

  if (!state) {
    return (
      <div className="min-h-[calc(100vh-3rem)] bg-gray-50 dark:bg-[#18181A]">
        <div className={`${pageContentClass} py-8 text-center text-[14px] text-gray-400`}>Loading Curious…</div>
      </div>
    )
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Curious</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{answeredCount}</span> answered
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{state.pending_count}</span> pending
            </p>
          </div>
          <div className="relative flex items-center gap-2">
            {hasPendingWeave && (
              <button
                type="button"
                disabled={weaving}
                onClick={() => void flushCuriousSession('done')}
                className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-[12px] font-medium text-emerald-700 transition-colors hover:bg-emerald-100 disabled:opacity-50 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200 dark:hover:bg-emerald-950/50"
                style={{ borderWidth: '0.5px' }}
              >
                {weaving ? 'Updating…' : 'Done for now'}
              </button>
            )}
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

        <div className="space-y-5">
          <AnimatePresence mode="wait" initial={false}>
            {focus ? (
              <FocusQuestion
                key={focus.question.id}
                pending={focus}
                selectedOption={selectedOption}
                saving={saving}
                remainingAfter={remainingAfter}
                onSelect={setSelectedOption}
                onAnswer={() => void answerQuestion(focus)}
                onSkip={focusQueue.length > 1 ? skipFocus : null}
              />
            ) : (
              <EmptyState key="empty" />
            )}
          </AnimatePresence>

          <LearnedAccordion
            open={learnedOpen}
            onToggle={() => setLearnedOpen((value) => !value)}
            selfProfile={state.self_profile}
            answeredGroups={state.answered_groups}
            answeredCount={answeredCount}
          />

          {state.preview.length > 0 && <UserModelPreview preview={state.preview} />}
        </div>
      </div>
    </div>
  )
}

function FocusQuestion({
  pending,
  selectedOption,
  saving,
  remainingAfter,
  onSelect,
  onAnswer,
  onSkip,
}: {
  pending: CuriousPendingQuestion
  selectedOption: string
  saving: boolean
  remainingAfter: number
  onSelect: (optionId: string) => void
  onAnswer: () => void
  onSkip: (() => void) | null
}) {
  const question = pending.question
  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2, ease: easeOut }}
      className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E] sm:p-7"
      style={{ borderWidth: '0.5px' }}
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-600 dark:bg-blue-950/40 dark:text-blue-300">
          {question.source_label}
        </span>
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-medium text-gray-500 dark:bg-gray-800 dark:text-gray-400">
          {question.target_bucket_name}
        </span>
        {question.foundational && (
          <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-300">
            Foundational
          </span>
        )}
      </div>

      {question.framing_text && (
        <p className="mb-2 text-[12px] uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">
          {question.framing_text}
        </p>
      )}

      <h2 className="mb-6 text-[22px] font-medium leading-tight tracking-[-0.01em] text-gray-900 dark:text-gray-100 sm:text-[24px]">
        {question.question_text}
      </h2>

      <div className="space-y-2">
        {question.options.map((option) => {
          const selected = selectedOption === option.id
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => onSelect(option.id)}
              className={`flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-[14px] transition-[border-color,background-color,transform] duration-150 ease-out active:scale-[0.99] ${
                selected
                  ? 'border-blue-400 bg-blue-50/60 text-gray-900 dark:border-blue-500 dark:bg-blue-950/30 dark:text-gray-100'
                  : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-300 dark:hover:border-gray-600 dark:hover:bg-[#202024]'
              }`}
              style={{ borderWidth: '0.5px' }}
            >
              <span
                className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border transition-colors ${
                  selected
                    ? 'border-blue-500 bg-blue-500 text-white'
                    : 'border-gray-300 dark:border-gray-600'
                }`}
              >
                {selected && <Check size={10} strokeWidth={3} />}
              </span>
              <span className="font-medium">{option.label}</span>
            </button>
          )
        })}
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[12px] text-gray-400 dark:text-gray-500">
          {onSkip && (
            <>
              <button
                type="button"
                onClick={onSkip}
                className="rounded-md px-2 py-1 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              >
                Skip
              </button>
              <span className="text-gray-300 dark:text-gray-700">·</span>
            </>
          )}
          <span>
            {remainingAfter === 0
              ? 'Last one'
              : `${remainingAfter} more after this`}
          </span>
        </div>
        <button
          type="button"
          disabled={!selectedOption || saving}
          onClick={onAnswer}
          className="rounded-xl bg-blue-500 px-4 py-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save answer'}
        </button>
      </div>
    </motion.article>
  )
}

function EmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2, ease: easeOut }}
      className="rounded-2xl border border-dashed border-gray-200 bg-white/60 px-6 py-12 text-center dark:border-gray-700 dark:bg-[#1C1C1E]/60"
      style={{ borderWidth: '0.5px' }}
    >
      <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-500 dark:bg-blue-950/40 dark:text-blue-300">
        <Sparkles size={18} />
      </div>
      <h3 className="text-[15px] font-medium text-gray-800 dark:text-gray-200">You're caught up</h3>
      <p className="mx-auto mt-1 max-w-sm text-[13px] leading-6 text-gray-500 dark:text-gray-500">
        Orbit will surface more questions as you keep using it. Check back later.
      </p>
    </motion.div>
  )
}

function LearnedAccordion({
  open,
  onToggle,
  selfProfile,
  answeredGroups,
  answeredCount,
}: {
  open: boolean
  onToggle: () => void
  selfProfile: string
  answeredGroups: CuriousAnsweredGroup[]
  answeredCount: number
}) {
  return (
    <section
      className="rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
      style={{ borderWidth: '0.5px' }}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left"
      >
        <div className="flex items-baseline gap-3">
          <span className="text-[14px] font-semibold text-gray-800 dark:text-gray-200">What Orbit's learned</span>
          <span className="text-[12px] text-gray-500 dark:text-gray-500">
            <span className="tabular-nums">{answeredCount}</span> answer{answeredCount === 1 ? '' : 's'}
            <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
            <span className="tabular-nums">{answeredGroups.length}</span> bucket{answeredGroups.length === 1 ? '' : 's'}
          </span>
        </div>
        <ChevronDown
          size={16}
          className={`shrink-0 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 py-5 dark:border-gray-800">
          {selfProfile && (
            <div className="mb-6">
              <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">
                Self profile
              </p>
              <p className="text-[14px] leading-7 text-gray-700 dark:text-gray-300">{selfProfile}</p>
            </div>
          )}

          <p className="mb-3 text-[11px] font-medium uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">
            Answered by bucket
          </p>
          {answeredGroups.length === 0 ? (
            <p className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-4 py-6 text-center text-[13px] text-gray-400 dark:border-gray-700 dark:bg-[#18181A]">
              Nothing answered yet.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {answeredGroups.map((group) => (
                <article
                  key={group.target_bucket_key}
                  className="rounded-xl border border-gray-200 bg-gray-50/60 p-3 dark:border-gray-800 dark:bg-[#18181A]"
                  style={{ borderWidth: '0.5px' }}
                >
                  <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-gray-400 dark:text-gray-500">
                    {group.target_bucket_name}
                    <span className="ml-1 text-gray-300 dark:text-gray-700">·</span>
                    <span className="ml-1 tabular-nums">{group.answers.length}</span>
                  </p>
                  <div className="mt-2 space-y-1">
                    {group.answers.map((answer) => (
                      <button
                        key={answer.life_item_id}
                        type="button"
                        onClick={() => {
                          window.location.href = `/chat?item=${answer.life_item_id}`
                        }}
                        className="block w-full rounded-md px-2 py-1.5 text-left text-[13px] leading-5 text-gray-600 transition-colors hover:bg-white dark:text-gray-300 dark:hover:bg-[#202024]"
                      >
                        {answer.bucket_update_text}
                      </button>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function UserModelPreview({
  preview,
}: {
  preview: CuriousPageState['preview']
}) {
  return (
    <section
      className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
      style={{ borderWidth: '0.5px' }}
    >
      <h2 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200">What I'll add to your user model</h2>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        {preview.map((group) => (
          <article
            key={group.target_bucket_key}
            className="rounded-xl border border-gray-200 bg-gray-50/70 p-3 dark:border-gray-800 dark:bg-[#18181A]"
            style={{ borderWidth: '0.5px' }}
          >
            <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-gray-400 dark:text-gray-500">
              {group.target_bucket_name}
            </p>
            <ul className="mt-2 space-y-1.5">
              {group.lines.map((line) => (
                <li key={line} className="text-[13px] leading-5 text-gray-600 dark:text-gray-300">
                  {line}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
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
