"use client"

import * as React from "react"
import { useRouter } from "next/navigation"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"

export function PageBack({ label, href }: { label: string; href?: string }) {
  const router = useRouter()

  const handleBack = React.useCallback(() => {
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back()
      return
    }

    router.push(href ?? "/chat")
  }, [href, router])

  return (
    <Button
      variant="ghost"
      className="mb-2 gap-2 px-0 text-muted-foreground hover:bg-transparent hover:text-foreground"
      onClick={handleBack}
    >
      <ArrowLeft size={16} />
      {label}
    </Button>
  )
}
