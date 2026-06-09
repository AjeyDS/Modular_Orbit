import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowUp, Check, ChevronDown, FileText, FolderOpen, Layers, ScrollText, Sparkles } from 'lucide-react'
import {
  confirmCaptureProposal,
  fetchChatMessages,
  respondToChat,
  streamChat,
  type CaptureProposalPreview,
  type ChatMessageItem,
  type ChatMode,
  type SourceKind,
  type SourceRef,
} from '../lib/api'
import { Markdown } from '../components/Markdown'
import { pageContentClass } from '../layout/pageShell'
import { chatSessionChangedEvent, newChatEvent } from '../layout/Sidebar'

type ChatMessage =
  | { role: 'assistant' | 'user'; content: string; suggestions?: CaptureProposalPreview[]; sources?: SourceRef[] }
  | { role: 'system'; content: string }

const modes: Array<{ id: ChatMode; label: string; description: string }> = [
  { id: 'understanding', label: 'Understanding', description: 'Reads your user model, then retrieves and synthesizes.' },
  { id: 'fast', label: 'Fast', description: 'Direct answer from retrieved knowledge.' },
]

const prompts = [
  'What should I focus on today?',
  'Help me think through a decision',
  'What do you know about me?',
]

const USER_NAME = 'Ajey'

const STAGE_LABELS: Record<string, string> = {
  thinking: 'Thinking it through…',
  routing: 'Reading your story',
  checking_state: 'Checking your tasks, plans & goals',
  retrieving: 'Searching your knowledge',
  reading_story: 'Pulling it together',
  writing: 'Writing',
}

function greetingFor(hour: number) {
  if (hour < 5) return `Late night, ${USER_NAME}`
  if (hour < 12) return `Good morning, ${USER_NAME}`
  if (hour < 17) return `Good afternoon, ${USER_NAME}`
  if (hour < 22) return `Good evening, ${USER_NAME}`
  return `Late night, ${USER_NAME}`
}

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlSessionId = searchParams.get('session')
  const [sessionId, setSessionId] = useState(() => urlSessionId ?? crypto.randomUUID())
  const [mode, setMode] = useState<ChatMode>('understanding')
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)
  const [hydrating, setHydrating] = useState(false)
  const [persistedRemotely, setPersistedRemotely] = useState(false)
  const [acceptingProposal, setAcceptingProposal] = useState<string | null>(null)
  const [streamStatus, setStreamStatus] = useState('')
  const [streamingContent, setStreamingContent] = useState('')
  const greeting = useMemo(() => greetingFor(new Date().getHours()), [])

  const understandingMode = mode === 'understanding'
  const isEmpty = messages.length === 0 && !hydrating

  const resetChat = useCallback(() => {
    setMessages([])
    setDraft('')
    setSessionId(crypto.randomUUID())
    setMode('understanding')
    setPersistedRemotely(false)
    setSearchParams({}, { replace: true })
  }, [setSearchParams])

  useEffect(() => {
    const handler = () => resetChat()
    window.addEventListener(newChatEvent, handler)
    return () => window.removeEventListener(newChatEvent, handler)
  }, [resetChat])

  // Hydrate from a session URL when it changes (deep-link, sidebar click, refresh).
  useEffect(() => {
    if (!urlSessionId) return
    if (urlSessionId === sessionId && persistedRemotely) return
    let cancelled = false
    setHydrating(true)
    setSessionId(urlSessionId)
    setMessages([])
    setDraft('')
    fetchChatMessages(urlSessionId)
      .then((items) => {
        if (cancelled) return
        setMessages(items.map(_toChatMessage))
        setPersistedRemotely(true)
      })
      .catch(() => {
        if (cancelled) return
        // Unknown session — treat as a fresh chat.
        setMessages([])
        setPersistedRemotely(false)
      })
      .finally(() => {
        if (!cancelled) setHydrating(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSessionId])

  async function sendMessage(text = draft.trim()) {
    const message = text.trim()
    if (!message || sending) return

    const wasNewSession = !persistedRemotely
    setDraft('')
    setSending(true)
    setStreamStatus('')
    setStreamingContent('')
    setMessages((current) => [...current, { role: 'user', content: message }])
    let answer = ''
    let suggestions: CaptureProposalPreview[] = []
    let sources: SourceRef[] = []
    try {
      await streamChat(
        { session_id: sessionId, mode, message },
        {
          onStage: (stage) => {
            setStreamStatus(STAGE_LABELS[stage] ?? stage)
          },
          onAnswerDelta: (delta) => {
            answer += delta
            setStreamingContent((current) => current + delta)
          },
          onDone: ({ suggestions: doneSuggestions, sources: doneSources }) => {
            suggestions = doneSuggestions
            sources = doneSources
          },
        },
      )
      setMessages((current) => [
        ...current,
        {
          role: 'assistant',
          content: answer,
          suggestions,
          sources,
        },
      ])
      setPersistedRemotely(true)
      if (wasNewSession) {
        setSearchParams({ session: sessionId }, { replace: true })
      }
      window.dispatchEvent(new CustomEvent(chatSessionChangedEvent))
    } catch (err) {
      try {
        const response = await respondToChat({ session_id: sessionId, mode, message })
        setMessages((current) => [
          ...current,
          {
            role: 'assistant',
            content: response.answer,
            suggestions: response.suggestions,
            sources: response.sources ?? [],
          },
        ])
        setPersistedRemotely(true)
        if (wasNewSession) {
          setSearchParams({ session: sessionId }, { replace: true })
        }
        window.dispatchEvent(new CustomEvent(chatSessionChangedEvent))
      } catch (fallbackErr) {
        setMessages((current) => [
          ...current,
          {
            role: 'system',
            content: fallbackErr instanceof Error ? fallbackErr.message : 'Chat failed.',
          },
        ])
      }
    } finally {
      setSending(false)
      setStreamStatus('')
      setStreamingContent('')
    }
  }

  function _toChatMessage(item: ChatMessageItem): ChatMessage {
    if (item.role === 'system') {
      return { role: 'system', content: item.content }
    }
    return {
      role: item.role,
      content: item.content,
      suggestions: item.suggestions ?? undefined,
      sources: item.sources ?? undefined,
    }
  }

  async function acceptSuggestion(proposal: CaptureProposalPreview) {
    setAcceptingProposal(proposal.id)
    try {
      const response = await confirmCaptureProposal(proposal.id)
      const savedMessage =
        response.module_id === 'goals' && response.goal_id
          ? 'Saved as a tentative goal — view it on the Goals page.'
          : `Saved ${response.module_id} item.`
      setMessages((current) => [
        ...current,
        {
          role: 'system',
          content: savedMessage,
        },
      ])
    } catch (err) {
      setMessages((current) => [
        ...current,
        {
          role: 'system',
          content: err instanceof Error ? err.message : 'Could not save the preview.',
        },
      ])
    } finally {
      setAcceptingProposal(null)
    }
  }

  return (
    <div className="h-[calc(100vh-3rem)] overflow-hidden bg-gray-50 dark:bg-[#18181A]">
      <div className={`${pageContentClass} flex h-full flex-col py-6`}>
        {isEmpty ? (
          <EmptyState
            greeting={greeting}
            mode={mode}
            understandingMode={understandingMode}
            draft={draft}
            sending={sending}
            onModeChange={setMode}
            onDraftChange={setDraft}
            onSend={() => void sendMessage()}
            onSuggest={(prompt) => void sendMessage(prompt)}
          />
        ) : (
          <ConversationView
            messages={messages}
            sending={sending}
            streamStatus={streamStatus}
            streamingContent={streamingContent}
            acceptingProposal={acceptingProposal}
            onAccept={(p) => void acceptSuggestion(p)}
          />
        )}

        {!isEmpty && (
          <div className="shrink-0 pt-3">
            <Composer
              mode={mode}
              understandingMode={understandingMode}
              draft={draft}
              sending={sending}
              onModeChange={setMode}
              onDraftChange={setDraft}
              onSend={() => void sendMessage()}
            />
          </div>
        )}
      </div>
    </div>
  )
}

function EmptyState({
  greeting,
  mode,
  understandingMode,
  draft,
  sending,
  onModeChange,
  onDraftChange,
  onSend,
  onSuggest,
}: {
  greeting: string
  mode: ChatMode
  understandingMode: boolean
  draft: string
  sending: boolean
  onModeChange: (mode: ChatMode) => void
  onDraftChange: (value: string) => void
  onSend: () => void
  onSuggest: (prompt: string) => void
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-2">
      <div className="w-full max-w-[42rem]">
        <h1 className="mb-6 text-center text-[28px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100 md:text-[32px]">
          {greeting}
        </h1>
        <Composer
          mode={mode}
          understandingMode={understandingMode}
          draft={draft}
          sending={sending}
          onModeChange={onModeChange}
          onDraftChange={onDraftChange}
          onSend={onSend}
          placeholder="How can I help today?"
          autoFocus
        />
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          {prompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onSuggest(prompt)}
              className="cursor-pointer rounded-full border border-gray-200 px-3.5 py-1.5 text-[12px] text-gray-600 transition-colors hover:border-gray-300 hover:bg-white hover:text-gray-800 dark:border-gray-700 dark:text-gray-400 dark:hover:border-gray-600 dark:hover:bg-[#1E1E20] dark:hover:text-gray-200"
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function ConversationView({
  messages,
  sending,
  streamStatus,
  streamingContent,
  acceptingProposal,
  onAccept,
}: {
  messages: ChatMessage[]
  sending: boolean
  streamStatus: string
  streamingContent: string
  acceptingProposal: string | null
  onAccept: (proposal: CaptureProposalPreview) => void
}) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, sending, streamStatus, streamingContent])

  return (
    <div className="flex-1 space-y-6 overflow-y-auto py-4">
      {messages.map((message, index) => (
        <article key={`${message.role}-${index}`} className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
          <div
            className={`max-w-[min(85%,42rem)] px-4 py-3 text-[14px] leading-7 ${
              message.role === 'user'
                ? 'rounded-2xl rounded-br-sm bg-blue-500 text-white'
                : message.role === 'system'
                  ? 'rounded-xl border border-amber-200 bg-amber-50 text-[13px] text-amber-800 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200'
                  : 'rounded-2xl rounded-bl-sm bg-gray-50 text-gray-800 dark:bg-gray-800/30 dark:text-gray-200'
            }`}
          >
            {message.role === 'assistant' ? (
              <Markdown>{message.content}</Markdown>
            ) : (
              <p className="whitespace-pre-wrap">{message.content}</p>
            )}
            {message.role === 'assistant' && message.sources && message.sources.length > 0 && (
              <SourcesStrip sources={message.sources} />
            )}
            {'suggestions' in message && message.suggestions && message.suggestions.length > 0 && (
              <div className="mt-4 grid gap-2">
                {message.suggestions.map((proposal) => (
                  <div
                    key={proposal.id}
                    className="rounded-xl border border-gray-200 bg-white p-3 text-gray-800 dark:border-gray-700 dark:bg-[#1C1C1E] dark:text-gray-200"
                    style={{ borderWidth: '0.5px' }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-blue-500">
                          <Sparkles size={13} />
                          {proposalLabel(proposal)}
                        </p>
                        <h3 className="mt-1 text-[14px] font-medium">{proposal.title}</h3>
                        {goalTargetHint(proposal) && (
                          <p className="mt-1 text-[12px] text-gray-500 dark:text-gray-400">{goalTargetHint(proposal)}</p>
                        )}
                        {proposal.description && (
                          <p className="mt-1 text-[13px] leading-6 text-gray-500 dark:text-gray-400">
                            {proposal.description}
                          </p>
                        )}
                      </div>
                      <button
                        type="button"
                        disabled={acceptingProposal === proposal.id}
                        onClick={() => onAccept(proposal)}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-blue-500 px-3 py-1.5 text-[12px] font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:opacity-50"
                      >
                        <Check size={13} />
                        Save
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </article>
      ))}
      {sending && (
        <div className="flex justify-start">
          <div className="max-w-[min(85%,42rem)] rounded-2xl rounded-bl-sm bg-gray-50 px-4 py-3 text-[14px] leading-7 text-gray-800 dark:bg-gray-800/30 dark:text-gray-200">
            {streamStatus && (
              <p className="mb-2 text-[12px] font-medium text-violet-600 dark:text-violet-300">{streamStatus}</p>
            )}
            {streamingContent ? (
              <Markdown>{streamingContent}</Markdown>
            ) : (
              <div className="flex h-5 items-center space-x-1.5">
                <div className="h-2 w-2 animate-bounce rounded-full bg-gray-400 dark:bg-gray-500" />
                <div
                  className="h-2 w-2 animate-bounce rounded-full bg-gray-400 dark:bg-gray-500"
                  style={{ animationDelay: '150ms' }}
                />
                <div
                  className="h-2 w-2 animate-bounce rounded-full bg-gray-400 dark:bg-gray-500"
                  style={{ animationDelay: '300ms' }}
                />
              </div>
            )}
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}

function Composer({
  mode,
  understandingMode,
  draft,
  sending,
  onModeChange,
  onDraftChange,
  onSend,
  placeholder = 'Ask your advisor…',
  autoFocus = false,
}: {
  mode: ChatMode
  understandingMode: boolean
  draft: string
  sending: boolean
  onModeChange: (mode: ChatMode) => void
  onDraftChange: (value: string) => void
  onSend: () => void
  placeholder?: string
  autoFocus?: boolean
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`
  }, [draft])

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus()
  }, [autoFocus])

  return (
    <div
      className={`relative rounded-2xl border bg-white shadow-sm transition-colors dark:bg-[#1E1E20] ${
        understandingMode
          ? 'border-violet-300 focus-within:border-violet-400 dark:border-violet-700 dark:focus-within:border-violet-500'
          : 'border-gray-200 focus-within:border-gray-300 dark:border-gray-700 dark:focus-within:border-gray-600'
      }`}
      style={{ borderWidth: '0.5px' }}
    >
      <textarea
        ref={textareaRef}
        value={draft}
        rows={1}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            onSend()
          }
        }}
        placeholder={placeholder}
        className="w-full resize-none overflow-y-auto bg-transparent px-4 pt-3 text-[14px] text-gray-800 outline-none placeholder:text-gray-400 dark:text-gray-200 dark:placeholder:text-gray-500"
        style={{ maxHeight: '140px' }}
      />
      <div className="flex items-center justify-between gap-2 px-3 pb-2 pt-1">
        <ModePicker mode={mode} onChange={onModeChange} />
        <button
          type="button"
          onClick={onSend}
          disabled={!draft.trim() || sending}
          aria-label="Send"
          className={`rounded-lg p-1.5 transition-[color,transform,background-color] duration-150 ease-out ${
            draft.trim()
              ? understandingMode
                ? 'bg-violet-500 text-white hover:bg-violet-600 active:scale-[0.97]'
                : 'bg-blue-500 text-white hover:bg-blue-600 active:scale-[0.97]'
              : 'cursor-default bg-gray-100 text-gray-300 dark:bg-gray-800 dark:text-gray-600'
          }`}
        >
          <ArrowUp size={16} />
        </button>
      </div>
    </div>
  )
}

function ModePicker({ mode, onChange }: { mode: ChatMode; onChange: (mode: ChatMode) => void }) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const active = modes.find((item) => item.id === mode) ?? modes[0]

  useEffect(() => {
    if (!open) return
    function onDocClick(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium transition-colors ${
          mode === 'understanding'
            ? 'text-violet-600 hover:bg-violet-50 dark:text-violet-300 dark:hover:bg-violet-950/30'
            : 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'
        }`}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {active.label}
        <ChevronDown size={12} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 mb-2 w-[15rem] rounded-xl border border-gray-200 bg-white p-1 shadow-lg dark:border-gray-800 dark:bg-[#1C1C1E]"
          style={{ borderWidth: '0.5px' }}
        >
          {modes.map((item) => {
            const isActive = mode === item.id
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  onChange(item.id)
                  setOpen(false)
                }}
                className={`flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left transition-colors ${
                  isActive
                    ? 'bg-gray-100 dark:bg-gray-800'
                    : 'hover:bg-gray-100 dark:hover:bg-gray-800'
                }`}
              >
                <div className="min-w-0 flex-1">
                  <p className={`text-[13px] font-medium ${item.id === 'understanding' ? 'text-violet-600 dark:text-violet-300' : 'text-gray-900 dark:text-gray-100'}`}>
                    {item.label}
                  </p>
                  <p className="mt-0.5 text-[11px] leading-4 text-gray-500 dark:text-gray-400">{item.description}</p>
                </div>
                {isActive && <Check size={14} className="mt-0.5 shrink-0 text-blue-500" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

function SourcesStrip({ sources }: { sources: SourceRef[] }) {
  return (
    <div className="mt-3 border-t border-gray-200/80 pt-3 dark:border-gray-700/80">
      <p className="mb-2 text-[10px] font-medium uppercase tracking-[0.14em] text-gray-400 dark:text-gray-500">Sources</p>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((source) => (
          <span
            key={`${source.kind}-${source.label}`}
            className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-white px-2 py-0.5 text-[11px] text-gray-600 dark:border-gray-700 dark:bg-[#1C1C1E] dark:text-gray-400"
            style={{ borderWidth: '0.5px' }}
          >
            <SourceIcon kind={source.kind} />
            <span className="max-w-[12rem] truncate">{source.label}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function SourceIcon({ kind }: { kind: SourceKind }) {
  const className = 'shrink-0 text-gray-400 dark:text-gray-500'
  if (kind === 'document') return <FileText size={11} className={className} />
  if (kind === 'bucket') return <FolderOpen size={11} className={className} />
  if (kind === 'module') return <Layers size={11} className={className} />
  return <ScrollText size={11} className={className} />
}

function proposalLabel(proposal: CaptureProposalPreview) {
  if (proposal.module_id === 'goals') return 'Add as goal?'
  return `Preview ${proposal.module_id}`
}

function goalTargetHint(proposal: CaptureProposalPreview) {
  if (proposal.module_id !== 'goals') return null
  const note = typeof proposal.payload?.target_note === 'string' ? proposal.payload.target_note.trim() : ''
  if (note) return note
  return proposal.payload?.horizon === 'short_term' ? 'Short-term goal' : 'Long-term goal'
}
