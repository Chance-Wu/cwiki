import { motion } from 'framer-motion'

export function EmptyFilter() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <motion.path
        d="M30 35 L90 35 L70 60 L70 80 L50 85 L50 60 Z"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        strokeDasharray="240"
        initial={{ strokeDashoffset: 240 }}
        animate={{ strokeDashoffset: 0 }}
        transition={{ duration: 1.2, ease: 'easeInOut' }}
      />
      <circle
        cx="85"
        cy="40"
        r="3"
        className="fill-illus-soft"
        style={{
          transformOrigin: '85px 40px',
          animation: 'illus-fill-pulse 2s infinite ease-in-out',
        }}
      />
      <circle
        cx="35"
        cy="75"
        r="2"
        className="fill-illus-outline"
        style={{ animation: 'illus-twinkle-a 3s 0.5s infinite ease-in-out' }}
      />
      <motion.line
        x1="45"
        y1="95"
        x2="75"
        y2="95"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, delay: 0.6 }}
      />
    </svg>
  )
}
