import { useId, type KeyboardEvent, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { cn } from './cn'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
  icon?: ReactNode
}

interface SegmentedControlProps<T extends string> {
  options: SegmentedOption<T>[]
  value: T
  onChange: (v: T) => void
  ariaLabel?: string
  size?: 'sm' | 'md'
}

const sizeStyles = {
  sm: 'px-3 py-1 text-label',
  md: 'px-3 py-1.5 text-label',
} as const

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  size = 'md',
}: SegmentedControlProps<T>) {
  const layoutId = useId()

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const nextIndex = (index + delta + options.length) % options.length
    const next = options[nextIndex]
    if (next) onChange(next.value)
  }

  return (
    <div role="tablist" aria-label={ariaLabel} className="inline-flex items-center rounded-control bg-surface-inset p-0.5">
      {options.map((option, index) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => handleKeyDown(event, index)}
            className={cn(
              'relative inline-flex items-center gap-1.5 rounded-[8px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50',
              sizeStyles[size],
              active ? 'text-fg' : 'text-fg-secondary',
            )}
          >
            {active && (
              <motion.div
                layoutId={`segmented-${layoutId}`}
                className="absolute inset-0 rounded-[8px] bg-surface shadow-sm"
                transition={{ duration: 0.2, ease: [0.23, 1, 0.32, 1] }}
              />
            )}
            <span className="relative z-10 inline-flex items-center gap-1.5">
              {option.icon}
              {option.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}

interface FilterTabsProps {
  options: string[]
  value: string
  onChange: (v: string) => void
  ariaLabel?: string
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function FilterTabs({ options, value, onChange, ariaLabel }: FilterTabsProps) {
  return (
    <SegmentedControl
      options={options.map((option) => ({ value: option, label: capitalize(option) }))}
      value={value}
      onChange={onChange}
      ariaLabel={ariaLabel}
    />
  )
}
