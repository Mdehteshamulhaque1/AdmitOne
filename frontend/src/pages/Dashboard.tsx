import { useMemo, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import {
  ArrowUpRight,
  CalendarCheck2,
  CheckCheck,
  CheckCircle2,
  DoorOpen,
  Hourglass,
  LogIn,
  ScanLine,
  UserPlus,
  Users,
} from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Skeleton } from "@/components/ui/Skeleton"
import { ChartCard } from "@/components/widgets/ChartCard"
import { ChartTooltip } from "@/components/widgets/ChartTooltip"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { StatusChip } from "@/components/widgets/StatusChip"
import { AssignRoomDialog } from "@/components/visits/AssignRoomDialog"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { useAuth } from "@/lib/auth"
import { useApproveVisit, useSummary, useVisitList } from "@/lib/queries"
import { useChartPalette } from "@/lib/theme"
import { formatApiError, type Visit } from "@/lib/types"
import { cn, formatClock, formatDate, formatRelative, greeting } from "@/lib/utils"

/** One number about today, with where it leads. */
function TodayTile({ label, value, icon, tone, to, loading }: { label: string; value: number; icon: ReactNode; tone: string; to?: string; loading: boolean }) {
  const body = (
    <div className={cn("flex h-full items-center gap-4 rounded-2xl border border-border bg-card p-4 shadow-card transition", to && "hover:border-primary/50")}>
      <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl", tone)}>{icon}</span>
      <div className="min-w-0">
        {loading ? <Skeleton className="h-7 w-10" /> : <div className="text-2xl font-semibold tabular-nums">{value}</div>}
        <div className="truncate text-sm text-muted-foreground">{label}</div>
      </div>
    </div>
  )
  return to ? <Link to={to} className="rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{body}</Link> : body
}

function Panel({ title, hint, link, children, className }: { title: string; hint?: string; link?: { to: string; label: string }; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-2xl border border-border bg-card p-5 shadow-card", className)}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{title}</h2>
          {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
        </div>
        {link && (
          <Link to={link.to} className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline">
            {link.label} <ArrowUpRight className="size-3.5" />
          </Link>
        )}
      </div>
      {children}
    </section>
  )
}

export function DashboardPage() {
  const { user, org, can } = useAuth()
  const palette = useChartPalette()
  const summary = useSummary()
  const today = useVisitList({ date: "today", status: "PENDING,APPROVED,CHECKED_IN,CHECKED_OUT", ordering: "expected_arrival", page_size: 50 }, { refetchInterval: 60_000 })
  const pending = useVisitList({ status: "PENDING", ordering: "visit_date", page_size: 4 }, { refetchInterval: 45_000 })
  const inside = useVisitList({ status: "CHECKED_IN", ordering: "-checked_in_at", page_size: 6 }, { refetchInterval: 30_000 })
  const approve = useApproveVisit()
  const [approving, setApproving] = useState<Visit | null>(null)
  const [selected, setSelected] = useState<Visit | null>(null)

  const s = summary.data
  const sched = s?.analytics?.today_schedule
  const flow = useMemo(
    () => (s?.analytics?.daily_series ?? []).map((p) => ({ date: p.date.slice(5).replace("-", "/"), full: p.date, Visits: p.visits, "Checked in": p.checked_in })),
    [s],
  )
  const topVisitors = (s?.analytics?.top_visitors ?? []).slice(0, 6).map((t) => ({ name: t.name.split(" ")[0], full: t.name, Visits: t.visits }))

  const onApprove = async (v: Visit, room: number | null) => {
    try {
      const res = await approve.mutateAsync({ id: v.id, room })
      toast.success(`${v.visitor.full_name} approved`, { description: res.detail })
      setApproving(null)
    } catch (e) {
      toast.error("Approval failed", { description: formatApiError(e) })
    }
  }

  const upcoming = today.data.filter((v) => v.status !== "CHECKED_OUT")
  const firstName = user?.full_name.split(" ")[0] ?? "there"

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org?.name}
        title={`${greeting()}, ${firstName}`}
        description="What's happening at the gate today, and what needs your decision."
        actions={
          <>
            {can("scan_qr") && (
              <Button variant="secondary" size="sm" asChild>
                <Link to="/dashboard/security"><ScanLine className="size-4" /> Gate scanner</Link>
              </Button>
            )}
            {can("create_visitor") && (
              <Button size="sm" asChild>
                <Link to="/dashboard/register-visit"><UserPlus className="size-4" /> Register visit</Link>
              </Button>
            )}
          </>
        }
      />

      {summary.isError && <QueryErrorState message="Some dashboard numbers didn't load." retry={() => void summary.refetch()} />}

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <TodayTile loading={summary.isLoading} label="Expected today" value={sched?.expected ?? s?.today ?? 0} icon={<CalendarCheck2 className="size-5" />} tone="bg-primary-soft text-primary" to="/dashboard/visits?date=today" />
        <TodayTile loading={summary.isLoading} label="Arrived today" value={sched?.arrived ?? 0} icon={<LogIn className="size-5" />} tone="bg-success-soft text-success" to="/dashboard/visits?date=today" />
        <TodayTile loading={summary.isLoading} label="Inside now" value={s?.inside ?? 0} icon={<Users className="size-5" />} tone="bg-info-soft text-info" to={can("scan_qr") ? "/dashboard/security" : "/dashboard/visits?status=CHECKED_IN"} />
        <TodayTile
          loading={summary.isLoading}
          label="Waiting for approval"
          value={s?.pending ?? 0}
          icon={<Hourglass className="size-5" />}
          tone={(s?.pending ?? 0) > 0 ? "bg-warning-soft text-warning" : "bg-secondary text-muted-foreground"}
          to={can("approve_visitor") ? "/dashboard/approvals" : "/dashboard/visits?status=PENDING"}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Panel
          className="lg:col-span-2"
          title="Today's arrivals"
          hint={sched ? `${sched.expected} expected, ${sched.arrived} arrived, ${sched.left} left` : "In order of arrival time"}
          link={{ to: "/dashboard/visits?date=today", label: "All of today" }}
        >
          {today.isLoading ? (
            <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-14 w-full" />)}</div>
          ) : upcoming.length === 0 ? (
            <EmptyState icon={<CalendarCheck2 className="size-5" />} title="No more visitors expected today" description="Visits booked or registered for today appear here in arrival order." className="py-8" />
          ) : (
            <ol className="relative space-y-1 before:absolute before:bottom-3 before:left-[3.15rem] before:top-3 before:w-px before:bg-border">
              {upcoming.map((v) => (
                <li key={v.id} className="relative flex items-center gap-3 rounded-xl px-1 py-2">
                  <span className="w-11 shrink-0 text-right text-xs font-medium tabular-nums text-muted-foreground">{formatClock(v.expected_arrival)}</span>
                  <span className={cn("relative z-10 size-2.5 shrink-0 rounded-full ring-4 ring-card", v.status === "CHECKED_IN" ? "bg-success" : v.status === "APPROVED" ? "bg-primary" : "bg-warning")} />
                  <button type="button" onClick={() => setSelected(v)} className="flex min-w-0 flex-1 items-center gap-3 text-left">
                    <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-9" />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium hover:text-primary">{v.visitor.full_name}</span>
                      <span className="block truncate text-xs text-muted-foreground">{v.purpose}{v.host_name ? ` · with ${v.host_name}` : ""}{v.room_label ? ` · Room ${v.room_label}` : ""}</span>
                    </span>
                  </button>
                  {v.status === "PENDING" && can("approve_visitor") ? (
                    <Button size="sm" variant="outline" onClick={() => setApproving(v)} disabled={v.visitor.is_blacklisted}>
                      <CheckCircle2 className="size-3.5" /> Approve
                    </Button>
                  ) : (
                    <StatusChip status={v.status} size="sm" />
                  )}
                </li>
              ))}
            </ol>
          )}
        </Panel>

        <div className="space-y-4">
          {can("approve_visitor") && (
            <Panel title="Needs your decision" link={{ to: "/dashboard/approvals", label: "Approvals" }}>
              {pending.isLoading ? (
                <Skeleton className="h-24 w-full" />
              ) : pending.data.length === 0 ? (
                <p className="flex items-center gap-2 text-sm text-muted-foreground"><CheckCheck className="size-4 text-success" /> Nothing waiting.</p>
              ) : (
                <ul className="space-y-2">
                  {pending.data.map((v) => (
                    <li key={v.id}>
                      <button type="button" onClick={() => setApproving(v)} className="flex w-full items-center gap-3 rounded-xl border border-border px-3 py-2 text-left transition hover:border-primary/50">
                        <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-8" />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">{v.visitor.full_name}</span>
                          <span className="block truncate text-xs text-muted-foreground">{formatDate(v.visit_date)}, {formatClock(v.expected_arrival)} · {v.purpose}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          )}
          <Panel title="Inside now" link={can("scan_qr") ? { to: "/dashboard/security", label: "Gate" } : undefined}>
            {inside.isLoading ? (
              <Skeleton className="h-24 w-full" />
            ) : inside.data.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nobody is checked in.</p>
            ) : (
              <ul className="space-y-2.5">
                {inside.data.map((v) => (
                  <li key={v.id}>
                    <button type="button" onClick={() => setSelected(v)} className="flex w-full items-center gap-3 text-left">
                      <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-8" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{v.visitor.full_name}</span>
                        <span className="block truncate text-xs text-muted-foreground">
                          in {formatRelative(v.checked_in_at)}{v.room_label ? ` · ` : ""}{v.room_label && <><DoorOpen className="inline size-3" /> {v.room_label}</>}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      <div>
        <h2 className="mb-3 text-sm font-semibold">Trends</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["This week", s?.week],
            ["This month", s?.month],
            ["Avg. time on site", s ? `${s.avg_duration_minutes} min` : undefined],
            ["Declined (all time)", s?.rejected],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-xl border border-border bg-card px-4 py-3">
              <div className="text-xs text-muted-foreground">{label}</div>
              <div className="mt-0.5 text-lg font-semibold tabular-nums">{value ?? "—"}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
          <ChartCard title="Visits per day" description="Last 14 days" className="lg:col-span-2">
            {summary.isLoading ? (
              <Skeleton className="h-56 w-full" />
            ) : flow.length === 0 ? (
              <EmptyState title="No visits yet" description="Register a visit to see activity here." className="py-10" />
            ) : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={flow} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="flowGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={palette.series[0]} stopOpacity={0.3} />
                        <stop offset="100%" stopColor={palette.series[0]} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke={palette.grid} vertical={false} />
                    <XAxis dataKey="date" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} interval={1} />
                    <YAxis tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip content={<ChartTooltip labelFormatter={(_, p) => formatDate(String(p?.full ?? ""))} />} cursor={{ stroke: palette.grid }} />
                    <Area type="monotone" dataKey="Visits" stroke={palette.series[0]} strokeWidth={2.5} fill="url(#flowGrad)" activeDot={{ r: 4 }} />
                    <Area type="monotone" dataKey="Checked in" stroke={palette.series[2]} strokeWidth={2} fill="transparent" strokeDasharray="4 3" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </ChartCard>
          <ChartCard title="Frequent visitors" description="Most visits on record">
            {summary.isLoading ? (
              <Skeleton className="h-52 w-full" />
            ) : topVisitors.length === 0 ? (
              <EmptyState title="No data yet" className="py-8" />
            ) : (
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={topVisitors} layout="vertical" margin={{ top: 0, right: 12, left: 8, bottom: 0 }}>
                    <CartesianGrid stroke={palette.grid} horizontal={false} />
                    <XAxis type="number" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" width={70} tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
                    <Tooltip content={<ChartTooltip labelFormatter={(_, p) => String(p?.full ?? "")} />} cursor={{ fill: palette.grid }} />
                    <Bar dataKey="Visits" radius={[0, 6, 6, 0]} fill={palette.series[0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </ChartCard>
        </div>
      </div>

      <AssignRoomDialog
        visit={approving}
        open={approving !== null}
        onOpenChange={(o) => !o && setApproving(null)}
        mode="approve"
        loading={approve.isPending}
        onConfirm={(room) => { if (approving) void onApprove(approving, room) }}
      />
      <VisitDrawer visitId={selected?.id ?? null} initial={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
