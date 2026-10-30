import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Home } from 'lucide-react'
import { useTranslation } from '../i18n/I18nProvider'
import { Button } from '../components/ui/Button'
import { spring, duration, ease } from '../lib/motion'

function LostIllustration() {
  return (
    <motion.svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      initial="hidden"
      animate="visible"
    >
      <circle
        cx="60"
        cy="60"
        r="50"
        stroke="var(--border-strong)"
        strokeWidth="1.5"
        strokeDasharray="4 4"
        opacity="0.4"
      />
      <motion.path
        d="M40 70 L55 50 L70 65 L85 45"
        stroke="rgb(var(--brand-rgb))"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: duration.reveal, delay: 0.3, ease: ease.out }}
      />
      <circle
        cx="85"
        cy="45"
        r="3"
        fill="rgb(var(--brand-rgb))"
        className="animate-pop-in"
        style={{ transformOrigin: '85px 45px', animationDelay: '1s' }}
      />
      <motion.g
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: duration.reveal, delay: 0.5 }}
      >
        <circle cx="35" cy="35" r="2" fill="var(--text-tertiary)" opacity="0.3" />
        <circle cx="90" cy="80" r="1.5" fill="var(--text-tertiary)" opacity="0.3" />
        <circle cx="25" cy="75" r="1" fill="var(--text-tertiary)" opacity="0.3" />
      </motion.g>
    </motion.svg>
  )
}

export default function NotFoundPage() {
  const { t } = useTranslation()

  return (
    <div className="flex flex-1 items-center justify-center px-4">
      <motion.div
        className="text-center max-w-sm"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: duration.slow, ease: ease.out }}
      >
        <div className="relative inline-block mb-6">
          <div className="absolute inset-0 bg-brand-500/10 rounded-full blur-2xl" />
          <LostIllustration />
        </div>
        <motion.h1
          className="text-6xl font-semibold text-[var(--text-tertiary)] tabular-nums tracking-tighter"
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ ...spring.gentle, delay: 0.2 }}
        >
          404
        </motion.h1>
        <motion.h2
          className="text-lg font-semibold text-[var(--text-primary)] mt-3"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: duration.stagger, delay: 0.4 }}
        >
          {t.notFound.title}
        </motion.h2>
        <motion.p
          className="text-sm text-[var(--text-secondary)] mt-2 leading-relaxed max-w-xs mx-auto"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: duration.stagger, delay: 0.5 }}
        >
          {t.notFound.description}
        </motion.p>
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: duration.stagger, delay: 0.6 }}
        >
          <Button variant="primary" asChild className="mt-8">
            <Link to="/">
              <Home size={16} aria-hidden="true" />
              {t.notFound.backHome}
            </Link>
          </Button>
        </motion.div>
      </motion.div>
    </div>
  )
}
