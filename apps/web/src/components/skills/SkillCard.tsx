import { useState, memo } from 'react'
import { motion } from 'framer-motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Skill } from '../../lib/api'
import { spring, duration } from '../../lib/motion'
import { Button } from '../ui/Button'
import { Badge } from '../ui/Badge'
import { Pencil, Trash2, Check, Lock, PackagePlus } from 'lucide-react'
import AgentBadge from './AgentBadge'
import { SOURCE_CONFIG, SOURCE_BADGE, NEUTRAL_CHIP } from './constants'

const SkillCard = memo(function SkillCard({
  skill: s,
  idx = 0,
  onOpen,
  onEdit,
  onDelete,
  onImport,
  onUnpublish,
}: {
  skill: Skill
  idx?: number
  onOpen: (skill: Skill) => void
  onEdit: (skill: Skill) => void
  onDelete: (name: string) => void
  onImport: (skill: Skill) => void
  onUnpublish: (skill: Skill, agent: string) => void
}) {
  const { t } = useTranslation()
  const cfg = SOURCE_CONFIG[s.source] || SOURCE_CONFIG.project
  const SourceIcon = cfg.icon
  const sourceLabel =
    (t.skills[`source_${s.source}` as keyof typeof t.skills] as string) || s.source
  const [confirmDel, setConfirmDel] = useState(false)

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...spring.snappy, delay: Math.min(idx * 0.04, 0.3) }}
      onClick={() => onOpen(s)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onOpen(s)
        }
      }}
      role="button"
      tabIndex={0}
      className="group relative px-4 py-3 hover-lift hover:bg-brand-badge-bg cursor-pointer transition-all duration-150"
    >
      <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-full bg-brand-400 opacity-40 transition-opacity duration-150" />
      <div className="flex items-start gap-3.5 group-hover:translate-x-0.5 transition-transform duration-150">
        {/* 图标头像 */}
        <motion.div
          className={`flex items-center justify-center w-8 h-8 rounded-lg ${cfg.bg} ${cfg.color} shrink-0 ring-1 ${cfg.ring}`}
          whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
          transition={{ duration: duration.modal }}
        >
          {s.builtin ? (
            <Lock size={16} aria-hidden="true" />
          ) : (
            <SourceIcon size={16} aria-hidden="true" />
          )}
        </motion.div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <h3 className="font-semibold text-[var(--text-primary)] text-sm tracking-[-0.01em] truncate min-w-0 leading-snug">
              {s.name}
            </h3>
            <Badge className={SOURCE_BADGE[s.source] || NEUTRAL_CHIP}>{sourceLabel}</Badge>
            {s.builtin && (
              <span className="flex items-center gap-0.5 text-xs font-medium text-[var(--text-tertiary)]">
                <Lock size={11} aria-hidden="true" />
                {t.skills.builtin}
              </span>
            )}
          </div>
          <p className="text-xs text-[var(--text-secondary)] mt-1.5 line-clamp-2 leading-relaxed">
            {s.description || '-'}
          </p>
          {s.agents.length > 0 && (
            <div className="flex items-center gap-1 mt-2 flex-wrap">
              {s.agents.map((agent) => (
                <AgentBadge
                  key={agent}
                  agent={agent}
                  onRemove={s.editable ? () => onUnpublish(s, agent) : undefined}
                  removeTitle={
                    s.editable
                      ? (t.skills.unpublishAgent as string).replace('{{agent}}', agent)
                      : undefined
                  }
                />
              ))}
            </div>
          )}
        </div>
        {s.editable && (
          <div
            className="flex gap-0.5 shrink-0 md:opacity-0 group-hover:md:opacity-100 hover:!opacity-100 focus-within:!opacity-100 transition-opacity"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              onClick={() => onEdit(s)}
              variant="icon"
              size="sm"
              className="min-w-[36px] min-h-[36px]"
              title={t.skills.edit}
              aria-label={t.skills.edit}
            >
              <Pencil size={14} aria-hidden="true" />
            </Button>
            <Button
              onClick={(e) => {
                e.stopPropagation()
                if (confirmDel) {
                  onDelete(s.name)
                } else {
                  setConfirmDel(true)
                }
              }}
              variant="icon"
              size="sm"
              className={`min-w-[36px] min-h-[36px] ${confirmDel ? 'text-danger-fg bg-danger/10' : 'hover:text-danger-fg hover:bg-danger/10'}`}
              title={confirmDel ? t.common.confirm : t.skills.delete}
              aria-label={confirmDel ? t.common.confirm : t.skills.delete}
            >
              {confirmDel ? (
                <Check size={14} aria-hidden="true" />
              ) : (
                <Trash2 size={14} aria-hidden="true" />
              )}
            </Button>
          </div>
        )}
        {!s.editable && (
          <div
            className="shrink-0 md:opacity-0 group-hover:md:opacity-100 hover:!opacity-100 focus-within:!opacity-100 transition-opacity"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              onClick={() => onImport(s)}
              variant="icon"
              size="sm"
              className="min-w-[36px] min-h-[36px]"
              title={t.skills.importBuiltin}
              aria-label={t.skills.importBuiltin}
            >
              <PackagePlus size={14} aria-hidden="true" />
            </Button>
          </div>
        )}
      </div>
    </motion.div>
  )
})

export default SkillCard
