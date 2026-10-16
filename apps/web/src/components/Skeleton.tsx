export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`shimmer rounded-lg ${className}`} />
}

const CARD_CLASS = 'glass rounded-lg'

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className={`${CARD_CLASS} px-4 py-3 space-y-2`}>
          <Skeleton className="h-3.5 w-2/3" />
          <div className="flex gap-1.5">
            <Skeleton className="h-4 w-10 rounded-lg" />
            <Skeleton className="h-4 w-12 rounded-lg" />
            <Skeleton className="h-4 w-14 rounded-lg" />
          </div>
          <div className="flex items-center gap-2">
            <Skeleton className="h-1.5 w-1.5 rounded-full" />
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-8" />
          </div>
        </div>
      ))}
    </div>
  )
}

export function TabContentSkeleton() {
  return (
    <div className="mt-4 pt-3 border-t border-[var(--border-default)] space-y-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-3 w-3 rounded-full" />
          <Skeleton className={`h-3 ${i % 2 === 0 ? 'w-2/3' : 'w-1/2'}`} />
        </div>
      ))}
    </div>
  )
}

const COL_CLASSES: Record<number, string> = {
  2: 'md:grid-cols-2',
  3: 'md:grid-cols-3',
  4: 'md:grid-cols-4',
  5: 'md:grid-cols-5',
  6: 'md:grid-cols-6',
}

export function CardSkeleton({ cols = 4 }: { cols?: number }) {
  const colClass = COL_CLASSES[cols] ?? 'md:grid-cols-4'
  return (
    <div className={`grid grid-cols-2 ${colClass} gap-3 md:gap-4`}>
      {Array.from({ length: cols }).map((_, i) => (
        <div key={i} className={`${CARD_CLASS} p-4 space-y-2`}>
          <Skeleton className="h-6 w-10" />
          <Skeleton className="h-2.5 w-16" />
        </div>
      ))}
    </div>
  )
}
