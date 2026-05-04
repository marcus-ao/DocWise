"use client"

import { AlertTriangle } from "lucide-react"

import { useBackendStatus } from "@/components/providers/backend-status-provider"

export function BackendStatusBanner() {
  const { ready, checked, message } = useBackendStatus()

  if (!checked || ready || !message) {
    return null
  }

  return (
    <div className="border-b border-amber-500/30 bg-amber-500/12 px-6 py-3 text-sm text-amber-200 dark:text-amber-100">
      <div className="flex items-center gap-2">
        <AlertTriangle size={16} className="shrink-0" />
        <span>{message}</span>
      </div>
    </div>
  )
}
