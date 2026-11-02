/** 知识图谱视口变换的纯函数，供 Canvas 交互与单测复用。 */

export interface GraphView {
  scale: number
  tx: number
  ty: number
}

export const GRAPH_MIN_SCALE = 0.25
export const GRAPH_MAX_SCALE = 3

export function clampGraphScale(scale: number): number {
  return Math.min(GRAPH_MAX_SCALE, Math.max(GRAPH_MIN_SCALE, scale))
}

/** 以屏幕点 (cx, cy) 为锚缩放：锚点下的世界坐标保持不动。 */
export function zoomGraphView(
  view: GraphView,
  nextScale: number,
  cx: number,
  cy: number,
): GraphView {
  const next = clampGraphScale(nextScale)
  if (next === view.scale) return view
  const ratio = next / view.scale
  return {
    scale: next,
    tx: cx - (cx - view.tx) * ratio,
    ty: cy - (cy - view.ty) * ratio,
  }
}

export function panGraphView(view: GraphView, dx: number, dy: number): GraphView {
  return { scale: view.scale, tx: view.tx + dx, ty: view.ty + dy }
}

/** 双指缩放：按两指距离变化缩放，并跟随中点平移。 */
export function pinchGraphView(
  start: GraphView,
  startDistance: number,
  currentDistance: number,
  startMid: { x: number; y: number },
  mid: { x: number; y: number },
): GraphView {
  const safeStart = Math.max(startDistance, 1)
  const next = clampGraphScale(start.scale * (currentDistance / safeStart))
  const ratio = next / start.scale
  return {
    scale: next,
    tx: mid.x - (startMid.x - start.tx) * ratio,
    ty: mid.y - (startMid.y - start.ty) * ratio,
  }
}

/** 大图缩短布局动画帧数：每帧 O(n²)，节点越多越需要控制总帧数。 */
export function simulationFramesForNodes(count: number): number {
  if (count <= 200) return 240
  if (count <= 500) return 160
  return 90
}
