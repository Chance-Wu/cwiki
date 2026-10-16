/**
 * 品牌色触点常量 — CSS 之外（JS/HTML）的品牌色唯一来源。
 *
 * 品牌色全貌与换色步骤（四处同步，缺一会出现新旧色混杂）：
 * 1. tailwind.config.js 的 brand 调色板 —— 所有 brand-* 工具类
 * 2. src/index.css 的 :root / .dark / [data-brand] CSS 变量
 * 3. 本文件 —— theme-color 元信息与品牌图标（运行时引用）+ 主题预设
 * 4. 静态副本 —— index.html 的 theme-color meta、public/favicon.svg、
 *    public/manifest.json 的 theme_color
 */

export type BrandThemeKey = 'amber' | 'blue' | 'emerald' | 'violet'

export interface BrandThemePreset {
  light: { brandRgb: string; brandDeepRgb: string; brandTextRgb: string }
  dark: { brandRgb: string; brandDeepRgb: string; brandTextRgb: string }
  iconColor: { light: { bg: string; fg: string }; dark: { bg: string; fg: string } }
  themeColor: { light: string; dark: string }
}

export const BRAND_THEMES: Record<BrandThemeKey, BrandThemePreset> = {
  amber: {
    light: { brandRgb: '217 119 6', brandDeepRgb: '180 83 9', brandTextRgb: '180 83 9' },
    dark: { brandRgb: '245 158 11', brandDeepRgb: '217 119 6', brandTextRgb: '251 191 36' },
    iconColor: {
      light: { bg: '#D97706', fg: '#FFFFFF' },
      dark: { bg: '#F59E0B', fg: '#1A1612' },
    },
    themeColor: { light: '#D97706', dark: '#F59E0B' },
  },
  blue: {
    light: { brandRgb: '37 99 235', brandDeepRgb: '29 78 216', brandTextRgb: '29 78 216' },
    dark: { brandRgb: '96 165 250', brandDeepRgb: '59 130 246', brandTextRgb: '147 197 253' },
    iconColor: {
      light: { bg: '#2563EB', fg: '#FFFFFF' },
      dark: { bg: '#60A5FA', fg: '#0B1120' },
    },
    themeColor: { light: '#2563EB', dark: '#60A5FA' },
  },
  emerald: {
    light: { brandRgb: '5 150 105', brandDeepRgb: '4 120 87', brandTextRgb: '4 120 87' },
    dark: { brandRgb: '16 185 129', brandDeepRgb: '5 150 105', brandTextRgb: '110 231 183' },
    iconColor: {
      light: { bg: '#059669', fg: '#FFFFFF' },
      dark: { bg: '#10B981', fg: '#0B1120' },
    },
    themeColor: { light: '#059669', dark: '#10B981' },
  },
  violet: {
    light: { brandRgb: '124 58 237', brandDeepRgb: '109 40 217', brandTextRgb: '109 40 217' },
    dark: { brandRgb: '167 139 250', brandDeepRgb: '139 92 246', brandTextRgb: '196 181 253' },
    iconColor: {
      light: { bg: '#7C3AED', fg: '#FFFFFF' },
      dark: { bg: '#A78BFA', fg: '#0B1120' },
    },
    themeColor: { light: '#7C3AED', dark: '#A78BFA' },
  },
}

export const DEFAULT_BRAND_THEME: BrandThemeKey = 'amber'

function getBrand(): BrandThemePreset {
  const key = (localStorage.getItem('brand-theme') as BrandThemeKey) || DEFAULT_BRAND_THEME
  return BRAND_THEMES[key] ?? BRAND_THEMES[DEFAULT_BRAND_THEME]
}

export const BRAND = {
  get themeColor() {
    const b = getBrand()
    return b.themeColor
  },
  get iconColor() {
    const b = getBrand()
    return b.iconColor
  },
}
