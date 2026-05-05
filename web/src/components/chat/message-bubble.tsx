"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { Check, Copy, FileText, Sparkles, ThumbsDown, ThumbsUp, User } from "lucide-react"
import ReactMarkdown from "react-markdown"
import SyntaxHighlighter from "react-syntax-highlighter"
import { github } from "react-syntax-highlighter/dist/esm/styles/hljs"
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
  isStreamingPending?: boolean
}

function extractTextContent(node: React.ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node)
  if (Array.isArray(node)) return node.map(extractTextContent).join("")
  if (React.isValidElement<{ children?: React.ReactNode }>(node)) {
    return extractTextContent(node.props.children)
  }
  return ""
}

function CodeBlock({ language, value }: { language?: string; value: string }) {
  const [copied, setCopied] = React.useState(false)

  async function copyCode() {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1400)
  }

  return (
    <div className="group/code relative my-5 overflow-hidden rounded-2xl border border-border/70 bg-muted/55">
      <button
        type="button"
        onClick={() => void copyCode()}
        className="absolute right-3 top-3 z-10 inline-flex h-8 w-8 items-center justify-center rounded-md bg-background/72 text-muted-foreground opacity-0 shadow-sm backdrop-blur-[2px] transition-all hover:bg-background hover:text-foreground group-hover/code:opacity-100"
        aria-label="复制代码"
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
      <SyntaxHighlighter
        language={language}
        style={github}
        PreTag="div"
        wrapLongLines
        customStyle={{
          margin: 0,
          borderRadius: "1rem",
          background: "transparent",
          padding: "1.15rem 1.2rem",
          fontSize: "0.9rem",
          lineHeight: "1.7",
        }}
        codeTagProps={{
          style: {
            fontFamily:
              'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
          },
        }}
      >
        {value}
      </SyntaxHighlighter>
    </div>
  )
}

function ThinkingDots() {
  return (
    <div className="inline-flex min-w-[82px] items-center justify-center gap-1.5 rounded-full border border-border bg-card px-3.5 py-2 shadow-[0_10px_24px_rgba(15,23,42,0.08)] dark:shadow-none">
      {[0, 1, 2].map((index) => (
        <motion.span
          key={index}
          className="h-1.5 w-1.5 rounded-full bg-foreground"
          animate={{ opacity: [0.22, 1, 0.22], y: [0, -1.25, 0], scale: [0.96, 1.04, 0.96] }}
          transition={{ duration: 1, repeat: Infinity, delay: index * 0.16, ease: "easeInOut" }}
        />
      ))}
    </div>
  )
}

export function MessageBubble({ message, isStreamingPending = false }: MessageBubbleProps) {
  const isUser = message.role === "user"
  const isPendingAssistant = !isUser && isStreamingPending && !message.content.trim()
  const isAssistantStreaming = !isUser && isStreamingPending
  const [copied, setCopied] = React.useState(false)
  const [feedbackMark, setFeedbackMark] = React.useState<"up" | "down" | null>(null)

  async function copyMessage() {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  function sendPlaceholderFeedback(kind: "up" | "down") {
    setFeedbackMark(kind)
    window.setTimeout(() => setFeedbackMark(null), 1400)
  }

  return (
    <div className={cn("flex gap-4", isUser ? "flex-row-reverse" : "flex-row")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full shadow-sm",
          isUser ? "bg-muted text-muted-foreground" : "bg-muted text-foreground"
        )}
      >
        {isUser ? (
          <User size={16} />
        ) : isPendingAssistant ? (
          <Sparkles size={16} />
        ) : (
          <Sparkles size={16} />
        )}
      </div>

      <div className={cn("flex max-w-[85%] flex-col gap-2", isUser ? "items-end" : "items-start")}>
        {isPendingAssistant ? (
          <ThinkingDots />
        ) : (
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
              <div className="prose prose-sm prose-neutral max-w-none break-words text-card-foreground dark:prose-invert prose-p:my-3 prose-p:leading-7 prose-p:text-foreground prose-headings:mb-4 prose-headings:text-foreground prose-strong:text-foreground prose-em:text-foreground prose-code:text-foreground prose-code:before:content-none prose-code:after:content-none prose-li:text-foreground prose-li:marker:text-foreground prose-a:font-medium prose-a:text-foreground prose-blockquote:border-border prose-blockquote:text-foreground prose-ol:text-foreground prose-ul:text-foreground prose-hr:border-border prose-table:text-foreground prose-th:border-border prose-th:text-foreground prose-td:border-border prose-td:text-foreground prose-pre:m-0 prose-pre:border-0 prose-pre:bg-transparent prose-pre:p-0">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    pre({ children }) {
                      return <>{children}</>
                    },
                    code({ className, children, ...props }) {
                      const codeText = extractTextContent(children).replace(/\n$/, "")
                      const match = /language-([\w-]+)/.exec(className || "")
                      const isInline = !match && !codeText.includes("\n")

                      if (isInline) {
                        return (
                          <code
                            {...props}
                            className="rounded-md border border-border/60 bg-muted px-1.5 py-0.5 font-mono text-[0.92em] font-semibold text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.28)] dark:border-border dark:bg-muted/90 dark:shadow-none"
                          >
                            {codeText}
                          </code>
                        )
                      }

                      return <CodeBlock language={match?.[1]} value={codeText} />
                    },
                    p({ children }) {
                      return <p className="text-foreground">{children}</p>
                    },
                    li({ children }) {
                      return <li className="text-foreground">{children}</li>
                    },
                    table({ children }) {
                      return (
                        <div className="my-5 overflow-x-auto rounded-2xl border border-border/70 bg-background/70">
                          <table className="m-0 w-full text-sm">{children}</table>
                        </div>
                      )
                    },
                    th({ children }) {
                      return (
                        <th className="border-b border-border bg-muted/35 px-3 py-2 text-left font-semibold text-foreground">
                          {children}
                        </th>
                      )
                    },
                    td({ children }) {
                      return <td className="border-b border-border/70 px-3 py-2 align-top text-foreground">{children}</td>
                    },
                  }}
                >
                  {message.content}
                </ReactMarkdown>
              </div>
            )}
          </div>
        )}

        {!isUser && !isAssistantStreaming ? (
          <div className="relative flex items-center gap-2 pl-2 text-muted-foreground">
            <button
              type="button"
              onClick={() => void copyMessage()}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors hover:bg-muted hover:text-foreground"
              aria-label="复制回复"
            >
              {copied ? <Check size={16} /> : <Copy size={16} />}
            </button>
            <button
              type="button"
              onClick={() => sendPlaceholderFeedback("up")}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors hover:bg-muted hover:text-foreground"
              aria-label="好评"
            >
              {feedbackMark === "up" ? <Check size={16} /> : <ThumbsUp size={16} />}
            </button>
            <button
              type="button"
              onClick={() => sendPlaceholderFeedback("down")}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors hover:bg-muted hover:text-foreground"
              aria-label="差评"
            >
              {feedbackMark === "down" ? <Check size={16} /> : <ThumbsDown size={16} />}
            </button>
          </div>
        ) : null}

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
