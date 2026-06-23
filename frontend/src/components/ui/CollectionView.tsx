import { useEffect, useState } from 'react'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { cn } from './cn'
import { SkeletonRows } from './Skeleton'

const ROW_EASE = [0.23, 1, 0.32, 1] as const

interface CollectionViewProps {
  composer?: ReactNode
  loading?: boolean
  isEmpty?: boolean
  empty?: ReactNode
  skeleton?: ReactNode
  children?: ReactNode
  className?: string
}

export function CollectionView({
  composer,
  loading = false,
  isEmpty = false,
  empty,
  skeleton,
  children,
  className,
}: CollectionViewProps) {
  return (
    <div className={className}>
      {composer}
      {loading ? (
        <div className="mt-3">{skeleton ?? <SkeletonRows count={3} />}</div>
      ) : isEmpty ? (
        empty
      ) : (
        <div className="mt-3 space-y-1">
          <AnimatePresence initial={false}>{children}</AnimatePresence>
        </div>
      )}
    </div>
  )
}

// motion.article's prop typing fights with framer-motion's own event-handler
// overrides (onDrag, onAnimationStart, etc.), so we base the props on
// ComponentPropsWithoutRef<typeof motion.article> rather than plain article
// attributes. This keeps `layout` and the standard div/article attributes
// spreadable without TS friction.
type CollectionRowProps = ComponentPropsWithoutRef<typeof motion.article> & {
  accent?: boolean
  className?: string
  children: ReactNode
}

export function CollectionRow({ accent = false, className, children, ...rest }: CollectionRowProps) {
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.18, ease: ROW_EASE }}
      className={cn(
        'group rounded-control border bg-surface transition-colors',
        accent ? 'border-accent/40 ai-wash' : 'border-hairline hover:border-hairline-strong',
        className,
      )}
      {...rest}
    >
      {children}
    </motion.article>
  )
}

interface EditableTitleProps {
  value: string
  onSave: (next: string) => void
  className?: string
  placeholder?: string
}

export function EditableTitle({ value, onSave, className, placeholder }: EditableTitleProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  // Keep draft synced with external value changes while not actively editing.
  useEffect(() => {
    if (!editing) setDraft(value)
  }, [value, editing])

  const commit = () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== value) onSave(trimmed)
    setEditing(false)
  }

  const cancel = () => {
    setDraft(value)
    setEditing(false)
  }

  if (!editing) {
    return (
      <button
        type="button"
        className={cn('cursor-text text-left', className)}
        onClick={() => {
          setDraft(value)
          setEditing(true)
        }}
      >
        {value || placeholder}
      </button>
    )
  }

  return (
    <input
      autoFocus
      value={draft}
      placeholder={placeholder}
      className={cn('bg-transparent outline-none', className)}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault()
          commit()
        } else if (event.key === 'Escape') {
          event.preventDefault()
          cancel()
        }
      }}
    />
  )
}

interface RowActionsProps {
  children: ReactNode
  className?: string
}

export function RowActions({ children, className }: RowActionsProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-1 transition-opacity duration-150',
        'opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100',
        className,
      )}
    >
      {children}
    </div>
  )
}
