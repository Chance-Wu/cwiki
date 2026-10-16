import { useEffect, useRef, type ReactNode } from 'react'
import { motion } from 'framer-motion'
import { ease, duration } from '../lib/motion'
import PageHeader from './PageHeader'

interface PageShellProps {
  maxWidth?: string
  /** 内容列宽度。默认跟随 maxWidth；给更窄的值时内容在标题轨内左对齐，保持与 h1 同一条左轨。 */
  contentWidth?: string
  header: ReactNode
  children: ReactNode
}

export default function PageShell({
  maxWidth = 'max-w-6xl',
  contentWidth,
  header,
  children,
}: PageShellProps) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('in-view')
            io.unobserve(entry.target)
          }
        }
      },
      { root: el, rootMargin: '0px 0px -40px 0px', threshold: 0.05 },
    )
    const observe = () => {
      el.querySelectorAll('.stagger-item:not(.in-view)').forEach((item) => io.observe(item))
    }
    observe()
    const mo = new MutationObserver(observe)
    mo.observe(el, { childList: true, subtree: true })
    return () => {
      io.disconnect()
      mo.disconnect()
    }
  }, [])

  return (
    <div className="flex flex-col h-full">
      <motion.div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto scrollbar-thin relative"
        initial={{ opacity: 0, y: 8, scale: 0.995 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: duration.slow, ease: ease.bounce }}
      >
        <PageHeader maxWidth={maxWidth}>{header}</PageHeader>
        <div className={`px-4 sm:px-5 md:px-7 ${maxWidth} mx-auto w-full pb-16 md:pb-6 relative`}>
          {contentWidth ? <div className={`${contentWidth} mr-auto`}>{children}</div> : children}
        </div>
      </motion.div>
    </div>
  )
}
