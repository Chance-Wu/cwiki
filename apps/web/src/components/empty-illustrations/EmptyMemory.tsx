import { motion } from 'framer-motion'

export function EmptyMemory() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <motion.rect
        x="30"
        y="25"
        width="60"
        height="70"
        rx="6"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        strokeDasharray="260"
        initial={{ strokeDashoffset: 260 }}
        animate={{ strokeDashoffset: 0 }}
        transition={{ duration: 1.2, ease: 'easeInOut' }}
      />
      <motion.line
        x1="42"
        y1="42"
        x2="78"
        y2="42"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, delay: 0.5 }}
      />
      <motion.line
        x1="42"
        y1="52"
        x2="70"
        y2="52"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, delay: 0.7 }}
      />
      <motion.line
        x1="42"
        y1="62"
        x2="65"
        y2="62"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, delay: 0.9 }}
      />
      <circle
        cx="85"
        cy="30"
        r="6"
        className="fill-illus-soft"
        style={{
          transformOrigin: '85px 30px',
          animation: 'illus-fill-pulse 2s infinite ease-in-out',
        }}
      />
      <path
        d="M83 30 L85 28 L87 30"
        className="stroke-illus-muted"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        style={{ animation: 'illus-float-y-sm 2s ease-in-out infinite' }}
      />
    </svg>
  )
}
