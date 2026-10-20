import { useState, useEffect, useRef } from 'react'
import { X, Plus } from 'lucide-react'
import { api } from '../../lib/api'
import { Badge } from '../ui/Badge'
import { Input } from '../ui/Input'
import { useTranslation } from '../../i18n/I18nProvider'

interface Props {
  tags: string[]
  memoryId: string
  onTagsChanged: () => void
  compact?: boolean
}

export default function TagsEditor({ tags, memoryId, onTagsChanged, compact }: Props) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [currentTags, setCurrentTags] = useState<string[]>(Array.isArray(tags) ? tags : [])
  const [newTag, setNewTag] = useState('')
  const [saving, setSaving] = useState(false)
  const [availableTags, setAvailableTags] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setCurrentTags(Array.isArray(tags) ? tags : [])
  }, [tags])

  useEffect(() => {
    if (editing) {
      api.listTags().then((res) => {
        setAvailableTags(res.tags?.map((t) => t.name) || [])
      }).catch(() => {})
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [editing])

  const handleAddTag = async (tag: string) => {
    const trimmed = tag.trim().toLowerCase()
    if (!trimmed || currentTags.includes(trimmed)) return
    const newTags = [...currentTags, trimmed]
    setCurrentTags(newTags)
    setNewTag('')
    await saveTags(newTags)
  }

  const handleBatchAdd = async (input: string) => {
    const tags = input
      .split(/[,，\s]+/)
      .map((t) => t.trim().toLowerCase())
      .filter((t) => t && !currentTags.includes(t))
    if (tags.length === 0) return
    const newTags = [...currentTags, ...tags]
    setCurrentTags(newTags)
    setNewTag('')
    await saveTags(newTags)
  }

  const handleRemoveTag = async (tag: string) => {
    const newTags = currentTags.filter((t) => t !== tag)
    setCurrentTags(newTags)
    await saveTags(newTags)
  }

  const saveTags = async (newTags: string[]) => {
    setSaving(true)
    try {
      await api.updateMemoryTags(memoryId, newTags)
      onTagsChanged()
    } catch {
      setCurrentTags(tags)
    } finally {
      setSaving(false)
    }
  }

  const suggestedTags = availableTags.filter(
    (t) => !currentTags.includes(t) && t.includes(newTag.toLowerCase()),
  )

  if (!editing) {
    return (
      <button
        onClick={() => setEditing(true)}
        className="flex items-center gap-1 text-xs text-[var(--text-tertiary)] hover:text-brand-500 transition-colors mt-1"
      >
        {!compact && <Plus size={12} />}
        <span>{t.memories.editTags}</span>
      </button>
    )
  }

  return (
    <div className="mt-2 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-1.5 flex-1">
          {currentTags.length === 0 && (
            <span className="text-xs text-[var(--text-tertiary)]">{t.memories.noTags}</span>
          )}
          {currentTags.map((tag) => (
            <Badge
              key={tag}
              variant="default"
              className="bg-brand-badge-bg text-brand-badge-text border-brand-border gap-1"
            >
              {tag}
              <button
                onClick={() => handleRemoveTag(tag)}
                disabled={saving}
                className="hover:text-danger-fg transition-colors"
              >
                <X size={10} />
              </button>
            </Badge>
          ))}
        </div>
        <button
          onClick={() => setEditing(false)}
          className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors shrink-0"
        >
          {t.memories.done}
        </button>
      </div>
      <div className="relative">
        <Input
          ref={inputRef}
          value={newTag}
          onChange={(e) => setNewTag(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleBatchAdd(newTag)
            }
            if (e.key === 'Escape') {
              setEditing(false)
            }
          }}
          onBlur={() => {
            if (newTag.trim()) {
              handleBatchAdd(newTag)
            }
          }}
          placeholder={t.memories.tagsInputPlaceholder}
          className="text-sm"
          disabled={saving}
        />
        {suggestedTags.length > 0 && newTag && (
          <div className="absolute top-full left-0 right-0 mt-1 bg-surface-card border border-[var(--border-default)] rounded-lg shadow-lg z-10 max-h-32 overflow-y-auto">
            {suggestedTags.slice(0, 5).map((tag) => (
              <button
                key={tag}
                onClick={() => handleAddTag(tag)}
                className="w-full text-left px-3 py-1.5 text-sm hover:bg-brand-badge-bg transition-colors"
              >
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
