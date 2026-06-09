const STORAGE_KEY = 'orbit:module-order'
const DEFAULT_ORDER = ['chat', 'curious', 'tasks', 'routine', 'plans', 'logs', 'documents', 'user_model', 'recommendations', 'strategies', 'goals']
const CHANGE_EVENT = 'orbit:module-order-changed'

export function defaultIndex(moduleId: string) {
  const i = DEFAULT_ORDER.indexOf(moduleId)
  return i === -1 ? DEFAULT_ORDER.length : i
}

function readStored(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

export function applyOrder(enabledIds: string[]): string[] {
  const stored = readStored()
  const enabled = new Set(enabledIds)
  const kept = stored.filter((id) => enabled.has(id))
  const remaining = enabledIds
    .filter((id) => !kept.includes(id))
    .sort((a, b) => defaultIndex(a) - defaultIndex(b))
  return [...kept, ...remaining]
}

export function setModuleOrder(ids: string[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT))
}

export function reorderById(ids: string[], id: string, delta: -1 | 1): string[] {
  const idx = ids.indexOf(id)
  if (idx === -1) return ids
  const next = idx + delta
  if (next < 0 || next >= ids.length) return ids
  const out = [...ids]
  ;[out[idx], out[next]] = [out[next], out[idx]]
  return out
}

export const moduleOrderChangeEvent = CHANGE_EVENT
