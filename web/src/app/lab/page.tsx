"use client"

import * as React from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  ArrowRightLeft,
  Database,
  Search,
  SlidersHorizontal,
  Loader2,
  Sparkles,
  FileText,
  Layers,
  Clock,
  GitCompareArrows,
  Hash,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PageBack } from "@/components/layout/page-back"
import { cn } from "@/lib/utils"
import {
  apiJson,
  LabChunkResult,
  LabCompareResponse,
  LabHistoryTurn,
  LabRewriterInfo,
  Workspace,
  WorkspaceListResponse,
} from "@/lib/api"

type StrategyKey = "vector_only" | "keyword_only" | "hybrid" | "hybrid_rerank"

type StrategyMeta = {
  key: StrategyKey
  label: string
  short: string
  icon: React.ReactNode
  color: "blue" | "emerald" | "amber" | "purple"
}

const STRATEGY_META: StrategyMeta[] = [
  { key: "vector_only", label: "纯向量", short: "Vector", icon: <Database size={14} />, color: "blue" },
  { key: "keyword_only", label: "关键词", short: "Keyword", icon: <Search size={14} />, color: "emerald" },
  { key: "hybrid", label: "混合 RRF", short: "Hybrid", icon: <ArrowRightLeft size={14} />, color: "amber" },
  { key: "hybrid_rerank", label: "混合 + Rerank", short: "Rerank", icon: <Sparkles size={14} />, color: "purple" },
]

const STRATEGY_THEME: Record<StrategyMeta["color"], {
  text: string
  bg: string
  border: string
  glow: string
  bar: string
}> = {
  blue: {
    text: "text-blue-500",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
    glow: "group-hover:bg-blue-500/40",
    bar: "bg-blue-500/70",
  },
  emerald: {
    text: "text-emerald-500",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    glow: "group-hover:bg-emerald-500/40",
    bar: "bg-emerald-500/70",
  },
  amber: {
    text: "text-amber-500",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    glow: "group-hover:bg-amber-500/40",
    bar: "bg-amber-500/70",
  },
  purple: {
    text: "text-purple-500",
    bg: "bg-purple-500/10",
    border: "border-purple-500/30",
    glow: "group-hover:bg-purple-500/40",
    bar: "bg-purple-500/70",
  },
}

export default function LabPage() {
  const [query, setQuery] = React.useState("Airflow scheduler 故障排查")
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([])
  const [selectedWorkspaces, setSelectedWorkspaces] = React.useState<string[]>(["public_tech"])
  const [selectedStrategies, setSelectedStrategies] = React.useState<StrategyKey[]>([
    "vector_only",
    "hybrid",
    "hybrid_rerank",
  ])
  const [topK, setTopK] = React.useState(5)
  const [rrfK, setRrfK] = React.useState(60)
  const [rerankTopK, setRerankTopK] = React.useState(5)
  const [showParams, setShowParams] = React.useState(false)
  const [useRewriter, setUseRewriter] = React.useState(true)
  const [routeOverride, setRouteOverride] = React.useState<"auto" | StrategyRoute>("auto")
  const [showHistory, setShowHistory] = React.useState(false)
  const [historyJson, setHistoryJson] = React.useState("")
  const [contextSummary, setContextSummary] = React.useState("")
  const [historyError, setHistoryError] = React.useState<string | null>(null)

  const [results, setResults] = React.useState<Record<string, LabChunkResult[]>>({})
  const [timing, setTiming] = React.useState<Record<string, number>>({})
  const [overlap, setOverlap] = React.useState<Record<string, number>>({})
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [rewriterInfo, setRewriterInfo] = React.useState<LabRewriterInfo | null>(null)
  const [isRunning, setIsRunning] = React.useState(false)

  React.useEffect(() => {
    apiJson<WorkspaceListResponse>("/workspaces")
      .then((data) => {
        setWorkspaces(data.items)
        if (data.items.length && !data.items.some((w) => w.slug === "public_tech")) {
          setSelectedWorkspaces([data.items[0].slug])
        }
      })
      .catch(() => {
        setWorkspaces([])
      })
  }, [])

  const abortControllerRef = React.useRef<AbortController | null>(null)

  const parseHistoryPayload = React.useCallback((): LabHistoryTurn[] | null => {
    if (!historyJson.trim()) return null
    const parsed = JSON.parse(historyJson)
    if (!Array.isArray(parsed)) {
      throw new Error("历史模拟必须是 JSON 数组")
    }
    return parsed as LabHistoryTurn[]
  }, [historyJson])

  const runCompare = React.useCallback(async () => {
    if (!query.trim() || selectedStrategies.length === 0 || selectedWorkspaces.length === 0) return
    let historyTurns: LabHistoryTurn[] | null = null
    try {
      historyTurns = parseHistoryPayload()
      setHistoryError(null)
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "历史模拟 JSON 非法")
      return
    }
    setIsRunning(true)
    setErrors({})

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const data = await apiJson<LabCompareResponse>("/lab/compare", {
        method: "POST",
        signal: controller.signal,
          body: JSON.stringify({
            query,
            workspace_ids: selectedWorkspaces,
            strategies: selectedStrategies,
            top_k: topK,
            rrf_k: rrfK,
            rerank_top_k: rerankTopK,
            use_rewriter: useRewriter,
            route_override: routeOverride === "auto" ? null : routeOverride,
            recent_turns: historyTurns,
            context_summary: contextSummary.trim() || null,
          }),
        })
      if (controller.signal.aborted) return

      setResults(data.results)
      setTiming(data.timing_ms)
      setOverlap(data.overlap_matrix)
      setErrors(data.errors)
      setRewriterInfo(data.rewriter)
    } catch (err) {
      if (controller.signal.aborted) return
      setErrors({ compare: err instanceof Error ? err.message : "检索对比失败" })
      setResults({})
      setTiming({})
      setOverlap({})
      setRewriterInfo(null)
    } finally {
      if (!controller.signal.aborted) {
        setIsRunning(false)
      }
    }
  }, [contextSummary, parseHistoryPayload, query, rerankTopK, rrfK, routeOverride, selectedStrategies, selectedWorkspaces, topK, useRewriter])

  React.useEffect(() => {
    void runCompare()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleStrategy = (key: StrategyKey) => {
    setSelectedStrategies((prev) =>
      prev.includes(key) ? (prev.length > 1 ? prev.filter((s) => s !== key) : prev) : [...prev, key],
    )
  }

  const toggleWorkspace = (slug: string) => {
    setSelectedWorkspaces((prev) =>
      prev.includes(slug) ? (prev.length > 1 ? prev.filter((s) => s !== slug) : prev) : [...prev, slug],
    )
  }

  const activeStrategies = STRATEGY_META.filter((m) => selectedStrategies.includes(m.key))
  const maxTiming = Math.max(1, ...activeStrategies.map((meta) => timing[meta.key] ?? 0))

  return (
    <div className="w-full h-full p-6 flex flex-col gap-5 overflow-y-auto relative custom-scrollbar">
      {/* Dynamic Background Glow */}
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/5 blur-[120px] -z-10 rounded-full" />
      
      <div className="shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <PageBack label="返回控制台" href="/" className="mb-3" />
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-foreground/90">检索实验室</h1>
            <Badge variant="outline" className="bg-primary/5 text-primary border-primary/20 font-mono text-[10px] px-2 py-0.5 rounded-md">LAB-v1</Badge>
          </div>
          <p className="text-[13px] text-muted-foreground mt-1.5">
            实时对比多种检索策略的召回表现与系统耗时，优化知识库检索效果
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => setShowParams((v) => !v)} 
            className={cn("gap-2 rounded-xl px-4 text-[13px] h-9 transition-colors", showParams ? "bg-muted/60 text-foreground" : "text-muted-foreground hover:bg-muted/40")}
          >
            <SlidersHorizontal size={14} />
            {showParams ? "收起参数" : "调节参数"}
          </Button>
          <Button 
            variant="outline" 
            size="sm" 
            className="rounded-xl gap-2 border-border/60 bg-background/40 backdrop-blur-sm hover:bg-muted/50 h-9 px-4 text-[13px]"
            onClick={() => {
              setQuery("Airflow scheduler 故障排查")
              void runCompare()
            }}
          >
            <Clock size={14} />
            重置测试
          </Button>
        </div>
      </div>

      <Card className="shrink-0 p-5 bg-card/60 backdrop-blur-xl border-border/40 shadow-[0_8px_32px_rgba(0,0,0,0.02)] rounded-[24px] flex flex-col gap-4 relative z-10">
        <div className="flex flex-col lg:flex-row items-stretch lg:items-center gap-3">
          <div className="relative flex-1 group">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground transition-all group-focus-within:text-primary group-focus-within:scale-110" size={18} />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-11 h-12 text-[15px] bg-background/50 border-border/40 rounded-2xl focus-visible:ring-primary/20 focus-visible:border-primary/40 transition-all shadow-inner"
              placeholder="输入测试查询，例如: Airflow scheduler 故障排查"
              onKeyDown={(e) => {
                if (e.key === "Enter") void runCompare()
              }}
            />
          </div>
          <Button
            className="h-12 px-8 gap-2 rounded-2xl shadow-[0_8px_20px_rgba(var(--primary),0.15)] dark:shadow-[0_8px_20px_rgba(0,0,0,0.2)] transition-all active:scale-95 bg-primary hover:opacity-90 font-medium"
            onClick={() => void runCompare()}
            disabled={isRunning || selectedStrategies.length === 0 || selectedWorkspaces.length === 0}
          >
            {isRunning ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
            {isRunning ? "对比中..." : "开始对比"}
          </Button>
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-bold mr-2">策略模式</span>
            <div className="flex flex-wrap gap-1.5">
              {STRATEGY_META.map((meta) => {
                const theme = STRATEGY_THEME[meta.color]
                const active = selectedStrategies.includes(meta.key)
                return (
                  <button
                    key={meta.key}
                    type="button"
                    onClick={() => toggleStrategy(meta.key)}
                    className={cn(
                      "h-8 px-3.5 rounded-xl border text-[13px] font-medium flex items-center gap-2 transition-all duration-200",
                      active
                        ? cn(theme.bg, theme.text, theme.border, "shadow-sm scale-[1.02]")
                        : "bg-muted/20 text-muted-foreground border-border/40 hover:bg-muted/40 hover:text-foreground hover:border-border",
                    )}
                  >
                    {meta.icon}
                    {meta.label}
                  </button>
                )
              })}
            </div>
          </div>

          {workspaces.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-bold mr-2">数据范围</span>
              <div className="flex flex-wrap gap-1.5">
                {workspaces.map((ws) => {
                  const active = selectedWorkspaces.includes(ws.slug)
                  return (
                    <button
                      key={ws.slug}
                      type="button"
                      onClick={() => toggleWorkspace(ws.slug)}
                      className={cn(
                        "h-8 px-3.5 rounded-xl border text-[13px] font-medium transition-all duration-200 flex items-center gap-2",
                        active
                          ? "bg-primary/10 text-primary border-primary/30 shadow-sm scale-[1.02]"
                          : "bg-muted/20 text-muted-foreground border-border/40 hover:bg-muted/40 hover:text-foreground hover:border-border",
                      )}
                      title={ws.description ?? ws.name}
                    >
                      <Hash size={12} />
                      {ws.name}
                    </button>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <AnimatePresence initial={false}>
          {showParams && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="overflow-hidden"
            >
              <div className="pt-4 grid grid-cols-1 sm:grid-cols-3 gap-6 border-t border-border/40">
                <ParamSlider
                  label="Recall Count (Top K)"
                  icon={<Layers size={13} />}
                  value={topK}
                  min={1}
                  max={20}
                  onChange={setTopK}
                  hint="每个策略的初筛召回数量"
                />
                <ParamSlider
                  label="RRF Smooth (k)"
                  icon={<GitCompareArrows size={13} />}
                  value={rrfK}
                  min={10}
                  max={200}
                  step={5}
                  onChange={setRrfK}
                  hint="混合排序平滑因子，越大越平衡"
                />
                <ParamSlider
                  label="Rerank Output"
                  icon={<Sparkles size={13} />}
                  value={rerankTopK}
                  min={1}
                  max={20}
                  onChange={setRerankTopK}
                  hint="二次排序后的最终输出数量"
                />
                <div className="flex flex-col gap-2">
                  <span className="text-xs font-medium text-foreground/80">Rewriter 开关</span>
                  <button
                    type="button"
                    onClick={() => setUseRewriter((prev) => !prev)}
                    className={cn(
                      "h-10 rounded-xl border text-sm font-medium transition-colors",
                      useRewriter
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border/50 bg-muted/20 text-muted-foreground",
                    )}
                  >
                    {useRewriter ? "已启用 rewrite" : "已关闭 rewrite"}
                  </button>
                  <span className="text-[10px] text-muted-foreground/70">对比直检索与改写后检索</span>
                </div>
                <div className="flex flex-col gap-2">
                  <span className="text-xs font-medium text-foreground/80">Route Override</span>
                  <select
                    value={routeOverride}
                    onChange={(event) => setRouteOverride(event.target.value as "auto" | StrategyRoute)}
                    className="h-10 rounded-xl border border-border/50 bg-background/50 px-3 text-sm text-foreground"
                  >
                    <option value="auto">Auto</option>
                    <option value="tech_general">tech_general</option>
                    <option value="project_specific">project_specific</option>
                    <option value="troubleshooting">troubleshooting</option>
                    <option value="runbook_generation">runbook_generation</option>
                  </select>
                  <span className="text-[10px] text-muted-foreground/70">用于对齐生产 route 行为</span>
                </div>
              </div>
              <div className="pt-4 border-t border-border/40 flex flex-col gap-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-xs font-medium text-foreground/80">对话历史模拟</div>
                    <div className="text-[10px] text-muted-foreground/70">为 follow-up query 提供 recent_turns 与 summary</div>
                  </div>
                  <Button variant="ghost" size="sm" className="rounded-xl text-xs" onClick={() => setShowHistory((prev) => !prev)}>
                    {showHistory ? "收起" : "展开"}
                  </Button>
                </div>
                {showHistory && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="flex flex-col gap-2">
                      <label className="text-xs font-medium text-foreground/80">recent_turns JSON</label>
                      <textarea
                        value={historyJson}
                        onChange={(event) => setHistoryJson(event.target.value)}
                        className="min-h-[150px] rounded-2xl border border-border/50 bg-background/50 px-3 py-3 font-mono text-xs text-foreground outline-none focus:border-primary/40"
                        placeholder='[{"query":"Airflow 报错怎么办？","answer":"先看日志","tool_facts":["query_service_status: service=airflow status=degraded alerts=1"]}]'
                      />
                    </div>
                    <div className="flex flex-col gap-2">
                      <label className="text-xs font-medium text-foreground/80">context_summary</label>
                      <textarea
                        value={contextSummary}
                        onChange={(event) => setContextSummary(event.target.value)}
                        className="min-h-[150px] rounded-2xl border border-border/50 bg-background/50 px-3 py-3 text-xs text-foreground outline-none focus:border-primary/40"
                        placeholder="例如：当前在排查 Airflow scheduler 故障，前序结论是日志里出现 heartbeat lag。"
                      />
                    </div>
                  </div>
                )}
                {historyError && <div className="text-xs text-orange-600 dark:text-orange-400">{historyError}</div>}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </Card>

      {Object.values(errors).length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="shrink-0 rounded-2xl border border-orange-500/20 bg-orange-500/5 px-4 py-3 text-sm text-orange-600 dark:text-orange-400 backdrop-blur-md flex items-center gap-2"
        >
          <ArrowRightLeft size={16} />
          部分策略降级：{Object.entries(errors).map(([key, value]) => `${key}: ${value}`).join("；")}
        </motion.div>
      )}

      {rewriterInfo && (
        <Card className="shrink-0 p-4 bg-card/60 backdrop-blur-md border-border/50 rounded-2xl">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles size={14} className="text-primary" />
            <h3 className="text-sm font-semibold text-foreground/90">Rewrite 诊断</h3>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 text-xs">
            <RewriteField label="Route" value={rewriterInfo.route} />
            <RewriteField label="Fallback" value={rewriterInfo.fallback_reason || "none"} />
            <RewriteField label="使用状态" value={rewriterInfo.used ? "enabled" : "disabled"} />
            <RewriteField label="Original" value={rewriterInfo.original_query} />
            <RewriteField label="Rewritten" value={rewriterInfo.rewritten_query} />
            <RewriteField label="Effective" value={rewriterInfo.effective_query} />
          </div>
          {rewriterInfo.missing_entities.length > 0 && (
            <div className="mt-3 text-xs text-orange-600 dark:text-orange-400">
              缺失关键实体：{rewriterInfo.missing_entities.join(", ")}
            </div>
          )}
          {rewriterInfo.diagnostic_hint && (
            <div className="mt-2 text-xs text-muted-foreground">{rewriterInfo.diagnostic_hint}</div>
          )}
        </Card>
      )}

      <div className="flex-1 min-h-0 flex flex-col gap-5">
        {activeStrategies.length > 0 && Object.keys(timing).length > 0 && (
          <div className="shrink-0 grid grid-cols-1 lg:grid-cols-2 gap-5">
            <TimingCard strategies={activeStrategies} timing={timing} maxTiming={maxTiming} />
            <OverlapCard strategies={activeStrategies} overlap={overlap} />
          </div>
        )}

        <div className="flex-1 min-h-[500px] flex gap-4 overflow-x-auto custom-scrollbar pb-2">
          {activeStrategies.map((meta) => (
            <StrategyColumn
              key={meta.key}
              meta={meta}
              chunks={results[meta.key]}
              timingMs={timing[meta.key]}
              isLoading={isRunning}
              error={errors[meta.key]}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

type StrategyRoute = "tech_general" | "project_specific" | "troubleshooting" | "runbook_generation"

function RewriteField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border/40 bg-background/40 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">{label}</div>
      <div className="text-foreground/90 break-words">{value || "—"}</div>
    </div>
  )
}

function ParamSlider({
  label,
  icon,
  value,
  min,
  max,
  step = 1,
  onChange,
  hint,
}: {
  label: string
  icon: React.ReactNode
  value: number
  min: number
  max: number
  step?: number
  onChange: (value: number) => void
  hint?: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground/80 flex items-center gap-1.5">
          <span className="text-muted-foreground">{icon}</span>
          {label}
        </span>
        <span className="text-xs font-mono font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded">
          {value}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 bg-muted/60 rounded-full appearance-none cursor-pointer accent-primary"
      />
      {hint && <span className="text-[10px] text-muted-foreground/70">{hint}</span>}
    </div>
  )
}

function TimingCard({
  strategies,
  timing,
  maxTiming,
}: {
  strategies: StrategyMeta[]
  timing: Record<string, number>
  maxTiming: number
}) {
  return (
    <Card className="p-4 bg-card/60 backdrop-blur-md border-border/50 rounded-2xl">
      <div className="flex items-center gap-2 mb-3">
        <Clock size={14} className="text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground/90">耗时对比</h3>
      </div>
      <div className="flex flex-col gap-2">
        {strategies.map((meta) => {
          const ms = timing[meta.key] ?? 0
          const theme = STRATEGY_THEME[meta.color]
          const pct = (ms / maxTiming) * 100
          return (
            <div key={meta.key} className="flex items-center gap-3">
              <span className={cn("text-xs font-medium w-24 flex items-center gap-1.5", theme.text)}>
                {meta.icon}
                {meta.short}
              </span>
              <div className="flex-1 h-5 bg-muted/40 rounded-full overflow-hidden relative">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                  className={cn("h-full rounded-full", theme.bar)}
                />
              </div>
              <span className="text-xs font-mono font-semibold w-16 text-right text-foreground/80">{ms}ms</span>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function OverlapCard({
  strategies,
  overlap,
}: {
  strategies: StrategyMeta[]
  overlap: Record<string, number>
}) {
  const names = strategies.map((s) => s.key)
  const lookup = (a: string, b: string): number | null => {
    if (a === b) return 1
    return overlap[`${a}_vs_${b}`] ?? overlap[`${b}_vs_${a}`] ?? null
  }
  const cellColor = (value: number | null) => {
    if (value === null) return "bg-muted/30 text-muted-foreground/60"
    if (value >= 0.75) return "bg-emerald-500/25 text-emerald-700 dark:text-emerald-300"
    if (value >= 0.5) return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400"
    if (value >= 0.25) return "bg-amber-500/15 text-amber-700 dark:text-amber-400"
    if (value > 0) return "bg-orange-500/10 text-orange-700 dark:text-orange-400"
    return "bg-muted/40 text-muted-foreground"
  }
  return (
    <Card className="p-4 bg-card/60 backdrop-blur-md border-border/50 rounded-2xl">
      <div className="flex items-center gap-2 mb-3">
        <GitCompareArrows size={14} className="text-muted-foreground" />
        <h3 className="text-sm font-semibold text-foreground/90">策略重叠度（Jaccard）</h3>
      </div>
      {strategies.length < 2 ? (
        <div className="text-xs text-muted-foreground py-4 text-center">选择至少 2 个策略查看重叠度</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="text-left font-medium text-muted-foreground px-2 py-1.5"></th>
                {strategies.map((meta) => {
                  const theme = STRATEGY_THEME[meta.color]
                  return (
                    <th key={meta.key} className={cn("font-medium px-2 py-1.5 text-center", theme.text)}>
                      {meta.short}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {names.map((rowKey, rowIdx) => {
                const rowMeta = strategies[rowIdx]
                const rowTheme = STRATEGY_THEME[rowMeta.color]
                return (
                  <tr key={rowKey}>
                    <td className={cn("font-medium px-2 py-1.5", rowTheme.text)}>{rowMeta.short}</td>
                    {names.map((colKey) => {
                      const val = lookup(rowKey, colKey)
                      return (
                        <td key={colKey} className="px-1 py-1">
                          <div
                            className={cn(
                              "h-8 rounded-md flex items-center justify-center font-mono text-[11px] font-semibold",
                              cellColor(val),
                            )}
                          >
                            {val === null ? "-" : val.toFixed(2)}
                          </div>
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function StrategyColumn({
  meta,
  chunks,
  timingMs,
  isLoading,
  error,
}: {
  meta: StrategyMeta
  chunks?: LabChunkResult[]
  timingMs?: number
  isLoading?: boolean
  error?: string
}) {
  const theme = STRATEGY_THEME[meta.color]
  return (
    <div className="flex-1 min-w-[260px] flex flex-col min-h-0">
      <div className="flex items-center justify-between mb-3 px-1 shrink-0">
        <h3 className="font-semibold text-[14px] flex items-center gap-2 text-foreground/90">
          <span className={cn("p-1.5 rounded-lg", theme.bg, theme.text)}>{meta.icon}</span>
          {meta.label}
        </h3>
        <Badge variant="secondary" className="font-mono bg-muted/60 border border-border/40 text-xs px-2 py-0.5">
          {timingMs === undefined ? (isLoading ? "..." : meta.key) : `${timingMs}ms`}
        </Badge>
      </div>

      <div className="flex-1 bg-card/30 backdrop-blur-md border border-border/50 overflow-hidden flex flex-col rounded-2xl shadow-[0_8px_40px_rgb(0,0,0,0.02)] dark:shadow-none">
        <div className="flex-1 overflow-y-auto custom-scrollbar p-4">
          <motion.div
            variants={{
              hidden: { opacity: 0 },
              show: { opacity: 1, transition: { staggerChildren: 0.04 } },
            }}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-3 pb-2"
          >
            <AnimatePresence mode="popLayout">
              {isLoading ? (
                renderSkeletons(theme)
              ) : error ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex flex-col items-center justify-center h-40 text-xs text-orange-600 dark:text-orange-400 bg-orange-500/5 rounded-xl border border-dashed border-orange-500/30 px-4 text-center"
                >
                  <Layers size={24} className="mb-2 opacity-40" />
                  策略执行失败
                  <span className="mt-1 text-[11px] opacity-70 line-clamp-2">{error}</span>
                </motion.div>
              ) : !chunks || chunks.length === 0 ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex flex-col items-center justify-center h-40 text-xs text-muted-foreground bg-card/20 rounded-xl border border-dashed border-border/50"
                >
                  <Layers size={24} className="mb-2 opacity-20" />
                  暂无召回结果
                </motion.div>
              ) : (
                chunks.map((chunk, index) => (
                  <ChunkCard key={`${meta.key}-${chunk.id}-${index}`} meta={meta} chunk={chunk} index={index} />
                ))
              )}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </div>
  )
}

function renderSkeletons(theme: { bg: string; text: string; border: string }) {
  return Array.from({ length: 3 }).map((_, i) => (
    <motion.div
      key={`skeleton-${i}`}
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="p-4 rounded-xl border border-border/30 bg-card/20 flex flex-col gap-3"
    >
      <div className="flex justify-between items-center">
        <Skeleton className="h-5 w-24 rounded-md opacity-40" />
        <Skeleton className="h-4 w-32 rounded-md opacity-20" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-full rounded-md opacity-30" />
        <Skeleton className="h-4 w-[90%] rounded-md opacity-25" />
        <Skeleton className="h-4 w-[40%] rounded-md opacity-20" />
      </div>
      <div className="mt-2 pt-2 border-t border-border/20 flex items-center gap-2">
        <Skeleton className="h-3 w-3 rounded-full opacity-20" />
        <Skeleton className="h-3 w-40 rounded-md opacity-20" />
      </div>
    </motion.div>
  ))
}

function ChunkCard({ meta, chunk, index }: { meta: StrategyMeta; chunk: LabChunkResult; index: number }) {
  const theme = STRATEGY_THEME[meta.color]
  return (
    <motion.div
      layout
      variants={{
        hidden: { opacity: 0, y: 12, scale: 0.98 },
        show: {
          opacity: 1,
          y: 0,
          scale: 1,
          transition: { type: "spring", stiffness: 400, damping: 30 },
        },
        exit: { opacity: 0, scale: 0.96, transition: { duration: 0.2 } },
      }}
      className="group relative flex flex-col p-4 rounded-xl border border-border/50 bg-card/50 backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-card/80 hover:shadow-[0_8px_24px_rgb(0,0,0,0.04)] dark:hover:shadow-none"
    >
      <div
        className={cn(
          "absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 rounded-r-full bg-primary/0 transition-all duration-300 group-hover:h-12",
          theme.glow,
        )}
      />

      <div className="flex justify-between items-start mb-2 gap-2">
        <Badge
          variant="outline"
          className={cn(
            "font-mono text-[11px] font-semibold px-2 py-0.5 border",
            theme.text,
            theme.border,
            theme.bg,
          )}
        >
          #{index + 1} · {chunk.score.toFixed(3)}
        </Badge>
        <span className="text-[10px] text-muted-foreground/60 font-mono truncate px-2 py-0.5 bg-muted/30 rounded border border-border/40 max-w-[140px]">
          {chunk.chunk_uid ?? chunk.id}
        </span>
      </div>

      <p className="text-[13px] leading-relaxed text-foreground/90 line-clamp-5 mb-2 font-medium">{chunk.text}</p>

      <div className="mt-auto pt-2 border-t border-border/40 flex items-center gap-1.5 text-[11px] text-muted-foreground/80 truncate">
        <FileText size={11} className="shrink-0 opacity-70" />
        <span className="truncate">{chunk.doc_name || "未知文档"}</span>
        {chunk.section_path && (
          <>
            <span className="opacity-50">•</span>
            <span className="truncate">{chunk.section_path}</span>
          </>
        )}
      </div>
    </motion.div>
  )
}
