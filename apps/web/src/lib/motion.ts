type Bezier = [number, number, number, number]

export const ease = {
  out: [0.16, 1, 0.3, 1] as Bezier,
  in: [0.7, 0, 0.84, 0] as Bezier,
  io: [0.65, 0, 0.35, 1] as Bezier,
  snap: [0.2, 0, 0, 1] as Bezier,
  smooth: [0.4, 0, 0.2, 1] as Bezier,
  bounce: [0.34, 1.56, 0.64, 1] as Bezier,
}

export const duration = {
  fast: 0.1,
  normal: 0.15,
  slow: 0.25,
  modal: 0.2,
  reveal: 0.5,
  stagger: 0.35,
  medium: 0.4,
} as const

export const spring = {
  dialog: { stiffness: 400, damping: 30 },
  layout: { stiffness: 500, damping: 35 },
  press: { stiffness: 600, damping: 25 },
  gentle: { stiffness: 300, damping: 28 },
  snappy: { stiffness: 500, damping: 22 },
  /** 弹性过冲 — 激进入场动画 */
  bouncy: { stiffness: 400, damping: 15 },
  /** 极端弹性 — 夸张入场 */
  wild: { stiffness: 350, damping: 10 },
} as const
