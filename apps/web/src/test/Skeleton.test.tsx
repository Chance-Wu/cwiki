import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { Skeleton, ListSkeleton, TabContentSkeleton, CardSkeleton } from '../components/Skeleton'

describe('Skeleton', () => {
  it('renders with default className', () => {
    const { container } = render(<Skeleton />)
    const el = container.firstChild as HTMLElement
    expect(el).toHaveClass('shimmer')
    expect(el).toHaveClass('rounded-lg')
  })

  it('renders with custom className', () => {
    const { container } = render(<Skeleton className="h-4 w-20" />)
    const el = container.firstChild as HTMLElement
    expect(el).toHaveClass('h-4')
    expect(el).toHaveClass('w-20')
  })
})

describe('ListSkeleton', () => {
  it('renders default 5 rows', () => {
    render(<ListSkeleton />)
    const cards = document.querySelectorAll('.glass.rounded-lg')
    expect(cards.length).toBe(5)
  })

  it('renders custom number of rows', () => {
    render(<ListSkeleton rows={3} />)
    const cards = document.querySelectorAll('.glass.rounded-lg')
    expect(cards.length).toBe(3)
  })

  it('each row contains skeleton elements', () => {
    render(<ListSkeleton rows={2} />)
    const shimmers = document.querySelectorAll('.shimmer')
    expect(shimmers.length).toBeGreaterThan(0)
  })
})

describe('TabContentSkeleton', () => {
  it('renders 4 rows', () => {
    render(<TabContentSkeleton />)
    const shimmers = document.querySelectorAll('.shimmer')
    expect(shimmers.length).toBe(8)
  })
})

describe('CardSkeleton', () => {
  it('renders default 4 cards', () => {
    render(<CardSkeleton />)
    const cards = document.querySelectorAll('.glass.rounded-lg')
    expect(cards.length).toBe(4)
  })

  it('renders custom number of cards', () => {
    render(<CardSkeleton cols={6} />)
    const cards = document.querySelectorAll('.glass.rounded-lg')
    expect(cards.length).toBe(6)
  })

  it('applies correct grid class for cols', () => {
    const { container } = render(<CardSkeleton cols={3} />)
    const grid = container.firstChild as HTMLElement
    expect(grid).toHaveClass('md:grid-cols-3')
  })
})
