import type { ReactNode } from 'react'
import { cn } from './cn'

export type PillTone = 'neutral' | 'success' | 'warn' | 'danger' | 'accent'

const toneStyles: Record<PillTone, string> = {
  neutral: 'bg-surface-inset text-fg-secondary',
  success: 'bg-success/10 text-success',
  warn: 'bg-warn/10 text-warn',
  danger: 'bg-danger/10 text-danger',
  accent: 'bg-accent/10 text-accent',
}

interface PillProps {
  tone?: PillTone
  className?: string
  children?: ReactNode
}

export function Pill({ tone = 'neutral', className, children }: PillProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-caption font-semibold',
        toneStyles[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
