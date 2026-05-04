import { backendApiPath, proxyToBackend } from "@/lib/server-proxy"

type Context = {
  params: { path?: string[] }
}

async function handle(request: Request, { params }: Context) {
  const path = params.path?.join("/") ?? ""
  const destinationPath = backendApiPath(`/${path}`)
  const { response } = await proxyToBackend(request, destinationPath)
  return response
}

export { handle as GET, handle as POST, handle as PUT, handle as PATCH, handle as DELETE, handle as OPTIONS }
