"use client"

import * as React from "react"
import Link from "next/link"
import { Clock, MessageSquare, Search } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { apiJson, ConversationListItem, ConversationListResponse, formatShortDate } from "@/lib/api"

export default function HistoryPage() {
  const [items, setItems] = React.useState<ConversationListItem[]>([])
  const [search, setSearch] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    apiJson<ConversationListResponse>("/chat/conversations", { query: { limit: 60 } })
      .then((data) => {
        if (!cancelled) setItems(data.items)
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = items.filter((chat) => chat.title.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="w-full h-full p-6 flex flex-col gap-6 overflow-hidden">
      <div className="shrink-0 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">历史对话</h1>
          <p className="text-sm text-muted-foreground mt-1">恢复已落库的 Agent 会话与引用回答</p>
        </div>
        <div className="relative w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="pl-9 h-10 bg-background/50"
            placeholder="搜索历史对话..."
          />
        </div>
      </div>

      {error && <div className="text-sm text-red-500">历史记录加载失败：{error}</div>}

      <div className="flex-1 overflow-y-auto min-h-0">
        {filtered.length === 0 ? (
          <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
            暂无历史对话。完成一次真实聊天后，这里会自动出现记录。
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pb-6">
            {filtered.map((chat) => (
              <Card
                key={chat.id}
                className="p-5 bg-background/50 backdrop-blur-sm border-border/50 hover:border-primary/30 hover:bg-muted/30 transition-colors group flex flex-col justify-between"
              >
                <div>
                  <div className="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center shrink-0 mb-3">
                    <MessageSquare size={18} />
                  </div>
                  <h3 className="font-semibold text-lg line-clamp-2 leading-tight mb-2">
                    <Link href={`/chat/${chat.id}`} className="hover:underline decoration-primary/50 underline-offset-4">
                      {chat.title}
                    </Link>
                  </h3>
                </div>

                <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                  <Badge variant="outline" className="font-normal bg-background/50 text-[10px]">
                    {chat.workspace_slug ?? "public_tech"}
                  </Badge>
                  <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1">
                      <MessageSquare size={12} /> {chat.message_count}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock size={12} /> {formatShortDate(chat.updated_at)}
                    </span>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
