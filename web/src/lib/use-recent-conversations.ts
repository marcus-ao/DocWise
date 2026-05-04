"use client"

import * as React from "react"

import { useBackendStatus } from "@/components/providers/backend-status-provider"
import { apiJson, ConversationListItem, ConversationListResponse } from "@/lib/api"
import { subscribeConversationsUpdated } from "@/lib/conversation-events"

export function useRecentConversations(limit = 5) {
  const { ready: backendReady } = useBackendStatus()
  const [recent, setRecent] = React.useState<ConversationListItem[]>([])

  const loadRecent = React.useCallback(() => {
    if (!backendReady) {
      setRecent([])
      return () => {}
    }

    let cancelled = false
    apiJson<ConversationListResponse>("/chat/conversations", {
      cache: "no-store",
      query: { limit, archived: false, _ts: Date.now() },
    })
      .then((data) => {
        if (!cancelled) {
          setRecent(data.items.slice(0, limit))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRecent([])
        }
      })

    return () => {
      cancelled = true
    }
  }, [backendReady, limit])

  React.useEffect(() => loadRecent(), [loadRecent])

  React.useEffect(() => {
    return subscribeConversationsUpdated(() => {
      const cleanup = loadRecent()
      const timer = window.setTimeout(() => {
        loadRecent()
      }, 300)
      return () => {
        cleanup()
        window.clearTimeout(timer)
      }
    })
  }, [loadRecent])

  return recent
}
