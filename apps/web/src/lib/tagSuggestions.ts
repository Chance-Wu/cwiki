export interface TagMergeSuggestion {
  /** 需要合并的标签名（含建议保留者） */
  tags: string[]
  /** 建议保留的写法 */
  target: string
  /** 差异类型，用于提示文案 */
  reason: 'case' | 'spacing' | 'plural'
}

interface TagLike {
  name: string
  count: number
}

/** 归一化：去空白、小写；英文且长度 >3 时去掉复数尾 s。 */
function normalizeKey(name: string): string {
  const lower = name.trim().toLowerCase().replace(/\s+/g, '')
  if (/^[a-z]+$/.test(lower) && lower.length > 3 && lower.endsWith('s')) {
    return lower.slice(0, -1)
  }
  return lower
}

/**
 * 从标签列表推断可合并项：大小写、空白、单复数差异。
 * 只给建议，不自动合并；调用方确认后走既有 merge API。
 */
export function suggestTagMerges(tags: TagLike[]): TagMergeSuggestion[] {
  const groups = new Map<string, TagLike[]>()
  for (const tag of tags) {
    const key = normalizeKey(tag.name)
    const list = groups.get(key) ?? []
    list.push(tag)
    groups.set(key, list)
  }

  const suggestions: TagMergeSuggestion[] = []
  for (const list of groups.values()) {
    if (list.length < 2) continue
    const names = list.map((item) => item.name)
    if (new Set(names).size < 2) continue

    // 保留使用次数最多的写法；并列时取更短的，通常更规范
    const sorted = [...list].sort((a, b) => b.count - a.count || a.name.length - b.name.length)
    const target = sorted[0].name

    const trimmedLower = new Set(names.map((name) => name.trim().toLowerCase()))
    let reason: TagMergeSuggestion['reason'] = 'plural'
    if (names.some((name) => name !== name.trim())) {
      reason = 'spacing'
    } else if (trimmedLower.size === 1 && names.some((name) => name !== name.toLowerCase())) {
      reason = 'case'
    }

    suggestions.push({ tags: names, target, reason })
  }

  return suggestions
}
