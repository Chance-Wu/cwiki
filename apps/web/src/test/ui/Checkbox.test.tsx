import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Checkbox } from '../../components/ui/Checkbox'

describe('Checkbox', () => {
  it('renders with label', () => {
    render(<Checkbox checked={false} onCheckedChange={vi.fn()} label="Accept" />)
    expect(screen.getByText('Accept')).toBeInTheDocument()
  })

  it('toggles on click', async () => {
    const onChange = vi.fn()
    render(<Checkbox checked={false} onCheckedChange={onChange} label="Check" />)
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith(true)
  })
})
