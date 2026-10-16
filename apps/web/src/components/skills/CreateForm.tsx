import { useState } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Skill } from '../../lib/api'
import { useCreateSkill } from '../../hooks/useSkills'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'
import { Bot } from 'lucide-react'
import { AGENT_BTN_ACTIVE, AGENT_BTN_INACTIVE } from './constants'

export default function CreateForm({
  onSuccess,
  onCancel,
  submitLabel,
  agents,
}: {
  onSuccess: (skill: Skill) => void
  onCancel: () => void
  submitLabel: string
  agents: string[]
}) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [body, setBody] = useState('')
  const [selectedAgents, setSelectedAgents] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateSkill()

  const toggleAgent = (agent: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agent) ? prev.filter((a) => a !== agent) : [...prev, agent],
    )
  }

  const handleSubmit = async () => {
    if (!name.trim() || !description.trim() || !body.trim()) return
    setError(null)
    try {
      const skill = await createMutation.mutateAsync({
        name: name.trim(),
        description: description.trim(),
        body: body.trim(),
        agents: selectedAgents,
      })
      onSuccess(skill)
    } catch (e) {
      setError(e instanceof Error ? e.message : t.skills.saveFailed)
    }
  }

  return (
    <>
      {error && (
        <div className="mb-3 p-2.5 bg-danger/18 text-danger-fg text-xs rounded-lg font-medium border border-danger/25">
          {error}
        </div>
      )}
      <div className="space-y-3">
        <div>
          <label className="text-xs font-medium text-[var(--text-primary)] mb-1 block">
            {t.skills.name}
          </label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t.skills.namePlaceholder}
            autoFocus
          />
        </div>
        <div>
          <label className="text-xs font-medium text-[var(--text-primary)] mb-1 block">
            {t.skills.description}
          </label>
          <Input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t.skills.descPlaceholder}
          />
        </div>
        <div>
          <label className="text-xs font-medium text-[var(--text-primary)] mb-1 block">
            {t.skills.body}
          </label>
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder={t.skills.bodyPlaceholder}
            rows={8}
            className="font-mono"
          />
        </div>
        {agents.length > 0 && (
          <div>
            <label className="text-xs font-medium text-[var(--text-primary)] mb-1 block">
              {t.skills.publishTo}
            </label>
            <div className="flex gap-2 flex-wrap">
              {agents.map((agent) => (
                <button
                  key={agent}
                  type="button"
                  aria-pressed={selectedAgents.includes(agent)}
                  onClick={() => toggleAgent(agent)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-150 ${
                    selectedAgents.includes(agent) ? AGENT_BTN_ACTIVE : AGENT_BTN_INACTIVE
                  }`}
                >
                  <Bot size={12} className="inline mr-1" aria-hidden="true" />
                  {agent}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-[var(--border-default)]">
        <Button onClick={onCancel} variant="secondary">
          {t.common.cancel}
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={createMutation.isPending || !name.trim() || !description.trim() || !body.trim()}
        >
          {submitLabel}
        </Button>
      </div>
    </>
  )
}
