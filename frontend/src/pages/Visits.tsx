import { useCallback, useMemo, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { CalendarRange, Filter, UserPlus, X } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table"
import { PageHeader } from "@/components/widgets/PageHeader"
import { Pagination } from "@/components/widgets/Pagination"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { StatusChip } from "@/components/widgets/StatusChip"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { useAuth } from "@/lib/auth"
import { useVisits } from "@/lib/queries"
import { VISIT_SOURCE_LABELS, VISIT_STATUSES, VISIT_STATUS_LABELS, type Visit } from "@/lib/types"
import { cn, formatClock, formatDate, formatDuration, todayIso } from "@/lib/utils"

const PAGE_SIZE = 20

const QUICK_FILTERS: { label: string; params: Record<string, string> }[] = [
  { label: "All", params: {} },
  { label: "Today", params: { date: "today" } },
  { label: "Upcoming", params: { upcoming: "1" } },
  { label: "Inside now", params: { status: "CHECKED_IN" } },
  { label: "Awaiting approval", params: { status: "PENDING" } },
]

export function VisitsPage() {
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const [selected, setSelected] = useState<Visit | null>(null)
  const [showFilters, setShowFilters] = useState(false)

  const q = searchParams.get("q") ?? ""
  const status = searchParams.get("status") ?? ""
  const date = searchParams.get("date") ?? ""
  const dateFrom = searchParams.get("date_from") ?? ""
  const dateTo = searchParams.get("date_to") ?? ""
  const upcoming = searchParams.get("upcoming") === "1"
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1)

  const params = useMemo(
    () => ({
      q,
      status,
      date,
      date_from: dateFrom,
      date_to: dateTo,
      upcoming,
      page,
      page_size: PAGE_SIZE,
      ordering: date === "today" || upcoming ? "visit_date" : "-registered_at",
    }),
    [q, status, date, dateFrom, dateTo, upcoming, page],
  )
  const { data, isLoading, isError, isFetching, refetch } = useVisits(params)

  const update = useCallback(
    (patch: Record<string, string | undefined>, resetPage = true) => {
      const next = new URLSearchParams(searchParams)
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === "") next.delete(k)
        else next.set(k, v)
      }
      if (resetPage) next.delete("page")
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const activeQuick = QUICK_FILTERS.find((f) => {
    const keys = ["date", "upcoming", "status"]
    return keys.every((k) => (f.params[k] ?? "") === (searchParams.get(k) ?? ""))
  })
  const hasFilters = Boolean(q || status || date || dateFrom || dateTo || upcoming)
  const rows = data?.results ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Visits"
        description="Every scheduled, active and completed visit in your workspace."
        actions={
          can("create_visitor") && (
            <Button asChild>
              <Link to="/dashboard/register-visit">
                <UserPlus className="size-4" /> Register visit
              </Link>
            </Button>
          )
        }
      />

      {isError && <QueryErrorState message="Couldn't load visits." retry={() => void refetch()} />}

      <div className="flex flex-wrap items-center gap-2">
        {QUICK_FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            onClick={() => update({ date: undefined, upcoming: undefined, status: undefined, ...f.params })}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              activeQuick?.label === f.label
                ? "border-primary/30 bg-primary-soft text-primary"
                : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            {f.label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <SearchInput value={q} onChange={(v) => update({ q: v })} placeholder="Search name, phone, purpose…" className="w-full sm:w-72" />
          <Button variant={showFilters || hasFilters ? "secondary" : "outline"} size="icon" onClick={() => setShowFilters((s) => !s)} aria-label="More filters">
            <Filter className="size-4" />
          </Button>
        </div>
      </div>

      {showFilters && (
        <div className="card-surface grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">Status</label>
            <Select value={status || "all"} onValueChange={(v) => update({ status: v === "all" ? undefined : v })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Any status</SelectItem>
                {VISIT_STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>{VISIT_STATUS_LABELS[s]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">On date</label>
            <Input type="date" value={date === "today" ? todayIso() : date} onChange={(e) => update({ date: e.target.value, date_from: undefined, date_to: undefined })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">From</label>
            <Input type="date" value={dateFrom} onChange={(e) => update({ date_from: e.target.value, date: undefined })} />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground">To</label>
            <Input type="date" value={dateTo} onChange={(e) => update({ date_to: e.target.value, date: undefined })} />
          </div>
          <div className="flex items-end">
            <Button variant="ghost" size="sm" disabled={!hasFilters} onClick={() => setSearchParams({}, { replace: true })}>
              <X className="size-4" /> Clear filters
            </Button>
          </div>
        </div>
      )}

      <div className="card-surface overflow-hidden">
        {isLoading ? (
          <div className="space-y-3 p-5">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<CalendarRange className="size-6" />}
              title={hasFilters ? "No visits match these filters" : "No visits yet"}
              description={hasFilters ? "Try widening the date range or clearing the search." : "Register a visitor to create the first visit."}
              action={hasFilters ? <Button size="sm" variant="outline" onClick={() => setSearchParams({}, { replace: true })}>Clear filters</Button> : undefined}
            />
          </div>
        ) : (
          <>
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Visitor</TableHead>
                    <TableHead>Purpose</TableHead>
                    <TableHead>Schedule</TableHead>
                    <TableHead>Host</TableHead>
                    <TableHead>Source</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">On site</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((v) => (
                    <TableRow key={v.id} className="cursor-pointer" onClick={() => setSelected(v)}>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <Avatar name={v.visitor.full_name} src={v.visitor.photo} />
                          <div className="min-w-0">
                            <div className="truncate font-medium">{v.visitor.full_name}</div>
                            <div className="truncate text-xs text-muted-foreground">{v.visitor.company || v.visitor.phone}</div>
                          </div>
                          {v.visitor.is_blacklisted && <Badge tone="danger" size="sm">Blacklisted</Badge>}
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[16rem] truncate text-muted-foreground">{v.purpose}</TableCell>
                      <TableCell>
                        <div className="text-sm">{formatDate(v.visit_date)}</div>
                        <div className="text-xs text-muted-foreground">{formatClock(v.expected_arrival)}–{formatClock(v.expected_exit)}</div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{v.host_name || "—"}</TableCell>
                      <TableCell><Badge size="sm">{VISIT_SOURCE_LABELS[v.source] ?? v.source}</Badge></TableCell>
                      <TableCell><StatusChip status={v.status} /></TableCell>
                      <TableCell className="text-right text-muted-foreground">{formatDuration(v.duration_minutes)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <ul className="divide-y divide-border md:hidden">
              {rows.map((v) => (
                <li key={v.id}>
                  <button type="button" onClick={() => setSelected(v)} className="flex w-full items-center gap-3 p-4 text-left">
                    <Avatar name={v.visitor.full_name} src={v.visitor.photo} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">{v.visitor.full_name}</span>
                        <StatusChip status={v.status} size="sm" />
                      </div>
                      <div className="truncate text-xs text-muted-foreground">{v.purpose}</div>
                      <div className="text-xs text-muted-foreground">{formatDate(v.visit_date)} · {formatClock(v.expected_arrival)}</div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data?.count ?? 0} onPageChange={(p) => update({ page: String(p) }, false)} label="visits" isFetching={isFetching} />
          </>
        )}
      </div>

      <VisitDrawer visitId={selected?.id ?? null} initial={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
