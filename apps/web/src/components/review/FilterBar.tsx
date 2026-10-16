import { motion, AnimatePresence } from 'framer-motion'
import { Filter } from 'lucide-react'
import { spring, ease, duration } from '../../lib/motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { Card } from '../ui/Card'
import { typeLabel, TYPE_COLORS, MASTERY_COLORS } from '../../lib/labels'

const PILL_ACTIVE =
  'bg-surface-elevated/60 text-[var(--text-primary)] font-semibold border border-[var(--border-default)]'
const PILL_INACTIVE =
  'text-[var(--text-secondary)] hover:bg-surface-elevated/40 hover:text-[var(--text-primary)]'

const MASTERY_ORDER = ['new', 'learning', 'familiar', 'proficient', 'mastered'] as const

interface FilterBarProps {
  itemCount: number
  filterMastery: string | null
  filterType: string | null
  setFilterMastery: (v: string | null) => void
  setFilterType: (v: string | null) => void
  showFilters: boolean
  setShowFilters: (v: boolean) => void
  hasActiveFilters: boolean
  availableTypes: string[]
}

export const FilterBar = function FilterBar({
  itemCount,
  filterMastery,
  filterType,
  setFilterMastery,
  setFilterType,
  showFilters,
  setShowFilters,
  hasActiveFilters,
  availableTypes,
}: FilterBarProps) {
  const { t } = useTranslation()

  if (itemCount === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay: 0.38 }}
    >
      <Card className="p-4 md:p-5 mb-5">
        <button
          aria-label={t.review.filter}
          aria-expanded={showFilters}
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 select-none ${
            hasActiveFilters ? PILL_ACTIVE : PILL_INACTIVE
          }`}
        >
          <Filter size={14} aria-hidden="true" />
          {t.review.filter}
          {hasActiveFilters && (
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--text-tertiary)]" />
          )}
        </button>

        <AnimatePresence>
          {showFilters && (
            <motion.div
              className="mt-3 space-y-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: duration.modal, ease: ease.out }}
            >
              {/* 掌握度筛选 */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-[var(--text-tertiary)] mr-1">
                  {t.review.filterMastery}:
                </span>
                <button
                  aria-pressed={filterMastery === null}
                  onClick={() => setFilterMastery(null)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-150 select-none active:scale-[0.97] ${
                    filterMastery === null ? PILL_ACTIVE : PILL_INACTIVE
                  }`}
                >
                  {t.common.all}
                </button>
                {MASTERY_ORDER.map((level) => (
                  <button
                    key={level}
                    aria-pressed={filterMastery === level}
                    onClick={() => setFilterMastery(filterMastery === level ? null : level)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-150 select-none active:scale-[0.97] ${
                      filterMastery === level ? MASTERY_COLORS[level] : PILL_INACTIVE
                    }`}
                  >
                    {t.review[`mastery_${level}` as keyof typeof t.review] ?? level}
                  </button>
                ))}
              </div>

              {/* 记忆类型筛选 */}
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-[var(--text-tertiary)] mr-1">
                  {t.review.filterType}:
                </span>
                <button
                  aria-pressed={filterType === null}
                  onClick={() => setFilterType(null)}
                  className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-150 select-none active:scale-[0.97] ${
                    filterType === null ? PILL_ACTIVE : PILL_INACTIVE
                  }`}
                >
                  {t.common.all}
                </button>
                {availableTypes.map((type) => (
                  <button
                    key={type}
                    aria-pressed={filterType === type}
                    onClick={() => setFilterType(filterType === type ? null : type)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all duration-150 select-none active:scale-[0.97] ${
                      filterType === type
                        ? (TYPE_COLORS[type] ??
                          'bg-surface-inset text-[var(--text-secondary)] border border-[var(--border-default)] shadow-warm-xs')
                        : PILL_INACTIVE
                    }`}
                  >
                    {typeLabel(t.common, type)}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>
    </motion.div>
  )
}
