"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
import { usePathname, useRouter } from "next/navigation"
import {
  ArrowDown,
  ChevronDown,
  DatabaseZap,
  Hash,
  Maximize2,
  Minimize2,
  PanelRightClose,
  PanelRightOpen,
  Paperclip,
  Send,
} from "lucide-react"

import { AgentReasoning, ReasoningStep } from "@/components/chat/agent-reasoning"
import { MessageList } from "@/components/chat/message-list"
import { useBackendStatus } from "@/components/providers/backend-status-provider"
import { PageBack } from "@/components/layout/page-back"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import {
  apiJson,
  API_BASE_URL,
  apiVoid,
  ChatMessage,
  ConversationDetail,
  ReasoningEvent,
  Workspace,
  WorkspaceListResponse,
} from "@/lib/api"
import { setActiveConversation } from "@/lib/active-conversation"
import { notifyConversationsUpdated } from "@/lib/conversation-events"

const AUTO_WORKSPACE = "__auto__"
const COLLAPSED_TEXTAREA_HEIGHT = 40
const EXPANDED_TEXTAREA_HEIGHT = 240

function describeScopeDecision(event: Pick<ReasoningEvent, "scope_reason_code" | "scope_reason_params" | "selected_project">) {
  const code = event.scope_reason_code
  const params = event.scope_reason_params ?? {}
  const explicit = typeof params.explicit === "string" ? params.explicit : undefined
  const aliasChosen = typeof params.alias_chosen === "string" ? params.alias_chosen : undefined
  const inheritedFromTurn = typeof params.inherited_from_turn === "number" ? params.inherited_from_turn : undefined
  const projectSlug = typeof params.project_slug === "string" ? params.project_slug : event.selected_project ?? undefined

  switch (code) {
    case "explicit_plus_alias":
      return projectSlug
        ? `检测到问题涉及 ${projectSlug}，已在显式知识域基础上合并项目上下文`
        : "显式知识域与项目别名已合并"
    case "explicit_conflict_ignored":
      return explicit
        ? `已尊重显式选择 ${explicit}，忽略其他项目候选`
        : "已尊重显式项目选择，忽略其他项目候选"
    case "explicit_only":
      return explicit ? `按显式选择 ${explicit} 作为首要知识域` : "按显式选择确定知识域"
    case "auto_project_matched":
      return projectSlug ? `自动命中项目 ${projectSlug}` : "自动命中项目知识域"
    case "route_downgrade":
      return "当前问题未命中项目知识域，已按路由默认范围降级"
    case "inherited_from_turn":
      return inheritedFromTurn !== undefined
        ? `当前问题未命中显式或别名，已继承第 ${inheritedFromTurn} 轮的知识域范围`
        : "当前问题未命中显式或别名，已继承上一轮知识域范围"
    case "out_of_scope":
      return "当前问题已判定为超出范围"
    case "auto_route_default":
      return "未命中显式或项目别名，已按路由默认范围处理"
    default:
      return undefined
  }
}

function StreamingSquare() {
  return (
    <motion.span
      style={{ backgroundColor: "var(--docwise-streaming-square)" }}
      className="block h-3 w-3 rounded-sm shadow-[0_0_10px_rgba(255,255,255,0.4)] dark:shadow-none"
      animate={{ 
        scale: [0.85, 1.05, 0.85], 
        opacity: [0.8, 1, 0.8],
        borderRadius: ["25%", "35%", "25%"] 
      }}
      transition={{ 
        duration: 1.5, 
        repeat: Infinity, 
        ease: "easeInOut" 
      }}
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

function MessageDirectory({
  messages,
  onNavigate,
}: {
  messages: ChatMessage[]
  onNavigate: (id: string) => void
}) {
  const [isHovered, setIsHovered] = React.useState(false)
  const userMessages = messages.filter((m) => m.role === "user" && m.id !== "welcome")

  if (userMessages.length <= 1) return null

  // Only show the last 7 indicators in minimized mode
  const minimizedMessages = userMessages.slice(-7)

  return (
    <motion.div
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className="absolute right-3 top-1/2 z-40 flex -translate-y-1/2 flex-col items-end px-1 py-6 group/nav"
      style={{ height: "fit-content", minWidth: "48px" }}
    >
      <AnimatePresence mode="wait">
        {isHovered ? (
          <motion.div
            key="expanded"
            initial={{ opacity: 0, x: 20, scale: 0.9 }}
            animate={{ opacity: 1, x: 0, scale: 1 }}
            exit={{ opacity: 0, x: 20, scale: 0.9 }}
            transition={{ type: "spring", stiffness: 400, damping: 25 }}
            className="flex w-[320px] flex-col gap-0.5 rounded-[20px] border border-border bg-card/75 p-1.5 shadow-[0_32px_64px_-16px_rgba(0,0,0,0.15)] ring-1 ring-black/5 backdrop-blur-2xl"
          >
            <div className="mb-1 flex items-center justify-center border-b border-border/40 px-4 py-2.5">
              <div className="flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                <span className="text-[11px] font-bold uppercase tracking-[0.18em] text-foreground/70">交互目录</span>
              </div>
            </div>
            {/* Scrollable area: show up to 10 items, then scrollbar */}
            <div className="max-h-[396px] overflow-y-auto pr-1 custom-scrollbar">
              {userMessages.map((msg, i) => (
                <button
                  key={msg.id}
                  onClick={() => onNavigate(msg.id)}
                  className="group/item w-full text-left p-2.5 rounded-xl transition-all hover:bg-muted flex items-start gap-2.5 active:scale-[0.98]"
                >
                  <span className="shrink-0 text-[11px] font-mono text-muted-foreground/50 mt-0.5 min-w-[20px]">
                    {String(i + 1).padStart(2, "0")}.
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-tight text-foreground/70 transition-colors group-hover/item:text-foreground">
                    {msg.content}
                  </span>
                </button>
              ))}
            </div>
          </motion.div>
        ) : (
          <motion.button
            type="button"
            key="minimized"
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            aria-label="展开交互目录"
            className="group/nav flex cursor-pointer flex-col items-end gap-4 pr-1.5 py-6"
          >
            {minimizedMessages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={false}
                className="h-[3px] w-5 rounded-full bg-black/90 shadow-[0_1.5px_4px_rgba(0,0,0,0.15)] transition-all duration-500 group-hover/nav:w-7 group-hover/nav:bg-black dark:bg-white/70 dark:group-hover/nav:bg-white"
              />
            ))}
          </motion.button>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

type ChatConsoleProps = {
  conversationId?: string
  backLabel?: string
  backHref?: string
}

export function ChatConsole({ conversationId, backLabel, backHref }: ChatConsoleProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { ready: backendReady, checked: backendChecked, message: backendMessage } = useBackendStatus()
  const [input, setInput] = React.useState("")
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([])
  const [selectedWorkspaceSlug, setSelectedWorkspaceSlug] = React.useState<string>(AUTO_WORKSPACE)
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
  const [isInputExpanded, setIsInputExpanded] = React.useState(false)
  const [activeConversationId, setActiveConversationId] = React.useState<string | undefined>(conversationId)
  const [remoteRunStatus, setRemoteRunStatus] = React.useState<string | null>(null)
  const isResizingRef = React.useRef(false)
  const streamAbortRef = React.useRef<AbortController | null>(null)
  const activeRunIdRef = React.useRef<string | null>(null)
  const userStoppedRef = React.useRef(false)
  
  const scrollRef = React.useRef<HTMLDivElement>(null)
  const suppressAutoScrollRef = React.useRef(false)
  const suppressAutoScrollTimerRef = React.useRef<number | null>(null)
  const isUserScrollingRef = React.useRef(false)
  const [isUserScrolling, setIsUserScrollingState] = React.useState(false)
  const isRunActive = isStreaming || remoteRunStatus === "running"

  const chatWorkspaceOptions = React.useMemo(
    () =>
      workspaces.filter(
        (workspace) =>
          workspace.is_active &&
          workspace.workspace_type !== "mock_ops" &&
          (workspace.slug === "public_tech" || workspace.workspace_type === "project_pack")
      ),
    [workspaces]
  )

  const selectedWorkspaceLabel = React.useMemo(() => {
    if (selectedWorkspaceSlug === AUTO_WORKSPACE) {
      return "Auto"
    }
    return chatWorkspaceOptions.find((workspace) => workspace.slug === selectedWorkspaceSlug)?.name ?? selectedWorkspaceSlug
  }, [chatWorkspaceOptions, selectedWorkspaceSlug])

  React.useEffect(() => {
    apiJson<WorkspaceListResponse>("/workspaces")
      .then((data) => setWorkspaces(data.items))
      .catch(() => setWorkspaces([]))
  }, [])

  const setIsUserScrolling = React.useCallback((value: boolean) => {
    isUserScrollingRef.current = value
    setIsUserScrollingState(value)
  }, [])

  const scrollToBottom = React.useCallback((force = false) => {
    if (!scrollRef.current) return
    if (suppressAutoScrollRef.current && !force) return
    if (isUserScrollingRef.current && !force) return
    
    const element = scrollRef.current
    const performScroll = () => {
      element.scrollTo({
        top: element.scrollHeight,
        behavior: force ? "smooth" : "auto",
      })
    }
    
    performScroll()
    // A small delay handles late layout shifts (markdown tables, code blocks, etc.)
    if (!force) {
      setTimeout(performScroll, 60)
    }
    
    if (force) setIsUserScrolling(false)
  }, [setIsUserScrolling])

  React.useEffect(() => {
    scrollToBottom()
  }, [messages, reasoningSteps, scrollToBottom])

  const handleScroll = React.useCallback(() => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    // Increased detection threshold for more reliable 'at bottom' check
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 80
    setIsUserScrolling(!isAtBottom)
  }, [setIsUserScrolling])

  React.useEffect(() => {
    return () => {
      if (suppressAutoScrollTimerRef.current !== null) {
        window.clearTimeout(suppressAutoScrollTimerRef.current)
      }
    }
  }, [])

  const scrollToMessage = React.useCallback((id: string) => {
    const element = document.getElementById(`msg-${id}`)
    const container = scrollRef.current
    if (element && container) {
      suppressAutoScrollRef.current = true
      if (suppressAutoScrollTimerRef.current !== null) {
        window.clearTimeout(suppressAutoScrollTimerRef.current)
      }
      setIsUserScrolling(true)
      const containerRect = container.getBoundingClientRect()
      const elementRect = element.getBoundingClientRect()
      const relativeTop = elementRect.top - containerRect.top + container.scrollTop
      container.scrollTo({ top: relativeTop - 24, behavior: "smooth" })
      suppressAutoScrollTimerRef.current = window.setTimeout(() => {
        suppressAutoScrollRef.current = false
      }, 450)
    }
  }, [setIsUserScrolling])

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
    // A fresh chat starts at `/chat`, but once the backend assigns a real
    // conversation id we want the URL to become `/chat/<uuid>`. We defer the
    // route replace until streaming ends so the component is not remounted in
    // the middle of an active SSE response.
    if (conversationId) return
    if (!activeConversationId || isStreaming) return
    if (pathname !== "/chat") return
    router.replace(`/chat/${activeConversationId}`)
  }, [activeConversationId, conversationId, isStreaming, pathname, router])

  const loadConversation = React.useCallback(
    async (conversationIdToLoad: string) => {
      const conversation = await apiJson<ConversationDetail>(`/chat/conversations/${conversationIdToLoad}`)
      const hydratedMessages = [...conversation.messages]
      const lastMessage = hydratedMessages[hydratedMessages.length - 1]
      if (conversation.status === "running" && lastMessage?.role !== "assistant") {
        hydratedMessages.push({
          id: `${conversation.run_id ?? conversation.id}:assistant-pending`,
          role: "assistant",
          content: "",
          created_at: conversation.updated_at,
        })
      }

      const hydratedReasoning: ReasoningStep[] = conversation.trace_events.map((event) => ({
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

      setMessages(hydratedMessages)
      setReasoningSteps(
        conversation.status === "running" && hydratedReasoning.length === 0 ? seededThinkingStep : hydratedReasoning
      )
      setRemoteRunStatus(conversation.status ?? null)
      activeRunIdRef.current = conversation.status === "running" ? conversation.run_id : null
      if (!conversationId) {
        setActiveConversation(conversation.id, "chat")
      }
    },
    [conversationId, seededThinkingStep]
  )

  React.useEffect(() => {
    // When a brand-new conversation receives its first `run` event, we switch
    // to the server-issued conversation id before the stream is finished.
    // Reloading the conversation during that window can replace the locally
    // seeded assistant bubble with a server snapshot that still has empty
    // content, breaking subsequent token updates until a manual refresh.
    if (!activeConversationId || !backendReady || isStreaming) return
    let cancelled = false
    loadConversation(activeConversationId).catch((err: Error) => {
      if (!cancelled) setError(err.message)
    })
    return () => {
      cancelled = true
    }
  }, [activeConversationId, backendReady, isStreaming, loadConversation])

  React.useEffect(() => {
    if (!activeConversationId || !backendReady || isStreaming || remoteRunStatus !== "running") return
    const timer = window.setInterval(() => {
      void loadConversation(activeConversationId).catch(() => {})
    }, 1000)
    return () => window.clearInterval(timer)
  }, [activeConversationId, backendReady, isStreaming, loadConversation, remoteRunStatus])

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
      const scopeReason = describeScopeDecision(event)
      const detailParts = [
        event.decision ? `决策: ${event.decision}` : null,
        scopeReason ?? event.reason ?? null,
        event.confidence !== undefined ? `置信度: ${event.confidence.toFixed(2)}` : null,
      ].filter(Boolean)
      const meta = [
        event.workspace_policy ? `工作区策略：${event.workspace_policy}` : null,
        event.workspace_ids?.length ? `工作区范围：${event.workspace_ids.join(", ")}` : null,
        event.effective_workspace_slugs?.length ? `知识域范围：${event.effective_workspace_slugs.join(", ")}` : null,
        event.selected_project ? `命中项目：${event.selected_project}` : null,
        event.scope_reason_code ? `范围决策：${event.scope_reason_code}` : null,
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

  const handleStop = React.useCallback(async () => {
    const runId = activeRunIdRef.current
    if (!isRunActive) return

    userStoppedRef.current = true
    try {
      if (runId) {
        await apiVoid(`/chat/runs/${runId}/cancel`, { method: "POST" })
      }
    } catch {
      // swallow cancel errors; local abort still stops UI streaming
    } finally {
      streamAbortRef.current?.abort()
      streamAbortRef.current = null
      activeRunIdRef.current = null
      setIsStreaming(false)
      setRemoteRunStatus("cancelled")
    }
  }, [isRunActive])

  const handleSend = React.useCallback(async () => {
    const query = input.trim()
    if (!query || isRunActive || !backendReady) return

    const requestSeed = typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const assistantId = `assistant-${requestSeed}`
    const userId = `user-${requestSeed}`
    setError(null)
    setInput("")
    setReasoningSteps(seededThinkingStep)
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: query },
      { id: assistantId, role: "assistant", content: "" },
    ])
    setIsStreaming(true)
    userStoppedRef.current = false
    const abortController = new AbortController()
    streamAbortRef.current = abortController

    try {
      let response: Response
      try {
        response = await fetch(`${API_BASE_URL}/chat/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: abortController.signal,
          body: JSON.stringify({
            query,
            workspace_slug: selectedWorkspaceSlug === AUTO_WORKSPACE ? undefined : selectedWorkspaceSlug,
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
            if (payload.run_id) {
              activeRunIdRef.current = payload.run_id
            }
          }
          if (event === "run") {
              if (payload.query_id) {
                setActiveConversationId(payload.query_id)
                setActiveConversation(payload.query_id, "chat")
              }
              if (payload.run_id) {
                activeRunIdRef.current = payload.run_id
              }
              setRemoteRunStatus("running")
            }
          if (event === "route") {
            const scopeReason = describeScopeDecision(payload as ReasoningEvent)
            const hasEffectiveScopes = Array.isArray(payload.effective_workspace_slugs)
              ? payload.effective_workspace_slugs.length > 0
              : false
            const routeNode = hasEffectiveScopes || payload.scope_reason_code ? "scope_selector" : "query_router"
            const routeTitle = routeNode === "scope_selector" ? "知识域范围" : "路由决策"
            mergeReasoning({
              node: routeNode,
              title: routeTitle,
              decision: payload.route,
              reason: scopeReason ?? (payload.selected_project ? `命中项目 ${payload.selected_project}` : "已完成路由判断"),
              confidence: payload.confidence,
              workspace_policy: payload.workspace_policy,
              workspace_ids: payload.workspace_ids,
              effective_workspace_slugs: payload.effective_workspace_slugs,
              selected_project: payload.selected_project,
              scope_reason_code: payload.scope_reason_code,
              scope_reason_params: payload.scope_reason_params,
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
              activeRunIdRef.current = payload.run_id ?? activeRunIdRef.current
              setRemoteRunStatus("succeeded")
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
          if (event === "cancelled") {
            if (payload.query_id) {
              setActiveConversationId(payload.query_id)
              setActiveConversation(payload.query_id, "chat")
            }
            activeRunIdRef.current = null
            setRemoteRunStatus("succeeded")
            notifyConversationsUpdated()
            setIsStreaming(false)
            break
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
      if (abortController.signal.aborted) {
        if (!userStoppedRef.current) {
          setRemoteRunStatus("running")
        }
        notifyConversationsUpdated()
        return
      }
      const message = err instanceof Error ? err.message : "对话请求失败"
      setError(message)
      setMessages((prev) =>
        prev.map((item) =>
          item.id === assistantId ? { ...item, content: `对话请求失败：${message}` } : item
        )
      )
    } finally {
      if (streamAbortRef.current === abortController) {
        streamAbortRef.current = null
      }
      activeRunIdRef.current = null
      setIsStreaming(false)
    }
  }, [activeConversationId, backendReady, input, isRunActive, mergeReasoning, seededThinkingStep, selectedWorkspaceSlug])

  return (
    <div className="relative flex h-full w-full overflow-hidden">
      <div className="relative z-10 flex h-full flex-1 flex-col">
        <header className="h-16 shrink-0 border-b border-border/80 bg-background px-6 shadow-sm">
          <div className="flex h-full items-center justify-between">
            <div className="flex items-center gap-4">
              {backHref && (
                <div className="flex items-center border-r border-border pr-4 h-8">
                  <PageBack label={backLabel ?? "返回"} href={backHref} className="mb-0" />
                </div>
              )}
              <DropdownMenu>
                <DropdownMenuTrigger
                  title={
                    selectedWorkspaceSlug === AUTO_WORKSPACE
                      ? "系统会根据问题自动决定知识域范围"
                      : "当前使用显式选择的知识域；命中项目别名时后端仍可能合并项目上下文"
                  }
                  className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted/60"
                >
                  <span className="h-2 w-2 rounded-full bg-green-500" />
                  <span>{selectedWorkspaceLabel}</span>
                  <ChevronDown size={14} className="text-muted-foreground" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-64 border border-border/60 bg-popover/95 backdrop-blur-xl shadow-2xl rounded-xl p-1.5">
                  <DropdownMenuGroup>
                    <DropdownMenuLabel>知识域范围</DropdownMenuLabel>
                    <DropdownMenuRadioGroup value={selectedWorkspaceSlug} onValueChange={setSelectedWorkspaceSlug}>
                      <DropdownMenuRadioItem value={AUTO_WORKSPACE} className="cursor-pointer rounded-lg gap-2 py-2">
                        <div className="flex flex-col">
                          <span className="font-medium">Auto</span>
                          <span className="text-xs text-muted-foreground">系统会根据问题自动决定知识域范围</span>
                        </div>
                      </DropdownMenuRadioItem>
                      <DropdownMenuSeparator className="bg-border/40" />
                      {chatWorkspaceOptions.map((workspace) => (
                        <DropdownMenuRadioItem
                          key={workspace.slug}
                          value={workspace.slug}
                          className="cursor-pointer rounded-lg gap-2 py-2"
                        >
                          <div className="flex min-w-0 flex-col">
                            <span className="flex items-center gap-1.5 font-medium">
                              <Hash size={12} className="text-muted-foreground" />
                              {workspace.name}
                            </span>
                            <span className="truncate text-xs text-muted-foreground">
                              {workspace.description ?? workspace.slug}
                            </span>
                          </div>
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuGroup>
                </DropdownMenuContent>
              </DropdownMenu>
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

        <div className="flex-1 relative min-h-0">
          <div 
            ref={scrollRef}
            onScroll={handleScroll}
            className="h-full overflow-y-auto px-4 py-6 md:px-10 scroll-smooth"
          >
            <div className="mx-auto max-w-3xl min-h-full pb-8">
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
                <MessageList messages={messages} isStreaming={isRunActive} />
              )}
            </div>
          </div>
          <MessageDirectory messages={messages} onNavigate={scrollToMessage} />
        </div>

        <div className="shrink-0 p-4">
          <div className="relative mx-auto max-w-3xl">
            <AnimatePresence>
              {isUserScrolling && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: 10 }}
                  className="absolute -top-12 right-0 z-20"
                >
                  <Button
                    variant="outline"
                    size="icon"
                    className="rounded-full h-8 w-8 shadow-sm border border-border/60 bg-background/80 backdrop-blur-sm text-muted-foreground hover:text-foreground"
                    onClick={() => scrollToBottom(true)}
                  >
                    <ArrowDown size={16} />
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>
            <div
              className={cn(
                "relative flex gap-2 rounded-2xl border border-border/70 bg-card/85 backdrop-blur-md p-2 shadow-[0_16px_40px_rgba(15,23,42,0.06)] dark:shadow-none transition-all duration-300 focus-within:shadow-[0_16px_40px_rgba(15,23,42,0.1)] focus-within:border-border",
                isInputExpanded ? "items-stretch" : "items-end"
              )}
            >
              <Button variant="ghost" size="icon" className="h-10 w-10 shrink-0 rounded-xl text-muted-foreground hover:bg-muted">
                <Paperclip size={18} />
              </Button>
              {isInputExpanded ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="收起输入框"
                  className="absolute right-2 top-2 z-10 h-10 w-10 rounded-xl text-muted-foreground hover:bg-muted hover:text-foreground"
                  onClick={() => setIsInputExpanded(false)}
                >
                  <Minimize2 size={16} />
                </Button>
              ) : null}
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
                className={cn(
                  "min-h-[40px] flex-1 resize-none custom-scrollbar border-none bg-transparent py-2 text-[15px] font-medium leading-relaxed text-foreground outline-none placeholder:text-muted-foreground focus:ring-0 disabled:cursor-not-allowed disabled:text-slate-900 dark:disabled:text-muted-foreground dark:placeholder:text-muted-foreground",
                  isInputExpanded ? "overflow-y-auto pr-14" : "overflow-y-hidden pr-2"
                )}
                style={{ height: `${isInputExpanded ? EXPANDED_TEXTAREA_HEIGHT : COLLAPSED_TEXTAREA_HEIGHT}px` }}
                rows={1}
              />
              <div
                className={cn(
                  "shrink-0",
                  isInputExpanded ? "flex flex-col justify-end gap-2" : "flex items-end gap-2"
                )}
              >
                {!isInputExpanded ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label="展开输入框"
                    className="h-10 w-10 rounded-xl text-muted-foreground hover:bg-muted hover:text-foreground"
                    onClick={() => setIsInputExpanded(true)}
                  >
                    <Maximize2 size={16} />
                  </Button>
                ) : null}
                <Button
                  size="icon"
                  onClick={() => {
                    if (isRunActive) {
                      void handleStop()
                      return
                    }
                    void handleSend()
                  }}
                  disabled={(!input.trim() && !isRunActive) || !backendReady}
                  className="h-10 w-10 shrink-0 rounded-xl bg-primary/90 text-primary-foreground shadow-sm transition-transform hover:bg-primary active:scale-95 disabled:opacity-100 disabled:bg-primary/90"
                >
                  {isRunActive ? <StreamingSquare /> : <Send size={18} className="ml-0.5" />}
                </Button>
              </div>
            </div>
            <div className="mt-2 text-center text-xs text-muted-foreground/80">
              {!backendReady && backendChecked
                ? "后端恢复后刷新页面，即可继续使用对话、历史和检索功能。"
                : isRunActive
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
