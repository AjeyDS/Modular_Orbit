import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from './cn'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  inset?: boolean
  className?: string
  children?: ReactNode
}

export function Card({ inset = false, className, children, ...rest }: CardProps) {
  return (
    <div
      className={cn('rounded-card border border-hairline', inset ? 'bg-surface-inset' : 'bg-surface', className)}
      {...rest}
    >
      {children}
    </div>
  )
}

interface GlassPanelProps extends HTMLAttributes<HTMLDivElement> {
  elevated?: boolean
  className?: string
  children?: ReactNode
}

export function GlassPanel({ elevated = false, className, children, ...rest }: GlassPanelProps) {
  return (
    <div
      className={cn(
        'glass rounded-card border border-hairline',
        elevated && 'shadow-[0_24px_64px_-24px_rgba(0,0,0,0.28)]',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  )
}
