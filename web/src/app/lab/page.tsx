"use client"

import * as React from "react"
import { ArrowRightLeft, Database, Search, SlidersHorizontal } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { PageBack } from "@/components/layout/page-back"
import { ScrollArea } from "@/components/ui/scroll-area"
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
      <div className="shrink-0">
        <PageBack label="返回控制台" href="/" />
      </div>
      <Card className="shrink-0 p-4 bg-background/50 backdrop-blur-sm border-border/50 flex items-center gap-4">
        <div className="relative flex-1 max-w-2xl">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-10 h-12 text-base bg-background"
            placeholder="输入测试查询..."
          />
        </div>
        <Button className="h-12 px-8 gap-2" onClick={() => void runCompare()} disabled={isRunning}>
          {isRunning ? "对比中" : "运行对比"}
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" className="gap-2">
            <SlidersHorizontal size={16} />
            Top 5
          </Button>
        </div>
      </Card>

      {Object.values(errors).length > 0 && (
        <div className="text-sm text-orange-500">
          部分策略降级：{Object.entries(errors).map(([key, value]) => `${key}: ${value}`).join("；")}
        </div>
      )}

      <div className="flex gap-6 flex-1 min-h-0 xl:flex-row flex-col">
        <StrategyColumn
          title="策略 A: 纯向量检索"
          strategy="vector_only"
          icon={<Database size={16} className="text-foreground" />}
          color="blue"
          chunks={results.vector_only ?? []}
          timingMs={timing.vector_only}
        />
        <StrategyColumn
          title="策略 B: 混合检索 + Rerank"
          strategy="hybrid_rerank"
          icon={<ArrowRightLeft size={16} className="text-purple-500" />}
          color="purple"
          chunks={results.hybrid_rerank ?? []}
          timingMs={timing.hybrid_rerank}
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
}: {
  title: string
  strategy: string
  icon: React.ReactNode
  color: "blue" | "purple"
  chunks: LabChunkResult[]
  timingMs?: number
}) {
  const accent =
    color === "blue"
      ? { bg: "bg-border", text: "text-foreground", border: "border-border" }
      : { bg: "bg-purple-500", text: "text-purple-500", border: "border-purple-500/30" }
  return (
    <div className="flex-1 flex flex-col min-w-0">
      <div className="flex items-center justify-between mb-4 px-1">
        <h3 className="font-medium flex items-center gap-2">
          {icon}
          {title}
        </h3>
        <Badge variant="secondary">{timingMs === undefined ? strategy : `${timingMs}ms`}</Badge>
      </div>
      <Card className="flex-1 bg-background/30 backdrop-blur-sm border-border/50 overflow-hidden flex flex-col">
        <ScrollArea className="flex-1 p-4">
          <div className="space-y-4">
            {chunks.length === 0 && <div className="text-sm text-muted-foreground p-4">暂无召回结果。</div>}
            {chunks.map((chunk) => (
              <div key={`${strategy}-${chunk.id}`} className="p-4 rounded-xl border border-border/50 bg-background/50 relative overflow-hidden group">
                <div className={`absolute top-0 left-0 w-1 h-full ${accent.bg}`} />
                <div className="flex justify-between items-start mb-2 gap-3">
                  <Badge variant="outline" className={`font-mono text-xs ${accent.text} ${accent.border}`}>
                    Score: {chunk.score.toFixed(3)}
                  </Badge>
                  <span className="text-xs text-muted-foreground font-mono truncate">{chunk.chunk_uid ?? chunk.id}</span>
                </div>
                <p className="text-sm leading-relaxed line-clamp-5">{chunk.text}</p>
                <div className="mt-3 text-xs text-muted-foreground truncate">
                  {chunk.doc_name || "未知文档"} {chunk.section_path ? `· ${chunk.section_path}` : ""}
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </Card>
    </div>
  )
}
