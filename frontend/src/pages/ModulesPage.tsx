import { useEffect, useMemo, useState } from 'react'
import {
  Boxes,
  ChevronDown,
  ChevronUp,
  CircleHelp,
  FileText,
  Flame,
  ListTodo,
  NotebookTabs,
  ScrollText,
} from 'lucide-react'
import { motion } from 'framer-motion'
import type { ModuleCatalogItem, ModuleInstanceItem } from '../lib/api'
import { applyOrder, moduleOrderChangeEvent, reorderById, setModuleOrder } from '../layout/moduleOrder'
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

  function moveModule(id: string, delta: -1 | 1) {
    const enabledIds = enabledModules.filter((m) => m.module_id !== 'chat').map((m) => m.module_id)
    const ordered = applyOrder(enabledIds)
    const next = reorderById(ordered, id, delta)
    if (next !== ordered) setModuleOrder(next)
  }

  async function toggle(item: ModuleCatalogItem, enabled: boolean) {
    setBusyModule(item.id)
    try {
      if (enabled) await onDisable(item.id)
      else await onEnable(item.id)
    } finally {
      setBusyModule(null)
    }
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Manage Modules</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{orderedEnabled.length}</span> enabled
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{disabledItems.length}</span> available
            </p>
          </div>
        </header>

        {loading ? (
          <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center text-[14px] text-gray-400 dark:border-gray-800 dark:bg-[#1C1C1E]" style={{ borderWidth: '0.5px' }}>
            Loading module catalog…
          </div>
        ) : (
          <div className="space-y-6">
            <section
              className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
              style={{ borderWidth: '0.5px' }}
            >
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200">Enabled</h2>
                <p className="text-[11px] text-gray-400">Up/down arrows reorder the sidebar.</p>
              </div>
              {orderedEnabled.length === 0 ? (
                <p className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-4 py-8 text-center text-[13px] text-gray-400 dark:border-gray-700 dark:bg-[#18181A]">
                  No modules enabled yet — enable one below.
                </p>
              ) : (
                <ul className="space-y-2">
                  {orderedEnabled.map((item, index) => {
                    const busy = busyModule === item.id
                    return (
                      <motion.li
                        key={item.id}
                        layout
                        transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
                        className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white px-3 py-2.5 dark:border-gray-800 dark:bg-[#1C1C1E]"
                        style={{ borderWidth: '0.5px' }}
                      >
                        <div className="flex shrink-0 flex-col">
                          <button
                            type="button"
                            disabled={index === 0}
                            onClick={() => moveModule(item.id, -1)}
                            className="rounded p-0.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 disabled:cursor-default disabled:opacity-30 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                            aria-label={`Move ${item.name} up`}
                          >
                            <ChevronUp size={14} />
                          </button>
                          <button
                            type="button"
                            disabled={index === orderedEnabled.length - 1}
                            onClick={() => moveModule(item.id, 1)}
                            className="rounded p-0.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 disabled:cursor-default disabled:opacity-30 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                            aria-label={`Move ${item.name} down`}
                          >
                            <ChevronDown size={14} />
                          </button>
                        </div>
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-300">
                          {moduleIcon(item.id)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="text-[14px] font-medium leading-snug text-gray-800 dark:text-gray-200">{item.name}</h3>
                          <p className="mt-0.5 truncate text-[12px] text-gray-500 dark:text-gray-400">{item.description}</p>
                        </div>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void toggle(item, true)}
                          className="rounded-lg px-3 py-1.5 text-[12px] font-medium text-gray-500 transition-colors hover:bg-gray-100 disabled:cursor-progress disabled:opacity-50 dark:text-gray-300 dark:hover:bg-gray-800"
                        >
                          {busy ? '…' : 'Disable'}
                        </button>
                      </motion.li>
                    )
                  })}
                </ul>
              )}
            </section>

            <section
              className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
              style={{ borderWidth: '0.5px' }}
            >
              <div className="mb-3 flex items-baseline justify-between">
                <h2 className="text-[14px] font-semibold text-gray-800 dark:text-gray-200">Available</h2>
                <p className="text-[11px] text-gray-400">Catalog modules you haven't turned on yet.</p>
              </div>
              {disabledItems.length === 0 ? (
                <p className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-4 py-8 text-center text-[13px] text-gray-400 dark:border-gray-700 dark:bg-[#18181A]">
                  Everything in the catalog is enabled.
                </p>
              ) : (
                <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {disabledItems.map((item) => {
                    const busy = busyModule === item.id
                    const enabled = (enabledByModule.get(item.id) ?? []).length > 0
                    return (
                      <li
                        key={item.id}
                        className="flex items-start gap-3 rounded-xl border border-gray-200 bg-white p-3 dark:border-gray-800 dark:bg-[#1C1C1E]"
                        style={{ borderWidth: '0.5px' }}
                      >
                        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-300">
                          {moduleIcon(item.id)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="text-[14px] font-medium leading-snug text-gray-800 dark:text-gray-200">{item.name}</h3>
                          <p className="mt-0.5 text-[12px] leading-5 text-gray-500 dark:text-gray-400">{item.description}</p>
                          <p className="mt-1 text-[10px] uppercase tracking-wider text-gray-400">{item.storage_strategy}</p>
                        </div>
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void toggle(item, enabled)}
                          className="rounded-lg bg-blue-500 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-blue-600 disabled:cursor-progress disabled:opacity-50"
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

function moduleIcon(moduleId: string) {
  if (moduleId === 'tasks') return <ListTodo size={16} />
  if (moduleId === 'routine') return <Flame size={16} />
  if (moduleId === 'plans') return <NotebookTabs size={16} />
  if (moduleId === 'documents') return <FileText size={16} />
  if (moduleId === 'logs') return <ScrollText size={16} />
  if (moduleId === 'curious') return <CircleHelp size={16} />
  return <Boxes size={16} />
}
