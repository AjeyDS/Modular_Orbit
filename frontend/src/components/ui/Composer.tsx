import { useLayoutEffect, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'

interface ComposerProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  placeholder?: string
  leading?: ReactNode
  trailing?: ReactNode
  submitLabel?: string
  submitIcon?: ReactNode
  bare?: boolean
  multiline?: boolean
  submitDisabled?: boolean
  submitShortcut?: 'enter' | 'mod-enter'
}

const MAX_TEXTAREA_HEIGHT = 140

export function Composer({
  value,
  onChange,
  onSubmit,
  placeholder,
  leading,
  trailing,
  submitLabel = 'Add',
  submitIcon,
  bare = false,
  multiline = false,
  submitDisabled = false,
  submitShortcut = 'enter',
}: ComposerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const disabled = submitDisabled || !value.trim()

  // Auto-grow the textarea up to the cap.
  useLayoutEffect(() => {
    if (!multiline) return
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`
  }, [value, multiline])

  function focusInput() {
    if (multiline) textareaRef.current?.focus()
    else inputRef.current?.focus()
  }

  function submit() {
    if (disabled) return
    onSubmit()
    // Re-focus after the controlled value is cleared by the caller.
    focusInput()
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    submit()
  }

  function handleTextareaKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (submitShortcut === 'mod-enter') {
      // Plain Enter (and Shift+Enter) inserts a newline; Cmd/Ctrl+Enter submits.
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        submit()
      }
      return
    }
    // Default: Enter submits, Shift+Enter inserts a newline.
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className={
        bare
          ? 'flex items-center gap-2 py-1.5'
          : 'flex flex-wrap items-center gap-2 rounded-card border border-hairline bg-surface-inset px-3 py-2 transition-colors focus-within:border-hairline-strong'
      }
    >
      {submitIcon && (
        <button
          type="submit"
          aria-label="Add"
          disabled={disabled}
          className="shrink-0 rounded-md p-1 text-fg-tertiary transition-colors hover:text-accent disabled:opacity-40"
        >
          {submitIcon}
        </button>
      )}
      {leading}
      {multiline ? (
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleTextareaKeyDown}
          placeholder={placeholder}
          rows={1}
          className="min-w-0 flex-1 resize-none bg-transparent text-body text-fg outline-none placeholder:text-fg-tertiary"
        />
      ) : (
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent text-body text-fg outline-none placeholder:text-fg-tertiary"
        />
      )}
      {trailing}
      {!submitIcon && (
        <button
          type="submit"
          disabled={disabled}
          className="rounded-control bg-accent px-3 py-1.5 text-label font-medium text-white transition-[background-color,transform] duration-150 hover:bg-accent-hover active:scale-[0.97] disabled:opacity-40"
        >
          {submitLabel}
        </button>
      )}
    </form>
  )
}
