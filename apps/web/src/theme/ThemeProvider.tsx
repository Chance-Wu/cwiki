/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from 'react'
import { type BrandThemeKey, DEFAULT_BRAND_THEME } from './brandTokens'

type Theme = 'light' | 'dark' | 'system'
type ResolvedTheme = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  resolvedTheme: ResolvedTheme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
  brandTheme: BrandThemeKey
  setBrandTheme: (key: BrandThemeKey) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function getSystemTheme(): ResolvedTheme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

function getInitialTheme(): Theme {
  const stored = localStorage.getItem('theme') as Theme | null
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  return 'system'
}

function getInitialBrandTheme(): BrandThemeKey {
  const stored = localStorage.getItem('brand-theme') as BrandThemeKey | null
  if (stored && ['amber', 'blue', 'emerald', 'violet'].includes(stored)) return stored
  return DEFAULT_BRAND_THEME
}

function resolveTheme(theme: Theme): ResolvedTheme {
  return theme === 'system' ? getSystemTheme() : theme
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme)
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() =>
    resolveTheme(getInitialTheme()),
  )
  const [brandTheme, setBrandThemeState] = useState<BrandThemeKey>(getInitialBrandTheme)

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    if (next === 'system') {
      localStorage.removeItem('theme')
    } else {
      localStorage.setItem('theme', next)
    }
  }, [])

  const setBrandTheme = useCallback((key: BrandThemeKey) => {
    setBrandThemeState(key)
    if (key === DEFAULT_BRAND_THEME) {
      localStorage.removeItem('brand-theme')
      document.documentElement.removeAttribute('data-brand')
    } else {
      localStorage.setItem('brand-theme', key)
      document.documentElement.setAttribute('data-brand', key)
    }
  }, [])

  useEffect(() => {
    const resolved = resolveTheme(theme)
    setResolvedTheme(resolved)
    document.documentElement.classList.toggle('dark', resolved === 'dark')
  }, [theme])

  useEffect(() => {
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => {
      const resolved = e.matches ? 'dark' : 'light'
      setResolvedTheme(resolved)
      document.documentElement.classList.toggle('dark', resolved === 'dark')
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [theme])

  useEffect(() => {
    if (brandTheme === DEFAULT_BRAND_THEME) {
      document.documentElement.removeAttribute('data-brand')
    } else {
      document.documentElement.setAttribute('data-brand', brandTheme)
    }
  }, [brandTheme])

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === 'light' ? 'dark' : prev === 'dark' ? 'system' : 'light'
      if (next === 'system') {
        localStorage.removeItem('theme')
      } else {
        localStorage.setItem('theme', next)
      }
      return next
    })
  }, [])

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme, toggleTheme, brandTheme, setBrandTheme }),
    [theme, resolvedTheme, setTheme, toggleTheme, brandTheme, setBrandTheme],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
