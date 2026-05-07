"use client"

import * as React from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Database,
  FileCheck,
  PenLine,
  Route,
  Search,
  Wrench,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"

import { ScrollArea } from "@/components/ui/scroll-area"

export interface ReasoningStep {
  id: string | number
  node: string
  title: string
  detail: string
  meta?: string[]
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
  const [expandedSteps, setExpandedSteps] = React.useState<Record<string, boolean>>({})

  const toggleStep = React.useCallback((id: string | number) => {
    setExpandedSteps((prev) => ({ ...prev, [String(id)]: !prev[String(id)] }))
  }, [])

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <div className="h-16 shrink-0 border-b border-border px-4">
        <div className="flex h-full items-center justify-between gap-3">
          <h3 className="flex items-center gap-2 text-sm font-medium text-foreground">
            <div className="h-2 w-2 rounded-full bg-primary animate-pulse" />
            Agent 实时思考流
          </h3>
          {steps.length > 0 ? <div className="text-xs text-muted-foreground">{`${steps.length} 个节点`}</div> : null}
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1 p-4">
        <div className="relative space-y-4 before:absolute before:inset-y-0 before:left-[11px] before:w-px before:bg-border">
          {steps.length === 0 && (
            <div className="rounded-2xl border border-dashed border-border bg-card/70 px-4 py-5 text-sm text-muted-foreground shadow-sm">
              正在等待新的推理节点...
            </div>
          )}
          {steps.map((step, index) => {
            const isActive = step.status === "active"
            const StepIcon = step.icon ?? iconForNode(step.node)
            const hasMeta = Boolean(step.meta && step.meta.length > 0)
            const expanded = expandedSteps[String(step.id)] ?? index === steps.length - 1
            return (
              <motion.div
                layout
                key={step.id}
                initial={{ opacity: 0, x: 15, scale: 0.98 }}
                animate={{ opacity: 1, x: 0, scale: 1 }}
                transition={{ type: "spring", stiffness: 400, damping: 30, delay: index * 0.04 }}
                className="relative flex items-start gap-3"
              >
                <div className="z-10 mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-card shadow-sm">
                  {isActive ? (
                    <div className="relative flex h-3 w-3 items-center justify-center">
                      <motion.span
                        className="absolute inline-flex h-full w-full rounded-full bg-primary opacity-60"
                        animate={{ scale: [1, 1.8, 1], opacity: [0.6, 0, 0.6] }}
                        transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                      />
                      <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
                    </div>
                  ) : step.status === "error" ? (
                    <CircleAlert size={14} className="text-red-500" />
                  ) : (
                    <CheckCircle2 size={14} className="text-muted-foreground/70" />
                  )}
                </div>

                <div className="flex-1 rounded-xl border border-border bg-card p-3 shadow-sm transition-colors hover:bg-muted/20">
                  <div className="mb-1 flex items-center gap-2">
                    <StepIcon size={14} className="text-foreground/80" />
                    <span className="text-sm font-medium text-foreground">{step.title}</span>
                    <span className="ml-auto text-[11px] uppercase tracking-wide text-muted-foreground">
                      {step.status === "active" ? "进行中" : step.status === "error" ? "异常" : "完成"}
                    </span>
                  </div>
                  <p className="text-[13px] leading-6 text-foreground/90">{step.detail}</p>
                  {hasMeta ? (
                    <button
                      type="button"
                      onClick={() => toggleStep(step.id)}
                      className="mt-2 inline-flex cursor-pointer items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      {expanded ? "收起详情" : "展开详情"}
                    </button>
                  ) : null}
                  <AnimatePresence initial={false}>
                    {hasMeta && expanded && (
                      <motion.div
                        layout
                        initial={{ height: 0, opacity: 0, marginTop: 0 }}
                        animate={{ height: "auto", opacity: 1, marginTop: 12 }}
                        exit={{ height: 0, opacity: 0, marginTop: 0 }}
                        transition={{ duration: 0.2, ease: "easeInOut" }}
                        className="overflow-hidden"
                      >
                        <div className="rounded-lg border border-border bg-background px-3 py-2">
                          <ul className="space-y-1.5 text-xs leading-5 text-foreground/85">
                            {step.meta?.map((item, itemIndex) => (
                              <li key={`${step.id}-${itemIndex}`}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  )
}
