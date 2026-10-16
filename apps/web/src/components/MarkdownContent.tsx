import { lazy, Suspense, useCallback, useEffect, useMemo, memo, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,
  Copy,
  ChevronDown,
  ExternalLink as ExternalLinkIcon,
  Info,
  Lightbulb,
  Link,
  Loader2,
  ShieldAlert,
  X,
} from 'lucide-react'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useTranslation, type TranslationKeys } from '../i18n/I18nProvider'

// 仅注册常用语言，控制语法高亮的打包体积
SyntaxHighlighter.registerLanguage('python', python)
SyntaxHighlighter.registerLanguage('javascript', javascript)
SyntaxHighlighter.registerLanguage('typescript', typescript)
SyntaxHighlighter.registerLanguage('bash', bash)
SyntaxHighlighter.registerLanguage('shell', bash)
SyntaxHighlighter.registerLanguage('json', json)
SyntaxHighlighter.registerLanguage('markdown', markdown)
SyntaxHighlighter.registerLanguage('yaml', yaml)
SyntaxHighlighter.registerLanguage('sql', sql)

const ReactMarkdownWithGfm = lazy(async () => {
  const [mod, gfmMod, mathMod, katexMod] = await Promise.all([
    import('react-markdown'),
    import('remark-gfm'),
    import('remark-math'),
    import('rehype-katex'),
    import('katex/dist/katex.min.css'),
  ])
  const ReactMarkdown = mod.default
  const remarkGfm = gfmMod.default
  const remarkMath = mathMod.default
  const rehypeKatex = katexMod.default
  return {
    default: function MarkdownWrapper(props: {
      children: string
      components?: Record<string, React.ComponentType<Record<string, unknown>>>
    }) {
      return (
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          {...props}
        />
      )
    },
  }
})

const CodeBlock = memo(function CodeBlock({
  code,
  language,
  t,
}: {
  code: string
  language?: string
  t: TranslationKeys
}) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }, [code])

  const lineCount = code.split('\n').length

  return (
    <pre className="group relative">
      <div className="code-block-header">
        {language && <span className="code-block-lang">{language}</span>}
        <button
          onClick={handleCopy}
          className="code-block-copy"
          title={copied ? t.markdown.copied : t.markdown.copy}
          aria-label={copied ? t.markdown.copied : t.markdown.copyCode}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          <span className="code-block-copy-text">
            {copied ? t.markdown.copied : t.markdown.copy}
          </span>
        </button>
      </div>
      <div className="code-block-with-lines">
        <div className="code-line-numbers">
          {Array.from({ length: lineCount }, (_, i) => (
            <span key={i}>{i + 1}</span>
          ))}
        </div>
        <SyntaxHighlighter
          language={language || 'text'}
          style={vscDarkPlus}
          customStyle={{
            margin: 0,
            padding: '1rem',
            background: 'transparent',
            fontSize: '13px',
            lineHeight: '1.65',
          }}
          codeTagProps={{
            style: {
              fontFamily: 'var(--font-mono)',
            },
          }}
          showLineNumbers={false}
        >
          {code}
        </SyntaxHighlighter>
      </div>
    </pre>
  )
})

function getCalloutConfig(t: TranslationKeys) {
  return {
    note: { icon: Info, label: t.markdown.note, color: 'info' },
    tip: { icon: Lightbulb, label: t.markdown.tip, color: 'success' },
    important: { icon: Check, label: t.markdown.important, color: 'brand' },
    warning: { icon: AlertTriangle, label: t.markdown.warning, color: 'warning' },
    caution: { icon: ShieldAlert, label: t.markdown.caution, color: 'danger' },
  } as const
}

type CalloutType = 'note' | 'tip' | 'important' | 'warning' | 'caution'

function extractCallInfo(
  children: React.ReactNode,
  t: TranslationKeys,
): {
  type: CalloutType
  title: string
  restChildren: React.ReactNode
} | null {
  const calloutConfig = getCalloutConfig(t)
  const childArray = Array.isArray(children) ? children : children ? [children] : []

  for (let i = 0; i < childArray.length; i++) {
    const child = childArray[i]
    if (!child) continue

    const text = extractText(child)
    const match = text.match(/^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*([\s\S]*)/)
    if (!match) continue

    const type = match[1].toLowerCase() as CalloutType
    const title = match[2].trim() || calloutConfig[type].label
    const restChildren = childArray.filter((_, idx) => idx !== i)

    return { type, title, restChildren: restChildren.length ? restChildren : null }
  }

  return null
}

function extractText(node: React.ReactNode): string {
  if (typeof node === 'string') return node
  if (typeof node === 'number') return String(node)
  if (!node) return ''
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (typeof node === 'object' && 'props' in node) {
    return extractText((node as React.ReactElement).props?.children as React.ReactNode)
  }
  return ''
}

const Callout = memo(function Callout({
  type,
  title,
  children,
  t,
}: {
  type: CalloutType
  title: string
  children: React.ReactNode
  t: TranslationKeys
}) {
  const config = getCalloutConfig(t)[type]
  const Icon = config.icon
  return (
    <div className={`callout callout-${config.color}`}>
      <div className="callout-header">
        <Icon size={15} className="callout-icon" />
        <span className="callout-title">{title}</span>
      </div>
      <div className="callout-body">{children}</div>
    </div>
  )
})

function MermaidBlock({ code, t }: { code: string; t: TranslationKeys }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const mod = await import('mermaid')
        const mermaid = mod.default
        mermaid.initialize({ startOnLoad: false, theme: 'default', securityLevel: 'loose' })
        if (cancelled || !containerRef.current) return

        const id = `mermaid-${Date.now()}`
        const { svg } = await mermaid.render(id, code)
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg
          setLoading(false)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : t.markdown.renderFailed)
          setLoading(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code, t.markdown.renderFailed])

  return (
    <div className="mermaid-block">
      <div className="code-block-header">
        <span className="code-block-lang">mermaid</span>
      </div>
      <div className="mermaid-content">
        {loading && !error && (
          <div className="mermaid-loading">
            <Loader2 size={14} className="animate-spin" />
            <span>{t.markdown.renderingChart}</span>
          </div>
        )}
        {error && (
          <div className="mermaid-error">
            {t.markdown.chartRenderFailed}: {error}
          </div>
        )}
        <div ref={containerRef} className="mermaid-diagram" />
      </div>
    </div>
  )
}

function extractHeadings(content: string): { level: number; text: string; id: string }[] {
  const cleaned = content.replace(/```[\s\S]*?```/g, '').replace(/`[^`]*`/g, '')
  const headingRegex = /^(#{1,6})\s+(.+)$/gm
  const headings: { level: number; text: string; id: string }[] = []
  let match
  while ((match = headingRegex.exec(cleaned)) !== null) {
    const text = match[2].replace(/[*_`[\]]/g, '').trim()
    headings.push({ level: match[1].length, text, id: slugify(text) })
  }
  return headings
}

function TableOfContents({ content, t }: { content: string; t: TranslationKeys }) {
  const [collapsed, setCollapsed] = useState(false)
  const headings = useMemo(() => {
    return extractHeadings(content).filter((h) => h.level >= 2 && h.level <= 3)
  }, [content])

  if (headings.length < 3) return null

  return (
    <div className="markdown-toc">
      <button
        className="markdown-toc-toggle"
        aria-label={t.markdown.toc}
        aria-expanded={!collapsed}
        onClick={() => setCollapsed(!collapsed)}
      >
        <span className="markdown-toc-title">{t.markdown.toc}</span>
        <ChevronDown size={14} className={`markdown-toc-chevron ${collapsed ? '' : 'expanded'}`} />
      </button>
      {!collapsed && (
        <nav className="markdown-toc-nav">
          {headings.map((h, i) => (
            <a
              key={i}
              href={`#${h.id}`}
              className={`markdown-toc-link toc-level-${h.level}`}
              onClick={(e) => {
                e.preventDefault()
                document.getElementById(h.id)?.scrollIntoView({ behavior: 'smooth' })
              }}
            >
              {h.text}
            </a>
          ))}
        </nav>
      )}
    </div>
  )
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fff\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/, '-')
    .trim()
}

const ImageWithLightbox = memo(function ImageWithLightbox({
  src,
  alt,
  t,
}: {
  src: string
  alt?: string
  t: TranslationKeys
}) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <>
      <div className="markdown-image-wrapper">
        <img src={src} alt={alt || ''} onClick={() => setIsOpen(true)} className="markdown-image" />
        {alt && <div className="markdown-image-caption">{alt}</div>}
      </div>
      {isOpen && (
        <div className="lightbox-overlay" onClick={() => setIsOpen(false)}>
          <button className="lightbox-close" aria-label={t.markdown.close}>
            <X size={20} />
          </button>
          <img
            src={src}
            alt={alt || ''}
            className="lightbox-image"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  )
})

const ExternalLink = memo(function ExternalLink({
  href,
  children,
}: {
  href: string
  children: React.ReactNode
}) {
  const isExternal = href.startsWith('http://') || href.startsWith('https://')

  return (
    <a
      href={href}
      target={isExternal ? '_blank' : undefined}
      rel={isExternal ? 'noopener noreferrer' : undefined}
    >
      {children}
      {isExternal && <ExternalLinkIcon size={12} className="external-link-icon" />}
    </a>
  )
})

const HeadingWithAnchor = memo(function HeadingWithAnchor({
  level,
  children,
  t,
}: {
  level: 1 | 2 | 3 | 4 | 5 | 6
  children: React.ReactNode
  t: TranslationKeys
}) {
  const Tag = `h${level}` as const
  const text =
    typeof children === 'string'
      ? children
      : Array.isArray(children)
        ? children.map((c) => (typeof c === 'string' ? c : '')).join('')
        : ''
  const id = text ? slugify(text) : undefined

  return (
    <Tag id={id} className="group heading-anchor">
      {children}
      {id && (
        <a href={`#${id}`} className="heading-anchor-link" aria-label={t.markdown.linkToHeading}>
          <Link size={14} />
        </a>
      )}
    </Tag>
  )
})

// react-markdown 的 component 覆写 props —— 放宽为任意键值对，
// 因为该库的 ComponentProps 泛型难以内联满足。
type MdCompProps = { children: React.ReactNode } & Record<string, unknown>

function createMarkdownComponents(t: TranslationKeys) {
  return {
    code({ className, children, ...props }: MdCompProps & { className?: string }) {
      const match = /language-(\w+)/.exec(className || '')
      const codeString = String(children).replace(/\n$/, '')
      if (match && match[1] === 'mermaid') {
        return <MermaidBlock code={codeString} t={t} />
      }
      if (match) {
        return <CodeBlock code={codeString} language={match[1]} t={t} />
      }
      return (
        <code className={className} {...props}>
          {children}
        </code>
      )
    },
    blockquote({ children, ...props }: MdCompProps) {
      const callout = extractCallInfo(children, t)
      if (callout) {
        return (
          <Callout type={callout.type} title={callout.title} t={t}>
            {callout.restChildren}
          </Callout>
        )
      }
      return <blockquote {...props}>{children}</blockquote>
    },
    img: ({ src, alt }: { src?: string; alt?: string }) => (
      <ImageWithLightbox src={src ?? ''} alt={alt ?? ''} t={t} />
    ),
    a: ({ href, children }: MdCompProps & { href?: string }) => (
      <ExternalLink href={href ?? '#'}>{children}</ExternalLink>
    ),
    h1: (props: MdCompProps & { id?: string }) => <HeadingWithAnchor level={1} t={t} {...props} />,
    h2: (props: MdCompProps & { id?: string }) => <HeadingWithAnchor level={2} t={t} {...props} />,
    h3: (props: MdCompProps & { id?: string }) => <HeadingWithAnchor level={3} t={t} {...props} />,
    h4: (props: MdCompProps & { id?: string }) => <HeadingWithAnchor level={4} t={t} {...props} />,
    h5: (props: MdCompProps & { id?: string }) => <HeadingWithAnchor level={5} t={t} {...props} />,
    h6: (props: MdCompProps & { id?: string }) => <HeadingWithAnchor level={6} t={t} {...props} />,
  }
}

interface MarkdownContentProps {
  content: string
  className?: string
}

export default function MarkdownContent({ content, className = '' }: MarkdownContentProps) {
  const { t } = useTranslation()
  const markdownComponents = useMemo(
    () =>
      createMarkdownComponents(t) as unknown as Record<
        string,
        React.ComponentType<Record<string, unknown>>
      >,
    [t],
  )

  return (
    <div className={`markdown-content ${className}`}>
      <TableOfContents content={content} t={t} />
      <Suspense
        fallback={
          <div className="text-sm text-[var(--text-secondary)] flex items-center justify-center gap-2 py-4">
            <Loader2 size={14} className="animate-spin" />
            {t.common.loading}
          </div>
        }
      >
        <ReactMarkdownWithGfm components={markdownComponents}>{content}</ReactMarkdownWithGfm>
      </Suspense>
    </div>
  )
}
