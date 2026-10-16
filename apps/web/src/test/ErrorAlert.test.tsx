import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ErrorAlert from '../components/ErrorAlert'

describe('ErrorAlert', () => {
  it('renders error message', () => {
    render(<ErrorAlert message="Something went wrong" />)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })

  it('renders with custom className', () => {
    const { container } = render(<ErrorAlert message="Error" className="custom-class" />)
    expect(container.firstChild).toHaveClass('custom-class')
  })

  it('renders dismiss button when onDismiss is provided', () => {
    const onDismiss = vi.fn()
    render(<ErrorAlert message="Error" onDismiss={onDismiss} dismissLabel="Close" />)
    const dismissBtn = screen.getByText('Close')
    expect(dismissBtn).toBeInTheDocument()
    fireEvent.click(dismissBtn)
    expect(onDismiss).toHaveBeenCalled()
  })

  it('renders retry button when onRetry is provided', () => {
    const onRetry = vi.fn()
    render(<ErrorAlert message="Error" onRetry={onRetry} retryLabel="Try again" />)
    const retryBtn = screen.getByText('Try again')
    expect(retryBtn).toBeInTheDocument()
    fireEvent.click(retryBtn)
    expect(onRetry).toHaveBeenCalled()
  })

  it('uses default retry label when not provided', () => {
    render(<ErrorAlert message="Error" onRetry={vi.fn()} />)
    expect(screen.getByText('Retry')).toBeInTheDocument()
  })

  it('renders both retry and dismiss buttons', () => {
    render(
      <ErrorAlert
        message="Error"
        onRetry={vi.fn()}
        onDismiss={vi.fn()}
        retryLabel="Retry"
        dismissLabel="Dismiss"
      />,
    )
    expect(screen.getByText('Retry')).toBeInTheDocument()
    expect(screen.getByText('Dismiss')).toBeInTheDocument()
  })
})
