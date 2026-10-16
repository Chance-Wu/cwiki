import { motion } from 'framer-motion'

export function EmptySkills() {
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
        y="35"
        width="60"
        height="50"
        rx="6"
        className="stroke-illus-brand"
        strokeWidth="2"
        fill="none"
        strokeDasharray="220"
        initial={{ strokeDashoffset: 220 }}
        animate={{ strokeDashoffset: 0 }}
        transition={{ duration: 1.2, ease: 'easeInOut' }}
      />
      <motion.path
        d="M45 55 L55 65 L75 45"
        className="stroke-illus-accent"
        strokeWidth="2.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1, delay: 0.5 }}
        style={{ animation: 'illus-opacity-breathe 2.5s 1.5s ease-in-out infinite' }}
      />
      <circle
        cx="60"
        cy="25"
        r="5"
        className="fill-illus-accent-fill"
        style={{
          transformOrigin: '60px 25px',
          animation: 'illus-fill-pulse 2s infinite ease-in-out',
        }}
      />
      <path
        d="M58 23 L60 20 L62 23"
        className="stroke-illus-accent"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        style={{ animation: 'illus-float-fade-sm 2s ease-in-out infinite' }}
      />
      <motion.line
        x1="42"
        y1="75"
        x2="78"
        y2="75"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, delay: 0.8 }}
      />
    </svg>
  )
}
