export interface AlignedDiffRow {
  left: { type: 'unchanged' | 'removed' | 'empty'; content: string; lineNum?: number }
  right: { type: 'unchanged' | 'added' | 'empty'; content: string; lineNum?: number }
}

export function computeAlignedRows(oldText: string, newText: string): AlignedDiffRow[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')
  const m = oldLines.length
  const n = newLines.length

  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
      }
    }
  }

  const raw: Array<{ type: 'unchanged' | 'removed' | 'added'; content: string }> = []
  let i = m,
    j = n
  const stack: Array<{ type: 'unchanged' | 'removed' | 'added'; content: string }> = []

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      stack.push({ type: 'unchanged', content: oldLines[i - 1] })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      stack.push({ type: 'added', content: newLines[j - 1] })
      j--
    } else if (i > 0) {
      stack.push({ type: 'removed', content: oldLines[i - 1] })
      i--
    }
  }
  while (stack.length > 0) raw.push(stack.pop()!)

  const rows: AlignedDiffRow[] = []
  let oldLineNum = 0
  let newLineNum = 0
  let k = 0

  while (k < raw.length) {
    if (raw[k].type === 'unchanged') {
      oldLineNum++
      newLineNum++
      rows.push({
        left: { type: 'unchanged', content: raw[k].content, lineNum: oldLineNum },
        right: { type: 'unchanged', content: raw[k].content, lineNum: newLineNum },
      })
      k++
    } else {
      const removedBlock: string[] = []
      const addedBlock: string[] = []
      while (k < raw.length && raw[k].type === 'removed') {
        removedBlock.push(raw[k].content)
        k++
      }
      while (k < raw.length && raw[k].type === 'added') {
        addedBlock.push(raw[k].content)
        k++
      }
      const maxLen = Math.max(removedBlock.length, addedBlock.length)
      for (let idx = 0; idx < maxLen; idx++) {
        if (idx < removedBlock.length && idx < addedBlock.length) {
          oldLineNum++
          newLineNum++
          rows.push({
            left: { type: 'removed', content: removedBlock[idx], lineNum: oldLineNum },
            right: { type: 'added', content: addedBlock[idx], lineNum: newLineNum },
          })
        } else if (idx < removedBlock.length) {
          oldLineNum++
          rows.push({
            left: { type: 'removed', content: removedBlock[idx], lineNum: oldLineNum },
            right: { type: 'empty', content: '' },
          })
        } else {
          newLineNum++
          rows.push({
            left: { type: 'empty', content: '' },
            right: { type: 'added', content: addedBlock[idx], lineNum: newLineNum },
          })
        }
      }
    }
  }

  return rows
}
