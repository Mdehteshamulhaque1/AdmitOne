import type { AuthTokens } from "@/lib/types"

const ACCESS_KEY = "sg_access"
const REFRESH_KEY = "sg_refresh"

// Long-running dashboard queries must never hang the app: abort any request
// that exceeds this budget and surface a 408 instead of an infinite spinner.
const REQUEST_TIMEOUT_MS = 30_000

// API base URL: uses Vite proxy in dev (/api), full URL in production via
// VITE_API_BASE_URL (VITE_API_URL kept as a backward-compatible fallback).
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_URL ?? ""
const API_BASE_URL = API_BASE.replace(/\/+$/, "")

// Media paths arrive from the backend as relative strings -- "/media/
// visitor_photos/x.jpg" and the same shape for avatars and org logos. In
// development the Vite proxy makes them work as-is. In production the SPA is
// served from a different origin than the API (Vercel vs Render), so a
// relative src= would resolve against the SPA's own host and 404 long before
// reaching Django's /media/ route. Before an image is ever rendered, make the
// media path absolute against the configured API base.
function absolutizeMediaUrls(value: unknown): unknown {
  if (typeof value === "string") {
    return value.startsWith("/media/") ? `${API_BASE_URL}${value}` : value
  }
  if (value === null || typeof value !== "object") return value
  if (Array.isArray(value)) return value.map(absolutizeMediaUrls)
  return Object.fromEntries(
    Object.entries(value).map(([key, val]) => [key, absolutizeMediaUrls(val)]),
  )
}

export function buildUrl(path: string): string {
  if (!API_BASE) return path // dev: use Vite proxy /api
  const p = path.startsWith("/") ? path : `/${path}`
  return `${API_BASE_URL}${p}`
}

async function fetchWithTimeout(url: string, options: RequestInit = {}): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  const onAbort = () => controller.abort()
  const callerSignal = options.signal
  if (callerSignal) {
    if (callerSignal.aborted) controller.abort()
    else callerSignal.addEventListener("abort", onAbort, { once: true })
  }
  try {
    return await fetch(url, { ...options, signal: controller.signal })
  } finally {
    clearTimeout(timer)
    if (callerSignal) callerSignal.removeEventListener("abort", onAbort)
  }
}

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function setTokens(tokens: AuthTokens): void {
  localStorage.setItem(ACCESS_KEY, tokens.access)
  localStorage.setItem(REFRESH_KEY, tokens.refresh)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export class ApiError extends Error {
  status: number
  data: unknown

  constructor(status: number, data: unknown) {
    super(typeof data === "string" ? data : "Request failed")
    this.name = "ApiError"
    this.status = status
    this.data = data
  }
}

async function refreshAccessToken(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const res = await fetchWithTimeout(buildUrl("/api/auth/token/refresh/"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    })
    if (!res.ok) {
      clearTokens()
      return false
    }
    const tokens = (await res.json()) as AuthTokens
    localStorage.setItem(ACCESS_KEY, tokens.access)
    return true
  } catch {
    clearTokens()
    return false
  }
}

export async function api<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const token = getAccessToken()
  const headers = new Headers(options.headers)
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  if (token) headers.set("Authorization", `Bearer ${token}`)

  let res: Response
  try {
    res = await fetchWithTimeout(buildUrl(path), { ...options, headers })
  } catch {
    throw new ApiError(408, { detail: "Request timed out" })
  }

  if (res.status === 401 && retry && getRefreshToken()) {
    const ok = await refreshAccessToken()
    if (ok) return api<T>(path, options, false)
  }

  if (!res.ok) {
    const raw = await res.text()
    let body: unknown
    try {
      body = JSON.parse(raw)
    } catch {
      body = raw
    }
    throw new ApiError(res.status, body)
  }

  if (res.status === 204) return undefined as T
  const data = (await res.json()) as unknown
  return (API_BASE ? absolutizeMediaUrls(data) : data) as T
}

export async function downloadFile(path: string, filename: string): Promise<void> {
  const token = getAccessToken()
  const res = await fetchWithTimeout(buildUrl(path), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (res.status === 401 && getRefreshToken()) {
    const ok = await refreshAccessToken()
    if (ok) return downloadFile(path, filename)
  }

  if (!res.ok) {
    throw new ApiError(res.status, { detail: "Export failed" })
  }

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
