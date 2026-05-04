"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { Paperclip, Send, Sparkles } from "lucide-react"

import { AgentReasoning, ReasoningStep } from "@/components/chat/agent-reasoning"
import { MessageList } from "@/components/chat/message-list"
import { Button } from "@/components/ui/button"
import {
  apiJson,
  API_BASE_URL,
  ChatMessage,
  ConversationDetail,
  ReasoningEvent,
} from "@/lib/api"

const DEFAULT_WORKSPACE = "public_tech"

type ChatConsoleProps = {
  conversationId?: string
}

export function ChatConsole({ conversationId }: ChatConsoleProps) {
  const [input, setInput] = React.useState("")
  const [messages, setMessages] = React.useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "你好，我是 DocWise 助手。你可以询问技术文档、排查服务故障，或让 Agent 帮你串联检索、工具调用与引用证据。",
    },
  ])
  const [showReasoning, setShowReasoning] = React.useState(true)
  const [reasoningSteps, setReasoningSteps] = React.useState<ReasoningStep[]>([])
  const [isStreaming, setIsStreaming] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!conversationId) return
    let cancelled = false
    apiJson<ConversationDetail>(`/chat/conversations/${conversationId}`)
      .then((conversation) => {
        if (!cancelled) {
          setMessages(conversation.messages)
          setReasoningSteps([])
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [conversationId])

  const mergeReasoning = React.useCallback((event: ReasoningEvent) => {
    setReasoningSteps((prev) => {
      const detailParts = [
        event.decision ? `决策: ${event.decision}` : null,
        event.reason ?? null,
        event.confidence !== undefined ? `置信度: ${event.confidence.toFixed(2)}` : null,
      ].filter(Boolean)
      const nextStep: ReasoningStep = {
        id: event.node,
        node: event.node,
        title: event.title || event.node,
        detail: detailParts.join(" · ") || "节点执行中",
        status: event.status,
      }
      const existing = prev.findIndex((step) => step.node === event.node)
      if (existing === -1) return [...prev, nextStep]
      const next = [...prev]
      next[existing] = nextStep
      return next
    })
  }, [])

  const handleSend = React.useCallback(async () => {
    const query = input.trim()
    if (!query || isStreaming) return

    const assistantId = `assistant-${Date.now()}`
    setError(null)
    setInput("")
    setReasoningSteps([])
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", content: query },
      { id: assistantId, role: "assistant", content: "" },
    ])
    setIsStreaming(true)

    try {
      const response = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, workspace_slug: DEFAULT_WORKSPACE }),
      })
      if (!response.ok || !response.body) {
        throw new Error(`后端返回 ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split("\n\n")
        buffer = frames.pop() ?? ""
        for (const frame of frames) {
          const eventLine = frame.split("\n").find((line) => line.startsWith("event: "))
          const dataLine = frame.split("\n").find((line) => line.startsWith("data: "))
          if (!eventLine || !dataLine) continue
          const event = eventLine.replace("event: ", "")
          const payload = JSON.parse(dataLine.replace("data: ", ""))

          if (event === "reasoning") {
            mergeReasoning(payload as ReasoningEvent)
          }
          if (event === "token" && payload.content) {
            setMessages((prev) =>
              prev.map((message) =>
                message.id === assistantId ? { ...message, content: message.content + payload.content } : message
              )
            )
          }
          if (event === "answer" || event === "done") {
            const content = payload.content ?? payload.answer
            if (content) {
              setMessages((prev) =>
                prev.map((message) => (message.id === assistantId ? { ...message, content } : message))
              )
            }
          }
          if (event === "citation" && payload.citations) {
            setMessages((prev) =>
              prev.map((message) =>
                message.id === assistantId ? { ...message, citations: payload.citations } : message
              )
            )
          }
          if (event === "error") {
            throw new Error(payload.message || "流式对话失败")
          }
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "对话请求失败"
      setError(message)
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantId ? { ...item, content: `对话请求失败：${message}` } : item
        )
      )
    } finally {
      setIsStreaming(false)
    }
  }, [input, isStreaming, mergeReasoning])

  return (
    <div className="flex w-full h-full relative overflow-hidden">
      <div className="flex-1 flex flex-col h-full relative z-10">
        <header className="h-16 flex items-center justify-between px-6 shrink-0 bg-background/50 backdrop-blur-md border-b border-border/50">
          <div className="flex items-center gap-3">
            <div className="px-3 py-1.5 rounded-md bg-secondary/50 text-sm font-medium text-secondary-foreground flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              Public Tech Workspace
            </div>
            {error && <span className="text-xs text-red-500 truncate max-w-[360px]">{error}</span>}
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="gap-2 text-muted-foreground"
            onClick={() => setShowReasoning(!showReasoning)}
          >
            <Sparkles size={16} className={showReasoning ? "text-primary" : ""} />
            Agent 思考流
          </Button>
        </header>

        <div className="flex-1 overflow-y-auto px-4 md:px-10 py-6 scroll-smooth">
          <div className="max-w-3xl mx-auto">
            <MessageList messages={messages} />
          </div>
        </div>

        <div className="p-4 shrink-0 bg-gradient-to-t from-background via-background to-transparent">
          <div className="max-w-3xl mx-auto relative group">
            <div className="absolute inset-0 bg-primary/5 rounded-2xl blur-xl group-focus-within:bg-primary/10 transition-colors duration-500" />
            <div className="relative flex items-end gap-2 bg-background/80 backdrop-blur-xl border border-border/50 shadow-sm rounded-2xl p-2 transition-shadow focus-within:shadow-md focus-within:border-primary/30">
              <Button variant="ghost" size="icon" className="shrink-0 text-muted-foreground rounded-xl h-10 w-10 hover:bg-muted">
                <Paperclip size={18} />
              </Button>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    void handleSend()
                  }
                }}
                placeholder="询问 Airflow、K8s、API、故障日志或项目文档..."
                className="flex-1 max-h-48 min-h-[40px] bg-transparent border-none resize-none focus:ring-0 text-[15px] leading-relaxed py-2 outline-none placeholder:text-muted-foreground/70"
                rows={1}
              />
              <Button
                size="icon"
                onClick={() => void handleSend()}
                disabled={!input.trim() || isStreaming}
                className="shrink-0 rounded-xl h-10 w-10 bg-primary/90 hover:bg-primary text-primary-foreground shadow-sm transition-transform active:scale-95 disabled:opacity-50"
              >
                <Send size={18} className="ml-0.5" />
              </Button>
            </div>
            <div className="text-center mt-2 text-xs text-muted-foreground/60">
              {isStreaming ? "Agent 正在检索、推理并生成回答..." : "回答会附带引用证据，请在执行操作前核实。"}
            </div>
          </div>
        </div>
      </div>

      <AnimatePresence>
        {showReasoning && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 320, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="shrink-0 h-full bg-muted/10 border-l border-border/50 overflow-hidden"
          >
            <div className="w-[320px] h-full flex flex-col">
              <AgentReasoning steps={reasoningSteps} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
