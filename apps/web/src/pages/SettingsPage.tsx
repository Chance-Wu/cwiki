import { useState } from 'react'
import { motion } from 'framer-motion'
import {
  Loader2,
  Database,
  TrendingUp,
  Globe,
  Info,
  Download,
  Sun,
  Moon,
  Monitor,
  Settings,
} from 'lucide-react'
import { api } from '../lib/api'
import { useTranslation } from '../i18n/I18nProvider'
import { spring, duration } from '../lib/motion'
import { CardSkeleton } from '../components/Skeleton'
import ErrorAlert from '../components/ErrorAlert'
import { useToast } from '../components/Toast'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import SectionGroup from '../components/SectionGroup'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import StatBox from '../components/StatBox'
import RingProgress from '../components/RingProgress'
import { useHealth, useConfig } from '../hooks/useSettings'
import { useMetrics, useDefaultWorkspace } from '../hooks/useDashboard'
import { useTheme } from '../theme/ThemeProvider'

export default function SettingsPage() {
  const { locale, setLocale, t } = useTranslation()
  const { toast } = useToast()
  const { theme, toggleTheme, brandTheme, setBrandTheme } = useTheme()

  const {
    data: health,
    isLoading: healthLoading,
    error: healthError,
    refetch: refetchHealth,
    isFetching: healthFetching,
  } = useHealth()
  const { data: config } = useConfig()
  const { data: metrics, isLoading: metricsLoading, isFetching: metricsFetching } = useMetrics()
  const { data: workspaceId } = useDefaultWorkspace()

  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)

  const loading = healthLoading || metricsLoading
  const error = healthError && !health
  const isFetching = healthFetching || metricsFetching

  const toggleLocale = () => setLocale(locale === 'zh' ? 'en' : 'zh')

  const handleExport = async (format: 'json' | 'zip') => {
    setExporting(true)
    try {
      const res = await api.exportData(format)

      if (format === 'zip') {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'cwiki_export.zip'
        a.click()
        URL.revokeObjectURL(url)
      } else {
        const data = await res.json()
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'cwiki_export.json'
        a.click()
        URL.revokeObjectURL(url)
      }
    } catch {
      toast(t.settings.exportFailed, 'error')
    } finally {
      setExporting(false)
    }
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    try {
      const result = await api.importData(file)
      toast(
        t.settings.importSuccess.replace('{n}', String(result.results?.created ?? 0)),
        'success',
      )
    } catch {
      toast(t.settings.importFailed, 'error')
    } finally {
      setImporting(false)
      e.target.value = ''
    }
  }


  return (
    <PageShell
      maxWidth="max-w-6xl"
      header={
        <div className="flex items-center justify-between">
          <PageTitle icon={<Settings size={18} />} title={t.settings.title} />
          <Button
            onClick={() => {
              refetchHealth()
            }}
            disabled={isFetching}
            variant="secondary"
          >
            <Loader2 size={14} className={isFetching ? 'animate-spin' : ''} />
            {t.common.refresh}
          </Button>
        </div>
      }
    >
      {loading ? (
        <CardSkeleton cols={2} />
      ) : error ? (
        <ErrorAlert
          message={t.settings.loadFailed}
          onRetry={() => {
            refetchHealth()
          }}
          retryLabel={t.common.retry}
        />
      ) : (
        <div className="space-y-8">
          {/* ── 偏好 ── */}
          <SectionGroup
            accentFrom="from-brand-400"
            accentTo="to-brand-600"
            title={t.settings.groupPreference}
          >
            {/* 语言设置 */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring.snappy, delay: 0.05 }}
            >
              <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]">
                <div className="flex items-center gap-2.5 mb-3">
                  <motion.div
                    className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-brand-50 to-brand-100/50 shrink-0 ring-1 ring-brand-200/40 border border-brand-200/25 shadow-warm-xs"
                    whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
                    transition={{ duration: duration.modal }}
                  >
                    <Globe size={15} className="text-brand-fg" aria-hidden="true" />
                  </motion.div>
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">
                    {t.settings.language}
                  </h3>
                </div>
                <div className="flex items-center gap-3">
                  <Button onClick={toggleLocale} variant="secondary">
                    <Globe size={14} aria-hidden="true" />
                    {t.settings.switchLang}
                  </Button>
                  <span className="text-xs text-[var(--text-secondary)] font-medium">
                    {t.settings.currentLang}:{' '}
                    {locale === 'zh' ? t.common.chinese : t.common.english}
                  </span>
                </div>
              </Card>
            </motion.div>

            {/* 外观 */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring.snappy, delay: 0.1 }}
            >
              <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]">
                <div className="flex items-center gap-2.5 mb-3">
                  <motion.div
                    className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-warning/18 to-warning/8 shrink-0 ring-1 ring-warning/30 border border-warning/25 shadow-warm-xs"
                    whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
                    transition={{ duration: duration.modal }}
                  >
                    {theme === 'dark' ? (
                      <Moon size={15} className="text-warning-fg" aria-hidden="true" />
                    ) : theme === 'light' ? (
                      <Sun size={15} className="text-warning-fg" aria-hidden="true" />
                    ) : (
                      <Monitor size={15} className="text-warning-fg" aria-hidden="true" />
                    )}
                  </motion.div>
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">
                    {t.settings.appearance}
                  </h3>
                </div>
                <div className="flex items-center gap-3">
                  <Button onClick={toggleTheme} variant="secondary">
                    {theme === 'dark' ? (
                      <Moon size={14} aria-hidden="true" />
                    ) : theme === 'light' ? (
                      <Sun size={14} aria-hidden="true" />
                    ) : (
                      <Monitor size={14} aria-hidden="true" />
                    )}
                    {theme === 'dark'
                      ? t.settings.themeDark
                      : theme === 'light'
                        ? t.settings.themeLight
                        : t.settings.themeSystem}
                  </Button>
                  <span className="text-xs text-[var(--text-secondary)] font-medium">
                    {t.settings.theme}:{' '}
                    {theme === 'dark'
                      ? t.settings.themeDark
                      : theme === 'light'
                        ? t.settings.themeLight
                        : t.settings.themeSystem}
                  </span>
                </div>
                <div className="mt-4 pt-4 border-t border-[var(--border-default)]">
                  <p className="text-xs text-[var(--text-secondary)] font-medium mb-3">
                    {t.settings.brandTheme}
                  </p>
                  <div className="flex items-center gap-3">
                    {[
                      { key: 'amber' as const, color: '#D97706', label: t.settings.brandAmber },
                      { key: 'blue' as const, color: '#2563EB', label: t.settings.brandBlue },
                      { key: 'emerald' as const, color: '#059669', label: t.settings.brandEmerald },
                      { key: 'violet' as const, color: '#7C3AED', label: t.settings.brandViolet },
                    ].map(({ key, color, label }) => (
                      <button
                        key={key}
                        aria-label={label}
                        onClick={() => setBrandTheme(key)}
                        title={label}
                        className={`group relative w-8 h-8 rounded-full transition-all duration-200 hover:scale-110 ${
                          brandTheme === key
                            ? 'scale-110'
                            : 'ring-1 ring-[var(--border-default)] hover:ring-[var(--border-strong)]'
                        }`}
                        style={{
                          background: color,
                          ...(brandTheme === key
                            ? { boxShadow: `0 0 0 2px var(--surface-card), 0 0 0 4px ${color}` }
                            : {}),
                        }}
                      >
                        {brandTheme === key && (
                          <motion.svg
                            initial={{ scale: 0 }}
                            animate={{ scale: 1 }}
                            className="absolute inset-0 m-auto w-4 h-4 text-white"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={3}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </motion.svg>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </Card>
            </motion.div>
          </SectionGroup>

          {/* ── 工作区 ── */}
          <SectionGroup
            accentFrom="from-info/60"
            accentTo="to-info"
            title={t.settings.groupWorkspace}
          >
            {/* 工作区信息 */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring.snappy, delay: 0.15 }}
            >
              <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]">
                <div className="flex items-center gap-2.5 mb-3">
                  <motion.div
                    className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-info/18 to-info/8 shrink-0 ring-1 ring-info/30"
                    whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
                    transition={{ duration: duration.modal }}
                  >
                    <Info size={15} className="text-info-fg" aria-hidden="true" />
                  </motion.div>
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">
                    {t.settings.workspace}
                  </h3>
                </div>
                <div className="space-y-4">
                  <div className="flex justify-between text-xs">
                    <span className="text-[var(--text-secondary)] font-medium">
                      {t.settings.workspaceId}
                    </span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {workspaceId || '-'}
                    </span>
                  </div>
                </div>
              </Card>
            </motion.div>
          </SectionGroup>

          {/* ── 数据 ── */}
          <SectionGroup
            accentFrom="from-success/60"
            accentTo="to-success"
            title={t.settings.groupData}
          >
            {/* 数据管理 */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring.snappy, delay: 0.2 }}
            >
              <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)]">
                <div className="flex items-center gap-2.5 mb-3">
                  <motion.div
                    className="flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-success/18 to-success/8 shrink-0 ring-1 ring-success/30"
                    whileHover={{ scale: 1.08, rotate: [-3, 3, 0] }}
                    transition={{ duration: duration.modal }}
                  >
                    <Database size={15} className="text-success-fg" aria-hidden="true" />
                  </motion.div>
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">
                    {t.settings.dataManagement}
                  </h3>
                </div>
                <div className="space-y-4">
                  <div>
                    <p className="text-xs text-[var(--text-secondary)] mb-3 font-medium">
                      {t.settings.exportDesc}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        onClick={() => handleExport('json')}
                        disabled={exporting}
                        variant="secondary"
                      >
                        <Loader2 size={14} className={exporting ? 'animate-spin' : ''} />
                        JSON
                      </Button>
                      <Button
                        onClick={() => handleExport('zip')}
                        disabled={exporting}
                        variant="secondary"
                      >
                        <Download size={14} aria-hidden="true" />
                        ZIP
                      </Button>
                    </div>
                  </div>
                  <div className="mt-5 pt-4 border-t border-[var(--border-default)]">
                    <p className="text-xs text-[var(--text-secondary)] mb-3 font-medium">
                      {t.settings.importDesc}
                    </p>
                    <Button variant="secondary" asChild>
                      <label
                        className={`cursor-pointer ${importing ? 'pointer-events-none opacity-50' : ''}`}
                      >
                        <Loader2 size={14} className={importing ? 'animate-spin' : ''} />
                        {importing ? t.settings.importing : t.settings.importFile}
                        <input
                          type="file"
                          accept=".json,.zip"
                          onChange={handleImport}
                          className="hidden"
                          disabled={importing}
                        />
                      </label>
                    </Button>
                  </div>
                </div>
              </Card>
            </motion.div>
          </SectionGroup>

          {/* ── 系统 ── */}
          <SectionGroup
            accentFrom="from-[var(--text-tertiary)]"
            accentTo="to-[var(--text-secondary)]"
            title={t.settings.groupSystem}
          >
            {/* 系统监控 */}
            {metrics && (
              <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...spring.snappy, delay: 0.25 }}
              >
                <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)] bg-surface-elevated/20">
                  <div className="flex items-center gap-2.5 mb-3">
                    <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-surface-elevated/40 shrink-0 ring-1 ring-subtle">
                      <TrendingUp
                        size={15}
                        className="text-[var(--text-secondary)]"
                        aria-hidden="true"
                      />
                    </div>
                    <h3 className="text-base font-semibold text-[var(--text-primary)]">
                      {t.settings.monitoring}
                    </h3>
                  </div>

                  {/* 检索性能——可视化卡片 */}
                  <div className="mb-5">
                    <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-3">
                      {t.settings.retrieval}
                    </p>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <StatBox
                        value={
                          <>
                            {metrics.retrieval.avg_latency_ms}
                            <span className="text-sm font-normal opacity-60">{t.settings.ms}</span>
                          </>
                        }
                        label={t.settings.avgLatency}
                        color={
                          metrics.retrieval.avg_latency_ms < 100
                            ? 'success'
                            : metrics.retrieval.avg_latency_ms < 300
                              ? 'warning'
                              : 'danger'
                        }
                      />
                      <StatBox
                        value={metrics.retrieval.queries_24h}
                        label={t.settings.queries24h}
                        color="brand"
                      />
                      <div className="flex flex-col items-center justify-center p-3 bg-success/18 rounded-lg ring-1 ring-success/30">
                        <RingProgress
                          value={metrics.retrieval.success_rate}
                          size={44}
                          strokeWidth={4}
                          color="var(--success-rgb)"
                          label={`${(metrics.retrieval.success_rate * 100).toFixed(0)}%`}
                        />
                        <span className="text-xs text-success-fg mt-1.5 font-medium">
                          {t.settings.successRate}
                        </span>
                      </div>
                      <StatBox
                        value={metrics.retrieval.total_queries}
                        label={t.settings.totalQueries}
                        color="info"
                      />
                    </div>
                  </div>

                  {/* 存储——紧凑行 */}
                  <div className="pt-4 border-t border-[var(--border-default)]">
                    <p className="text-xs font-semibold text-[var(--text-tertiary)] uppercase tracking-[0.08em] mb-3">
                      {t.settings.storage}
                    </p>
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2 text-xs text-[var(--text-secondary)] font-medium">
                        <Database size={14} aria-hidden="true" />
                        {t.settings.vectors}
                      </span>
                      <span className="text-xs font-semibold text-[var(--text-primary)] tabular-nums">
                        {metrics.storage.vector_count.toLocaleString()}
                      </span>
                    </div>
                  </div>
                </Card>
              </motion.div>
            )}

            {/* 关于 */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...spring.snappy, delay: 0.35 }}
            >
              <Card className="p-4 md:p-5 transition-all duration-150 hover:shadow-warm-md hover:border-[var(--border-strong)] bg-surface-elevated/20">
                <div className="flex items-center gap-2.5 mb-3">
                  <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-surface-elevated/40 shrink-0 ring-1 ring-subtle">
                    <Info size={15} className="text-[var(--text-secondary)]" aria-hidden="true" />
                  </div>
                  <h3 className="text-base font-semibold text-[var(--text-primary)]">
                    {t.settings.about}
                  </h3>
                </div>
                <div className="divide-y divide-[var(--border-default)]">
                  <div className="flex justify-between py-2.5 first:pt-0">
                    <span className="text-xs text-[var(--text-secondary)] font-medium">
                      {t.settings.version}
                    </span>
                    <span className="font-semibold text-[var(--text-primary)]">
                      {health?.version ?? '-'}
                    </span>
                  </div>
                  <div className="flex justify-between py-2.5">
                    <span className="text-xs text-[var(--text-secondary)] font-medium">
                      {t.settings.configFile}
                    </span>
                    <span className="font-mono text-xs text-[var(--text-secondary)] font-medium bg-surface-elevated/30 px-1.5 py-0.5 rounded-lg ring-1 ring-subtle">
                      {config?.system_info.config_path ?? 'config.yaml'}
                    </span>
                  </div>
                  <div className="flex justify-between py-2.5 last:pb-0">
                    <span className="text-xs text-[var(--text-secondary)] font-medium">
                      {t.settings.dataDir}
                    </span>
                    <span className="font-mono text-xs text-[var(--text-secondary)] font-medium bg-surface-elevated/30 px-1.5 py-0.5 rounded-lg ring-1 ring-subtle">
                      {config?.system_info.memory_dir ?? './cwiki-data/'}
                    </span>
                  </div>
                </div>
              </Card>
            </motion.div>
          </SectionGroup>
        </div>
      )}
    </PageShell>
  )
}
