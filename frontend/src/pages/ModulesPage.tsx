import { useEffect, useMemo, useState } from 'react'
import {
  Boxes,
  CircleHelp,
  FileText,
  Flame,
  GripVertical,
  ListTodo,
  NotebookTabs,
  ScrollText,
} from 'lucide-react'
import { Reorder } from 'framer-motion'
import type { ModuleCatalogItem, ModuleInstanceItem } from '../lib/api'
import { applyOrder, moduleOrderChangeEvent, setModuleOrder } from '../layout/moduleOrder'
import { EmptyState, Pill, SkeletonRows, useToast } from '../components/ui'
import { pageContentClass } from '../layout/pageShell'

type Props = {
  catalog: ModuleCatalogItem[]
  enabledModules: ModuleInstanceItem[]
  enabledByModule: Map<string, ModuleInstanceItem[]>
  loading: boolean
  onEnable: (moduleId: string) => Promise<void>
  onDisable: (moduleId: string) => Promise<void>
}

export default function ModulesPage({ catalog, enabledModules, enabledByModule, loading, onEnable, onDisable }: Props) {
  const [busyModule, setBusyModule] = useState<string | null>(null)
  const [orderTick, setOrderTick] = useState(0)
  const { undoToast } = useToast()

  useEffect(() => {
    const handler = () => setOrderTick((t) => t + 1)
    window.addEventListener(moduleOrderChangeEvent, handler)
    return () => window.removeEventListener(moduleOrderChangeEvent, handler)
  }, [])

  const orderedEnabled = useMemo(() => {
    const enabledIds = enabledModules.filter((m) => m.module_id !== 'chat').map((m) => m.module_id)
    const orderedIds = applyOrder(enabledIds)
    const byId = new Map(catalog.map((m) => [m.id, m]))
    return orderedIds.map((id) => byId.get(id)).filter((m): m is ModuleCatalogItem => Boolean(m))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, enabledModules, orderTick])

  const disabledItems = useMemo(() => {
    const enabledIds = new Set(enabledModules.map((m) => m.module_id))
    return catalog.filter((m) => !enabledIds.has(m.id) && m.id !== 'chat')
  }, [catalog, enabledModules])

  async function enableModule(item: ModuleCatalogItem) {
    setBusyModule(item.id)
    try {
      await onEnable(item.id)
    } finally {
      setBusyModule(null)
    }
  }

  // Disable is reversible: surface an undo toast and only persist on commit so
  // the 5s window can re-enable without round-tripping through the catalog.
  function disableModule(item: ModuleCatalogItem) {
    undoToast({
      message: 'Module disabled',
      onUndo: () => void onEnable(item.id),
      onCommit: () => void onDisable(item.id),
    })
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Manage Modules</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{orderedEnabled.length}</span> enabled
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{disabledItems.length}</span> available
            </p>
          </div>
        </header>

        {loading ? (
          <SkeletonRows count={4} />
        ) : (
          <div className="space-y-8">
            <section>
              <h2 className="mb-2 px-3 text-caption font-medium uppercase tracking-wider text-fg-tertiary">
                Enabled
              </h2>
              {orderedEnabled.length === 0 ? (
                <p className="px-3 py-2 text-label text-fg-secondary">No modules enabled yet — enable one below.</p>
              ) : (
                <Reorder.Group
                  axis="y"
                  values={orderedEnabled}
                  onReorder={(next) => setModuleOrder(next.map((m) => m.id))}
                  className="space-y-1"
                >
                  {orderedEnabled.map((item) => (
                    <Reorder.Item
                      key={item.id}
                      value={item}
                      className="group flex items-center gap-3 rounded-control px-3 py-2.5 transition-colors hover:bg-surface-inset"
                    >
                      <GripVertical
                        size={16}
                        className="shrink-0 cursor-grab text-fg-tertiary active:cursor-grabbing"
                        aria-hidden
                      />
                      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface-inset text-fg-secondary">
                        {moduleIcon(item.id)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <h3 className="text-label font-medium leading-snug text-fg">{item.name}</h3>
                        <p className="mt-0.5 truncate text-caption text-fg-secondary">{item.description}</p>
                      </div>
                      <button
                        type="button"
                        onClick={() => disableModule(item)}
                        className="shrink-0 rounded-control px-3 py-1.5 text-label font-medium text-fg-secondary transition-colors hover:bg-surface-inset hover:text-fg"
                      >
                        Disable
                      </button>
                    </Reorder.Item>
                  ))}
                </Reorder.Group>
              )}
            </section>

            <section>
              <h2 className="mb-2 px-3 text-caption font-medium uppercase tracking-wider text-fg-tertiary">
                Available
              </h2>
              {disabledItems.length === 0 ? (
                <EmptyState icon={<Boxes size={18} />} title="Everything in the catalog is enabled." />
              ) : (
                <ul className="divide-y divide-hairline">
                  {disabledItems.map((item) => {
                    const busy = busyModule === item.id
                    return (
                      <li key={item.id} className="flex items-center gap-3 px-3 py-2.5">
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface-inset text-fg-secondary">
                          {moduleIcon(item.id)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="text-label font-medium leading-snug text-fg">{item.name}</h3>
                            <Pill tone="neutral">{humanizeStorageStrategy(item.storage_strategy)}</Pill>
                          </div>
                          <p className="mt-0.5 text-caption leading-5 text-fg-secondary">{item.description}</p>
                        </div>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void enableModule(item)}
                          className="shrink-0 rounded-control bg-accent px-3 py-1.5 text-label font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-progress disabled:opacity-50"
                        >
                          {busy ? '…' : 'Enable'}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  )
}

function humanizeStorageStrategy(value: string) {
  if (value === 'generalized') return 'Generalized storage'
  if (value === 'extended') return 'Extended storage'
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function moduleIcon(moduleId: string) {
  if (moduleId === 'tasks') return <ListTodo size={16} />
  if (moduleId === 'routine') return <Flame size={16} />
  if (moduleId === 'plans') return <NotebookTabs size={16} />
  if (moduleId === 'documents') return <FileText size={16} />
  if (moduleId === 'logs') return <ScrollText size={16} />
  if (moduleId === 'curious') return <CircleHelp size={16} />
  return <Boxes size={16} />
}
