import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, FileText, Loader2, UploadCloud, X } from 'lucide-react'
import { createDocument, uploadDocument } from '../../lib/api'

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
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={{ duration: 0.18, ease: easeOut }}
            className="relative flex max-h-[min(90vh,720px)] w-full max-w-[600px] flex-col overflow-hidden rounded-[1.25rem] border border-gray-200 bg-white text-gray-800 shadow-[0_24px_64px_-24px_rgba(23,27,22,0.28)] dark:border-gray-800 dark:bg-[#1C1C1E] dark:text-gray-200"
            style={{ borderWidth: '0.5px' }}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-center justify-between gap-3 border-b border-gray-100 px-5 py-3.5 dark:border-gray-800">
              <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Add a document</h2>
              <button
                type="button"
                onClick={requestClose}
                aria-label="Close"
                className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              >
                <X size={15} />
              </button>
            </header>

            <div className="px-5 pt-3">
              <div className="flex items-center rounded-lg bg-gray-100 p-0.5 dark:bg-gray-800">
                {(['upload', 'paste'] as const).map((value) => {
                  const active = segment === value
                  return (
                    <button
                      key={value}
                      type="button"
                      onClick={() => {
                        setSegment(value)
                        setLocalError('')
                      }}
                      className={`flex-1 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors ${
                        active
                          ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
                          : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200'
                      }`}
                    >
                      {value === 'upload' ? 'Upload file' : 'Paste text'}
                    </button>
                  )
                })}
              </div>
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
                      className={`flex min-h-[12rem] cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed px-5 py-8 text-center transition-[border-color,background-color,color] duration-200 ease-out ${
                        dragOver
                          ? 'border-blue-400 bg-blue-50/70 text-blue-600 dark:border-blue-500 dark:bg-blue-950/30 dark:text-blue-300'
                          : 'border-gray-300 bg-gray-50/50 text-gray-500 hover:border-gray-400 hover:bg-gray-50 dark:border-gray-700 dark:bg-[#1E1E20] dark:hover:border-gray-600'
                      }`}
                    >
                      <UploadCloud size={22} className="mb-3" />
                      <p className="text-[14px]">
                        Drop a file here or <span className="font-medium underline">browse</span>
                      </p>
                      <p className="mt-1.5 max-w-md text-[12px] leading-5 text-gray-400">
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
                              className="flex items-center gap-2 rounded-xl border border-gray-200 bg-gray-50 px-3 py-2 dark:border-gray-700 dark:bg-[#202024]"
                              style={{ borderWidth: '0.5px' }}
                            >
                              <FileText size={14} className="shrink-0 text-gray-400" />
                              <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-gray-700 dark:text-gray-300">
                                {file.name}
                              </span>
                              <span className="shrink-0 text-[11px] tabular-nums text-gray-400">
                                {formatBytes(file.size)}
                              </span>
                              <span className={uploadStatusClass(status)}>
                                {status}
                              </span>
                              <button
                                type="button"
                                disabled={status === 'uploading'}
                                onClick={() => removeFile(file)}
                                className="text-gray-400 transition-colors hover:text-gray-600 disabled:opacity-30 dark:hover:text-gray-200"
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
                      <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                        Name
                      </span>
                      <input
                        ref={nameInputRef}
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="orbit_notes"
                        className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-[14px] outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200 dark:focus:border-gray-600"
                      />
                    </label>
                    <label className="grid gap-1.5">
                      <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
                        Content
                      </span>
                      <textarea
                        value={content}
                        onChange={(event) => setContent(event.target.value)}
                        rows={9}
                        placeholder="Paste document text here…"
                        className="resize-none rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-[13px] leading-6 outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#1E1E20] dark:text-gray-200 dark:focus:border-gray-600"
                      />
                    </label>
                  </motion.div>
                )}
              </AnimatePresence>

              {localError && (
                <p className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
                  {localError}
                </p>
              )}
            </div>

            <footer className="flex items-center justify-between gap-3 border-t border-gray-100 px-5 py-3 dark:border-gray-800">
              <button
                type="button"
                onClick={requestClose}
                className="rounded-lg px-3 py-1.5 text-[13px] text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              >
                Cancel
              </button>
              {segment === 'upload' ? (
                <button
                  type="button"
                  disabled={pendingFiles.length === 0 || uploading}
                  onClick={() => void handleUpload()}
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
                >
                  {uploading ? <Loader2 size={14} className="animate-spin" /> : <UploadCloud size={14} />}
                  {uploading ? 'Uploading…' : 'Upload'}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!name.trim() || !content.trim() || saving}
                  onClick={() => void handlePasteSave()}
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
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
                  className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 border-t border-gray-200 bg-white/95 px-5 py-3 text-[13px] backdrop-blur dark:border-gray-800 dark:bg-[#1C1C1E]/95"
                >
                  <span className="text-gray-700 dark:text-gray-300">Discard this draft?</span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setConfirmingDiscard(false)}
                      className="rounded-lg px-3 py-1.5 text-[12px] text-gray-500 hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
                    >
                      Keep editing
                    </button>
                    <button
                      type="button"
                      onClick={discardAndClose}
                      className="rounded-lg bg-red-500 px-3 py-1.5 text-[12px] font-medium text-white transition-colors hover:bg-red-600"
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
  if (status === 'done') return `${base} bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200`
  if (status === 'error') return `${base} bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-200`
  if (status === 'uploading') return `${base} bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-200`
  return `${base} bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400`
}
