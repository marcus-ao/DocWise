export const API_BASE_URL =
  process.env.NEXT_PUBLIC_DOCWISE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1"

export type Citation = {
  chunk_id: string
  chunk_uid: string
  document_id: string
  document_title: string
  section_path: string | null
  page_number: number | null
  score: number
  quote: string
}

export type ChatMessage = {
  id: string
  role: "user" | "assistant"
  content: string
  citations?: Citation[]
  created_at?: string
}

export type ConversationListItem = {
  id: string
  query_id: string
  run_id: string | null
  title: string
  workspace_id: string | null
  workspace_slug: string | null
  created_at: string
  updated_at: string
  message_count: number
  route: string | null
  status: string | null
}

export type ConversationListResponse = {
  items: ConversationListItem[]
  total: number
  limit: number
  offset: number
}

export type ConversationDetail = {
  id: string
  query_id: string
  run_id: string | null
  title: string
  workspace_id: string | null
  workspace_slug: string | null
  created_at: string
  updated_at: string
  messages: ChatMessage[]
}

export type ReasoningEvent = {
  node: string
  title: string
  decision?: string
  reason?: string
  confidence?: number
  status: "active" | "complete" | "error"
}

export type TraceListItem = {
  run_id: string
  query_id: string
  query: string
  route: string | null
  status: string
  latency_ms: number | null
  created_at: string
  started_at: string | null
  ended_at: string | null
}

export type TraceTimelineNode = {
  id: string
  title: string
  type: string
  start_time_ms: number
  end_time_ms: number
  duration_ms: number
  indent_level: number
  status: string
  metadata: Record<string, unknown>
  error_message: string | null
}

export type TraceTimelineResponse = {
  run_id: string
  total_latency_ms: number
  nodes: TraceTimelineNode[]
}

export type EvalTrendItem = {
  run_id: string
  run_name: string
  hit_rate_at_5: number | null
  mrr: number | null
  citation_accuracy: number | null
  bad_case_count: number
  total_cases: number
  created_at: string
}

export type EvalBadCaseItem = {
  eval_result_id: string
  run_id: string
  case_id: string
  query: string
  bad_case_types: string[]
  error_message: string | null
  created_at: string
}

export type LabChunkResult = {
  id: string
  chunk_uid: string | null
  score: number
  text: string
  doc_name: string
  document_id: string | null
  section_path: string | null
  page_number: number | null
}

export type LabCompareResponse = {
  results: Record<string, LabChunkResult[]>
  overlap_matrix: Record<string, number>
  timing_ms: Record<string, number>
  degraded: boolean
  errors: Record<string, string>
}

export type DocumentListItem = {
  id: string
  workspace_id: string
  workspace_slug: string
  title: string
  file_name: string
  doc_type: string
  status: string
  chunk_count: number
  file_size: number
  created_at: string
  indexed_at: string | null
}

export type DocumentListResponse = {
  items: DocumentListItem[]
  total: number
  limit: number
  offset: number
}

export type UploadResponse = {
  document_id: string
  job_id: string
  status: string
}

type ApiOptions = RequestInit & {
  query?: Record<string, string | number | boolean | null | undefined>
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

function apiUrl(path: string, query?: ApiOptions["query"]) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`
  const url = new URL(`${API_BASE_URL}${normalizedPath}`)
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value))
    }
  }
  return url.toString()
}

export async function apiJson<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { query, headers, ...init } = options
  const response = await fetch(apiUrl(path, query), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new ApiError(response.status, detail || response.statusText)
  }
  return response.json() as Promise<T>
}

export async function apiForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(apiUrl(path), { method: "POST", body })
  if (!response.ok) {
    const detail = await response.text()
    throw new ApiError(response.status, detail || response.statusText)
  }
  return response.json() as Promise<T>
}

export function formatShortDate(value?: string | null) {
  if (!value) return "-"
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

export function formatLatency(ms?: number | null) {
  if (ms === null || ms === undefined) return "-"
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}
