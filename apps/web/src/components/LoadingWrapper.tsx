import { useState, useEffect, useRef, type ReactNode } from 'react'

interface LoadingWrapperProps {
  loading: boolean
  skeleton: ReactNode
  children: ReactNode
}

export default function LoadingWrapper({ loading, skeleton, children }: LoadingWrapperProps) {
  const [showContent, setShowContent] = useState(!loading)
  const [fading, setFading] = useState(false)
  const prevLoading = useRef(loading)

  useEffect(() => {
    if (loading) {
      setShowContent(false)
      setFading(false)
      prevLoading.current = true
      return
    }
    if (prevLoading.current && !loading) {
      requestAnimationFrame(() => {
        setFading(true)
        const timer = setTimeout(() => {
          setShowContent(true)
          setFading(false)
        }, 300)
        prevLoading.current = false
        return () => clearTimeout(timer)
      })
    } else if (!loading) {
      setShowContent(true)
    }
  }, [loading])

  if (showContent && !fading) {
    return <>{children}</>
  }

  return (
    <>
      <div className={`transition-opacity duration-300 ${fading ? 'opacity-0' : 'opacity-100'}`}>
        {skeleton}
      </div>
      {!showContent && <div className="hidden">{children}</div>}
    </>
  )
}
