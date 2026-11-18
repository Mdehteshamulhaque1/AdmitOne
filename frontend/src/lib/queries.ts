import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { api, downloadFile } from "@/lib/api"
import type {
  AuditLogEntry,
  AuditLogParams,
  BlacklistEntry,
  BlacklistReason,
  Building,
  BuildingPayload,
  DashboardSummary,
  Department,
  OrganizationCreatePayload,
  OrganizationDetail,
  OrganizationResponse,
  OrganizationUpdatePayload,
  Paged,
  RegisterVisitPayload,
  RegisterVisitResponse,
  ScanResult,
  TeamMember,
  TeamMemberCreatePayload,
  TeamMemberUpdatePayload,
  User,
  Visit,
  VisitListParams,
  Visitor,
  VisitorUpdatePayload,
} from "@/lib/types"

export const queryKeys = {
  summary: ["summary"] as const,
  visits: (params: VisitListParams = {}) => ["visits", params] as const,
  visit: (id: number) => ["visit", id] as const,
  visitors: (q = "", page = 1, extra: Record<string, string> = {}) =>
    ["visitors", q, page, extra] as const,
  visitorVisits: (id: number) => ["visitor-visits", id] as const,
  hosts: ["hosts"] as const,
  buildings: ["buildings"] as const,
  departments: ["departments"] as const,
  team: (q = "") => ["team", q] as const,
  org: ["org"] as const,
  audit: (params: AuditLogParams = {}) => ["audit", params] as const,
  auditActions: ["audit-actions"] as const,
  blacklist: (q = "", page = 1) => ["blacklist", q, page] as const,
  me: ["me"] as const,
}

function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || value === false) continue
    search.set(key, value === true ? "1" : String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ""
}

/* ---------------- Dashboard ---------------- */

export function useSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: () => api<DashboardSummary>("/api/dashboard/summary/"),
    refetchInterval: 60_000,
  })
}

/* ---------------- Visits ---------------- */

export function useVisits(params: VisitListParams = {}, options: { enabled?: boolean; refetchInterval?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.visits(params),
    queryFn: () => api<Paged<Visit>>(`/api/visits/${qs({ page_size: 20, ...params })}`),
    placeholderData: keepPreviousData,
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
  })
}

/** Convenience: a flat list (first `page_size` rows) for small live panels. */
export function useVisitList(params: VisitListParams = {}, options: { refetchInterval?: number } = {}) {
  const query = useVisits({ page_size: 100, ...params }, options)
  return { ...query, data: query.data?.results ?? [] }
}

export function useVisit(id: number | null) {
  return useQuery({
    queryKey: queryKeys.visit(id ?? 0),
    queryFn: () => api<Visit>(`/api/visits/${id}/`),
    enabled: id !== null,
  })
}

function invalidateVisitData(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: ["visits"] })
  void queryClient.invalidateQueries({ queryKey: ["visit"] })
  void queryClient.invalidateQueries({ queryKey: ["visitor-visits"] })
  void queryClient.invalidateQueries({ queryKey: ["visitors"] })
  void queryClient.invalidateQueries({ queryKey: ["summary"] })
}

function useVisitAction(endpoint: "approve" | "checkin" | "checkout" | "reissue") {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<{ detail: string; visit: Visit }>(`/api/visits/${id}/${endpoint}/`, {
        method: "POST",
        body: "{}",
      }),
    onSuccess: () => invalidateVisitData(queryClient),
  })
}

export function useApproveVisit() {
  return useVisitAction("approve")
}
export function useCheckIn() {
  return useVisitAction("checkin")
}
export function useCheckOut() {
  return useVisitAction("checkout")
}
export function useReissuePass() {
  return useVisitAction("reissue")
}

export function useRejectVisit() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      api<{ detail: string; visit: Visit }>(`/api/visits/${id}/reject/`, {
        method: "POST",
        body: JSON.stringify({ reason: reason || "Declined" }),
      }),
    onSuccess: () => invalidateVisitData(queryClient),
  })
}

export function useCancelVisit() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason }: { id: number; reason?: string }) =>
      api<{ detail: string; visit: Visit }>(`/api/visits/${id}/cancel/`, {
        method: "POST",
        body: JSON.stringify({ reason: reason ?? "" }),
      }),
    onSuccess: () => invalidateVisitData(queryClient),
  })
}

export function useScanPass() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ payload, dryRun = false }: { payload: string; dryRun?: boolean }) =>
      api<ScanResult>("/api/visits/scan/", {
        method: "POST",
        body: JSON.stringify({ payload, dry_run: dryRun }),
      }),
    onSuccess: (_data, vars) => {
      if (!vars.dryRun) invalidateVisitData(queryClient)
    },
  })
}

export function useRegisterVisit() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: RegisterVisitPayload) =>
      api<RegisterVisitResponse>("/api/visits/register/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => invalidateVisitData(queryClient),
  })
}

export function useWalkInVisit() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: RegisterVisitPayload) =>
      api<RegisterVisitResponse>("/api/visits/walkin/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => invalidateVisitData(queryClient),
  })
}

/* ---------------- Visitors ---------------- */

export function useVisitors({
  search = "",
  page = 1,
  blacklisted,
  ordering,
}: { search?: string; page?: number; blacklisted?: boolean; ordering?: string } = {}) {
  const extra: Record<string, string> = {}
  if (blacklisted !== undefined) extra.blacklisted = String(blacklisted)
  if (ordering) extra.ordering = ordering
  return useQuery({
    queryKey: queryKeys.visitors(search, page, extra),
    queryFn: async () => {
      const response = await api<Paged<Visitor>>(
        `/api/visitors/${qs({ page, page_size: 20, q: search, ...extra })}`,
      )
      return { visitors: response.results, total: response.count, hasMore: Boolean(response.next) }
    },
    placeholderData: keepPreviousData,
  })
}

export function useVisitor(visitorId: number | null) {
  return useQuery({
    queryKey: ["visitor", visitorId ?? 0] as const,
    queryFn: () => api<Visitor>(`/api/visitors/${visitorId}/`),
    enabled: visitorId !== null,
  })
}

export function useVisitorVisits(visitorId: number | null) {
  return useQuery({
    queryKey: queryKeys.visitorVisits(visitorId ?? 0),
    queryFn: () => api<Visit[]>(`/api/visitors/${visitorId}/visits/`),
    enabled: visitorId !== null,
  })
}

export function useUpdateVisitor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: VisitorUpdatePayload }) =>
      api<Visitor>(`/api/visitors/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => invalidateVisitData(queryClient),
  })
}

export function useBlacklistVisitor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, reason, comment }: { id: number; reason: BlacklistReason; comment?: string }) =>
      api<{ detail: string; entry: BlacklistEntry }>(`/api/visitors/${id}/blacklist/`, {
        method: "POST",
        body: JSON.stringify({ reason, comment: comment ?? "" }),
      }),
    onSuccess: () => {
      invalidateVisitData(queryClient)
      void queryClient.invalidateQueries({ queryKey: ["blacklist"] })
    },
  })
}

export function useUnblacklistVisitor() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api<{ detail: string }>(`/api/visitors/${id}/blacklist/`, { method: "DELETE" }),
    onSuccess: () => {
      invalidateVisitData(queryClient)
      void queryClient.invalidateQueries({ queryKey: ["blacklist"] })
    },
  })
}

export function useBlacklist({ search = "", page = 1 }: { search?: string; page?: number } = {}) {
  return useQuery({
    queryKey: queryKeys.blacklist(search, page),
    queryFn: () => api<Paged<BlacklistEntry>>(`/api/blacklist/${qs({ q: search, page, page_size: 20 })}`),
    placeholderData: keepPreviousData,
  })
}

/* ---------------- Org data ---------------- */

export function useHosts() {
  return useQuery({
    queryKey: queryKeys.hosts,
    queryFn: () => api<User[]>("/api/hosts/"),
    staleTime: 60_000,
  })
}

export function useBuildings() {
  return useQuery({
    queryKey: queryKeys.buildings,
    queryFn: () => api<Building[]>("/api/buildings/"),
    staleTime: 60_000,
  })
}

export function useDepartments() {
  return useQuery({
    queryKey: queryKeys.departments,
    queryFn: () => api<Department[]>("/api/departments/"),
    staleTime: 60_000,
  })
}

export function useOrganization(enabled = true) {
  return useQuery({
    queryKey: queryKeys.org,
    queryFn: () => api<OrganizationDetail>("/api/organizations/me/"),
    enabled,
  })
}

export function useUpdateOrganization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: OrganizationUpdatePayload) =>
      api<OrganizationDetail>("/api/organizations/me/", {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.org })
      void queryClient.invalidateQueries({ queryKey: queryKeys.me })
    },
  })
}

function useCrud<T, P>(path: string, key: readonly unknown[]) {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: key })
    void queryClient.invalidateQueries({ queryKey: queryKeys.hosts })
  }
  const create = useMutation({
    mutationFn: (payload: P) => api<T>(`${path}/`, { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: invalidate,
  })
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<P> }) =>
      api<T>(`${path}/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => api<void>(`${path}/${id}/`, { method: "DELETE" }),
    onSuccess: invalidate,
  })
  return { create, update, remove }
}

export function useBuildingMutations() {
  return useCrud<Building, BuildingPayload>("/api/buildings", queryKeys.buildings)
}

export function useDepartmentMutations() {
  return useCrud<Department, { name: string; code?: string }>("/api/departments", queryKeys.departments)
}

/* ---------------- Team ---------------- */

export function useTeam(search = "") {
  return useQuery({
    queryKey: queryKeys.team(search),
    queryFn: () => api<TeamMember[]>(`/api/team/${qs({ q: search })}`),
    placeholderData: keepPreviousData,
  })
}

export function useTeamMutations() {
  const queryClient = useQueryClient()
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["team"] })
    void queryClient.invalidateQueries({ queryKey: queryKeys.hosts })
    void queryClient.invalidateQueries({ queryKey: queryKeys.departments })
  }
  const create = useMutation({
    mutationFn: (payload: TeamMemberCreatePayload) =>
      api<TeamMember>("/api/team/", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: invalidate,
  })
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: TeamMemberUpdatePayload }) =>
      api<TeamMember>(`/api/team/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: invalidate,
  })
  const deactivate = useMutation({
    mutationFn: (id: number) => api<void>(`/api/team/${id}/`, { method: "DELETE" }),
    onSuccess: invalidate,
  })
  return { create, update, deactivate }
}

/* ---------------- Audit ---------------- */

export function useAuditLogs(params: AuditLogParams = {}) {
  return useQuery({
    queryKey: queryKeys.audit(params),
    queryFn: () => api<Paged<AuditLogEntry>>(`/api/audit-logs/${qs({ page_size: 25, ...params })}`),
    placeholderData: keepPreviousData,
  })
}

export function useAuditActions() {
  return useQuery({
    queryKey: queryKeys.auditActions,
    queryFn: () => api<string[]>("/api/audit-logs/actions/"),
    staleTime: 5 * 60_000,
  })
}

export async function exportAuditCsv(params: AuditLogParams = {}): Promise<void> {
  const filename = `securegate-audit-${new Date().toISOString().slice(0, 10)}.csv`
  return downloadFile(`/api/audit-logs/${qs({ ...params, export: "csv" })}`, filename)
}

/* ---------------- Account ---------------- */

export function useUpdateProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { full_name?: string; phone?: string }) =>
      api<User>("/api/auth/me/profile/", { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.me }),
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (payload: { current_password: string; new_password: string }) =>
      api<{ detail: string }>("/api/auth/change-password/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  })
}

export function useCreateOrganization() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: OrganizationCreatePayload) =>
      api<OrganizationResponse>("/api/organizations/", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.me })
    },
  })
}

/* ---------------- Reports ---------------- */

export type ExportPeriod = "daily" | "weekly" | "monthly" | "all"

export async function exportReportsCsv(period: ExportPeriod): Promise<void> {
  const filename = `securegate-${period}-${new Date().toISOString().slice(0, 10)}.csv`
  return downloadFile(`/api/reports/export/?period=${period}`, filename)
}
