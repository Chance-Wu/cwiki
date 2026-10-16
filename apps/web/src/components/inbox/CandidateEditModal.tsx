import { useState, useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { useTranslation } from '../../i18n/I18nProvider'
import { type Candidate } from '../../lib/api'
import { Dialog } from '../ui/Dialog'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Textarea } from '../ui/Textarea'
import MarkdownContent from '../MarkdownContent'
import { useModal } from '../../hooks/useModal'
import { duration, ease } from '../../lib/motion'

interface CandidateEditModalProps {
  candidate: Candidate | null
  actionLoading: string | null
  onClose: () => void
  onSubmit: (candidate: Candidate, title: string, content: string) => Promise<void>
}

export default function CandidateEditModal({
  candidate,
  actionLoading,
  onClose,
  onSubmit,
}: CandidateEditModalProps) {
  const { t } = useTranslation()
  useModal(!!candidate, onClose)
  const [editTitle, setEditTitle] = useState('')
  const [editContent, setEditContent] = useState('')
  const [editTab, setEditTab] = useState<'source' | 'preview'>('source')

  useEffect(() => {
    if (candidate) {
      setEditTitle(candidate.title)
      setEditContent(candidate.content)
      setEditTab('source')
    }
  }, [candidate])

  return (
    <Dialog
      open={!!candidate}
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
      title={t.inbox.editTitle}
      size="lg"
      fixedHeight
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {t.inbox.cancel}
          </Button>
          <Button
            onClick={async () => {
              if (candidate) {
                await onSubmit(candidate, editTitle, editContent)
              }
            }}
            disabled={actionLoading === candidate?.id || !editContent.trim()}
          >
            {t.inbox.save}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.inbox.labelTitle}
          </label>
          <Input type="text" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1">
            {t.inbox.labelContent}
          </label>
          <div className="flex gap-1 mb-2">
            <button
              role="tab"
              aria-selected={editTab === 'source'}
              onClick={() => setEditTab('source')}
              className={`px-3 py-1 text-sm rounded-lg transition-all duration-150 select-none active:scale-[0.97] ${
                editTab === 'source'
                  ? 'bg-surface-inset text-[var(--text-primary)] font-medium'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-surface-inset'
              }`}
            >
              {t.inbox.sourceTab}
            </button>
            <button
              role="tab"
              aria-selected={editTab === 'preview'}
              onClick={() => setEditTab('preview')}
              className={`px-3 py-1 text-sm rounded-lg transition-all duration-150 select-none active:scale-[0.97] ${
                editTab === 'preview'
                  ? 'bg-surface-inset text-[var(--text-primary)] font-medium'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-surface-inset'
              }`}
            >
              {t.inbox.previewTab}
            </button>
          </div>
          <AnimatePresence mode="wait">
            <motion.div
              key={editTab}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: duration.normal, ease: ease.out }}
            >
              {editTab === 'source' ? (
                <Textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  rows={6}
                  className="min-h-[168px]"
                />
              ) : (
                <div className="rounded-lg p-4 min-h-[168px] bg-surface-inset border border-[var(--border-default)] shadow-warm-xs">
                  <MarkdownContent content={editContent} />
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </Dialog>
  )
}
