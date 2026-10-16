import { motion } from 'framer-motion'

export function EmptyHealth() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <motion.path
        d="M60 85 L35 60 C25 50 25 35 35 30 C45 25 55 30 60 40 C65 30 75 25 85 30 C95 35 95 50 85 60 Z"
        className="stroke-illus-rose"
        strokeWidth="2"
        fill="none"
        strokeDasharray="280"
        initial={{ strokeDashoffset: 280 }}
        animate={{ strokeDashoffset: 0 }}
        transition={{ duration: 1.5, ease: 'easeInOut' }}
      />
      <motion.path
        d="M40 55 L50 55 L55 45 L60 65 L65 50 L70 55 L80 55"
        className="stroke-illus-rose"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1.2, delay: 0.5 }}
        style={{ animation: 'illus-opacity-breathe 2s 1.7s ease-in-out infinite' }}
      />
    </svg>
  )
}
