const DEFAULT_API_PATH = "/api/v1"
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
  "host",
])

type ProxyResult = {
  response: Response
}

function normalizeTarget(rawTarget: string | undefined) {
  const trimmed = rawTarget?.trim()
  if (!trimmed) {
    return null
  }

  return trimmed.endsWith("/") ? trimmed.slice(0, -1) : trimmed
}

function proxyError(message: string, detail?: string) {
  return Response.json(
    {
      error: "backend_unavailable",
      message,
      detail,
    },
    { status: 503 }
  )
}

function buildHeaders(request: Request) {
  const headers = new Headers()
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value)
    }
  })
  return headers
}

export async function proxyToBackend(request: Request, destinationPath: string): Promise<ProxyResult> {
  const backendBase = normalizeTarget(process.env.DOCWISE_API_PROXY_TARGET)
  if (!backendBase) {
    return {
      response: proxyError("未配置后端代理地址", "请设置 DOCWISE_API_PROXY_TARGET 后再启动前端。"),
    }
  }

  const url = new URL(request.url)
  const target = new URL(destinationPath, `${backendBase}/`)
  target.search = url.search

  try {
    const response = await fetch(target, {
      method: request.method,
      headers: buildHeaders(request),
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
      duplex: request.method === "GET" || request.method === "HEAD" ? undefined : "half",
      cache: "no-store",
    } as RequestInit)

    const responseHeaders = new Headers(response.headers)
    HOP_BY_HOP_HEADERS.forEach((header) => responseHeaders.delete(header))
    responseHeaders.set("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate")
    responseHeaders.set("Pragma", "no-cache")
    responseHeaders.set("Expires", "0")

    return {
      response: new Response(response.body, {
        status: response.status,
        statusText: response.statusText,
        headers: responseHeaders,
      }),
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown proxy error"
    return {
      response: proxyError("后端服务未连接", detail),
    }
  }
}

export function backendApiPath(pathname: string) {
  if (pathname.startsWith(DEFAULT_API_PATH)) {
    return pathname
  }

  return `${DEFAULT_API_PATH}${pathname.startsWith("/") ? pathname : `/${pathname}`}`
}
