import { useEffect, useMemo, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import {
  disableModule,
  enableModule,
  fetchModuleCatalog,
  fetchShellState,
  type ModuleCatalogItem,
  type ModuleInstanceItem,
  type ShellState,
} from './lib/api'
import ChatPage from './pages/ChatPage'
import CuriousPage from './pages/CuriousPage'
import DocumentsPage from './pages/DocumentsPage'
import GoalsPage from './pages/GoalsPage'
import LogsPage from './pages/LogsPage'
import ModulesPage from './pages/ModulesPage'
import PlansPage from './pages/PlansPage'
import RoutinePage from './pages/RoutinePage'
import SettingsPage from './pages/SettingsPage'
import TasksPage from './pages/TasksPage'
import UserModelPage from './pages/UserModelPage'
import { Sidebar } from './layout/Sidebar'
import { ThemeProvider, useTheme } from './layout/useTheme'
import { ToastProvider } from './components/ui'

function App() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <AppContent />
      </ToastProvider>
    </ThemeProvider>
  )
}

function AppContent() {
  const location = useLocation()
  const { resolvedTheme } = useTheme()
  const [shell, setShell] = useState<ShellState | null>(null)
  const [catalog, setCatalog] = useState<ModuleCatalogItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const enabledModules = useMemo(() => uniqueEnabledModules(shell?.enabled_modules ?? [], catalog), [shell, catalog])
  const enabledByModule = useMemo(() => groupEnabledModules(shell?.enabled_modules ?? []), [shell])

  async function loadShell() {
    setError('')
    setLoading(true)
    try {
      const [nextShell, nextCatalog] = await Promise.all([fetchShellState(), fetchModuleCatalog()])
      setShell(nextShell)
      setCatalog(nextCatalog)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Modular Orbit')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadShell()
  }, [])

  return (
    <div className="min-h-screen bg-bg font-sans text-fg selection:bg-accent/30">
      <nav className="glass sticky top-0 z-50 border-b border-hairline transition-[border-color,background-color] duration-200 ease-out">
        <div className="flex h-12 w-full items-center justify-between px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <img
              src={resolvedTheme === 'light' ? '/orbit_light.png' : '/orbit_dark.png'}
              alt="Orbit logo"
              className="h-[22px] w-auto object-contain transition-opacity duration-200 ease-out"
            />
            <span className="text-lg font-semibold tracking-tight text-fg">Orbit</span>
            <span className="hidden rounded-full border border-hairline px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-fg-tertiary md:inline">
              Modular
            </span>
          </div>
        </div>
      </nav>

      <div className="grid w-full grid-cols-[12.5rem_minmax(0,1fr)] gap-0 lg:grid-cols-[15rem_minmax(0,1fr)]">
        <Sidebar enabledModules={enabledModules} />

        <main className="min-w-0">
          {error && (
            <div className="mx-6 mt-4 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}

          <div key={location.pathname} className="animate-[orbitFade_180ms_var(--ease-orbit-out)]">
            <Routes>
              <Route path="/" element={<Navigate to="/chat" replace />} />
              <Route path="/dashboard" element={<Navigate to="/chat" replace />} />
              <Route path="/workspace" element={<Navigate to="/chat" replace />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/modules/curious" element={<CuriousPage />} />
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/goals" element={<GoalsPage />} />
              <Route path="/modules/tasks" element={<TasksPage />} />
              <Route path="/modules/routine" element={<RoutinePage />} />
              <Route path="/modules/plans" element={<PlansPage />} />
              <Route path="/modules/documents" element={<DocumentsPage />} />
              <Route path="/user-model" element={<UserModelPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route
                path="/modules"
                element={
                  <ModulesPage
                    catalog={catalog}
                    enabledModules={enabledModules}
                    enabledByModule={enabledByModule}
                    loading={loading}
                    onEnable={async (moduleId) => {
                      await enableModule(moduleId)
                      await loadShell()
                    }}
                    onDisable={async (moduleId) => {
                      const instances = enabledByModule.get(moduleId) ?? []
                      await Promise.all(instances.map((instance) => disableModule(instance.id)))
                      await loadShell()
                    }}
                  />
                }
              />
              <Route path="*" element={<Navigate to="/chat" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}

function groupEnabledModules(instances: ModuleInstanceItem[]) {
  const grouped = new Map<string, ModuleInstanceItem[]>()
  for (const instance of instances) {
    grouped.set(instance.module_id, [...(grouped.get(instance.module_id) ?? []), instance])
  }
  return grouped
}

function uniqueEnabledModules(instances: ModuleInstanceItem[], catalog: ModuleCatalogItem[]) {
  const catalogById = new Map(catalog.map((module) => [module.id, module]))
  const byModule = new Map<string, ModuleInstanceItem>()
  for (const instance of instances) {
    if (!byModule.has(instance.module_id)) {
      const module = catalogById.get(instance.module_id)
      byModule.set(instance.module_id, {
        ...instance,
        module_name: module?.name ?? instance.module_name,
        display_name: module?.name ?? instance.display_name,
      })
    }
  }
  return [...byModule.values()].sort((a, b) => moduleOrder(a.module_id) - moduleOrder(b.module_id))
}

function moduleOrder(moduleId: string) {
  const order = ['chat', 'curious', 'tasks', 'routine', 'plans', 'logs', 'documents', 'user_model', 'recommendations', 'strategies', 'goals']
  const index = order.indexOf(moduleId)
  return index === -1 ? order.length : index
}

export default App
