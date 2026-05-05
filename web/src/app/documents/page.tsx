"use client"

import * as React from "react"
import { CheckCircle2, FileText, RefreshCw, Trash2, UploadCloud } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PageBack } from "@/components/layout/page-back"
import { useBackendStatus } from "@/components/providers/backend-status-provider"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
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

  const loadDocuments = React.useCallback(() => {
    if (!backendReady) {
      setDocuments([])
      setIsLoading(false)
      setError(null)
      return
    }
    setIsLoading(true)
    const query = workspace === "All" ? { limit: 100 } : { workspace_slug: workspace, limit: 100 }
    apiJson<DocumentListResponse>("/documents", { query })
      .then((data) => {
        setDocuments(data.items)
        setError(null)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setIsLoading(false))
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
          <h1 className="text-2xl font-semibold tracking-tight">知识库管理</h1>
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
          <Button className="gap-2" onClick={() => inputRef.current?.click()} disabled={isUploading}>
            <UploadCloud size={16} />
            {isUploading ? "上传中" : "上传文档"}
          </Button>
        </div>
      </div>

      {error && (
        <div className="shrink-0 rounded-lg border border-border/50 bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
          {error}
        </div>
      )}

      {!backendReady && backendChecked && (
        <div className="shrink-0 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-500">
          {backendMessage}
        </div>
      )}

      <div className="flex gap-6 flex-1 min-h-0 lg:flex-row flex-col">
        <Card className="w-full lg:w-64 shrink-0 flex flex-col bg-background/50 backdrop-blur-sm border-border/50 p-4">
          <h3 className="font-semibold text-sm mb-4 text-muted-foreground">Workspaces</h3>
          <div className="space-y-1">
            {WORKSPACES.map((ws) => (
              <button
                key={ws}
                onClick={() => setWorkspace(ws)}
                className={`w-full text-left px-3 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
                  workspace === ws ? "bg-muted text-foreground font-medium" : "hover:bg-muted text-foreground/80"
                }`}
              >
                {ws}
              </button>
            ))}
          </div>
        </Card>

        <Card className="flex-1 flex flex-col bg-background/50 backdrop-blur-sm border-border/50 overflow-hidden relative">
          <div className="flex-1 overflow-auto">
            <Table>
              <TableHeader className="bg-muted/30 sticky top-0 backdrop-blur-sm">
                <TableRow className="border-border/50">
                  <TableHead className="w-[300px]">文档名称</TableHead>
                  <TableHead>Workspace</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">Chunks</TableHead>
                  <TableHead className="text-right">更新时间</TableHead>
                  <TableHead className="w-[100px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={`skeleton-${i}`}>
                      <TableCell><Skeleton className="h-5 w-48" /></TableCell>
                      <TableCell><Skeleton className="h-5 w-24" /></TableCell>
                      <TableCell><Skeleton className="h-5 w-20" /></TableCell>
                      <TableCell className="text-right"><Skeleton className="h-5 w-8 ml-auto" /></TableCell>
                      <TableCell className="text-right"><Skeleton className="h-5 w-32 ml-auto" /></TableCell>
                      <TableCell></TableCell>
                    </TableRow>
                  ))
                ) : documents.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={6} className="h-32 text-center text-muted-foreground">
                      当前筛选下暂无文档。
                    </TableCell>
                  </TableRow>
                ) : null}
                {!isLoading && documents.map((doc) => (
                  <TableRow key={doc.id} className="border-border/50 hover:bg-muted/30 transition-colors group">
                    <TableCell className="font-medium">
                      <div className="flex items-center gap-2">
                        <FileText size={16} className="text-muted-foreground" />
                        <span className="truncate">{doc.file_name || doc.title}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="font-normal bg-background/50">
                        {doc.workspace_slug}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={doc.status} />
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{doc.chunk_count}</TableCell>
                    <TableCell className="text-right text-muted-foreground text-sm">
                      {formatShortDate(doc.indexed_at ?? doc.created_at)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-2 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
                        <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" onClick={() => void reindexDocument(doc.id)}>
                          <RefreshCw size={14} />
                        </Button>
                        <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-red-500" onClick={() => void deleteDocument(doc.id)}>
                          <Trash2 size={14} />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </Card>
      </div>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  if (status === "ready") {
    return (
      <Badge variant="secondary" className="bg-green-500/10 text-green-500 hover:bg-green-500/20">
        <CheckCircle2 size={12} className="mr-1" /> Ready
      </Badge>
    )
  }
  if (status === "processing" || status === "pending") {
    return (
      <Badge variant="secondary" className="bg-muted text-foreground hover:bg-muted/90 animate-pulse">
        <RefreshCw size={12} className="mr-1 animate-spin" /> Processing
      </Badge>
    )
  }
  return (
    <Badge variant="secondary" className="bg-red-500/10 text-red-500 hover:bg-red-500/20">
      Error
    </Badge>
  )
}
