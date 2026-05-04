"use client"

import * as React from "react"
import { cn } from "@/lib/utils"
import { FileText, Sparkles, User } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import type { Citation } from "@/lib/api"

interface MessageBubbleProps {
  message: {
    id: string
    role: "user" | "assistant"
    content: string
    citations?: Citation[]
  }
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user"

  return (
    <div className={cn("flex gap-4", isUser ? "flex-row-reverse" : "flex-row")}>
      {/* 头像 */}
      <div className={cn(
        "w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm",
        isUser ? "bg-muted text-muted-foreground" : "bg-primary/10 text-primary"
      )}>
        {isUser ? <User size={16} /> : <Sparkles size={16} />}
      </div>

      {/* 消息内容 */}
      <div className={cn(
        "flex flex-col gap-2 max-w-[85%]",
        isUser ? "items-end" : "items-start"
      )}>
        <div className={cn(
          "px-4 py-3 rounded-2xl text-[15px] leading-relaxed relative group overflow-hidden",
          isUser 
            ? "bg-muted text-foreground rounded-tr-sm" 
            : "bg-transparent text-foreground"
        )}>
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <div className="prose prose-sm prose-slate dark:prose-invert max-w-none break-words text-foreground prose-p:leading-relaxed prose-pre:bg-muted/50 prose-pre:text-foreground">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-2 pl-4">
            {message.citations.slice(0, 4).map((citation, index) => (
              <div
                key={`${citation.chunk_uid}-${index}`}
                className="inline-flex max-w-[260px] items-center gap-1.5 rounded-md border border-border/50 bg-muted/30 px-2 py-1 text-xs text-muted-foreground"
              >
                <FileText size={12} className="shrink-0" />
                <span className="truncate">
                  [{index + 1}] {citation.document_title || citation.chunk_uid}
                </span>
                <span className="font-mono text-[10px]">{citation.score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
