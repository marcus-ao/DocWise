import { proxyToBackend } from "@/lib/server-proxy"

async function handle(request: Request) {
  const { response } = await proxyToBackend(request, "/healthz")
  return response
}

export { handle as GET }
