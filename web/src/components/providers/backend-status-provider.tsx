"use client"

import * as React from "react"

type BackendStatus = {
  ready: boolean
  checked: boolean
  message: string | null
}

const BackendStatusContext = React.createContext<BackendStatus>({
  ready: true,
  checked: false,
  message: null,
})

async function checkBackend() {
  try {
    const response = await fetch("/readyz", { cache: "no-store" })
    if (!response.ok) {
      return {
        ready: false,
        message: "后端服务未连接，请先启动 API / Redis / 数据库后再刷新页面。",
      }
    }

    const payload = (await response.json()) as { status?: string }
    if (payload.status !== "ready") {
      return {
        ready: false,
        message: "后端服务正在启动或依赖尚未就绪，请稍后再试。",
      }
    }

    return { ready: true, message: null }
  } catch {
    return {
      ready: false,
      message: "后端服务未连接，请确认 DOCWISE_API_PROXY_TARGET 和本地 API 进程是否正常。",
    }
  }
}

export function BackendStatusProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<BackendStatus>({
    ready: true,
    checked: false,
    message: null,
  })

  React.useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | null = null

    async function refresh() {
      const next = await checkBackend()
      if (!cancelled) {
        setState({
          ready: next.ready,
          checked: true,
          message: next.message,
        })
      }
    }

    void refresh()
    timer = setInterval(() => {
      void refresh()
    }, 10000)

    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
  }, [])

  return <BackendStatusContext.Provider value={state}>{children}</BackendStatusContext.Provider>
}

export function useBackendStatus() {
  return React.useContext(BackendStatusContext)
}
