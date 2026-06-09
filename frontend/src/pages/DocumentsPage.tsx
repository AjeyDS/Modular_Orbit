import { useEffect, useMemo, useState } from 'react'
import { FileText, Pencil, Plus } from 'lucide-react'
import {
  fetchDocuments,
  renameDocument,
  updateDocumentAnnotation,
  type DocumentItem,
} from '../lib/api'
import { AsyncStatusPills } from '../components/status'
import { pageContentClass } from '../layout/pageShell'
import { AddDocumentDialog } from '../components/documents/AddDocumentDialog'

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)

  async function load() {
    setLoading(true)
    setError('')
    try {
      setDocuments(await fetchDocuments())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load documents')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const totalSize = useMemo(
    () => documents.reduce((sum, doc) => sum + (doc.byte_size ?? 0), 0),
    [documents],
  )

  async function handleSaved(message: string) {
    setStatus(message)
    setError('')
    await load()
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-gray-50 text-gray-800 dark:bg-[#18181A] dark:text-gray-200">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-[22px] font-semibold tracking-[-0.02em] text-gray-900 dark:text-gray-100">Documents</h1>
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              <span className="tabular-nums">{documents.length}</span>{' '}
              {documents.length === 1 ? 'doc' : 'docs'}
              <span className="px-1.5 text-gray-300 dark:text-gray-700">·</span>
              <span className="tabular-nums">{formatBytes(totalSize)}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-3.5 py-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97]"
          >
            <Plus size={15} />
            Add document
          </button>
        </header>

        {error && (
          <div className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
            {error}
          </div>
        )}
        {status && !error && (
          <div className="mb-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-700 dark:border-emerald-900/70 dark:bg-emerald-950/30 dark:text-emerald-200">
            {status}
          </div>
        )}

        <section
          className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-800 dark:bg-[#1C1C1E]"
          style={{ borderWidth: '0.5px' }}
        >
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[12px] text-gray-500 dark:text-gray-500">
              Uploaded files become Life Items, Knowledge Chunks, and Connections.
            </p>
          </div>

          {loading && documents.length === 0 ? (
            <div className="py-10 text-center text-[14px] text-gray-400">Loading documents…</div>
          ) : documents.length === 0 ? (
            <EmptyDocumentsState onAdd={() => setDialogOpen(true)} />
          ) : (
            <div className="divide-y divide-gray-100 dark:divide-gray-800">
              {documents.map((document) => <DocumentRow key={document.id} document={document} onChanged={() => void load()} />)}
            </div>
          )}
        </section>
      </div>

      <AddDocumentDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSaved={(message) => void handleSaved(message)}
      />
    </div>
  )
}

function EmptyDocumentsState({
  onAdd,
}: {
  onAdd: () => void
}) {
  return (
    <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/60 px-6 py-12 text-center dark:border-gray-700 dark:bg-[#18181A]">
      <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-white text-gray-400 dark:bg-gray-800 dark:text-gray-500">
        <FileText size={18} />
      </div>
      <h3 className="text-[15px] font-medium text-gray-800 dark:text-gray-200">No documents yet</h3>
      <p className="mx-auto mt-1.5 max-w-sm text-[13px] leading-6 text-gray-500 dark:text-gray-500">
        Drop a file or paste some text. Orbit chunks it and queues it for connection review.
      </p>
      <button
        type="button"
        onClick={onAdd}
        className="mt-4 inline-flex items-center gap-2 rounded-xl bg-blue-500 px-3.5 py-2 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97]"
      >
        <Plus size={15} />
        Add your first document
      </button>
    </div>
  )
}

function DocumentRow({ document, onChanged }: { document: DocumentItem; onChanged: () => void }) {
  const [renaming, setRenaming] = useState(false)
  const [uniqueName, setUniqueName] = useState(document.unique_name)
  const [editingTag, setEditingTag] = useState(false)
  const [tag, setTag] = useState(document.category_tag)
  const [editingSummary, setEditingSummary] = useState(false)
  const [summary, setSummary] = useState(document.connection_summary)

  useEffect(() => {
    setUniqueName(document.unique_name)
    setTag(document.category_tag)
    setSummary(document.connection_summary)
  }, [document.unique_name, document.category_tag, document.connection_summary])

  async function saveName() {
    const next = uniqueName.trim()
    if (next && next !== document.unique_name) {
      await renameDocument(document.id, next)
      onChanged()
    }
    setRenaming(false)
  }

  async function saveAnnotation(next: { category_tag?: string; connection_summary?: string }) {
    await updateDocumentAnnotation(document.id, next)
    onChanged()
  }

  return (
    <article className="group flex items-start gap-3 px-2 py-3 transition-colors hover:bg-gray-50/60 dark:hover:bg-[#202024]">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-300">
        <FileText size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-medium leading-snug text-gray-800 dark:text-gray-200">
          {document.original_name}
        </span>
        <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-2 text-[12px] text-gray-400">
          {renaming ? (
            <input
              autoFocus
              value={uniqueName}
              onChange={(event) => setUniqueName(event.target.value)}
              onBlur={() => void saveName()}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void saveName()
                if (event.key === 'Escape') {
                  setUniqueName(document.unique_name)
                  setRenaming(false)
                }
              }}
              className="min-w-44 bg-transparent text-blue-500 outline-none"
            />
          ) : (
            <button
              type="button"
              onClick={() => setRenaming(true)}
              className="inline-flex max-w-full items-center gap-1 text-blue-500 transition-colors hover:text-blue-600"
            >
              <span className="truncate">{document.unique_name}</span>
              <Pencil size={11} />
            </button>
          )}
          <span className="tabular-nums">{formatBytes(document.byte_size)}</span>
          <AsyncStatusPills
            connection={document.connection_status}
            chunk={document.chunk_status}
            bucketUpdate={document.bucket_update_status}
          />
        </div>
        <div className="mt-2 flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1.5">
          {editingTag ? (
            <input
              autoFocus
              value={tag}
              onChange={(event) => setTag(event.target.value)}
              onBlur={() => {
                setEditingTag(false)
                void saveAnnotation({ category_tag: tag.trim() })
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  setEditingTag(false)
                  void saveAnnotation({ category_tag: tag.trim() })
                }
                if (event.key === 'Escape') {
                  setTag(document.category_tag)
                  setEditingTag(false)
                }
              }}
              className="h-6 w-36 rounded-full border border-blue-200 bg-blue-50 px-2.5 text-[11px] font-medium text-blue-700 outline-none dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-200"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingTag(true)}
              className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] font-medium text-blue-600 transition-colors hover:bg-blue-100 dark:bg-blue-950/30 dark:text-blue-200 dark:hover:bg-blue-950/50"
            >
              {document.category_tag || 'uncategorized'}
            </button>
          )}
          <span className="mt-1 text-[11px] text-gray-300 dark:text-gray-700">·</span>
          {editingSummary ? (
            <input
              autoFocus
              value={summary}
              onChange={(event) => setSummary(event.target.value)}
              onBlur={() => {
                setEditingSummary(false)
                void saveAnnotation({ connection_summary: summary.trim() })
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  setEditingSummary(false)
                  void saveAnnotation({ connection_summary: summary.trim() })
                }
                if (event.key === 'Escape') {
                  setSummary(document.connection_summary)
                  setEditingSummary(false)
                }
              }}
              className="min-w-[16rem] flex-1 bg-transparent text-[12px] text-gray-500 outline-none dark:text-gray-400"
            />
          ) : (
            <button
              type="button"
              onClick={() => setEditingSummary(true)}
              className="min-w-0 flex-1 text-left text-[12px] leading-5 text-gray-500 transition-colors hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
            >
              {document.connection_summary || 'No connection summary yet.'}
            </button>
          )}
        </div>
      </div>
    </article>
  )
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
