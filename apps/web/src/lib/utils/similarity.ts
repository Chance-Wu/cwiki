/**
 * 根据相似度返回颜色类名（用于徽章、标签等）
 * @param similarity 相似度 0-1 或百分比 0-100
 * @param includeBg 是否包含背景色（默认 true）
 * @param includeBorder 是否包含边框色（默认 false）
 */
export function getSimilarityColor(
  similarity: number,
  includeBg = true,
  includeBorder = false,
): string {
  // 归一化到 0-1
  const sim = similarity > 1 ? similarity / 100 : similarity
  const percent = Math.round(sim * 100)

  let textClass: string
  let bgClass: string
  let borderClass: string

  if (percent >= 90) {
    textClass = 'text-success-fg'
    bgClass = 'bg-success/10'
    borderClass = 'border-success/20'
  } else if (percent >= 75) {
    textClass = 'text-warning-fg'
    bgClass = 'bg-warning/10'
    borderClass = 'border-warning/20'
  } else {
    textClass = 'text-[var(--text-secondary)]'
    bgClass = 'bg-[var(--surface-inset)]'
    borderClass = 'border-[var(--border-default)]'
  }

  const classes = [textClass]
  if (includeBg) classes.push(bgClass)
  if (includeBorder) classes.push(borderClass)

  return classes.join(' ')
}
