import { useState } from 'react'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Skill } from '../../lib/api'
import { useImportSkill } from '../../hooks/useSkills'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'

export default function ImportForm({
  onSuccess,
  onCancel,
}: {
  onSuccess: (skill: Skill) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [path, setPath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const importMutation = useImportSkill()

  const handleSubmit = async () => {
    if (!path.trim()) return
    setError(null)
    try {
      const skill = await importMutation.mutateAsync(path.trim())
      onSuccess(skill)
    } catch (e) {
      setError(e instanceof Error ? e.message : t.skills.importFailed)
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
            {t.skills.importPath}
          </label>
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder={t.skills.importPathPlaceholder}
            autoFocus
          />
          <p className="text-xs text-[var(--text-tertiary)] mt-1 font-medium">
            {t.skills.importHint}
          </p>
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-[var(--border-default)]">
        <Button onClick={onCancel} variant="secondary">
          {t.common.cancel}
        </Button>
        <Button onClick={handleSubmit} disabled={importMutation.isPending || !path.trim()}>
          {t.skills.import}
        </Button>
      </div>
    </>
  )
}
