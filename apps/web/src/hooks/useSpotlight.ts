import { useRef, useEffect } from 'react'

export function useSpotlight<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return

    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (mq.matches) return

    let lastRippleTime = 0

    // 800ms 节流：快速滑动时避免涟漪元素堆积
    const spawnRipple = (x: number, y: number) => {
      const ripple = document.createElement('div')
      ripple.className = 'spotlight-ripple'
      ripple.style.left = `${x}px`
      ripple.style.top = `${y}px`
      el.appendChild(ripple)
      ripple.addEventListener('animationend', () => ripple.remove())
    }

    const handleMove = (e: MouseEvent) => {
      const now = Date.now()
      if (now - lastRippleTime < 800) return
      lastRippleTime = now

      const rect = el.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      spawnRipple(x, y)
    }

    el.addEventListener('mousemove', handleMove, { passive: true })

    return () => {
      el.removeEventListener('mousemove', handleMove)
    }
  }, [])

  return ref
}
