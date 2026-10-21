import { useState, useEffect, useCallback, useRef } from 'react'
import { api, type Relation, type RelatedMemory } from '../../lib/api'
import { typeLabel, TYPE_COLORS } from '../../lib/labels'
import { useTranslation } from '../../i18n/I18nProvider'
import { TabContentSkeleton } from '../Skeleton'
import ErrorAlert from '../ErrorAlert'
import EmptyState from '../EmptyState'
import { EmptyRelations } from '../EmptyIllustrations'

interface Props {
  memoryId: string
  onNavigateToMemory?: (memoryId: string) => void
}

interface GraphNode {
  id: string
  title: string
  type: string
  x: number
  y: number
  vx: number
  vy: number
  isCenter: boolean
}

interface GraphEdge {
  source: string
  target: string
  relationType: string
  confidence: number
  relationId: string
  isForward: boolean
}

const RELATION_COLORS: Record<string, string> = {
  related: '#8b5cf6',
  supports: '#22c55e',
  contradicts: '#ef4444',
  supersedes: '#f59e0b',
  refines: '#3b82f6',
}

const RELATION_TYPES = ['related', 'supports', 'contradicts', 'supersedes', 'refines'] as const

export default function RelationGraph({ memoryId, onNavigateToMemory }: Props) {
  const { t } = useTranslation()
  const [relations, setRelations] = useState<Relation[]>([])
  const [relatedMemories, setRelatedMemories] = useState<RelatedMemory[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [viewMode, setViewMode] = useState<'graph' | 'list'>('graph')
  const svgRef = useRef<SVGSVGElement>(null)
  const animationRef = useRef<number>(0)
  const nodesRef = useRef<GraphNode[]>([])
  const [nodes, setNodes] = useState<GraphNode[]>([])
  const [graphVersion, setGraphVersion] = useState(0)
  const [edges, setEdges] = useState<GraphEdge[]>([])
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  const [dimensions] = useState({ width: 600, height: 400 })
  const [showAddForm, setShowAddForm] = useState(false)
  const [newRelationTarget, setNewRelationTarget] = useState('')
  const [newRelationType, setNewRelationType] = useState<string>('related')
  const [deletingRelationId, setDeletingRelationId] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(false)
    try {
      const data = await api.getMemoryRelations(memoryId)
      setRelations(data.relations || [])
      setRelatedMemories(data.related_memories || [])
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [memoryId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // 构建图数据
  useEffect(() => {
    if (relatedMemories.length === 0 && relations.length === 0) {
      setNodes([])
      setEdges([])
      return
    }

    const centerX = dimensions.width / 2
    const centerY = dimensions.height / 2

    const centerNode: GraphNode = {
      id: memoryId,
      title: t.memories.currentMemory || '当前记忆',
      type: 'center',
      x: centerX,
      y: centerY,
      vx: 0,
      vy: 0,
      isCenter: true,
    }

    const newNodes: GraphNode[] = [centerNode]
    const angleStep = (2 * Math.PI) / Math.max(relatedMemories.length, 1)
    const radius = 150

    relatedMemories.forEach((m, i) => {
      const angle = angleStep * i - Math.PI / 2
      newNodes.push({
        id: m.id,
        title: m.title,
        type: m.type,
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
        vx: 0,
        vy: 0,
        isCenter: false,
      })
    })

    const newEdges: GraphEdge[] = relations.map((r) => {
      const isForward = r.source_memory_id === memoryId
      return {
        source: r.source_memory_id,
        target: r.target_memory_id,
        relationType: r.relation_type,
        confidence: r.confidence,
        relationId: r.id,
        isForward,
      }
    })

    setNodes(newNodes)
    nodesRef.current = newNodes
    setEdges(newEdges)
    setGraphVersion((v) => v + 1)
  }, [memoryId, relatedMemories, relations, dimensions, t.memories.currentMemory])

  // 力导向模拟
  useEffect(() => {
    if (nodesRef.current.length <= 1 || viewMode !== 'graph') return

    const simulate = () => {
      const next = nodesRef.current.map((n) => ({ ...n }))
      const centerX = dimensions.width / 2
      const centerY = dimensions.height / 2

      for (let i = 0; i < next.length; i++) {
        for (let j = i + 1; j < next.length; j++) {
          const dx = next[j].x - next[i].x
          const dy = next[j].y - next[i].y
          const dist = Math.sqrt(dx * dx + dy * dy) || 1
          const force = 500 / (dist * dist)
          const fx = (dx / dist) * force
          const fy = (dy / dist) * force
          if (!next[i].isCenter) {
            next[i].vx -= fx
            next[i].vy -= fy
          }
          if (!next[j].isCenter) {
            next[j].vx += fx
            next[j].vy += fy
          }
        }
      }

      for (const edge of edges) {
        const source = next.find((n) => n.id === edge.source)
        const target = next.find((n) => n.id === edge.target)
        if (!source || !target) continue
        const dx = target.x - source.x
        const dy = target.y - source.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (dist - 120) * 0.01
        const fx = (dx / dist) * force
        const fy = (dy / dist) * force
        if (!source.isCenter) {
          source.vx += fx
          source.vy += fy
        }
        if (!target.isCenter) {
          target.vx -= fx
          target.vy -= fy
        }
      }

      for (const node of next) {
        if (node.isCenter) continue
        const dx = centerX - node.x
        const dy = centerY - node.y
        node.vx += dx * 0.001
        node.vy += dy * 0.001
      }

      let motion = 0
      for (const node of next) {
        if (node.isCenter) continue
        node.vx *= 0.9
        node.vy *= 0.9
        const px = node.x
        const py = node.y
        node.x += node.vx
        node.y += node.vy
        node.x = Math.max(40, Math.min(dimensions.width - 40, node.x))
        node.y = Math.max(40, Math.min(dimensions.height - 40, node.y))
        motion += (node.x - px) ** 2 + (node.y - py) ** 2
      }

      nodesRef.current = next
      setNodes(next)
      if (motion > 0.05) {
        animationRef.current = requestAnimationFrame(simulate)
      }
    }

    animationRef.current = requestAnimationFrame(simulate)
    return () => cancelAnimationFrame(animationRef.current)
  }, [graphVersion, edges, viewMode, dimensions])

  const handleCreateRelation = async () => {
    if (!newRelationTarget || !newRelationType) return
    try {
      await api.createMemoryRelation(memoryId, newRelationTarget, newRelationType)
      setShowAddForm(false)
      setNewRelationTarget('')
      setNewRelationType('related')
      fetchData()
    } catch {
      // 错误由 ErrorAlert 处理
    }
  }

  const handleDeleteRelation = async (relationId: string) => {
    setDeletingRelationId(relationId)
    try {
      await api.deleteMemoryRelation(memoryId, relationId)
      fetchData()
    } catch {
      // 错误处理
    } finally {
      setDeletingRelationId(null)
    }
  }

  // 计算箭头路径（缩短到节点边缘）
  const getArrowPath = (
    sx: number,
    sy: number,
    tx: number,
    ty: number,
    sourceR: number,
    targetR: number,
  ) => {
    const dx = tx - sx
    const dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy) || 1
    const ux = dx / dist
    const uy = dy / dist
    const x1 = sx + ux * sourceR
    const y1 = sy + uy * sourceR
    const x2 = tx - ux * (targetR + 6)
    const y2 = ty - uy * (targetR + 6)
    return { x1, y1, x2, y2, ux, uy }
  }

  if (loading) return <TabContentSkeleton />
  if (error)
    return (
      <ErrorAlert
        message={t.memories.loadRelationsFailed}
        onRetry={fetchData}
        retryLabel={t.common.retry}
      />
    )
  if (relations.length === 0 && relatedMemories.length === 0 && !showAddForm)
    return (
      <div className="space-y-4">
        <EmptyState illustration={<EmptyRelations />} message={t.memories.noRelations} />
        <button
          onClick={() => setShowAddForm(true)}
          className="w-full py-2 text-sm text-brand-500 border border-dashed border-brand-300 rounded-lg hover:bg-brand-badge-bg transition-colors"
        >
          {t.memories.addRelation}
        </button>
      </div>
    )

  return (
    <div className="space-y-4">
      {/* 视图切换 + 添加按钮 */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setViewMode('graph')}
          className={`px-3 py-1 text-sm rounded-lg transition-colors ${
            viewMode === 'graph'
              ? 'bg-brand-500 text-white'
              : 'bg-surface-inset text-[var(--text-secondary)] hover:bg-brand-badge-bg'
          }`}
        >
          {t.memories.graphView}
        </button>
        <button
          onClick={() => setViewMode('list')}
          className={`px-3 py-1 text-sm rounded-lg transition-colors ${
            viewMode === 'list'
              ? 'bg-brand-500 text-white'
              : 'bg-surface-inset text-[var(--text-secondary)] hover:bg-brand-badge-bg'
          }`}
        >
          {t.memories.listView}
        </button>
        <div className="flex-1" />
        {!showAddForm && (
          <button
            onClick={() => setShowAddForm(true)}
            className="px-3 py-1 text-sm rounded-lg bg-brand-badge-bg text-brand-500 hover:bg-brand-100 transition-colors"
          >
            + {t.memories.addRelation}
          </button>
        )}
      </div>

      {/* 创建关系表单 */}
      {showAddForm && (
        <div className="p-3 bg-surface-inset rounded-lg border border-[var(--border-default)] space-y-3">
          <h4 className="text-sm font-medium text-[var(--text-primary)]">
            {t.memories.createRelationTitle}
          </h4>
          <div className="space-y-2">
            <label className="block text-xs text-[var(--text-secondary)]">
              {t.memories.selectTargetMemory}
            </label>
            <select
              value={newRelationTarget}
              onChange={(e) => setNewRelationTarget(e.target.value)}
              className="w-full px-2 py-1.5 text-sm bg-surface-card border border-[var(--border-default)] rounded-lg text-[var(--text-primary)]"
            >
              <option value="">{t.memories.selectTargetMemory}</option>
              {/* 可以输入其他记忆 ID */}
            </select>
            <input
              type="text"
              value={newRelationTarget}
              onChange={(e) => setNewRelationTarget(e.target.value)}
              placeholder="或输入记忆 ID"
              className="w-full px-2 py-1.5 text-sm bg-surface-card border border-[var(--border-default)] rounded-lg text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)]"
            />
          </div>
          <div>
            <label className="block text-xs text-[var(--text-secondary)] mb-1">
              {t.memories.selectRelationType}
            </label>
            <div className="flex flex-wrap gap-1.5">
              {RELATION_TYPES.map((type) => (
                <button
                  key={type}
                  onClick={() => setNewRelationType(type)}
                  className={`px-2 py-1 text-xs rounded-lg border transition-colors ${
                    newRelationType === type
                      ? 'border-brand-500 bg-brand-badge-bg text-brand-500'
                      : 'border-[var(--border-default)] text-[var(--text-secondary)] hover:bg-brand-badge-bg'
                  }`}
                  style={newRelationType === type ? { borderColor: RELATION_COLORS[type] } : {}}
                >
                  <span
                    className="inline-block w-2 h-2 rounded-full mr-1"
                    style={{ backgroundColor: RELATION_COLORS[type] }}
                  />
                  {type}
                </button>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleCreateRelation}
              disabled={!newRelationTarget || !newRelationType}
              className="px-3 py-1 text-sm bg-brand-500 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-brand-600 transition-colors"
            >
              {t.common.save || '创建'}
            </button>
            <button
              onClick={() => {
                setShowAddForm(false)
                setNewRelationTarget('')
              }}
              className="px-3 py-1 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              {t.common.cancel || '取消'}
            </button>
          </div>
        </div>
      )}

      {viewMode === 'graph' && relations.length > 0 ? (
        <div className="relative bg-surface-inset rounded-xl border border-[var(--border-default)] overflow-hidden">
          <svg
            ref={svgRef}
            width={dimensions.width}
            height={dimensions.height}
            className="w-full h-auto"
            viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
          >
            <defs>
              {Object.entries(RELATION_COLORS).map(([type, color]) => (
                <marker
                  key={type}
                  id={`arrow-${type}`}
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
                </marker>
              ))}
            </defs>

            {/* 边（带箭头） */}
            {edges.map((edge, i) => {
              const source = nodes.find((n) => n.id === edge.source)
              const target = nodes.find((n) => n.id === edge.target)
              if (!source || !target) return null
              const color = RELATION_COLORS[edge.relationType] || '#8b5cf6'
              const isHighlighted = hoveredNode === edge.source || hoveredNode === edge.target
              const sourceR = source.isCenter ? 24 : 18
              const targetR = target.isCenter ? 24 : 18
              const { x1, y1, x2, y2 } = getArrowPath(
                source.x,
                source.y,
                target.x,
                target.y,
                sourceR,
                targetR,
              )
              return (
                <g key={i}>
                  <line
                    x1={x1}
                    y1={y1}
                    x2={x2}
                    y2={y2}
                    stroke={color}
                    strokeWidth={isHighlighted ? 3 : 2}
                    strokeOpacity={isHighlighted ? 1 : 0.5}
                    strokeDasharray={edge.relationType === 'contradicts' ? '5,5' : undefined}
                    markerEnd={`url(#arrow-${edge.relationType})`}
                  />
                  {isHighlighted && (
                    <text
                      x={(source.x + target.x) / 2}
                      y={(source.y + target.y) / 2 - 8}
                      textAnchor="middle"
                      className="text-xs fill-[var(--text-secondary)]"
                    >
                      {edge.relationType} ({Math.round(edge.confidence * 100)}%)
                    </text>
                  )}
                </g>
              )
            })}

            {/* 节点 */}
            {nodes.map((node) => {
              const isHovered = hoveredNode === node.id
              const radius = node.isCenter ? 24 : 18
              const color = node.isCenter
                ? '#8b5cf6'
                : TYPE_COLORS[node.type]?.includes('bg-')
                  ? '#8b5cf6'
                  : '#6b7280'

              return (
                <g
                  key={node.id}
                  onMouseEnter={() => setHoveredNode(node.id)}
                  onMouseLeave={() => setHoveredNode(null)}
                  onClick={() => !node.isCenter && onNavigateToMemory?.(node.id)}
                  className={node.isCenter ? '' : 'cursor-pointer'}
                >
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={radius + (isHovered ? 4 : 0)}
                    fill={color}
                    fillOpacity={isHovered ? 0.3 : 0.15}
                    className="transition-all duration-150"
                  />
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={radius}
                    fill={color}
                    stroke={isHovered ? color : 'transparent'}
                    strokeWidth={2}
                  />
                  <text
                    x={node.x}
                    y={node.y + radius + 16}
                    textAnchor="middle"
                    className="text-xs fill-[var(--text-primary)] pointer-events-none"
                  >
                    {node.title.length > 12 ? node.title.slice(0, 12) + '...' : node.title}
                  </text>
                </g>
              )
            })}
          </svg>

          {/* 图例 */}
          <div className="absolute bottom-2 right-2 bg-surface-card/90 backdrop-blur-sm rounded-lg p-2 text-xs space-y-1">
            {Object.entries(RELATION_COLORS).map(([type, color]) => (
              <div key={type} className="flex items-center gap-2">
                <div className="w-4 h-0.5" style={{ backgroundColor: color }} />
                <span className="text-[var(--text-secondary)]">{type}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* 列表视图 */}
      {viewMode === 'list' && (
        <div className="space-y-4">
          {relatedMemories.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
                {t.memories.relatedMemories}
              </h4>
              <div className="space-y-3">
                {relatedMemories.map((m) => (
                  <div
                    key={m.id}
                    onClick={() => onNavigateToMemory?.(m.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onNavigateToMemory?.(m.id)
                      }
                    }}
                    className="group relative flex items-center gap-2 p-2 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs hover:bg-brand-badge-bg cursor-pointer transition-all duration-150 active:scale-[0.98]"
                  >
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-4 rounded-full bg-brand-400 opacity-40 transition-opacity duration-150" />
                    <span
                      className={`px-1.5 py-0.5 text-sm rounded-lg border ${TYPE_COLORS[m.type] || 'bg-surface-inset text-[var(--text-secondary)] border-[var(--border-default)]'}`}
                    >
                      {typeLabel(t.common, m.type)}
                    </span>
                    <span className="text-sm text-[var(--text-primary)] truncate flex-1">
                      {m.title}
                    </span>
                    <svg
                      className="w-4 h-4 text-[var(--text-tertiary)] shrink-0"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 5l7 7-7 7"
                      />
                    </svg>
                  </div>
                ))}
              </div>
            </div>
          )}
          {relations.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-[var(--text-secondary)] mb-2">
                {t.memories.relationType}
              </h4>
              <div className="space-y-3">
                {relations.map((r) => {
                  const isSource = r.source_memory_id === memoryId
                  const otherId = isSource ? r.target_memory_id : r.source_memory_id
                  const other = relatedMemories.find((m) => m.id === otherId)
                  return (
                    <div
                      key={r.id}
                      className="flex items-center gap-3 text-base p-2 bg-surface-inset rounded-lg border border-[var(--border-default)] shadow-warm-xs"
                    >
                      <span
                        className="px-1.5 py-0.5 text-sm rounded-lg border"
                        style={{
                          borderColor: RELATION_COLORS[r.relation_type] || '#8b5cf6',
                          color: RELATION_COLORS[r.relation_type] || '#8b5cf6',
                        }}
                      >
                        {isSource ? '→' : '←'} {r.relation_type}
                      </span>
                      <span className="text-sm text-[var(--text-primary)] truncate flex-1">
                        {other?.title || otherId.slice(0, 8)}
                      </span>
                      <span className="text-[var(--text-secondary)] text-xs tabular-nums">
                        {t.memories.relationConfidence}: {Math.round(r.confidence * 100)}%
                      </span>
                      <button
                        onClick={() => handleDeleteRelation(r.id)}
                        disabled={deletingRelationId === r.id}
                        className="p-1 text-[var(--text-tertiary)] hover:text-danger-fg transition-colors disabled:opacity-50"
                        title={t.memories.deleteRelation}
                      >
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        >
                          <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                        </svg>
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
