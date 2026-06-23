import type { AsyncStepStatus, LifecycleStatus } from '../lib/api'
import { Pill, type PillTone } from './ui/Pill'

const lifecycleTones: Record<string, PillTone> = {
  active: 'success',
  completed: 'success',
  archived: 'neutral',
  deleted: 'neutral',
}

const lifecycleLabels: Record<string, string> = {
  active: 'Active',
  completed: 'Completed',
  archived: 'Archived',
  deleted: 'Deleted',
}

export function LifecyclePill({ status }: { status: LifecycleStatus | string }) {
  const tone = lifecycleTones[status] ?? 'neutral'
  const label = lifecycleLabels[status] ?? humanizeStage(status)
  return <Pill tone={tone}>{label}</Pill>
}

const stepTones: Record<AsyncStepStatus, PillTone> = {
  pending: 'warn',
  complete: 'success',
  failed: 'danger',
  not_needed: 'neutral',
}

const stepLabels: Partial<Record<string, string>> = {
  connection: 'Connection',
  chunks: 'Chunks',
  bucket: 'Memory',
  pending: 'pending',
  complete: 'complete',
  failed: 'failed',
  not_needed: 'skipped',
  running: 'running',
}

/**
 * The single place raw backend stage identifiers are converted to friendly
 * labels. Accepts either a single token (e.g. `chunk`, `pending`) or a
 * space-joined pair (e.g. `connection running`, `chunk pending`). No raw
 * identifier should ever reach the UI without passing through here.
 */
export function humanizeStage(stage: string): string {
  return stage
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => stepLabels[token] ?? token.charAt(0).toUpperCase() + token.slice(1).replace(/_/g, ' '))
    .join(' ')
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
  const statuses: [string, AsyncStepStatus][] = [
    ['connection', connection],
    ['chunks', chunk],
    ['bucket', bucketUpdate],
  ]

  const visible = statuses.filter(([, value]) => value !== 'complete' && value !== 'not_needed')

  if (visible.length === 0) return null

  return (
    <>
      {visible.map(([stage, value]) => (
        <Pill key={stage} tone={stepTones[value] ?? 'neutral'}>
          {humanizeStage(`${stage} ${value}`)}
        </Pill>
      ))}
    </>
  )
}
