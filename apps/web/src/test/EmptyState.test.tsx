import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { InboxIcon } from 'lucide-react'
import EmptyState from '../components/EmptyState'

describe('EmptyState', () => {
  it('renders message', () => {
    render(<EmptyState message="No items found" />)
    expect(screen.getByText('No items found')).toBeInTheDocument()
  })

  it('renders without icon', () => {
    render(<EmptyState message="Empty" />)
    const container = screen.getByText('Empty').parentElement
    expect(container?.querySelector('.text-gray-300')).not.toBeInTheDocument()
  })

  it('renders with icon', () => {
    render(<EmptyState icon={<InboxIcon data-testid="icon" />} message="No inbox items" />)
    expect(screen.getByTestId('icon')).toBeInTheDocument()
    expect(screen.getByText('No inbox items')).toBeInTheDocument()
  })
})
