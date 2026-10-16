import { useEffect, useId, useState } from 'react'

interface RingProgressProps {
  value: number
  size?: number
  strokeWidth?: number
  color?: string
  label?: string
}

export default function RingProgress({
  value,
  size = 48,
  strokeWidth = 4,
  color = 'var(--brand-rgb)',
  label,
}: RingProgressProps) {
  // useId 生成含冒号的 ID，SVG url() 引用需去掉
  const gradientId = useId().replace(/:/g, '')
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  const clamped = Math.max(0, Math.min(1, value))
  const targetOffset = circumference * (1 - clamped)

  // 初始绘制动画：从 0 画到目标值
  const [offset, setOffset] = useState(circumference)
  useEffect(() => {
    const raf = requestAnimationFrame(() => setOffset(targetOffset))
    return () => cancelAnimationFrame(raf)
  }, [targetOffset])

  // 品牌默认时用 deep 色收尾，自定义色时以透明度渐隐
  const toStop = color === 'var(--brand-rgb)' ? 'rgb(var(--brand-deep-rgb))' : `rgb(${color} / 0.7)`

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={`rgb(${color})`} />
            <stop offset="100%" stopColor={toStop} />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          className="text-[var(--border-default)]"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-[stroke-dashoffset] duration-700 ease-out"
        />
      </svg>
      {label && (
        <span className="absolute text-2xs font-semibold tabular-nums text-[var(--text-primary)]">
          {label}
        </span>
      )}
    </div>
  )
}
