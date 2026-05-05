"use client"

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
    <ChatConsole
      conversationId={params.id}
      backLabel="返回控制台"
      backHref="/"
    />
  )
}
