import type { ReactNode } from 'react'

interface SectionGroupProps {
  accentFrom: string
  accentTo: string
  title: ReactNode
  children: ReactNode
}

export default function SectionGroup({ accentFrom, accentTo, title, children }: SectionGroupProps) {
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <div className={`w-1 h-5 bg-gradient-to-b ${accentFrom} ${accentTo} rounded-full`} />
        <h2 className="text-sm font-semibold text-[var(--text-primary)] uppercase tracking-[0.08em]">
          {title}
        </h2>
      </div>
      {children}
    </section>
  )
}
