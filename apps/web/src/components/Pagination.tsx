import { useCallback, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTranslation, translate } from '../i18n/I18nProvider'
import { Button } from './ui/Button'
import { spring, duration } from '../lib/motion'

interface PaginationProps {
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  pageSizeOptions?: number[]
  scrollTargetRef?: React.RefObject<HTMLElement | null>
}

const PAGE_SIZES = [10, 15, 20, 30, 50]

export default function Pagination({
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  pageSizeOptions = PAGE_SIZES,
  scrollTargetRef,
}: PaginationProps) {
  const { t } = useTranslation()
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const currentPage = Math.min(page, totalPages)
  const prevPageRef = useRef(currentPage)
  const pageDisplayRef = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    const el = pageDisplayRef.current
    if (!el) return
    const from = prevPageRef.current
    const to = currentPage
    prevPageRef.current = currentPage
    if (from === to) return

    let startTime: number | null = null
    const animDuration = 200
    const animate = (time: number) => {
      if (startTime === null) startTime = time
      const elapsed = time - startTime
      const progress = Math.min(elapsed / animDuration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      const current = Math.round(from + (to - from) * eased)
      el.textContent = String(current)
      if (progress < 1) requestAnimationFrame(animate)
    }
    requestAnimationFrame(animate)
  }, [currentPage])

  const scrollToTop = useCallback(() => {
    if (scrollTargetRef?.current) {
      scrollTargetRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [scrollTargetRef])

  const handlePageChange = useCallback(
    (newPage: number) => {
      onPageChange(newPage)
      scrollToTop()
    },
    [onPageChange, scrollToTop],
  )

  if (total <= pageSize) return null

  return (
    <motion.div
      className="flex flex-col sm:flex-row items-center justify-between gap-2.5 mt-4 pt-3"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: duration.normal }}
    >
      <div className="flex items-center gap-2.5 text-xs text-[var(--text-tertiary)] tabular-nums">
        <span>{translate(t.pagination.total, { n: total })}</span>
        <span className="flex items-center gap-0.5">
          {translate(t.pagination.pageInfo, { current: '', total: totalPages }).replace(
            /^(\s*)/,
            '$1',
          )}
          <AnimatePresence mode="popLayout">
            <motion.span
              key={currentPage}
              className="inline-flex items-center justify-center min-w-[1.5ch] h-5 px-1 rounded-lg bg-brand-200/45 border border-brand-300/40 text-brand-fg font-medium text-xs shadow-warm-xs"
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              transition={spring.snappy}
            >
              {currentPage}
            </motion.span>
          </AnimatePresence>
          <span>/</span>
          <span>{totalPages}</span>
        </span>
        <select
          value={pageSize}
          onChange={(e) => {
            onPageSizeChange(Number(e.target.value))
            handlePageChange(1)
          }}
          className="py-1 px-1.5 text-xs rounded-lg bg-surface-card border border-[var(--glass-border)] shadow-warm-xs text-[var(--text-secondary)] cursor-pointer hover:border-[var(--glass-border-hover)] transition-[border-color,box-shadow] duration-200 ease-out focus-visible:outline-none focus-visible:border-brand-400 focus-visible:ring-2 focus-visible:ring-brand-200/30"
        >
          {pageSizeOptions.map((s) => (
            <option key={s} value={s}>
              {translate(t.pagination.perPage, { n: s })}
            </option>
          ))}
        </select>
      </div>
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="xs"
          onClick={() => handlePageChange(1)}
          disabled={currentPage === 1}
        >
          {t.pagination.first}
        </Button>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => handlePageChange(currentPage - 1)}
          disabled={currentPage === 1}
        >
          {t.pagination.prev}
        </Button>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => handlePageChange(currentPage + 1)}
          disabled={currentPage === totalPages}
        >
          {t.pagination.next}
        </Button>
        <Button
          variant="ghost"
          size="xs"
          onClick={() => handlePageChange(totalPages)}
          disabled={currentPage === totalPages}
        >
          {t.pagination.last}
        </Button>
      </div>
    </motion.div>
  )
}
