"use client"

import * as React from "react"
import { motion, AnimatePresence } from "framer-motion"
import { CheckCircle2, FileText, RefreshCw, Trash2, UploadCloud, Layers, Loader2 } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { PageBack } from "@/components/layout/page-back"
import { useBackendStatus } from "@/components/providers/backend-status-provider"
import { apiForm, apiJson, DocumentListItem, DocumentListResponse, formatShortDate, UploadResponse } from "@/lib/api"

const WORKSPACES = ["All", "public_tech", "project_airflow", "project_fastapi", "project_backstage"]

export default function DocumentsPage() {
  const { ready: backendReady, checked: backendChecked, message: backendMessage } = useBackendStatus()
  const [documents, setDocuments] = React.useState<DocumentListItem[]>([])
  const [isLoading, setIsLoading] = React.useState(true)
  const [workspace, setWorkspace] = React.useState("All")
  const [error, setError] = React.useState<string | null>(null)
  const [isUploading, setIsUploading] = React.useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)

  const abortControllerRef = React.useRef<AbortController | null>(null)

  const loadDocuments = React.useCallback(() => {
    if (!backendReady) {
      setDocuments([])
      setIsLoading(false)
      setError(null)
      return
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    const controller = new AbortController()
    abortControllerRef.current = controller

    setIsLoading(true)
    const query = workspace === "All" ? { limit: 100 } : { workspace_slug: workspace, limit: 100 }
    
    apiJson<DocumentListResponse>("/documents", { query, signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return
        setDocuments(data.items)
        setError(null)
      })
      .catch((err: Error) => {
        if (controller.signal.aborted) return
        setError(err.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setIsLoading(false)
        }
      })
  }, [backendReady, workspace])

  React.useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  const uploadDocument = React.useCallback(
    async (file: File) => {
      setIsUploading(true)
      const form = new FormData()
      form.set("file", file)
      form.set("workspace_slug", workspace === "All" ? "public_tech" : workspace)
      form.set("enqueue", "true")
      try {
        const response = await apiForm<UploadResponse>("/documents/upload", form)
        setError(`已提交索引任务：${response.job_id}`)
        loadDocuments()
      } catch (err) {
        setError(err instanceof Error ? err.message : "上传失败")
      } finally {
        setIsUploading(false)
        if (inputRef.current) inputRef.current.value = ""
      }
    },
    [loadDocuments, workspace]
  )

  const reindexDocument = React.useCallback(
    async (documentId: string) => {
      try {
        await apiJson(`/documents/${documentId}/retry`, { method: "POST", body: "{}" })
        loadDocuments()
      } catch (err) {
        setError(err instanceof Error ? err.message : "重建索引失败")
      }
    },
    [loadDocuments]
  )

  const deleteDocument = React.useCallback(
    async (documentId: string) => {
      try {
        await apiJson(`/documents/${documentId}`, { method: "DELETE" })
        loadDocuments()
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除失败")
      }
    },
    [loadDocuments]
  )

  return (
    <div className="w-full h-full p-6 flex flex-col gap-6 overflow-hidden">
      <div className="shrink-0 flex items-center justify-between">
        <div>
          <PageBack label="返回控制台" href="/" />
          <h1 className="text-3xl font-bold tracking-tight text-foreground/90">知识库管理</h1>
          <p className="text-sm text-muted-foreground mt-1">上传、索引和管理 Workspace 文档资产</p>
        </div>
        <div>
          <input
            ref={inputRef}
            type="file"
            className="hidden"
            accept=".md,.txt,.pdf,.docx"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void uploadDocument(file)
            }}
          />
          <Button 
            className="gap-2 rounded-xl h-11 px-5 shadow-sm transition-all hover:shadow-md active:scale-95" 
            onClick={() => inputRef.current?.click()} 
            disabled={isUploading}
          >
            {isUploading ? <Loader2 size={18} className="animate-spin" /> : <UploadCloud size={18} />}
            {isUploading ? "正在上传..." : "上传文档"}
          </Button>
        </div>
      </div>

      {error && (
        <motion.div 
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="shrink-0 rounded-xl border border-border/50 bg-muted/30 px-4 py-3 text-sm text-muted-foreground backdrop-blur-sm"
        >
          {error}
        </motion.div>
      )}

      {!backendReady && backendChecked && (
        <div className="shrink-0 rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-500 backdrop-blur-sm">
          {backendMessage}
        </div>
      )}

      <div className="flex gap-8 flex-1 min-h-0 lg:flex-row flex-col">
        {/* Workspace Sidebar */}
        <div className="w-full lg:w-64 shrink-0 flex flex-col">
          <div className="font-bold text-xs uppercase tracking-[0.15em] mb-4 text-muted-foreground/60 px-2">Workspaces</div>
          <div className="space-y-1.5 relative">
            {WORKSPACES.map((ws) => {
              const isActive = workspace === ws;
              return (
                <button
                  key={ws}
                  onClick={() => setWorkspace(ws)}
                  className={cn(
                    "group relative w-full flex items-center gap-3 px-4 py-3 rounded-xl cursor-pointer text-sm transition-all duration-300 outline-none",
                    isActive ? "text-foreground font-semibold" : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {isActive && (
                    <motion.div
                      layoutId="doc-workspace-active"
                      className="absolute inset-0 rounded-xl bg-card border border-border/50 shadow-sm backdrop-blur-md dark:shadow-none"
                      transition={{ type: "spring", stiffness: 350, damping: 30 }}
                    />
                  )}
                  {!isActive && (
                    <div className="absolute inset-0 rounded-xl bg-muted/0 transition-colors duration-200 group-hover:bg-card/40" />
                  )}
                  <Layers size={16} className={cn("relative z-10 transition-colors", isActive ? "text-primary" : "opacity-70 group-hover:opacity-100")} />
                  <span className="relative z-10 truncate">{ws}</span>
                </button>
              )
            })}
          </div>
        </div>

        {/* Document List */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-auto custom-scrollbar pr-2 pb-8">
            <motion.div
              variants={{
                hidden: { opacity: 0 },
                show: { opacity: 1, transition: { staggerChildren: 0.04 } }
              }}
              initial="hidden"
              animate="show"
              className="flex flex-col gap-3"
            >
              <AnimatePresence mode="popLayout">
                {isLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <motion.div key={`skeleton-${i}`} className="flex items-center justify-between p-5 rounded-2xl border border-border/30 bg-card/20">
                      <div className="flex items-center gap-4">
                        <Skeleton className="h-11 w-11 rounded-full" />
                        <div className="space-y-2">
                          <Skeleton className="h-5 w-48 rounded-md" />
                          <Skeleton className="h-3 w-24 rounded-md" />
                        </div>
                      </div>
                      <Skeleton className="h-8 w-24 rounded-full" />
                    </motion.div>
                  ))
                ) : documents.length === 0 ? (
                  <motion.div 
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="flex flex-col items-center justify-center h-64 text-sm text-muted-foreground bg-card/20 rounded-2xl border border-dashed border-border/60 backdrop-blur-sm"
                  >
                    <FileText size={40} className="mb-4 opacity-20" />
                    当前筛选下暂无文档。
                  </motion.div>
                ) : (
                  documents.map((doc) => (
                    <motion.div
                      key={doc.id}
                      layout
                      variants={{
                        hidden: { opacity: 0, y: 12, scale: 0.99 },
                        show: { opacity: 1, y: 0, scale: 1, transition: { type: "spring", stiffness: 400, damping: 30 } },
                        exit: { opacity: 0, scale: 0.96, transition: { duration: 0.2 } }
                      }}
                      className="group relative flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-2xl border border-border/50 bg-card/40 px-5 py-4 backdrop-blur-sm transition-all duration-300 hover:-translate-y-0.5 hover:bg-card/80 hover:shadow-[0_8px_30px_rgb(0,0,0,0.04)] dark:hover:bg-muted/30 dark:hover:shadow-none"
                    >
                      <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-8 rounded-r-full bg-primary/0 transition-all duration-300 group-hover:bg-primary/40 group-hover:h-10" />
                      
                      <div className="flex items-center gap-4 min-w-0">
                        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-primary/10 bg-primary/5 text-primary/70 transition-colors duration-300 group-hover:bg-primary/10 group-hover:text-primary">
                          <FileText size={20} />
                        </div>
                        <div className="min-w-0">
                          <div className="truncate text-[15px] font-semibold text-foreground/90 transition-colors group-hover:text-primary mb-1">
                            {doc.file_name || doc.title}
                          </div>
                          <div className="flex flex-wrap items-center gap-3 text-[11px] font-medium text-muted-foreground/70">
                            <span className="flex items-center gap-1.5 bg-muted/50 px-2.5 py-0.5 rounded-full border border-border/40 text-foreground/80">
                              <span className="w-1.5 h-1.5 rounded-full bg-blue-500/60" />
                              {doc.workspace_slug}
                            </span>
                            <span className="font-mono opacity-80">{doc.chunk_count} Chunks</span>
                            <span>{formatShortDate(doc.indexed_at ?? doc.created_at)}</span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-4 sm:ml-auto">
                        <StatusBadge status={doc.status} />
                        <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-all duration-200">
                          <Button 
                            variant="ghost" 
                            size="icon" 
                            className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted" 
                            onClick={() => void reindexDocument(doc.id)} 
                            title="重建索引"
                          >
                            <RefreshCw size={15} />
                          </Button>
                          <Button 
                            variant="ghost" 
                            size="icon" 
                            className="h-9 w-9 rounded-xl text-muted-foreground hover:text-red-500 hover:bg-red-500/10" 
                            onClick={() => void deleteDocument(doc.id)} 
                            title="删除文档"
                          >
                            <Trash2 size={15} />
                          </Button>
                        </div>
                      </div>
                    </motion.div>
                  ))
                )}
              </AnimatePresence>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  if (status === "ready") {
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full bg-green-500/10 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-green-600 dark:text-green-400 border border-green-500/20">
        <CheckCircle2 size={12} /> Ready
      </div>
    )
  }
  if (status === "processing" || status === "pending") {
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full bg-blue-500/10 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400 border border-blue-500/20 animate-pulse">
        <RefreshCw size={12} className="animate-spin" /> Processing
      </div>
    )
  }
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 px-3 py-1 text-[10px] font-bold uppercase tracking-wider text-red-600 dark:text-red-400 border border-red-500/20">
      Error
    </div>
  )
}
