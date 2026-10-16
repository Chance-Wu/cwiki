import { motion } from 'framer-motion'

export function EmptyVersions() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <motion.rect
        x="35"
        y="55"
        width="50"
        height="35"
        rx="5"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        strokeDasharray="170"
        initial={{ strokeDashoffset: 170 }}
        animate={{ strokeDashoffset: 0 }}
        transition={{ duration: 0.8, ease: 'easeInOut' }}
      />
      <motion.rect
        x="35"
        y="42"
        width="50"
        height="35"
        rx="5"
        className="stroke-illus-outline"
        strokeWidth="1.5"
        fill="none"
        strokeDasharray="170"
        initial={{ strokeDashoffset: 170, opacity: 0 }}
        animate={{ strokeDashoffset: 0, opacity: 0.6 }}
        transition={{ duration: 0.8, delay: 0.2, ease: 'easeInOut' }}
      />
      <motion.rect
        x="35"
        y="29"
        width="50"
        height="35"
        rx="5"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        fill="none"
        strokeDasharray="170"
        initial={{ strokeDashoffset: 170, opacity: 0 }}
        animate={{ strokeDashoffset: 0, opacity: 0.35 }}
        transition={{ duration: 0.8, delay: 0.4, ease: 'easeInOut' }}
      />
      <motion.line
        x1="45"
        y1="65"
        x2="72"
        y2="65"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.7 }}
      />
      <motion.line
        x1="45"
        y1="72"
        x2="65"
        y2="72"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.85 }}
      />
      <motion.line
        x1="45"
        y1="79"
        x2="58"
        y2="79"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 1 }}
      />
      <circle
        cx="88"
        cy="38"
        r="6"
        className="fill-illus-subtle"
        style={{
          transformOrigin: '88px 38px',
          animation: 'illus-fill-pulse 2.5s infinite ease-in-out',
        }}
      />
      <path
        d="M86 38 L88 35 L90 38"
        className="stroke-illus-muted"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ animation: 'illus-float-fade-sm 2.5s ease-in-out infinite' }}
      />
    </svg>
  )
}
