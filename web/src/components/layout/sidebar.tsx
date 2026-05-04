"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"
import {
  Activity,
  Archive,
  BarChart2,
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
            <Link href="/" className="flex items-center gap-3 rounded-md px-1 py-0.5 transition-colors hover:text-foreground">
              <div className="flex h-6 w-6 items-center justify-center rounded bg-primary text-sm font-bold text-primary-foreground">
                D
              </div>
              DocWise
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
          <Link href="/chat" className="block">
            <Button className="w-full justify-start gap-2 rounded-full border border-border bg-card text-foreground shadow-none hover:bg-muted">
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
              href={item.href}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors",
                isActive ? "bg-muted font-medium text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
              )}
            >
              <item.icon
                size={18}
                className={cn("shrink-0", isActive ? "text-foreground" : "opacity-70 group-hover:opacity-100")}
              />
              {!isCollapsed && <span className="truncate">{item.name}</span>}
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
