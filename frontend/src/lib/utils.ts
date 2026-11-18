import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function initials(name: string): string {
  return (
    name
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?"
  )
}

function parse(iso?: string | null): Date | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

export function formatDate(iso?: string | null): string {
  const d = parse(iso)
  if (!d) return "—"
  return d.toLocaleDateString([], { day: "2-digit", month: "short", year: "numeric" })
}

export function formatDateTime(iso?: string | null): string {
  const d = parse(iso)
  if (!d) return "—"
  return d.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
}

/** "HH:MM:SS" or "HH:MM" from the API -> "HH:MM". */
export function formatClock(value?: string | null): string {
  if (!value) return "—"
  return value.slice(0, 5)
}

/** Human-friendly relative time ("3 min ago", "in 2 h", "yesterday"). */
export function formatRelative(iso?: string | null, now: Date = new Date()): string {
  const d = parse(iso)
  if (!d) return "—"
  const diff = d.getTime() - now.getTime()
  const abs = Math.abs(diff)
  const past = diff < 0
  const unit = (n: number, u: string) => (past ? `${n} ${u} ago` : `in ${n} ${u}`)
  if (abs < 45_000) return past ? "just now" : "now"
  if (abs < 3_600_000) return unit(Math.round(abs / 60_000), "min")
  if (abs < 86_400_000) return unit(Math.round(abs / 3_600_000), "h")
  const days = Math.round(abs / 86_400_000)
  if (days === 1) return past ? "yesterday" : "tomorrow"
  if (days < 7) return unit(days, "days")
  return formatDate(iso)
}

export function formatDuration(minutes: number): string {
  if (!minutes || minutes <= 0) return "—"
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m} min`
}

export function greeting(date: Date = new Date()): string {
  const h = date.getHours()
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}

export function todayIso(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
