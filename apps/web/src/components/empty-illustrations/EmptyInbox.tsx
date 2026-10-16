import { motion } from 'framer-motion'

export function EmptyInbox() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g style={{ animation: 'illus-float-y-lg 3s ease-in-out infinite' }}>
        <motion.rect
          x="20"
          y="45"
          width="80"
          height="55"
          rx="8"
          className="stroke-illus-warm"
          strokeWidth="2"
          fill="none"
          strokeDasharray="240"
          initial={{ strokeDashoffset: 240 }}
          animate={{ strokeDashoffset: 0 }}
          transition={{ duration: 1.2, ease: 'easeInOut' }}
        />
        <motion.path
          d="M20 60 L40 60 L45 50 L75 50 L80 60 L100 60"
          className="stroke-illus-warm"
          strokeWidth="2"
          fill="none"
          strokeDasharray="120"
          initial={{ strokeDashoffset: 120 }}
          animate={{ strokeDashoffset: 0 }}
          transition={{ duration: 1, delay: 0.2, ease: 'easeInOut' }}
        />
        <rect
          x="35"
          y="55"
          width="50"
          height="35"
          rx="4"
          className="stroke-illus-brand-light"
          strokeWidth="1.5"
          fill="none"
        />
        <motion.line
          x1="42"
          y1="65"
          x2="70"
          y2="65"
          className="stroke-illus-brand-light"
          strokeWidth="1.5"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.8, delay: 0.5 }}
        />
        <motion.line
          x1="42"
          y1="72"
          x2="65"
          y2="72"
          className="stroke-illus-brand-light"
          strokeWidth="1.5"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.8, delay: 0.7 }}
        />
        <motion.line
          x1="42"
          y1="79"
          x2="58"
          y2="79"
          className="stroke-illus-brand-light"
          strokeWidth="1.5"
          strokeLinecap="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 0.8, delay: 0.9 }}
        />
      </g>
      <circle
        cx="60"
        cy="32"
        r="5"
        className="fill-illus-warm-fill"
        style={{ animation: 'illus-twinkle-a 2.5s ease-in-out infinite' }}
      />
      <path
        d="M57 30 L60 27 L63 30"
        className="stroke-illus-warm"
        strokeWidth="1.5"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ animation: 'illus-float-fade-md 2.5s ease-in-out infinite' }}
      />
      <circle
        cx="30"
        cy="35"
        r="1.5"
        className="fill-illus-warm-fill"
        style={{ animation: 'illus-twinkle-a 3s 0.5s infinite ease-in-out' }}
      />
      <circle
        cx="90"
        cy="40"
        r="1"
        className="fill-illus-warm-fill"
        style={{ animation: 'illus-twinkle-a 3s 1s infinite ease-in-out' }}
      />
    </svg>
  )
}
