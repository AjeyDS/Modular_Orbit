import { cn } from './cn'

interface SkeletonProps {
  className?: string
}

export function Skeleton({ className }: SkeletonProps) {
  return <div className={cn('animate-pulse rounded-control bg-surface-inset', className)} />
}

interface SkeletonRowsProps {
  count?: number
  className?: string
}

export function SkeletonRows({ count = 3, className }: SkeletonRowsProps) {
  return (
    <div className={cn('space-y-1', className)}>
      {Array.from({ length: count }).map((_, index) => (
        <Skeleton key={index} className="h-14 w-full" />
      ))}
    </div>
  )
}
