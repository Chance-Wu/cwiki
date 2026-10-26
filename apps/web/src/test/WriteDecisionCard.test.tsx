import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '../i18n/I18nProvider'
import WriteDecisionCard from '../components/config/WriteDecisionCard'

const h = vi.hoisted(() => {
  const baseData = {
    enabled: true,
    default_action: 'write' as const,
    storage_path: 'config.local.yaml',
    preview: '',
    limits: {
      max_rules: 30,
      max_description: 300,
      max_examples: 5,
      max_example_chars: 120,
      max_match_values: 20,
      max_keyword_values: 30,
      max_match_value_chars: 100,
      max_hint_chars: 800,
    },
    rules: [
      {
        id: 'skip-a',
        action: 'skip' as const,
        description: '跳过 A',
        examples: [],
        match: { workspace: [], type: [], tags: [], keyword: ['a'] },
      },
      {
        id: 'write-a',
        action: 'write' as const,
        description: '写入 A',
        examples: [],
        match: { workspace: [], type: [], tags: [], keyword: ['b'] },
      },
      {
        id: 'skip-b',
        action: 'skip' as const,
        description: '跳过 B',
        examples: [],
        match: { workspace: [], type: [], tags: [], keyword: ['c'] },
      },
      {
        id: 'update-a',
        action: 'update' as const,
        description: '更新 A',
        examples: [],
        match: { workspace: [], type: [], tags: [], keyword: ['d'] },
      },
    ],
  }
  return {
    baseData,
    data: structuredClone(baseData),
    update: vi.fn(),
    preview: vi.fn(),
    previewBody: null as unknown,
  }
})

vi.mock('../hooks/useSettings', () => ({
  useWriteDecision: () => ({
    data: h.data,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    update: { mutate: h.update, isPending: false },
  }),
  useWriteDecisionPreview: () => ({ mutate: h.preview, isPending: false }),
}))

const PREVIEW_RESULT = {
  preview: 'preview-text',
  length: 12,
  max_chars: 800,
  shown_rules: 4,
  total_rules: 4,
  truncated: false,
  skipped_rules: 0,
}

function renderCard() {
  const user = userEvent.setup()
  render(
    <I18nProvider>
      <WriteDecisionCard />
    </I18nProvider>,
  )
  return user
}

function rowOf(text: string): HTMLElement {
  return screen.getByText(text).closest('.group') as HTMLElement
}

describe('WriteDecisionCard', () => {
  beforeEach(() => {
    h.data = structuredClone(h.baseData)
    h.update.mockClear()
    h.preview.mockClear()
    h.preview.mockImplementation((body, options) => {
      h.previewBody = body
      options?.onSuccess?.(PREVIEW_RESULT)
    })
  })

  it('renders groups in matching priority order', () => {
    renderCard()

    const headings = screen.getAllByRole('heading', { level: 4 }).map((node) => node.textContent)
    expect(headings).toEqual(['不应该写入', '应该更新', '应该写入'])
  })

  it('reorders rules within their own group', async () => {
    const user = renderCard()
    expect(screen.getAllByText(/^跳过 [AB]$/).map((node) => node.textContent)).toEqual([
      '跳过 A',
      '跳过 B',
    ])

    await user.click(within(rowOf('跳过 B')).getByLabelText('上移'))

    expect(screen.getAllByText(/^跳过 [AB]$/).map((node) => node.textContent)).toEqual([
      '跳过 B',
      '跳过 A',
    ])
  })

  it('duplicates a rule with a unique id', async () => {
    const user = renderCard()

    await user.click(within(rowOf('跳过 A')).getByLabelText('复制规则'))

    expect(screen.getAllByText('跳过 A', { selector: 'span.truncate' })).toHaveLength(2)
    expect(screen.getByText('skip-a-copy')).toBeInTheDocument()
  })

  it('requests a server preview after the debounce window', async () => {
    const user = renderCard()

    await user.click(screen.getByRole('button', { name: /会话注入预览/ }))

    await waitFor(() => expect(h.preview).toHaveBeenCalledTimes(1), { timeout: 2000 })
    expect(h.previewBody).toMatchObject({ enabled: true, default_action: 'write', workspace: '' })
    expect(screen.getByText('preview-text')).toBeInTheDocument()
  })

  it('blocks saving and lists issues when a rule exceeds limits', () => {
    h.data = structuredClone(h.baseData)
    h.data.rules = [h.data.rules[0]]
    h.data.rules[0].description = 'x'.repeat(301)

    renderCard()

    expect(screen.getByText('1 条规则需要修正')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /保存规则/ })).toBeDisabled()
  })
})
