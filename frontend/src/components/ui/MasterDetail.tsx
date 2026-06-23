import type { ReactNode } from 'react'
import { cn } from './cn'

interface MasterDetailProps {
  nav: ReactNode
  detail: ReactNode
  navWidthClass?: string
  className?: string
}

export function MasterDetail({ nav, detail, navWidthClass, className }: MasterDetailProps) {
  return (
    <div className={cn('grid gap-4', navWidthClass ?? 'lg:grid-cols-[15rem_minmax(0,1fr)]', className)}>
      <aside className="h-fit rounded-card bg-surface-inset p-1.5">{nav}</aside>
      <div className="min-w-0">{detail}</div>
    </div>
  )
}

interface NavItemProps {
  active?: boolean
  icon?: ReactNode
  label: string
  sublabel?: string
  trailing?: ReactNode
  onClick?: () => void
}

export function NavItem({ active = false, icon, label, sublabel, trailing, onClick }: NavItemProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'true' : undefined}
      className={cn(
        'mb-1 flex w-full items-center justify-between gap-2 rounded-control px-3 py-2 text-left transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40',
        active ? 'bg-surface text-fg shadow-sm' : 'text-fg-secondary hover:bg-surface hover:text-fg',
      )}
    >
      <span className="flex min-w-0 items-center gap-2">
        {icon}
        <span className="min-w-0">
          <span className="block truncate text-label font-medium">{label}</span>
          {sublabel && <span className="block truncate text-caption text-fg-tertiary">{sublabel}</span>}
        </span>
      </span>
      {trailing && <span className="shrink-0">{trailing}</span>}
    </button>
  )
}
