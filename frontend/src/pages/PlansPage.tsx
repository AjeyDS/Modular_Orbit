import { useEffect, useMemo, useState } from 'react'
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Plus,
  Trash2,
  X,
} from 'lucide-react'
import {
  addPlanStep,
  archivePlan,
  completePlan,
  completePlanStep,
  deletePlan,
  fetchPlans,
  type LifecycleStatus,
  type PlanItem,
  type PlanStepItem,
} from '../lib/api'
import { AsyncStatusPills } from '../components/status'
import { pageContentClass } from '../layout/pageShell'
import { ImportPlanDialog } from '../components/plans/ImportPlanDialog'

type PlanFilter = Extract<LifecycleStatus, 'active' | 'completed' | 'archived'>

export default function PlansPage() {
  const [plans, setPlans] = useState<PlanItem[]>([])
  const [filter, setFilter] = useState<PlanFilter>('active')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)

  async function load(nextFilter = filter) {
    setLoading(true)
    setError('')
    try {
      setPlans(await fetchPlans(nextFilter))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load plans')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load(filter)
  }, [filter])

  const sortedPlans = useMemo(
    () => [...plans].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    [plans],
  )

  const totalSteps = useMemo(
    () => plans.reduce((sum, plan) => sum + plan.total_steps, 0),
    [plans],
  )
  const activeCount = useMemo(
    () => plans.filter((plan) => plan.lifecycle_status === 'active').length,
    [plans],
  )

  async function handleImported(message: string) {
    setStatus(message)
    setError('')
    if (filter !== 'active') {
      setFilter('active')
    } else {
      await load('active')
    }
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Plans</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{plans.length}</span> {plans.length === 1 ? 'plan' : 'plans'}
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{activeCount}</span> active
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{totalSteps}</span> steps
            </p>
          </div>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-3.5 py-2 text-[13px] font-semibold text-white shadow-[0_1px_0_rgba(0,0,0,0.04)] transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97]"
          >
            <Plus size={15} />
            New plan
          </button>
        </header>

        {error && (
          <StatusBanner tone="error" message={error} onDismiss={() => setError('')} />
        )}
        {status && !error && (
          <StatusBanner tone="success" message={status} onDismiss={() => setStatus('')} />
        )}

        <section
          className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
          style={{ borderWidth: '0.5px' }}
        >
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <FilterTabs value={filter} onChange={setFilter} />
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              Saved plans keep their nested structure and lifecycle statuses.
            </p>
          </div>

          {loading && plans.length === 0 ? (
            <div className="py-12 text-center text-[14px] text-gray-500">Loading plans…</div>
          ) : sortedPlans.length === 0 ? (
            <EmptyPlansState filter={filter} onCreate={() => setDialogOpen(true)} />
          ) : (
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(22rem,1fr))]">
              {sortedPlans.map((plan) => (
                <PlanCard key={plan.id} plan={plan} onChanged={() => void load()} />
              ))}
            </div>
          )}
        </section>
      </div>

      <ImportPlanDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onImported={(message) => void handleImported(message)}
      />
    </div>
  )
}

function EmptyPlansState({ filter, onCreate }: { filter: PlanFilter; onCreate: () => void }) {
  if (filter !== 'active') {
    return (
      <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 py-12 text-center text-[14px] text-gray-500 dark:border-gray-700 dark:bg-[#18181A] dark:text-gray-500">
        No {filter} plans yet.
      </div>
    )
  }
  return (
    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 py-12 text-center dark:border-gray-700 dark:bg-[#18181A]">
      <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-white text-gray-400 dark:bg-gray-800 dark:text-gray-500">
        <FileText size={18} />
      </div>
      <h3 className="text-[16px] font-semibold tracking-[-0.02em] text-gray-800 dark:text-gray-200">No plans yet</h3>
      <p className="mx-auto mt-2 max-w-sm text-[13px] leading-6 text-gray-500 dark:text-gray-500">
        Paste a plan from ChatGPT, Claude, Gemini, or notes. Orbit extracts the hierarchy and saves every node into the modular lifecycle.
      </p>
      <button
        type="button"
        onClick={onCreate}
        className="mt-5 inline-flex items-center gap-2 rounded-xl bg-blue-500 px-3.5 py-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97]"
      >
        <Plus size={15} />
        Import your first plan
      </button>
    </div>
  )
}

function StatusBanner({ tone, message, onDismiss }: { tone: 'error' | 'success'; message: string; onDismiss: () => void }) {
  const classes = tone === 'error'
    ? 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200'
    : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200'
  return (
    <div className={`mb-4 flex items-center justify-between gap-3 rounded-2xl border px-4 py-3 text-[13px] ${classes}`}>
      <span>{message}</span>
      <button type="button" onClick={onDismiss} className="opacity-70 transition-opacity hover:opacity-100">
        <X size={14} />
      </button>
    </div>
  )
}

function PlanCard({ plan, onChanged }: { plan: PlanItem; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [newStep, setNewStep] = useState('')
  const status: 'complete' | 'in progress' | 'not started' =
    plan.total_steps > 0 && plan.completed_steps === plan.total_steps
      ? 'complete'
      : plan.completed_steps > 0
        ? 'in progress'
        : 'not started'
  const accentColor = status === 'complete' ? '#1D9E75' : status === 'in progress' ? '#4A9EFF' : '#6B7280'
  const squareBg = status === 'complete' ? '#d1f5e8' : status === 'in progress' ? '#dceefa' : '#F3F4F6'

  async function submitStep() {
    const title = newStep.trim()
    if (!title) return
    await addPlanStep(plan.id, { title })
    setNewStep('')
    onChanged()
  }

  return (
    <article className="overflow-hidden rounded-2xl border border-gray-200 bg-white transition-colors hover:border-gray-300 dark:border-gray-800 dark:bg-[#18181A] dark:hover:border-gray-700">
      <button type="button" onClick={() => setExpanded((value) => !value)} className="flex w-full items-center gap-3 px-4 pb-2 pt-3 text-left">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl" style={{ backgroundColor: squareBg }}>
          {status === 'complete' ? (
            <CheckCircle2 size={17} style={{ color: accentColor }} />
          ) : (
            <span className="text-[12px] font-semibold leading-none tabular-nums" style={{ color: accentColor }}>
              {plan.completed_steps > 0 ? `${plan.completed_steps}/${plan.total_steps}` : String(plan.total_steps)}
            </span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-semibold leading-snug text-gray-800 dark:text-gray-200">
            {plan.title}
          </span>
          <span className="mt-0.5 block text-[12px] text-gray-500 dark:text-gray-500">
            {plan.total_steps} step{plan.total_steps !== 1 ? 's' : ''} · {status}
          </span>
        </div>
        <ChevronRight size={14} className={`shrink-0 text-gray-400 transition-transform duration-150 ease-out ${expanded ? 'rotate-90' : ''}`} />
      </button>

      <div className="mx-4 mb-3 h-[4px] overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
        <div className="h-full rounded-full transition-[width] duration-200 ease-out" style={{ width: `${plan.progress_percent}%`, backgroundColor: accentColor }} />
      </div>

      {expanded && (
        <div className="border-t border-gray-100 px-4 py-3 dark:border-gray-800">
          {plan.description && <p className="mb-3 text-[13px] leading-6 text-gray-500 dark:text-gray-400">{plan.description}</p>}
          <PlanStepTree planId={plan.id} steps={plan.steps} onChanged={onChanged} />

          {plan.lifecycle_status === 'active' && (
            <div className="mt-3 flex gap-2">
              <input
                value={newStep}
                onChange={(event) => setNewStep(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void submitStep()
                }}
                placeholder="Add a step"
                className="min-w-0 flex-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-[13px] outline-none focus:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:focus:border-gray-600"
              />
              <button type="button" onClick={() => void submitStep()} className="rounded-xl bg-blue-500 px-3 py-2 text-[12px] font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97]">
                Add
              </button>
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <AsyncStatusPills connection={plan.connection_status} chunk={plan.chunk_status} bucketUpdate={plan.bucket_update_status} />
            <div className="flex items-center gap-2">
              {plan.lifecycle_status === 'active' && (
                <IconAction label="Complete plan" onClick={async () => { await completePlan(plan.id); onChanged() }}>
                  <CheckCircle2 size={14} />
                </IconAction>
              )}
              <IconAction label="Archive plan" onClick={async () => { await archivePlan(plan.id); onChanged() }}>
                <Archive size={14} />
              </IconAction>
              <IconAction label="Delete plan" danger onClick={async () => { await deletePlan(plan.id); onChanged() }}>
                <Trash2 size={14} />
              </IconAction>
            </div>
          </div>
        </div>
      )}
    </article>
  )
}

function IconAction({ label, danger = false, children, onClick }: { label: string; danger?: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={`rounded-lg p-1.5 transition-[background-color,color,transform] duration-150 ease-out active:scale-[0.94] ${
        danger ? 'text-gray-300 hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30' : 'text-gray-300 hover:bg-emerald-50 hover:text-[#1D9E75] dark:hover:bg-emerald-950/30'
      }`}
    >
      {children}
    </button>
  )
}

function PlanStepTree({ planId, steps, onChanged }: { planId: string; steps: PlanStepItem[]; onChanged: () => void }) {
  return (
    <div className="space-y-1">
      {steps.map((step) => (
        <PlanStepNode key={step.id} planId={planId} step={step} onChanged={onChanged} depth={0} />
      ))}
    </div>
  )
}

function PlanStepNode({ planId, step, onChanged, depth }: { planId: string; step: PlanStepItem; onChanged: () => void; depth: number }) {
  const [collapsed, setCollapsed] = useState(false)
  const children = step.children || []
  const isLeaf = children.length === 0
  const progress = branchProgress(step)

  return (
    <div className={depth > 0 ? 'ml-4 border-l border-gray-200 pl-3 dark:border-gray-800' : ''}>
      <div className="group flex items-start gap-2 rounded-xl px-2 py-2 transition-colors hover:bg-gray-50/60 dark:hover:bg-gray-800/40">
        {!isLeaf ? (
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="mt-0.5 rounded-md text-gray-400 transition-colors hover:text-gray-700 dark:hover:text-gray-200"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
        ) : (
          <button
            type="button"
            disabled={step.status === 'completed'}
            onClick={async () => {
              await completePlanStep(planId, step.id)
              onChanged()
            }}
            className="mt-0.5 rounded-full transition-transform active:scale-[0.9] disabled:cursor-default"
          >
            {step.status === 'completed' ? (
              <CheckCircle2 size={15} className="text-[#1D9E75]" />
            ) : (
              <span className="block h-[15px] w-[15px] rounded-full border border-gray-300 bg-white dark:border-gray-600 dark:bg-[#1C1C1E]" />
            )}
          </button>
        )}
        <div className="min-w-0 flex-1">
          <div className={`text-[13px] ${step.status === 'completed' ? 'text-gray-400 line-through' : isLeaf ? 'text-gray-700 dark:text-gray-300' : 'font-semibold text-gray-800 dark:text-gray-200'}`}>
            {step.title}
          </div>
          {step.description && <div className="mt-0.5 text-[12px] leading-5 text-gray-500 dark:text-gray-500">{step.description}</div>}
        </div>
        {!isLeaf && (
          <span className="mt-0.5 rounded-full bg-gray-100 px-2 py-0.5 text-[11px] tabular-nums text-gray-500 dark:bg-gray-800 dark:text-gray-400">
            {progress.completed}/{progress.total}
          </span>
        )}
      </div>
      {!collapsed && children.length > 0 && (
        <div className="mt-1 space-y-1">
          {children.map((child) => (
            <PlanStepNode key={child.id} planId={planId} step={child} onChanged={onChanged} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function FilterTabs({ value, onChange }: { value: PlanFilter; onChange: (value: PlanFilter) => void }) {
  return (
    <div className="flex items-center rounded-lg bg-gray-100 p-0.5 dark:bg-gray-800">
      {(['active', 'completed', 'archived'] as const).map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onChange(item)}
          className={
            value === item
              ? 'rounded-md bg-white px-3 py-1 text-[12px] font-medium capitalize text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
              : 'rounded-md px-3 py-1 text-[12px] capitalize text-gray-400 transition-colors hover:text-gray-600 dark:hover:text-gray-300'
          }
        >
          {item}
        </button>
      ))}
    </div>
  )
}

function branchProgress(step: PlanStepItem): { completed: number; total: number } {
  const children = step.children || []
  if (children.length === 0) {
    return { completed: step.status === 'completed' ? 1 : 0, total: 1 }
  }
  return children.reduce(
    (acc, child) => {
      const childProgress = branchProgress(child)
      return {
        completed: acc.completed + childProgress.completed,
        total: acc.total + childProgress.total,
      }
    },
    { completed: 0, total: 0 },
  )
}
