"use client"

import Link from "next/link"
import {
  Activity,
  Archive,
  ArrowRight,
  BarChart2,
  FileText,
  FlaskConical,
  History,
  MessageSquare,
} from "lucide-react"

import { useBackendStatus } from "@/components/providers/backend-status-provider"
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const MODULES = [
  { href: "/chat", title: "Agent 对话", description: "发起新会话，查看引用证据与实时推理过程。", icon: MessageSquare },
  { href: "/history", title: "历史对话", description: "管理全部非归档会话，支持重命名、归档与删除。", icon: History },
  { href: "/documents", title: "文档中心", description: "上传文档、查看索引状态、重试失败任务。", icon: FileText },
  { href: "/traces", title: "执行链路", description: "查看 Agent 节点耗时、执行顺序与链路细节。", icon: Activity },
  { href: "/eval", title: "评估面板", description: "跟踪 RAG 指标、坏例与批次趋势。", icon: BarChart2 },
  { href: "/lab", title: "实验室", description: "对比不同检索策略的召回结果与耗时表现。", icon: FlaskConical },
  { href: "/archive", title: "存档会话", description: "集中查看已归档会话，必要时恢复到历史列表。", icon: Archive },
]

export default function HomePage() {
  const { checked: backendChecked, ready: backendReady, message: backendMessage } = useBackendStatus()

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-8">
        <header className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-4xl font-semibold tracking-tight text-foreground">DocWise 控制台</h1>
          </div>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
            面向企业开发团队的知识工作流工作台，覆盖对话、文档、执行链路、评估、实验与会话归档。
          </p>
          {!backendReady && backendChecked ? (
            <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-600 dark:text-amber-300">
              {backendMessage}
            </div>
          ) : null}
        </header>

        <section className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {MODULES.map((entry, index) => (
            <Link key={entry.href} href={entry.href} className="block outline-none group">
              <Card className="h-full border border-border bg-card/40 backdrop-blur-sm py-0 shadow-[0_8px_30px_rgb(0,0,0,0.02)] transition-all duration-300 hover:scale-[1.015] hover:bg-card/80 hover:shadow-[0_8px_30px_rgb(0,0,0,0.06)] dark:shadow-none dark:hover:bg-muted/30">
                <CardHeader className="space-y-4 px-6 py-6">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-background/50 text-foreground shadow-sm transition-transform duration-300 group-hover:-rotate-3 group-hover:scale-105">
                      <entry.icon size={22} className="opacity-80 transition-opacity duration-300 group-hover:opacity-100" />
                    </div>
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-transparent transition-colors duration-300 group-hover:bg-muted">
                      <ArrowRight size={16} className="text-muted-foreground transition-transform duration-300 group-hover:translate-x-0.5 group-hover:text-foreground" />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <CardTitle className="text-lg font-semibold tracking-tight text-foreground">{entry.title}</CardTitle>
                    <CardDescription className="text-sm leading-relaxed text-muted-foreground">
                      {entry.description}
                    </CardDescription>
                  </div>
                </CardHeader>
              </Card>
            </Link>
          ))}
        </section>
      </div>
    </div>
  )
}
