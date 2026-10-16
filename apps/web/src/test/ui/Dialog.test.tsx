import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { Dialog } from '../../components/ui/Dialog'
import { I18nProvider } from '../../i18n/I18nProvider'

// Dialog 内部调用 useTranslation，需包裹 I18nProvider
const renderWithI18n = (ui: ReactElement) => render(<I18nProvider>{ui}</I18nProvider>)

describe('Dialog', () => {
  it('renders nothing when open is false', () => {
    renderWithI18n(
      <Dialog open={false} onOpenChange={vi.fn()} title="Test">
        <div>Content</div>
      </Dialog>,
    )
    expect(screen.queryByText('Content')).not.toBeInTheDocument()
  })

  it('renders children when open is true', () => {
    renderWithI18n(
      <Dialog open={true} onOpenChange={vi.fn()} title="Test">
        <div>Dialog content</div>
      </Dialog>,
    )
    expect(screen.getByText('Dialog content')).toBeInTheDocument()
  })

  it('renders title', () => {
    renderWithI18n(
      <Dialog open={true} onOpenChange={vi.fn()} title="My Title">
        <div>Content</div>
      </Dialog>,
    )
    expect(screen.getByText('My Title')).toBeInTheDocument()
  })

  it('calls onOpenChange(false) on overlay click', async () => {
    const onOpenChange = vi.fn()
    renderWithI18n(
      <Dialog open={true} onOpenChange={onOpenChange} title="Test">
        <div>Content</div>
      </Dialog>,
    )
    const overlay = document.querySelector('[data-radix-dialog-overlay]')
    if (overlay) {
      await userEvent.click(overlay)
      expect(onOpenChange).toHaveBeenCalledWith(false)
    }
  })
})
