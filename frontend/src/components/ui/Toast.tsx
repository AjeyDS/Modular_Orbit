import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { GlassPanel } from './Surface'

type ToastTone = 'neutral' | 'success' | 'warn' | 'danger' | 'accent'

interface ToastItem {
  id: number
  message: string
  tone: ToastTone
  /** When present, renders an Undo affordance. */
  onUndo?: () => void
}

interface SimpleToastInput {
  message: string
  tone?: ToastTone
  durationMs?: number
}

interface UndoToastInput {
  message: string
  onUndo: () => void
  onCommit: () => void
  durationMs?: number
}

interface ToastContextValue {
  toast: (input: SimpleToastInput) => void
  undoToast: (input: UndoToastInput) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const EASE_ORBIT_OUT = [0.23, 1, 0.32, 1] as const

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const nextId = useRef(0)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())

  const clearTimer = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timers.current.delete(id)
    }
  }, [])

  const dismiss = useCallback(
    (id: number) => {
      clearTimer(id)
      setToasts((prev) => prev.filter((item) => item.id !== id))
    },
    [clearTimer],
  )

  const toast = useCallback(
    ({ message, tone = 'neutral', durationMs = 4000 }: SimpleToastInput) => {
      const id = nextId.current++
      setToasts((prev) => [...prev, { id, message, tone }])
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), durationMs),
      )
    },
    [dismiss],
  )

  const undoToast = useCallback(
    ({ message, onUndo, onCommit, durationMs = 5000 }: UndoToastInput) => {
      const id = nextId.current++
      // Guard so exactly one of onUndo / onCommit ever fires.
      let settled = false

      const handleUndo = () => {
        if (settled) return
        settled = true
        onUndo()
        dismiss(id)
      }

      const commit = () => {
        if (settled) return
        settled = true
        onCommit()
        dismiss(id)
      }

      setToasts((prev) => [...prev, { id, message, tone: 'neutral', onUndo: handleUndo }])
      timers.current.set(id, setTimeout(commit, durationMs))
    },
    [dismiss],
  )

  // Flush any pending commit timers on unmount.
  useEffect(() => {
    const map = timers.current
    return () => {
      map.forEach((timer) => clearTimeout(timer))
      map.clear()
    }
  }, [])

  const value = useMemo<ToastContextValue>(() => ({ toast, undoToast }), [toast, undoToast])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-6 left-1/2 z-[100] flex -translate-x-1/2 flex-col items-center gap-2">
        <AnimatePresence>
          {toasts.map((item) => (
            <motion.div
              key={item.id}
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              transition={{ duration: 0.2, ease: EASE_ORBIT_OUT }}
            >
              <GlassPanel elevated className="flex items-center gap-3 px-4 py-2.5 text-label text-fg">
                <span>{item.message}</span>
                {item.onUndo && (
                  <button
                    type="button"
                    onClick={item.onUndo}
                    className="font-medium text-accent hover:text-accent-hover"
                  >
                    Undo
                  </button>
                )}
              </GlassPanel>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider')
  }
  return context
}
