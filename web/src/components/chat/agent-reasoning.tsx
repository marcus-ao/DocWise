"use client"

import * as React from "react"
import { motion } from "framer-motion"
import { CheckCircle2, CircleAlert, Database, FileCheck, PenLine, Route, Search, Wrench } from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { ScrollArea } from "@/components/ui/scroll-area"

export interface ReasoningStep {
  id: string | number
  node: string
  title: string
  detail: string
  icon?: LucideIcon
  status: "active" | "complete" | "error"
}

interface AgentReasoningProps {
  steps: ReasoningStep[]
}

function iconForNode(node: string) {
  if (node.includes("router")) return Route
  if (node.includes("retriever")) return Search
  if (node.includes("rerank")) return Database
  if (node.includes("tool")) return Wrench
  if (node.includes("citation") || node.includes("evidence")) return FileCheck
  if (node.includes("answer")) return PenLine
  return CircleAlert
}

export function AgentReasoning({ steps }: AgentReasoningProps) {
  return (
    <div className="flex flex-col h-full">
      <div className="h-16 flex items-center px-4 border-b border-border/50 shrink-0">
        <h3 className="font-medium text-sm text-foreground/80 flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
          Agent 实时思考流
        </h3>
      </div>

      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-border/50 before:to-transparent">
          {steps.length === 0 && (
            <div className="text-sm text-muted-foreground px-2 py-8 text-center">
              发起一次提问后，这里会显示路由、检索、工具和生成节点。
            </div>
          )}
          {steps.map((step, index) => {
            const isActive = step.status === "active"
            const StepIcon = step.icon ?? iconForNode(step.node)
            return (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.05 }}
                className="relative flex items-start gap-3"
              >
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-background border border-border shrink-0 z-10 shadow-sm mt-1">
                  {isActive ? (
                    <div className="w-2 h-2 rounded-full bg-primary animate-ping" />
                  ) : step.status === "error" ? (
                    <CircleAlert size={14} className="text-red-500" />
                  ) : (
                    <CheckCircle2 size={14} className="text-muted-foreground/50" />
                  )}
                </div>

                <div className="flex-1 bg-background/50 backdrop-blur-sm border border-border/50 rounded-xl p-3 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex items-center gap-2 mb-1">
                    <StepIcon size={14} className="text-primary/70" />
                    <span className="text-xs font-medium text-foreground/80">{step.title}</span>
                  </div>
                  <p className="text-[13px] text-muted-foreground leading-relaxed">{step.detail}</p>
                </div>
              </motion.div>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}
