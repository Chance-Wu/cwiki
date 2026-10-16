import { type HTMLAttributes, type ReactNode } from 'react'
import { twMerge } from 'tailwind-merge'
import { useSpotlight } from '../../hooks/useSpotlight'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
}

export function Card({ children, className, ...props }: CardProps) {
  const spotlightRef = useSpotlight()

  return (
    <div
      ref={spotlightRef}
      className={twMerge(
        'glass relative overflow-hidden rounded-2xl',
        'transition-[box-shadow,border-color,transform] duration-300 ease-spring',
        'hover:-translate-y-0.5 hover:border-[var(--glass-border-hover)] hover:shadow-glass-lg',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
