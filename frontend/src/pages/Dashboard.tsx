import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  ArrowUpRight,
  Building2,
  CalendarCheck2,
  CheckCheck,
  CheckCircle2,
  Clock,
  Hourglass,
  LogOut,
  ScanLine,
  UserPlus,
  XCircle,
} from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Card, CardContent } from "@/components/ui/Card"
import { Skeleton } from "@/components/ui/Skeleton"
import { EmptyState } from "@/components/ui/EmptyState"
import { ChartCard } from "@/components/widgets/ChartCard"
import { ChartTooltip } from "@/components/widgets/ChartTooltip"
import { KpiCard } from "@/components/widgets/KpiCard"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { StatusChip } from "@/components/widgets/StatusChip"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { useAuth } from "@/lib/auth"
import { useApproveVisit, useSummary, useVisitList } from "@/lib/queries"
import { useChartPalette } from "@/lib/theme"
import { formatApiError, type Visit } from "@/lib/types"
import { formatClock, formatDate, greeting } from "@/lib/utils"

export function DashboardPage() {
  const { user, org, can } = useAuth()
  const palette = useChartPalette()
  const { data: summary, isLoading: loadingSummary, isError: summaryError, refetch: refetchSummary } = useSummary()
  const { data: recent, isLoading: loadingRecent, isError: recentError, refetch: refetchRecent } = useVisitList(
    { page_size: 8 },
    { refetchInterval: 60_000 },
  )
  const { data: today, isLoading: loadingToday } = useVisitList(
    { date: "today", status: "PENDING,APPROVED,CHECKED_IN", ordering: "expected_arrival", page_size: 12 },
    { refetchInterval: 60_000 },
  )
  const approve = useApproveVisit()
  const [selected, setSelected] = useState<Visit | null>(null)

  const analytics = summary?.analytics
  const flow = useMemo(
    () =>
      (analytics?.daily_series ?? []).map((p) => ({
        date: p.date.slice(5).replace("-", "/"),
        full: p.date,
        Visits: p.visits,
        "Checked in": p.checked_in,
      })),
    [analytics],
  )
  const sparkline = (analytics?.daily_series ?? []).slice(-7).map((p) => p.visits)
  const topVisitors = (analytics?.top_visitors ?? []).slice(0, 6).map((t) => ({
    name: t.name.split(" ")[0],
    full: t.name,
    Visits: t.visits,
  }))

  const quickApprove = async (v: Visit) => {
    try {
      const res = await approve.mutateAsync(v.id)
      toast.success("Visit approved", { description: res.detail })
    } catch (e) {
      toast.error("Approval failed", { description: formatApiError(e) })
    }
  }

  const firstName = user?.full_name.split(" ")[0] ?? "there"

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org?.name}
        title={`${greeting()}, ${firstName}`}
        description="Live view of who is expected, who is inside and what needs your decision."
        actions={
          <>
            {can("scan_qr") && (
              <Button variant="secondary" size="sm" asChild>
                <Link to="/dashboard/security">
                  <ScanLine className="size-4" /> Gate scanner
                </Link>
              </Button>
            )}
            {can("approve_visitor") && (
              <Button variant="secondary" size="sm" asChild>
                <Link to="/dashboard/approvals">
                  <CheckCheck className="size-4" /> Approvals
                  {summary && summary.pending > 0 && (
                    <Badge tone="warning" size="sm">{summary.pending}</Badge>
                  )}
                </Link>
              </Button>
            )}
            {can("create_visitor") && (
              <Button size="sm" asChild>
                <Link to="/dashboard/register-visit">
                  <UserPlus className="size-4" /> Register visitor
                </Link>
              </Button>
            )}
          </>
        }
      />

      {(summaryError || recentError) && (
        <QueryErrorState
          message="Some dashboard data couldn't be loaded."
          retry={() => {
            void refetchSummary()
            void refetchRecent()
          }}
        />
      )}

      <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 xl:grid-cols-6">
        <KpiCard index={0} label="Visitors today" value={summary?.today ?? 0} icon={<CalendarCheck2 className="size-5" />} accent="primary" trend={summary ? summary.trend : null} sparkline={sparkline} to="/dashboard/visits?date=today" />
        <KpiCard index={1} label="Pending approvals" value={summary?.pending ?? 0} icon={<Hourglass className="size-5" />} accent="warning" to={can("approve_visitor") ? "/dashboard/approvals" : "/dashboard/visits?status=PENDING"} />
        <KpiCard index={2} label="Inside now" value={summary?.inside ?? 0} icon={<Building2 className="size-5" />} accent="cyan" to="/dashboard/visits?status=CHECKED_IN" />
        <KpiCard index={3} label="Checked out" value={summary?.checked_out ?? 0} icon={<LogOut className="size-5" />} accent="info" hint="all time" />
        <KpiCard index={4} label="Rejected" value={summary?.rejected ?? 0} icon={<XCircle className="size-5" />} accent="danger" hint="all time" />
        <KpiCard index={5} label="Avg time on site" value={summary?.avg_duration_minutes ?? 0} suffix="min" icon={<Clock className="size-5" />} accent="violet" />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ChartCard title="Visit flow" description="Scheduled visits per day · last 14 days" className="lg:col-span-2">
          {loadingSummary ? (
            <Skeleton className="h-64 w-full" />
          ) : flow.length === 0 ? (
            <EmptyState title="No visits yet" description="Register a visitor to see activity here." className="py-10" />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={flow} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id="flowGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={palette.series[0]} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={palette.series[0]} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={palette.grid} vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} interval={1} />
                  <YAxis tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip labelFormatter={(_, p) => formatDate(String(p?.full ?? ""))} />} cursor={{ stroke: palette.grid }} />
                  <Area type="monotone" dataKey="Visits" stroke={palette.series[0]} strokeWidth={2.5} fill="url(#flowGrad)" activeDot={{ r: 4 }} />
                  <Area type="monotone" dataKey="Checked in" stroke={palette.series[1]} strokeWidth={2} fill="transparent" strokeDasharray="4 3" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>

        <ChartCard title="Frequent visitors" description="Most visits on record">
          {loadingSummary ? (
            <Skeleton className="h-56 w-full" />
          ) : topVisitors.length === 0 ? (
            <EmptyState title="No data yet" className="py-8" />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={topVisitors} layout="vertical" margin={{ top: 0, right: 12, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke={palette.grid} horizontal={false} />
                  <XAxis type="number" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={70} tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip labelFormatter={(_, p) => String(p?.full ?? "")} />} cursor={{ fill: palette.grid }} />
                  <Bar dataKey="Visits" radius={[0, 6, 6, 0]} fill={palette.series[1]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardContent className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold">Today's schedule</h3>
                <p className="text-xs text-muted-foreground">
                  {analytics
                    ? `${analytics.today_schedule.expected} expected · ${analytics.today_schedule.arrived} arrived · ${analytics.today_schedule.left} left`
                    : "Expected arrivals in order"}
                </p>
              </div>
              <Link to="/dashboard/visits?date=today" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-strong">
                All today <ArrowUpRight className="size-3.5" />
              </Link>
            </div>
            {loadingToday ? (
              <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
            ) : today.length === 0 ? (
              <EmptyState icon={<CalendarCheck2 className="size-5" />} title="Nothing scheduled today" description="Visits registered for today will appear here in arrival order." className="py-8" />
            ) : (
              <ul className="divide-y divide-border">
                {today.map((v) => (
                  <li key={v.id} className="flex items-center gap-3 py-2.5">
                    <span className="w-12 shrink-0 font-mono text-xs text-muted-foreground">{formatClock(v.expected_arrival)}</span>
                    <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-8" />
                    <button type="button" onClick={() => setSelected(v)} className="min-w-0 flex-1 text-left">
                      <div className="truncate text-sm font-medium hover:text-primary">{v.visitor.full_name}</div>
                      <div className="truncate text-xs text-muted-foreground">{v.purpose}{v.host_name ? ` · ${v.host_name}` : ""}</div>
                    </button>
                    {v.status === "PENDING" && can("approve_visitor") ? (
                      <Button size="sm" variant="outline" disabled={approve.isPending} onClick={() => quickApprove(v)}>
                        <CheckCircle2 className="size-3.5" /> Approve
                      </Button>
                    ) : (
                      <StatusChip status={v.status} size="sm" />
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Recent activity</h3>
              <Link to="/dashboard/visits" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-strong">
                All visits <ArrowUpRight className="size-3.5" />
              </Link>
            </div>
            {loadingRecent ? (
              <div className="space-y-3">{[...Array(5)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
            ) : recent.length === 0 ? (
              <EmptyState icon={<UserPlus className="size-5" />} title="No visits yet" description="Register your first visitor to get started." className="py-8" />
            ) : (
              <ul className="space-y-1">
                {recent.map((v) => (
                  <li key={v.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(v)}
                      className="flex w-full items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors hover:bg-hover"
                    >
                      <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-9" />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-sm font-medium">{v.visitor.full_name}</span>
                          <StatusChip status={v.status} size="sm" />
                        </div>
                        <div className="truncate text-xs text-muted-foreground">{v.purpose} · {formatDate(v.visit_date)}</div>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <VisitDrawer visitId={selected?.id ?? null} initial={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
