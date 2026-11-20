// 配置卡片及其内部控件：数值输入、图标动画、搜索高亮。
import { useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { duration, spring } from '../../lib/motion'
import { translate, useTranslation } from '../../i18n/I18nProvider'
import { Card } from '../ui/Card'
import { Input } from '../ui/Input'
import { Switch } from '../ui/Switch'
import { fieldMatches, UNIT_KEYS } from './configSchema'
import type { ConfigSection, EditableField, SectionTheme } from './configSchema'

function NumberInput({
  value,
  onChange,
  step,
  min,
  max,
  rangeLabel,
}: {
  value: number
  onChange: (v: number) => void
  step?: string
  min?: number
  max?: number
  rangeLabel?: string
}) {
  const [local, setLocal] = useState(String(value))
  const lastReported = useRef(value)
  if (value !== lastReported.current) {
    lastReported.current = value
    setLocal(String(value))
  }
  const numeric = Number(local)
  const invalid =
    local.trim() !== '' &&
    !Number.isNaN(numeric) &&
    ((min !== undefined && numeric < min) || (max !== undefined && numeric > max))

  return (
    <Input
      type="text"
      inputMode="decimal"
      step={step}
      aria-invalid={invalid}
      data-config-input="true"
      title={invalid ? rangeLabel : undefined}
      value={local}
      onChange={(e) => {
        const raw = e.target.value
        if (raw === '' || raw === '-' || raw === '.') {
          setLocal(raw)
          return
        }
        if (!isNaN(Number(raw))) {
          setLocal(raw)
          const n = Number(raw)
          lastReported.current = n
          onChange(n)
        }
      }}
      onBlur={() => {
        const n = Number(local)
        if (isNaN(n)) setLocal(String(value))
        else setLocal(String(n))
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
      }}
      className={`w-20 px-2.5 py-1.5 text-right text-xs font-medium tabular-nums ${
        invalid ? 'border-danger/60 focus-visible:border-danger focus-visible:ring-danger/20' : ''
      }`}
    />
  )
}

function AnimatedIcon({ theme }: { theme: SectionTheme }) {
  const Icon = theme.icon
  return (
    <motion.div
      className={`flex items-center justify-center w-8 h-8 rounded-lg ${theme.iconGradient} shrink-0 ring-1 ${theme.iconRing}`}
      whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
      transition={{ duration: duration.modal }}
    >
      <Icon size={15} className={theme.iconColor} aria-hidden="true" />
    </motion.div>
  )
}

function Highlighted({ text, query }: { text: string; query: string }) {
  const q = query.trim()
  if (!q) return <>{text}</>
  const index = text.toLowerCase().indexOf(q.toLowerCase())
  if (index < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, index)}
      <mark className="rounded bg-warning/30 px-0.5 text-primary">
        {text.slice(index, index + q.length)}
      </mark>
      {text.slice(index + q.length)}
    </>
  )
}

function ConfigCard({
  theme,
  cardTitle,
  subtitle,
  fields,
  columns,
  section,
  localConfig,
  onFieldChange,
  delay,
  searchQuery,
}: {
  theme: SectionTheme
  cardTitle?: string
  subtitle?: string
  fields: EditableField[]
  columns?: 1 | 2
  section: ConfigSection
  localConfig: Record<string, Record<string, unknown>>
  onFieldChange: (section: ConfigSection, key: string, value: boolean | number) => void
  delay: number
  searchQuery: string
}) {
  const { t } = useTranslation()
  const copy = t.config as Record<string, string>
  const titleKey = cardTitle ?? theme.title
  const columnCount = columns ?? (theme.grid ? 2 : 1)
  const visibleFields = searchQuery.trim()
    ? fields.filter((field) => fieldMatches(field, searchQuery, copy))
    : fields
  if (visibleFields.length === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay }}
      className="h-full"
    >
      <Card className="h-full p-4 transition-all duration-150 hover:border-strong hover:shadow-warm-md md:p-5">
        <div className="mb-3 flex items-center gap-2.5">
          <AnimatedIcon theme={theme} />
          <h3 className="text-base font-semibold text-primary">{copy[titleKey] ?? titleKey}</h3>
        </div>
        {subtitle && (
          <p className="mb-4 text-xs font-medium text-tertiary">{copy[subtitle] ?? subtitle}</p>
        )}
        <div
          className={
            columnCount === 2
              ? 'grid grid-cols-1 gap-x-6 gap-y-1 md:grid-cols-2'
              : 'flex flex-col gap-y-1'
          }
        >
          {visibleFields.map((field) => (
            <div
              key={field.key}
              className="flex items-center justify-between rounded-lg px-3 py-2.5 -mx-3 transition-all duration-150 hover:bg-brand-badge-bg"
            >
              <div className="mr-3 min-w-0 flex-1">
                <span className="text-xs font-medium text-primary">
                  <Highlighted text={copy[field.nameKey] ?? field.key} query={searchQuery} />
                </span>
                <p className="text-xs font-medium text-tertiary">
                  <Highlighted text={copy[field.descKey] ?? ''} query={searchQuery} />
                </p>
              </div>
              {field.type === 'boolean' ? (
                <Switch
                  checked={localConfig[section][field.key] as boolean}
                  onCheckedChange={(v) => onFieldChange(section, field.key, v)}
                />
              ) : (
                <div className="flex shrink-0 items-center gap-1.5">
                  <NumberInput
                    value={(localConfig[section][field.key] as number) ?? 0}
                    onChange={(v) => onFieldChange(section, field.key, v)}
                    step={field.step}
                    min={field.min}
                    max={field.max}
                    rangeLabel={
                      field.min !== undefined && field.max !== undefined
                        ? translate(copy.fieldRange, { min: field.min, max: field.max })
                        : undefined
                    }
                  />
                  <span className="w-10 text-right text-[10px] font-medium tabular-nums text-tertiary">
                    {field.unit ? (copy[UNIT_KEYS[field.unit]] ?? '') : ''}
                  </span>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>
    </motion.div>
  )
}

export { ConfigCard }
