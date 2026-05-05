"use client"

const ACTIVE_CONVERSATION_ID_KEY = "docwise:active-conversation-id"
const ACTIVE_CONVERSATION_SOURCE_KEY = "docwise:active-conversation-source"

export function getActiveConversationId() {
  if (typeof window === "undefined") return null
  return window.sessionStorage.getItem(ACTIVE_CONVERSATION_ID_KEY)
}

export function setActiveConversation(id: string | null, source: "chat" | "history" | "archive" = "chat") {
  if (typeof window === "undefined") return
  if (!id) {
    window.sessionStorage.removeItem(ACTIVE_CONVERSATION_ID_KEY)
    window.sessionStorage.removeItem(ACTIVE_CONVERSATION_SOURCE_KEY)
    return
  }
  window.sessionStorage.setItem(ACTIVE_CONVERSATION_ID_KEY, id)
  window.sessionStorage.setItem(ACTIVE_CONVERSATION_SOURCE_KEY, source)
}

export function getActiveConversationSource(): "chat" | "history" | "archive" {
  if (typeof window === "undefined") return "chat"
  const value = window.sessionStorage.getItem(ACTIVE_CONVERSATION_SOURCE_KEY)
  return value === "history" || value === "archive" ? value : "chat"
}

export function clearActiveConversation() {
  setActiveConversation(null)
}
