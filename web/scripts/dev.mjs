import { existsSync, readFileSync, rmSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { spawn } from "node:child_process"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const webDir = path.resolve(__dirname, "..")
const rootDir = path.resolve(webDir, "..")
const nextDir = path.join(webDir, ".next")
const tsBuildInfo = path.join(webDir, "tsconfig.tsbuildinfo")
const nextBin = path.join(webDir, "node_modules", "next", "dist", "bin", "next")

function safeRemove(target) {
  if (!existsSync(target)) return
  rmSync(target, {
    recursive: true,
    force: true,
    maxRetries: 5,
    retryDelay: 200,
  })
}

function parseEnvFile(filePath) {
  if (!existsSync(filePath)) return {}
  const env = {}
  for (const rawLine of readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith("#") || !line.includes("=")) continue
    const [key, ...rest] = line.split("=")
    env[key.trim()] = rest.join("=").trim()
  }
  return env
}

function resolveProxyTarget() {
  if (process.env.DOCWISE_API_PROXY_TARGET?.trim()) {
    return process.env.DOCWISE_API_PROXY_TARGET.trim()
  }

  const mergedEnv = {
    ...parseEnvFile(path.join(rootDir, ".env.local.example")),
    ...parseEnvFile(path.join(rootDir, ".env")),
  }

  if (mergedEnv.DOCWISE_API_PROXY_TARGET?.trim()) {
    return mergedEnv.DOCWISE_API_PROXY_TARGET.trim()
  }

  const host = mergedEnv.APP_HOST?.trim() || "127.0.0.1"
  const port = mergedEnv.APP_PORT?.trim() || "8000"
  const normalizedHost = host === "0.0.0.0" ? "127.0.0.1" : host
  return `http://${normalizedHost}:${port}`
}

safeRemove(nextDir)
safeRemove(tsBuildInfo)

const env = {
  ...process.env,
  DOCWISE_API_PROXY_TARGET: resolveProxyTarget(),
  NEXT_PUBLIC_DOCWISE_API_BASE_URL: process.env.NEXT_PUBLIC_DOCWISE_API_BASE_URL ?? "/api/v1",
}

const child = spawn(process.execPath, [nextBin, "dev", "--hostname", "127.0.0.1", "--port", "3000"], {
  cwd: webDir,
  stdio: "inherit",
  env,
})

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})
