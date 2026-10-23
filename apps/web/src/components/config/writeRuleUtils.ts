import type { WritePolicyRuleMatch } from '../../lib/api'

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
