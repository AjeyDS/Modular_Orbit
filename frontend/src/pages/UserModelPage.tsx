import { useEffect, useMemo, useState } from 'react'
import { Save, ShieldCheck } from 'lucide-react'
import { fetchStoryBuckets, updateStoryBucket, type StoryBucketItem } from '../lib/api'
import { pageContentClass } from '../layout/pageShell'

export default function UserModelPage() {
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

  useEffect(() => {
    void loadBuckets()
  }, [])

  useEffect(() => {
    if (!selectedBucket) return
    setDraftName(selectedBucket.display_name)
    setDraftDescription(selectedBucket.description)
    setDraftContent(selectedBucket.content)
  }, [selectedBucket])

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
      setStatus('Saved. User Edit Lock is active for this bucket.')
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Unable to save Story Bucket')
    } finally {
      setSaving(false)
    }
  }

  const isDirty =
    selectedBucket !== null &&
    (draftName !== selectedBucket.display_name ||
      draftDescription !== selectedBucket.description ||
      draftContent !== selectedBucket.content)

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5">
          <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">User Model</h1>
          <p className="mt-1 text-[13px] text-gray-500 dark:text-gray-400">
            What Orbit understands about you. Edits lock a bucket from automatic rewriting.
          </p>
        </header>

        <div className="space-y-4">
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <h2 className="text-[16px] font-semibold text-gray-900 dark:text-gray-100">Story Buckets</h2>
                <p className="mt-1 text-[13px] leading-6 text-gray-500 dark:text-gray-400">
                  Story Buckets are Orbit's editable understanding of you. Edits update the markdown files directly and protect the section from automatic rewrites.
                </p>
              </div>
              <button
                type="button"
                disabled={!isDirty || saving || !selectedBucket}
                onClick={() => void saveBucket()}
                className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-[13px] font-medium text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:opacity-40"
              >
                <Save size={14} />
                {saving ? 'Saving...' : 'Save bucket'}
              </button>
            </div>
            {status && (
              <p className="mt-3 rounded-lg border border-gray-200 bg-gray-50/70 px-3 py-2 text-[12px] text-gray-600 dark:border-gray-800 dark:bg-[#18181A] dark:text-gray-400">
                {status}
              </p>
            )}
          </Card>

          {loading ? (
            <Card>
              <p className="py-6 text-center text-[13px] text-gray-400">Loading Story Buckets...</p>
            </Card>
          ) : (
            <div className="grid gap-3 lg:grid-cols-[16rem_minmax(0,1fr)]">
              <aside
                className="rounded-2xl border border-gray-200 bg-white p-2 dark:border-gray-800 dark:bg-[#1C1C1E]"
                style={{ borderWidth: '0.5px' }}
              >
                {buckets.map((bucket) => (
                  <button
                    key={bucket.id}
                    type="button"
                    onClick={() => setSelectedId(bucket.id)}
                    className={`mb-1 flex w-full items-start justify-between gap-3 rounded-lg px-3 py-2 text-left transition-colors ${
                      selectedBucket?.id === bucket.id
                        ? 'bg-gray-100 text-gray-900 dark:bg-gray-800 dark:text-gray-100'
                        : 'text-gray-500 hover:bg-gray-100 hover:text-gray-800 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200'
                    }`}
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] font-medium">{bucket.display_name}</span>
                      <span className="mt-0.5 block truncate text-[11px] text-gray-400">{bucket.stable_key}</span>
                    </span>
                    {bucket.last_user_edit_at && <ShieldCheck size={14} className="mt-0.5 shrink-0 text-blue-400" />}
                  </button>
                ))}
              </aside>

              {selectedBucket && (
                <section
                  className="rounded-2xl border border-gray-200 bg-white dark:border-gray-800 dark:bg-[#1C1C1E]"
                  style={{ borderWidth: '0.5px' }}
                >
                  <div className="border-b border-gray-100 p-4 dark:border-gray-800">
                    <div className="grid gap-3 md:grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)]">
                      <label className="grid gap-1.5">
                        <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Bucket name</span>
                        <input
                          value={draftName}
                          onChange={(event) => setDraftName(event.target.value)}
                          className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-[14px] outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200 dark:focus:border-gray-600"
                        />
                      </label>
                      <label className="grid gap-1.5">
                        <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Description</span>
                        <input
                          value={draftDescription}
                          onChange={(event) => setDraftDescription(event.target.value)}
                          className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-[14px] outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200 dark:focus:border-gray-600"
                        />
                      </label>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-gray-400">
                      <span>{selectedBucket.is_splittable ? 'Splittable bucket' : 'Stable bucket'}</span>
                      <span aria-hidden>·</span>
                      <span className="truncate">{selectedBucket.file_path}</span>
                      {selectedBucket.last_user_edit_at && (
                        <>
                          <span aria-hidden>·</span>
                          <span>User edited {new Date(selectedBucket.last_user_edit_at).toLocaleString()}</span>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="p-4">
                    <label className="grid gap-2">
                      <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">Markdown story</span>
                      <textarea
                        value={draftContent}
                        onChange={(event) => setDraftContent(event.target.value)}
                        rows={22}
                        spellCheck={false}
                        className="min-h-[28rem] resize-y rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 font-mono text-[13px] leading-6 text-gray-700 outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200 dark:focus:border-gray-600"
                      />
                    </label>
                  </div>
                </section>
              )}
            </div>
          )}
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
