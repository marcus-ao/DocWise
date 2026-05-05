"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"
import { clearActiveConversation } from "@/lib/active-conversation"
import { cn } from "@/lib/utils"

export function PageBack({ label, href, className }: { label: string; href?: string; className?: string }) {
  const router = useRouter()
  const targetHref = href ?? "/"

  const handleBack = React.useCallback(() => {
    if (targetHref === "/") {
      clearActiveConversation()
    }
    router.replace(targetHref)
  }, [router, targetHref])

  return (
    <Button
      variant="ghost"
      className={cn("mb-2 gap-2 px-0 text-muted-foreground hover:bg-transparent hover:text-foreground", className)}
      onClick={handleBack}
    >
      <ArrowLeft size={16} />
      {label}
    </Button>
  )
}
