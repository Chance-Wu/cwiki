import { createBrowserHistory, parsePath, type To } from '@remix-run/router'
import { flushSync } from 'react-dom'

export const supportsViewTransition =
  typeof document !== 'undefined' && typeof document.startViewTransition === 'function'

const prefersReducedMotion = supportsViewTransition
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : null

const ROUTE_DEPTH: Record<string, number> = {
  '/': 0,
  '/pending': 1,
  '/memories': 2,
  '/skills': 3,
  '/config': 4,
  '/review': 5,
  '/settings': 6,
}

function getRouteDepth(pathname: string): number {
  return ROUTE_DEPTH[pathname] ?? -1
}

function setNavDirection(fromPath: string, toPath: string) {
  const fromDepth = getRouteDepth(fromPath)
  const toDepth = getRouteDepth(toPath)
  if (fromDepth < 0 || toDepth < 0 || fromDepth === toDepth) {
    document.documentElement.removeAttribute('data-nav-direction')
    return
  }
  document.documentElement.dataset.navDirection = toDepth > fromDepth ? 'forward' : 'back'
}

// v5Compat: push/replace 时通知监听器（BrowserRouter 的默认行为），否则 React Router 收不到更新
export const history = createBrowserHistory({ window, v5Compat: true })

if (supportsViewTransition && prefersReducedMotion) {
  const originalPush = history.push.bind(history)
  const originalReplace = history.replace.bind(history)
  let currentPath = history.location.pathname

  const resolveTargetPathname = (to: To): string => {
    if (typeof to === 'string') {
      return parsePath(to).pathname || history.location.pathname
    }
    return to.pathname || history.location.pathname
  }

  history.push = (to, state) => {
    const targetPathname = resolveTargetPathname(to)
    currentPath = targetPathname
    if (prefersReducedMotion.matches || targetPathname === history.location.pathname) {
      originalPush(to, state)
      return
    }
    setNavDirection(history.location.pathname, targetPathname)
    document.startViewTransition(() => {
      flushSync(() => {
        originalPush(to, state)
      })
    })
  }

  history.replace = (to, state) => {
    const targetPathname = resolveTargetPathname(to)
    currentPath = targetPathname
    if (prefersReducedMotion.matches || targetPathname === history.location.pathname) {
      originalReplace(to, state)
      return
    }
    setNavDirection(history.location.pathname, targetPathname)
    document.startViewTransition(() => {
      flushSync(() => {
        originalReplace(to, state)
      })
    })
  }

  // POP 导航（浏览器后退/前进）：库自身的 popstate 处理先行更新 location 并排队路由状态，
  // 本监听器注册在后，flushSync 在转场回调内清空队列，让新页面在转场内渲染
  window.addEventListener('popstate', () => {
    const targetPathname = history.location.pathname
    const from = currentPath
    currentPath = targetPathname
    if (prefersReducedMotion.matches || targetPathname === from) return
    setNavDirection(from, targetPathname)
    document.startViewTransition(() => {
      flushSync(() => {})
    })
  })
}
