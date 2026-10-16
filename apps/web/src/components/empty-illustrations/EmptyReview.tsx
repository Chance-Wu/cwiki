import { motion } from 'framer-motion'

export function EmptyReview() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g style={{ animation: 'illus-float-y-md 3s ease-in-out infinite' }}>
        <motion.rect
          x="30"
          y="30"
          width="60"
          height="55"
          rx="8"
          className="stroke-illus-brand"
          strokeWidth="2"
          fill="none"
          strokeDasharray="230"
          initial={{ strokeDashoffset: 230 }}
          animate={{ strokeDashoffset: 0 }}
          transition={{ duration: 1.2, ease: 'easeInOut' }}
        />
        <motion.rect
          x="38"
          y="38"
          width="44"
          height="6"
          rx="3"
          className="fill-illus-brand-fill"
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.6 }}
          transition={{ duration: 0.5, delay: 0.6 }}
        />
        <motion.line
          x1="38"
          y1="52"
          x2="68"
          y2="52"
          className="stroke-illus-brand-light"
          strokeWidth="2"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.6, delay: 0.7 }}
        />
        <motion.line
          x1="38"
          y1="60"
          x2="60"
          y2="60"
          className="stroke-illus-brand-light"
          strokeWidth="2"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.6, delay: 0.9 }}
        />
        <motion.line
          x1="38"
          y1="68"
          x2="55"
          y2="68"
          className="stroke-illus-brand-light"
          strokeWidth="2"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.6, delay: 1.1 }}
        />
        <motion.path
          d="M62 62 L70 70 L82 56"
          className="stroke-illus-accent"
          strokeWidth="2.5"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.8, delay: 1 }}
          style={{ animation: 'illus-opacity-breathe 2.5s 1.8s ease-in-out infinite' }}
        />
      </g>
      <circle
        cx="88"
        cy="28"
        r="5"
        className="fill-illus-accent-fill"
        style={{
          transformOrigin: '88px 28px',
          animation: 'illus-fill-pulse 2.5s infinite ease-in-out',
        }}
      />
      <circle
        cx="32"
        cy="95"
        r="1.5"
        className="fill-illus-outline"
        style={{ animation: 'illus-twinkle-a 3s 0.5s infinite ease-in-out' }}
      />
      <circle
        cx="92"
        cy="90"
        r="1"
        className="fill-illus-outline"
        style={{ animation: 'illus-twinkle-a 3s 1.2s infinite ease-in-out' }}
      />
    </svg>
  )
}
