"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { Activity, Clock, Database, Layers } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { ScrollArea } from "@/components/ui/scroll-area"
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
  const [selectedTrace, setSelectedTrace] = React.useState<TraceListItem | null>(null)
  const [timeline, setTimeline] = React.useState<TraceTimelineNode[]>([])
  const [totalLatency, setTotalLatency] = React.useState(0)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    apiJson<TraceListResponse>("/traces", { query: { limit: 30 } })
      .then((data) => {
        if (cancelled) return
        setTraces(data.items)
        setSelectedTrace(data.items[0] ?? null)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
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
    return () => {
      cancelled = true
    }
  }, [selectedTrace])

  return (
    <div className="flex w-full h-full p-6 gap-6">
      <Card className="w-1/3 h-full flex flex-col bg-background/50 backdrop-blur-sm border-border/50">
        <div className="p-4 border-b border-border/50 shrink-0">
          <h2 className="font-semibold text-lg flex items-center gap-2">
            <Activity className="text-primary" size={20} />
            最近运行
          </h2>
        </div>
        <ScrollArea className="flex-1 p-2">
          <div className="space-y-2">
            {traces.length === 0 && (
              <div className="p-4 text-sm text-muted-foreground">暂无 trace。完成一次对话后会自动生成。</div>
            )}
            {traces.map((trace) => (
              <button
                key={trace.run_id}
                onClick={() => setSelectedTrace(trace)}
                className={`w-full text-left p-3 rounded-xl cursor-pointer transition-all ${
                  selectedTrace?.run_id === trace.run_id
                    ? "bg-primary/10 border-primary/20 border"
                    : "hover:bg-muted border border-transparent"
                }`}
              >
                <div className="font-medium text-sm mb-2 truncate">{trace.query}</div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge variant="secondary" className="font-normal text-[10px] px-1.5 py-0">
                    {trace.route ?? "unknown"}
                  </Badge>
                  <span className="flex items-center gap-1">
                    <Clock size={12} /> {formatLatency(trace.latency_ms)}
                  </span>
                  <span className="ml-auto">{formatShortDate(trace.created_at)}</span>
                </div>
              </button>
            ))}
          </div>
        </ScrollArea>
      </Card>

      <Card className="flex-1 h-full flex flex-col bg-background/50 backdrop-blur-sm border-border/50 overflow-hidden relative">
        <div className="p-5 border-b border-border/50 shrink-0 flex items-center justify-between bg-background/50">
          <div>
            <h3 className="font-medium text-lg mb-1">{selectedTrace?.query ?? "请选择一次运行"}</h3>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="font-mono">{selectedTrace?.run_id ?? "-"}</span>
              <span>•</span>
              <span className="text-primary">{formatLatency(totalLatency)} 总耗时</span>
            </div>
          </div>
        </div>

        {error && <div className="px-5 py-2 text-sm text-red-500">{error}</div>}

        <ScrollArea className="flex-1 p-6">
          <div className="max-w-3xl mx-auto space-y-6 relative before:absolute before:inset-0 before:ml-2.5 before:-translate-x-px before:h-full before:w-px before:bg-border/50">
            {timeline.length === 0 && (
              <div className="text-sm text-muted-foreground pl-10">当前运行还没有可展示的节点时间线。</div>
            )}
            {timeline.map((node, index) => (
              <TraceNode key={node.id} node={node} delay={index * 0.04} />
            ))}
          </div>
        </ScrollArea>
      </Card>
    </div>
  )
}

function TraceNode({ node, delay }: { node: TraceTimelineNode; delay: number }) {
  const colors =
    {
      route: "bg-blue-500/20 text-blue-500 border-blue-500/30",
      retrieval: "bg-green-500/20 text-green-500 border-green-500/30",
      check: "bg-slate-500/20 text-slate-500 border-slate-500/30",
      tool: "bg-orange-500/20 text-orange-500 border-orange-500/30",
      llm: "bg-purple-500/20 text-purple-500 border-purple-500/30",
    }[node.type] || "bg-primary/20 text-primary border-primary/30"

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
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.25 }}
      className="relative flex items-center gap-4 group"
      style={{ marginLeft: node.indent_level * 24 }}
    >
      <div className={`w-5 h-5 rounded-full border bg-background flex items-center justify-center shrink-0 z-10 ${colors.split(" ")[2]}`}>
        <div className={`w-1.5 h-1.5 rounded-full ${colors.split(" ")[1].replace("text-", "bg-")}`} />
      </div>

      <div className={`flex-1 flex items-center justify-between p-3 rounded-lg border bg-background/40 backdrop-blur-sm transition-all hover:bg-muted/50 ${colors}`}>
        <div className="flex items-center gap-2 min-w-0">
          {icon}
          <span className="font-medium text-sm truncate">{node.title}</span>
          {node.status === "error" && <Badge variant="destructive">error</Badge>}
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <div className="h-1.5 w-24 bg-background rounded-full overflow-hidden">
            <div className={`h-full rounded-full ${colors.split(" ")[1].replace("text-", "bg-")}`} style={{ width }} />
          </div>
          <span className="text-xs font-mono">{formatLatency(node.duration_ms)}</span>
        </div>
      </div>
    </motion.div>
  )
}
