/**
 * 确定性填空：从标签与标题中挑选术语，在正文中挖空。
 *
 * 不依赖分词模型，术语来源限定为标签、标题中的反引号代码、英文标识符，
 * 以及标题按标点切出的中文短语。找不到可用术语时返回 null，
 * 调用方回退到「翻面自评」，避免生成歧义卡片。
 */

export interface Cloze {
  /** 已挖空的正文 */
  text: string
  /** 实际被挖空的术语 */
  terms: string[]
}

const MAX_TERMS = 3
const MIN_CJK_LENGTH = 2
const MAX_CJK_LENGTH = 16
const MIN_LATIN_LENGTH = 4
const CJK_PATTERN = /[\u4e00-\u9fff]/
const LATIN_WORD_PATTERN = /^[A-Za-z0-9_]+$/
const TITLE_SPLIT_PATTERN = /[，。、；：,.;:！？!?\s·\-/|（）()【】[\]]+/
// 代码块与行内代码：挖空时必须原样保留
const PROTECTED_PATTERN = /(```[\s\S]*?```|`[^`\n]*`)/g

// 只过滤完全匹配的常见虚词，避免把整句语气词当术语
const STOP_WORDS = new Set([
  '如何',
  '什么',
  '为什么',
  '怎么',
  '以及',
  '一个',
  '我们',
  '可以',
  '需要',
  '使用',
  '通过',
  '进行',
  '相关',
  '主要',
  '常见',
  '实现',
])

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function isUsableTerm(term: string): boolean {
  if (STOP_WORDS.has(term)) return false
  if (CJK_PATTERN.test(term)) {
    return term.length >= MIN_CJK_LENGTH && term.length <= MAX_CJK_LENGTH
  }
  return term.length >= MIN_LATIN_LENGTH
}

function collectCandidates(title: string, tags: string[]): string[] {
  const candidates: string[] = []
  const seen = new Set<string>()

  const push = (raw: string) => {
    const term = raw.trim()
    if (!term || !isUsableTerm(term)) return
    const key = term.toLowerCase()
    if (seen.has(key)) return
    seen.add(key)
    candidates.push(term)
  }

  tags.forEach(push)

  for (const match of title.match(/`([^`]+)`/g) ?? []) {
    push(match.slice(1, -1))
  }
  for (const match of title.match(/[A-Za-z][A-Za-z0-9_]{3,}/g) ?? []) {
    push(match)
  }
  for (const part of title.split(TITLE_SPLIT_PATTERN)) {
    push(part)
  }

  return candidates
}

/** 在非代码片段中把术语替换为下划线；每个术语全局只替换第一处。 */
function maskTerms(content: string, terms: string[]): { text: string; used: string[] } {
  const used = new Set<string>()
  const parts = content.split(PROTECTED_PATTERN)

  const masked = parts.map((part, index) => {
    // split 带捕获组时，奇数下标是受保护的代码片段
    if (index % 2 === 1) return part
    let text = part
    for (const term of terms) {
      if (used.has(term) || !text.includes(term)) continue
      if (LATIN_WORD_PATTERN.test(term)) {
        // 拉丁术语加词边界，避免 ThreadPool 误伤 ThreadPools
        const re = new RegExp(`(?<![A-Za-z0-9_])${escapeRegExp(term)}(?![A-Za-z0-9_])`)
        if (!re.test(text)) continue
        text = text.replace(re, '____')
      } else {
        text = text.replace(term, '____')
      }
      used.add(term)
    }
    return text
  })

  return { text: masked.join(''), used: Array.from(used) }
}

export function buildCloze(content: string, title: string, tags: string[] = []): Cloze | null {
  const candidates = collectCandidates(title, tags)
  if (candidates.length === 0) return null

  const present = candidates.filter((term) => content.includes(term)).slice(0, MAX_TERMS)
  if (present.length === 0) return null

  const { text, used } = maskTerms(content, present)
  const terms = present.filter((term) => used.includes(term))
  if (terms.length === 0) return null

  return { text, terms }
}
