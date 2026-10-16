import { memo } from 'react'
import { Link } from 'react-router-dom'
import type { LucideIcon } from 'lucide-react'
import { motion, useTransform, type Transition } from 'framer-motion'
import { duration } from '../lib/motion'
import Sparkline from './Sparkline'
import { useCountUp } from '../hooks/useCountUp'
import { useTilt3d } from '../hooks/useTilt3d'

export type StatTone = 'brand' | 'success' | 'warning' | 'danger' | 'info'

const TONES: Record<StatTone, { chip: string; ring: string; line: string; glow: string }> = {
  brand: {
    chip: 'bg-brand-100/70 text-brand-fg border border-brand-300/35 shadow-warm-xs',
    ring: 'ring-brand-300/30',
    line: 'var(--brand-rgb)',
    glow: 'rgba(var(--brand-rgb), 0.25)',
  },
  success: {
    chip: 'bg-success/22 border border-success/35 text-success-fg shadow-warm-xs',
    ring: 'ring-success/30',
    line: 'var(--success-rgb)',
    glow: 'rgba(var(--success-rgb), 0.25)',
  },
  warning: {
    chip: 'bg-warning/22 border border-warning/35 text-warning-fg shadow-warm-xs',
    ring: 'ring-warning/30',
    line: 'var(--warning-rgb)',
    glow: 'rgba(var(--warning-rgb), 0.25)',
  },
  danger: {
    chip: 'bg-danger/22 border border-danger/35 text-danger-fg shadow-warm-xs',
    ring: 'ring-danger/30',
    line: 'var(--danger-rgb)',
    glow: 'rgba(var(--danger-rgb), 0.25)',
  },
  info: {
    chip: 'bg-info/22 border border-info/35 text-info-fg shadow-warm-xs',
    ring: 'ring-info/30',
    line: 'var(--info-rgb)',
    glow: 'rgba(var(--info-rgb), 0.25)',
  },
}

const ENTRANCE: Transition = {
  type: 'spring',
  stiffness: 280,
  damping: 12,
  mass: 0.8,
}

interface StatCardProps {
  label: string
  value: number
  Icon: LucideIcon
  tone?: StatTone
  trend?: number[]
  subValue?: string
  to?: string
  index?: number
}

const StatCard = memo(function StatCard({
  label,
  value,
  Icon,
  tone = 'brand',
  trend,
  subValue,
  to,
  index = 0,
}: StatCardProps) {
  const animatedRef = useCountUp(value)
  const isEmpty = value === 0
  const t = TONES[tone]
  const { ref: tiltRef, rotateX, rotateY, glareX, glareY, glareOpacity } = useTilt3d(18)

  // 光泽 gradient — 跟随鼠标位置
  const glareBg = useTransform(
    [glareX, glareY, glareOpacity],
    ([gx, gy, go]) =>
      `radial-gradient(circle at ${gx as number}% ${gy as number}%, rgba(255,255,255,${go as number}), transparent 60%)`,
  )

  // hover 光泽扫过
  const shimmerX = useTransform(glareX, [0, 100], [-120, 120])

  const card = (
    <motion.div
      ref={tiltRef}
      style={{
        perspective: '800px',
        rotateX,
        rotateY,
        transformStyle: 'preserve-3d',
      }}
      initial={{ opacity: 0, y: 80, scale: 0.5, rotate: -6 }}
      animate={{ opacity: 1, y: 0, scale: 1, rotate: 0 }}
      transition={{ ...ENTRANCE, delay: index * 0.12 }}
      className="h-full"
    >
      <motion.div
        className={`glass-card group relative h-full overflow-hidden rounded-2xl p-5 md:p-6 transition-shadow duration-500 ${to ? 'cursor-pointer' : ''}`}
        whileHover={{
          y: -4,
          transition: { type: 'spring', stiffness: 400, damping: 20 },
        }}
        style={{
          boxShadow: `0 0 0 0px ${t.glow}`,
        }}
        animate={{}}
        whileTap={{ scale: 0.98 }}
      >
        {/* hover 边框发光 */}
        <motion.div
          className="pointer-events-none absolute inset-0 z-[5] rounded-2xl"
          style={{
            boxShadow: `inset 0 0 0 1px transparent`,
          }}
          whileHover={{
            boxShadow: `inset 0 0 0 1.5px ${t.glow}, 0 8px 32px -8px ${t.glow}`,
            transition: { duration: duration.stagger },
          }}
        />

        {/* 光泽叠加层 */}
        <motion.div
          className="pointer-events-none absolute inset-0 z-10 rounded-2xl"
          style={{ background: glareBg }}
        />

        {/* hover 光泽扫过条 */}
        <motion.div className="pointer-events-none absolute inset-0 z-[6] rounded-2xl overflow-hidden opacity-0 group-hover:opacity-100 transition-opacity duration-300">
          <motion.div
            className="absolute top-0 h-full w-20 -skew-x-12"
            style={{
              x: shimmerX,
              background: `linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent)`,
            }}
          />
        </motion.div>

        {/* 背景装饰 — 呼吸脉冲 */}
        <motion.div
          className="absolute -top-10 -right-10 h-32 w-32 rounded-full opacity-[0.10] pointer-events-none"
          style={{ background: `radial-gradient(circle, rgb(${t.line}), transparent 70%)` }}
          animate={{
            scale: [1, 1.2, 1],
            opacity: [0.1, 0.18, 0.1],
          }}
          transition={{
            duration: 3,
            repeat: Infinity,
            ease: 'easeInOut',
            delay: index * 0.5,
          }}
        />

        <div className="relative z-20 flex h-full flex-col">
          <div className="mb-5 flex items-center justify-between">
            <div className="flex min-w-0 items-center gap-3">
              <motion.div
                className={`flex items-center justify-center w-9 h-9 rounded-xl shrink-0 ring-1 ${t.ring} ${t.chip}`}
                whileHover={{
                  rotate: [0, -12, 12, -6, 6, 0],
                  scale: 1.15,
                }}
                animate={{
                  y: [0, -2, 0],
                }}
                transition={{
                  y: { duration: 2.5, repeat: Infinity, ease: 'easeInOut', delay: index * 0.3 },
                  rotate: { duration: duration.reveal, ease: 'easeOut' },
                  scale: { duration: duration.reveal, ease: 'easeOut' },
                }}
              >
                <Icon size={17} strokeWidth={2} aria-hidden="true" />
              </motion.div>
              <p className="text-xs text-[var(--text-tertiary)] font-medium truncate tracking-wide">
                {label}
              </p>
            </div>
            {trend && trend.length >= 2 && (
              <Sparkline data={trend} width={48} height={16} color={t.line} />
            )}
          </div>

          <div className="mt-auto">
            <motion.p
              className={`leading-none tabular-nums ${
                isEmpty
                  ? 'text-3xl md:text-4xl text-[var(--text-tertiary)]/50 font-semibold'
                  : 'text-5xl md:text-6xl font-bold tracking-tight text-[var(--text-primary)]'
              }`}
              initial={{ opacity: 0, scale: 0.5 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{
                type: 'spring',
                stiffness: 200,
                damping: 10,
                delay: 0.3 + index * 0.12,
              }}
            >
              <span ref={animatedRef}>0</span>
            </motion.p>

            {/* 数值脉冲光环 */}
            {!isEmpty && (
              <motion.div
                className="absolute inset-0 rounded-2xl pointer-events-none"
                initial={{ opacity: 0.6, scale: 0.95 }}
                animate={{ opacity: 0, scale: 1.05 }}
                transition={{
                  duration: 1.2,
                  delay: 0.5 + index * 0.12,
                  ease: 'easeOut',
                }}
                style={{
                  boxShadow: `0 0 40px 10px ${t.glow}`,
                }}
              />
            )}

            {subValue && (
              <motion.p
                className="text-xs text-[var(--text-tertiary)] mt-3 font-medium"
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.6 + index * 0.12, duration: duration.medium }}
              >
                {subValue}
              </motion.p>
            )}
          </div>
        </div>
      </motion.div>
    </motion.div>
  )

  if (to) {
    return (
      <Link to={to} className="block h-full no-underline">
        {card}
      </Link>
    )
  }

  return card
})

export default StatCard
