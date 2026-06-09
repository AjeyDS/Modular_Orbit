import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronDown, Monitor, Moon, Settings as SettingsIcon, Sun } from 'lucide-react'
import { useTheme, type Theme } from './useTheme'

const USER_NAME = 'Ajey'
const USER_EMAIL = 'dhayashankerajey@gmail.com'

const themeOptions: Array<{ value: Theme; label: string; icon: typeof Sun }> = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'auto', label: 'Auto', icon: Monitor },
]

export function ProfileMenu() {
  const navigate = useNavigate()
  const { theme, setTheme } = useTheme()
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false)
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-gray-100 dark:hover:bg-gray-800"
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-50 text-[11px] font-bold text-blue-600 dark:bg-blue-950/50 dark:text-blue-300">
          {USER_NAME.slice(0, 2).toUpperCase()}
        </div>
        <span className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-gray-800 dark:text-gray-200">
          {USER_NAME}
        </span>
        <ChevronDown size={14} className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 mb-2 w-[14.5rem] origin-bottom-left rounded-xl border border-gray-200 bg-white p-1 shadow-lg dark:border-gray-800 dark:bg-[#1C1C1E]"
          style={{ borderWidth: '0.5px' }}
        >
          <div className="px-2.5 py-1.5">
            <p className="truncate text-[13px] font-medium text-gray-900 dark:text-gray-100">{USER_NAME}</p>
            <p className="truncate text-[11px] text-gray-400">{USER_EMAIL}</p>
          </div>
          <div className="my-1 border-t border-gray-100 dark:border-gray-800" />
          <div className="px-1.5 py-1.5">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-gray-400">Theme</p>
            <div className="flex items-center rounded-md bg-gray-100 p-0.5 dark:bg-gray-800">
              {themeOptions.map((opt) => {
                const Icon = opt.icon
                const active = theme === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setTheme(opt.value)}
                    aria-pressed={active}
                    className={`flex flex-1 items-center justify-center gap-1 rounded px-1.5 py-1 text-[11px] font-medium transition-colors ${
                      active
                        ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
                        : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
                    }`}
                  >
                    <Icon size={11} />
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </div>
          <div className="my-1 border-t border-gray-100 dark:border-gray-800" />
          <button
            type="button"
            onClick={() => {
              navigate('/settings')
              setOpen(false)
            }}
            className="flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] text-gray-700 transition-colors hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            <SettingsIcon size={14} />
            Settings…
          </button>
        </div>
      )}
    </div>
  )
}
