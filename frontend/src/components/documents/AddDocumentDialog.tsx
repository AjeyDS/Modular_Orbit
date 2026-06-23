import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, FileText, Loader2, UploadCloud, X } from 'lucide-react'
import { createDocument, uploadDocument } from '../../lib/api'
import { SegmentedControl } from '../ui'

type Segment = 'upload' | 'paste'
type UploadStatus = 'queued' | 'uploading' | 'done' | 'error'

const easeOut = [0.23, 1, 0.32, 1] as const

type Props = {
  open: boolean
  onClose: () => void
  onSaved: (message: string) => void
}

export function AddDocumentDialog({ open, onClose, onSaved }: Props) {
  const [segment, setSegment] = useState<Segment>('upload')
  const [pendingFiles, setPendingFiles] = useState<File[]>([])
  const [fileStatuses, setFileStatuses] = useState<Record<string, UploadStatus>>({})
  const [uploading, setUploading] = useState(false)
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [localError, setLocalError] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)

  const nameInputRef = useRef<HTMLInputElement | null>(null)

  const hasUnsaved =
    pendingFiles.length > 0 || name.trim().length > 0 || content.trim().length > 0

  function resetAll() {
    setSegment('upload')
    setPendingFiles([])
    setFileStatuses({})
    setUploading(false)
    setName('')
    setContent('')
    setSaving(false)
    setLocalError('')
    setDragOver(false)
    setConfirmingDiscard(false)
  }

  const requestClose = useCallback(() => {
    if (hasUnsaved) {
      setConfirmingDiscard(true)
      return
    }
    onClose()
    resetAll()
  }, [hasUnsaved, onClose])

  function discardAndClose() {
    onClose()
    resetAll()
  }

  async function handleUpload() {
    if (pendingFiles.length === 0 || uploading) return
    setUploading(true)
    setLocalError('')
    let done = 0
    let failed = 0
    const doneKeys = new Set<string>()
    try {
      for (const file of pendingFiles) {
        const key = fileKey(file)
        setFileStatuses((current) => ({ ...current, [key]: 'uploading' }))
        try {
          await uploadDocument(file)
          done += 1
          doneKeys.add(key)
          setFileStatuses((current) => ({ ...current, [key]: 'done' }))
        } catch (err) {
          failed += 1
          setFileStatuses((current) => ({ ...current, [key]: 'error' }))
          setLocalError(err instanceof Error ? err.message : 'Unable to upload one or more documents')
        }
      }
      if (failed === 0) {
        onSaved(`${done} file${done === 1 ? '' : 's'} uploaded and queued for connection review.`)
        onClose()
        resetAll()
      } else {
        onSaved(`${done} file${done === 1 ? '' : 's'} uploaded. ${failed} failed.`)
        setPendingFiles((current) => current.filter((file) => !doneKeys.has(fileKey(file))))
      }
    } finally {
      setUploading(false)
    }
  }

  async function handlePasteSave() {
    const originalName = name.trim()
    const body = content.trim()
    if (!originalName || !body || saving) return
    setSaving(true)
    setLocalError('')
    try {
      await createDocument({
        original_name: originalName.endsWith('.md') ? originalName : `${originalName}.md`,
        content: body,
      })
      onSaved('Document saved and queued for connection review.')
      onClose()
      resetAll()
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Unable to save document')
    } finally {
      setSaving(false)
    }
  }

  function handleDrop(event: React.DragEvent<HTMLLabelElement>) {
    event.preventDefault()
    setDragOver(false)
    const dropped = Array.from(event.dataTransfer.files)
    if (dropped.length > 0) {
      appendFiles(dropped)
      setLocalError('')
    }
  }

  function appendFiles(files: File[]) {
    setPendingFiles((current) => {
      const existing = new Set(current.map(fileKey))
      const next = [...current]
      for (const file of files) {
        if (!existing.has(fileKey(file))) next.push(file)
      }
      return next
    })
    setFileStatuses((current) => {
      const next = { ...current }
      for (const file of files) {
        next[fileKey(file)] = 'queued'
      }
      return next
    })
  }

  function removeFile(file: File) {
    const key = fileKey(file)
    setPendingFiles((current) => current.filter((item) => fileKey(item) !== key))
    setFileStatuses((current) => {
      const next = { ...current }
      delete next[key]
      return next
    })
  }

  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        requestClose()
      }
    }
    document.addEventListener('keydown', onKey)

    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKey)
    }
  }, [open, requestClose])

  useEffect(() => {
    if (!open) return
    if (segment !== 'paste') return
    const raf = requestAnimationFrame(() => {
      nameInputRef.current?.focus()
    })
    return () => cancelAnimationFrame(raf)
  }, [open, segment])

  if (typeof document === 'undefined') return null

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="add-document-dialog"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16, ease: easeOut }}
        >
          <motion.div
            className="absolute inset-0 bg-black/30 backdrop-blur-sm"
            onClick={requestClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18, ease: easeOut }}
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Add a document"
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={{ duration: 0.18, ease: easeOut }}
            className="relative flex max-h-[min(90vh,720px)] w-full max-w-[600px] flex-col overflow-hidden rounded-[var(--radius-modal)] border border-hairline bg-surface text-fg shadow-[0_24px_64px_-24px_rgba(0,0,0,0.28)]"
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3.5">
              <h2 className="text-body font-semibold tracking-[-0.01em] text-fg">Add a document</h2>
              <button
                type="button"
                onClick={requestClose}
                aria-label="Close"
                className="rounded-control p-1.5 text-fg-tertiary transition-colors hover:bg-surface-inset hover:text-fg"
              >
                <X size={15} />
              </button>
            </header>

            <div className="px-5 pt-3">
              <SegmentedControl
                ariaLabel="Document input mode"
                options={[
                  { value: 'upload', label: 'Upload file' },
                  { value: 'paste', label: 'Paste text' },
                ]}
                value={segment}
                onChange={(value) => {
                  setSegment(value)
                  setLocalError('')
                }}
              />
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              <AnimatePresence mode="wait" initial={false}>
                {segment === 'upload' ? (
                  <motion.div
                    key="upload"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.16, ease: easeOut }}
                  >
                    <label
                      onDragOver={(event) => {
                        event.preventDefault()
                        setDragOver(true)
                      }}
                      onDragLeave={() => setDragOver(false)}
                      onDrop={handleDrop}
                      className={`flex min-h-[12rem] cursor-pointer flex-col items-center justify-center rounded-card border border-dashed px-5 py-8 text-center transition-[border-color,background-color,color] duration-200 ease-out ${
                        dragOver
                          ? 'border-accent bg-accent/5 text-accent'
                          : 'border-hairline bg-surface-inset text-fg-secondary hover:border-hairline-strong'
                      }`}
                    >
                      <UploadCloud size={22} className="mb-3" />
                      <p className="text-label text-fg">
                        Drop a file here or <span className="font-medium underline">browse</span>
                      </p>
                      <p className="mt-1.5 max-w-md text-caption leading-5 text-fg-tertiary">
                        PDF, DOCX, Markdown, text, CSV, HTML, XML, RTF, or email. Orbit extracts text, chunks it, and queues it for review.
                      </p>
                      <input
                        type="file"
                        multiple
                        accept=".pdf,.md,.markdown,.txt,.json,.jsonl,.docx,.csv,.tsv,.html,.htm,.xml,.rtf,.eml"
                        onChange={(event) => {
                          const selected = Array.from(event.target.files ?? [])
                          if (selected.length > 0) {
                            appendFiles(selected)
                            setLocalError('')
                            event.target.value = ''
                          }
                        }}
                        className="hidden"
                      />
                    </label>

                    {pendingFiles.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {pendingFiles.map((file) => {
                          const status = fileStatuses[fileKey(file)] ?? 'queued'
                          return (
                            <div
                              key={fileKey(file)}
                              className="flex items-center gap-2 rounded-control border border-hairline bg-surface-inset px-3 py-2"
                            >
                              <FileText size={14} className="shrink-0 text-fg-tertiary" />
                              <span className="min-w-0 flex-1 truncate text-label font-medium text-fg-secondary">
                                {file.name}
                              </span>
                              <span className="shrink-0 text-caption tabular-nums text-fg-tertiary">
                                {formatBytes(file.size)}
                              </span>
                              <span className={uploadStatusClass(status)}>
                                {status}
                              </span>
                              <button
                                type="button"
                                disabled={status === 'uploading'}
                                onClick={() => removeFile(file)}
                                className="text-fg-tertiary transition-colors hover:text-fg disabled:opacity-30"
                                aria-label={`Remove ${file.name}`}
                              >
                                <X size={14} />
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </motion.div>
                ) : (
                  <motion.div
                    key="paste"
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.16, ease: easeOut }}
                    className="grid gap-3"
                  >
                    <label className="grid gap-1.5">
                      <span className="text-caption font-medium uppercase tracking-wider text-fg-secondary">
                        Name
                      </span>
                      <input
                        ref={nameInputRef}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="orbit_notes"
                        className="rounded-control border border-hairline bg-surface-inset px-3 py-2 text-label text-fg outline-none transition-colors focus:border-hairline-strong"
                      />
                    </label>
                    <label className="grid gap-1.5">
                      <span className="text-caption font-medium uppercase tracking-wider text-fg-secondary">
                        Content
                      </span>
                      <textarea
                        value={content}
                        onChange={(event) => setContent(event.target.value)}
                        rows={9}
                        placeholder="Paste document text here…"
                        className="resize-none rounded-control border border-hairline bg-surface-inset px-3 py-2 text-label leading-6 text-fg outline-none transition-colors focus:border-hairline-strong"
                      />
                    </label>
                  </motion.div>
                )}
              </AnimatePresence>

              {localError && (
                <p className="mt-3 rounded-control border border-danger/30 bg-danger/10 px-3 py-2 text-caption text-danger">
                  {localError}
                </p>
              )}
            </div>

            <footer className="flex items-center justify-between gap-3 border-t border-hairline px-5 py-3">
              <button
                type="button"
                onClick={requestClose}
                className="rounded-control px-3 py-1.5 text-label text-fg-secondary transition-colors hover:bg-surface-inset hover:text-fg"
              >
                Cancel
              </button>
              {segment === 'upload' ? (
                <button
                  type="button"
                  disabled={pendingFiles.length === 0 || uploading}
                  onClick={() => void handleUpload()}
                  className="inline-flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
                >
                  {uploading ? <Loader2 size={14} className="animate-spin" /> : <UploadCloud size={14} />}
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!name.trim() || !content.trim() || saving}
                  onClick={() => void handlePasteSave()}
                  className="inline-flex items-center gap-2 rounded-control bg-accent px-4 py-2 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
                >
                  {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                  {saving ? 'Saving…' : 'Save text'}
                </button>
              )}
            </footer>

            <AnimatePresence>
              {confirmingDiscard && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 8 }}
                  transition={{ duration: 0.16, ease: easeOut }}
                  className="glass absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 border-t border-hairline px-5 py-3 text-label"
                >
                  <span className="text-fg-secondary">Discard this draft?</span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirmingDiscard(false)}
                      className="rounded-control px-3 py-1.5 text-caption text-fg-secondary transition-colors hover:bg-surface-inset hover:text-fg"
                    >
                      Keep editing
                    </button>
                    <button
                      type="button"
                      onClick={discardAndClose}
                      className="rounded-control bg-danger px-3 py-1.5 text-caption font-medium text-white transition-colors hover:bg-danger/90"
                    >
                      Discard
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function fileKey(file: File) {
  return `${file.name}-${file.size}-${file.lastModified}`
}

function uploadStatusClass(status: UploadStatus) {
  const base = 'shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold'
  if (status === 'done') return `${base} bg-success/10 text-success`
  if (status === 'error') return `${base} bg-danger/10 text-danger`
  if (status === 'uploading') return `${base} bg-accent/10 text-accent`
  return `${base} bg-surface-inset text-fg-secondary`
}
