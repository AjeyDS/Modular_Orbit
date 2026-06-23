import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Check, FileText, FolderOpen, Layers, ScrollText, Sparkles } from 'lucide-react'
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
import {
  ChatComposer,
  ChatThread,
  Chip,
  MessageBubble,
  SegmentedControl,
  TypingIndicator,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'
import { chatSessionChangedEvent, newChatEvent } from '../layout/Sidebar'

type ChatMessage =
  | { role: 'assistant' | 'user'; content: string; suggestions?: CaptureProposalPreview[]; sources?: SourceRef[] }
  | { role: 'system'; content: string }

type ProposalSaveState =
  | { status: 'saving' }
  | { status: 'saved' }
  | { status: 'error'; message: string }

const modeOptions: Array<{ value: ChatMode; label: string }> = [
  { value: 'understanding', label: 'Understanding' },
  { value: 'fast', label: 'Fast' },
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
  const [proposalStates, setProposalStates] = useState<Record<string, ProposalSaveState>>({})
  const [streamStatus, setStreamStatus] = useState('')
  const [streamingContent, setStreamingContent] = useState('')
  const greeting = useMemo(() => greetingFor(new Date().getHours()), [])

  const isEmpty = messages.length === 0 && !hydrating

  const resetChat = useCallback(() => {
    setMessages([])
    setDraft('')
    setSessionId(crypto.randomUUID())
    setMode('understanding')
    setPersistedRemotely(false)
    setProposalStates({})
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
    setProposalStates({})
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
            setStreamStatus(STAGE_LABELS[stage] ?? 'Thinking…')
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

  // Save-in-place: confirm the capture proposal and morph the card to a saved
  // state keyed by proposal.id. No system message is appended to the transcript.
  async function acceptSuggestion(proposal: CaptureProposalPreview) {
    setProposalStates((current) => ({ ...current, [proposal.id]: { status: 'saving' } }))
    try {
      await confirmCaptureProposal(proposal.id)
      setProposalStates((current) => ({ ...current, [proposal.id]: { status: 'saved' } }))
    } catch (err) {
      setProposalStates((current) => ({
        ...current,
        [proposal.id]: {
          status: 'error',
          message: err instanceof Error ? err.message : 'Could not save the preview.',
        },
      }))
    }
  }

  return (
    <div className="h-[calc(100vh-3rem)] overflow-hidden bg-bg text-fg">
      <div className={`${pageContentClass} flex h-full flex-col py-6`}>
        {isEmpty ? (
          <div className="flex flex-1 flex-col items-center justify-center px-2">
            <div className="w-full max-w-[42rem]">
              <h1 className="mb-6 text-center text-display font-semibold tracking-[-0.02em] text-fg">{greeting}</h1>
              <ChatComposer
                value={draft}
                onChange={setDraft}
                onSend={() => void sendMessage()}
                placeholder="How can I help today?"
                sending={sending}
                autoFocus
                leftToolbar={
                  <SegmentedControl
                    options={modeOptions}
                    value={mode}
                    onChange={setMode}
                    size="sm"
                    ariaLabel="Reasoning mode"
                  />
                }
              />
              <div className="mt-4 flex flex-wrap justify-center gap-2">
                {prompts.map((prompt) => (
                  <Chip key={prompt} onClick={() => void sendMessage(prompt)}>
                    {prompt}
                  </Chip>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <ChatThread scrollKey={[messages.length, streamStatus, streamingContent]} isEmpty={false}>
            {messages.map((message, index) => (
              <MessageBubble key={`${message.role}-${index}`} role={message.role}>
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
                      <SuggestionCard
                        key={proposal.id}
                        proposal={proposal}
                        state={proposalStates[proposal.id]}
                        onSave={() => void acceptSuggestion(proposal)}
                      />
                    ))}
                  </div>
                )}
              </MessageBubble>
            ))}
            {sending && (
              <MessageBubble role="assistant">
                {streamStatus && (
                  <p className="mb-2 text-caption font-medium text-fg-secondary">{streamStatus}</p>
                )}
                {streamingContent ? <Markdown>{streamingContent}</Markdown> : <TypingIndicator />}
              </MessageBubble>
            )}
          </ChatThread>
        )}

        {!isEmpty && (
          <div className="shrink-0 pt-3">
            <ChatComposer
              value={draft}
              onChange={setDraft}
              onSend={() => void sendMessage()}
              placeholder="Ask your advisor…"
              sending={sending}
              leftToolbar={
                <SegmentedControl
                  options={modeOptions}
                  value={mode}
                  onChange={setMode}
                  size="sm"
                  ariaLabel="Reasoning mode"
                />
              }
            />
          </div>
        )}
      </div>
    </div>
  )
}

function SuggestionCard({
  proposal,
  state,
  onSave,
}: {
  proposal: CaptureProposalPreview
  state: ProposalSaveState | undefined
  onSave: () => void
}) {
  const hint = goalTargetHint(proposal)
  const saved = state?.status === 'saved'
  const saving = state?.status === 'saving'

  return (
    <div
      className={`rounded-control border bg-surface p-3 ${
        saved ? 'border-success/30' : 'border-hairline'
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-caption font-medium uppercase tracking-wide text-accent">
            <Sparkles size={13} />
            {proposalLabel(proposal)}
          </p>
          <h3 className="mt-1 text-label font-medium text-fg">{proposal.title}</h3>
          {hint && <p className="mt-1 text-caption text-fg-secondary">{hint}</p>}
          {proposal.description && (
            <p className="mt-1 text-caption leading-6 text-fg-secondary">{proposal.description}</p>
          )}
          {state?.status === 'error' && <p className="mt-2 text-caption text-danger">{state.message}</p>}
        </div>
        {saved ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 px-3 py-1.5 text-caption font-medium text-success">
            <Check size={13} />
            Saved
          </span>
        ) : (
          <button
            type="button"
            disabled={saving}
            onClick={onSave}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-control bg-accent px-3 py-1.5 text-caption font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97] disabled:opacity-50"
          >
            <Check size={13} />
            {saving ? 'Saving…' : 'Save'}
          </button>
        )}
      </div>
    </div>
  )
}

function SourcesStrip({ sources }: { sources: SourceRef[] }) {
  return (
    <div className="mt-3 border-t border-hairline pt-3">
      <p className="mb-2 text-caption uppercase tracking-wide text-fg-tertiary">Sources</p>
      <div className="flex flex-wrap gap-1.5">
        {sources.map((source) => (
          <span
            key={`${source.kind}-${source.label}`}
            className="inline-flex items-center gap-1 rounded-full border border-hairline bg-surface px-2 py-0.5 text-caption text-fg-secondary"
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
  const className = 'shrink-0 text-fg-tertiary'
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
