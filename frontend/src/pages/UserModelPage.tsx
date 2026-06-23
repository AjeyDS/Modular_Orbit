import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, Save, ShieldCheck } from 'lucide-react'
import {
  addUserNote,
  fetchStoryBuckets,
  fetchUserFacts,
  fetchWovenDoc,
  reweaveUserModel,
  updateStoryBucket,
  type StoryBucketItem,
  type UserFact,
  type WovenDoc,
} from '../lib/api'
import { Markdown } from '../components/Markdown'
import { pageContentClass } from '../layout/pageShell'
import { Card, MasterDetail, NavItem, Pill, useToast } from '../components/ui'

function formatTimestamp(value: string): string {
  return new Date(value).toLocaleString()
}

export default function UserModelPage() {
  const { toast } = useToast()

  const [doc, setDoc] = useState<WovenDoc | null>(null)
  const [facts, setFacts] = useState<UserFact[]>([])
  const [noteDraft, setNoteDraft] = useState('')
  const [docLoading, setDocLoading] = useState(true)
  const [reweaving, setReweaving] = useState(false)
  const [addingNote, setAddingNote] = useState(false)
  const [wovenStatus, setWovenStatus] = useState('')

  const [buckets, setBuckets] = useState<StoryBucketItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  const [draftContent, setDraftContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState('')

  const selectedBucket = useMemo(
    () => buckets.find((bucket) => bucket.id === selectedId) ?? buckets[0] ?? null,
    [buckets, selectedId],
  )

  async function loadBuckets() {
    setLoading(true)
    setStatus('')
    try {
      const nextBuckets = await fetchStoryBuckets()
      setBuckets(nextBuckets)
      setSelectedId((current) => current ?? nextBuckets[0]?.id ?? null)
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Unable to load Story Buckets')
    } finally {
      setLoading(false)
    }
  }

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
    void loadBuckets()
  }, [])

  useEffect(() => {
    if (!selectedBucket) return
    setDraftName(selectedBucket.display_name)
    setDraftDescription(selectedBucket.description)
    setDraftContent(selectedBucket.content)
  }, [selectedBucket])

  const isDirty =
    selectedBucket !== null &&
    (draftName !== selectedBucket.display_name ||
      draftDescription !== selectedBucket.description ||
      draftContent !== selectedBucket.content)

  function selectBucket(nextId: string) {
    if (nextId === selectedBucket?.id) return
    if (isDirty) {
      // Don't silently discard unsaved editor edits — keep the user where they are.
      toast({ message: 'You have unsaved edits — save or discard them first.', tone: 'warn' })
      return
    }
    setSelectedId(nextId)
  }

  function discardDraft() {
    if (!selectedBucket) return
    setDraftName(selectedBucket.display_name)
    setDraftDescription(selectedBucket.description)
    setDraftContent(selectedBucket.content)
  }

  async function saveBucket() {
    if (!selectedBucket || saving) return
    setSaving(true)
    setStatus('Saving Story Bucket...')
    try {
      const updated = await updateStoryBucket(selectedBucket.id, {
        display_name: draftName.trim() || selectedBucket.display_name,
        description: draftDescription,
        content: draftContent,
      })
      setBuckets((current) => current.map((bucket) => (bucket.id === updated.id ? updated : bucket)))
      setStatus('Saved. This bucket is now locked from automatic rewrites.')
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Unable to save Story Bucket')
    } finally {
      setSaving(false)
    }
  }

  const noteBusy = addingNote || reweaving
  const noteEmpty = !noteDraft.trim()

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5">
          <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">User Model</h1>
          <p className="mt-1 text-label text-fg-secondary">
            What Orbit understands about you. Edits lock a bucket from automatic rewriting.
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

          <Card className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-heading font-semibold text-fg">Story Buckets (legacy)</h2>
                <p className="mt-1 text-label leading-6 text-fg-secondary">
                  Story Buckets are Orbit's editable understanding of you. Edits update the markdown directly and lock the section from automatic rewrites.
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {isDirty && (
                  <button
                    type="button"
                    disabled={!selectedBucket}
                    onClick={discardDraft}
                    className="inline-flex items-center justify-center rounded-control px-4 py-2 text-label font-medium text-fg-secondary transition-colors hover:text-fg disabled:opacity-40"
                  >
                    Discard
                  </button>
                )}
                <button
                  type="button"
                  disabled={!isDirty || saving || !selectedBucket}
                  onClick={() => void saveBucket()}
                  className="inline-flex items-center justify-center gap-2 rounded-control bg-accent px-4 py-2 text-label font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
                >
                  <Save size={14} />
                  {saving ? 'Saving...' : 'Save bucket'}
                </button>
              </div>
            </div>
            {status && (
              <p className="mt-3 rounded-control border border-hairline bg-surface-inset px-3 py-2 text-caption text-fg-secondary">
                {status}
              </p>
            )}
          </Card>

          {loading ? (
            <Card className="p-5">
              <p className="py-6 text-center text-label text-fg-tertiary">Loading Story Buckets...</p>
            </Card>
          ) : (
            <MasterDetail
              navWidthClass="lg:grid-cols-[16rem_minmax(0,1fr)]"
              nav={buckets.map((bucket) => (
                <NavItem
                  key={bucket.id}
                  active={selectedBucket?.id === bucket.id}
                  label={bucket.display_name}
                  sublabel={bucket.stable_key}
                  trailing={
                    bucket.last_user_edit_at ? <ShieldCheck size={14} className="text-accent" /> : undefined
                  }
                  onClick={() => selectBucket(bucket.id)}
                />
              ))}
              detail={
                selectedBucket && (
                  <Card className="overflow-hidden">
                    <div className="border-b border-hairline p-4">
                      <div className="grid gap-3 md:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
                        <label className="grid gap-1.5">
                          <span className="text-caption font-medium uppercase tracking-wider text-fg-tertiary">
                            Bucket name
                          </span>
                          <input
                            value={draftName}
                            onChange={(event) => setDraftName(event.target.value)}
                            className="rounded-control border border-hairline bg-surface-inset px-3 py-2 text-label text-fg outline-none transition-colors focus:border-accent"
                          />
                        </label>
                        <label className="grid gap-1.5">
                          <span className="text-caption font-medium uppercase tracking-wider text-fg-tertiary">
                            Description
                          </span>
                          <input
                            value={draftDescription}
                            onChange={(event) => setDraftDescription(event.target.value)}
                            className="rounded-control border border-hairline bg-surface-inset px-3 py-2 text-label text-fg outline-none transition-colors focus:border-accent"
                          />
                        </label>
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2 text-caption text-fg-tertiary">
                        <span>{selectedBucket.is_splittable ? 'Splittable bucket' : 'Stable bucket'}</span>
                        <span aria-hidden>·</span>
                        <span className="truncate">{selectedBucket.file_path}</span>
                        {selectedBucket.last_user_edit_at && (
                          <>
                            <span aria-hidden>·</span>
                            <span>Edited {formatTimestamp(selectedBucket.last_user_edit_at)}</span>
                          </>
                        )}
                      </div>
                    </div>

                    <div className="p-4">
                      <label className="grid gap-2">
                        <span className="text-caption font-medium uppercase tracking-wider text-fg-tertiary">
                          Markdown story
                        </span>
                        <textarea
                          value={draftContent}
                          onChange={(event) => setDraftContent(event.target.value)}
                          rows={22}
                          spellCheck={false}
                          className="min-h-[28rem] resize-y rounded-control border border-hairline bg-surface-inset px-3 py-2 font-mono text-label leading-6 text-fg outline-none transition-colors focus:border-accent"
                        />
                      </label>
                    </div>
                  </Card>
                )
              }
            />
          )}
        </div>
      </div>
    </div>
  )
}
