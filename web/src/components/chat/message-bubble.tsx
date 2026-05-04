"use client"

import * as React from "react"
import { FileText, Sparkles, User } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

import type { Citation } from "@/lib/api"
import { cn } from "@/lib/utils"

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
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-sm",
          isUser ? "bg-muted text-muted-foreground" : "bg-muted text-foreground"
        )}
      >
        {isUser ? <User size={16} /> : <Sparkles size={16} />}
      </div>

      <div className={cn("flex max-w-[85%] flex-col gap-2", isUser ? "items-end" : "items-start")}>
        <div
          className={cn(
            "relative overflow-hidden rounded-2xl border px-4 py-3 text-[15px] leading-7 shadow-sm",
            isUser
              ? "rounded-tr-sm border-border bg-muted/88 text-foreground shadow-[0_8px_20px_rgba(15,23,42,0.04)] dark:shadow-none"
              : "rounded-tl-sm border-border bg-card text-card-foreground shadow-[0_10px_28px_rgba(15,23,42,0.06)] dark:shadow-none"
          )}
        >
          {isUser ? (
            <div className="whitespace-pre-wrap text-foreground">{message.content}</div>
          ) : (
            <div className="prose prose-sm prose-neutral max-w-none break-words text-card-foreground dark:prose-invert prose-p:leading-7 prose-p:text-foreground prose-pre:border prose-pre:border-border/70 prose-pre:bg-muted/70 prose-pre:text-foreground prose-headings:text-foreground prose-strong:text-foreground prose-code:text-foreground prose-li:text-foreground prose-a:text-foreground prose-blockquote:border-border prose-blockquote:text-foreground prose-ol:text-foreground prose-ul:text-foreground">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="flex flex-wrap gap-2 pl-4">
            {message.citations.slice(0, 4).map((citation, index) => (
              <div
                key={`${citation.chunk_uid}-${index}`}
                className="inline-flex max-w-[260px] items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs text-muted-foreground shadow-sm"
              >
                <FileText size={12} className="shrink-0" />
                <span className="truncate">
                  [{index + 1}] {citation.document_title || citation.chunk_uid}
                </span>
                <span className="font-mono text-[10px] text-foreground/80">{citation.score.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
