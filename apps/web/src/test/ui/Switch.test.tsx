import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Switch } from '../../components/ui/Switch'

describe('Switch', () => {
  it('renders with label', () => {
    render(<Switch checked={false} onCheckedChange={vi.fn()} label="Dark mode" />)
    expect(screen.getByText('Dark mode')).toBeInTheDocument()
  })

  it('toggles on click', async () => {
    const onChange = vi.fn()
    render(<Switch checked={false} onCheckedChange={onChange} label="Toggle" />)
    await userEvent.click(screen.getByRole('switch'))
    expect(onChange).toHaveBeenCalledWith(true)
  })
})
