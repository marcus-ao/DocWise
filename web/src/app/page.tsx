import Link from "next/link"
import { Activity, BarChart2, FileText, FlaskConical, MessageSquare } from "lucide-react"

const ENTRIES = [
  { href: "/chat", title: "Agent 对话", desc: "流式回答、引用证据与实时思考流", icon: MessageSquare },
  { href: "/documents", title: "知识库", desc: "上传、重建索引和查看文档状态", icon: FileText },
  { href: "/traces", title: "执行链路", desc: "查看 Agent 节点时间线和耗时", icon: Activity },
  { href: "/eval", title: "评估仪表盘", desc: "追踪 RAG 指标与 Bad Cases", icon: BarChart2 },
  { href: "/lab", title: "检索实验室", desc: "对比 vector、keyword、hybrid 和 rerank", icon: FlaskConical },
]

export default function Home() {
  return (
    <div className="w-full h-full p-6 overflow-y-auto">
      <div className="max-w-6xl mx-auto flex flex-col gap-6">
        <header className="pt-2">
          <h1 className="text-3xl font-semibold tracking-tight">DocWise 控制台</h1>
          <p className="text-sm text-muted-foreground mt-2">
            企业开发者知识工作流 Agent：文档 RAG、故障排查、执行链路与评估闭环。
          </p>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {ENTRIES.map((entry) => (
            <Link
              key={entry.href}
              href={entry.href}
              className="group rounded-xl border border-border/50 bg-background/50 p-5 hover:bg-muted/30 hover:border-primary/30 transition-colors"
            >
              <entry.icon size={22} className="text-primary mb-4" />
              <div className="font-semibold text-lg">{entry.title}</div>
              <div className="text-sm text-muted-foreground mt-1">{entry.desc}</div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}
