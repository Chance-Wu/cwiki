/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
} from 'react'
import zh from './locales/zh'
import type { TranslationKeys } from './locales/en'
export type { TranslationKeys }

type Locale = 'zh' | 'en'

// en 词典按需加载：单飞缓存，避免重复触发动态 import
let enCache: Promise<TranslationKeys> | null = null
function loadEn(): Promise<TranslationKeys> {
  if (!enCache) enCache = import('./locales/en').then((m) => m.default)
  return enCache
}

interface I18nContextValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: TranslationKeys
}

export const I18nContext = createContext<I18nContextValue | null>(null)

const STORAGE_KEY = 'cwiki-locale'

function getInitialLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'en' || stored === 'zh') return stored
  return 'zh'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale)
  const [enDict, setEnDict] = useState<TranslationKeys | null>(null)

  useEffect(() => {
    if (locale !== 'en' || enDict) return
    let cancelled = false
    loadEn().then((dict) => {
      if (!cancelled) setEnDict(dict)
    })
    return () => {
      cancelled = true
    }
  }, [locale, enDict])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    localStorage.setItem(STORAGE_KEY, l)
  }, [])

  // 同步 <html lang> 与当前 locale（覆盖首次挂载；index.html 默认 zh-CN）
  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
  }, [locale])

  // en 词典未就绪时回退 zh 渲染，加载完成后整体重渲染切换
  const value = useMemo(
    () => ({ locale, setLocale, t: locale === 'en' && enDict ? enDict : zh }),
    [locale, setLocale, enDict],
  )

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useTranslation() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error('useTranslation must be used within I18nProvider')
  return ctx
}

export function translate(template: string, params: Record<string, string | number> = {}) {
  let result = template
  for (const [key, value] of Object.entries(params)) {
    result = result.replace(`{${key}}`, String(value))
  }
  return result
}
