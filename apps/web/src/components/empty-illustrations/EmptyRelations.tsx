import { motion } from 'framer-motion'

export function EmptyRelations() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle
        cx="40"
        cy="42"
        r="12"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        style={{
          strokeDasharray: 76,
          strokeDashoffset: 76,
          animation: 'illus-stroke-draw 0.8s 0s forwards ease-in-out',
        }}
      />
      <circle
        cx="80"
        cy="42"
        r="12"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        style={{
          strokeDasharray: 76,
          strokeDashoffset: 76,
          animation: 'illus-stroke-draw 0.8s 0.15s forwards ease-in-out',
        }}
      />
      <circle
        cx="60"
        cy="78"
        r="12"
        className="stroke-illus-outline"
        strokeWidth="2"
        fill="none"
        style={{
          strokeDasharray: 76,
          strokeDashoffset: 76,
          animation: 'illus-stroke-draw 0.8s 0.3s forwards ease-in-out',
        }}
      />
      <motion.line
        x1="51"
        y1="46"
        x2="69"
        y2="46"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.6 }}
      />
      <motion.line
        x1="45"
        y1="53"
        x2="55"
        y2="67"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.75 }}
      />
      <motion.line
        x1="75"
        y1="53"
        x2="65"
        y2="67"
        className="stroke-illus-detail"
        strokeWidth="1.5"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.9 }}
      />
      <circle
        cx="40"
        cy="42"
        r="4"
        className="fill-illus-soft"
        style={{
          transformOrigin: '40px 42px',
          animation: 'illus-fill-pulse 3s infinite ease-in-out',
        }}
      />
      <circle
        cx="80"
        cy="42"
        r="3.5"
        className="fill-illus-subtle"
        style={{
          transformOrigin: '80px 42px',
          animation: 'illus-fill-pulse 3s 0.5s infinite ease-in-out',
        }}
      />
      <circle
        cx="60"
        cy="78"
        r="3"
        className="fill-illus-subtle"
        style={{
          transformOrigin: '60px 78px',
          animation: 'illus-fill-pulse 3s 1s infinite ease-in-out',
        }}
      />
    </svg>
  )
}
