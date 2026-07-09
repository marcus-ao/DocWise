"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"

import { MessageBubble } from "./message-bubble"
import type { ChatMessage } from "@/lib/api"

interface MessageListProps {
  messages: ChatMessage[]
  isStreaming?: boolean
  assistantRunStatus?: string | null
}

export function MessageList({ messages, isStreaming = false, assistantRunStatus = null }: MessageListProps) {
  return (
    <div className="flex flex-col gap-6 pb-4">
      <AnimatePresence initial={false} mode="popLayout">
        {messages.map((message, index) => (
          <motion.div
            layout="position"
            key={message.id}
            id={`msg-${message.id}`}
            initial={{ opacity: 0, y: 10, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ 
              type: "spring",
              stiffness: 400,
              damping: 30,
              mass: 1
            }}
          >
            <MessageBubble
              message={message}
              isStreamingPending={isStreaming && index === messages.length - 1 && message.role === "assistant"}
              runStatus={index === messages.length - 1 && message.role === "assistant" ? assistantRunStatus : null}
            />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
