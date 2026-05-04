import { proxyToBackend } from "@/lib/server-proxy"

async function handle(request: Request) {
  const { response } = await proxyToBackend(request, "/readyz")
  return response
}

export { handle as GET }
