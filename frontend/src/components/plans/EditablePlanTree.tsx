import { useState } from 'react'
import { ChevronDown, ChevronRight, GripVertical, Trash2 } from 'lucide-react'
import type { ParsedPlanNode } from '../../lib/api'

export function EditablePlanTree({ nodes, onChange }: { nodes: ParsedPlanNode[]; onChange: (nodes: ParsedPlanNode[]) => void }) {
  return (
    <div className="space-y-2">
      {nodes.map((node, index) => (
        <EditablePlanNodeCard
          key={`${index}-${node.title}`}
          node={node}
          depth={0}
          onChange={(next) => onChange(nodes.map((item, itemIndex) => (itemIndex === index ? next : item)))}
          onDelete={() => onChange(nodes.filter((_, itemIndex) => itemIndex !== index))}
        />
      ))}
      <button
        type="button"
        onClick={() => onChange([...nodes, emptyNode('New step')])}
        className="rounded-xl border border-dashed border-[#d9c9b4] px-3 py-2 text-[12px] font-medium text-[#8d6b41] transition-colors hover:bg-white dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
      >
        + Add top-level node
      </button>
    </div>
  )
}

function EditablePlanNodeCard({
  node,
  depth,
  onChange,
  onDelete,
}: {
  node: ParsedPlanNode
  depth: number
  onChange: (node: ParsedPlanNode) => void
  onDelete: () => void
}) {
  const [collapsed, setCollapsed] = useState(false)
  const children = node.children || []
  const canAddChild = depth < 3

  return (
    <div className="space-y-2" style={{ marginLeft: depth ? 18 : 0 }}>
      <div className="rounded-2xl border border-[#e7dccb] bg-white p-3 shadow-[0_1px_0_rgba(45,35,22,0.03)] dark:border-gray-800 dark:bg-[#1C1C1E]">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="mt-1 rounded-md p-0.5 text-[#b4a48f] transition-colors hover:bg-[#f6eadb] hover:text-[#7a5b36] dark:hover:bg-gray-800"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
          <GripVertical size={14} className="mt-1.5 text-[#d2c3b0]" />
          <div className="min-w-0 flex-1">
            <input
              value={node.title}
              onChange={(event) => onChange({ ...node, title: event.target.value })}
              className="w-full bg-transparent text-[13px] font-semibold text-[#342d24] outline-none placeholder:text-[#b7a58f] dark:text-gray-100"
              placeholder="Untitled node"
            />
            <textarea
              value={node.description ?? ''}
              onChange={(event) => onChange({ ...node, description: event.target.value || null })}
              rows={node.description ? 2 : 1}
              className="mt-1 w-full resize-none rounded-lg bg-[#fbf6ee] px-2 py-1.5 text-[12px] leading-5 text-[#756a5d] outline-none placeholder:text-[#b9aa98] focus:bg-[#f8efe2] dark:bg-[#18181A] dark:text-gray-400 dark:focus:bg-gray-800"
              placeholder="Add description or notes"
            />
          </div>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-lg p-1.5 text-[#c6b8a5] transition-colors hover:bg-red-50 hover:text-red-500 dark:hover:bg-red-950/30"
          >
            <Trash2 size={14} />
          </button>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 pl-12">
          {canAddChild && (
            <button
              type="button"
              onClick={() => onChange({ ...node, children: [...children, emptyNode('New child step')] })}
              className="text-[11px] font-medium text-[#8d6b41] transition-colors hover:text-[#5c4328] dark:text-gray-400"
            >
              + Add child
            </button>
          )}
          <span className="text-[11px] text-[#b4a48f]">{children.length} child{children.length === 1 ? '' : 'ren'}</span>
        </div>
      </div>

      {!collapsed && children.length > 0 && (
        <div className="border-l border-[#e1d1bd] pl-3 dark:border-gray-800">
          {children.map((child, index) => (
            <EditablePlanNodeCard
              key={`${depth}-${index}-${child.title}`}
              node={child}
              depth={depth + 1}
              onChange={(next) => onChange({ ...node, children: children.map((item, itemIndex) => (itemIndex === index ? next : item)) })}
              onDelete={() => onChange({ ...node, children: children.filter((_, itemIndex) => itemIndex !== index) })}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function emptyNode(title: string): ParsedPlanNode {
  return { title, description: null, metadata: {}, children: [] }
}

export function countNodes(nodes: ParsedPlanNode[]): number {
  return nodes.reduce((sum, node) => sum + 1 + countNodes(node.children || []), 0)
}

export function countLeaves(nodes: ParsedPlanNode[]): number {
  return nodes.reduce((sum, node) => sum + ((node.children || []).length > 0 ? countLeaves(node.children || []) : 1), 0)
}

export function maxDepth(nodes: ParsedPlanNode[], depth = 1): number {
  if (nodes.length === 0) return 0
  return Math.max(...nodes.map((node) => ((node.children || []).length > 0 ? maxDepth(node.children || [], depth + 1) : depth)))
}
