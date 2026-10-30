import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpenCheck,
  Brain,
  FileText,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Monitor,
  Moon,
  MoreHorizontal,
  Network,
  Settings,
  Sliders,
  Sparkles,
  Sun,
  WifiOff,
  X,
} from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import { useTheme } from '../theme/ThemeProvider'
import { BRAND } from '../theme/brandTokens'
import { useDashboardStats } from '../hooks/useDashboard'
import { useReviewStats } from '../hooks/useReview'
import { useNetworkStatus } from '../hooks/useNetworkStatus'
import { spring, ease, duration } from '../lib/motion'

// 静态样式对象提升到模块作用域，避免每次渲染重复创建
const MAIN_BG_STYLE: React.CSSProperties = {
  background:
    'radial-gradient(ellipse 80% 50% at 50% 0%, var(--content-glow-1) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 30% 80%, var(--content-glow-2) 0%, transparent 50%)',
}

const BADGE_COLORS: Record<string, string> = {
  amber: 'bg-warning/22 border border-warning/35 text-warning-fg',
  brand: 'bg-brand-200/45 border border-brand-300/40 text-brand-fg',
}

const DOT_COLORS: Record<string, string> = {
  amber: 'bg-warning',
  brand: 'bg-brand-500',
}

const TRANSITION_RESIZING = { duration: 0 }
const TRANSITION_SPRING = { type: 'spring' as const, stiffness: 350, damping: 30 }

const CwikiBrandIcon = memo(function CwikiBrandIcon({
  className = 'w-9 h-9',
}: {
  className?: string
}) {
  const { resolvedTheme } = useTheme()
  const colors = resolvedTheme === 'dark' ? BRAND.iconColor.dark : BRAND.iconColor.light
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" className={className}>
      <rect width="32" height="32" rx="7" fill={colors.bg} />
      <path
        d="M21 10 A8 8 0 1 0 21 22"
        stroke={colors.fg}
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  )
})

export default function Layout({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation()
  const { theme, resolvedTheme, toggleTheme } = useTheme()
  const location = useLocation()
  const { data: stats } = useDashboardStats()
  const pendingCount = stats?.candidates ?? 0
  const { data: reviewStats } = useReviewStats()
  const dueReviewCount = reviewStats?.due_now ?? 0
  const online = useNetworkStatus()
  const [showMore, setShowMore] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem('cwiki-sidebar-collapsed') === '1'
    } catch {
      return false
    }
  })
  const [sidebarWidth, setSidebarWidth] = useState(() => {
    try {
      const saved = localStorage.getItem('cwiki-sidebar-width')
      return saved ? Math.max(160, Math.min(320, parseInt(saved, 10))) : 216
    } catch {
      return 216
    }
  })
  const [isResizing, setIsResizing] = useState(false)
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.innerWidth < 768 // md breakpoint
  })
  const resizeStartX = useRef(0)
  const resizeStartWidth = useRef(0)

  useEffect(() => {
    const meta = document.querySelector('meta[name="theme-color"]')
    if (meta) {
      meta.setAttribute(
        'content',
        resolvedTheme === 'dark' ? BRAND.themeColor.dark : BRAND.themeColor.light,
      )
    }
  }, [resolvedTheme])

  // 监听屏幕宽度变化，切换移动端/桌面端
  useEffect(() => {
    const mql = window.matchMedia('(max-width: 767px)')
    const handler = (e: MediaQueryListEvent | MediaQueryList) => {
      setIsMobile(e.matches)
    }
    handler(mql)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [])

  useEffect(() => {
    const labels: Record<string, string> = {
      '/': t.nav.home,
      '/pending': t.nav.inbox,
      '/notes': t.nav.notes,
      '/memories': t.nav.memories,
      '/skills': t.nav.skills,
      '/config': t.nav.config,
      '/review': t.nav.review,
      '/graph': t.nav.graph,
      '/quality': t.nav.quality,
      '/settings': t.nav.settings,
    }
    const label = labels[location.pathname]
    document.title = label ? `${label} - cwiki` : 'cwiki'
  }, [location.pathname, t])

  const primaryItems = useMemo(
    () => [
      { to: '/', icon: LayoutDashboard, label: t.nav.home },
      { to: '/pending', icon: Inbox, label: t.nav.inbox },
      { to: '/notes', icon: FileText, label: t.nav.notes },
      { to: '/memories', icon: Brain, label: t.nav.memories },
    ],
    [t.nav.home, t.nav.inbox, t.nav.notes, t.nav.memories],
  )

  const secondaryItems = useMemo(
    () => [
      { to: '/skills', icon: Sparkles, label: t.nav.skills },
      { to: '/config', icon: Sliders, label: t.nav.config },
      { to: '/review', icon: BookOpenCheck, label: t.nav.review },
      { to: '/graph', icon: Network, label: t.nav.graph },
      { to: '/quality', icon: Monitor, label: t.nav.quality },
      { to: '/settings', icon: Settings, label: t.nav.settings },
    ],
    [t.nav.skills, t.nav.config, t.nav.review, t.nav.graph, t.nav.quality, t.nav.settings],
  )

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem('cwiki-sidebar-collapsed', next ? '1' : '0')
      } catch {
        // localStorage 不可用（隐私模式 / 配额满）时静默降级
      }
      return next
    })
  }, [])

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsResizing(true)
      resizeStartX.current = e.clientX
      resizeStartWidth.current = sidebarWidth
    },
    [sidebarWidth],
  )

  useEffect(() => {
    if (!isResizing) return

    // 拖宽小于 100px 视为折叠意图，直接收起侧栏；否则宽度夹取到 160~320 并持久化
    const COLLAPSE_THRESHOLD = 100

    const handleMouseMove = (e: MouseEvent) => {
      const delta = e.clientX - resizeStartX.current
      const newWidth = resizeStartWidth.current + delta

      if (newWidth < COLLAPSE_THRESHOLD) {
        setSidebarCollapsed(true)
        try {
          localStorage.setItem('cwiki-sidebar-collapsed', '1')
        } catch {
          // localStorage 不可用时静默降级
        }
        return
      }

      const clampedWidth = Math.max(160, Math.min(320, newWidth))
      setSidebarWidth(clampedWidth)
      try {
        localStorage.setItem('cwiki-sidebar-width', String(clampedWidth))
      } catch {
        // localStorage 不可用时静默降级
      }
    }

    const handleMouseUp = () => {
      setIsResizing(false)
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [isResizing])

  const closeSheet = useCallback(() => {
    setShowMore(false)
  }, [])

  const themeLabel =
    theme === 'light'
      ? t.settings.themeLight
      : theme === 'dark'
        ? t.settings.themeDark
        : t.settings.themeSystem

  const ThemeIcon = theme === 'light' ? Sun : theme === 'dark' ? Moon : Monitor

  return (
    <div className="relative flex flex-col h-dvh overflow-hidden">
      {/* 环境光浮动光斑 */}
      <div className="ambient-orbs" aria-hidden="true" />
      <div className="flex flex-1 min-h-0">
        {/* 侧边栏：拖拽期间用零时长过渡，弹簧动画会让跟手感发黏 */}
        <motion.nav
          className="vt-sidebar hidden md:flex fixed top-0 left-0 bottom-0 flex-col z-nav sidebar-glass"
          style={{
            width: sidebarCollapsed ? 60 : sidebarWidth,
          }}
          animate={{
            width: sidebarCollapsed ? 60 : sidebarWidth,
          }}
          transition={isResizing ? TRANSITION_RESIZING : TRANSITION_SPRING}
          aria-label={t.layout.navigation}
        >
          <div className="group relative flex flex-col h-full overflow-hidden">
            {/* 拖拽调宽手柄 */}
            {!sidebarCollapsed && (
              <div
                onMouseDown={handleResizeStart}
                className="absolute right-0 top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand-400/30 transition-colors duration-150 z-10"
                style={{ touchAction: 'none' }}
              />
            )}
            {/* 品牌区 */}
            <div className="px-3.5 pt-4 pb-3">
              <div
                className={`flex items-center ${sidebarCollapsed ? 'justify-center' : 'gap-2.5'}`}
              >
                <motion.button
                  onClick={toggleSidebar}
                  whileTap={{ scale: 0.9 }}
                  transition={{ duration: duration.fast }}
                  className="hover:opacity-80 transition-opacity duration-150 cursor-pointer"
                  title={sidebarCollapsed ? t.layout.expandSidebar : t.layout.collapseSidebar}
                  aria-label={sidebarCollapsed ? t.layout.expandSidebar : t.layout.collapseSidebar}
                >
                  <CwikiBrandIcon className="transition-all duration-200 w-7 h-7" />
                </motion.button>
                <AnimatePresence initial={false}>
                  {!sidebarCollapsed && (
                    <motion.h1
                      className="text-[15px] font-semibold text-[var(--text-primary)] tracking-[-0.02em] leading-none"
                      initial={{ opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -8 }}
                      transition={{ duration: duration.normal, ease: ease.out }}
                    >
                      cwiki
                    </motion.h1>
                  )}
                </AnimatePresence>
              </div>
            </div>

            {/* 主导航 */}
            <div className="flex-1 py-3 overflow-y-auto scrollbar-thin">
              <div className="px-2 space-y-1">
                {primaryItems.map(({ to, icon: Icon, label }) => (
                  <SidebarLink
                    key={to}
                    to={to}
                    Icon={Icon}
                    label={label}
                    collapsed={sidebarCollapsed}
                    badge={
                      to === '/pending' && pendingCount > 0
                        ? { value: pendingCount, color: 'amber' }
                        : undefined
                    }
                  />
                ))}
              </div>

              <div className="my-2.5 mx-3 h-px bg-gradient-to-r from-transparent via-[var(--border-default)] to-transparent" />

              <div className="px-2 space-y-1">
                {secondaryItems.map(({ to, icon: Icon, label }) => (
                  <SidebarLink
                    key={to}
                    to={to}
                    Icon={Icon}
                    label={label}
                    collapsed={sidebarCollapsed}
                    badge={
                      to === '/review' && dueReviewCount > 0
                        ? { value: dueReviewCount, color: 'brand' }
                        : undefined
                    }
                  />
                ))}
              </div>
            </div>

            {/* 底部信息 */}
            <div className="px-2.5 pt-3 pb-3 mt-auto border-t border-[var(--border-default)]">
              <AnimatePresence mode="sync" initial={false}>
                {sidebarCollapsed ? (
                  <motion.div
                    key="collapsed"
                    initial={{ opacity: 0, y: 4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 4 }}
                    transition={{ duration: duration.fast }}
                    className="flex flex-col items-center gap-1.5"
                  >
                    <motion.button
                      onClick={toggleTheme}
                      whileTap={{ scale: 0.9 }}
                      transition={{ duration: duration.fast }}
                      className="flex items-center justify-center w-7 h-7 rounded-lg text-[var(--text-tertiary)] transition-all duration-150 hover:bg-surface-inset hover:text-[var(--text-secondary)]"
                      title={themeLabel}
                      aria-label={themeLabel}
                    >
                      <motion.span
                        key={theme}
                        initial={{ scale: 0.5, opacity: 0, rotate: -90 }}
                        animate={{ scale: 1, opacity: 1, rotate: 0 }}
                        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                        className="flex items-center justify-center"
                      >
                        <ThemeIcon size={14} />
                      </motion.span>
                    </motion.button>
                    <span
                      className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-success/60' : 'bg-danger/60'}`}
                      style={
                        online ? { animation: 'illus-pulse 2s infinite ease-in-out' } : undefined
                      }
                      title={online ? t.common.online : t.common.offline}
                    />
                  </motion.div>
                ) : (
                  <motion.div
                    key="expanded"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: duration.fast }}
                    className="flex items-center justify-between gap-2"
                  >
                    <motion.button
                      onClick={toggleTheme}
                      whileTap={{ scale: 0.97 }}
                      transition={{ duration: duration.fast }}
                      className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap text-[var(--text-tertiary)] hover:bg-surface-inset hover:text-[var(--text-secondary)] transition-all duration-150"
                      title={themeLabel}
                      aria-label={themeLabel}
                    >
                      <motion.span
                        key={theme}
                        initial={{ scale: 0.5, opacity: 0, rotate: -90 }}
                        animate={{ scale: 1, opacity: 1, rotate: 0 }}
                        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                        className="flex items-center justify-center"
                      >
                        <ThemeIcon size={13} />
                      </motion.span>
                      <span>{themeLabel}</span>
                    </motion.button>
                    <span
                      className={`flex items-center gap-1.5 px-2 text-xs font-medium whitespace-nowrap transition-all duration-150 ${
                        online ? 'text-success-fg' : 'text-danger-fg'
                      }`}
                      title={online ? t.common.online : t.common.offline}
                    >
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-success/60' : 'bg-danger/60'}`}
                        style={
                          online ? { animation: 'illus-pulse 2s infinite ease-in-out' } : undefined
                        }
                      />
                      {online ? t.common.online : t.common.offline}
                    </span>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </motion.nav>

        {/* 主内容区 */}
        <motion.main
          className="relative flex-1 min-w-0 flex flex-col overflow-hidden"
          style={MAIN_BG_STYLE}
          animate={{ marginLeft: isMobile ? 0 : sidebarCollapsed ? 60 : sidebarWidth }}
          transition={isResizing ? TRANSITION_RESIZING : TRANSITION_SPRING}
        >
          <div className="relative z-10 flex-1 min-h-0 flex flex-col">
            {/* 离线横幅不用 AnimatePresence exit：后台标签页 rAF 停转会让
                exit 动画永不完成，opacity:0 的 DOM 永久残留占布局与可访问性树 */}
            {!online && (
              <motion.div
                className="mx-4 md:mx-6 mt-4 md:mt-6 flex items-center gap-2 px-4 py-2.5 glass border-danger/20 rounded-lg text-base text-danger-fg shrink-0"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ type: 'spring', ...spring.snappy }}
                role="alert"
              >
                <WifiOff size={14} className="shrink-0" />
                <span>{t.common.offline}</span>
              </motion.div>
            )}
            <div className="flex-1 min-h-0 flex flex-col">{children}</div>
          </div>
        </motion.main>
      </div>

      {/* 移动端底部导航 */}
      <nav
        className="vt-bottom-nav md:hidden shrink-0 flex items-center gap-0.5 py-1.5 px-1 pb-safe z-nav border-t border-[var(--border-default)] sidebar-glass"
        aria-label={t.layout.navigation}
      >
        {primaryItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `relative flex flex-col items-center gap-0.5 px-3 py-1 text-xs flex-1 rounded-lg transition-all duration-150 ease-out select-none active:scale-[0.97] ${
                isActive
                  ? 'nav-glass text-[var(--text-primary)] font-medium'
                  : 'text-[var(--text-tertiary)]'
              }`
            }
            end={to === '/'}
          >
            {({ isActive }) => (
              <>
                <div className="relative">
                  <Icon size={18} strokeWidth={isActive ? 2 : 1.75} aria-hidden="true" />
                  {to === '/pending' && pendingCount > 0 && (
                    <span className="absolute -top-1.5 -right-2.5 min-w-[16px] h-4 px-1 flex items-center justify-center bg-warning text-[var(--on-accent)] text-3xs font-semibold tabular-nums rounded-full">
                      {pendingCount > 99 ? '99' : pendingCount}
                    </span>
                  )}
                </div>
                <span className="text-xs">{label}</span>
                {isActive && (
                  <motion.span
                    layoutId="bottom-nav-indicator"
                    className="absolute -bottom-0.5 left-1/2 h-[2px] w-5 -translate-x-1/2 rounded-full bg-brand-400"
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                  />
                )}
              </>
            )}
          </NavLink>
        ))}
        <motion.button
          onClick={() => setShowMore(true)}
          whileTap={{ scale: 0.97 }}
          transition={{ duration: duration.fast }}
          className="flex flex-col items-center gap-0.5 px-3 py-1 text-xs flex-1 text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] hover:bg-surface-inset rounded-lg transition-all duration-150 ease-out select-none"
        >
          <MoreHorizontal size={18} strokeWidth={1.75} aria-hidden="true" />
          <span>{t.layout.more}</span>
        </motion.button>
      </nav>

      {/* 移动端"更多"抽屉 */}
      <AnimatePresence>
        {showMore && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: duration.modal }}
              className="md:hidden fixed inset-0 z-sheet bg-surface-overlay"
              onClick={closeSheet}
            />
            <motion.div
              initial={{ y: '100%' }}
              animate={{ y: 0 }}
              exit={{ y: '100%' }}
              transition={{ type: 'spring', ...spring.layout }}
              className="md:hidden fixed bottom-0 left-0 right-0 z-sheet border-t border-[var(--glass-border)] rounded-t-xl pb-safe glass-heavy"
            >
              <div className="flex justify-center pt-2.5 pb-1">
                <div className="w-8 h-1 rounded-full bg-[var(--border-default)]" />
              </div>
              <div className="flex items-center justify-between px-4 py-2.5">
                <span className="text-sm font-semibold text-[var(--text-primary)]">
                  {t.layout.more}
                </span>
                <motion.button
                  onClick={closeSheet}
                  whileTap={{ scale: 0.9 }}
                  transition={{ duration: duration.fast }}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] rounded-lg hover:bg-surface-inset transition-all duration-150"
                  aria-label={t.common.close}
                >
                  <X size={16} aria-hidden="true" />
                </motion.button>
              </div>
              <div className="grid grid-cols-3 gap-2.5 px-4 pb-5">
                {secondaryItems.map(({ to, icon: Icon, label }, idx) => (
                  <motion.div
                    key={to}
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      delay: 0.05 + idx * 0.06,
                      duration: duration.modal,
                      ease: 'easeOut',
                    }}
                  >
                    <NavLink
                      to={to}
                      onClick={closeSheet}
                      className={({ isActive }) =>
                        `flex flex-col items-center gap-1.5 p-2.5 rounded-lg transition-all duration-150 ease-out select-none active:scale-[0.97] ${
                          isActive
                            ? 'nav-glass text-[var(--text-primary)]'
                            : 'text-[var(--text-secondary)] hover:bg-surface-inset'
                        }`
                      }
                      end={to === '/'}
                    >
                      <Icon size={18} strokeWidth={1.75} />
                      <div className="relative">
                        <span className="text-xs font-medium">{label}</span>
                        {to === '/review' && dueReviewCount > 0 && (
                          <span className="absolute -top-1.5 -right-4 min-w-[16px] h-4 px-1 flex items-center justify-center bg-brand-500 text-[var(--on-brand)] text-3xs font-semibold tabular-nums rounded-full">
                            {dueReviewCount > 99 ? '99' : dueReviewCount}
                          </span>
                        )}
                      </div>
                    </NavLink>
                  </motion.div>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

const SidebarLink = memo(function SidebarLink({
  to,
  Icon,
  label,
  collapsed,
  badge,
}: {
  to: string
  Icon: LucideIcon
  label: string
  collapsed?: boolean
  badge?: { value: number; color: 'amber' | 'brand' }
}) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => {
        const activeCls =
          'nav-glass text-[var(--text-primary)] font-semibold bg-[var(--nav-glass-active)]'
        return `relative flex items-center py-2.5 rounded-lg transition-all duration-150 ease-out select-none group ${
          collapsed ? 'justify-center px-0' : 'gap-2.5 px-3'
        } ${isActive ? activeCls : 'text-[var(--text-secondary)] hover:bg-surface-inset/60 hover:text-[var(--text-primary)]'}`
      }}
      end={to === '/'}
      title={collapsed ? label : undefined}
    >
      {({ isActive }) => (
        <>
          {/* 激活态指示条 */}
          <AnimatePresence initial={false}>
            {isActive && (
              <motion.span
                layoutId="sidebar-active-indicator"
                className="absolute left-0 top-1/2 w-[2.5px] h-4 rounded-full bg-brand-400"
                initial={{ opacity: 0, scaleY: 0 }}
                animate={{ opacity: 1, scaleY: 1, y: '-50%' }}
                exit={{ opacity: 0, scaleY: 0 }}
                transition={{ duration: duration.normal, ease: ease.out }}
              />
            )}
          </AnimatePresence>
          <motion.div
            className={`relative flex items-center justify-center w-5 h-5 shrink-0 transition-colors duration-150 ease-out ${
              isActive
                ? 'text-brand-text-active'
                : 'text-[var(--text-tertiary)] group-hover:text-[var(--text-secondary)]'
            }`}
            layout
            transition={{ type: 'spring', ...spring.dialog }}
          >
            <Icon size={collapsed ? 18 : 16} strokeWidth={isActive ? 2 : 1.75} aria-hidden="true" />
            {badge && badge.value > 0 && (
              <span
                className={`absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full ${DOT_COLORS[badge.color]}`}
              />
            )}
          </motion.div>
          <AnimatePresence initial={false}>
            {!collapsed && (
              <motion.span
                className="tracking-[0.01em] truncate text-xs"
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: 'auto' }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: duration.modal, ease: ease.out }}
                style={{ overflow: 'hidden', whiteSpace: 'nowrap' }}
              >
                {label}
              </motion.span>
            )}
          </AnimatePresence>
          <AnimatePresence initial={false}>
            {!collapsed && badge && (
              <motion.span
                className={`ml-auto min-w-[20px] h-[20px] px-1.5 flex items-center justify-center rounded-lg text-xs font-semibold tabular-nums ${BADGE_COLORS[badge.color]}`}
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: duration.normal }}
              >
                {badge.value > 99 ? '99+' : badge.value}
              </motion.span>
            )}
          </AnimatePresence>
        </>
      )}
    </NavLink>
  )
})
