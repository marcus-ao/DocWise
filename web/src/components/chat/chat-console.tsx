"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { DatabaseZap, PanelRightClose, PanelRightOpen, Paperclip, Send } from "lucide-react"

import { AgentReasoning, ReasoningStep } from "@/components/chat/agent-reasoning"
import { MessageList } from "@/components/chat/message-list"
import { useBackendStatus } from "@/components/providers/backend-status-provider"
import { Button } from "@/components/ui/button"
import {
  apiJson,
  API_BASE_URL,
  ChatMessage,
  ConversationDetail,
  ReasoningEvent,
} from "@/lib/api"
import { setActiveConversation } from "@/lib/active-conversation"
import { notifyConversationsUpdated } from "@/lib/conversation-events"

const DEFAULT_WORKSPACE = "public_tech"

function StreamingSquare() {
  return (
    <motion.span
      style={{ backgroundColor: "var(--docwise-streaming-square)" }}
      className="block h-3.5 w-3.5 rounded-[0.32rem]"
      animate={{ scale: [0.82, 1, 0.82], opacity: [0.84, 1, 0.84] }}
      transition={{ duration: 1.25, repeat: Infinity, ease: "easeInOut" }}
    />
  )
}

function summarizeReasoningMeta(detail: {
  input_summary: Record<string, unknown> | null
  output_summary: Record<string, unknown> | null
  latency_ms: number | null
  error_message: string | null
}) {
  const meta: string[] = []
  const merged = [detail.input_summary, detail.output_summary]
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .flatMap((item) => Object.entries(item))
    .slice(0, 6)

  for (const [key, value] of merged) {
    if (value === null || value === undefined || value === "") continue
    meta.push(`${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
  }
  if (detail.latency_ms !== null && detail.latency_ms !== undefined) {
    meta.push(`耗时: ${detail.latency_ms}ms`)
  }
  if (detail.error_message) {
    meta.push(`错误: ${detail.error_message}`)
  }
  return meta
}

function summarizeReasoningDetail(detail: {
  input_summary: Record<string, unknown> | null
  output_summary: Record<string, unknown> | null
  error_message: string | null
  status: string
}) {
  if (detail.error_message) return detail.error_message
  const merged = [detail.output_summary, detail.input_summary]
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .flatMap((item) => Object.entries(item))
  const firstUseful = merged.find(([, value]) => value !== null && value !== undefined && value !== "")
  if (firstUseful) {
    const [key, value] = firstUseful
    return `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`
  }
  return detail.status === "running" ? "节点执行中" : "节点已完成"
}

type ChatConsoleProps = {
  conversationId?: string
}

export function ChatConsole({ conversationId }: ChatConsoleProps) {
  const { ready: backendReady, checked: backendChecked, message: backendMessage } = useBackendStatus()
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
  const [reasoningWidth, setReasoningWidth] = React.useState(360)
  const [activeConversationId, setActiveConversationId] = React.useState<string | undefined>(conversationId)
  const isResizingRef = React.useRef(false)

  const seededThinkingStep = React.useMemo<ReasoningStep[]>(
    () => [
      {
        id: "pending-thinking",
        node: "pending_thinking",
        title: "Agent 思考中",
        detail: "正在检索资料、组织线索并准备生成回答",
        meta: ["等待首批检索与推理节点返回..."],
        status: "active",
      },
    ],
    []
  )

  React.useEffect(() => {
    setActiveConversationId(conversationId)
  }, [conversationId])

  React.useEffect(() => {
    if (!activeConversationId || !backendReady) return
    let cancelled = false
    apiJson<ConversationDetail>(`/chat/conversations/${activeConversationId}`)
      .then((conversation) => {
        if (!cancelled) {
          setMessages(conversation.messages)
          setReasoningSteps(
            conversation.trace_events.map((event) => ({
              id: `${event.node_name}:${event.sequence_no}`,
              node: event.node_name,
              title: event.node_name,
              detail: summarizeReasoningDetail(event),
              meta: summarizeReasoningMeta(event),
              status:
                event.status === "failed" || event.status === "error"
                  ? "error"
                  : event.status === "running"
                    ? "active"
                    : "complete",
            }))
          )
          if (!conversationId) {
            setActiveConversation(conversation.id, "chat")
          }
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [activeConversationId, backendReady, conversationId])

  React.useEffect(() => {
    function handlePointerMove(event: PointerEvent) {
      if (!isResizingRef.current) return
      const nextWidth = Math.min(520, Math.max(320, window.innerWidth - event.clientX))
      setReasoningWidth(nextWidth)
    }

    function handlePointerUp() {
      isResizingRef.current = false
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
    }

    window.addEventListener("pointermove", handlePointerMove)
    window.addEventListener("pointerup", handlePointerUp)
    return () => {
      window.removeEventListener("pointermove", handlePointerMove)
      window.removeEventListener("pointerup", handlePointerUp)
    }
  }, [])

  const mergeReasoning = React.useCallback((event: ReasoningEvent) => {
    setReasoningSteps((prev) => {
      const detailParts = [
        event.decision ? `决策: ${event.decision}` : null,
        event.reason ?? null,
        event.confidence !== undefined ? `置信度: ${event.confidence.toFixed(2)}` : null,
      ].filter(Boolean)
      const meta = [
        event.workspace_policy ? `工作区策略：${event.workspace_policy}` : null,
        event.workspace_ids?.length ? `工作区范围：${event.workspace_ids.join(", ")}` : null,
        event.selected_project ? `命中项目：${event.selected_project}` : null,
        event.chunk_count !== undefined ? `候选片段数：${event.chunk_count}` : null,
        event.top_k !== undefined ? `重排保留数：${event.top_k}` : null,
        event.fallback ? "当前节点已降级处理" : null,
        event.tools?.length ? `计划工具：${event.tools.join(", ")}` : null,
        event.loop_round !== undefined ? `工具轮次：第 ${event.loop_round} 轮` : null,
        event.results?.length
          ? `工具结果：${event.results.map((item) => `${item.tool}(${item.status}) ${item.summary}`).join("；")}`
          : null,
        event.run_id ? `运行 ID：${event.run_id}` : null,
        event.query_id ? `会话 ID：${event.query_id}` : null,
        event.refused ? `拒答原因：${event.refusal_reason ?? "未提供"}` : null,
        event.latency_ms !== undefined ? `累计耗时：${event.latency_ms}ms` : null,
      ].filter(Boolean) as string[]
      const nextStep: ReasoningStep = {
        id: event.node,
        node: event.node,
        title: event.title || event.node,
        detail: detailParts.join(" · ") || "节点执行中",
        meta,
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
    if (!query || isStreaming || !backendReady) return

    const assistantId = `assistant-${Date.now()}`
    setError(null)
    setInput("")
    setReasoningSteps(seededThinkingStep)
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", content: query },
      { id: assistantId, role: "assistant", content: "" },
    ])
    setIsStreaming(true)

    try {
      let response: Response
      try {
        response = await fetch(`${API_BASE_URL}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            query,
            workspace_slug: DEFAULT_WORKSPACE,
            conversation_id: activeConversationId ?? null,
          }),
        })
      } catch (networkError) {
        const detail = networkError instanceof Error ? networkError.message : "Network request failed"
        throw new Error(`无法连接后端服务: ${detail}`)
      }
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
          if (event === "route") {
            mergeReasoning({
              node: "query_router",
              title: "路由决策",
              decision: payload.route,
              reason: payload.selected_project ? `命中项目 ${payload.selected_project}` : "已完成路由判断",
              confidence: payload.confidence,
              workspace_policy: payload.workspace_policy,
              workspace_ids: payload.workspace_ids,
              selected_project: payload.selected_project,
              status: "complete",
            })
          }
          if (event === "retrieval") {
            mergeReasoning({
              node: "hybrid_retriever",
              title: "混合检索",
              reason: `已召回 ${payload.chunk_count ?? 0} 个候选片段`,
              chunk_count: payload.chunk_count,
              workspace_ids: payload.workspace_ids,
              status: "complete",
            })
          }
          if (event === "rerank") {
            mergeReasoning({
              node: "reranker",
              title: "结果重排",
              reason: payload.fallback ? "重排失败，已降级继续" : `保留 ${payload.top_k ?? 0} 个高相关片段`,
              top_k: payload.top_k,
              fallback: payload.fallback,
              status: payload.fallback ? "error" : "complete",
            })
          }
          if (event === "tool_call") {
            mergeReasoning({
              node: "tool_executor",
              title: "工具执行",
              reason: "开始执行工具调用",
              tools: payload.tools,
              loop_round: payload.loop_round,
              status: "active",
            })
          }
          if (event === "tool_result") {
            mergeReasoning({
              node: "tool_executor",
              title: "工具执行",
              reason: "工具调用已返回结果",
              results: payload.results,
              status: "complete",
            })
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
            if (event === "done") {
              if (payload.query_id) {
                setActiveConversationId(payload.query_id)
                setActiveConversation(payload.query_id, "chat")
              }
              notifyConversationsUpdated()
              mergeReasoning({
                node: "answer_generator",
                title: "答案生成",
                reason: payload.refused ? "本轮请求已结束，结果为拒答" : "本轮请求已完成并写入会话列表",
                run_id: payload.run_id,
                query_id: payload.query_id,
                latency_ms: payload.latency_ms,
                refused: payload.refused,
                refusal_reason: payload.refusal_reason,
                status: payload.refused ? "error" : "complete",
              })
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
  }, [activeConversationId, backendReady, input, isStreaming, mergeReasoning, seededThinkingStep])

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      <div className="relative z-10 flex h-full flex-1 flex-col">
        <header className="h-16 shrink-0 border-b border-border/80 bg-background px-6 shadow-sm">
          <div className="flex h-full items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground shadow-sm">
                <span className="h-2 w-2 rounded-full bg-green-500" />
                Public Tech Workspace
              </div>
              {!backendReady && backendChecked ? (
                <span className="max-w-[460px] truncate text-xs text-amber-500">{backendMessage}</span>
              ) : error ? (
                <span className="max-w-[360px] truncate text-xs text-red-500">{error}</span>
              ) : null}
            </div>
            <Button
              variant="ghost"
              size="icon"
              className="text-muted-foreground hover:bg-muted"
              onClick={() => setShowReasoning(!showReasoning)}
            >
              {showReasoning ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
            </Button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-6 md:px-10">
          <div className="mx-auto max-w-3xl">
            {!backendReady && backendChecked ? (
              <div className="flex min-h-[420px] items-center">
                <div className="w-full rounded-3xl border border-border bg-card px-8 py-10 shadow-[0_16px_40px_rgba(15,23,42,0.06)] dark:shadow-none">
                  <div className="flex items-start gap-4">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-amber-500/10 text-amber-500">
                      <DatabaseZap size={20} />
                    </div>
                    <div className="space-y-3">
                      <h2 className="text-xl font-semibold text-foreground">后端服务暂未连接</h2>
                      <p className="max-w-2xl text-sm leading-7 text-muted-foreground">
                        {backendMessage ?? "请先启动 API、Redis 和数据库，再刷新页面。"}
                      </p>
                      <div className="rounded-2xl border border-border bg-background px-4 py-3 text-sm text-foreground">
                        当前仍可浏览历史、文档、评估等页面结构；后端恢复后刷新页面，即可继续使用对话、历史和检索功能。
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <MessageList messages={messages} isStreaming={isStreaming} />
            )}
          </div>
        </div>

        <div className="shrink-0 p-4">
          <div className="relative mx-auto max-w-3xl">
            <div className="relative flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-[0_14px_40px_rgba(15,23,42,0.08)] dark:shadow-none">
              <Button variant="ghost" size="icon" className="h-10 w-10 shrink-0 rounded-xl text-muted-foreground hover:bg-muted">
                <Paperclip size={18} />
              </Button>
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && backendReady) {
                    event.preventDefault()
                    void handleSend()
                  }
                }}
                disabled={!backendReady}
                placeholder={backendReady ? "询问 Airflow、K8s、API、故障日志或项目文档..." : "后端未连接，暂时无法发起对话"}
                className="min-h-[40px] max-h-48 flex-1 resize-none border-none bg-transparent py-2 text-[15px] font-medium leading-relaxed text-foreground outline-none placeholder:text-muted-foreground focus:ring-0 disabled:cursor-not-allowed disabled:text-slate-900 dark:disabled:text-muted-foreground dark:placeholder:text-muted-foreground"
                rows={1}
              />
              <Button
                size="icon"
                onClick={() => void handleSend()}
                disabled={!input.trim() || isStreaming || !backendReady}
                className="h-10 w-10 shrink-0 rounded-xl bg-primary/90 text-primary-foreground shadow-sm transition-transform hover:bg-primary active:scale-95 disabled:opacity-100 disabled:bg-primary/90"
              >
                {isStreaming ? <StreamingSquare /> : <Send size={18} className="ml-0.5" />}
              </Button>
            </div>
            <div className="mt-2 text-center text-xs text-muted-foreground/80">
              {!backendReady && backendChecked
                ? "后端恢复后刷新页面，即可继续使用对话、历史和检索功能。"
                : isStreaming
                  ? "Agent 正在检索、推理并生成回答..."
                  : "回答会附带引用证据，请在执行操作前核实。"}
            </div>
          </div>
        </div>
      </div>

      <AnimatePresence>
        {showReasoning && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: reasoningWidth, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="relative h-full shrink-0 border-l border-border bg-background"
          >
            <button
              type="button"
              aria-label="调整思考流面板宽度"
              className="absolute left-0 top-0 z-20 h-full w-3 -translate-x-1/2 cursor-col-resize bg-transparent"
              onPointerDown={() => {
                isResizingRef.current = true
                document.body.style.cursor = "col-resize"
                document.body.style.userSelect = "none"
              }}
            />
            <div className="relative flex h-full min-h-0 flex-col overflow-hidden" style={{ width: reasoningWidth }}>
              <button
                type="button"
                aria-label="占位拖拽手柄"
                className="pointer-events-none absolute left-0 top-0 h-full w-2 opacity-0"
              />
              <AgentReasoning steps={reasoningSteps} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
