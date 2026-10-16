import { useState, useCallback } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from '../../i18n/I18nProvider'
import { api } from '../../lib/api'
import { typeLabel } from '../../lib/labels'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'
import { Select } from '../ui/Select'
import { useToast } from '../Toast'

const MEMORY_TYPES = [
  'fact',
  'decision',
  'issue',
  'convention',
  'pattern',
  'procedure',
  'feedback',
  'reference',
  'constraint',
  'lesson',
  'rule',
]

interface MemoryCreateModalProps {
  open: boolean
  onClose: () => void
  onCreated: () => void
  defaultType?: string
}

export default function MemoryCreateModal({
  open,
  onClose,
  onCreated,
  defaultType,
}: MemoryCreateModalProps) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [createType, setCreateType] = useState(
    defaultType && MEMORY_TYPES.includes(defaultType) ? defaultType : 'fact',
  )
  const [createTitle, setCreateTitle] = useState('')
  const [createContent, setCreateContent] = useState('')
  const [createTags, setCreateTags] = useState('')
  const [creating, setCreating] = useState(false)

  const resetAndClose = useCallback(() => {
    onClose()
    setCreateTitle('')
    setCreateContent('')
    setCreateTags('')
  }, [onClose])

  const handleCreate = useCallback(async () => {
    if (!createTitle.trim() || !createContent.trim()) return
    setCreating(true)
    try {
      const tags = createTags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean)
      await api.createMemory({
        title: createTitle.trim(),
        content: createContent.trim(),
        type: createType,
        tags: tags.length > 0 ? tags : undefined,
      })
      onClose()
      setCreateTitle('')
      setCreateContent('')
      setCreateTags('')
      toast(t.memories.createSuccess, 'success')
      onCreated()
    } catch {
      toast(t.memories.createFailed, 'error')
    } finally {
      setCreating(false)
    }
  }, [
    createTitle,
    createContent,
    createType,
    createTags,
    onClose,
    toast,
    t.memories.createSuccess,
    t.memories.createFailed,
    onCreated,
  ])

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) resetAndClose()
      }}
      title={t.memories.createTitle}
      size="lg"
      fixedHeight
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={resetAndClose}>
            {t.common.cancel}
          </Button>
          <Button
            onClick={handleCreate}
            disabled={creating || !createTitle.trim() || !createContent.trim()}
          >
            {creating ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
            {creating ? t.common.loading : t.common.save}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.memories.titleLabel}
          </label>
          <Input
            type="text"
            value={createTitle}
            onChange={(e) => setCreateTitle(e.target.value)}
            placeholder={t.memories.memoryTitle}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.memories.labelType}
          </label>
          <Select
            value={createType}
            onChange={setCreateType}
            options={MEMORY_TYPES.map((type) => ({
              value: type,
              label: typeLabel(t.common, type),
            }))}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.memories.labelTags}
          </label>
          <Input
            type="text"
            value={createTags}
            onChange={(e) => setCreateTags(e.target.value)}
            placeholder={t.memories.tagsPlaceholder}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.memories.contentLabel}
          </label>
          <Textarea
            value={createContent}
            onChange={(e) => setCreateContent(e.target.value)}
            rows={8}
            className="font-mono"
            placeholder={t.memories.contentPlaceholder}
          />
        </div>
      </div>
    </Dialog>
  )
}
