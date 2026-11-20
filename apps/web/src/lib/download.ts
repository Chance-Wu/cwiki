/**
 * 触发浏览器下载一个 Blob，统一处理 objectURL 的创建与回收。
 * 供 GraphPage（PNG/JSON 导出）、MemoriesPage（批量导出）、WeeklyReview（周报导出）共用。
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
