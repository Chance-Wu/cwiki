import { useEffect, useRef, useState, type ReactNode } from 'react'

interface PageHeaderProps {
  maxWidth?: string
  children: ReactNode
}

export default function PageHeader({ maxWidth = 'max-w-6xl', children }: PageHeaderProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isStuck, setIsStuck] = useState(false)

  useEffect(() => {
    const el = containerRef.current?.parentElement
    if (!el) return
    const onScroll = () => {
      setIsStuck(el.scrollTop > 4)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <div
      ref={containerRef}
      className="sticky top-0 z-10 transition-[background] duration-200"
      style={{
        background: isStuck
          ? 'color-mix(in srgb, var(--surface-bg) 92%, transparent)'
          : 'transparent',
        backdropFilter: isStuck ? 'blur(12px)' : 'blur(4px)',
        WebkitBackdropFilter: isStuck ? 'blur(12px)' : 'blur(4px)',
      }}
    >
      <div className={`${maxWidth} mx-auto w-full px-4 sm:px-5 md:px-7 py-4 md:py-5 relative`}>
        {children}
        <div
          className="absolute bottom-0 left-0 right-0 h-px transition-opacity duration-200 pointer-events-none"
          style={{
            background:
              'linear-gradient(90deg, transparent, var(--border-default) 20%, var(--border-default) 80%, transparent)',
            opacity: isStuck ? 1 : 0,
          }}
        />
      </div>
    </div>
  )
}
