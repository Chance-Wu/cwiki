import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Input } from '../../components/ui/Input'

describe('Input', () => {
  it('renders with placeholder', () => {
    render(<Input placeholder="Search..." />)
    expect(screen.getByPlaceholderText('Search...')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<Input className="w-64" />)
    expect(container.firstChild).toHaveClass('w-64')
  })

  it('forwards ref', () => {
    const ref = { current: null } as React.MutableRefObject<HTMLInputElement | null>
    render(<Input ref={ref} />)
    expect(ref.current).toBeInstanceOf(HTMLInputElement)
  })
})
