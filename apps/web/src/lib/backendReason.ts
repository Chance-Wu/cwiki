import type { TranslationKeys } from '../i18n/I18nProvider'
import { translate } from '../i18n/I18nProvider'

// 后端机器生成的诊断 reason（quality_gate / health）是英文模式化字符串，
// 且存量数据已以英文入库——前端按已知模式翻译可同时覆盖存量与新数据。
// 未知模式原样透传；后端新增 reason 模式时需同步维护此映射。
// 仅中文界面翻译，英文界面直接展示原文。

const DIMENSION_LABELS: Record<string, string> = {
  stable: '稳定性',
  reusable: '可复用性',
  actionable: '可操作性',
  scoped: '范围确定性',
  evidence_backed: '证据充分性',
}

function mapDimensions(csv: string): string {
  return csv
    .split(',')
    .map((s) => DIMENSION_LABELS[s.trim()] ?? s.trim())
    .join('、')
}

function translatePart(part: string, t: TranslationKeys): string {
  let m = part.match(/^Strengths: (.+)$/)
  if (m) return translate(t.memories.reasonStrengths, { items: mapDimensions(m[1]) })

  m = part.match(/^Weaknesses: (.+)$/)
  if (m) return translate(t.memories.reasonWeaknesses, { items: mapDimensions(m[1]) })

  if (part === 'Balanced candidate') return t.memories.reasonBalanced

  m = part.match(/^(\d+) unresolved conflict\(s\)$/)
  if (m) return translate(t.memories.reasonConflicts, { n: m[1] })

  m = part.match(/^Low utility score: ([\d.]+)$/)
  if (m) return translate(t.memories.reasonLowUtility, { score: m[1] })

  m = part.match(/^Low confidence: ([\d.]+)$/)
  if (m) return translate(t.memories.reasonLowConfidence, { score: m[1] })

  m = part.match(/^High confidence: ([\d.]+)$/)
  if (m) return translate(t.memories.reasonHighConfidence, { score: m[1] })

  if (part === 'Pinned: permanent memory floor applied') return t.memories.reasonPinned

  m = part.match(/^Not used for (\d+) days$/)
  if (m) return translate(t.memories.reasonNotUsed, { n: m[1] })

  m = part.match(/^Never used in (\d+) days$/)
  if (m) return translate(t.memories.reasonNeverUsed, { n: m[1] })

  return part
}

export function translateBackendReason(text: string, t: TranslationKeys, locale: string): string {
  if (locale !== 'zh') return text
  return text
    .split('; ')
    .map((p) => translatePart(p.trim(), t))
    .join('；')
}
