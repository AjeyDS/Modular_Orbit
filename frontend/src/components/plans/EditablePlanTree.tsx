import { useState } from 'react'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import type { ParsedPlanNode } from '../../lib/api'

export function EditablePlanTree({ nodes, onChange }: { nodes: ParsedPlanNode[]; onChange: (nodes: ParsedPlanNode[]) => void }) {
  return (
    <div className="space-y-0.5">
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
        className="rounded-control border border-dashed border-hairline px-3 py-2 text-caption font-medium text-fg-secondary transition-colors hover:bg-surface-inset hover:text-fg"
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
    <div className={depth > 0 ? 'ml-4 border-l border-hairline pl-3' : ''}>
      <div className="group rounded-control px-2 py-2 transition-colors hover:bg-surface-inset">
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => setCollapsed((value) => !value)}
            className="mt-1 rounded-md text-fg-tertiary transition-colors hover:text-fg"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
          </button>
          <div className="min-w-0 flex-1">
            <input
              value={node.title}
              onChange={(event) => onChange({ ...node, title: event.target.value })}
              className="w-full bg-transparent text-label font-medium text-fg outline-none placeholder:text-fg-tertiary"
              placeholder="Untitled node"
            />
            <textarea
              value={node.description ?? ''}
              onChange={(event) => onChange({ ...node, description: event.target.value || null })}
              rows={node.description ? 2 : 1}
              className="mt-1 w-full resize-none rounded-control bg-surface-inset px-2 py-1.5 text-caption leading-5 text-fg-secondary outline-none placeholder:text-fg-tertiary focus:bg-surface-inset"
              placeholder="Add description or notes"
            />
          </div>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md p-1.5 text-fg-tertiary transition-colors hover:text-danger"
          >
            <Trash2 size={14} />
          </button>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2 pl-6">
          {canAddChild && (
            <button
              type="button"
              onClick={() => onChange({ ...node, children: [...children, emptyNode('New child step')] })}
              className="text-caption font-medium text-accent transition-colors hover:text-accent-hover"
            >
              + Add child
            </button>
          )}
          <span className="text-caption text-fg-tertiary">{children.length} child{children.length === 1 ? '' : 'ren'}</span>
        </div>
      </div>

      {!collapsed && children.length > 0 && (
        <div className="mt-0.5 space-y-0.5">
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
