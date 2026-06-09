import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Boxes, Brush, Monitor, Moon, Sun, User } from 'lucide-react'
import { pageContentClass } from '../layout/pageShell'
import { useTheme, type Theme } from '../layout/useTheme'

type SettingsTab = 'profile' | 'appearance' | 'modules'

const tabs: Array<{ id: SettingsTab; label: string; icon: typeof User }> = [
  { id: 'profile', label: 'Profile', icon: User },
  { id: 'appearance', label: 'Appearance', icon: Brush },
  { id: 'modules', label: 'Modules', icon: Boxes },
]

function readHashTab(): SettingsTab {
  const hash = window.location.hash.replace('#', '')
  if (hash === 'profile' || hash === 'appearance' || hash === 'modules') return hash
  return 'profile'
}

export default function SettingsPage() {
  const [tab, setTab] = useState<SettingsTab>(() => readHashTab())

  useEffect(() => {
    function onHash() {
      setTab(readHashTab())
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  function selectTab(next: SettingsTab) {
    setTab(next)
    if (window.location.hash !== `#${next}`) {
      window.history.replaceState(null, '', `#${next}`)
    }
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5">
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Settings</h1>
        </header>

        <div className="grid gap-5 lg:grid-cols-[14rem_minmax(0,1fr)]">
          <aside
            className="h-fit rounded-2xl border border-gray-200 bg-white p-2 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
            style={{ borderWidth: '0.5px' }}
          >
            {tabs.map((item) => {
              const Icon = item.icon
              const active = tab === item.id
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => selectTab(item.id)}
                  className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] font-medium transition-colors ${
                    active
                      ? 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
                      : 'text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200'
                  }`}
                >
                  <Icon size={14} />
                  {item.label}
                </button>
              )
            })}
          </aside>

          <section className="min-w-0">
            {tab === 'profile' && <ProfileTab />}
            {tab === 'appearance' && <AppearanceTab />}
            {tab === 'modules' && <ModulesTab />}
          </section>
        </div>
      </div>
    </div>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-2xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
      style={{ borderWidth: '0.5px' }}
    >
      {children}
    </div>
  )
}

function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-gray-800 dark:text-gray-200">{label}</p>
        {hint && <p className="mt-0.5 text-[12px] text-gray-500 dark:text-gray-400">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function ProfileTab() {
  return (
    <Card>
      <h2 className="mb-1 text-[16px] font-semibold text-gray-900 dark:text-gray-100">Profile</h2>
      <p className="mb-4 text-[13px] text-gray-500 dark:text-gray-400">How Orbit recognizes you. Editable in a future release.</p>
      <div className="divide-y divide-gray-100 dark:divide-gray-800">
        <FieldRow label="Name">
          <span className="text-[13px] text-gray-700 dark:text-gray-300">Ajey</span>
        </FieldRow>
        <FieldRow label="Email">
          <span className="text-[13px] text-gray-700 dark:text-gray-300">dhayashankerajey@gmail.com</span>
        </FieldRow>
      </div>
    </Card>
  )
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme()
  const options: Array<{ value: Theme; label: string; icon: typeof Sun; hint: string }> = [
    { value: 'light', label: 'Light', icon: Sun, hint: 'Always light' },
    { value: 'dark', label: 'Dark', icon: Moon, hint: 'Always dark' },
    { value: 'auto', label: 'Auto', icon: Monitor, hint: 'Match system' },
  ]
  return (
    <Card>
      <h2 className="mb-1 text-[16px] font-semibold text-gray-900 dark:text-gray-100">Appearance</h2>
      <p className="mb-4 text-[13px] text-gray-500 dark:text-gray-400">Set how Orbit looks on this device.</p>
      <div className="grid gap-2 sm:grid-cols-3">
        {options.map((opt) => {
          const Icon = opt.icon
          const active = theme === opt.value
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => setTheme(opt.value)}
              className={`flex flex-col items-start gap-1 rounded-xl border px-4 py-3 text-left transition-colors ${
                active
                  ? 'border-blue-400 bg-blue-50/60 text-gray-900 dark:border-blue-700 dark:bg-blue-950/30 dark:text-gray-100'
                  : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-300 dark:hover:border-gray-600'
              }`}
              style={{ borderWidth: '0.5px' }}
            >
              <Icon size={16} />
              <span className="text-[13px] font-medium">{opt.label}</span>
              <span className="text-[11px] text-gray-500 dark:text-gray-400">{opt.hint}</span>
            </button>
          )
        })}
      </div>
    </Card>
  )
}

function ModulesTab() {
  return (
    <Card>
      <h2 className="mb-1 text-[16px] font-semibold text-gray-900 dark:text-gray-100">Modules</h2>
      <p className="mb-4 text-[13px] text-gray-500 dark:text-gray-400">
        Choose which modules appear in the sidebar and the order they stack. Lives on its own page so it's deep-linkable.
      </p>
      <NavLink
        to="/modules"
        className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-3.5 py-2 text-[13px] font-medium text-white transition-colors hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
      >
        <Boxes size={14} />
        Open Manage Modules
      </NavLink>
    </Card>
  )
}
