"use client"

import * as React from "react"
import { AnimatePresence, motion } from "framer-motion"
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
import { Skeleton } from "@/components/ui/skeleton"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
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
import { setActiveConversation } from "@/lib/active-conversation"
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
  const [isLoading, setIsLoading] = React.useState(true)
  const [search, setSearch] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [renamingId, setRenamingId] = React.useState<string | null>(null)
  const [titleDraft, setTitleDraft] = React.useState("")

  const source = archived ? "archive" : "history"

  const loadConversations = React.useCallback(async () => {
    if (!backendReady) {
      setItems([])
      setIsLoading(false)
      setError(null)
      return
    }

    setIsLoading(true)
    try {
      const data = await apiJson<ConversationListResponse>("/chat/conversations", {
        cache: "no-store",
        query: { limit: 80, archived, _ts: Date.now() },
      })
      setItems(data.items)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载会话列表失败")
    } finally {
      setIsLoading(false)
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

  function cancelRenaming() {
    setRenamingId(null)
    setTitleDraft("")
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
      <div className="shrink-0">
        <PageBack label={backLabel} href={backHref} />
      </div>
      <div className="shrink-0 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
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

      <div className="min-h-0 flex-1 overflow-y-auto custom-scrollbar pr-2">
        {!backendReady && backendChecked ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            后端恢复后，这里会显示完整的会话列表。
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{emptyText}</div>
        ) : (
          <motion.div
            variants={{
              hidden: { opacity: 0 },
              show: {
                opacity: 1,
                transition: { staggerChildren: 0.04 }
              }
            }}
            initial="hidden"
            animate="show"
            className="flex flex-col gap-3 pb-8"
          >
            <AnimatePresence mode="popLayout">
              {filtered.map((chat) => (
                <motion.div
                  key={chat.id}
                  layout
                  variants={{
                    hidden: { opacity: 0, y: 12, scale: 0.99 },
                    show: { opacity: 1, y: 0, scale: 1, transition: { type: "spring", stiffness: 400, damping: 30 } },
                    exit: { opacity: 0, scale: 0.96, transition: { duration: 0.2 } }
                  }}
                  className="group relative flex items-center gap-4 rounded-2xl border border-border/50 bg-card/40 px-5 py-4 backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-card/80 hover:border-border hover:shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:hover:bg-muted/30 dark:hover:shadow-none"
                >
                  {/* Visual Accent */}
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 rounded-r-full bg-primary/0 transition-all duration-300 group-hover:bg-primary/40 group-hover:h-10" />

                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-primary/10 bg-primary/5 text-primary/70 transition-colors duration-300 group-hover:bg-primary/10 group-hover:text-primary">
                    <MessageSquare size={18} />
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
                              cancelRenaming()
                            }
                          }}
                        />
                        <Button size="sm" onClick={() => void renameConversation(chat)}>
                          保存
                        </Button>
                        <Button size="sm" variant="ghost" className="px-1.5 text-muted-foreground hover:bg-transparent" onClick={cancelRenaming}>
                          取消
                        </Button>
                      </div>
                    ) : (
                      <Link
                        href={`/chat/${chat.id}?from=${source}`}
                        onClick={() => setActiveConversation(chat.id, source)}
                        className="block truncate text-[15px] font-semibold text-foreground/90 transition-colors hover:text-primary"
                      >
                        {chat.title}
                      </Link>
                    )}

                    <div className="mt-1.5 flex flex-wrap items-center gap-4 text-[11px] font-medium text-muted-foreground/70">
                      <div className="flex items-center gap-1.5 rounded-full bg-muted/50 px-2.5 py-0.5 text-foreground/80 border border-border/40">
                        <span className="w-1 h-1 rounded-full bg-primary/60" />
                        {chat.workspace_slug ?? "public_tech"}
                      </div>
                      <span className="flex items-center gap-1.5">
                        <MessageSquare size={13} className="opacity-70" /> {chat.message_count} 消息
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Clock size={13} className="opacity-70" /> {formatShortDate(chat.updated_at)}
                      </span>
                      {archived ? (
                        <Badge variant="secondary" className="rounded-full bg-amber-500/10 text-amber-600 dark:text-amber-400 border-none px-2.5 h-5 text-[10px]">
                          已存档
                        </Badge>
                      ) : null}
                    </div>
                  </div>

                  <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                    <DropdownMenu>
                      <DropdownMenuTrigger>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-9 w-9 rounded-xl text-muted-foreground hover:bg-muted hover:text-foreground"
                        >
                          <MoreHorizontal size={18} />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-48 border border-border/60 bg-popover/95 backdrop-blur-xl shadow-2xl rounded-xl p-1.5">
                        <DropdownMenuItem
                          className="cursor-pointer rounded-lg gap-2 py-2"
                          onClick={() => {
                            setRenamingId(chat.id)
                            setTitleDraft(chat.title)
                          }}
                        >
                          <PencilLine size={15} className="text-muted-foreground" />
                          <span>重命名</span>
                        </DropdownMenuItem>
                        <DropdownMenuItem className="cursor-pointer rounded-lg gap-2 py-2" onClick={() => void toggleArchive(chat.id, !archived)}>
                          {archived ? <RotateCcw size={15} className="text-muted-foreground" /> : <Archive size={15} className="text-muted-foreground" />}
                          <span>{archived ? "恢复到历史" : "存档会话"}</span>
                        </DropdownMenuItem>
                        <DropdownMenuSeparator className="bg-border/40" />
                        <DropdownMenuItem className="cursor-pointer rounded-lg gap-2 py-2 text-red-500 focus:text-red-500 focus:bg-red-500/10" onClick={() => void deleteConversation(chat)}>
                          <Trash2 size={15} />
                          <span>删除会话</span>
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
    </div>
  )
}
