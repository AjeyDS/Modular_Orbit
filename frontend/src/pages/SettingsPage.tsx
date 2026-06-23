import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { Boxes, Brush, Monitor, Moon, Sun, User } from 'lucide-react'
import { pageContentClass } from '../layout/pageShell'
import { useTheme } from '../layout/useTheme'
import { Card, MasterDetail, NavItem, SegmentedControl } from '../components/ui'

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
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5">
          <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Settings</h1>
        </header>

        <MasterDetail
          navWidthClass="lg:grid-cols-[14rem_minmax(0,1fr)]"
          nav={tabs.map((item) => {
            const Icon = item.icon
            return (
              <NavItem
                key={item.id}
                active={tab === item.id}
                icon={<Icon size={15} />}
                label={item.label}
                onClick={() => selectTab(item.id)}
              />
            )
          })}
          detail={
            <>
              {tab === 'profile' && <ProfileTab />}
              {tab === 'appearance' && <AppearanceTab />}
              {tab === 'modules' && <ModulesTab />}
            </>
          }
        />
      </div>
    </div>
  )
}

function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <p className="text-label font-medium text-fg">{label}</p>
        {hint && <p className="mt-0.5 text-caption text-fg-secondary">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function ProfileTab() {
  return (
    <Card className="p-5">
      <h2 className="mb-1 text-heading font-semibold text-fg">Profile</h2>
      <p className="mb-4 text-label text-fg-secondary">How Orbit recognizes you. Editable in a future release.</p>
      <div className="divide-y divide-hairline">
        <FieldRow label="Name">
          <span className="text-label text-fg">Ajey</span>
        </FieldRow>
        <FieldRow label="Email">
          <span className="text-label text-fg">dhayashankerajey@gmail.com</span>
        </FieldRow>
      </div>
    </Card>
  )
}

function AppearanceTab() {
  const { theme, setTheme } = useTheme()
  return (
    <Card className="p-5">
      <h2 className="mb-1 text-heading font-semibold text-fg">Appearance</h2>
      <p className="mb-4 text-label text-fg-secondary">Set how Orbit looks on this device.</p>
      <SegmentedControl
        options={[
          { value: 'light', label: 'Light', icon: <Sun size={14} /> },
          { value: 'dark', label: 'Dark', icon: <Moon size={14} /> },
          { value: 'auto', label: 'Auto', icon: <Monitor size={14} /> },
        ]}
        value={theme}
        onChange={setTheme}
        ariaLabel="Theme"
      />
      <p className="mt-3 text-caption text-fg-secondary">Auto matches your system setting.</p>
    </Card>
  )
}

function ModulesTab() {
  return (
    <Card className="p-5">
      <h2 className="mb-1 text-heading font-semibold text-fg">Modules</h2>
      <p className="mb-4 text-label text-fg-secondary">
        Choose which modules appear in the sidebar and the order they stack. Lives on its own page so it's deep-linkable.
      </p>
      <NavLink
        to="/modules"
        className="inline-flex items-center gap-2 rounded-control bg-accent px-3.5 py-2 text-label font-medium text-white transition-colors hover:bg-accent-hover"
      >
        <Boxes size={14} />
        Open Manage Modules
      </NavLink>
    </Card>
  )
}
