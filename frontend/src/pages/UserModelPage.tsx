import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import {
  addUserNote,
  fetchUserFacts,
  fetchWovenDoc,
  reweaveUserModel,
  type UserFact,
  type WovenDoc,
} from '../lib/api'
import { Markdown } from '../components/Markdown'
import { pageContentClass } from '../layout/pageShell'
import { Card, Pill } from '../components/ui'

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString()
}

export default function UserModelPage() {
  const [doc, setDoc] = useState<WovenDoc | null>(null)
  const [facts, setFacts] = useState<UserFact[]>([])
  const [noteDraft, setNoteDraft] = useState('')
  const [docLoading, setDocLoading] = useState(true)
  const [reweaving, setReweaving] = useState(false)
  const [addingNote, setAddingNote] = useState(false)
  const [wovenStatus, setWovenStatus] = useState('')

  async function loadWovenModel() {
    setDocLoading(true)
    try {
      const [nextDoc, nextFacts] = await Promise.all([fetchWovenDoc(), fetchUserFacts(20)])
      setDoc(nextDoc)
      setFacts(nextFacts)
    } catch (err) {
      setWovenStatus(err instanceof Error ? err.message : 'Unable to load woven model')
    } finally {
      setDocLoading(false)
    }
  }

  async function refreshFacts() {
    try {
      setFacts(await fetchUserFacts(20))
    } catch {
      // Non-fatal; keep the prior list.
    }
  }

  async function reweave() {
    if (reweaving) return
    setReweaving(true)
    setWovenStatus('Re-weaving the model...')
    try {
      const next = await reweaveUserModel()
      if (next) {
        setDoc(next)
        setWovenStatus(`Re-wove version ${next.version}.`)
      } else {
        setWovenStatus('Nothing new to weave yet.')
      }
      await refreshFacts()
    } catch (err) {
      setWovenStatus(err instanceof Error ? err.message : 'Unable to re-weave')
    } finally {
      setReweaving(false)
    }
  }

  async function addNote(thenReweave: boolean) {
    const text = noteDraft.trim()
    if (!text || addingNote || reweaving) return
    setAddingNote(true)
    setWovenStatus('Adding note...')
    try {
      await addUserNote(text)
      setNoteDraft('')
      if (thenReweave) {
        // Weave the new note in immediately so the user doesn't need a second click.
        setWovenStatus('Note captured. Re-weaving the model...')
        await addingNoteReweave()
      } else {
        setWovenStatus('Note captured. It will weave into the model on the next re-weave.')
        await refreshFacts()
      }
    } catch (err) {
      setWovenStatus(err instanceof Error ? err.message : 'Unable to add note')
    } finally {
      setAddingNote(false)
    }
  }

  // Re-weave after an add without bailing on the reweaving guard (we may still be
  // inside addNote's busy window). Mirrors reweave() but lets addNote own the status copy.
  async function addingNoteReweave() {
    setReweaving(true)
    try {
      const next = await reweaveUserModel()
      if (next) {
        setDoc(next)
        setWovenStatus(`Note captured and re-wove version ${next.version}.`)
      } else {
        setWovenStatus('Note captured.')
      }
      await refreshFacts()
    } catch (err) {
      setWovenStatus(err instanceof Error ? err.message : 'Unable to re-weave')
    } finally {
      setReweaving(false)
    }
  }

  useEffect(() => {
    void loadWovenModel()
  }, [])

  const noteBusy = addingNote || reweaving
  const noteEmpty = !noteDraft.trim()

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5">
          <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">User Model</h1>
          <p className="mt-1 text-label text-fg-secondary">
            What Orbit understands about you, woven from your captured facts and notes.
          </p>
        </header>

        <div className="space-y-4">
          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-heading font-semibold text-fg">Woven User Model</h2>
                <p className="mt-1 text-label leading-6 text-fg-secondary">
                  Orbit weaves your captured facts and notes into a single living document.
                  {doc && (
                    <span className="ml-1 text-fg-tertiary">
                      Version {doc.version} · woven {formatTimestamp(doc.woven_at)}
                    </span>
                  )}
                </p>
              </div>
              <button
                type="button"
                disabled={reweaving}
                onClick={() => void reweave()}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-control bg-accent px-4 py-2 text-label font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
              >
                <RefreshCw size={14} className={reweaving ? 'animate-spin' : undefined} />
                {reweaving ? 'Re-weaving...' : 'Re-weave now'}
              </button>
            </div>
            {wovenStatus && (
              <p className="mt-3 rounded-control border border-hairline bg-surface-inset px-3 py-2 text-caption text-fg-secondary">
                {wovenStatus}
              </p>
            )}

            <div className="mt-4 rounded-control border border-hairline bg-surface-inset p-4 text-label leading-6 text-fg">
              {docLoading ? (
                <p className="text-center text-fg-tertiary">Loading woven model...</p>
              ) : doc ? (
                <Markdown>{doc.content}</Markdown>
              ) : (
                <p className="text-fg-tertiary">
                  No woven model yet — add a note or capture activity, then re-weave.
                </p>
              )}
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="text-heading font-semibold text-fg">Add note</h2>
            <p className="mt-1 text-label leading-6 text-fg-secondary">
              Capture a fact about yourself. Notes are saved and merged into your woven model.
            </p>
            <textarea
              value={noteDraft}
              onChange={(event) => setNoteDraft(event.target.value)}
              rows={3}
              placeholder="e.g. I prefer deep-work blocks in the morning."
              className="mt-3 w-full resize-y rounded-control border border-hairline bg-surface-inset px-3 py-2 text-label leading-6 text-fg outline-none transition-colors focus:border-accent"
            />
            <div className="mt-3 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                disabled={noteEmpty || noteBusy}
                onClick={() => void addNote(false)}
                className="inline-flex items-center justify-center rounded-control px-4 py-2 text-label font-medium text-fg-secondary transition-colors hover:text-fg disabled:opacity-40"
              >
                {addingNote && !reweaving ? 'Adding...' : 'Add note'}
              </button>
              <button
                type="button"
                disabled={noteEmpty || noteBusy}
                onClick={() => void addNote(true)}
                className="inline-flex items-center justify-center gap-2 rounded-control bg-accent px-4 py-2 text-label font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
              >
                <RefreshCw size={14} className={noteBusy ? 'animate-spin' : undefined} />
                {noteBusy ? 'Weaving...' : 'Add & re-weave'}
              </button>
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="text-heading font-semibold text-fg">Recently captured</h2>
            <p className="mt-1 text-label leading-6 text-fg-secondary">
              The latest facts feeding your model.
            </p>
            {facts.length === 0 ? (
              <p className="mt-4 text-label text-fg-tertiary">No facts captured yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {facts.map((fact) => (
                  <li
                    key={fact.id}
                    className="flex items-start justify-between gap-3 rounded-control border border-hairline bg-surface-inset px-3 py-2"
                  >
                    <div className="min-w-0">
                      <Pill tone="neutral" className="mr-2 align-middle uppercase tracking-wider">
                        {fact.source}
                      </Pill>
                      <span className="text-label leading-6 text-fg">{fact.text}</span>
                    </div>
                    {fact.woven ? (
                      <Pill tone="success" className="mt-0.5 shrink-0">
                        woven
                      </Pill>
                    ) : (
                      <Pill tone="warn" className="mt-0.5 shrink-0">
                        pending
                      </Pill>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
