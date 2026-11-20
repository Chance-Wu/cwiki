/**
 * 页面渲染冒烟测试：每个页面在「接口全部失败」与「核心接口有数据」两种路径下
 * 都应挂载完成并收敛到稳定状态（错误提示 / 空态 / 数据渲染），不允许白屏或抛错。
 *
 * 实现方式：把 ../lib/api 整体 mock 成一个自动 stub 的 Proxy —— 默认 reject
 * （命中各页已有的 ErrorAlert / catch 降级分支），用例内按需 mockResolvedValue
 * 覆写成 happy path；afterEach 清空 Map 让下个用例从全新 stub 开始。
 * 页面级 Provider（QueryClient / Router / I18n）在 renderPage 统一提供。
 */
import { describe, it, expect, vi, beforeAll, afterEach, type Mock } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { I18nProvider } from '../i18n/I18nProvider'
import { ThemeProvider } from '../theme/ThemeProvider'

const apiStub = vi.hoisted(() => {
  const stubs = new Map<string, unknown>()
  const getStub = (name: string): unknown => {
    if (!stubs.has(name)) {
      stubs.set(
        name,
        vi.fn(() => Promise.reject(new Error(`smoke: ${name} 未 mock`))),
      )
    }
    return stubs.get(name)
  }
  const api = new Proxy(
    {},
    {
      get: (_, prop) => (typeof prop === 'string' ? getStub(prop) : undefined),
    },
  )
  return { api, getStub, resetStubs: () => stubs.clear() }
})

vi.mock('../lib/api', () => ({ api: apiStub.api }))

import HomePage from '../pages/HomePage'
import InboxPage from '../pages/InboxPage'
import NotesPage from '../pages/NotesPage'
import MemoriesPage from '../pages/MemoriesPage'
import SkillsPage from '../pages/SkillsPage'
import ReviewPage from '../pages/ReviewPage'
import SettingsPage from '../pages/SettingsPage'
import GraphPage from '../pages/GraphPage'
import QualityPage from '../pages/QualityPage'
import NotFoundPage from '../pages/NotFoundPage'

function stubOf(name: string): Mock {
  return apiStub.getStub(name) as Mock
}

function renderPage(ui: ReactElement, route = '/') {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <I18nProvider>
          <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
        </I18nProvider>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

// jsdom 缺失的浏览器 API：页面组件会用到 IntersectionObserver（spotlight/懒加载）、
// ResizeObserver 与 canvas（知识图谱）。错误路径不渲染 canvas，仅做兜底 stub。
beforeAll(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null)
})

afterEach(() => {
  cleanup()
  apiStub.resetStubs()
})

describe('页面冒烟：接口全部失败（错误/降级分支）', () => {
  it('首页：降级默认值仍完整渲染', async () => {
    renderPage(<HomePage />)
    expect(
      await screen.findByRole('heading', { level: 1, name: '今日记忆活动' }),
    ).toBeInTheDocument()
  })

  it('待审页：显示错误提示与重试', async () => {
    renderPage(<InboxPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '待审' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('待整理页：显示错误提示', async () => {
    renderPage(<NotesPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '待整理' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('记忆库页：列表失败显式报错而不是误显示空态', async () => {
    renderPage(<MemoriesPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '记忆库' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText('没有找到匹配的记忆')).not.toBeInTheDocument()
  })

  it('技能页：显示错误提示', async () => {
    renderPage(<SkillsPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '技能管理' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('复习页：空队列收敛到空态/错误提示', async () => {
    renderPage(<ReviewPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '间隔复习' })).toBeInTheDocument()
  })

  it('知识图谱页：显示错误提示', async () => {
    renderPage(<GraphPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '知识图谱' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('质量分布页：显示错误提示', async () => {
    renderPage(<QualityPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '质量分布' })).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('设置页：健康与配置降级后仍渲染', async () => {
    renderPage(<SettingsPage />)
    expect(await screen.findByRole('heading', { level: 1, name: '设置' })).toBeInTheDocument()
  })

  it('404 页：渲染未找到提示', async () => {
    renderPage(<NotFoundPage />, '/no-such-page')
    expect((await screen.findAllByText('404')).length).toBeGreaterThan(0)
    expect(await screen.findByRole('link', { name: '返回首页' })).toBeInTheDocument()
  })
})

describe('页面冒烟：核心接口有数据（happy path）', () => {
  it('记忆库页：列表项与标签筛选渲染', async () => {
    stubOf('getMemories').mockResolvedValue({
      items: [
        {
          id: 'm1',
          title: '测试记忆一',
          content: '这是第一条测试记忆的内容',
          content_preview: '这是第一条测试记忆的内容',
          type: 'fact',
          status: 'active',
          confidence: 0.8,
          importance: 0.5,
          tags: ['cwiki'],
          version: 1,
          updated_at: '2026-11-01T00:00:00Z',
          last_used_at: null,
          workspace_id: null,
          workspace: '默认工作区',
          use_count: 1,
          review_status: 'new',
          mastery_level: 'new',
          source: 'mcp',
        },
      ],
      total: 1,
    })
    stubOf('listTags').mockResolvedValue({ tags: [{ name: 'cwiki', count: 1 }] })
    stubOf('getMemoryStats').mockResolvedValue({
      total: 1,
      type_distribution: { fact: 1 },
      avg_confidence: 0.8,
    })

    renderPage(<MemoriesPage />)
    expect(await screen.findByText('测试记忆一')).toBeInTheDocument()
    expect(screen.queryByText('没有找到匹配的记忆')).not.toBeInTheDocument()
    // 列表加载成功时不出现错误提示
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('待整理页：笔记列表渲染', async () => {
    stubOf('getSessionNotes').mockResolvedValue({
      items: [
        {
          id: 'n1',
          content_preview: '这是一条待整理笔记的预览内容',
          host: 'qoder',
          workspace: 'default',
          signal_type: 'fact',
          candidate_id: null,
          created_at: '2026-10-20T00:00:00Z',
        },
      ],
      total: 1,
    })

    renderPage(<NotesPage />)
    expect(await screen.findByText('这是一条待整理笔记的预览内容')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('质量分布页：分布数据与汇总卡渲染', async () => {
    stubOf('getQualityDistribution').mockResolvedValue({
      total: 20,
      averages: { confidence: 0.617, importance: 0.549, usage_count: 2.9 },
      confidence_distribution: { low: 2, medium: 10, high: 8 },
      importance_distribution: { low: 3, medium: 9, high: 8 },
      usage_distribution: { unused: 4, low: 6, medium: 5, high: 5 },
      decay_distribution: { fresh: 9, aging: 7, stale: 4 },
      duplicate_pairs: [],
      truncated: false,
    })
    // 页内的重复记忆卡有独立查询，也需给定空数据（否则会走它自己的错误分支）
    stubOf('getMemoryDuplicates').mockResolvedValue({ pairs: [], total: 0 })

    renderPage(<QualityPage />)
    expect(await screen.findByText('61.7%')).toBeInTheDocument()
    expect(await screen.findByText('平均使用次数')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
