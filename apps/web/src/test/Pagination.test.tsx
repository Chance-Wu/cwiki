import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Pagination from '../components/Pagination'
import { I18nProvider } from '../i18n/I18nProvider'

function renderWithI18n(ui: React.ReactElement) {
  return render(<I18nProvider>{ui}</I18nProvider>)
}

describe('Pagination', () => {
  it('renders nothing when total <= pageSize', () => {
    const { container } = renderWithI18n(
      <Pagination
        total={10}
        page={1}
        pageSize={10}
        onPageChange={() => {}}
        onPageSizeChange={() => {}}
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders pagination when total > pageSize', () => {
    renderWithI18n(
      <Pagination
        total={50}
        page={1}
        pageSize={10}
        onPageChange={() => {}}
        onPageSizeChange={() => {}}
      />,
    )
    expect(screen.getByText('首页')).toBeInTheDocument()
    expect(screen.getByText('上一页')).toBeInTheDocument()
    expect(screen.getByText('下一页')).toBeInTheDocument()
    expect(screen.getByText('末页')).toBeInTheDocument()
  })

  it('disables prev buttons on first page', () => {
    renderWithI18n(
      <Pagination
        total={50}
        page={1}
        pageSize={10}
        onPageChange={() => {}}
        onPageSizeChange={() => {}}
      />,
    )
    expect(screen.getByText('首页')).toBeDisabled()
    expect(screen.getByText('上一页')).toBeDisabled()
    expect(screen.getByText('下一页')).not.toBeDisabled()
    expect(screen.getByText('末页')).not.toBeDisabled()
  })

  it('disables next buttons on last page', () => {
    renderWithI18n(
      <Pagination
        total={50}
        page={5}
        pageSize={10}
        onPageChange={() => {}}
        onPageSizeChange={() => {}}
      />,
    )
    expect(screen.getByText('首页')).not.toBeDisabled()
    expect(screen.getByText('上一页')).not.toBeDisabled()
    expect(screen.getByText('下一页')).toBeDisabled()
    expect(screen.getByText('末页')).toBeDisabled()
  })

  it('calls onPageChange when clicking next', () => {
    const onPageChange = vi.fn()
    renderWithI18n(
      <Pagination
        total={50}
        page={1}
        pageSize={10}
        onPageChange={onPageChange}
        onPageSizeChange={() => {}}
      />,
    )
    fireEvent.click(screen.getByText('下一页'))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('calls onPageChange(1) when changing page size', () => {
    const onPageChange = vi.fn()
    const onPageSizeChange = vi.fn()
    renderWithI18n(
      <Pagination
        total={50}
        page={3}
        pageSize={10}
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />,
    )
    fireEvent.change(screen.getByDisplayValue('10 条/页'), { target: { value: '20' } })
    expect(onPageSizeChange).toHaveBeenCalledWith(20)
    expect(onPageChange).toHaveBeenCalledWith(1)
  })
})
