import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowLeft, Check, Loader2, Sparkles, X } from 'lucide-react'
import {
  createPlan,
  parsePlanText,
  type ParsedPlanDraft,
  type ParsedPlanNode,
} from '../../lib/api'
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
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)

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
    setConfirmingDiscard(false)
  }

  function requestClose() {
    if (step === 'review' && previewNodes.length > 0) {
      setConfirmingDiscard(true)
      return
    }
    onClose()
    resetAll()
  }

  function discardAndClose() {
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
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function handleKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.stopPropagation()
        requestClose()
      }
    }
    document.addEventListener('keydown', handleKey)

    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKey)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, step, previewNodes.length])

  useEffect(() => {
    if (!open) return
    const raf = requestAnimationFrame(() => {
      if (step === 'paste') textareaRef.current?.focus()
      else titleInputRef.current?.focus()
    })
    return () => cancelAnimationFrame(raf)
  }, [open, step])

  if (typeof document === 'undefined') return null

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="import-dialog"
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
            layout
            initial={{ opacity: 0, scale: 0.97, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: 8 }}
            transition={{ duration: 0.18, ease: easeOut, layout: { duration: 0.28, ease: easeOut } }}
            className="relative flex max-h-[min(90vh,820px)] w-full flex-col overflow-hidden rounded-[1.25rem] border border-gray-200 bg-white text-gray-800 shadow-[0_24px_64px_-24px_rgba(23,27,22,0.28)] dark:border-gray-800 dark:bg-[#1C1C1E] dark:text-gray-200"
            style={{ maxWidth: step === 'paste' ? 600 : 880, borderWidth: '0.5px' }}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="flex items-center justify-between gap-3 border-b border-gray-100 px-5 py-4 dark:border-gray-800">
              <div className="flex items-center gap-3">
                <h2 className="text-[16px] font-semibold tracking-[-0.02em]">Import a plan</h2>
                <span className="text-[12px] text-gray-500 dark:text-gray-500">
                  <span className={step === 'paste' ? 'text-gray-900 dark:text-gray-200' : ''}>Paste</span>
                  <span className="px-1.5">·</span>
                  <span className={step === 'review' ? 'text-gray-900 dark:text-gray-200' : ''}>Review</span>
                </span>
              </div>
              <button
                type="button"
                onClick={requestClose}
                aria-label="Close"
                className="rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:text-gray-500 dark:hover:bg-gray-800 dark:hover:text-gray-200"
              >
                <X size={16} />
              </button>
            </header>

            <AnimatePresence mode="wait" initial={false}>
              {step === 'paste' ? (
                <motion.div
                  key="paste"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.16, ease: easeOut }}
                  className="flex min-h-0 flex-1 flex-col"
                >
                  <div className="flex items-center justify-between gap-3 px-5 pt-4">
                    <p className="text-[13px] leading-6 text-gray-500 dark:text-gray-400">
                      Paste a plan from ChatGPT, Claude, Gemini, or notes. Headings, phases, and nested bullets all work.
                    </p>
                    <button
                      type="button"
                      onClick={() => {
                        setRawPlanText(samplePlan)
                        setLocalError('')
                      }}
                      className="shrink-0 rounded-full border border-gray-200 px-3 py-1 text-[12px] font-medium text-gray-600 transition-[background-color,transform] duration-150 ease-out hover:bg-gray-100 active:scale-[0.97] dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
                    >
                      Use sample
                    </button>
                  </div>

                  <div className="min-h-0 flex-1 px-5 py-4">
                    <textarea
                      ref={textareaRef}
                      value={rawPlanText}
                      onChange={(event) => setRawPlanText(event.target.value)}
                      spellCheck={false}
                      placeholder="Paste a plan here. Headings, phases, weeks, domains, bullets, and nested bullets are all welcome."
                      className="h-[20rem] w-full resize-none rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 font-mono text-[13px] leading-7 text-gray-800 outline-none transition-colors placeholder:text-gray-400 focus:border-gray-300 dark:border-gray-800 dark:bg-[#18181A] dark:text-gray-200 dark:placeholder:text-gray-600 dark:focus:border-gray-500"
                    />
                  </div>

                  {localError && (
                    <p className="mx-5 mb-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
                      {localError}
                    </p>
                  )}

                  <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 px-5 py-4 dark:border-gray-800">
                    <p className="text-[12px] text-gray-500 dark:text-gray-500">
                      {rawPlanText.trim() ? `${rawPlanText.trim().length.toLocaleString()} characters` : 'Nothing pasted yet'}
                    </p>
                    <button
                      type="button"
                      disabled={!rawPlanText.trim() || parsing}
                      onClick={() => void handleParse()}
                      className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-blue-600 active:scale-[0.97] disabled:cursor-default disabled:opacity-40"
                    >
                      {parsing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                      {parsing ? 'Parsing…' : 'Parse plan →'}
                    </button>
                  </footer>
                </motion.div>
              ) : (
                <motion.div
                  key="review"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.16, ease: easeOut }}
                  className="flex min-h-0 flex-1 flex-col"
                >
                  <div className="grid gap-3 border-b border-gray-100 px-5 py-4 sm:grid-cols-[1fr_10rem] dark:border-gray-800">
                    <input
                      ref={titleInputRef}
                      value={previewTitle}
                      onChange={(event) => setPreviewTitle(event.target.value)}
                      placeholder="Plan title"
                      className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-[14px] font-semibold outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#18181A] dark:focus:border-gray-500"
                    />
                    <select
                      value={previewCategory}
                      onChange={(event) => setPreviewCategory(event.target.value as PlanCategory)}
                      className="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-[13px] outline-none transition-colors focus:border-gray-300 dark:border-gray-700 dark:bg-[#18181A] dark:focus:border-gray-500"
                    >
                      <option value="work">work</option>
                      <option value="learn">learn</option>
                      <option value="personal">personal</option>
                    </select>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 border-b border-gray-100 px-5 py-2.5 text-[12px] text-gray-500 dark:border-gray-800 dark:text-gray-500">
                    <span>{stats.nodes} nodes</span>
                    <span>·</span>
                    <span>{stats.leaves} leaves</span>
                    <span>·</span>
                    <span>{stats.depth} levels</span>
                  </div>

                  <div className="min-h-0 flex-1 overflow-y-auto bg-gray-50 p-4 dark:bg-[#18181A]">
                    <EditablePlanTree nodes={previewNodes} onChange={setPreviewNodes} />
                  </div>

                  {localError && (
                    <p className="mx-5 mt-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 dark:border-red-900/70 dark:bg-red-950/30 dark:text-red-200">
                      {localError}
                    </p>
                  )}

                  <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 px-5 py-4 dark:border-gray-800">
                    <button
                      type="button"
                      onClick={() => {
                        setStep('paste')
                        setLocalError('')
                      }}
                      className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-[13px] text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
                    >
                      <ArrowLeft size={14} />
                      Back to paste
                    </button>
                    <button
                      type="button"
                      disabled={!previewTitle.trim() || previewNodes.length === 0 || importing}
                      onClick={() => void handleConfirm()}
                      className="inline-flex items-center gap-2 rounded-xl bg-gray-900 px-4 py-2.5 text-[13px] font-semibold text-white transition-[background-color,transform] duration-150 ease-out hover:bg-gray-800 active:scale-[0.97] disabled:opacity-40 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
                    >
                      {importing ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                      {importing ? 'Saving…' : 'Save plan'}
                    </button>
                  </footer>
                </motion.div>
              )}
            </AnimatePresence>

            <AnimatePresence>
              {confirmingDiscard && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 8 }}
                  transition={{ duration: 0.16, ease: easeOut }}
                  className="absolute inset-x-0 bottom-0 flex items-center justify-between gap-3 border-t border-gray-100 bg-white/95 px-5 py-3 text-[13px] backdrop-blur dark:border-gray-800 dark:bg-[#1C1C1E]/95"
                >
                  <span className="text-gray-700 dark:text-gray-300">Discard the parsed plan?</span>
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
