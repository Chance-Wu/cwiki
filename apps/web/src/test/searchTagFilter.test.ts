import { describe, expect, it } from 'vitest'
import { filterByTags } from '../hooks/useSearch'

const items = [
  { id: '1', tags: ['redis', 'cluster'] },
  { id: '2', tags: ['redis'] },
  { id: '3', tags: [] },
  { id: '4' },
  { id: '5', tags: "['redis', 'cluster']" },
]

describe('filterByTags', () => {
  it('无标签条件时返回全部结果', () => {
    expect(filterByTags(items)).toEqual(items)
    expect(filterByTags(items, [])).toEqual(items)
  })

  it('多个标签按 AND 语义过滤', () => {
    expect(filterByTags(items, ['redis', 'cluster'])).toEqual([items[0], items[4]])
    expect(filterByTags(items, ['redis'])).toEqual([items[0], items[1], items[4]])
  })

  it('兼容文件索引返回的 Python repr 标签字符串', () => {
    expect(filterByTags(items, ['redis', 'cluster'])).toEqual([items[0], items[4]])
  })

  it('标签比较不区分大小写', () => {
    expect(filterByTags(items, ['REDIS', 'Cluster'])).toEqual([items[0], items[4]])
  })

  it('缺失 tags 字段的结果不会误命中', () => {
    expect(filterByTags(items, ['redis'])).not.toContainEqual(items[3])
  })
})
