import { memo, useId } from 'react'

interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  color?: string
  className?: string
}

function SparklineInner({
  data,
  width = 60,
  height = 20,
  color = 'var(--brand-rgb)',
  className = '',
}: SparklineProps) {
  const gradientId = useId().replace(/:/g, '')

  if (data.length < 2) return null

  const max = Math.max(...data)
  const min = Math.min(...data)
  const range = max - min || 1

  const padding = 2
  const chartWidth = width - padding * 2
  const chartHeight = height - padding * 2

  const points = data.map((value, index) => {
    const x = padding + (index / (data.length - 1)) * chartWidth
    const y = padding + chartHeight - ((value - min) / range) * chartHeight
    return { x, y }
  })

  const pathPoints = points.map((p) => `${p.x},${p.y}`).join(' ')
  const lastPoint = points[points.length - 1]

  return (
    <svg
      width={width}
      height={height}
      className={`inline-block ${className}`}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={`rgb(${color} / 0.15)`} />
          <stop offset="100%" stopColor={`rgb(${color} / 0.05)`} />
        </linearGradient>
      </defs>
      <polyline points={pathPoints} fill={`url(#${gradientId})`} stroke="none" />
      <polyline
        points={pathPoints}
        fill="none"
        stroke={`rgb(${color} / 0.8)`}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={lastPoint.x} cy={lastPoint.y} r="2" fill={`rgb(${color} / 0.85)`} />
    </svg>
  )
}

function sparklinePropsEqual(prev: SparklineProps, next: SparklineProps): boolean {
  if (prev.width !== next.width || prev.height !== next.height) return false
  if (prev.color !== next.color || prev.className !== next.className) return false
  if (prev.data.length !== next.data.length) return false
  for (let i = 0; i < prev.data.length; i++) {
    if (prev.data[i] !== next.data[i]) return false
  }
  return true
}

export default memo(SparklineInner, sparklinePropsEqual)
