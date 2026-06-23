import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Boxes,
  Check,
  CircleHelp,
  FileText,
  Flame,
  ListTodo,
  MessageCircle,
  NotebookTabs,
  Pencil,
  Plus,
  ScrollText,
  ShieldCheck,
  Target,
  Trash2,
  X,
} from 'lucide-react'
import {
  deleteChatSession,
  fetchChatSessions,
  renameChatSession,
  type ChatSessionItem,
  type ModuleInstanceItem,
} from '../lib/api'
import { applyOrder, moduleOrderChangeEvent } from './moduleOrder'
import { ProfileMenu } from './ProfileMenu'

type SidebarTab = 'chat' | 'modules'

export const newChatEvent = 'orbit:new-chat'
export const chatSessionChangedEvent = 'orbit:chat-session-changed'

function activeTab(pathname: string): SidebarTab {
  if (pathname === '/logs') return 'modules'
  if (pathname === '/goals') return 'modules'
  if (pathname === '/user-model') return 'modules'
  if (pathname.startsWith('/modules')) return 'modules'
  return 'chat'
}

export function Sidebar({ enabledModules }: { enabledModules: ModuleInstanceItem[] }) {
  const location = useLocation()
  const navigate = useNavigate()
  const tab = activeTab(location.pathname)

  const orderedModules = useOrderedModules(enabledModules)

  function selectTab(next: SidebarTab) {
    if (next === tab) return
    if (next === 'chat') {
      navigate('/chat')
      return
    }
    // Modules: land on the first enabled module, or the manage page if none.
    const first = orderedModules[0]
    navigate(first ? modulePath(first.module_id) : '/modules')
  }

  function handleNewChat() {
    window.dispatchEvent(new CustomEvent(newChatEvent))
    navigate('/chat')
  }

  return (
    <aside className="glass sticky top-12 flex h-[calc(100vh-3rem)] shrink-0 flex-col self-start border-r border-hairline px-3 py-4 lg:px-4">
      <div className="mb-4 flex items-center rounded-lg bg-surface-inset p-0.5">
        {(['chat', 'modules'] as const).map((value) => {
          const active = tab === value
          return (
            <button
              key={value}
              type="button"
              onClick={() => selectTab(value)}
              className="relative flex-1 rounded-md px-3 py-1.5 text-[12px] font-medium"
            >
              {active && (
                <motion.div
                  layoutId="sidebar-tab-bg"
                  className="absolute inset-0 rounded-md bg-surface shadow-sm"
                  transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
                />
              )}
              <span className={`relative z-10 ${active ? 'text-fg' : 'text-fg-secondary'}`}>
                {value === 'chat' ? 'Chat' : 'Modules'}
              </span>
            </button>
          )
        })}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
        {tab === 'chat' ? <ChatPane onNewChat={handleNewChat} /> : <ModulesPane orderedModules={orderedModules} />}
      </div>

      <div className="mt-2 border-t border-hairline pt-2">
        <ProfileMenu />
      </div>
    </aside>
  )
}

function useOrderedModules(enabledModules: ModuleInstanceItem[]) {
  const [orderTick, setOrderTick] = useState(0)
  useEffect(() => {
    const handler = () => setOrderTick((t) => t + 1)
    window.addEventListener(moduleOrderChangeEvent, handler)
    return () => window.removeEventListener(moduleOrderChangeEvent, handler)
  }, [])

  return useMemo(() => {
    const enabledIds = enabledModules.filter((m) => m.module_id !== 'chat').map((m) => m.module_id)
    const orderedIds = applyOrder(enabledIds)
    const byId = new Map(enabledModules.map((m) => [m.module_id, m]))
    return orderedIds.map((id) => byId.get(id)).filter((m): m is ModuleInstanceItem => Boolean(m))
    // orderTick triggers re-evaluation when localStorage changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabledModules, orderTick])
}

function ChatPane({ onNewChat }: { onNewChat: () => void }) {
  const [searchParams] = useSearchParams()
  const activeSessionId = searchParams.get('session')
  const [sessions, setSessions] = useState<ChatSessionItem[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const items = await fetchChatSessions()
      setSessions(items)
      setLoadError('')
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Unable to load chats')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  useEffect(() => {
    const handler = () => void refresh()
    window.addEventListener(chatSessionChangedEvent, handler)
    return () => window.removeEventListener(chatSessionChangedEvent, handler)
  }, [refresh])

  return (
    <>
      <button
        type="button"
        onClick={onNewChat}
        className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-medium text-fg-secondary transition-colors hover:bg-surface-inset"
      >
        <Plus size={15} />
        New chat
      </button>
      <p className="mt-5 px-3 text-[11px] font-medium uppercase tracking-wider text-fg-tertiary">
        Recents
      </p>
      {loading ? (
        <p className="px-3 py-1.5 text-[12px] text-fg-tertiary">Loading…</p>
      ) : loadError ? (
        <p className="px-3 py-1.5 text-[12px] text-danger">{loadError}</p>
      ) : sessions.length === 0 ? (
        <p className="px-3 py-1.5 text-[12px] text-fg-tertiary">
          Past conversations will appear here.
        </p>
      ) : (
        <div className="mt-1 flex flex-col gap-0.5">
          {sessions.map((session) => (
            <RecentRow
              key={session.id}
              session={session}
              isActive={session.id === activeSessionId}
              onChanged={refresh}
            />
          ))}
        </div>
      )}
    </>
  )
}

function RecentRow({
  session,
  isActive,
  onChanged,
}: {
  session: ChatSessionItem
  isActive: boolean
  onChanged: () => void
}) {
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState(false)
  const [titleDraft, setTitleDraft] = useState(session.title ?? '')
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!renaming) setTitleDraft(session.title ?? '')
  }, [session.title, renaming])

  async function commitRename() {
    const next = titleDraft.trim()
    if (!next || next === session.title) {
      setRenaming(false)
      return
    }
    setBusy(true)
    try {
      await renameChatSession(session.id, next)
      onChanged()
    } catch (err) {
      console.error(err)
    } finally {
      setBusy(false)
      setRenaming(false)
    }
  }

  async function commitDelete() {
    setBusy(true)
    try {
      await deleteChatSession(session.id)
      if (isActive) navigate('/chat')
      onChanged()
    } catch (err) {
      console.error(err)
    } finally {
      setBusy(false)
      setConfirmingDelete(false)
    }
  }

  if (confirmingDelete) {
    return (
      <div className="flex items-center justify-between gap-1 rounded-lg bg-danger/10 px-2 py-1.5">
        <span className="truncate text-[12px] text-danger">Delete?</span>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            disabled={busy}
            onClick={commitDelete}
            aria-label="Confirm delete"
            className="rounded-md p-1 text-danger hover:bg-danger/15"
          >
            <Check size={12} />
          </button>
          <button
            type="button"
            onClick={() => setConfirmingDelete(false)}
            aria-label="Cancel delete"
            className="rounded-md p-1 text-danger hover:bg-danger/15"
          >
            <X size={12} />
          </button>
        </div>
      </div>
    )
  }

  if (renaming) {
    return (
      <div className="rounded-lg bg-surface-inset px-2 py-1">
        <input
          autoFocus
          value={titleDraft}
          onChange={(event) => setTitleDraft(event.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void commitRename()
            if (event.key === 'Escape') {
              setTitleDraft(session.title ?? '')
              setRenaming(false)
            }
          }}
          className="w-full bg-transparent text-[13px] text-fg outline-none"
        />
      </div>
    )
  }

  const displayTitle = session.title?.trim() || 'Untitled chat'
  const rowClasses = `group flex w-full items-center gap-1 rounded-lg px-2 py-1.5 transition-colors ${
    isActive
      ? 'bg-surface-inset'
      : 'hover:bg-surface-inset'
  }`
  const linkClasses = `flex min-w-0 flex-1 items-center gap-2 text-left text-[13px] transition-colors ${
    isActive
      ? 'text-fg'
      : 'text-fg-secondary group-hover:text-fg'
  }`

  return (
    <div className={rowClasses}>
      <NavLink to={`/chat?session=${encodeURIComponent(session.id)}`} className={linkClasses}>
        <MessageCircle size={13} className="shrink-0 text-fg-tertiary" />
        <span className="min-w-0 flex-1 truncate">{displayTitle}</span>
      </NavLink>
      <div className="flex shrink-0 items-center gap-0.5">
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            setRenaming(true)
          }}
          aria-label={`Rename ${displayTitle}`}
          className="rounded-md p-1 text-fg-tertiary transition-colors hover:bg-surface-inset hover:text-fg-secondary focus-visible:bg-surface-inset focus-visible:text-fg-secondary"
        >
          <Pencil size={11} />
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            setConfirmingDelete(true)
          }}
          aria-label={`Delete ${displayTitle}`}
          className="rounded-md p-1 text-fg-tertiary transition-colors hover:bg-danger/10 hover:text-danger focus-visible:bg-danger/10 focus-visible:text-danger"
        >
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  )
}

function ModulesPane({ orderedModules }: { orderedModules: ModuleInstanceItem[] }) {
  return (
    <>
      {orderedModules.map((item) => (
        <NavLink
          key={item.module_id}
          to={modulePath(item.module_id)}
          className={({ isActive }) =>
            `flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
              isActive
                ? 'bg-surface-inset text-fg'
                : 'text-fg-secondary hover:bg-surface-inset hover:text-fg'
            }`
          }
        >
          {moduleIcon(item.module_id)}
          <span className="truncate">{item.module_name}</span>
        </NavLink>
      ))}
      <div className="mt-3 border-t border-hairline pt-3">
        <NavLink
          to="/modules"
          className={({ isActive }) =>
            `flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
              isActive
                ? 'bg-surface-inset text-fg'
                : 'text-fg-secondary hover:bg-surface-inset hover:text-fg'
            }`
          }
        >
          <Boxes size={15} />
          <span className="truncate">Manage Modules</span>
        </NavLink>
      </div>
    </>
  )
}

function modulePath(moduleId: string) {
  if (moduleId === 'chat') return '/chat'
  if (moduleId === 'logs') return '/logs'
  if (moduleId === 'goals') return '/goals'
  if (moduleId === 'user_model') return '/user-model'
  return `/modules/${moduleId}`
}

function moduleIcon(moduleId: string) {
  if (moduleId === 'tasks') return <ListTodo size={15} />
  if (moduleId === 'routine') return <Flame size={15} />
  if (moduleId === 'plans') return <NotebookTabs size={15} />
  if (moduleId === 'documents') return <FileText size={15} />
  if (moduleId === 'logs') return <ScrollText size={15} />
  if (moduleId === 'goals') return <Target size={15} />
  if (moduleId === 'curious') return <CircleHelp size={15} />
  if (moduleId === 'user_model') return <ShieldCheck size={15} />
  return <Boxes size={15} />
}
