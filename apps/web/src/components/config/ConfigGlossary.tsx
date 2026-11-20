// 配置页的导入导航卡与术语表弹窗。
import { ArrowRight, ChevronRight } from 'lucide-react'
import { Card } from '../ui/Card'
import { Dialog } from '../ui/Dialog'
import { GLOSSARY, WORKFLOW_STEPS } from './configSchema'

function WorkflowCard({
  copy,
  onNavigate,
}: {
  copy: Record<string, string>
  onNavigate: (id: string) => void
}) {
  return (
    <Card className="p-4 md:p-5">
      <h3 className="text-sm font-semibold text-primary">{copy.workflowTitle}</h3>
      <p className="mt-1 max-w-3xl text-xs font-medium leading-relaxed text-tertiary">
        {copy.workflowHint}
      </p>
      <div className="mt-4 grid gap-2 md:grid-cols-3">
        {WORKFLOW_STEPS.map((step, index) => (
          <div key={step.id} className="relative">
            <button
              type="button"
              onClick={() => onNavigate(step.id)}
              className="group flex h-full w-full flex-col rounded-xl border border-default bg-surface-card/60 p-3 text-left transition-colors duration-150 hover:border-brand-300/60 hover:bg-brand-50/40 dark:hover:bg-brand-500/5"
            >
              <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.08em] text-tertiary">
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-md border text-[11px] font-semibold tabular-nums ${step.chip}`}
                >
                  {index + 1}
                </span>
                {copy[step.labelKey]}
              </span>
              <span className="mt-1.5 text-sm font-semibold text-primary">
                {copy[step.titleKey]}
              </span>
              <span className="mt-1 text-xs leading-relaxed text-secondary">
                {copy[step.descKey]}
              </span>
              <span className="mt-2 flex items-center gap-1 text-[11px] font-medium text-brand-fg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                {copy.workflowOpen}
                <ArrowRight size={11} aria-hidden="true" />
              </span>
            </button>
            {index < WORKFLOW_STEPS.length - 1 && (
              <ChevronRight
                size={14}
                aria-hidden="true"
                className="absolute -right-2 top-1/2 hidden -translate-y-1/2 text-tertiary md:block"
              />
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function GlossaryDialog({
  open,
  onOpenChange,
  copy,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  copy: Record<string, string>
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={copy.glossaryTitle}
      description={copy.glossaryDesc}
      size="lg"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {GLOSSARY.map(([termKey, descKey]) => (
          <div
            key={termKey}
            className="rounded-lg border border-default bg-[var(--surface-inset)]/60 p-3"
          >
            <p className="text-xs font-semibold text-primary">{copy[termKey]}</p>
            <p className="mt-1 text-xs leading-relaxed text-secondary">{copy[descKey]}</p>
          </div>
        ))}
      </div>
    </Dialog>
  )
}

export { WorkflowCard, GlossaryDialog }
