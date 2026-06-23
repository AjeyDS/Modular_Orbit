import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon: ReactNode
  title: string
  body?: string
  action?: ReactNode
}

export function EmptyState({ icon, title, body, action }: EmptyStateProps) {
  return (
    <div className="rounded-card border border-dashed border-hairline bg-surface-inset/40 px-6 py-10 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-control bg-surface text-fg-tertiary">
        {icon}
      </div>
      <div className="text-label font-medium text-fg">{title}</div>
      {body && <p className="mt-1 text-caption leading-5 text-fg-secondary">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
