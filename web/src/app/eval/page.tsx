"use client"

import * as React from "react"
import { motion } from "framer-motion"
import type { LucideIcon } from "lucide-react"
import { Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip as RechartsTooltip, XAxis, YAxis } from "recharts"
import { AlertTriangle, BarChart2, CheckCircle, Target } from "lucide-react"

import { Card } from "@/components/ui/card"
import { PageBack } from "@/components/layout/page-back"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { apiJson, EvalBadCaseItem, EvalTrendItem } from "@/lib/api"
import { cn } from "@/lib/utils"

type EvalTrendsResponse = {
  trends: EvalTrendItem[]
}

type EvalBadCaseListResponse = {
  items: EvalBadCaseItem[]
  total: number
}

export default function EvalPage() {
  const [trends, setTrends] = React.useState<EvalTrendItem[]>([])
  const [badCases, setBadCases] = React.useState<EvalBadCaseItem[]>([])
  const [isLoading, setIsLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    Promise.all([
      apiJson<EvalTrendsResponse>("/eval/trends", { query: { limit: 10 } }),
      apiJson<EvalBadCaseListResponse>("/eval/bad-cases", { query: { limit: 12 } }),
    ])
      .then(([trendData, badCaseData]) => {
        if (!cancelled) {
          setTrends(trendData.trends)
          setBadCases(badCaseData.items)
        }
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

  const chartData = trends.map((item) => ({
    run: item.run_name,
    hitRate: toPercent(item.hit_rate_at_5),
    mrr: Number((item.mrr ?? 0).toFixed(3)),
    accuracy: toPercent(item.citation_accuracy),
  }))
  const latest = trends[trends.length - 1]

  return (
    <div className="w-full h-full p-6 flex flex-col gap-6 overflow-hidden">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <PageBack label="返回控制台" href="/" />
          <h1 className="text-2xl font-semibold tracking-tight">评估仪表盘</h1>
          <p className="text-sm text-muted-foreground mt-1">从 eval_results 聚合 RAG 检索、引用与坏例趋势</p>
        </div>
      </div>

      {error && <div className="text-sm text-red-500">评估数据加载失败：{error}</div>}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 shrink-0">
        <MetricCard title="Hit Rate @ 5" value={`${toPercent(latest?.hit_rate_at_5)}%`} icon={Target} color="neutral" />
        <MetricCard title="MRR" value={(latest?.mrr ?? 0).toFixed(2)} icon={BarChart2} color="purple" />
        <MetricCard title="Citation Accuracy" value={`${toPercent(latest?.citation_accuracy)}%`} icon={CheckCircle} color="green" />
        <MetricCard title="Bad Cases" value={String(latest?.bad_case_count ?? badCases.length)} icon={AlertTriangle} color="orange" />
        </div>

      <div className="flex gap-6 flex-1 min-h-0 xl:flex-row flex-col">
        <Card className="flex-1 p-6 bg-background/50 backdrop-blur-sm border-border/50 flex flex-col">
          <h3 className="font-semibold mb-6">指标趋势对比</h3>
          <div className="flex-1 min-h-0 w-full">
            {isLoading ? (
              <div className="h-full w-full flex items-end gap-2 p-4">
                {Array.from({ length: 10 }).map((_, i) => (
                  <Skeleton key={i} className="w-full rounded-t-sm" style={{ height: `${Math.random() * 60 + 20}%` }} />
                ))}
              </div>
            ) : chartData.length === 0 ? (
              <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
                暂无评估批次。运行 eval 后会展示趋势曲线。
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="run" stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} tickLine={false} axisLine={false} />
                  <RechartsTooltip
                    contentStyle={{
                      backgroundColor: "hsl(var(--background))",
                      borderColor: "hsl(var(--border))",
                      borderRadius: "8px",
                    }}
                  />
                  <Line type="monotone" dataKey="hitRate" name="Hit Rate %" stroke="#5f6b7a" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                  <Line type="monotone" dataKey="accuracy" name="Citation %" stroke="#22c55e" strokeWidth={3} dot={{ r: 4 }} />
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </Card>

        <Card className="w-full xl:w-1/3 p-0 flex flex-col bg-background/50 backdrop-blur-sm border-border/50 min-h-[320px]">
          <div className="p-4 border-b border-border/50">
            <h3 className="font-semibold flex items-center gap-2">
              <AlertTriangle size={18} className="text-orange-500" />
              最近 Bad Cases
            </h3>
          </div>
          <ScrollArea className="flex-1 p-4">
            <div className="space-y-4">
              {badCases.length === 0 && <div className="text-sm text-muted-foreground">暂无坏例记录。</div>}
              {badCases.map((item) => (
                <div key={item.eval_result_id} className="p-3 rounded-lg border border-border/50 bg-muted/20 hover:bg-muted/50 transition-colors">
                  <div className="text-sm font-medium mb-1 line-clamp-2">{item.query}</div>
                  <div className="text-xs text-muted-foreground line-clamp-2">
                    {item.error_message ?? `case_id: ${item.case_id}`}
                  </div>
                  <div className="mt-2 text-[10px] uppercase text-orange-500 font-semibold">
                    {item.bad_case_types.join(", ")}
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </Card>
      </div>
    </div>
  )
}

function toPercent(value?: number | null) {
  return Math.round((value ?? 0) * 100)
}

function MetricCard({
  title,
  value,
  icon: Icon,
  color,
}: {
  title: string
  value: string
  icon: LucideIcon
  color: "neutral" | "purple" | "green" | "orange"
}) {
  const themes = {
    neutral: {
      text: "text-foreground",
      bg: "bg-foreground/10",
      glow: "bg-foreground/20",
      shadow: "shadow-foreground/5",
    },
    purple: {
      text: "text-purple-500",
      bg: "bg-purple-500/10",
      glow: "bg-purple-500/20",
      shadow: "shadow-purple-500/5",
    },
    green: {
      text: "text-emerald-500",
      bg: "bg-emerald-500/10",
      glow: "bg-emerald-500/20",
      shadow: "shadow-emerald-500/5",
    },
    orange: {
      text: "text-orange-500",
      bg: "bg-orange-500/10",
      glow: "bg-orange-500/20",
      shadow: "shadow-orange-500/5",
    },
  }
  const theme = themes[color] || themes.neutral

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-6 rounded-2xl border border-border/50 bg-card/60 backdrop-blur-md relative overflow-hidden group hover:border-border transition-colors shadow-sm"
    >
      <div className={cn("absolute -right-6 -top-6 w-24 h-24 rounded-full blur-2xl opacity-40 group-hover:opacity-70 transition-all duration-500", theme.glow)} />
      <div className="flex justify-between items-start relative z-10">
        <div>
          <div className="text-sm text-muted-foreground font-medium mb-1">{title}</div>
          <div className="text-3xl font-bold tracking-tight">{value}</div>
        </div>
        <div className={cn("p-2.5 rounded-xl shadow-inner", theme.bg, theme.text, theme.shadow)}>
          <Icon size={20} />
        </div>
      </div>
      <div className="mt-5 text-[11px] uppercase tracking-wider font-semibold text-muted-foreground/70 bg-muted/40 inline-flex px-2 py-0.5 rounded-md relative z-10 border border-border/30">
        最新已完成批次
      </div>
    </motion.div>
  )
}
