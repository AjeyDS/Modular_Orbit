import type { AsyncStepStatus, LifecycleStatus } from '../lib/api'

export function LifecyclePill({ status }: { status: LifecycleStatus | string }) {
  const styles: Record<string, string> = {
    active: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200',
    completed: 'bg-blue-100 text-blue-800 dark:bg-blue-950/50 dark:text-blue-200',
    archived: 'bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-300',
    deleted: 'bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-200',
  }
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${styles[status] ?? styles.archived}`}>
      {status}
    </span>
  )
}

export function AsyncStatusPills({
  connection,
  chunk,
  bucketUpdate,
}: {
  connection: AsyncStepStatus
  chunk: AsyncStepStatus
  bucketUpdate: AsyncStepStatus
}) {
  const statuses = [
    ['connection', connection],
    ['chunks', chunk],
    ['bucket', bucketUpdate],
  ].filter(([, value]) => value !== 'complete' && value !== 'not_needed')

  if (statuses.length === 0) return null

  return (
    <>
      {statuses.map(([label, value]) => (
        <span
          key={label}
          className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800 dark:bg-amber-950/50 dark:text-amber-200"
        >
          {label} {value}
        </span>
      ))}
    </>
  )
}
