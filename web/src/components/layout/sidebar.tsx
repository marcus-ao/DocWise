"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"
import {
  Activity,
  Archive,
  BarChart2,
  Bot,
  FileText,
  FlaskConical,
  History,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { clearActiveConversation, getActiveConversationId, getActiveConversationSource, setActiveConversation } from "@/lib/active-conversation"
import { useRecentConversations } from "@/lib/use-recent-conversations"
import { ConversationListItem } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ThemeToggle } from "./theme-toggle"

const NAV_ITEMS = [
  { name: "对话", href: "/chat", icon: MessageSquare },
  { name: "历史", href: "/history", icon: History },
  { name: "文档", href: "/documents", icon: FileText },
  { name: "链路", href: "/traces", icon: Activity },
  { name: "评估", href: "/eval", icon: BarChart2 },
  { name: "实验室", href: "/lab", icon: FlaskConical },
  { name: "存档", href: "/archive", icon: Archive },
]

export function Sidebar() {
  const [isCollapsed, setIsCollapsed] = React.useState(false)
  const pathname = usePathname()
  const recent = useRecentConversations(4)
  const [chatHref, setChatHref] = React.useState("/chat")

  React.useEffect(() => {
    const activeId = getActiveConversationId()
    const source = getActiveConversationSource()
    if (activeId) {
      setChatHref(source === "archive" ? `/chat/${activeId}?from=archive` : `/chat/${activeId}?from=history`)
    } else {
      setChatHref("/chat")
    }
  }, [pathname])

  return (
    <motion.aside
      initial={{ width: 280 }}
      animate={{ width: isCollapsed ? 72 : 280 }}
      transition={{ duration: 0.22, ease: "easeInOut" }}
      className="relative z-20 flex h-full shrink-0 flex-col border-r border-border bg-sidebar text-sidebar-foreground"
    >
      <div className="flex h-16 shrink-0 items-center justify-between border-b border-border px-4">
        {!isCollapsed && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex items-center gap-3 text-lg font-semibold tracking-tight">
            <Link href="/" className="group flex items-center gap-3 rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-border bg-card text-foreground shadow-sm transition-all duration-200 group-hover:-translate-y-0.5 group-hover:shadow-md">
                <Bot size={16} />
              </div>
              <div className="flex flex-col leading-none">
                <span className="bg-gradient-to-r from-foreground via-foreground/90 to-foreground/65 bg-clip-text font-semibold tracking-[0.01em] text-transparent transition-all duration-200 group-hover:tracking-[0.03em]">
                  DocWise
                </span>
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground/75">
                  Knowledge Agent
                </span>
              </div>
            </Link>
          </motion.div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsCollapsed((value) => !value)}
          className="ml-auto text-muted-foreground hover:text-foreground"
        >
          {isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </Button>
      </div>

      {!isCollapsed && (
        <div className="px-4 py-4">
          <Link
            href="/chat"
            className="block"
            onClick={() => {
              clearActiveConversation()
              setChatHref("/chat")
            }}
          >
            <Button className="w-full justify-start gap-2 rounded-full border border-border bg-card text-foreground shadow-none transition-all duration-150 hover:scale-[1.015] hover:bg-muted active:scale-[0.995]">
              <Plus size={16} />
              新建对话
            </Button>
          </Link>
        </div>
      )}

      <nav className="flex-1 space-y-1 overflow-y-auto px-3">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href || pathname.startsWith(`${item.href}/`)
          const linkContent = (
            <Link
              href={item.href === "/chat" ? chatHref : item.href}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors outline-none",
                isActive ? "text-foreground font-medium" : "text-muted-foreground hover:text-foreground"
              )}
            >
              {isActive && (
                <motion.div
                  layoutId="sidebar-active-indicator"
                  className="absolute inset-0 rounded-lg bg-muted/80 border border-border/50 shadow-sm dark:shadow-none"
                  transition={{ type: "spring", stiffness: 350, damping: 30 }}
                />
              )}
              {!isActive && (
                <div className="absolute inset-0 rounded-lg bg-muted/0 transition-colors duration-200 group-hover:bg-muted/50" />
              )}
              <item.icon
                size={18}
                className={cn("shrink-0 relative z-10 transition-colors duration-200", isActive ? "text-foreground" : "opacity-70 group-hover:opacity-100")}
              />
              {!isCollapsed && <span className="truncate relative z-10">{item.name}</span>}
            </Link>
          )

          if (isCollapsed) {
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger render={linkContent} />
                <TooltipContent side="right" className="ml-2">
                  {item.name}
                </TooltipContent>
              </Tooltip>
            )
          }

          return <React.Fragment key={item.href}>{linkContent}</React.Fragment>
        })}

        {!isCollapsed && (
          <SidebarSection
            title="最近对话"
            icon={History}
            items={recent}
            pathname={pathname}
            emptyText="暂无历史记录"
            hrefPrefix="/history"
          />
        )}
      </nav>

      <div className="flex shrink-0 items-center justify-between border-t border-border p-4">
        {!isCollapsed && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Settings size={16} />
            <span className="truncate text-xs">v1.0.0-beta</span>
          </div>
        )}
        <ThemeToggle />
      </div>
    </motion.aside>
  )
}

function SidebarSection({
  title,
  icon: Icon,
  items,
  pathname,
  emptyText,
  hrefPrefix,
}: {
  title: string
  icon: typeof History
  items: ConversationListItem[]
  pathname: string
  emptyText: string
  hrefPrefix: string
}) {
  return (
    <div className="mb-2 mt-8">
      <div className="mb-2 flex items-center justify-between px-3">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
        <Link href={hrefPrefix} className="text-[11px] text-muted-foreground transition-colors hover:text-foreground">
          查看全部
        </Link>
      </div>
      <div className="space-y-1">
        {items.length === 0 && <div className="px-3 py-2 text-xs text-muted-foreground">{emptyText}</div>}
        {items.map((item) => {
          const isConversationActive = pathname === `/chat/${item.id}`
          return (
            <Link
              key={item.id}
              href={`/chat/${item.id}?from=history`}
              onClick={() => setActiveConversation(item.id, "history")}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                isConversationActive ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <History size={14} className="shrink-0 opacity-60" />
              <span className="truncate">{item.title}</span>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
