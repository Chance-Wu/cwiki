import { useState, useEffect, useRef, useCallback, lazy, Suspense } from 'react'
import { motion } from 'framer-motion'
import { Network } from 'lucide-react'
import { api, type FileMemory } from '../lib/api'
import { useDefaultWorkspace } from '../hooks/useDashboard'
import PageShell from '../components/PageShell'
import PageTitle from '../components/PageTitle'
import ErrorAlert from '../components/ErrorAlert'
import LoadingWrapper from '../components/LoadingWrapper'
import { CardSkeleton } from '../components/Skeleton'

const MemoryDetailModal = lazy(() => import('../components/memory/MemoryDetailModal'))

interface GraphNode {
  id: string
  title: string
  type: string
  confidence: number
  importance: number
  degree: number
  is_isolated: boolean
  x: number
  y: number
  vx: number
  vy: number
}

interface GraphEdge {
  id: string
  source: string
  target: string
  type: string
  confidence: number
  strength: number
}

interface ThemeColors {
  textPrimary: string
  textTertiary: string
  edgeDefault: string
  nodeStroke: string
  gridDot: string
  labelHalo: string
}

const RELATION_COLORS: Record<string, string> = {
  related: '#8b5cf6',
  supports: '#22c55e',
  contradicts: '#ef4444',
  supersedes: '#f59e0b',
  refines: '#3b82f6',
}

const TYPE_COLORS: Record<string, string> = {
  fact: '#3b82f6',
  decision: '#8b5cf6',
  pattern: '#22c55e',
  lesson: '#f59e0b',
  issue: '#ef4444',
  procedure: '#06b6d4',
}

const TYPE_LABELS: Record<string, string> = {
  fact: '事实',
  decision: '决策',
  pattern: '模式',
  lesson: '教训',
  issue: '问题',
  procedure: '流程',
}

const RELATION_LABELS: Record<string, string> = {
  related: '关联',
  supports: '支持',
  contradicts: '矛盾',
  supersedes: '取代',
  refines: '细化',
}

const SIM_FRAMES = 240
const KICK_FRAMES = 60
const SETTLE_FRAMES = 45
const ENERGY_THRESHOLD = 0.35

function readThemeColors(dark: boolean): ThemeColors {
  const css = getComputedStyle(document.documentElement)
  const get = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    textPrimary: get('--text-primary', dark ? '#f5f3f0' : '#18181B'),
    textTertiary: get('--text-tertiary', dark ? '#8a8279' : '#A1A1AA'),
    edgeDefault: get('--text-tertiary', dark ? '#8a8279' : '#A1A1AA'),
    nodeStroke: dark ? 'rgba(255,255,255,0.35)' : 'rgba(255,255,255,0.9)',
    gridDot: dark ? 'rgba(255,255,255,0.05)' : 'rgba(24,24,27,0.06)',
    labelHalo: dark ? 'rgba(0,0,0,0.85)' : 'rgba(255,255,255,0.92)',
  }
}

const radiusOf = (node: GraphNode) => Math.min(7 + node.degree * 1.2, 26)
const hitRadiusOf = (node: GraphNode) => radiusOf(node) + 5

export default function GraphPage() {
  const workspaceQuery = useDefaultWorkspace()
  const [canvasEl, setCanvasEl] = useState<HTMLCanvasElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const nodesRef = useRef<GraphNode[]>([])
  const edgesRef = useRef<GraphEdge[]>([])
  const neighborsRef = useRef<Map<string, string[]>>(new Map())
  const hoveredRef = useRef<string | null>(null)
  const selectedRef = useRef<string | null>(null)
  const themeRef = useRef<{ dark: boolean; colors: ThemeColors } | null>(null)
  const simFramesRef = useRef(0)
  const frameCountRef = useRef(0)
  const runningRef = useRef(false)
  const rafRef = useRef(0)
  const gridRef = useRef<{ w: number; h: number; path: Path2D } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)
  const [hoveredNode, setHoveredNode] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<string | null>(null)
  const [detailMemory, setDetailMemory] = useState<FileMemory | null>(null)
  const [stats, setStats] = useState({
    total: 0,
    edges: 0,
    isolated: 0,
    avgDegree: '0.00',
    totalActive: 0,
    truncated: false,
  })

  const workspaceId = workspaceQuery.data

  useEffect(() => {
    if (!workspaceId) return

    const fetchGraph = async () => {
      try {
        setLoading(true)
        const data = await api.getKnowledgeGraph(workspaceId, 200)

        const count = data.nodes.length
        // Golden-angle 散布，避免对称死板；按节点量放大初始半径防挤压
        const rx = Math.min(70 + count * 2.2, 430)
        const ry = Math.min(50 + count * 1.6, 215)
        const initializedNodes: GraphNode[] = data.nodes.map((n, i) => ({
          ...n,
          x: 600 + Math.cos(i * 2.399963) * rx,
          y: 300 + Math.sin(i * 2.399963) * ry,
          vx: 0,
          vy: 0,
        }))

        const neighbors = new Map<string, string[]>()
        for (const edge of data.edges) {
          const targets = neighbors.get(edge.source) ?? []
          targets.push(edge.target)
          neighbors.set(edge.source, targets)
          const sources = neighbors.get(edge.target) ?? []
          sources.push(edge.source)
          neighbors.set(edge.target, sources)
        }

        nodesRef.current = initializedNodes
        edgesRef.current = data.edges
        neighborsRef.current = neighbors
        frameCountRef.current = 0

        const isolated = initializedNodes.filter((n) => n.is_isolated).length
        const avgDegree = count > 0 ? (data.edges.length * 2) / count : 0
        setStats({
          total: count,
          edges: data.edges.length,
          isolated,
          avgDegree: avgDegree.toFixed(2),
          totalActive: data.total_active ?? count,
          truncated: Boolean(data.truncated),
        })

        setError(false)
      } catch (err) {
        console.error('Failed to fetch graph:', err)
        setError(true)
      } finally {
        setLoading(false)
      }
    }

    fetchGraph()
  }, [workspaceId])

  const attachCanvas = useCallback((el: HTMLCanvasElement | null) => {
    canvasRef.current = el
    setCanvasEl(el)
  }, [])

  const getTheme = useCallback(() => {
    const dark = document.documentElement.classList.contains('dark')
    if (!themeRef.current || themeRef.current.dark !== dark) {
      themeRef.current = { dark, colors: readThemeColors(dark) }
    }
    return themeRef.current
  }, [])

  const simulate = useCallback(() => {
    const nodes = nodesRef.current
    const canvas = canvasRef.current
    if (nodes.length === 0 || !canvas) return
    const width = canvas.clientWidth || 1200
    const height = canvas.clientHeight || 600

    const neighbors = neighborsRef.current
    const byId = new Map(nodes.map((n) => [n.id, n]))

    let energy = 0
    const newNodes = nodes.map((node) => {
      let fx = 0,
        fy = 0

      for (const other of nodes) {
        if (other.id === node.id) continue
        const dx = node.x - other.x
        const dy = node.y - other.y
        const distSq = dx * dx + dy * dy || 1
        const dist = Math.sqrt(distSq)
        const force = 6000 / distSq
        fx += (dx / dist) * force
        fy += (dy / dist) * force
      }

      for (const otherId of neighbors.get(node.id) ?? []) {
        const other = byId.get(otherId)
        if (!other) continue
        const dx = other.x - node.x
        const dy = other.y - node.y
        const dist = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (dist - 110) * 0.012
        fx += (dx / dist) * force
        fy += (dy / dist) * force
      }

      fx += (width / 2 - node.x) * 0.0015
      fy += (height / 2 - node.y) * 0.0015

      const vx = (node.vx + fx) * 0.86
      const vy = (node.vy + fy) * 0.86
      energy += vx * vx + vy * vy
      return { ...node, vx, vy, x: node.x + vx, y: node.y + vy }
    })

    nodesRef.current = newNodes
    frameCountRef.current++
    if (frameCountRef.current > SETTLE_FRAMES && energy < nodes.length * ENERGY_THRESHOLD) {
      simFramesRef.current = 0
    }
  }, [])

  const renderScene = useCallback(
    (ctx: CanvasRenderingContext2D, cssW: number, cssH: number) => {
      const { colors } = getTheme()
      const nodes = nodesRef.current
      const edges = edgesRef.current
      const hovered = hoveredRef.current
      const selected = selectedRef.current
      const dpr = window.devicePixelRatio || 1

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, cssW, cssH)

      let grid = gridRef.current
      if (!grid || grid.w !== cssW || grid.h !== cssH) {
        const path = new Path2D()
        const gap = 26
        for (let gx = gap; gx < cssW; gx += gap) {
          for (let gy = gap; gy < cssH; gy += gap) {
            path.rect(gx - 0.5, gy - 0.5, 1, 1)
          }
        }
        grid = { w: cssW, h: cssH, path }
        gridRef.current = grid
      }
      ctx.fillStyle = colors.gridDot
      ctx.fill(grid.path)

      const focus = selected
        ? new Set<string>([selected, ...(neighborsRef.current.get(selected) ?? [])])
        : null

      const nodeMap = new Map<string, GraphNode>()
      for (const n of nodes) nodeMap.set(n.id, n)

      for (const edge of edges) {
        const source = nodeMap.get(edge.source)
        const target = nodeMap.get(edge.target)
        if (!source || !target) continue

        let alpha: number
        if (focus) {
          alpha = focus.has(edge.source) && focus.has(edge.target) ? 0.85 : 0.05
        } else if (hovered && (edge.source === hovered || edge.target === hovered)) {
          alpha = 0.9
        } else {
          alpha = hovered ? 0.12 : 0.3
        }

        const dx = target.x - source.x
        const dy = target.y - source.y
        const len = Math.sqrt(dx * dx + dy * dy) || 1
        const bend = Math.min(len * 0.09, 26)

        ctx.beginPath()
        ctx.moveTo(source.x, source.y)
        ctx.quadraticCurveTo(
          (source.x + target.x) / 2 - (dy / len) * bend,
          (source.y + target.y) / 2 + (dx / len) * bend,
          target.x,
          target.y,
        )
        ctx.strokeStyle = RELATION_COLORS[edge.type] || colors.edgeDefault
        ctx.lineWidth = 1 + edge.confidence * 1.6
        ctx.globalAlpha = alpha
        ctx.stroke()
      }
      ctx.globalAlpha = 1

      for (const node of nodes) {
        const r = radiusOf(node)
        const isHighlighted = node.id === hovered || node.id === selected
        const focusDimmed = focus !== null && !focus.has(node.id)

        const alpha = focusDimmed ? 0.12 : node.is_isolated && !isHighlighted ? 0.4 : 1

        ctx.beginPath()
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
        const fill = TYPE_COLORS[node.type] || colors.edgeDefault
        ctx.fillStyle = fill
        ctx.globalAlpha = alpha
        if (isHighlighted) {
          ctx.shadowColor = fill
          ctx.shadowBlur = 16
        }
        ctx.fill()
        ctx.shadowBlur = 0
        ctx.strokeStyle = colors.nodeStroke
        ctx.lineWidth = 1
        ctx.stroke()
        ctx.globalAlpha = 1

        if (isHighlighted) {
          ctx.font = '600 12px system-ui, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'bottom'
          ctx.fillStyle = colors.textPrimary
          ctx.shadowColor = colors.labelHalo
          ctx.shadowBlur = 6
          ctx.fillText(node.title.slice(0, 30), node.x, node.y - r - 6)
          ctx.shadowBlur = 0
        } else if (!focusDimmed) {
          ctx.font = '11px system-ui, sans-serif'
          ctx.textAlign = 'center'
          ctx.textBaseline = 'top'
          ctx.fillStyle = colors.textTertiary
          const label = node.title.length > 16 ? node.title.slice(0, 15) + '…' : node.title
          ctx.fillText(label, node.x, node.y + r + 6)
        }
      }
      ctx.globalAlpha = 1
    },
    [getTheme],
  )

  const tick = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas || !canvas.isConnected) {
      runningRef.current = false
      return
    }
    if (canvas.clientWidth === 0) {
      // LoadingWrapper 延迟挂载期间暂不消耗模拟帧，显示后再开始动画
      rafRef.current = requestAnimationFrame(tick)
      return
    }
    if (simFramesRef.current > 0) {
      simulate()
      simFramesRef.current--
    }
    const ctx = canvas.getContext('2d')
    if (ctx) renderScene(ctx, canvas.clientWidth, canvas.clientHeight)
    if (simFramesRef.current > 0) {
      rafRef.current = requestAnimationFrame(tick)
    } else {
      runningRef.current = false
    }
  }, [simulate, renderScene])

  const requestRedraw = useCallback(
    (simFrames = 0) => {
      if (simFrames > simFramesRef.current) simFramesRef.current = simFrames
      if (runningRef.current) return
      runningRef.current = true
      rafRef.current = requestAnimationFrame(tick)
    },
    [tick],
  )

  // 数据就绪后启动布局动画
  useEffect(() => {
    if (loading || error) return
    if (nodesRef.current.length === 0) return
    frameCountRef.current = 0
    requestRedraw(SIM_FRAMES)
  }, [loading, error, requestRedraw])

  // 高分屏与容器尺寸适配；依赖 canvasEl——LoadingWrapper 重挂 children 会替换
  // canvas 元素，需在新元素上重建 ResizeObserver
  useEffect(() => {
    if (!canvasEl) return
    canvasRef.current = canvasEl

    const applySize = () => {
      const cssW = canvasEl.clientWidth
      const cssH = canvasEl.clientHeight
      if (cssW === 0 || cssH === 0) return
      const dpr = window.devicePixelRatio || 1
      const bw = Math.round(cssW * dpr)
      const bh = Math.round(cssH * dpr)
      if (canvasEl.width !== bw || canvasEl.height !== bh) {
        canvasEl.width = bw
        canvasEl.height = bh
        gridRef.current = null
        if (nodesRef.current.length > 0) requestRedraw(KICK_FRAMES)
      }
    }

    applySize()
    const observer = new ResizeObserver(applySize)
    observer.observe(canvasEl)
    return () => observer.disconnect()
  }, [canvasEl, requestRedraw])

  // 主题切换时重绘（颜色从 CSS 变量读取，需重新取色）
  useEffect(() => {
    const observer = new MutationObserver(() => {
      themeRef.current = null
      requestRedraw()
    })
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => observer.disconnect()
  }, [requestRedraw])

  useEffect(() => {
    hoveredRef.current = hoveredNode
  }, [hoveredNode])

  useEffect(() => {
    selectedRef.current = selectedNode
  }, [selectedNode])

  // hover/选中变化时单帧重绘
  useEffect(() => {
    requestRedraw()
  }, [hoveredNode, selectedNode, requestRedraw])

  useEffect(() => {
    return () => {
      runningRef.current = false
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  const findNodeAt = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const rect = canvas.getBoundingClientRect()
    const x = clientX - rect.left
    const y = clientY - rect.top
    return nodesRef.current.find((node) => {
      const r = hitRadiusOf(node)
      const dx = node.x - x
      const dy = node.y - y
      return dx * dx + dy * dy < r * r
    })
  }, [])

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const id = findNodeAt(e.clientX, e.clientY)?.id ?? null
      if (id !== hoveredRef.current) {
        hoveredRef.current = id
        setHoveredNode(id)
      }
    },
    [findNodeAt],
  )

  const handleClick = useCallback(
    async (e: React.MouseEvent<HTMLCanvasElement>) => {
      const clicked = findNodeAt(e.clientX, e.clientY)

      setSelectedNode((prev) => {
        const newSelected = clicked ? (prev === clicked.id ? null : clicked.id) : null
        selectedRef.current = newSelected
        return newSelected
      })

      if (clicked) {
        try {
          const memory = await api.getMemoryDetail(clicked.id)
          setDetailMemory(memory)
        } catch (err) {
          console.error('Failed to fetch memory detail:', err)
        }
      }
    },
    [findNodeAt],
  )

  return (
    <PageShell
      maxWidth="max-w-7xl"
      header={
        <motion.div
          className="flex items-center justify-between"
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <PageTitle icon={<Network size={18} />} title="知识图谱" subtitle="工作区记忆关系全景" />
        </motion.div>
      }
    >
      {error ? (
        <ErrorAlert message="加载图谱失败" onRetry={() => window.location.reload()} />
      ) : (
        <LoadingWrapper loading={loading} skeleton={<CardSkeleton cols={1} />}>
          <div className="space-y-4">
            {/* Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  label: '节点数',
                  value: stats.total,
                  subtext: stats.truncated ? `共 ${stats.totalActive} 条记忆` : undefined,
                },
                { label: '关系数', value: stats.edges },
                { label: '孤立节点', value: stats.isolated },
                { label: '平均度数', value: stats.avgDegree },
              ].map(({ label, value, subtext }) => (
                <div
                  key={label}
                  className="glass-card p-4 rounded-xl transition-transform duration-200 hover:-translate-y-0.5"
                >
                  <div className="text-sm text-[var(--text-secondary)]">{label}</div>
                  <div className="text-2xl font-bold tabular-nums">{value}</div>
                  {subtext && (
                    <div className="text-xs text-[var(--text-tertiary)] mt-1">
                      展示 Top · {subtext}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Canvas */}
            <div className="glass-card rounded-xl p-4 relative overflow-hidden">
              <canvas
                ref={attachCanvas}
                className="w-full h-[600px] cursor-pointer block"
                onMouseMove={handleMouseMove}
                onClick={handleClick}
              />
              {stats.total === 0 && (
                <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                  <div className="text-center">
                    <Network
                      size={28}
                      className="mx-auto mb-2 text-[var(--text-tertiary)]"
                      aria-hidden
                    />
                    <p className="text-sm text-[var(--text-secondary)]">暂无记忆关系</p>
                    <p className="text-xs text-[var(--text-tertiary)] mt-1">
                      记忆之间建立关系后，这里会展示知识图谱
                    </p>
                  </div>
                </div>
              )}
              {(hoveredNode || selectedNode) && (
                <div className="absolute top-4 right-4 text-xs text-[var(--text-tertiary)] pointer-events-none">
                  {selectedNode ? '点击空白处取消聚焦' : '点击节点查看详情与关系编辑'}
                </div>
              )}
            </div>

            {/* Legend */}
            <div className="glass-card rounded-xl p-4">
              <div className="text-sm font-semibold mb-3">图例</div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5 text-xs">
                {Object.entries(TYPE_COLORS).map(([type, color]) => (
                  <div
                    key={type}
                    className="flex items-center gap-2 text-[var(--text-secondary)]"
                    title={type}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full shrink-0"
                      style={{ backgroundColor: color }}
                    />
                    <span>{TYPE_LABELS[type] ?? type}</span>
                    <span className="text-[var(--text-tertiary)]">{type}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 pt-3 border-t border-[var(--border-primary)]">
                <div className="text-sm font-semibold mb-3">关系类型</div>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5 text-xs">
                  {Object.entries(RELATION_COLORS).map(([type, color]) => (
                    <div
                      key={type}
                      className="flex items-center gap-2 text-[var(--text-secondary)]"
                      title={type}
                    >
                      <span
                        className="w-5 h-[3px] rounded-full shrink-0"
                        style={{ backgroundColor: color }}
                      />
                      <span>{RELATION_LABELS[type] ?? type}</span>
                      <span className="text-[var(--text-tertiary)]">{type}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </LoadingWrapper>
      )}

      {/* 详情弹窗 */}
      <Suspense fallback={null}>
        <MemoryDetailModal
          memory={detailMemory}
          onClose={() => setDetailMemory(null)}
          onMemoryUpdated={() => {
            setDetailMemory(null)
            window.location.reload()
          }}
        />
      </Suspense>
    </PageShell>
  )
}
