import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import zh from '../i18n/locales/zh'

vi.mock('../components/MarkdownContent', () => ({
  default: ({ content }: { content: string }) => <div data-testid="md">{content}</div>,
}))

import { ReviewCard } from '../components/ReviewCard'

const item = {
  memory_id: 'm1',
  title: '示例记忆标题',
  content: '这是用于断言可见性的正文内容。',
  memory_type: 'fact',
  source: null,
  confidence: 0.8,
  updated_at: null,
  ease_factor: 2.5,
  interval_days: 3,
  repetitions: 2,
  next_review: '2026-11-01T00:00:00Z',
  last_review: null,
  days_overdue: 0,
  mastery_level: 'new',
  total_reviews: 2,
}

const renderCard = (mode: 'learn' | 'test', showAnswer: boolean) =>
  render(
    <ReviewCard
      item={item}
      showAnswer={showAnswer}
      onShowAnswer={() => {}}
      t={zh}
      locale="zh"
      mode={mode}
    />,
  )

describe('ReviewCard 学习/测试模式', () => {
  it('学习模式下正文直接可见，无需翻面', () => {
    renderCard('learn', false)
    expect(screen.getByTestId('md')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: zh.review.showAnswer })).toBeNull()
  })

  it('测试模式下先隐藏正文，翻面后才显示', async () => {
    const { rerender } = renderCard('test', false)
    expect(screen.queryByTestId('md')).toBeNull()
    expect(screen.getByRole('button', { name: zh.review.showAnswer })).toBeInTheDocument()

    rerender(
      <ReviewCard
        item={item}
        showAnswer={true}
        onShowAnswer={() => {}}
        t={zh}
        locale="zh"
        mode="test"
      />,
    )
    expect(await screen.findByTestId('md')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: zh.review.showAnswer })).toBeNull()
  })
})
