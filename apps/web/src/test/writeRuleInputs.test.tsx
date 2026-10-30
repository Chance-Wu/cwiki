import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ListInput, MatchChips, MatchEditor } from '../components/config/writeRuleShared'
import {
  collectLimitIssues,
  collectWritePolicyLimitIssues,
} from '../components/config/writeRuleUtils'
import type { WriteDecisionLimits, WriteDecisionRule } from '../lib/api'
import type { WritePolicyLimits, WritePolicyRule } from '../lib/api/types'

const COPY: Record<string, string> = {
  writePolicyWorkspace: '工作区',
  writePolicyType: '类型',
  writePolicyTags: '标签',
  writePolicyKeyword: '关键词',
  writePolicyUntitled: '未命名规则',
  writeDecisionIssueDescription: '说明超过 {max} 字符',
  writeDecisionIssueExamples: '示例最多 {max} 条',
  writeDecisionIssueExampleLength: '单条示例不能超过 {max} 字符',
  writeDecisionIssueMatchCount: '{field} 最多 {max} 个值',
  writeDecisionIssueMatchValue: '单个匹配值不能超过 {max} 字符',
}

const LIMITS: WriteDecisionLimits = {
  max_rules: 30,
  max_description: 300,
  max_examples: 5,
  max_example_chars: 120,
  max_match_values: 2,
  max_keyword_values: 3,
  max_regex_values: 2,
  max_match_value_chars: 5,
  max_hint_chars: 800,
}

function ListHarness({ initial = [], max }: { initial?: string[]; max?: number }) {
  const [values, setValues] = useState(initial)
  return (
    <ListInput
      label="关键词"
      value={values}
      onChange={setValues}
      placeholder="输入后回车"
      hint="提示"
      max={max}
    />
  )
}

describe('ListInput', () => {
  it('adds tags on Enter and comma', async () => {
    const user = userEvent.setup()
    render(<ListHarness />)
    const input = screen.getByRole('textbox', { name: '关键词' })

    await user.type(input, 'alpha{Enter}')
    await user.type(input, 'beta,')
    expect(screen.getByText('alpha')).toBeInTheDocument()
    expect(screen.getByText('beta')).toBeInTheDocument()
  })

  it('splits pasted multi-value text', async () => {
    const user = userEvent.setup()
    render(<ListHarness />)
    const input = screen.getByRole('textbox', { name: '关键词' })

    await user.click(input)
    await user.paste('gamma\ndelta')
    expect(screen.getByText('gamma')).toBeInTheDocument()
    expect(screen.getByText('delta')).toBeInTheDocument()
  })

  it('respects the max value count', async () => {
    const user = userEvent.setup()
    render(<ListHarness max={2} />)
    const input = screen.getByRole('textbox', { name: '关键词' })

    await user.type(input, 'a{Enter}b{Enter}c{Enter}')
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
    expect(screen.queryByText('c')).not.toBeInTheDocument()
    expect(screen.getByText('2/2')).toBeInTheDocument()
  })

  it('removes the last tag with Backspace on empty input', async () => {
    const user = userEvent.setup()
    render(<ListHarness initial={['one', 'two']} />)
    const input = screen.getByRole('textbox', { name: '关键词' })

    await user.click(input)
    await user.keyboard('{Backspace}')
    await waitFor(() => expect(screen.queryByText('two')).not.toBeInTheDocument())
    expect(screen.getByText('one')).toBeInTheDocument()
  })
})

describe('MatchChips', () => {
  it('collapses long values into +N', () => {
    render(
      <MatchChips
        copy={COPY}
        match={{ workspace: [], type: [], tags: [], keyword: ['a', 'b', 'c', 'd', 'e'], regex: [] }}
      />,
    )
    expect(screen.getByText('a, b, c +2')).toBeInTheDocument()
  })
})

describe('collectLimitIssues', () => {
  const rule = (patch: Partial<WriteDecisionRule>): WriteDecisionRule => ({
    id: 'r1',
    action: 'write',
    description: '',
    examples: [],
    match: { workspace: [], type: [], tags: [], keyword: [], regex: [] },
    ...patch,
  })

  it('flags overlong description, examples and match values', () => {
    const longRule = rule({
      description: 'x'.repeat(LIMITS.max_description + 1),
      examples: ['y'.repeat(LIMITS.max_example_chars + 1)],
      match: { workspace: [], type: [], tags: [], keyword: ['z'.repeat(6)], regex: [] },
    })

    const issues = collectLimitIssues([longRule], COPY, LIMITS)

    expect(issues).toHaveLength(1)
    expect(issues[0].ruleId).toBe('r1')
    expect(issues[0].messages).toEqual(
      expect.arrayContaining([
        '说明超过 300 字符',
        '单条示例不能超过 120 字符',
        '单个匹配值不能超过 5 字符',
      ]),
    )
  })

  it('flags match value counts per field', () => {
    const crowded = rule({
      match: {
        workspace: ['a', 'b', 'c'],
        type: [],
        tags: [],
        keyword: ['1', '2', '3', '4'],
        regex: [],
      },
    })

    const issues = collectLimitIssues([crowded], COPY, LIMITS)

    expect(issues[0].messages).toEqual(
      expect.arrayContaining(['工作区 最多 2 个值', '关键词 最多 3 个值']),
    )
  })

  it('returns no issues within limits', () => {
    expect(collectLimitIssues([rule({ description: 'ok' })], COPY, LIMITS)).toEqual([])
  })
})

describe('collectWritePolicyLimitIssues', () => {
  const POLICY_LIMITS: WritePolicyLimits = {
    max_rules: 50,
    max_match_values: 2,
    max_keyword_values: 3,
    max_regex_values: 2,
    max_match_value_chars: 5,
  }

  const policyRule = (patch: Partial<WritePolicyRule>): WritePolicyRule => ({
    id: 'r1',
    action: 'review',
    reason: null,
    match: { workspace: [], type: [], tags: [], keyword: [], regex: [] },
    ...patch,
  })

  it('flags overlong match values', () => {
    const longRule = policyRule({
      match: { workspace: [], type: [], tags: [], keyword: ['z'.repeat(6)], regex: [] },
    })

    const issues = collectWritePolicyLimitIssues([longRule], COPY, POLICY_LIMITS)

    expect(issues).toHaveLength(1)
    expect(issues[0].ruleId).toBe('r1')
    expect(issues[0].messages).toEqual(expect.arrayContaining(['单个匹配值不能超过 5 字符']))
  })

  it('flags match value counts per field', () => {
    const crowded = policyRule({
      match: {
        workspace: ['a', 'b', 'c'],
        type: [],
        tags: [],
        keyword: ['1', '2', '3', '4'],
        regex: [],
      },
    })

    const issues = collectWritePolicyLimitIssues([crowded], COPY, POLICY_LIMITS)

    expect(issues[0].messages).toEqual(
      expect.arrayContaining(['工作区 最多 2 个值', '关键词 最多 3 个值']),
    )
  })

  it('returns no issues within limits', () => {
    expect(collectWritePolicyLimitIssues([policyRule({})], COPY, POLICY_LIMITS)).toEqual([])
  })
})

describe('MatchEditor', () => {
  it('renders the regex field and emits regex values separately', async () => {
    const user = userEvent.setup()
    const onMatchChange = vi.fn()

    render(
      <MatchEditor
        match={{ workspace: [], type: [], tags: [], keyword: [], regex: [] }}
        onMatchChange={onMatchChange}
        hint="提示"
        warning="告警"
        copy={{
          ...COPY,
          writePolicyMatch: '匹配条件',
          writePolicyRegex: '正则',
          writePolicyRegexHint: '按原文匹配',
        }}
        limits={{ workspace: 2, type: 2, tags: 2, keyword: 2, regex: 2, valueChars: 50 }}
      />,
    )

    const input = screen.getByRole('textbox', { name: '正则' })
    await user.type(input, '(?i)^x')
    await user.keyboard('{Enter}')

    expect(onMatchChange).toHaveBeenCalledWith('regex', ['(?i)^x'])
    expect(screen.getByText('按原文匹配')).toBeInTheDocument()
  })
})
