"use client"

import * as React from "react"
import { useRouter } from "next/navigation"

import { getActiveConversationId, getActiveConversationSource } from "@/lib/active-conversation"
import { ChatConsole } from "@/components/chat/chat-console"

export function ChatPageEntry() {
  const router = useRouter()
  const [resolved, setResolved] = React.useState(false)
  const [showFreshChat, setShowFreshChat] = React.useState(false)

  React.useEffect(() => {
    const activeId = getActiveConversationId()
    if (activeId) {
      const source = getActiveConversationSource()
      router.replace(source === "archive" ? `/chat/${activeId}?from=archive` : `/chat/${activeId}?from=history`)
      return
    }
    setShowFreshChat(true)
    setResolved(true)
  }, [router])

  if (!resolved && !showFreshChat) {
    return <div className="h-full w-full" />
  }

  return <ChatConsole />
}
