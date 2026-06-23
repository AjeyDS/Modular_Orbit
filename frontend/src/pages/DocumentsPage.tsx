import { useEffect, useMemo, useState } from 'react'
import { FileText, Plus } from 'lucide-react'
import {
  fetchDocuments,
  renameDocument,
  updateDocumentAnnotation,
  type DocumentItem,
} from '../lib/api'
import { AsyncStatusPills } from '../components/status'
import {
  CollectionRow,
  CollectionView,
  EditableTitle,
  EmptyState,
  useToast,
} from '../components/ui'
import { pageContentClass } from '../layout/pageShell'
import { AddDocumentDialog } from '../components/documents/AddDocumentDialog'

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dialogOpen, setDialogOpen] = useState(false)
  const { toast } = useToast()

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

  // After a successful add, refresh the list. The server derives unique_name,
  // chunk/connection status, and annotations, so a targeted refresh is the
  // accurate way to surface the new rows.
  async function handleSaved(message: string) {
    setStatus(message)
    setError('')
    await load()
  }

  // Optimistic rename: patch the row locally, persist in the background, and
  // reconcile via load() on failure so there's no full-list refetch flash.
  function handleRename(id: string, uniqueName: string) {
    setDocuments((current) =>
      current.map((doc) => (doc.id === id ? { ...doc, unique_name: uniqueName } : doc)),
    )
    void renameDocument(id, uniqueName).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to rename document', tone: 'danger' })
      void load()
    })
  }

  // Optimistic annotation edit (category tag / connection summary): patch local
  // state immediately, then persist; reload on error.
  function handleAnnotate(id: string, patch: { category_tag?: string; connection_summary?: string }) {
    setDocuments((current) =>
      current.map((doc) => (doc.id === id ? { ...doc, ...patch } : doc)),
    )
    void updateDocumentAnnotation(id, patch).catch((err) => {
      toast({ message: err instanceof Error ? err.message : 'Unable to update document', tone: 'danger' })
      void load()
    })
  }

  return (
    <div className="min-h-[calc(100vh-3rem)] bg-bg text-fg">
      <div className={`${pageContentClass} py-7`}>
        <header className="mb-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-2">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1 className="text-title font-semibold tracking-[-0.02em] text-fg">Documents</h1>
            <p className="text-caption text-fg-secondary">
              <span className="tabular-nums">{documents.length}</span>{' '}
              {documents.length === 1 ? 'doc' : 'docs'}
              <span className="px-1.5 text-fg-tertiary">·</span>
              <span className="tabular-nums">{formatBytes(totalSize)}</span>
            </p>
          </div>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="inline-flex items-center gap-2 rounded-control bg-accent px-3.5 py-2 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97]"
          >
            <Plus size={15} />
            Add document
          </button>
        </header>

        {error && (
          <div className="mb-3 rounded-control border border-danger/30 bg-danger/10 px-4 py-3 text-label text-danger">
            {error}
          </div>
        )}
        {status && !error && (
          <div className="mb-3 rounded-control border border-success/30 bg-success/10 px-4 py-3 text-label text-success">
            {status}
          </div>
        )}

        <CollectionView
          divided
          loading={loading && documents.length === 0}
          isEmpty={documents.length === 0}
          empty={
            <EmptyState
              icon={<FileText size={18} />}
              title="No documents yet"
              body="Drop a file or paste some text. Orbit chunks it and queues it for connection review."
              action={
                <button
                  type="button"
                  onClick={() => setDialogOpen(true)}
                  className="inline-flex items-center gap-2 rounded-control bg-accent px-3.5 py-2 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97]"
                >
                  <Plus size={15} />
                  Add your first document
                </button>
              }
            />
          }
        >
          {documents.map((document) => (
            <DocumentRow
              key={document.id}
              document={document}
              onRename={handleRename}
              onAnnotate={handleAnnotate}
            />
          ))}
        </CollectionView>
      </div>

      <AddDocumentDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSaved={(message) => void handleSaved(message)}
      />
    </div>
  )
}

function DocumentRow({
  document,
  onRename,
  onAnnotate,
}: {
  document: DocumentItem
  onRename: (id: string, uniqueName: string) => void
  onAnnotate: (id: string, patch: { category_tag?: string; connection_summary?: string }) => void
}) {
  return (
    <CollectionRow variant="plain">
      <div className="flex items-start gap-3 px-2 py-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-surface-inset text-fg-tertiary">
          <FileText size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <span className="block truncate text-body font-medium leading-snug text-fg">
            {document.original_name}
          </span>
          <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-2 text-caption text-fg-tertiary">
            <EditableTitle
              value={document.unique_name}
              onSave={(next) => onRename(document.id, next)}
              className="inline-block max-w-full truncate text-accent transition-colors hover:text-accent-hover"
            />
            <span className="tabular-nums">{formatBytes(document.byte_size)}</span>
            <AsyncStatusPills
              connection={document.connection_status}
              chunk={document.chunk_status}
              bucketUpdate={document.bucket_update_status}
            />
          </div>
          <div className="mt-2 flex min-w-0 flex-wrap items-start gap-x-2 gap-y-1.5">
            <CategoryTagEdit
              value={document.category_tag}
              onSave={(next) => onAnnotate(document.id, { category_tag: next })}
            />
            <span className="mt-1 text-caption text-fg-tertiary">·</span>
            <ConnectionSummaryEdit
              value={document.connection_summary}
              onSave={(next) => onAnnotate(document.id, { connection_summary: next })}
            />
          </div>
        </div>
      </div>
    </CollectionRow>
  )
}

// Inline-editable category tag rendered as a Pill-styled control. Commits on
// blur/Enter, cancels on Escape (resetting the draft).
function CategoryTagEdit({ value, onSave }: { value: string; onSave: (next: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    if (!editing) setDraft(value)
  }, [value, editing])

  function commit() {
    setEditing(false)
    onSave(draft.trim())
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            setDraft(value)
            setEditing(false)
          }
        }}
        className="h-6 w-36 rounded-full bg-surface-inset px-2.5 text-caption font-semibold text-fg-secondary outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
      />
    )
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="inline-flex items-center rounded-full bg-surface-inset px-2.5 py-1 text-caption font-semibold text-fg-secondary transition-colors hover:text-fg"
    >
      {value || 'uncategorized'}
    </button>
  )
}

// Inline-editable connection summary. Commits on blur/Enter, cancels on Escape.
function ConnectionSummaryEdit({ value, onSave }: { value: string; onSave: (next: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  useEffect(() => {
    if (!editing) setDraft(value)
  }, [value, editing])

  function commit() {
    setEditing(false)
    onSave(draft.trim())
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit()
          }
          if (event.key === 'Escape') {
            event.preventDefault()
            setDraft(value)
            setEditing(false)
          }
        }}
        className="min-w-[16rem] flex-1 bg-transparent text-caption text-fg-secondary outline-none"
      />
    )
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="min-w-0 flex-1 text-left text-caption leading-5 text-fg-secondary transition-colors hover:text-fg"
    >
      {value || 'No connection summary yet.'}
    </button>
  )
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
