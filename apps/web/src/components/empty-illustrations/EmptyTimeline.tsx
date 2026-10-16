import { motion } from 'framer-motion'

export function EmptyTimeline() {
  return (
    <svg
      width="120"
      height="120"
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <motion.line
        x1="40"
        y1="25"
        x2="40"
        y2="95"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1, ease: 'easeInOut' }}
      />
      <circle
        cx="40"
        cy="35"
        r="5"
        className="stroke-illus-outline animate-pop-in"
        strokeWidth="2"
        fill="none"
        style={{ transformOrigin: '40px 35px', animationDelay: '0.3s' }}
      />
      <motion.line
        x1="52"
        y1="35"
        x2="80"
        y2="35"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.5 }}
      />
      <circle
        cx="40"
        cy="60"
        r="4"
        className="fill-illus-soft"
        style={{ animation: 'illus-pulse 2.5s 0.3s infinite ease-in-out' }}
      />
      <motion.line
        x1="52"
        y1="60"
        x2="72"
        y2="60"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.6, delay: 0.7 }}
      />
      <circle
        cx="40"
        cy="82"
        r="3"
        className="fill-illus-outline"
        style={{ opacity: 0, animation: 'illus-fade 0.5s 0.9s forwards' }}
      />
      <motion.line
        x1="52"
        y1="82"
        x2="68"
        y2="82"
        className="stroke-illus-detail"
        strokeWidth="2"
        strokeLinecap="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 0.4 }}
        transition={{ duration: 0.6, delay: 1 }}
      />
    </svg>
  )
}
