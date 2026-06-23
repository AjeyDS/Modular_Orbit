import {
  useEffect,
  useLayoutEffect,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { ArrowUp } from 'lucide-react'
import { cn } from './cn'

const MAX_TEXTAREA_HEIGHT = 140

export type MessageRole = 'user' | 'assistant' | 'system'

interface MessageBubbleProps {
  role: MessageRole
  children: ReactNode
  className?: string
}

const bubbleStyles: Record<MessageRole, string> = {
  user: 'max-w-[min(85%,42rem)] rounded-2xl rounded-br-sm bg-accent px-4 py-3 text-body leading-7 text-white',
  assistant:
    'max-w-[min(85%,42rem)] rounded-2xl rounded-bl-sm bg-surface-inset px-4 py-3 text-body leading-7 text-fg',
  system:
    'max-w-[min(85%,42rem)] rounded-control border border-warn/30 bg-warn/10 px-4 py-3 text-label leading-7 text-warn sm:max-w-none',
}

export function MessageBubble({ role, children, className }: MessageBubbleProps) {
  return (
    <div className={cn('flex', role === 'user' ? 'justify-end' : 'justify-start')}>
      <div className={cn(bubbleStyles[role], className)}>{children}</div>
    </div>
  )
}

interface ChatThreadProps {
  children: ReactNode
  scrollKey?: unknown
  isEmpty?: boolean
  empty?: ReactNode
  className?: string
}

export function ChatThread({ children, scrollKey, isEmpty, empty, className }: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [scrollKey])

  if (isEmpty && empty) {
    return <div className={cn('flex flex-1 flex-col items-center justify-center', className)}>{empty}</div>
  }

  return (
    <div className={cn('flex-1 space-y-5 overflow-y-auto py-4', className)}>
      {children}
      <div ref={bottomRef} />
    </div>
  )
}

interface ChatComposerProps {
  value: string
  onChange: (v: string) => void
  onSend: () => void
  placeholder?: string
  leftToolbar?: ReactNode
  sending?: boolean
  autoFocus?: boolean
}

export function ChatComposer({
  value,
  onChange,
  onSend,
  placeholder,
  leftToolbar,
  sending = false,
  autoFocus = false,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const canSend = value.trim().length > 0

  // Auto-grow the textarea up to the cap.
  useLayoutEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`
  }, [value])

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus()
  }, [autoFocus])

  function send() {
    if (!canSend || sending) return
    onSend()
    // Re-focus after the controlled value is cleared by the caller.
    textareaRef.current?.focus()
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      send()
    }
  }

  return (
    <div className="relative rounded-card border border-hairline bg-surface shadow-sm transition-colors focus-within:border-hairline-strong">
      <textarea
        ref={textareaRef}
        value={value}
        rows={1}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="w-full resize-none overflow-y-auto bg-transparent px-4 pt-3 text-body text-fg outline-none placeholder:text-fg-tertiary"
        style={{ maxHeight: '140px' }}
      />
      <div
        className={cn(
          'flex items-center gap-2 px-3 pb-2 pt-1',
          leftToolbar ? 'justify-between' : 'justify-end',
        )}
      >
        {leftToolbar}
        <button
          type="button"
          aria-label="Send"
          onClick={send}
          disabled={!canSend || sending}
          className={cn(
            'rounded-control p-1.5 transition-[color,transform,background-color] duration-150',
            canSend
              ? 'bg-accent text-white hover:bg-accent-hover active:scale-[0.97]'
              : 'cursor-default bg-surface-inset text-fg-tertiary',
          )}
        >
          <ArrowUp size={16} />
        </button>
      </div>
    </div>
  )
}

interface ChipProps {
  children: ReactNode
  onClick?: () => void
  className?: string
}

const chipClass =
  'rounded-full border border-hairline bg-surface px-3 py-1 text-label text-fg-secondary transition-colors hover:border-hairline-strong hover:text-fg'

export function Chip({ children, onClick, className }: ChipProps) {
  if (onClick) {
    return (
      <button type="button" onClick={onClick} className={cn(chipClass, className)}>
        {children}
      </button>
    )
  }
  return <span className={cn(chipClass, className)}>{children}</span>
}

export interface QuickReply {
  id?: string
  label: string
}

interface QuickReplyChipsProps {
  replies: QuickReply[]
  onSelect: (label: string) => void
  className?: string
}

export function QuickReplyChips({ replies, onSelect, className }: QuickReplyChipsProps) {
  if (replies.length === 0) return null
  return (
    <div className={cn('mt-3 flex flex-wrap gap-2', className)}>
      {replies.map((reply) => (
        <Chip key={reply.id ?? reply.label} onClick={() => onSelect(reply.label)}>
          {reply.label}
        </Chip>
      ))}
    </div>
  )
}

interface TypingIndicatorProps {
  className?: string
}

export function TypingIndicator({ className }: TypingIndicatorProps) {
  return (
    <div className={cn('flex h-5 items-center space-x-1.5', className)}>
      <div className="h-2 w-2 animate-bounce rounded-full bg-fg-tertiary" style={{ animationDelay: '0ms' }} />
      <div className="h-2 w-2 animate-bounce rounded-full bg-fg-tertiary" style={{ animationDelay: '150ms' }} />
      <div className="h-2 w-2 animate-bounce rounded-full bg-fg-tertiary" style={{ animationDelay: '300ms' }} />
    </div>
  )
}
