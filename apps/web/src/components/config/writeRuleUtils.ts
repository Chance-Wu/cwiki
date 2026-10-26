import type {
  WriteDecisionLimits,
  WriteDecisionRule,
  WritePolicyRule,
  WritePolicyRuleMatch,
} from '../../lib/api'
import type { WritePolicyLimits } from '../../lib/api/types'
import { translate } from '../../i18n/I18nProvider'

export function isEmptyMatch(match: WritePolicyRuleMatch): boolean {
  return (
    match.workspace.length === 0 &&
    match.type.length === 0 &&
    match.tags.length === 0 &&
    match.keyword.length === 0
  )
}

export function validateRuleIds(
  rules: Array<{ id: string }>,
  copy: Record<string, string>,
): Array<string | null> {
  const seen = new Set<string>()
  return rules.map((rule) => {
    const id = rule.id.trim()
    if (!id) return copy.writePolicyRuleIdRequired
    if (!/^[A-Za-z0-9._-]+$/.test(id)) return copy.writePolicyRuleIdInvalid
    const key = id.toLowerCase()
    if (seen.has(key)) return copy.writePolicyRuleIdDuplicate
    seen.add(key)
    return null
  })
}

// 写入策略卡没有服务端 limits 字段，沿用同一组硬限制
export const DEFAULT_MATCH_LIMITS = {
  workspace: 20,
  type: 20,
  tags: 20,
  keyword: 30,
  valueChars: 100,
}

// 旧服务端响应缺少 limits 时的兜底，与服务端默认值保持一致
export const DEFAULT_WRITE_DECISION_LIMITS: WriteDecisionLimits = {
  max_rules: 30,
  max_description: 300,
  max_examples: 5,
  max_example_chars: 120,
  max_match_values: 20,
  max_keyword_values: 40,
  max_match_value_chars: 100,
  max_hint_chars: 800,
}

export interface RuleLimitIssue {
  index: number
  ruleId: string
  messages: string[]
}

/** 收集超出服务端硬限制的问题，用于保存前阻断与摘要提示。 */
export function collectLimitIssues(
  rules: WriteDecisionRule[],
  copy: Record<string, string>,
  limits: WriteDecisionLimits,
): RuleLimitIssue[] {
  const issues: RuleLimitIssue[] = []

  rules.forEach((rule, index) => {
    const messages: string[] = []
    if (rule.description.length > limits.max_description) {
      messages.push(translate(copy.writeDecisionIssueDescription, { max: limits.max_description }))
    }
    if (rule.examples.length > limits.max_examples) {
      messages.push(translate(copy.writeDecisionIssueExamples, { max: limits.max_examples }))
    }
    if (rule.examples.some((item) => item.length > limits.max_example_chars)) {
      messages.push(
        translate(copy.writeDecisionIssueExampleLength, { max: limits.max_example_chars }),
      )
    }

    const match = rule.match
    const counts: Array<[keyof WritePolicyRuleMatch, number]> = [
      ['workspace', limits.max_match_values],
      ['type', limits.max_match_values],
      ['tags', limits.max_match_values],
      ['keyword', limits.max_keyword_values],
    ]
    for (const [field, max] of counts) {
      if (match[field].length > max) {
        messages.push(
          translate(copy.writeDecisionIssueMatchCount, {
            field: copy[`writePolicy${field[0].toUpperCase()}${field.slice(1)}`] ?? field,
            max,
          }),
        )
      }
    }
    if (matchValues(match).some((value) => value.length > limits.max_match_value_chars)) {
      messages.push(
        translate(copy.writeDecisionIssueMatchValue, { max: limits.max_match_value_chars }),
      )
    }

    if (messages.length > 0) {
      issues.push({
        index,
        ruleId: rule.id.trim() || copy.writePolicyUntitled,
        messages,
      })
    }
  })

  return issues
}

function matchValues(match: WritePolicyRuleMatch): string[] {
  return [...match.workspace, ...match.type, ...match.tags, ...match.keyword]
}

export const DEFAULT_WRITE_POLICY_LIMITS: WritePolicyLimits = {
  max_rules: 50,
  max_match_values: 20,
  max_keyword_values: 40,
  max_match_value_chars: 100,
}

/** 写入策略卡的限值校验：匹配字段数量与字符长度。 */
export function collectWritePolicyLimitIssues(
  rules: WritePolicyRule[],
  copy: Record<string, string>,
  limits: WritePolicyLimits = DEFAULT_WRITE_POLICY_LIMITS,
): RuleLimitIssue[] {
  const issues: RuleLimitIssue[] = []

  rules.forEach((rule, index) => {
    const messages: string[] = []
    const match = rule.match
    const counts: Array<[keyof WritePolicyRuleMatch, number]> = [
      ['workspace', limits.max_match_values],
      ['type', limits.max_match_values],
      ['tags', limits.max_match_values],
      ['keyword', limits.max_keyword_values],
    ]
    for (const [field, max] of counts) {
      if (match[field].length > max) {
        messages.push(
          translate(copy.writeDecisionIssueMatchCount, {
            field: copy[`writePolicy${field[0].toUpperCase()}${field.slice(1)}`] ?? field,
            max,
          }),
        )
      }
    }
    if (matchValues(match).some((value) => value.length > limits.max_match_value_chars)) {
      messages.push(
        translate(copy.writeDecisionIssueMatchValue, { max: limits.max_match_value_chars }),
      )
    }

    if (messages.length > 0) {
      issues.push({
        index,
        ruleId: rule.id.trim() || copy.writePolicyUntitled,
        messages,
      })
    }
  })

  return issues
}
