"use client"

import * as React from "react"
import Link from "next/link"
import {
  Archive,
  Clock,
  MessageSquare,
  MoreHorizontal,
  PencilLine,
  RotateCcw,
  Search,
  Trash2,
} from "lucide-react"

import { PageBack } from "@/components/layout/page-back"
import { useBackendStatus } from "@/components/providers/backend-status-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  apiJson,
  apiVoid,
  ConversationListItem,
  ConversationListResponse,
  formatShortDate,
} from "@/lib/api"
import { notifyConversationsUpdated, subscribeConversationsUpdated } from "@/lib/conversation-events"

type ConversationListProps = {
  title: string
  description: string
  archived: boolean
  backHref: string
  backLabel: string
  emptyText: string
}

export function ConversationList({
  title,
  description,
  archived,
  backHref,
  backLabel,
  emptyText,
}: ConversationListProps) {
  const { ready: backendReady, checked: backendChecked, message: backendMessage } = useBackendStatus()
  const [items, setItems] = React.useState<ConversationListItem[]>([])
  const [search, setSearch] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [renamingId, setRenamingId] = React.useState<string | null>(null)
  const [titleDraft, setTitleDraft] = React.useState("")

  const source = archived ? "archive" : "history"

  const loadConversations = React.useCallback(async () => {
    if (!backendReady) {
      setItems([])
      setError(null)
      return
    }

    try {
      const data = await apiJson<ConversationListResponse>("/chat/conversations", {
        cache: "no-store",
        query: { limit: 80, archived, _ts: Date.now() },
      })
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载会话列表失败")
    }
  }, [archived, backendReady])

  React.useEffect(() => {
    void loadConversations()
  }, [loadConversations])

  React.useEffect(() => {
    return subscribeConversationsUpdated(() => {
      void loadConversations()
    })
  }, [loadConversations])

  const filtered = items.filter((chat) => chat.title.toLowerCase().includes(search.toLowerCase()))

  async function renameConversation(chat: ConversationListItem) {
    const nextTitle = titleDraft.trim()
    if (!nextTitle) return

    try {
      await apiVoid(`/chat/conversations/${chat.id}/rename`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: nextTitle }),
      })
      setRenamingId(null)
      setTitleDraft("")
      notifyConversationsUpdated()
      await loadConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : "重命名失败")
    }
  }

  async function toggleArchive(chatId: string, nextArchived: boolean) {
    try {
      await apiVoid(`/chat/conversations/${chatId}/archive`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ archived: nextArchived }),
      })
      notifyConversationsUpdated()
      await loadConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : nextArchived ? "存档失败" : "恢复失败")
    }
  }

  async function deleteConversation(chat: ConversationListItem) {
    const confirmed = window.confirm(`确定要删除“${chat.title}”吗？此操作不可恢复。`)
    if (!confirmed) return

    try {
      await apiVoid(`/chat/conversations/${chat.id}`, {
        method: "DELETE",
      })
      notifyConversationsUpdated()
      await loadConversations()
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败")
    }
  }

  return (
    <div className="flex h-full w-full flex-col gap-6 overflow-hidden p-6">
      <div className="shrink-0 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <PageBack label={backLabel} href={backHref} />
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </div>
        <div className="relative w-full md:w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-10 border-border bg-background pl-9 shadow-sm"
            placeholder={`搜索${archived ? "存档" : "历史"}对话...`}
            disabled={!backendReady}
          />
        </div>
      </div>

      {!backendReady && backendChecked ? (
        <div className="shrink-0 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
          {backendMessage}
        </div>
      ) : null}

      {error ? (
        <div className="shrink-0 rounded-lg border border-red-200/80 bg-red-50/80 px-4 py-3 text-sm text-red-600 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300">
          {error}
        </div>
      ) : null}

      <div className="min-h-0 flex-1 overflow-y-auto">
        {!backendReady && backendChecked ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            后端恢复后，这里会显示完整的会话列表。
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{emptyText}</div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm dark:shadow-none">
            <div className="divide-y divide-border">
              {filtered.map((chat) => (
                <div
                  key={chat.id}
                  className="group relative flex items-center gap-4 px-5 py-4 transition-colors hover:bg-muted/30"
                >
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
                    <MessageSquare size={16} />
                  </div>

                  <div className="min-w-0 flex-1">
                    {renamingId === chat.id ? (
                      <div className="flex items-center gap-2">
                        <Input
                          value={titleDraft}
                          onChange={(event) => setTitleDraft(event.target.value)}
                          className="h-9 border-border bg-background shadow-sm"
                          autoFocus
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              void renameConversation(chat)
                            }
                            if (event.key === "Escape") {
                              setRenamingId(null)
                              setTitleDraft("")
                            }
                          }}
                        />
                        <Button size="sm" onClick={() => void renameConversation(chat)}>
                          保存
                        </Button>
                      </div>
                    ) : (
                      <Link
                        href={`/chat/${chat.id}?from=${source}`}
                        className="block truncate text-sm font-medium text-foreground transition-colors hover:text-foreground"
                      >
                        {chat.title}
                      </Link>
                    )}

                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      <Badge variant="outline" className="bg-background text-[10px] font-normal">
                        {chat.workspace_slug ?? "public_tech"}
                      </Badge>
                      <span className="flex items-center gap-1">
                        <MessageSquare size={12} /> {chat.message_count}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock size={12} /> {formatShortDate(chat.updated_at)}
                      </span>
                      {archived ? (
                        <Badge variant="outline" className="bg-muted/40 text-[10px] font-normal">
                          已存档
                        </Badge>
                      ) : null}
                    </div>
                  </div>

                  <DropdownMenu>
                    <DropdownMenuTrigger>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 rounded-md text-muted-foreground opacity-70 transition-opacity hover:bg-muted hover:text-foreground group-hover:opacity-100"
                      >
                        <MoreHorizontal size={16} />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-44 border border-border bg-popover shadow-xl">
                      <DropdownMenuItem
                        className="cursor-pointer"
                        onClick={() => {
                          setRenamingId(chat.id)
                          setTitleDraft(chat.title)
                        }}
                      >
                        <PencilLine size={14} />
                        重命名
                      </DropdownMenuItem>
                      <DropdownMenuItem className="cursor-pointer" onClick={() => void toggleArchive(chat.id, !archived)}>
                        {archived ? <RotateCcw size={14} /> : <Archive size={14} />}
                        {archived ? "恢复到历史" : "存档"}
                      </DropdownMenuItem>
                      <DropdownMenuItem className="cursor-pointer" variant="destructive" onClick={() => void deleteConversation(chat)}>
                        <Trash2 size={14} />
                        删除
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
