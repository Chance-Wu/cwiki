import { useEffect, useRef } from 'react'

// 欠阻尼弹簧缓动：模拟真实回弹，比线性/立方缓动更有"弹性数字"质感
function springEase(t: number, damping = 0.65, frequency = 3.5): number {
  const omega = 2 * Math.PI * frequency
  const omegaD = omega * Math.sqrt(1 - damping * damping)
  return 1 - Math.exp(-damping * omega * t) * Math.cos(omegaD * t)
}

export function useCountUp(target: number, duration = 600, decimals = 0, delay = 0) {
  const ref = useRef<HTMLSpanElement>(null)
  const prevTargetRef = useRef(0)
  const rafRef = useRef<number>(0)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const startValue = prevTargetRef.current
    prevTargetRef.current = target
    // 从上一次目标值（而非 0）起算，数字更新时做增量过渡
    let startTime: number | null = null

    const animate = (time: number) => {
      if (startTime === null) startTime = time
      const elapsed = time - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = springEase(progress)
      const current = startValue + (target - startValue) * eased
      el.textContent = decimals > 0 ? current.toFixed(decimals) : String(Math.round(current))
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(animate)
      }
    }

    let rafId: number
    let timeoutId: ReturnType<typeof setTimeout> | undefined
    if (delay > 0) {
      timeoutId = setTimeout(() => {
        rafId = requestAnimationFrame(animate)
        rafRef.current = rafId
      }, delay)
    } else {
      rafId = requestAnimationFrame(animate)
      rafRef.current = rafId
    }
    return () => {
      if (timeoutId !== undefined) clearTimeout(timeoutId)
      cancelAnimationFrame(rafRef.current)
    }
  }, [target, duration, decimals, delay])

  return ref
}
