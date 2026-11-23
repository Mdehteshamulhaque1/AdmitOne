/**
 * Client for the self-service visitor account API (`/api/visitor/`).
 *
 * Visitor sessions are a separate credential from staff JWTs: they live under
 * their own storage key and are sent only to `/api/visitor/` and the public
 * booking endpoints, so a visitor can never accidentally drive the console.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ApiError, SERVER_UNREACHABLE, buildUrl } from "@/lib/api"
import type { BookingBuilding, BookingContext, VisitStatus } from "@/lib/types"

const TOKEN_KEY = "sg_visitor_token"
const REQUEST_TIMEOUT_MS = 30_000

export function getVisitorToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}
export function setVisitorToken(token: string) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    /* ignore */
  }
}
export function clearVisitorToken() {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

export async function visitorApi<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  // FormData (photo upload) sets its own multipart boundary.
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json")
  const token = getVisitorToken()
  if (token && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  let res: Response
  try {
    res = await fetch(buildUrl(path), { ...options, headers, signal: controller.signal })
  } catch (e) {
    if ((e as Error)?.name === "AbortError") throw new ApiError(408, { detail: "The request timed out. Check your connection and try again." })
    throw new ApiError(0, { detail: SERVER_UNREACHABLE })
  } finally {
    clearTimeout(timer)
  }
  if (res.status === 401) clearVisitorToken()
  if (!res.ok) {
    const raw = await res.text()
    let body: unknown
    try {
      body = JSON.parse(raw)
    } catch {
      // A 5xx with no JSON body means the API itself didn't answer (stopped,
      // restarting, or the dev proxy can't reach it): say so instead of nothing.
      body = res.status >= 500 ? { detail: SERVER_UNREACHABLE } : raw || { detail: `Request failed (${res.status}).` }
    }
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/* ---------------------------------------------------------------- types */

export interface VisitorAccount {
  id: number
  email: string
  full_name: string
  phone: string
  company: string
  designation: string
  /** Training-centre profile; all optional, "Other" values are free text. */
  category: string
  state: string
  university: string
  qualification: string
  passing_year: number | null
  created_at: string
  last_login: string | null
}

export interface OrganizationResult {
  id: number
  name: string
  slug: string
  tagline: string
  city: string
  country: string
  /** Directory detail: the organisation's buildings and their floors. */
  buildings: BookingBuilding[]
}

export interface VisitorVisit {
  id: number
  reference: string
  status: VisitStatus
  source: string
  visit_type: string
  visit_type_label: string
  visitor_category: string
  purpose: string
  visit_date: string
  expected_arrival: string
  expected_exit: string
  organization_name: string
  organization_slug: string
  organization_city: string
  department_name: string
  building_name: string
  floor_name: string
  /** Assigned by staff on approval; empty until then. */
  room_label: string
  room_number: string
  host_name: string
  host_designation: string
  phone_masked: string
  rejection_reason: string
  cancelled_at: string | null
  cancelled_reason: string
  registered_at: string
  approved_at: string | null
  rejected_at: string | null
  checked_in_at: string | null
  checked_out_at: string | null
  qr: { token: string; signature: string; is_valid: boolean } | null
  can_reschedule: boolean
  can_cancel: boolean
  can_arrive: boolean
  arriving_at: string | null
}

export interface VisitorBookingPayload {
  organization: string
  /** Catalogue path: who is visiting (drives the purpose list). */
  category?: string
  /** Legacy static path; not needed when `category` is sent. */
  visit_type?: string
  department?: number | null
  building?: number | null
  floor?: number | null
  host?: number | null
  visit_date: string
  expected_arrival: string
  expected_exit: string
  purpose: string
  purpose_other?: string
  notes?: string
  /** Gate-pass identity: one identity proof and its number. */
  document_type?: string
  document_number?: string
}

interface SessionResponse {
  token: string
  account: VisitorAccount
}

/* ---------------------------------------------------------------- hooks */

export const visitorKeys = {
  me: ["visitor", "me"] as const,
  orgs: (q: string) => ["visitor", "orgs", q] as const,
  context: (slug: string) => ["visitor", "context", slug] as const,
  bookings: ["visitor", "bookings"] as const,
  availability: (id: number, date: string) => ["visitor", "availability", id, date] as const,
}

export function useVisitorAccount() {
  return useQuery({
    queryKey: visitorKeys.me,
    queryFn: () => visitorApi<VisitorAccount>("/api/visitor/me/"),
    enabled: Boolean(getVisitorToken()),
    retry: false,
    staleTime: 5 * 60_000,
  })
}

function useSessionMutation(path: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      visitorApi<SessionResponse>(path, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: (data) => {
      setVisitorToken(data.token)
      qc.setQueryData(visitorKeys.me, data.account)
      void qc.invalidateQueries({ queryKey: visitorKeys.bookings })
    },
  })
}

/**
 * Create a visitor account WITHOUT signing in: the person signs in
 * explicitly next. The session the API issues on registration is revoked at
 * once and never stored, so the page can't end up looking signed in while
 * holding no token (which used to leave the booking wizard half signed-in).
 */
export function useVisitorRegister() {
  return useMutation({
    mutationFn: async (payload: Record<string, unknown>) => {
      const data = await visitorApi<SessionResponse>("/api/visitor/auth/register/", { method: "POST", body: JSON.stringify(payload) })
      try {
        await visitorApi("/api/visitor/auth/logout/", { method: "POST", body: "{}", headers: { Authorization: `Bearer ${data.token}` } })
      } catch {
        /* the unused session simply expires */
      }
      return data.account
    },
  })
}
export function useVisitorLogin() {
  return useSessionMutation("/api/visitor/auth/login/")
}

export function useVisitorLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async () => {
      try {
        await visitorApi("/api/visitor/auth/logout/", { method: "POST", body: "{}" })
      } finally {
        clearVisitorToken()
      }
    },
    onSettled: () => {
      qc.removeQueries({ queryKey: ["visitor"] })
    },
  })
}

export function useOrganizationSearch(q: string) {
  return useQuery({
    queryKey: visitorKeys.orgs(q),
    queryFn: () => visitorApi<OrganizationResult[]>(`/api/visitor/organizations/?q=${encodeURIComponent(q.trim())}`),
    enabled: Boolean(getVisitorToken()),
    staleTime: 60_000,
  })
}

export function useOrganizationContext(slug: string) {
  return useQuery({
    queryKey: visitorKeys.context(slug),
    queryFn: () => visitorApi<BookingContext>(`/api/visitor/organizations/${encodeURIComponent(slug)}/`),
    enabled: Boolean(slug),
    retry: false,
  })
}

export function useVisitorBookings(enabled = true) {
  return useQuery({
    queryKey: visitorKeys.bookings,
    queryFn: async () => (await visitorApi<{ visits: VisitorVisit[] }>("/api/visitor/bookings/")).visits,
    enabled: enabled && Boolean(getVisitorToken()),
    refetchInterval: 60_000,
  })
}

export function useCreateBooking() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ photo, ...payload }: VisitorBookingPayload & { photo?: Blob | null }) => {
      // A photo travels as multipart; without one the request stays JSON.
      let body: BodyInit = JSON.stringify(payload)
      if (photo) {
        const form = new FormData()
        for (const [key, value] of Object.entries(payload)) {
          if (value !== null && value !== undefined && value !== "") form.append(key, String(value))
        }
        form.append("photo", photo, "photo.jpg")
        body = form
      }
      return visitorApi<{ message: string; visit: VisitorVisit }>("/api/visitor/bookings/", { method: "POST", body })
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: visitorKeys.bookings }),
  })
}

export function useBookingAvailability(id: number | null, date: string) {
  return useQuery({
    queryKey: visitorKeys.availability(id ?? 0, date),
    queryFn: () =>
      visitorApi<{ date: string; slot_duration_minutes: number; slots: { start: string; end: string }[] }>(
        `/api/visitor/bookings/${id}/availability/?date=${date}`,
      ),
    enabled: id !== null && Boolean(date),
  })
}

function useBookingAction(action: "cancel" | "reschedule" | "arriving") {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Record<string, unknown>) =>
      visitorApi<{ detail: string; visit: VisitorVisit }>(`/api/visitor/bookings/${id}/${action}/`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: visitorKeys.bookings }),
  })
}

export function useCancelBooking() {
  return useBookingAction("cancel")
}
export function useRescheduleBooking() {
  return useBookingAction("reschedule")
}
export function useAnnounceArrival() {
  return useBookingAction("arriving")
}

export interface MyStudentPass {
  id: number
  organization_name: string
  admission_number: string
  course: string
  batch: string
  valid_from: string
  valid_until: string
  status: "ACTIVE" | "UPCOMING" | "EXPIRED" | "REVOKED"
  student_name: string
  photo: string | null
  payload: string | null
}

/** The signed-in student's own 6-month passes (empty for ordinary visitors). */
export function useMyStudentPasses() {
  return useQuery({
    queryKey: ["visitor", "student-pass"],
    queryFn: () => visitorApi<{ passes: MyStudentPass[] }>("/api/visitor/student-pass/"),
    enabled: Boolean(getVisitorToken()),
    staleTime: 60_000,
  })
}
