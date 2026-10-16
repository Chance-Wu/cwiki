import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactElement } from 'react'
import { Select } from '../../components/ui/Select'
import { I18nProvider } from '../../i18n/I18nProvider'

const options = [
  { value: 'a', label: 'Option A' },
  { value: 'b', label: 'Option B' },
  { value: 'c', label: 'Option C' },
]

// Select 内部调用 useTranslation，需包裹 I18nProvider
const renderWithI18n = (ui: ReactElement) => render(<I18nProvider>{ui}</I18nProvider>)

describe('Select', () => {
  it('renders with placeholder', () => {
    renderWithI18n(<Select options={options} value="" onChange={vi.fn()} placeholder="Choose..." />)
    expect(screen.getByText('Choose...')).toBeInTheDocument()
  })

  it('renders selected value', () => {
    renderWithI18n(<Select options={options} value="b" onChange={vi.fn()} />)
    expect(screen.getByText('Option B')).toBeInTheDocument()
  })

  it('renders trigger with combobox role', () => {
    renderWithI18n(<Select options={options} value="" onChange={vi.fn()} placeholder="Choose..." />)
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('renders with icon', () => {
    renderWithI18n(
      <Select
        options={options}
        value=""
        onChange={vi.fn()}
        icon={<span data-testid="test-icon">★</span>}
      />,
    )
    expect(screen.getByTestId('test-icon')).toBeInTheDocument()
  })
})
