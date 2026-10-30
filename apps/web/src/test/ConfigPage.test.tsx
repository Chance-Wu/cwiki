import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '../i18n/I18nProvider'
import ConfigPage from '../pages/ConfigPage'

const h = vi.hoisted(() => {
  const config = {
    app: { debug: false },
    parasitic_evolution: {
      memory_gap_detection_enabled: true,
      proactive_push_enabled: true,
      memory_relations_enabled: true,
      agent_profile_enabled: true,
      memory_version_tracking_enabled: true,
      auto_consolidate_enabled: true,
      review_reminders_enabled: true,
      mastery_coupled_decay_enabled: true,
      entity_extraction_enabled: true,
      write_time_conflict_enabled: true,
      auto_merge_enabled: false,
      auto_merge_threshold: 0.92,
      episodic_retrieval_enabled: false,
      auto_relation_enabled: true,
      auto_relation_threshold: 0.6,
      auto_relation_max_per_memory: 5,
      relation_auto_edge_ttl_days: 30,
    },
    memory: {
      title_max_length: 80,
      consolidate_threshold: 0.85,
      similarity_threshold: 0.7,
      relation_merge_threshold: 0.95,
      relation_update_threshold: 0.8,
      relation_conflict_threshold: 0.6,
      priority_discard_threshold: 0.35,
      priority_low_threshold: 0.65,
      priority_high_threshold: 0.85,
      auto_create_workspace: false,
      duplicate_exact_threshold: 0.98,
      duplicate_possible_threshold: 0.85,
      submit_dedup_scan_limit: 1000,
      submit_dedup_cross_workspace: false,
    },
    performance: {
      context_cache_ttl: 60,
      context_cache_max_size: 128,
      context_token_budget: 2000,
      dedup_top_k: 20,
      merge_suggestions_threshold: 0.5,
      auto_consolidate_limit: 200,
      auto_consolidate_top_k: 20,
    },
    retrieval: {
      bm25_weight: 0.6,
      vector_weight: 0.4,
      reranker_rrf_weight: 0.38,
      reranker_semantic_weight: 0.15,
      reranker_confidence_weight: 0.1,
      reranker_importance_weight: 0.12,
      reranker_freshness_weight: 0.1,
      reranker_usage_weight: 0.06,
      reranker_intent_weight: 0.09,
      reranker_key_term_bonus: 0.08,
    },
    mcp: {
      max_retries: 3,
      retry_backoff_seconds: 1,
    },
    scheduler: {
      auto_relation_interval_hours: 6,
      relation_ttl_check_interval_hours: 24,
    },
    system_info: {
      embedding_model: 'bge-small-zh',
      embedding_dimensions: 512,
      database_url: 'cwiki-data/cwiki.db',
      api_host: '127.0.0.1',
      api_port: 5172,
      memory_dir: './cwiki-data',
      config_path: 'config.yaml',
    },
  }
  return { config, save: vi.fn() }
})

vi.mock('../hooks/useSettings', () => ({
  useConfig: () => ({
    data: h.config,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    patchConfig: { mutate: h.save, isPending: false },
  }),
  useWriteDecision: () => ({
    data: {
      enabled: true,
      default_action: 'write',
      rules: [],
      storage_path: 'config.local.yaml',
      preview: '',
      limits: {
        max_rules: 30,
        max_description: 300,
        max_examples: 5,
        max_example_chars: 120,
        max_match_values: 20,
        max_keyword_values: 30,
        max_regex_values: 20,
        max_match_value_chars: 100,
        max_hint_chars: 800,
      },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    update: { mutate: vi.fn(), isPending: false },
  }),
  useWriteDecisionPreview: () => ({ mutate: vi.fn(), isPending: false }),
  useWritePolicy: () => ({
    data: {
      enabled: false,
      rules: [],
      storage_path: 'config.local.yaml',
      limits: {
        max_rules: 50,
        max_match_values: 20,
        max_keyword_values: 30,
        max_regex_values: 20,
        max_match_value_chars: 100,
      },
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    update: { mutate: vi.fn(), isPending: false },
  }),
}))

class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

function renderPage() {
  const user = userEvent.setup()
  render(
    <I18nProvider>
      <ConfigPage />
    </I18nProvider>,
  )
  return user
}

function debugRow(): HTMLElement {
  return screen.getByText('调试模式').closest('.justify-between') as HTMLElement
}

describe('ConfigPage', () => {
  beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
    Element.prototype.scrollIntoView = vi.fn()
    h.save.mockReset()
    h.save.mockImplementation((_config, options) => options?.onSuccess?.())
  })

  it('shows the workflow overview and section navigation', () => {
    renderPage()

    expect(screen.getByText('配置流程')).toBeInTheDocument()
    for (const label of [
      '写入规则',
      '写入后审核',
      '功能开关',
      '记忆阈值',
      '性能与检索',
      '运行时与调度',
      '高级',
    ]) {
      expect(screen.getByRole('link', { name: label })).toBeInTheDocument()
    }
  })

  it('opens the glossary with plain-language terms', async () => {
    const user = renderPage()

    await user.click(screen.getByRole('button', { name: '术语说明' }))

    expect(await screen.findByText('记忆概念速查')).toBeInTheDocument()
    expect(screen.getByText('准入（写入规则）')).toBeInTheDocument()
    expect(screen.getByText('RRF 排名融合')).toBeInTheDocument()
  })

  it('shows a sticky save bar after edits and can discard them', async () => {
    const user = renderPage()

    await user.click(within(debugRow()).getByRole('switch'))
    expect(await screen.findByText('1 项修改未保存')).toBeInTheDocument()
    const featuresLink = screen.getByRole('link', { name: /功能开关/ })
    expect(within(featuresLink).getByTitle('有未保存修改')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '撤销修改' }))
    await waitFor(() => expect(screen.queryByText('1 项修改未保存')).not.toBeInTheDocument())
  })

  it('blocks saving when a parameter is out of range', async () => {
    const user = renderPage()
    const row = screen.getByText('标题长度上限').closest('.justify-between') as HTMLElement
    const input = within(row).getByRole('textbox')

    await user.clear(input)
    await user.type(input, '0')

    expect(await screen.findByText('1 个参数超出允许范围')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存参数' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: '1 个参数超出允许范围' }))
    expect(input).toHaveFocus()
  })

  it('saves the edited parameters through the config API', async () => {
    const user = renderPage()

    await user.click(within(debugRow()).getByRole('switch'))
    await user.click(await screen.findByRole('button', { name: '保存参数' }))

    expect(h.save).toHaveBeenCalledTimes(1)
    expect(h.save.mock.calls[0][0].app.debug).toBe(true)
    await waitFor(() => expect(screen.queryByText('1 项修改未保存')).not.toBeInTheDocument())
  })
})
