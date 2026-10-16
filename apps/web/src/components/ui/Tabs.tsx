import * as RadixTabs from '@radix-ui/react-tabs'
import { type ReactNode, createContext, useContext } from 'react'
import { twMerge } from 'tailwind-merge'
import { motion } from 'framer-motion'
import { duration, ease } from '../../lib/motion'

const TabsContext = createContext<{ value: string | undefined }>({ value: undefined })

interface TabsProps {
  defaultValue: string
  value?: string
  onValueChange?: (value: string) => void
  children: ReactNode
  className?: string
}

export function Tabs({ defaultValue, value, onValueChange, children, className }: TabsProps) {
  const activeValue = value ?? defaultValue
  return (
    <TabsContext.Provider value={{ value: activeValue }}>
      <RadixTabs.Root
        defaultValue={defaultValue}
        value={value}
        onValueChange={onValueChange}
        className={className}
      >
        {children}
      </RadixTabs.Root>
    </TabsContext.Provider>
  )
}

export function TabsList({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <RadixTabs.List
      className={twMerge('relative flex gap-0 border-b border-[var(--glass-border)]', className)}
    >
      {children}
    </RadixTabs.List>
  )
}

export function TabsTrigger({
  value,
  children,
  className,
}: {
  value: string
  children: ReactNode
  className?: string
}) {
  const { value: activeValue } = useContext(TabsContext)
  const isActive = activeValue === value

  return (
    <RadixTabs.Trigger
      value={value}
      className={twMerge(
        'relative px-4 py-2 text-sm font-medium text-[var(--text-secondary)] transition-all duration-150 select-none active:scale-[0.97]',
        'hover:text-[var(--text-primary)]',
        'data-[state=active]:text-[var(--text-primary)]',
        'focus-visible:ring-2 focus-visible:ring-brand-200 focus-visible:outline-none',
        className,
      )}
    >
      {children}
      {isActive && (
        <motion.span
          layoutId="tabs-indicator"
          className="absolute bottom-0 left-0 right-0 h-0.5 bg-brand-500 rounded-full"
          transition={{ type: 'spring', stiffness: 500, damping: 35 }}
        />
      )}
    </RadixTabs.Trigger>
  )
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string
  children: ReactNode
  className?: string
}) {
  return (
    <RadixTabs.Content value={value} className={className}>
      {children}
    </RadixTabs.Content>
  )
}

/**
 * 带交叉淡入过渡动画的标签内容。
 * 填满父容器高度；激活内容绝对定位以驱动动画，
 * 高内容溢出时滚动（overflow-y: auto）。
 */
export function AnimatedTabsContent({
  value,
  children,
  className,
}: {
  value: string
  children: ReactNode
  className?: string
}) {
  const { value: activeValue } = useContext(TabsContext)
  const isActive = activeValue === value

  return (
    <div
      className="relative min-h-0 overflow-hidden"
      style={{ flex: isActive ? '1 1 0%' : '0 0 0px' }}
    >
      <RadixTabs.Content value={value} asChild forceMount>
        <motion.div
          key={value}
          initial={isActive ? { opacity: 0, y: 6 } : false}
          animate={{ opacity: isActive ? 1 : 0, y: isActive ? 0 : -6 }}
          transition={{ duration: duration.slow, ease: ease.bounce }}
          className={className}
          style={{
            position: 'absolute',
            inset: 0,
            overflowY: 'auto',
            overflowX: 'hidden',
            pointerEvents: isActive ? 'auto' : 'none',
          }}
        >
          {children}
        </motion.div>
      </RadixTabs.Content>
    </div>
  )
}
