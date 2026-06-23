import { useEffect, useMemo, useState } from 'react'
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Plus,
  Trash2,
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
import {
  CollectionRow,
  CollectionView,
  EmptyState,
  FilterTabs,
  Pill,
  RowActions,
  useToast,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'
import { ImportPlanDialog } from '../components/plans/ImportPlanDialog'

type PlanFilter = Extract<LifecycleStatus, 'active' | 'completed' | 'archived'>

type PlanStatus = 'complete' | 'in progress' | 'not started'

function planStatus(plan: PlanItem): PlanStatus {
  if (plan.total_steps > 0 && plan.completed_steps === plan.total_steps) return 'complete'
  if (plan.completed_steps > 0) return 'in progress'
  return 'not started'
}

// Recursively mark a step (by id) completed within the nested tree, returning a
// new tree. Used for the optimistic complete-step path so the leaf flips and any
// branch progress counts recompute from the updated children.
function markStepCompleted(steps: PlanStepItem[], stepId: string): PlanStepItem[] {
  return steps.map((step) => {
    if (step.id === stepId) {
      return { ...step, status: 'completed' as const }
    }
    if (step.children && step.children.length > 0) {
      return { ...step, children: markStepCompleted(step.children, stepId) }
    }
    return step
  })
}

export default function PlansPage() {
  const [plans, setPlans] = useState<PlanItem[]>([])
  const [filter, setFilter] = useState<PlanFilter>('active')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const { toast, undoToast } = useToast()

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
    setError('')
    toast({ message, tone: 'success' })
    if (filter !== 'active') {
      setFilter('active')
    } else {
      await load('active')
    }
  }

  // Optimistic complete: flip lifecycle locally (drops the plan from the active
  // filter), persist in the background, reconcile via load() only on error.
  function handleCompletePlan(plan: PlanItem) {
    if (plan.lifecycle_status !== 'active') return
    setPlans((current) =>
      filter === 'active'
        ? current.filter((item) => item.id !== plan.id)
        : current.map((item) =>
            item.id === plan.id ? { ...item, lifecycle_status: 'completed' as const } : item,
          ),
    )
    void completePlan(plan.id).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to complete plan', tone: 'danger' })
      void load()
    })
  }

  // Optimistic archive: drop from the active/completed filters immediately.
  function handleArchivePlan(plan: PlanItem) {
    setPlans((current) =>
      filter === 'archived'
        ? current.map((item) =>
            item.id === plan.id ? { ...item, lifecycle_status: 'archived' as const } : item,
          )
        : current.filter((item) => item.id !== plan.id),
    )
    void archivePlan(plan.id).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to archive plan', tone: 'danger' })
      void load()
    })
  }

  // Optimistic delete + undo: drop immediately, restore at the original index on
  // undo, persist the deletion on commit.
  function handleDeletePlan(plan: PlanItem) {
    const removed = plan
    const index = plans.findIndex((item) => item.id === removed.id)

    setPlans((current) => current.filter((item) => item.id !== removed.id))

    undoToast({
      message: 'Plan deleted',
      onUndo: () => {
        setPlans((current) => {
          const next = [...current]
          next.splice(Math.min(index < 0 ? next.length : index, next.length), 0, removed)
          return next
        })
      },
      onCommit: () => {
        void deletePlan(removed.id).catch((err) => {
          toast({ message: err instanceof Error ? err.message : 'Unable to delete plan', tone: 'danger' })
          void load()
        })
      },
    })
  }

  // Optimistic complete-step: mark the leaf completed in the nested tree and bump
  // the parent plan's completed_steps / progress_percent.
  function handleCompleteStep(planId: string, stepId: string) {
    setPlans((current) =>
      current.map((plan) => {
        if (plan.id !== planId) return plan
        const completedSteps = Math.min(plan.completed_steps + 1, plan.total_steps)
        const progress = plan.total_steps > 0 ? Math.round((completedSteps / plan.total_steps) * 100) : 0
        return {
          ...plan,
          steps: markStepCompleted(plan.steps, stepId),
          completed_steps: completedSteps,
          progress_percent: progress,
        }
      }),
    )
    void completePlanStep(planId, stepId).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to complete step', tone: 'danger' })
      void load()
    })
  }

  // Optimistic add-step: append the new leaf, bump total_steps, recompute the
  // progress denominator. Reconcile to the server item via load() on error.
  function handleAddStep(planId: string, title: string) {
    const tempId = `temp-${Date.now()}`
    const optimisticStep: PlanStepItem = {
      id: tempId,
      parent_step_id: null,
      position: 0,
      title,
      description: '',
      status: 'active',
      completed_at: null,
      children: [],
    }
    setPlans((current) =>
      current.map((plan) => {
        if (plan.id !== planId) return plan
        const totalSteps = plan.total_steps + 1
        const progress = totalSteps > 0 ? Math.round((plan.completed_steps / totalSteps) * 100) : 0
        return {
          ...plan,
          steps: [...plan.steps, optimisticStep],
          total_steps: totalSteps,
          progress_percent: progress,
        }
      }),
    )
    void addPlanStep(planId, { title })
      .then((updated) => {
        setPlans((current) => current.map((plan) => (plan.id === planId ? updated : plan)))
      })
      .catch((err) => {
        toast({ message: err instanceof Error ? err.message : 'Unable to add step', tone: 'danger' })
        void load()
      })
  }

  const emptyCopy =
    filter === 'active'
      ? {
          title: 'No plans yet.',
          body: 'Paste a plan from ChatGPT, Claude, Gemini, or notes. Orbit extracts the hierarchy and saves every node into the modular lifecycle.',
        }
      : { title: `No ${filter} plans yet.`, body: undefined }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Plans</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{plans.length}</span> {plans.length === 1 ? 'plan' : 'plans'}
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{activeCount}</span> active
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{totalSteps}</span> steps
            </p>
          </div>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="inline-flex items-center gap-2 rounded-control bg-accent px-3.5 py-2 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97]"
          >
            <Plus size={15} />
            New plan
          </button>
        </header>

        {error && (
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}

        <div className="mb-4">
          <FilterTabs
            options={['active', 'completed', 'archived']}
            value={filter}
            onChange={(value) => setFilter(value as PlanFilter)}
            ariaLabel="Plan filter"
          />
        </div>

        <CollectionView
          divided
          loading={loading && plans.length === 0}
          isEmpty={sortedPlans.length === 0}
          empty={
            <EmptyState
              icon={<FileText size={18} />}
              title={emptyCopy.title}
              body={emptyCopy.body}
              action={
                filter === 'active' ? (
                  <button
                    type="button"
                    onClick={() => setDialogOpen(true)}
                    className="inline-flex items-center gap-2 rounded-control bg-accent px-3.5 py-2 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97]"
                  >
                    <Plus size={15} />
                    Import your first plan
                  </button>
                ) : undefined
              }
            />
          }
        >
          {sortedPlans.map((plan) => (
            <PlanRow
              key={plan.id}
              plan={plan}
              onComplete={handleCompletePlan}
              onArchive={handleArchivePlan}
              onDelete={handleDeletePlan}
              onCompleteStep={handleCompleteStep}
              onAddStep={handleAddStep}
            />
          ))}
        </CollectionView>
      </div>

      <ImportPlanDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onImported={(message) => void handleImported(message)}
      />
    </div>
  )
}

function PlanRow({
  plan,
  onComplete,
  onArchive,
  onDelete,
  onCompleteStep,
  onAddStep,
}: {
  plan: PlanItem
  onComplete: (plan: PlanItem) => void
  onArchive: (plan: PlanItem) => void
  onDelete: (plan: PlanItem) => void
  onCompleteStep: (planId: string, stepId: string) => void
  onAddStep: (planId: string, title: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [newStep, setNewStep] = useState('')
  const status = planStatus(plan)
  const statusColor =
    status === 'complete' ? 'text-success' : status === 'in progress' ? 'text-accent' : 'text-fg-tertiary'

  function submitStep() {
    const title = newStep.trim()
    if (!title) return
    onAddStep(plan.id, title)
    setNewStep('')
  }

  return (
    <CollectionRow variant="plain">
      <div className="px-1 py-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="flex min-w-0 flex-1 items-center gap-3 text-left"
            aria-label={expanded ? `Collapse ${plan.title}` : `Expand ${plan.title}`}
          >
            <span className="flex h-9 w-9 shrink-0 items-center justify-center">
              {status === 'complete' ? (
                <CheckCircle2 size={20} className="text-success" strokeWidth={1.8} />
              ) : (
                <span className="flex h-9 w-9 items-center justify-center rounded-control bg-surface-inset text-caption font-semibold tabular-nums text-fg-secondary">
                  {plan.completed_steps > 0
                    ? `${plan.completed_steps}/${plan.total_steps}`
                    : String(plan.total_steps)}
                </span>
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body font-medium leading-snug text-fg">{plan.title}</span>
              <span className="mt-0.5 block text-caption text-fg-secondary">
                {plan.total_steps} step{plan.total_steps !== 1 ? 's' : ''} ·{' '}
                <span className={statusColor}>{status}</span>
              </span>
            </span>
            <ChevronRight
              size={14}
              className={`shrink-0 text-fg-tertiary transition-transform duration-150 ease-out ${
                expanded ? 'rotate-90' : ''
              }`}
            />
          </button>
          <RowActions className="self-start pt-0.5">
            {plan.lifecycle_status === 'active' && (
              <button
                type="button"
                onClick={() => onComplete(plan)}
                aria-label={`Complete ${plan.title}`}
                title="Complete plan"
                className="text-fg-tertiary transition-colors hover:text-success"
              >
                <CheckCircle2 size={14} />
              </button>
            )}
            <button
              type="button"
              onClick={() => onArchive(plan)}
              aria-label={`Archive ${plan.title}`}
              title="Archive plan"
              className="text-fg-tertiary transition-colors hover:text-fg"
            >
              <Archive size={14} />
            </button>
            <button
              type="button"
              onClick={() => onDelete(plan)}
              aria-label={`Delete ${plan.title}`}
              title="Delete plan"
              className="text-fg-tertiary transition-colors hover:text-danger"
            >
              <Trash2 size={14} />
            </button>
          </RowActions>
        </div>

        <div className="ml-12 mr-1 mt-2 h-[4px] overflow-hidden rounded-full bg-surface-inset">
          <div
            className={`h-full rounded-full transition-[width] duration-200 ease-out ${
              status === 'complete' ? 'bg-success' : 'bg-accent'
            }`}
            style={{ width: `${plan.progress_percent}%` }}
          />
        </div>

        {expanded && (
          <div className="ml-12 mr-1 mt-3 space-y-3">
            {plan.description && <p className="text-label leading-6 text-fg-secondary">{plan.description}</p>}

            <PlanStepTree planId={plan.id} steps={plan.steps} onCompleteStep={onCompleteStep} />

            {plan.lifecycle_status === 'active' && (
              <div className="flex items-center gap-2 rounded-control border border-hairline bg-surface-inset px-2 py-1 transition-colors focus-within:border-hairline-strong">
                <button
                  type="button"
                  onClick={submitStep}
                  disabled={!newStep.trim()}
                  aria-label="Add step"
                  className="shrink-0 rounded-md p-1 text-fg-tertiary transition-colors hover:text-accent disabled:opacity-40"
                >
                  <Plus size={16} />
                </button>
                <input
                  value={newStep}
                  onChange={(event) => setNewStep(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault()
                      submitStep()
                    }
                  }}
                  placeholder="Add a step…"
                  className="min-w-0 flex-1 bg-transparent text-label text-fg outline-none placeholder:text-fg-tertiary"
                />
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <AsyncStatusPills
                connection={plan.connection_status}
                chunk={plan.chunk_status}
                bucketUpdate={plan.bucket_update_status}
              />
            </div>
          </div>
        )}
      </div>
    </CollectionRow>
  )
}

function PlanStepTree({
  planId,
  steps,
  onCompleteStep,
}: {
  planId: string
  steps: PlanStepItem[]
  onCompleteStep: (planId: string, stepId: string) => void
}) {
  if (steps.length === 0) {
    return <p className="text-caption text-fg-tertiary">No steps yet.</p>
  }
  return (
    <div className="space-y-0.5">
      {steps.map((step) => (
        <PlanStepNode
          key={step.id}
          planId={planId}
          step={step}
          onCompleteStep={onCompleteStep}
          depth={0}
        />
      ))}
    </div>
  )
}

function PlanStepNode({
  planId,
  step,
  onCompleteStep,
  depth,
}: {
  planId: string
  step: PlanStepItem
  onCompleteStep: (planId: string, stepId: string) => void
  depth: number
}) {
  const [collapsed, setCollapsed] = useState(false)
  const children = step.children || []
  const isLeaf = children.length === 0
  const progress = branchProgress(step)
  const completed = step.status === 'completed'

  return (
    <div className={depth > 0 ? 'ml-4 border-l border-hairline pl-3' : ''}>
      <div className="group/step flex items-start gap-2 rounded-control px-2 py-1.5 transition-colors hover:bg-surface-inset">
        {!isLeaf ? (
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? `Expand ${step.title}` : `Collapse ${step.title}`}
            className="mt-0.5 rounded-md text-fg-tertiary transition-colors hover:text-fg"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
        ) : (
          <button
            type="button"
            disabled={completed}
            onClick={() => onCompleteStep(planId, step.id)}
            aria-label={`Complete ${step.title}`}
            className="mt-0.5 rounded-full transition-transform active:scale-[0.9] disabled:cursor-default"
          >
            {completed ? (
              <CheckCircle2 size={15} className="text-success" />
            ) : (
              <span className="block h-[15px] w-[15px] rounded-full border border-hairline" />
            )}
          </button>
        )}
        <div className="min-w-0 flex-1">
          <div
            className={`text-label ${
              completed
                ? 'text-fg-tertiary line-through'
                : isLeaf
                  ? 'text-fg'
                  : 'font-medium text-fg'
            }`}
          >
            {step.title}
          </div>
          {step.description && (
            <div className="mt-0.5 text-caption leading-5 text-fg-secondary">{step.description}</div>
          )}
        </div>
        {!isLeaf && (
          <span className="mt-0.5 shrink-0">
            <Pill tone="neutral">
              {progress.completed}/{progress.total}
            </Pill>
          </span>
        )}
      </div>
      {!collapsed && children.length > 0 && (
        <div className="mt-0.5 space-y-0.5">
          {children.map((child) => (
            <PlanStepNode
              key={child.id}
              planId={planId}
              step={child}
              onCompleteStep={onCompleteStep}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
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
