import { useState } from 'react'
import { type Skill } from '../../lib/api'
import { Badge } from '../ui/Badge'
import MarkdownContent from '../MarkdownContent'
import { Bot, Lock } from 'lucide-react'
import AgentBadge from './AgentBadge'
import {
  SOURCE_CONFIG,
  SOURCE_BADGE,
  NEUTRAL_CHIP,
  AGENT_BTN_ACTIVE,
  AGENT_BTN_INACTIVE,
} from './constants'
import zh from '../../i18n/locales/zh'

export default function SkillDetail({
  skill,
  t,
  onPublish,
  onUnpublish,
}: {
  skill: Skill
  t: typeof zh
  onPublish: (targetAgents?: string[]) => void
  onUnpublish: (targetAgents?: string[]) => void
}) {
  const [selectedAgents, setSelectedAgents] = useState<string[]>(
    skill.agents.filter((a) => skill.publishable_to.includes(a)),
  )
  const cfg = SOURCE_CONFIG[skill.source] || SOURCE_CONFIG.project
  const SourceIcon = cfg.icon
  const sourceLabel =
    (t.skills[`source_${skill.source}` as keyof typeof t.skills] as string) || skill.source

  const toggleAgent = (agent: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agent) ? prev.filter((a) => a !== agent) : [...prev, agent],
    )
  }

  const handleApplyAgents = async () => {
    const toAdd = selectedAgents.filter((a) => !skill.agents.includes(a))
    const toRemove = skill.agents.filter((a) => !selectedAgents.includes(a))
    if (toAdd.length > 0) await onPublish(toAdd)
    if (toRemove.length > 0) await onUnpublish(toRemove)
  }

  const hasChanges =
    selectedAgents.length !== skill.agents.length ||
    selectedAgents.some((a) => !skill.agents.includes(a))

  return (
    <>
      {/* 头部徽标 */}
      <div className="flex items-center gap-2 flex-wrap mb-5">
        <div
          className={`flex items-center justify-center w-9 h-9 rounded-lg ${cfg.bg} ${cfg.color} shrink-0`}
        >
          {skill.builtin ? (
            <Lock size={18} aria-hidden="true" />
          ) : (
            <SourceIcon size={18} aria-hidden="true" />
          )}
        </div>
        <Badge className={SOURCE_BADGE[skill.source] || NEUTRAL_CHIP}>{sourceLabel}</Badge>
        {skill.builtin && (
          <span className="flex items-center gap-0.5 text-xs font-medium text-[var(--text-tertiary)]">
            <Lock size={12} aria-hidden="true" />
            {t.skills.builtin}
          </span>
        )}
        {skill.provided_by && skill.provided_by.length > 0 && !skill.builtin && (
          <span className="flex items-center gap-0.5 text-xs font-medium text-[var(--text-tertiary)]">
            <Bot size={12} aria-hidden="true" />
            {skill.provided_by
              .map((a) => (t.skills[`source_${a}` as keyof typeof t.skills] as string) || a)
              .join(', ')}
          </span>
        )}
      </div>

      {/* Agent 发布状态 */}
      {skill.editable && (
        <div className="mb-5">
          <h4 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-2.5">
            {t.skills.publishTo}
          </h4>
          {skill.publishable_to.length === 0 ? (
            <p className="text-xs text-[var(--text-tertiary)]">{t.skills.noPublishTarget}</p>
          ) : (
            <>
              <div className="flex gap-2 flex-wrap">
                {skill.publishable_to.map((agent) => (
                  <button
                    key={agent}
                    aria-pressed={selectedAgents.includes(agent)}
                    onClick={() => toggleAgent(agent)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 active:scale-[0.97] ${
                      selectedAgents.includes(agent) ? AGENT_BTN_ACTIVE : AGENT_BTN_INACTIVE
                    }`}
                  >
                    <Bot size={12} className="inline mr-1" aria-hidden="true" />
                    {agent}
                  </button>
                ))}
              </div>
              {hasChanges ? (
                <div className="mt-2 flex gap-2">
                  <button
                    aria-label={t.skills.applyChanges}
                    onClick={handleApplyAgents}
                    className="px-2 py-1 text-xs text-[var(--text-primary)] hover:bg-surface-inset rounded-lg select-none transition-all duration-150 active:scale-[0.97] font-medium"
                  >
                    {t.skills.applyChanges}
                  </button>
                </div>
              ) : null}
            </>
          )}
        </div>
      )}

      {/* 当前启用的 Agent（内置技能只读展示） */}
      {!skill.editable && skill.agents.length > 0 && (
        <div className="mb-5">
          <h4 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-2.5">
            {t.skills.enabledFor}
          </h4>
          <div className="flex gap-1 flex-wrap">
            {skill.agents.map((agent) => (
              <AgentBadge key={agent} agent={agent} />
            ))}
          </div>
        </div>
      )}

      {/* 技能指令内容 */}
      <div className="mb-5">
        <h4 className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-2.5">
          {t.skills.bodyLabel}
        </h4>
        <div className="bg-surface-elevated/30 rounded-lg p-5">
          <MarkdownContent content={skill.body} />
        </div>
      </div>

      {/* 元信息 */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mb-5">
        <div>
          <span className="text-[var(--text-tertiary)] text-xs font-medium uppercase tracking-[0.08em]">
            {t.skills.sourceLabel}
          </span>
          <p className="text-xs text-[var(--text-primary)] font-medium">{sourceLabel}</p>
        </div>
        <div>
          <span className="text-[var(--text-tertiary)] text-xs font-medium uppercase tracking-[0.08em]">
            {t.skills.typeLabel}
          </span>
          <p className="text-xs text-[var(--text-primary)] font-medium">
            {skill.builtin ? t.skills.builtin : t.skills.custom}
          </p>
        </div>
        {skill.provided_by && skill.provided_by.length > 0 && (
          <div>
            <span className="text-[var(--text-tertiary)] text-xs font-medium uppercase tracking-[0.08em]">
              {t.skills.providedBy}
            </span>
            <p className="text-xs text-[var(--text-primary)] font-medium">
              {skill.provided_by
                .map((a) => (t.skills[`source_${a}` as keyof typeof t.skills] as string) || a)
                .join(', ')}
            </p>
          </div>
        )}
        <div className={skill.provided_by && skill.provided_by.length > 0 ? '' : 'col-span-2'}>
          <span className="text-[var(--text-tertiary)] text-xs font-medium uppercase tracking-[0.08em]">
            {t.skills.pathLabel}
          </span>
          <p className="text-[var(--text-secondary)] text-xs font-mono font-medium break-all bg-surface-elevated/30 px-1.5 py-0.5 rounded-lg ring-1 ring-subtle">
            {skill.path}
          </p>
        </div>
      </div>
    </>
  )
}
