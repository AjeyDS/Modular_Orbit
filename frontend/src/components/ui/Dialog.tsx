import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { X } from 'lucide-react'

const EASE_ORBIT_OUT = [0.23, 1, 0.32, 1] as const

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export interface DialogProps {
  open: boolean
  /** Called when the dialog should actually close (after discard-confirm if dirty). */
  onClose: () => void
  title: string
  /** Shown next to the title, e.g. a breadcrumb or SegmentedControl. */
  headerExtra?: ReactNode
  /** Scrollable body content. */
  children: ReactNode
  /** Action row pinned at the bottom. */
  footer?: ReactNode
  /** When true, a close attempt opens the built-in discard-confirm bar instead of closing. */
  dirty?: boolean
  /** Message shown in the discard-confirm bar. */
  discardLabel?: string
  /** Tailwind max-width utility for the panel. */
  maxWidthClass?: string
}

export function Dialog({
  open,
  onClose,
  title,
  headerExtra,
  children,
  footer,
  dirty = false,
  discardLabel = 'Discard changes?',
  maxWidthClass = 'max-w-2xl',
}: DialogProps) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement | null>(null)
  const previouslyFocused = useRef<HTMLElement | null>(null)
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)

  // A close attempt: if dirty, surface the discard-confirm bar; otherwise close.
  const requestClose = useCallback(() => {
    if (dirty) {
      setConfirmingDiscard(true)
      return
    }
    onClose()
  }, [dirty, onClose])

  // Reset the confirm bar whenever the dialog (re)opens.
  useEffect(() => {
    if (open) setConfirmingDiscard(false)
  }, [open])

  // Body scroll lock + remember/restore focus, while open.
  useEffect(() => {
    if (!open) return
    previouslyFocused.current = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = previousOverflow
      // Best-effort: restore focus to whatever was focused before opening.
      previouslyFocused.current?.focus?.()
    }
  }, [open])

  // Focus the panel (or its first focusable element) on open.
  useEffect(() => {
    if (!open) return
    const raf = requestAnimationFrame(() => {
      const panel = panelRef.current
      if (!panel) return
      const first = panel.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
      ;(first ?? panel).focus()
    })
    return () => cancelAnimationFrame(raf)
  }, [open])

  // Escape closes; Tab/Shift+Tab is trapped within the panel.
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        requestClose()
        return
      }
      if (event.key !== 'Tab') return

      const panel = panelRef.current
      if (!panel) return
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      )
      if (focusable.length === 0) {
        event.preventDefault()
        panel.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (event.shiftKey) {
        if (active === first || active === panel) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last) {
        event.preventDefault()
        first.focus()
      }
    },
    [requestClose],
  )

  if (typeof document === 'undefined') return null

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="dialog"
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16, ease: EASE_ORBIT_OUT }}
        >
          <motion.div
            className="glass absolute inset-0 bg-black/30 backdrop-blur-sm"
            onClick={requestClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: EASE_ORBIT_OUT }}
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            onKeyDown={handleKeyDown}
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.18, ease: EASE_ORBIT_OUT }}
            className={`relative flex max-h-[85vh] w-full ${maxWidthClass} flex-col overflow-hidden rounded-modal border border-hairline bg-surface shadow-[0_24px_64px_-24px_rgba(0,0,0,0.28)] outline-none`}
          >
            <header className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3">
              <div className="flex min-w-0 items-center gap-3">
                <h2 id={titleId} className="text-heading font-medium text-fg">
                  {title}
                </h2>
                {headerExtra}
              </div>
              <button
                type="button"
                onClick={requestClose}
                aria-label="Close"
                className="rounded-md p-1 text-fg-tertiary transition-colors hover:text-fg"
              >
                <X size={16} />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>

            {footer && <div className="border-t border-hairline px-5 py-3">{footer}</div>}

            <AnimatePresence>
              {confirmingDiscard && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 8 }}
                  transition={{ duration: 0.16, ease: EASE_ORBIT_OUT }}
                  className="glass absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 border-t border-hairline px-5 py-3"
                >
                  <span className="text-label text-fg-secondary">{discardLabel}</span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirmingDiscard(false)}
                      className="rounded-control px-3 py-1.5 text-caption text-fg-secondary transition-colors hover:bg-surface-inset hover:text-fg"
                    >
                      Keep editing
                    </button>
                    <button
                      type="button"
                      onClick={onClose}
                      className="rounded-control bg-danger px-3 py-1.5 text-caption font-medium text-white transition-colors hover:bg-danger/90"
                    >
                      Discard
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}
