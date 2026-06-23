import { useLayoutEffect, useRef, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'

interface ComposerProps {
  value: string
  onChange: (v: string) => void
  onSubmit: () => void
  placeholder?: string
  leading?: ReactNode
  trailing?: ReactNode
  submitLabel?: string
  multiline?: boolean
  submitDisabled?: boolean
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
  multiline = false,
  submitDisabled = false,
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
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-wrap items-center gap-2 rounded-card border border-hairline bg-surface-inset px-3 py-2 transition-colors focus-within:border-hairline-strong"
    >
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
      <button
        type="submit"
        disabled={disabled}
        className="rounded-control bg-accent px-3 py-1.5 text-label font-medium text-white transition-[background-color,transform] duration-150 hover:bg-accent-hover active:scale-[0.97] disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </form>
  )
}
