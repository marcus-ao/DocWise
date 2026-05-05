"use client"

import * as React from "react"
import { motion } from "framer-motion"

export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.995 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.995 }}
      transition={{ 
        type: "spring", 
        stiffness: 300, 
        damping: 30, 
        mass: 1,
        duration: 0.3 
      }}
      className="h-full w-full flex-1"
    >
      {children}
    </motion.div>
  )
}
