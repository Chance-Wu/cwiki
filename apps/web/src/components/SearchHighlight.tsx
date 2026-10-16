import { memo } from 'react'

interface SearchHighlightProps {
  text: string
  query: string
  className?: string
}

export default memo(function SearchHighlight({
  text,
  query,
  className = '',
}: SearchHighlightProps) {
  if (!query.trim()) return <span className={className}>{text}</span>

  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escaped})`, 'gi')
  const parts = text.split(regex)

  return (
    <span className={className}>
      {parts.map((part, i) =>
        regex.test(part) ? (
          <mark key={i} className="bg-warning/20 text-inherit rounded px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  )
})
