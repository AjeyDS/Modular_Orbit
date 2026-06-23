import { useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, Check, Loader2, Sparkles } from 'lucide-react'
import {
  createPlan,
  parsePlanText,
  type ParsedPlanDraft,
  type ParsedPlanNode,
} from '../../lib/api'
import { Chip, Dialog, SegmentedControl } from '../ui'
import { EditablePlanTree, countLeaves, countNodes, maxDepth } from './EditablePlanTree'

type PlanCategory = 'work' | 'learn' | 'personal'
type Step = 'paste' | 'review'

const samplePlan = `AWS Certified Data Engineer Study Plan

Domain 1: Data Ingestion & Transformation (34%)
- AWS Glue — ETL jobs, crawlers, Data Catalog
- Amazon Kinesis — streams, Firehose, real-time ingestion

Domain 2: Data Store Management (26%)
- Amazon S3 — partitioning and lifecycle policies
- Amazon Redshift — distribution styles, sort keys, Spectrum`

const easeOut = [0.23, 1, 0.32, 1] as const

const categoryOptions = [
  { value: 'work', label: 'work' },
  { value: 'learn', label: 'learn' },
  { value: 'personal', label: 'personal' },
] as const

type Props = {
  open: boolean
  onClose: () => void
  onImported: (message: string) => void
}

export function ImportPlanDialog({ open, onClose, onImported }: Props) {
  const [step, setStep] = useState<Step>('paste')
  const [rawPlanText, setRawPlanText] = useState('')
  const [previewDraft, setPreviewDraft] = useState<ParsedPlanDraft | null>(null)
  const [previewTitle, setPreviewTitle] = useState('')
  const [previewCategory, setPreviewCategory] = useState<PlanCategory>('personal')
  const [previewNodes, setPreviewNodes] = useState<ParsedPlanNode[]>([])
  const [parsing, setParsing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [localError, setLocalError] = useState('')

  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const titleInputRef = useRef<HTMLInputElement | null>(null)

  const stats = useMemo(() => ({
    nodes: countNodes(previewNodes),
    leaves: countLeaves(previewNodes),
    depth: maxDepth(previewNodes),
  }), [previewNodes])

  function resetAll() {
    setStep('paste')
    setRawPlanText('')
    setPreviewDraft(null)
    setPreviewTitle('')
    setPreviewCategory('personal')
    setPreviewNodes([])
    setParsing(false)
    setImporting(false)
    setLocalError('')
  }

  function handleClose() {
    onClose()
    resetAll()
  }

  async function handleParse() {
    if (!rawPlanText.trim() || parsing) return
    setParsing(true)
    setLocalError('')
    try {
      const draft = await parsePlanText(rawPlanText)
      setPreviewDraft(draft)
      setPreviewTitle(draft.title || 'Imported Plan')
      setPreviewCategory(draft.category)
      setPreviewNodes(draft.nodes)
      setStep('review')
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Unable to parse plan')
    } finally {
      setParsing(false)
    }
  }

  async function handleConfirm() {
    if (!previewDraft || !previewTitle.trim() || previewNodes.length === 0 || importing) return
    setImporting(true)
    setLocalError('')
    try {
      await createPlan({
        title: previewTitle.trim(),
        category: previewCategory,
        raw_text: rawPlanText,
        nodes: previewNodes,
      })
      const message = `Plan imported. ${countNodes(previewNodes)} nodes saved as plan steps.`
      onImported(message)
      onClose()
      resetAll()
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : 'Unable to import plan')
    } finally {
      setImporting(false)
    }
  }

  useEffect(() => {
    if (!open) return
    const raf = requestAnimationFrame(() => {
      if (step === 'paste') textareaRef.current?.focus()
      else titleInputRef.current?.focus()
    })
    return () => cancelAnimationFrame(raf)
  }, [open, step])

  const headerExtra = (
    <span className="text-caption text-fg-tertiary">
      <span className={step === 'paste' ? 'text-fg' : ''}>Paste</span>
      <span className="px-1.5">·</span>
      <span className={step === 'review' ? 'text-fg' : ''}>Review</span>
    </span>
  )

  const footer =
    step === 'paste' ? (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-caption text-fg-tertiary">
          {rawPlanText.trim() ? `${rawPlanText.trim().length.toLocaleString()} characters` : 'Nothing pasted yet'}
        </p>
        <button
          type="button"
          disabled={!rawPlanText.trim() || parsing}
          onClick={() => void handleParse()}
          className="inline-flex items-center gap-2 rounded-control bg-accent px-4 py-2.5 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
        >
          {parsing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
          {parsing ? 'Parsing…' : 'Parse plan →'}
        </button>
      </div>
    ) : (
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => {
            setStep('paste')
            setLocalError('')
          }}
          className="inline-flex items-center gap-2 rounded-control px-3 py-2 text-label text-fg-secondary transition-colors hover:bg-surface-inset hover:text-fg"
        >
          <ArrowLeft size={14} />
          Back to paste
        </button>
        <button
          type="button"
          disabled={!previewTitle.trim() || previewNodes.length === 0 || importing}
          onClick={() => void handleConfirm()}
          className="inline-flex items-center gap-2 rounded-control bg-accent px-4 py-2.5 text-label font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-accent-hover active:scale-[0.97] disabled:opacity-40"
        >
          {importing ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
          {importing ? 'Saving…' : 'Save plan'}
        </button>
      </div>
    )

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      title="Import a plan"
      headerExtra={headerExtra}
      dirty={step === 'review' && previewNodes.length > 0}
      discardLabel="Discard the parsed plan?"
      maxWidthClass={step === 'paste' ? 'max-w-xl' : 'max-w-3xl'}
      footer={footer}
    >
      <AnimatePresence mode="wait" initial={false}>
        {step === 'paste' ? (
          <motion.div
            key="paste"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.16, ease: easeOut }}
            className="flex flex-col gap-4"
          >
            <div className="flex items-center justify-between gap-3">
              <p className="text-label leading-6 text-fg-secondary">
                Paste a plan from ChatGPT, Claude, Gemini, or notes. Headings, phases, and nested bullets all work.
              </p>
              <Chip
                className="shrink-0"
                onClick={() => {
                  setRawPlanText(samplePlan)
                  setLocalError('')
                }}
              >
                Use sample
              </Chip>
            </div>

            <textarea
              ref={textareaRef}
              value={rawPlanText}
              onChange={(event) => setRawPlanText(event.target.value)}
              spellCheck={false}
              placeholder="Paste a plan here. Headings, phases, weeks, domains, bullets, and nested bullets are all welcome."
              className="h-[20rem] w-full resize-none rounded-control border border-hairline bg-surface-inset px-4 py-3 font-mono text-label leading-7 text-fg outline-none placeholder:text-fg-tertiary"
            />

            {localError && <p className="text-caption text-danger">{localError}</p>}
          </motion.div>
        ) : (
          <motion.div
            key="review"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.16, ease: easeOut }}
            className="flex flex-col gap-3"
          >
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={titleInputRef}
                value={previewTitle}
                onChange={(event) => setPreviewTitle(event.target.value)}
                placeholder="Plan title"
                className="min-w-0 flex-1 rounded-control border border-hairline bg-surface-inset px-3 py-2.5 text-body font-medium text-fg outline-none placeholder:text-fg-tertiary"
              />
              <SegmentedControl
                options={categoryOptions.map((option) => ({ value: option.value, label: option.label }))}
                value={previewCategory}
                onChange={(value) => setPreviewCategory(value as PlanCategory)}
                size="sm"
                ariaLabel="Plan category"
              />
            </div>

            <div className="flex flex-wrap items-center gap-2 text-caption text-fg-tertiary">
              <span>{stats.nodes} nodes</span>
              <span>·</span>
              <span>{stats.leaves} leaves</span>
              <span>·</span>
              <span>{stats.depth} levels</span>
            </div>

            <div className="rounded-control bg-surface-inset p-3">
              <EditablePlanTree nodes={previewNodes} onChange={setPreviewNodes} />
            </div>

            {localError && <p className="text-caption text-danger">{localError}</p>}
          </motion.div>
        )}
      </AnimatePresence>
    </Dialog>
  )
}
