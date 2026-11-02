import { describe, expect, it } from 'vitest'

import {
  clampGraphScale,
  GRAPH_MAX_SCALE,
  GRAPH_MIN_SCALE,
  panGraphView,
  pinchGraphView,
  simulationFramesForNodes,
  zoomGraphView,
} from '../lib/graphView'

describe('graphView', () => {
  it('clamps scale to configured bounds', () => {
    expect(clampGraphScale(0.01)).toBe(GRAPH_MIN_SCALE)
    expect(clampGraphScale(99)).toBe(GRAPH_MAX_SCALE)
    expect(clampGraphScale(1.5)).toBe(1.5)
  })

  it('keeps the world point under the cursor fixed while zooming', () => {
    const view = { scale: 1, tx: 10, ty: 20 }
    const next = zoomGraphView(view, 2, 100, 80)
    const worldX = (100 - view.tx) / view.scale
    const worldY = (80 - view.ty) / view.scale
    expect(next.scale).toBe(2)
    expect(worldX * next.scale + next.tx).toBeCloseTo(100)
    expect(worldY * next.scale + next.ty).toBeCloseTo(80)
  })

  it('pans without changing scale', () => {
    expect(panGraphView({ scale: 1.2, tx: 3, ty: 4 }, 10, -5)).toEqual({
      scale: 1.2,
      tx: 13,
      ty: -1,
    })
  })

  it('pinch scales by distance ratio and follows midpoint', () => {
    const view = { scale: 1, tx: 0, ty: 0 }
    const next = pinchGraphView(view, 100, 200, { x: 50, y: 50 }, { x: 60, y: 70 })
    expect(next.scale).toBe(2)
    // 起始中点 (50,50) 在世界坐标 (50,50)，缩放 2 倍后应落在当前中点 (60,70) 附近
    expect(50 * next.scale + next.tx).toBeCloseTo(60)
    expect(50 * next.scale + next.ty).toBeCloseTo(70)
  })

  it('shortens simulation for large graphs', () => {
    expect(simulationFramesForNodes(50)).toBe(240)
    expect(simulationFramesForNodes(400)).toBe(160)
    expect(simulationFramesForNodes(900)).toBe(90)
  })
})
