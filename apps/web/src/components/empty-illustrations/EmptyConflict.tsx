import { motion } from 'framer-motion'

export function EmptyConflict() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle
        cx="45"
        cy="55"
        r="18"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        style={{
          strokeDasharray: 115,
          strokeDashoffset: 115,
          animation: 'illus-stroke-draw 1s 0s forwards ease-in-out',
        }}
      />
      <circle
        cx="75"
        cy="55"
        r="18"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        style={{
          strokeDasharray: 115,
          strokeDashoffset: 115,
          animation: 'illus-stroke-draw 1s 0.2s forwards ease-in-out',
        }}
      />
      <motion.path
        d="M57 45 C60 50, 60 60, 57 65"
        className="stroke-illus-rose"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1.5 }}
        style={{ animation: 'illus-opacity-breathe 2.5s 1.5s ease-in-out infinite' }}
      />
      <motion.path
        d="M53 52 L57 55 L53 58"
        className="stroke-illus-rose"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1, delay: 0.5 }}
        style={{ animation: 'illus-opacity-breathe 2.5s 1.5s ease-in-out infinite' }}
      />
    </svg>
  )
}
