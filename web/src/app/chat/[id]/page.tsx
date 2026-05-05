"use client"

import { PageBack } from "@/components/layout/page-back"
import { ChatConsole } from "@/components/chat/chat-console"
import { setActiveConversation } from "@/lib/active-conversation"
import * as React from "react"

export default function DynamicChatPage({
  params,
  searchParams,
}: {
  params: { id: string }
  searchParams?: { from?: string }
}) {
  const fromArchive = searchParams?.from === "archive"
  React.useEffect(() => {
    setActiveConversation(params.id, fromArchive ? "archive" : "history")
  }, [fromArchive, params.id])

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-border bg-background px-6 py-4">
        <PageBack label={fromArchive ? "返回存档对话" : "返回历史对话"} href={fromArchive ? "/archive" : "/history"} />
      </div>
      <div className="min-h-0 flex-1">
        <ChatConsole conversationId={params.id} />
      </div>
    </div>
  )
}
