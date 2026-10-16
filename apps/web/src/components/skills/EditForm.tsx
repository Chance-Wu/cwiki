import { useState } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Skill } from '../../lib/api'
import { useUpdateSkill } from '../../hooks/useSkills'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'

export default function EditForm({
  skill,
  onSuccess,
  onCancel,
}: {
  skill: Skill
  onSuccess: (skill: Skill) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [description, setDescription] = useState(skill.description)
  const [body, setBody] = useState(skill.body)
  const [error, setError] = useState<string | null>(null)
  const updateMutation = useUpdateSkill()

  const handleSubmit = async () => {
    if (!description.trim() || !body.trim()) return
    setError(null)
    try {
      const updated = await updateMutation.mutateAsync({
        name: skill.name,
        description: description.trim(),
        body: body.trim(),
      })
      onSuccess(updated)
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
            {t.skills.description}
          </label>
          <Input value={description} onChange={(e) => setDescription(e.target.value)} autoFocus />
        </div>
        <div>
          <label className="text-xs font-medium text-[var(--text-primary)] mb-1 block">
            {t.skills.body}
          </label>
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={12}
            className="font-mono"
          />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-[var(--border-default)]">
        <Button onClick={onCancel} variant="secondary">
          {t.common.cancel}
        </Button>
        <Button
          onClick={handleSubmit}
          disabled={updateMutation.isPending || !description.trim() || !body.trim()}
        >
          {t.common.save}
        </Button>
      </div>
    </>
  )
}
