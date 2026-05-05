"use client"

import * as React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ArrowRightLeft, Database, Search, SlidersHorizontal, Loader2, Sparkles, FileText, Layers } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PageBack } from "@/components/layout/page-back"
import { cn } from "@/lib/utils"
import { apiJson, LabChunkResult, LabCompareResponse } from "@/lib/api"

const STRATEGIES = ["vector_only", "hybrid_rerank"]

export default function LabPage() {
  const [query, setQuery] = React.useState("Airflow scheduler 故障排查")
  const [results, setResults] = React.useState<Record<string, LabChunkResult[]>>({})
  const [timing, setTiming] = React.useState<Record<string, number>>({})
  const [errors, setErrors] = React.useState<Record<string, string>>({})
  const [isRunning, setIsRunning] = React.useState(false)

  const runCompare = React.useCallback(async () => {
    if (!query.trim()) return
    setIsRunning(true)
    setErrors({})
    try {
      const data = await apiJson<LabCompareResponse>("/lab/compare", {
        method: "POST",
        body: JSON.stringify({
          query,
          workspace_ids: ["public_tech"],
          strategies: STRATEGIES,
          top_k: 5,
        }),
      })
      setResults(data.results)
      setTiming(data.timing_ms)
      setErrors(data.errors)
    } catch (err) {
      setErrors({ compare: err instanceof Error ? err.message : "检索对比失败" })
      setResults({})
    } finally {
      setIsRunning(false)
    }
  }, [query])

  React.useEffect(() => {
    void runCompare()
  }, [runCompare])

  return (
    <div className="w-full h-full p-6 flex flex-col gap-6 overflow-hidden">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <PageBack label="返回控制台" href="/" />
          <h1 className="text-3xl font-bold tracking-tight text-foreground/90">检索实验室</h1>
          <p className="text-sm text-muted-foreground mt-1">对比不同检索策略与 Rerank 算法的召回结果与耗时表现</p>
        </div>
      </div>

      <Card className="shrink-0 p-3 bg-card/60 backdrop-blur-md border-border/50 shadow-sm rounded-2xl flex flex-col sm:flex-row items-center gap-4 relative z-10">
        <div className="relative flex-1 w-full group">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" size={18} />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-11 h-12 text-[15px] bg-background/50 border-border/50 rounded-xl focus-visible:ring-primary/20 shadow-inner"
            placeholder="输入测试查询，例如: Airflow scheduler 故障排查"
            onKeyDown={(e) => {
              if (e.key === 'Enter') void runCompare();
            }}
          />
        </div>
        <div className="flex items-center gap-3 w-full sm:w-auto">
          <Button variant="outline" className="h-12 px-4 rounded-xl gap-2 border-border/50 bg-background/50 hover:bg-muted">
            <SlidersHorizontal size={16} className="text-muted-foreground" />
            <span className="font-medium">Top 5</span>
          </Button>
          <Button className="h-12 px-8 gap-2 rounded-xl shadow-sm transition-all active:scale-95" onClick={() => void runCompare()} disabled={isRunning}>
            {isRunning ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
            {isRunning ? "对比中..." : "运行对比"}
          </Button>
        </div>
      </Card>

      {Object.values(errors).length > 0 && (
        <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="shrink-0 rounded-xl border border-orange-500/20 bg-orange-500/10 px-4 py-3 text-sm text-orange-600 dark:text-orange-400 backdrop-blur-sm">
          部分策略降级：{Object.entries(errors).map(([key, value]) => `${key}: ${value}`).join("；")}
        </motion.div>
      )}

      <div className="flex gap-6 flex-1 min-h-0 xl:flex-row flex-col">
        <StrategyColumn
          title="策略 A: 纯向量检索"
          strategy="vector_only"
          icon={<Database size={16} />}
          color="blue"
          chunks={results.vector_only}
          timingMs={timing.vector_only}
          isLoading={isRunning}
        />
        <StrategyColumn
          title="策略 B: 混合检索 + Rerank"
          strategy="hybrid_rerank"
          icon={<ArrowRightLeft size={16} />}
          color="purple"
          chunks={results.hybrid_rerank}
          timingMs={timing.hybrid_rerank}
          isLoading={isRunning}
        />
      </div>
    </div>
  )
}

function StrategyColumn({
  title,
  strategy,
  icon,
  color,
  chunks,
  timingMs,
  isLoading,
}: {
  title: string
  strategy: string
  icon: React.ReactNode
  color: "blue" | "purple"
  chunks?: LabChunkResult[]
  timingMs?: number
  isLoading?: boolean
}) {
  const themes = {
    blue: { text: "text-blue-500", bg: "bg-blue-500/10", border: "border-blue-500/20", glow: "group-hover:bg-blue-500/40" },
    purple: { text: "text-purple-500", bg: "bg-purple-500/10", border: "border-purple-500/20", glow: "group-hover:bg-purple-500/40" },
  }
  const theme = themes[color]

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="flex items-center justify-between mb-4 px-2 shrink-0">
        <h3 className="font-semibold text-[15px] flex items-center gap-2.5 text-foreground/90">
          <div className={cn("p-1.5 rounded-lg", theme.bg, theme.text)}>
            {icon}
          </div>
          {title}
        </h3>
        <Badge variant="secondary" className="font-mono bg-muted/60 border border-border/40 text-xs px-2.5 py-0.5">
          {timingMs === undefined ? (isLoading ? "..." : strategy) : `${timingMs}ms`}
        </Badge>
      </div>
      
      <div className="flex-1 bg-card/30 backdrop-blur-md border border-border/50 overflow-hidden flex flex-col rounded-[1.5rem] shadow-[0_8px_40px_rgb(0,0,0,0.02)] dark:shadow-none">
        <div className="flex-1 overflow-y-auto custom-scrollbar p-5">
          <motion.div 
            variants={{
              hidden: { opacity: 0 },
              show: { opacity: 1, transition: { staggerChildren: 0.05 } }
            }}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-4 pb-4"
          >
            <AnimatePresence mode="popLayout">
              {isLoading ? (
                Array.from({ length: 3 }).map((_, i) => (
                  <motion.div 
                    key={`skeleton-${i}`} 
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="p-5 rounded-2xl border border-border/30 bg-card/20 flex flex-col gap-3"
                  >
                    <div className="flex justify-between">
                      <Skeleton className="h-5 w-24 rounded-md" />
                      <Skeleton className="h-4 w-32 rounded-md" />
                    </div>
                    <Skeleton className="h-16 w-full rounded-md" />
                    <Skeleton className="h-4 w-48 rounded-md mt-2" />
                  </motion.div>
                ))
              ) : !chunks || chunks.length === 0 ? (
                <motion.div 
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex flex-col items-center justify-center h-48 text-sm text-muted-foreground bg-card/20 rounded-2xl border border-dashed border-border/50"
                >
                  <Layers size={32} className="mb-3 opacity-20" />
                  暂无召回结果
                </motion.div>
              ) : (
                chunks.map((chunk, index) => (
                  <motion.div 
                    key={`${strategy}-${chunk.id}-${index}`}
                    layout
                    variants={{
                      hidden: { opacity: 0, y: 15, scale: 0.98 },
                      show: { opacity: 1, y: 0, scale: 1, transition: { type: "spring", stiffness: 400, damping: 30 } },
                      exit: { opacity: 0, scale: 0.96, transition: { duration: 0.2 } }
                    }}
                    className="group relative flex flex-col p-5 rounded-2xl border border-border/50 bg-card/50 backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-card/80 hover:shadow-[0_8px_30px_rgb(0,0,0,0.05)] dark:hover:shadow-none"
                  >
                    <div className={cn("absolute left-0 top-1/2 -translate-y-1/2 w-1 h-10 rounded-r-full bg-primary/0 transition-all duration-300 group-hover:h-14", theme.glow)} />
                    
                    <div className="flex justify-between items-start mb-3 gap-3">
                      <Badge variant="outline" className={cn("font-mono text-xs font-semibold px-2 py-0.5 border", theme.text, theme.border, theme.bg)}>
                        Score: {chunk.score.toFixed(3)}
                      </Badge>
                      <span className="text-[11px] text-muted-foreground/60 font-mono truncate px-2 py-0.5 bg-muted/30 rounded-md border border-border/40">
                        {chunk.chunk_uid ?? chunk.id}
                      </span>
                    </div>
                    
                    <p className="text-[14px] leading-relaxed text-foreground/90 line-clamp-5 mb-3 font-medium">
                      {chunk.text}
                    </p>
                    
                    <div className="mt-auto pt-3 border-t border-border/40 flex items-center gap-2 text-xs text-muted-foreground/80 truncate">
                      <FileText size={13} className="shrink-0 opacity-70" />
                      <span className="truncate">{chunk.doc_name || "未知文档"}</span>
                      {chunk.section_path && (
                        <>
                          <span className="opacity-50">•</span>
                          <span className="truncate">{chunk.section_path}</span>
                        </>
                      )}
                    </div>
                  </motion.div>
                ))
              )}
            </AnimatePresence>
          </motion.div>
        </div>
      </div>
    </div>
  )
}
