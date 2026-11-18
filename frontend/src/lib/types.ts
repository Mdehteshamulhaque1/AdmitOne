export type Role = "ADMIN" | "RECEPTIONIST" | "SECURITY"

/**
 * The permission names the server can report in `GET /api/auth/me/`.
 *
 * This is a *mirror* of `accounts/permissions.py`, not a second source of
 * truth. It exists so a typo in a `can("...")` call is a compile error rather
 * than a silently-always-false runtime check. The server remains authoritative:
 * it computes the real list from the user's role, and every endpoint
 * re-derives permissions independently.
 */
export type Permission =
  | "view_dashboard"
  | "create_visitor"
  | "approve_visitor"
  | "checkin_visitor"
  | "checkout_visitor"
  | "manage_org"
  | "manage_buildings"
  | "manage_departments"
  | "manage_employees"
  | "manage_users"
  | "view_reports"
  | "view_audit_logs"
  | "view_visitor_documents"
  | "blacklist_visitor"
  | "badge_print"
  | "scan_qr"

export type VisitStatus =
  | "PENDING"
  | "APPROVED"
  | "REJECTED"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "CANCELLED"
  | "ARCHIVED"

export const VISIT_STATUSES: VisitStatus[] = [
  "PENDING",
  "APPROVED",
  "CHECKED_IN",
  "CHECKED_OUT",
  "REJECTED",
  "CANCELLED",
  "ARCHIVED",
]

export const VISIT_STATUS_LABELS: Record<VisitStatus, string> = {
  PENDING: "Pending",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CHECKED_IN: "Checked in",
  CHECKED_OUT: "Checked out",
  CANCELLED: "Cancelled",
  ARCHIVED: "Archived",
}

export const ROLE_LABELS: Record<Role, string> = {
  ADMIN: "Admin",
  RECEPTIONIST: "Receptionist",
  SECURITY: "Security",
}

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  ADMIN: "Full access: settings, team, approvals, gate, reports and audit log.",
  RECEPTIONIST: "Registers visitors and walk-ins, prints badges, views reports.",
  SECURITY: "Scans QR passes, checks visitors in/out, manages the blacklist.",
}

export type VisitSource = "STAFF" | "WALK_IN" | "PUBLIC_BOOKING"

export const VISIT_SOURCE_LABELS: Record<VisitSource, string> = {
  STAFF: "Desk",
  WALK_IN: "Walk-in",
  PUBLIC_BOOKING: "Pre-booked",
}

export interface User {
  id: number
  email: string
  full_name: string
  phone: string
  role: Role
  organization: number | null
}

export interface Organization {
  id: number
  name: string
  slug: string
  tagline: string
  timezone: string
  working_hours_start: string
  working_hours_end: string
}

export interface OrganizationDetail extends Organization {
  logo: string | null
  address: string
  city: string
  country: string
  visitor_policies: Record<string, unknown>
  security_policies: Record<string, unknown>
  weekly_working_hours: WeeklyWorkingHours
  /** Effective catalogue (saved one, or the training-centre defaults). */
  visitor_catalogue: VisitorCatalogue
  booking_path: string
  created_at: string
}

/* ---------------- Visitor catalogue (who visits -> what for) ---------------- */

export interface CataloguePurpose {
  label: string
  visit_type: string
  room_type: RoomType | ""
}

export interface CatalogueCategory {
  key: string
  label: string
  purposes: CataloguePurpose[]
}

export interface VisitorCatalogue {
  categories: CatalogueCategory[]
}

/* ---------------- Rooms ---------------- */

export const ROOM_TYPES = [
  { value: "CLASSROOM", label: "Classroom" },
  { value: "LAB", label: "Lab" },
  { value: "INTERVIEW_CABIN", label: "Interview cabin" },
  { value: "PLACEMENT_HALL", label: "Placement hall" },
  { value: "GROOMING_ROOM", label: "Grooming room" },
  { value: "SEMINAR_HALL", label: "Seminar hall" },
  { value: "MEETING_ROOM", label: "Meeting room" },
  { value: "RECEPTION", label: "Reception / counselling" },
  { value: "OFFICE", label: "Office" },
  { value: "OTHER", label: "Other" },
] as const

export type RoomType = (typeof ROOM_TYPES)[number]["value"]

export interface Room {
  id: number
  building: number
  building_name: string
  floor: number | null
  floor_name: string
  number: string
  name: string
  room_type: RoomType
  room_type_label: string
  capacity: number
  is_active: boolean
  label: string
  created_at: string
}

export interface RoomPayload {
  building: number
  floor?: number | null
  number: string
  name?: string
  room_type?: RoomType
  capacity?: number
  is_active?: boolean
}

export interface RoomAttendance {
  id: number
  visit_id: number
  visit_reference: string
  visitor_name: string
  visitor_category: string
  purpose: string
  room: number
  room_label: string
  room_number: string
  building_name: string
  scanned_by_name: string
  scanned_at: string
  note: string
}

export interface RoomScanResult extends ScanResult {
  attendance: RoomAttendance | null
}

export interface OrganizationUpdatePayload {
  name?: string
  tagline?: string
  address?: string
  city?: string
  country?: string
  timezone?: string
  working_hours_start?: string
  working_hours_end?: string
  visitor_policies?: Record<string, unknown>
  security_policies?: Record<string, unknown>
  weekly_working_hours?: WeeklyWorkingHours
}

export interface Building {
  id: number
  name: string
  address: string
  floors: number
  entry_gates: number
  exit_gates: number
  has_reception_desk?: boolean
  /** Floor rows (kept in sync with `floors` by the API) for placing rooms. */
  floor_list?: BookingFloor[]
  room_count?: number
  created_at?: string
}

export interface BuildingPayload {
  name: string
  address?: string
  floors?: number
  entry_gates?: number
  exit_gates?: number
  has_reception_desk?: boolean
}

export interface Department {
  id: number
  name: string
  code: string
  member_count?: number
}

export interface EmployeeProfile {
  id: number
  employee_id: string
  designation: string
  office_location: string
  joining_date: string | null
  status: "ACTIVE" | "INACTIVE" | "ON_LEAVE"
  department: number | null
  department_name: string
  building: number | null
  building_name: string
}

export interface TeamMember {
  id: number
  email: string
  full_name: string
  phone: string
  role: Role
  is_active: boolean
  is_locked: boolean
  last_login: string | null
  created_at: string
  employee: EmployeeProfile | null
}

export interface TeamMemberCreatePayload {
  email: string
  full_name: string
  phone?: string
  role: Role
  password: string
  designation?: string
  employee_id?: string
  department?: number | null
  building?: number | null
}

export interface TeamMemberUpdatePayload {
  full_name?: string
  phone?: string
  role?: Role
  is_active?: boolean
  designation?: string
  employee_id?: string
  office_location?: string
  department?: number | null
  building?: number | null
  status?: EmployeeProfile["status"]
  password?: string
}

export interface MeResponse {
  user: User
  organization: Organization | null
  permissions: Permission[]
}

export interface OrganizationCreatePayload {
  name: string
  tagline?: string
  city?: string
  country?: string
  timezone?: string
  working_hours_start?: string
  working_hours_end?: string
  building_name?: string
}

export interface OrganizationResponse {
  organization: Organization
  user: User
}

export interface AuthTokens {
  access: string
  refresh: string
}

export interface Visitor {
  id: number
  full_name: string
  phone: string
  email: string
  company: string
  designation: string
  /** Training-centre profile (free text on the wire; dropdowns in the UI). */
  category: string
  state: string
  university: string
  qualification: string
  passing_year: number | null
  /** Only present for roles holding `view_visitor_pii` (admin, reception). */
  address?: string
  photo: string | null
  /** Only present for roles holding `view_visitor_documents`. */
  document_type?: string
  document_number?: string
  vehicle_number: string
  vehicle_type: string
  /** Only present for roles holding `view_visitor_pii`. */
  emergency_contact?: string
  emergency_phone?: string
  special_notes: string
  is_blacklisted: boolean
  blacklist_reason: string
  visit_count?: number
  last_visit_at?: string | null
  created_at: string
}

export type VisitorUpdatePayload = Partial<
  Pick<
    Visitor,
    | "full_name"
    | "phone"
    | "email"
    | "company"
    | "designation"
    | "address"
    | "document_type"
    | "document_number"
    | "vehicle_number"
    | "vehicle_type"
    | "emergency_contact"
    | "emergency_phone"
    | "special_notes"
  >
>

export interface QrPass {
  /** The raw credential; only present for roles holding `badge_print`. */
  token?: string
  signature?: string
  expires_at: string
  is_used: boolean
  is_valid: boolean
}

export interface Visit {
  id: number
  visit_id: string
  visitor: Visitor
  host: number | null
  host_name: string
  building: number | null
  building_name: string
  floor: number | null
  floor_name: string
  room: number | null
  room_label: string
  room_number: string
  attendance_count: number
  department_name: string
  purpose: string
  visitor_category: string
  visit_type: string
  visit_type_label: string
  source: VisitSource
  visit_date: string
  expected_arrival: string
  expected_exit: string
  status: VisitStatus
  qr: QrPass | null
  duration_minutes: number
  registered_at: string
  approved_at: string | null
  rejected_at: string | null
  rejection_reason: string
  checked_in_at: string | null
  checked_out_at: string | null
  cancelled_at: string | null
  cancelled_reason: string
  arriving_at: string | null
  created_by_name: string
  checked_in_by_name: string
  checked_out_by_name: string
  notes: string
}

export interface VisitListParams {
  status?: string
  q?: string
  date?: string
  date_from?: string
  date_to?: string
  visitor?: number
  host?: number
  building?: number
  room?: number
  inside?: boolean
  upcoming?: boolean
  ordering?: string
  page?: number
  page_size?: number
}

export interface Paged<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface ScanResult {
  ok: boolean
  detail: string
  dry_run?: boolean
  visit: Visit | null
}

export const BLACKLIST_REASONS = [
  { value: "SECURITY_CONCERN", label: "Security concern" },
  { value: "FAKE_DOCUMENTS", label: "Fake documents" },
  { value: "MISCONDUCT", label: "Misconduct" },
  { value: "PERMANENT_BAN", label: "Permanent ban" },
] as const

export type BlacklistReason = (typeof BLACKLIST_REASONS)[number]["value"]

export interface BlacklistEntry {
  id: number
  visitor: Pick<Visitor, "id" | "full_name" | "phone" | "email" | "company" | "photo">
  reason: BlacklistReason
  reason_label: string
  comment: string
  added_by_name: string
  is_active: boolean
  created_at: string
}

export interface AuditLogEntry {
  id: number
  action: string
  entity_type: string
  entity_id: string
  details: string
  ip_address: string | null
  created_at: string
  actor: { id: number; full_name: string; email: string; role: Role } | null
}

export interface AuditLogParams {
  q?: string
  action?: string
  entity_type?: string
  actor?: number
  date_from?: string
  date_to?: string
  page?: number
  page_size?: number
}

export const DOCUMENT_TYPES = [
  { value: "AADHAAR", label: "Aadhaar" },
  { value: "PASSPORT", label: "Passport" },
  { value: "PAN", label: "PAN Card" },
  { value: "DRIVING_LICENSE", label: "Driving License" },
  { value: "COMPANY_ID", label: "Company ID" },
] as const

export const VEHICLE_TYPES = [
  { value: "none", label: "No vehicle" },
  { value: "CAR", label: "Car" },
  { value: "BIKE", label: "Bike" },
  { value: "TRUCK", label: "Truck" },
  { value: "VAN", label: "Van" },
  { value: "OTHER", label: "Other" },
] as const

export interface DailyPoint {
  date: string
  visits: number
  checked_in: number
}

export interface DashboardAnalytics {
  daily_series: DailyPoint[]
  status_counts: Record<VisitStatus, number>
  top_visitors: { id: number; name: string; visits: number }[]
  peak_hours: { hour: string; visits: number }[]
  by_department: { name: string; visits: number }[]
  today_schedule: { expected: number; arrived: number; inside: number; left: number }
}

export interface DashboardSummary {
  today: number
  week: number
  month: number
  inside: number
  pending: number
  approved: number
  avg_duration_minutes: number
  checked_out: number
  rejected: number
  trend: number
  total: number
  repeat_visitors: number
  first_time_visitors: number
  analytics: DashboardAnalytics
}

export interface RegisterVisitPayload {
  visitor: {
    full_name: string
    phone: string
    email?: string
    company?: string
    designation?: string
    document_type?: string
    document_number?: string
    vehicle_number?: string
    vehicle_type?: string
  }
  visit: {
    purpose: string
    host?: number
    building?: number
    visit_date?: string
    expected_arrival?: string
    expected_exit?: string
    notes?: string
  }
}

export interface RegisterVisitResponse {
  visitor: Visitor
  visit: Visit
  /** Non-blocking notes, e.g. the host already has a visitor in that slot. */
  warnings: string[]
}

export type WeeklyWindow = { start: string; end: string }
/** Keys "0" (Monday) to "6" (Sunday); an empty list closes the day. */
export type WeeklyWorkingHours = Record<string, WeeklyWindow[]>

export interface ApiError {
  detail?: string | Record<string, string[]>
}

export interface BookingDepartment {
  id: number
  name: string
  code: string
}

export interface BookingFloor {
  id: number
  name: string
  level: number
}

export interface BookingBuilding {
  id: number
  name: string
  address: string
  floors: BookingFloor[]
}

export interface BookingHost {
  id: number
  name: string
  designation: string
  department: number | null
}

export interface VisitTypeOption {
  value: string
  label: string
}

export interface BookingOrganization {
  id: number
  name: string
  slug: string
  tagline: string
  address: string
  city: string
  country: string
  timezone: string
  working_hours_start: string
  working_hours_end: string
}

export interface BookingContext {
  organization: BookingOrganization
  departments: BookingDepartment[]
  buildings: BookingBuilding[]
  visit_types: VisitTypeOption[]
  purposes: Record<string, string[]>
  /** Catalogue categories the visitor chooses from (drives the purpose list). */
  visitor_categories: CatalogueCategory[]
}

export interface AvailabilitySlot {
  start: string
  end: string
}

export interface HostAvailabilityResponse {
  date: string
  host: {
    id: number
    name: string
  }
  slot_duration_minutes: number
  slots: AvailabilitySlot[]
}

/**
 * Flatten any DRF error body into one human-readable sentence.
 * Handles `{"detail": "..."}`, `{"detail": {field: [..]}}`, `{field: [..]}`,
 * nested `{visitor: {phone: [..]}}` and plain strings.
 */
export function formatApiError(err: unknown): string {
  const flatten = (value: unknown, prefix = ""): string[] => {
    if (value == null) return []
    if (typeof value === "string") return [prefix ? `${prefix}: ${value}` : value]
    if (Array.isArray(value)) return value.flatMap((v) => flatten(v, prefix))
    if (typeof value === "object") {
      return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) => {
        if (k === "detail" || k === "non_field_errors") return flatten(v, prefix)
        const label = k.replace(/_/g, " ")
        return flatten(v, prefix ? `${prefix} ${label}` : label)
      })
    }
    return [String(value)]
  }
  if (typeof err === "object" && err !== null) {
    const body = (err as { data?: unknown }).data
    const messages = flatten(body)
    if (messages.length) return messages.join(" ")
    if (err instanceof Error && err.message) return err.message
  }
  return "Something went wrong. Please try again."
}
