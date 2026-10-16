import { motion } from 'framer-motion'

export function EmptyFeedback() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <motion.rect
        x="28"
        y="30"
        width="64"
        height="48"
        rx="8"
        className="stroke-illus-warm"
        strokeWidth="2"
        fill="none"
        strokeDasharray="224"
        initial={{ strokeDashoffset: 224 }}
        animate={{ strokeDashoffset: 0 }}
        transition={{ duration: 1.2, ease: 'easeInOut' }}
      />
      <motion.path
        d="M48 78 L48 90 L58 82"
        className="stroke-illus-warm"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.6 }}
      />
      <motion.g
        initial={{ opacity: 0, scale: 0.5 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.5, delay: 0.8 }}
      >
        <motion.path
          d="M50 50 L54 50 L56 44 L60 56 L64 48 L66 50 L70 50"
          className="stroke-illus-accent"
          strokeWidth="2"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1 }}
          style={{ animation: 'illus-opacity-breathe 2.5s 1s ease-in-out infinite' }}
        />
      </motion.g>
      <motion.line
        x1="40"
        y1="62"
        x2="62"
        y2="62"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 1 }}
      />
      <motion.line
        x1="40"
        y1="68"
        x2="55"
        y2="68"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 1.15 }}
      />
      <circle
        cx="85"
        cy="30"
        r="2"
        className="fill-illus-warm-fill"
        style={{ animation: 'illus-twinkle-a 3s 0.5s infinite ease-in-out' }}
      />
      <circle
        cx="30"
        cy="95"
        r="1.5"
        className="fill-illus-accent-fill"
        style={{ animation: 'illus-twinkle-b 3s 1s infinite ease-in-out' }}
      />
    </svg>
  )
}
