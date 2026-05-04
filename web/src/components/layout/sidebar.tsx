"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"
import {
  Activity,
  BarChart2,
  FileText,
  FlaskConical,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Settings,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { apiJson, ConversationListItem, ConversationListResponse } from "@/lib/api"
import { cn } from "@/lib/utils"
import { ThemeToggle } from "./theme-toggle"

const NAV_ITEMS = [
  { name: "对话", href: "/chat", icon: MessageSquare },
  { name: "文档", href: "/documents", icon: FileText },
  { name: "链路", href: "/traces", icon: Activity },
  { name: "评估", href: "/eval", icon: BarChart2 },
  { name: "实验室", href: "/lab", icon: FlaskConical },
]

export function Sidebar() {
  const [isCollapsed, setIsCollapsed] = React.useState(false)
  const [history, setHistory] = React.useState<ConversationListItem[]>([])
  const pathname = usePathname()

  React.useEffect(() => {
    let cancelled = false
    apiJson<ConversationListResponse>("/chat/conversations", { query: { limit: 4 } })
      .then((data) => {
        if (!cancelled) setHistory(data.items)
      })
      .catch(() => {
        if (!cancelled) setHistory([])
      })
    return () => {
      cancelled = true
    }
  }, [pathname])

  return (
    <motion.aside
      initial={{ width: 260 }}
      animate={{ width: isCollapsed ? 68 : 260 }}
      transition={{ duration: 0.3, ease: "easeInOut" }}
      className="relative flex flex-col h-full bg-background/50 backdrop-blur-xl border-r border-border/50 shrink-0 z-20"
    >
      <div className="flex items-center justify-between p-4 h-16 shrink-0">
        {!isCollapsed && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="font-semibold text-lg tracking-tight flex items-center gap-2">
            <div className="w-6 h-6 rounded bg-primary flex items-center justify-center text-primary-foreground text-sm font-bold">
              D
            </div>
            DocWise
          </motion.div>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="text-muted-foreground hover:text-foreground ml-auto"
        >
          {isCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </Button>
      </div>

      {!isCollapsed && (
        <div className="px-4 pb-4">
          <Button
            className="w-full justify-start gap-2 rounded-full bg-primary/10 hover:bg-primary/20 text-primary border-none shadow-none"
            render={<Link href="/chat" />}
          >
            <Plus size={16} />
            新建对话
          </Button>
        </div>
      )}

      <nav className="flex-1 px-3 space-y-1 overflow-y-auto mt-2">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href)
          const linkContent = (
            <Link
              href={item.href}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group relative",
                isActive
                  ? "bg-primary/10 text-primary font-medium"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <item.icon size={18} className={cn("shrink-0", isActive ? "text-primary" : "opacity-70 group-hover:opacity-100")} />
              {!isCollapsed && <span className="truncate">{item.name}</span>}
              {isActive && !isCollapsed && (
                <motion.div layoutId="sidebar-active-indicator" className="absolute left-0 top-1/4 bottom-1/4 w-1 bg-primary rounded-r-full" />
              )}
            </Link>
          )

          if (isCollapsed) {
            return (
              <Tooltip key={item.href}>
                <TooltipTrigger>{linkContent}</TooltipTrigger>
                <TooltipContent side="right" className="ml-2">
                  {item.name}
                </TooltipContent>
              </Tooltip>
            )
          }

          return <React.Fragment key={item.href}>{linkContent}</React.Fragment>
        })}

        {!isCollapsed && (
          <div className="mt-8 mb-2">
            <h4 className="px-3 text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              最近对话
            </h4>
            <div className="space-y-1">
              {history.length === 0 && (
                <div className="px-3 py-2 text-xs text-muted-foreground">暂无历史记录</div>
              )}
              {history.map((item) => (
                <Link
                  key={item.id}
                  href={`/chat/${item.id}`}
                  className="flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-muted-foreground hover:bg-muted hover:text-foreground text-sm truncate"
                >
                  <MessageSquare size={14} className="shrink-0 opacity-50" />
                  <span className="truncate">{item.title}</span>
                </Link>
              ))}
            </div>
          </div>
        )}
      </nav>

      <div className="p-4 border-t border-border/50 shrink-0 flex items-center justify-between">
        {!isCollapsed && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Settings size={16} className="cursor-pointer hover:text-foreground transition-colors" />
            <span className="truncate text-xs">v1.0.0-beta</span>
          </div>
        )}
        <ThemeToggle />
      </div>
    </motion.aside>
  )
}
