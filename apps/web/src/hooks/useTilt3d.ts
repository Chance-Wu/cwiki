import { useRef, useEffect, useCallback } from 'react'
import { useMotionValue, useSpring, type MotionValue } from 'framer-motion'

interface Tilt3dResult {
  ref: React.RefObject<HTMLDivElement>
  rotateX: MotionValue<number>
  rotateY: MotionValue<number>
  glareX: MotionValue<number>
  glareY: MotionValue<number>
  glareOpacity: MotionValue<number>
  scale: MotionValue<number>
}

/**
 * 3D 透视倾斜 hook — 鼠标位置驱动卡片 rotateX/Y + 光泽叠加
 * 尊重 prefers-reduced-motion，开启时返回零值 motion value
 */
export function useTilt3d(maxTilt = 18): Tilt3dResult {
  const ref = useRef<HTMLDivElement>(null)

  // 目标值（鼠标驱动）
  const targetRX = useMotionValue(0)
  const targetRY = useMotionValue(0)
  const targetGX = useMotionValue(50)
  const targetGY = useMotionValue(50)
  const targetOpacity = useMotionValue(0)
  const targetScale = useMotionValue(1)

  // Spring 平滑跟随目标值
  const rotateX = useSpring(targetRX, { stiffness: 300, damping: 20 })
  const rotateY = useSpring(targetRY, { stiffness: 300, damping: 20 })
  const glareX = useSpring(targetGX, { stiffness: 200, damping: 25 })
  const glareY = useSpring(targetGY, { stiffness: 200, damping: 25 })
  const glareOpacity = useSpring(targetOpacity, { stiffness: 200, damping: 25 })
  const scale = useSpring(targetScale, { stiffness: 400, damping: 25 })

  const handleMove = useCallback(
    (e: MouseEvent) => {
      const el = ref.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const px = (e.clientX - rect.left) / rect.width
      const py = (e.clientY - rect.top) / rect.height

      targetRY.set((px - 0.5) * maxTilt * 2)
      targetRX.set((0.5 - py) * maxTilt * 2)
      targetGX.set(px * 100)
      targetGY.set(py * 100)
      targetOpacity.set(0.28)
      targetScale.set(1.06)
    },
    [maxTilt, targetRX, targetRY, targetGX, targetGY, targetOpacity, targetScale],
  )

  const handleLeave = useCallback(() => {
    targetRX.set(0)
    targetRY.set(0)
    targetOpacity.set(0)
    targetScale.set(1)
  }, [targetRX, targetRY, targetOpacity, targetScale])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (mq.matches) return

    el.addEventListener('mousemove', handleMove, { passive: true })
    el.addEventListener('mouseleave', handleLeave)
    return () => {
      el.removeEventListener('mousemove', handleMove)
      el.removeEventListener('mouseleave', handleLeave)
    }
  }, [handleMove, handleLeave])

  return { ref, rotateX, rotateY, glareX, glareY, glareOpacity, scale }
}
