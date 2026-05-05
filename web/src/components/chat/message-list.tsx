"use client"

import * as React from "react"
import { motion } from "framer-motion"

import { MessageBubble } from "./message-bubble"
import type { ChatMessage } from "@/lib/api"

interface MessageListProps {
  messages: ChatMessage[]
  isStreaming?: boolean
}

export function MessageList({ messages, isStreaming = false }: MessageListProps) {
  return (
    <div className="flex flex-col gap-6 pb-4">
      {messages.map((message, index) => (
        <motion.div
          key={message.id}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
        >
          <MessageBubble
            message={message}
            isStreamingPending={isStreaming && index === messages.length - 1 && message.role === "assistant"}
          />
        </motion.div>
      ))}
    </div>
  )
}
