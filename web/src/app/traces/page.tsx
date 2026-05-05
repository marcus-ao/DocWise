"use client"

import * as React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Activity, Clock, Database, Layers } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PageBack } from "@/components/layout/page-back"
import {
  apiJson,
  formatLatency,
  formatShortDate,
  TraceListItem,
  TraceTimelineNode,
  TraceTimelineResponse,
} from "@/lib/api"

type TraceListResponse = {
  items: TraceListItem[]
  total: number
  limit: number
  offset: number
}

export default function TracesPage() {
  const [traces, setTraces] = React.useState<TraceListItem[]>([])
  const [isLoading, setIsLoading] = React.useState(true)
  const [selectedTrace, setSelectedTrace] = React.useState<TraceListItem | null>(null)
  const [timeline, setTimeline] = React.useState<TraceTimelineNode[]>([])
  const [isTimelineLoading, setIsTimelineLoading] = React.useState(false)
  const [totalLatency, setTotalLatency] = React.useState(0)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    apiJson<TraceListResponse>("/traces", { query: { limit: 30 } })
      .then((data) => {
        if (cancelled) return
        setTraces(data.items)
        setSelectedTrace(data.items[0] ?? null)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  React.useEffect(() => {
    if (!selectedTrace) {
      setTimeline([])
      return
    }
    let cancelled = false
    setIsTimelineLoading(true)
    apiJson<TraceTimelineResponse>(`/traces/${selectedTrace.run_id}/timeline`)
      .then((data) => {
        if (!cancelled) {
          setTimeline(data.nodes)
          setTotalLatency(data.total_latency_ms)
        }
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setIsTimelineLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedTrace])

  return (
    <div className="flex w-full h-full p-6 flex-col gap-4">
      <div className="shrink-0">
        <PageBack label="返回控制台" href="/" />
      </div>
      <div className="flex flex-1 gap-6 min-h-0 xl:flex-row flex-col overflow-hidden">
        <div className="w-full xl:w-80 shrink-0 flex flex-col">
          <div className="px-2 mb-4">
            <h2 className="font-semibold text-lg flex items-center gap-2">
              <Activity className="text-foreground" size={20} />
              最近运行
            </h2>
          </div>
        <div className="flex-1 overflow-y-auto custom-scrollbar pr-2 pb-8">
          <motion.div
            variants={{
              hidden: { opacity: 0 },
              show: { opacity: 1, transition: { staggerChildren: 0.04 } }
            }}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-2.5"
          >
            <AnimatePresence mode="popLayout">
              {traces.length === 0 && (
                <div className="p-4 text-sm text-muted-foreground text-center bg-card/20 rounded-xl border border-dashed border-border/50">
                  暂无 trace。完成一次对话后会自动生成。
                </div>
              )}
              {traces.map((trace) => {
                const isActive = selectedTrace?.run_id === trace.run_id;
                return (
                  <motion.button
                    key={trace.run_id}
                    layout
                    variants={{
                      hidden: { opacity: 0, x: -10, scale: 0.98 },
                      show: { opacity: 1, x: 0, scale: 1, transition: { type: "spring", stiffness: 400, damping: 30 } },
                      exit: { opacity: 0, scale: 0.96, transition: { duration: 0.2 } }
                    }}
                    onClick={() => setSelectedTrace(trace)}
                    className={cn(
                      "group relative w-full text-left p-4 rounded-2xl cursor-pointer transition-all duration-300 outline-none border backdrop-blur-sm",
                      isActive
                        ? "bg-card/80 border-border/80 shadow-[0_8px_30px_rgb(0,0,0,0.06)] dark:shadow-none"
                        : "bg-card/20 border-border/30 hover:-translate-y-0.5 hover:bg-card/60 hover:border-border/50 hover:shadow-sm"
                    )}
                  >
                    {isActive && (
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 rounded-r-full bg-primary" />
                    )}
                    <div className={cn("font-semibold text-[14px] mb-2.5 line-clamp-2 transition-colors", isActive ? "text-primary" : "text-foreground/90 group-hover:text-foreground")}>
                      {trace.query}
                    </div>
                    <div className="flex items-center gap-2.5 text-[11px] font-medium text-muted-foreground/70">
                      <span className="px-2 py-0.5 rounded-full bg-muted/60 border border-border/40 uppercase tracking-wide text-foreground/80">
                        {trace.route ?? "unknown"}
                      </span>
                      <span className="flex items-center gap-1 font-mono">
                        <Clock size={12} className="opacity-70" /> {formatLatency(trace.latency_ms)}
                      </span>
                      <span className="ml-auto">{formatShortDate(trace.created_at)}</span>
                    </div>
                  </motion.button>
                )
              })}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>

      <Card className="flex-1 h-full min-h-[420px] flex flex-col bg-card/30 backdrop-blur-md border-border/50 shadow-[0_8px_40px_rgb(0,0,0,0.04)] dark:shadow-none overflow-hidden relative rounded-[1.5rem]">
        <div className="p-5 border-b border-border/40 shrink-0 flex items-center justify-between bg-card/40">
          <div>
            <h3 className="font-medium text-lg mb-1">{selectedTrace?.query ?? "请选择一次运行"}</h3>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="font-mono">{selectedTrace?.run_id ?? "-"}</span>
              <span>•</span>
              <span className="text-foreground">{formatLatency(totalLatency)} 总耗时</span>
            </div>
          </div>
        </div>

        {error && <div className="px-5 py-2 text-sm text-red-500">{error}</div>}

        <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar p-6">
          <div className="max-w-3xl mx-auto space-y-6 relative before:absolute before:inset-0 before:ml-2.5 before:-translate-x-px before:h-full before:w-px before:bg-border/50">
            {timeline.length === 0 && (
              <div className="text-sm text-muted-foreground pl-10">当前运行还没有可展示的节点时间线。</div>
            )}
            {timeline.map((node, index) => (
              <TraceNode key={node.id} node={node} delay={index * 0.04} />
            ))}
          </div>
        </div>
      </Card>
    </div>
  </div>
  )
}

function TraceNode({ node, delay }: { node: TraceTimelineNode; delay: number }) {
  const colors =
    {
      route: "bg-muted text-foreground border-border",
      retrieval: "bg-green-500/20 text-green-500 border-green-500/30",
      check: "bg-slate-500/20 text-slate-500 border-slate-500/30",
      tool: "bg-orange-500/20 text-orange-500 border-orange-500/30",
      llm: "bg-purple-500/20 text-purple-500 border-purple-500/30",
    }[node.type] || "bg-muted text-foreground border-border"

  const icon =
    {
      route: <Layers size={14} />,
      retrieval: <Database size={14} />,
      check: <Activity size={14} />,
      tool: <Activity size={14} />,
      llm: <Activity size={14} />,
    }[node.type] ?? <Activity size={14} />
  const width = `${Math.min(100, Math.max(12, node.duration_ms / 25))}%`

  return (
    <motion.div
      initial={{ opacity: 0, x: 15, scale: 0.98 }}
      animate={{ opacity: 1, x: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 400, damping: 30, delay }}
      className="relative flex items-center gap-4 group"
      style={{ marginLeft: node.indent_level * 24 }}
    >
      <div className={`w-5 h-5 rounded-full border bg-background flex items-center justify-center shrink-0 z-10 shadow-sm ${colors.split(" ")[2]}`}>
        <div className={`w-1.5 h-1.5 rounded-full ${colors.split(" ")[1].replace("text-", "bg-")}`} />
      </div>

      <div className={`flex-1 flex items-center justify-between p-3 rounded-xl border bg-background/40 backdrop-blur-sm transition-all duration-300 hover:bg-muted/50 hover:shadow-sm ${colors}`}>
        <div className="flex items-center gap-2 min-w-0">
          {icon}
          <span className="font-medium text-sm truncate">{node.title}</span>
          {node.status === "error" && <Badge variant="destructive">error</Badge>}
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <div className="h-1.5 w-24 bg-background/80 shadow-inner rounded-full overflow-hidden">
            <motion.div 
              initial={{ width: 0 }}
              animate={{ width }}
              transition={{ delay: delay + 0.15, duration: 0.5, type: "spring", stiffness: 120 }}
              className={`h-full rounded-full ${colors.split(" ")[1].replace("text-", "bg-")}`} 
            />
          </div>
          <span className="text-xs font-mono w-12 text-right opacity-80">{formatLatency(node.duration_ms)}</span>
        </div>
      </div>
    </motion.div>
  )
}
