"use client"

const CONVERSATIONS_UPDATED_EVENT = "docwise:conversations-updated"

export function notifyConversationsUpdated() {
  if (typeof window === "undefined") return
  window.dispatchEvent(new Event(CONVERSATIONS_UPDATED_EVENT))
}

export function subscribeConversationsUpdated(handler: () => void) {
  if (typeof window === "undefined") {
    return () => {}
  }

  window.addEventListener(CONVERSATIONS_UPDATED_EVENT, handler)
  return () => window.removeEventListener(CONVERSATIONS_UPDATED_EVENT, handler)
}
