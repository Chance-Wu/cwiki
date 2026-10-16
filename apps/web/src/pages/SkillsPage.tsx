import { useState, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useTranslation } from '../i18n/I18nProvider'
import { type Skill } from '../lib/api'
import { ListSkeleton } from '../components/Skeleton'
import { useModal } from '../hooks/useModal'

import { useToast } from '../components/Toast'
import ErrorAlert from '../components/ErrorAlert'
import EmptyState from '../components/EmptyState'
import { EmptySkills } from '../components/EmptyIllustrations'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { Dialog } from '../components/ui/Dialog'
import { Input } from '../components/ui/Input'
import { SegmentedControl } from '../components/ui/SegmentedControl'
import { Plus, Download, Pencil, Trash2, X, Search, PackagePlus, Sparkles } from 'lucide-react'
import { spring, duration } from '../lib/motion'
import {
  useSkills,
  useSkillAgents,
  useDeleteSkill,
  usePublishSkill,
  useUnpublishSkill,
  useImportSkill,
} from '../hooks/useSkills'
import { SkillCard, SkillDetail, CreateForm, EditForm, ImportForm } from '../components/skills'

type Tab = 'custom' | string

export default function SkillsPage() {
  const { t } = useTranslation()
  const { toast } = useToast()

  const [tab, setTab] = useState<Tab>('custom')
  const [skillSearch, setSkillSearch] = useState('')
  const [detailSkill, setDetailSkill] = useState<Skill | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null)
  const [confirmDeleteSkill, setConfirmDeleteSkill] = useState(false)

  useModal(!!detailSkill, () => setDetailSkill(null))
  useModal(showCreate, () => setShowCreate(false))
  useModal(showImport, () => setShowImport(false))
  useModal(!!editingSkill, () => setEditingSkill(null))

  const sourceForTab = tab === 'custom' ? 'project' : tab
  const { data: skills = [], isLoading, error, refetch } = useSkills({ source: sourceForTab })
  const { data: agents = [] } = useSkillAgents()
  const publishMutation = usePublishSkill()
  const { mutateAsync: unpublishSkill } = useUnpublishSkill()
  const { mutateAsync: deleteSkill } = useDeleteSkill()
  const { mutateAsync: importBuiltinSkill } = useImportSkill()

  const filteredSkills = useMemo(() => {
    let list = skills
    if (skillSearch.trim()) {
      const q = skillSearch.toLowerCase()
      list = list.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.description && s.description.toLowerCase().includes(q)),
      )
    }
    return list
  }, [skills, skillSearch])

  const handlePublish = async (name: string, targetAgents?: string[]) => {
    try {
      await publishMutation.mutateAsync({ name, agents: targetAgents })
      toast(t.skills.publishSuccess, 'success')
    } catch (e) {
      toast(e instanceof Error ? e.message : t.skills.publishFailed, 'error')
    }
  }

  const handleUnpublish = useCallback(
    async (name: string, targetAgents?: string[]) => {
      try {
        await unpublishSkill({ name, agents: targetAgents })
        toast(t.skills.unpublishSuccess, 'success')
      } catch (e) {
        toast(e instanceof Error ? e.message : t.skills.unpublishFailed, 'error')
      }
    },
    [unpublishSkill, t, toast],
  )

  const handleDelete = useCallback(
    async (name: string) => {
      try {
        await deleteSkill(name)
        toast(t.skills.deleteSuccess, 'success')
        setDetailSkill(null)
      } catch (e) {
        toast(e instanceof Error ? e.message : t.skills.deleteFailed, 'error')
      }
    },
    [deleteSkill, t, toast],
  )

  const handleImportBuiltin = useCallback(
    async (sourcePath: string) => {
      try {
        const skill = await importBuiltinSkill(sourcePath)
        toast(t.skills.importSuccess, 'success')
        setDetailSkill(null)
        return skill
      } catch (e) {
        toast(e instanceof Error ? e.message : t.skills.importFailed, 'error')
        return null
      }
    },
    [importBuiltinSkill, t, toast],
  )

  const openSkill = useCallback((s: Skill) => setDetailSkill(s), [])
  const editSkill = useCallback((s: Skill) => setEditingSkill(s), [])
  const importSkill = useCallback(
    (s: Skill) => {
      void handleImportBuiltin(s.path)
    },
    [handleImportBuiltin],
  )
  const unpublishCardAgent = useCallback(
    (s: Skill, agent: string) => handleUnpublish(s.name, [agent]),
    [handleUnpublish],
  )

  const tabs: { key: Tab; label: string }[] = [
    { key: 'custom', label: t.skills.tabCustom },
    ...agents.map((a) => ({ key: a, label: a.charAt(0).toUpperCase() + a.slice(1) })),
  ]

  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <div className="flex items-center justify-between">
          <PageTitle icon={<Sparkles size={18} />} title={t.skills.title} />
          <div className="flex gap-2">
            <Button
              onClick={() => setShowImport(true)}
              variant="secondary"
              className="flex items-center gap-1.5"
            >
              <Download size={15} aria-hidden="true" />
              <span className="hidden sm:inline">{t.skills.import}</span>
            </Button>
            <Button onClick={() => setShowCreate(true)} className="flex items-center gap-1.5">
              <Plus size={15} aria-hidden="true" />
              <span className="hidden sm:inline">{t.skills.create}</span>
            </Button>
          </div>
        </div>
      }
    >
      {/* 搜索与筛选面板 */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...spring.snappy, delay: 0.05 }}
      >
        <Card className="p-4 md:p-5 mb-5">
          {/* 搜索框 */}
          <div className="relative mb-4">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] pointer-events-none z-10"
              aria-hidden="true"
            />
            <Input
              type="text"
              value={skillSearch}
              onChange={(e) => setSkillSearch(e.target.value)}
              placeholder={t.skills.searchPlaceholder}
              className="pl-9 pr-9 text-xs"
            />
            {skillSearch && (
              <button
                onClick={() => setSkillSearch('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)] hover:text-[var(--text-primary)] transition-all duration-150 active:scale-90"
                aria-label={t.common.close}
              >
                <X size={14} aria-hidden="true" />
              </button>
            )}
          </div>

          {/* 标签页 */}
          <div className="overflow-x-auto scrollbar-none pb-1">
            <SegmentedControl
              value={tab}
              onChange={setTab}
              options={tabs.map(({ key, label }) => ({
                value: key,
                label,
                count: tab === key && !isLoading ? skills.length : undefined,
              }))}
            />
          </div>
        </Card>
      </motion.div>

      <AnimatePresence mode="wait">
        <motion.div
          key={tab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: duration.slow, ease: [0.34, 1.56, 0.64, 1] }}
        >
          {isLoading ? (
            <ListSkeleton rows={4} />
          ) : error ? (
            <ErrorAlert
              message={t.skills.loadFailed}
              onRetry={() => refetch()}
              retryLabel={t.common.retry}
            />
          ) : filteredSkills.length === 0 ? (
            <EmptyState illustration={<EmptySkills />} message={t.skills.empty} />
          ) : (
            <Card className="divide-y divide-[var(--border-default)] overflow-hidden">
              {filteredSkills.map((s, idx) => (
                <SkillCard
                  key={`${s.source}-${s.name}`}
                  skill={s}
                  idx={idx}
                  onOpen={openSkill}
                  onEdit={editSkill}
                  onDelete={handleDelete}
                  onImport={importSkill}
                  onUnpublish={unpublishCardAgent}
                />
              ))}
            </Card>
          )}
        </motion.div>
      </AnimatePresence>

      {/* 详情弹窗 */}
      <Dialog
        open={!!detailSkill}
        onOpenChange={(v) => {
          if (!v) {
            setDetailSkill(null)
            setConfirmDeleteSkill(false)
          }
        }}
        title={detailSkill?.name ?? ''}
        description={detailSkill?.description}
        size="xl"
        fixedHeight
        footer={
          detailSkill ? (
            <div className="flex gap-2">
              {detailSkill.editable ? (
                <>
                  {detailSkill.agents.length > 0 && (
                    <Button
                      onClick={() => handleUnpublish(detailSkill.name)}
                      variant="secondary"
                      className="flex items-center gap-1.5"
                    >
                      <X size={14} aria-hidden="true" />
                      {t.skills.unpublishAll}
                    </Button>
                  )}
                  <Button
                    onClick={() => {
                      setDetailSkill(null)
                      setEditingSkill(detailSkill)
                    }}
                    variant="secondary"
                    className="flex items-center gap-1.5"
                  >
                    <Pencil size={14} aria-hidden="true" />
                    {t.skills.edit}
                  </Button>
                  <Button
                    onClick={() => {
                      if (confirmDeleteSkill) {
                        handleDelete(detailSkill.name)
                      } else {
                        setConfirmDeleteSkill(true)
                      }
                    }}
                    variant={confirmDeleteSkill ? 'danger' : 'ghost'}
                    className="flex items-center gap-1.5"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                    {confirmDeleteSkill ? t.common.confirm : t.skills.delete}
                  </Button>
                </>
              ) : (
                <Button
                  onClick={() => handleImportBuiltin(detailSkill.path)}
                  className="flex items-center gap-1.5"
                >
                  <PackagePlus size={14} aria-hidden="true" />
                  {t.skills.importBuiltin}
                </Button>
              )}
            </div>
          ) : undefined
        }
      >
        {detailSkill && (
          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
            <SkillDetail
              skill={detailSkill}
              t={t}
              onPublish={(targetAgents) => handlePublish(detailSkill.name, targetAgents)}
              onUnpublish={(targetAgents) => handleUnpublish(detailSkill.name, targetAgents)}
            />
          </div>
        )}
      </Dialog>

      {/* 新建弹窗 */}
      <Dialog
        open={showCreate}
        onOpenChange={(v) => {
          if (!v) setShowCreate(false)
        }}
        title={t.skills.createTitle}
        size="lg"
        fixedHeight
      >
        <CreateForm
          onSuccess={(skill) => {
            setShowCreate(false)
            toast(t.skills.createSuccess, 'success')
            setDetailSkill(skill)
          }}
          onCancel={() => setShowCreate(false)}
          submitLabel={t.skills.create}
          agents={agents}
        />
      </Dialog>

      {/* 编辑弹窗 */}
      <Dialog
        open={!!editingSkill}
        onOpenChange={(v) => {
          if (!v) setEditingSkill(null)
        }}
        title={t.skills.editTitle}
        size="lg"
        fixedHeight
      >
        {editingSkill && (
          <EditForm
            skill={editingSkill}
            onSuccess={(skill) => {
              setEditingSkill(null)
              toast(t.skills.updateSuccess, 'success')
              setDetailSkill(skill)
            }}
            onCancel={() => setEditingSkill(null)}
          />
        )}
      </Dialog>

      {/* 导入弹窗 */}
      <Dialog
        open={showImport}
        onOpenChange={(v) => {
          if (!v) setShowImport(false)
        }}
        title={t.skills.importTitle}
        size="lg"
        fixedHeight
      >
        <ImportForm
          onSuccess={(skill) => {
            setShowImport(false)
            toast(t.skills.importSuccess, 'success')
            setDetailSkill(skill)
          }}
          onCancel={() => setShowImport(false)}
        />
      </Dialog>
    </PageShell>
  )
}
