import { useState } from 'react'
import { X, Pencil, Merge, Trash2 } from 'lucide-react'
import { api } from '../../lib/api'
import type { TagInfo } from '../../lib/api/memories'
import { useTranslation } from '../../i18n/I18nProvider'
import { useToast } from '../Toast'

interface Props {
  tags: TagInfo[]
  onTagsChanged: () => void
  onClose: () => void
}

type Mode = 'idle' | 'rename' | 'merge' | 'delete'

export default function TagManagePanel({ tags, onTagsChanged, onClose }: Props) {
  const { t } = useTranslation()
  const { toast } = useToast()
  const [mode, setMode] = useState<Mode>('idle')
  const [selectedTag, setSelectedTag] = useState<string>('')
  const [newName, setNewName] = useState('')
  const [mergeSources, setMergeSources] = useState<string[]>([])
  const [mergeTarget, setMergeTarget] = useState('')
  const [loading, setLoading] = useState(false)

  const resetForm = () => {
    setMode('idle')
    setSelectedTag('')
    setNewName('')
    setMergeSources([])
    setMergeTarget('')
  }

  const handleRename = async () => {
    if (!selectedTag || !newName.trim()) return
    setLoading(true)
    try {
      const res = await api.renameTag(selectedTag, newName.trim())
      toast(t.memories.tagRenamed + ` (${res.updated_count})`, 'success')
      onTagsChanged()
      resetForm()
    } catch {
      toast('重命名失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleMerge = async () => {
    if (mergeSources.length < 2 || !mergeTarget.trim()) return
    setLoading(true)
    try {
      const res = await api.mergeTags(mergeSources, mergeTarget.trim())
      toast(t.memories.tagMerged + ` (${res.updated_count})`, 'success')
      onTagsChanged()
      resetForm()
    } catch {
      toast('合并失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async () => {
    if (!selectedTag) return
    setLoading(true)
    try {
      const res = await api.deleteTag(selectedTag)
      toast(t.memories.tagDeleted + ` (${res.updated_count})`, 'success')
      onTagsChanged()
      resetForm()
    } catch {
      toast('删除失败', 'error')
    } finally {
      setLoading(false)
    }
  }

  const toggleMergeSource = (tag: string) => {
    setMergeSources((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    )
  }

  return (
    <div className="p-4 bg-surface-card border border-[var(--border-default)] rounded-xl shadow-lg space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[var(--text-primary)]">
          {t.memories.tagManage}
        </h3>
        <button
          onClick={onClose}
          className="p-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      {mode === 'idle' && (
        <div className="space-y-3">
          <div className="flex gap-2">
            <button
              onClick={() => setMode('rename')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-inset rounded-lg border border-[var(--border-default)] text-[var(--text-secondary)] hover:bg-brand-badge-bg hover:text-brand-500 transition-colors"
            >
              <Pencil size={12} />
              {t.memories.renameTag}
            </button>
            <button
              onClick={() => setMode('merge')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-inset rounded-lg border border-[var(--border-default)] text-[var(--text-secondary)] hover:bg-brand-badge-bg hover:text-brand-500 transition-colors"
            >
              <Merge size={12} />
              {t.memories.mergeTags}
            </button>
            <button
              onClick={() => setMode('delete')}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-inset rounded-lg border border-[var(--border-default)] text-[var(--text-secondary)] hover:text-danger-fg hover:bg-danger-bg transition-colors"
            >
              <Trash2 size={12} />
              {t.memories.deleteTag}
            </button>
          </div>
          <div className="max-h-48 overflow-y-auto space-y-1">
            {tags.map((tag) => (
              <div
                key={tag.name}
                className="flex items-center justify-between px-2 py-1 text-sm rounded hover:bg-surface-inset transition-colors"
              >
                <span className="text-[var(--text-primary)]">{tag.name}</span>
                <span className="text-xs text-[var(--text-tertiary)] tabular-nums">
                  {tag.count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {mode === 'rename' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              {t.memories.renameTag}
            </label>
            <select
              value={selectedTag}
              onChange={(e) => setSelectedTag(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-surface-inset border border-[var(--border-default)] rounded-lg text-[var(--text-primary)]"
            >
              <option value="">--</option>
              {tags.map((tag) => (
                <option key={tag.name} value={tag.name}>
                  {tag.name} ({tag.count})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              {t.memories.tagNewName}
            </label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-surface-inset border border-[var(--border-default)] rounded-lg text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]"
              placeholder={t.memories.tagNewName}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleRename}
              disabled={!selectedTag || !newName.trim() || loading}
              className="px-3 py-1 text-sm bg-brand-500 text-white rounded-lg disabled:opacity-50 hover:bg-brand-600 transition-colors"
            >
              {loading ? '...' : t.common.confirm || '确认'}
            </button>
            <button
              onClick={resetForm}
              className="px-3 py-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              {t.common.cancel || '取消'}
            </button>
          </div>
        </div>
      )}

      {mode === 'merge' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              {t.memories.tagMergeSources}（{mergeSources.length}/2+）
            </label>
            <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto">
              {tags.map((tag) => (
                <button
                  key={tag.name}
                  onClick={() => toggleMergeSource(tag.name)}
                  disabled={mergeTarget === tag.name}
                  className={`px-2 py-0.5 text-xs rounded-full border transition-colors ${
                    mergeSources.includes(tag.name)
                      ? 'bg-brand-500 text-white border-brand-500'
                      : 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)] hover:bg-brand-badge-bg'
                  } ${mergeTarget === tag.name ? 'opacity-30 cursor-not-allowed' : ''}`}
                >
                  {tag.name}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              {t.memories.tagMergeTarget}
            </label>
            <input
              type="text"
              value={mergeTarget}
              onChange={(e) => setMergeTarget(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-surface-inset border border-[var(--border-default)] rounded-lg text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]"
              placeholder={t.memories.tagMergeTarget}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleMerge}
              disabled={mergeSources.length < 2 || !mergeTarget.trim() || loading}
              className="px-3 py-1 text-sm bg-brand-500 text-white rounded-lg disabled:opacity-50 hover:bg-brand-600 transition-colors"
            >
              {loading ? '...' : t.common.confirm || '确认'}
            </button>
            <button
              onClick={resetForm}
              className="px-3 py-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              {t.common.cancel || '取消'}
            </button>
          </div>
        </div>
      )}

      {mode === 'delete' && (
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              {t.memories.deleteTag}
            </label>
            <select
              value={selectedTag}
              onChange={(e) => setSelectedTag(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-surface-inset border border-[var(--border-default)] rounded-lg text-[var(--text-primary)]"
            >
              <option value="">--</option>
              {tags.map((tag) => (
                <option key={tag.name} value={tag.name}>
                  {tag.name} ({tag.count})
                </option>
              ))}
            </select>
          </div>
          {selectedTag && (
            <p className="text-xs text-danger-fg">
              {t.memories.confirmDeleteTag.replace('{tag}', selectedTag)}
            </p>
          )}
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              disabled={!selectedTag || loading}
              className="px-3 py-1 text-sm bg-danger-fg text-white rounded-lg disabled:opacity-50 hover:opacity-90 transition-colors"
            >
              {loading ? '...' : t.common.confirm || '确认'}
            </button>
            <button
              onClick={resetForm}
              className="px-3 py-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              {t.common.cancel || '取消'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
