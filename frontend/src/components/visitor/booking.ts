/**
 * Shared state and data hooks for the visitor booking flow.
 *
 * The flow mirrors an appointment app: pick what the visit is for, then who
 * and when, then confirm. Building, floor and room are NOT asked: reception
 * assigns the room when they approve, and it appears on the visitor's pass.
 */
import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { DEFAULT_PURPOSES, OTHER_PURPOSE } from "@/lib/student-options"
import type { AvailabilitySlot, BookingHost, CatalogueCategory, HostAvailabilityResponse } from "@/lib/types"

export type Step = "account" | "company" | "purpose" | "time" | "identity" | "confirm" | "done"

export const STEP_LABELS: Record<Exclude<Step, "done">, string> = {
  account: "Your account",
  company: "Company",
  purpose: "Purpose",
  time: "Person & time",
  identity: "Photo & ID",
  confirm: "Confirm",
}

export interface Draft {
  /** Catalogue category key (who is visiting); drives the purpose list. */
  category: string
  purpose: string
  purpose_other: string
  department: string
  host: string
  visit_date: string
  slot: AvailabilitySlot | null
  notes: string[]
  /** Gate-pass identity: identity proof type, its number, and a recent photo. */
  document_type: string
  document_number: string
  photo: Blob | null
  photo_url: string
}

export const EMPTY_DRAFT: Draft = {
  category: "",
  purpose: "",
  purpose_other: "",
  department: "",
  host: "",
  visit_date: "",
  slot: null,
  notes: [],
  document_type: "",
  document_number: "",
  photo: null,
  photo_url: "",
}

/** Identity proofs accepted at the gate, with the shape of each number (mirrors the API). */
export const ID_PROOFS: { value: string; label: string; placeholder: string; pattern: RegExp; hint: string }[] = [
  { value: "AADHAAR", label: "Aadhaar", placeholder: "1234 5678 9012", pattern: /^\d{12}$/, hint: "12 digits" },
  { value: "PASSPORT", label: "Passport", placeholder: "A1234567", pattern: /^[A-Z]\d{7}$/, hint: "1 letter and 7 digits" },
  { value: "PAN", label: "PAN card", placeholder: "ABCDE1234F", pattern: /^[A-Z]{5}\d{4}[A-Z]$/, hint: "5 letters, 4 digits, 1 letter" },
  { value: "DRIVING_LICENSE", label: "Driving licence", placeholder: "DL0420110012345", pattern: /^[A-Z0-9-]{8,20}$/, hint: "8 to 20 letters or digits, as printed" },
  { value: "COMPANY_ID", label: "Company / college ID", placeholder: "Number on your card", pattern: /^.{3,60}$/, hint: "as printed on the card" },
]

/** The ID number as the API stores it: no spaces, upper case (company IDs kept as typed). */
export function normaliseId(type: string, value: string) {
  return type === "COMPANY_ID" ? value.trim() : value.replace(/\s+/g, "").toUpperCase()
}

export function idProblem(type: string, value: string): string | null {
  const proof = ID_PROOFS.find((p) => p.value === type)
  if (!proof) return "Choose your identity proof."
  const v = normaliseId(type, value)
  if (!v) return "Enter the ID proof number."
  return proof.pattern.test(v) ? null : `${proof.label} number should be ${proof.hint}.`
}

/** Show only the last 4 characters of an ID number. */
export function maskId(value: string) {
  return value.length <= 4 ? value : `${"•".repeat(Math.min(value.length - 4, 8))}${value.slice(-4)}`
}

/** Fixed purposes for a category: the shared default list, plus any extra the workspace adds. */
export function purposeLabels(categoryKey: string, catalogue: CatalogueCategory[]): string[] {
  const fixed = DEFAULT_PURPOSES[categoryKey] ?? [OTHER_PURPOSE]
  const extra = (catalogue.find((c) => c.key === categoryKey)?.purposes ?? [])
    .map((p) => p.label)
    .filter((label) => !fixed.some((f) => f.toLowerCase() === label.toLowerCase()))
  // Keep "Other" last.
  return [...fixed.filter((l) => l !== OTHER_PURPOSE), ...extra.filter((l) => l !== OTHER_PURPOSE), OTHER_PURPOSE]
}

/**
 * The backend validates (category, purpose) against the workspace catalogue.
 * A preset purpose the workspace doesn't list is sent as "Other" with the
 * label as the reason, which every catalogue accepts.
 */
export function purposeForSubmit(draft: Draft, catalogue: CatalogueCategory[]): { purpose: string; purpose_other: string } {
  if (draft.purpose === OTHER_PURPOSE) return { purpose: OTHER_PURPOSE, purpose_other: draft.purpose_other.trim() }
  const listed = catalogue
    .find((c) => c.key === draft.category)
    ?.purposes.some((p) => p.label.toLowerCase() === draft.purpose.toLowerCase())
  return listed || catalogue.length === 0
    ? { purpose: draft.purpose, purpose_other: "" }
    : { purpose: OTHER_PURPOSE, purpose_other: draft.purpose.slice(0, 120) }
}

export function purposeText(draft: Draft) {
  return draft.purpose === OTHER_PURPOSE ? draft.purpose_other : draft.purpose
}

export function usePublicHosts(slug: string, department: string) {
  return useQuery({
    queryKey: ["visitor", "hosts", slug, department],
    queryFn: () =>
      api<BookingHost[]>(`/api/public/booking/${encodeURIComponent(slug)}/hosts/${department ? `?department=${department}` : ""}`),
    enabled: Boolean(slug),
  })
}

export function usePublicAvailability(slug: string, host: string, date: string) {
  return useQuery({
    queryKey: ["visitor", "slots", slug, host, date],
    queryFn: () =>
      api<HostAvailabilityResponse>(`/api/public/booking/${encodeURIComponent(slug)}/availability/?host=${host}&date=${date}`),
    enabled: Boolean(slug && host && date),
    retry: false,
  })
}

export interface CalendarDay {
  value: string
  weekday: string
  day: number
  month: string
}

/** The next `days` calendar days starting today (local time). */
export function upcomingDays(days = 90): CalendarDay[] {
  const out: CalendarDay[] = []
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  for (let i = 0; i < days; i++) {
    out.push({
      value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
      weekday: i === 0 ? "Today" : d.toLocaleDateString(undefined, { weekday: "short" }),
      day: d.getDate(),
      month: d.toLocaleDateString(undefined, { month: "short" }),
    })
    d.setDate(d.getDate() + 1)
  }
  return out
}

/** Free-slot count per day for the next 90 days, in a single request. */
export function usePublicAvailabilityCalendar(slug: string, host: string) {
  return useQuery({
    queryKey: ["visitor", "calendar", slug, host],
    queryFn: () =>
      api<{ start: string; days: Record<string, number> }>(
        `/api/public/booking/${encodeURIComponent(slug)}/calendar/?host=${host}&start=${upcomingDays(1)[0].value}&days=90`,
      ),
    enabled: Boolean(slug && host),
    retry: false,
    staleTime: 60_000,
  })
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("")
}
