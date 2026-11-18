import { useMemo, useState } from "react"
import { toast } from "sonner"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { CalendarDays, Clock, Download, FileBarChart2, Repeat, Users } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card"
import { EmptyState } from "@/components/ui/EmptyState"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { ChartCard } from "@/components/widgets/ChartCard"
import { ChartTooltip } from "@/components/widgets/ChartTooltip"
import { KpiCard } from "@/components/widgets/KpiCard"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { StatusChip } from "@/components/widgets/StatusChip"
import { exportReportsCsv, useSummary, type ExportPeriod } from "@/lib/queries"
import { STATUS_COLORS, useChartPalette, useTheme } from "@/lib/theme"
import { VISIT_STATUSES, VISIT_STATUS_LABELS, formatApiError, type VisitStatus } from "@/lib/types"
import { formatDate } from "@/lib/utils"

const PERIOD_LABELS: Record<ExportPeriod, string> = {
  daily: "Today",
  weekly: "Last 7 days",
  monthly: "Last 30 days",
  all: "All time",
}

export function ReportsPage() {
  const { data: summary, isLoading, isError, refetch } = useSummary()
  const palette = useChartPalette()
  const { resolved } = useTheme()
  const [period, setPeriod] = useState<ExportPeriod>("monthly")
  const [exporting, setExporting] = useState(false)

  const analytics = summary?.analytics
  const statusData = useMemo(
    () =>
      VISIT_STATUSES.map((s) => ({
        status: s,
        name: VISIT_STATUS_LABELS[s],
        value: analytics?.status_counts[s] ?? 0,
        color: STATUS_COLORS[resolved][s],
      })).filter((d) => d.value > 0),
    [analytics, resolved],
  )
  const totalStatus = statusData.reduce((a, b) => a + b.value, 0)
  const flow = (analytics?.daily_series ?? []).map((p) => ({
    date: p.date.slice(5).replace("-", "/"),
    full: p.date,
    Visits: p.visits,
    "Checked in": p.checked_in,
  }))
  const peak = (analytics?.peak_hours ?? []).map((p) => ({ hour: p.hour.slice(0, 2), Visits: p.visits }))
  const depts = (analytics?.by_department ?? []).map((d) => ({ name: d.name, Visits: d.visits }))

  const handleExport = async () => {
    setExporting(true)
    try {
      await exportReportsCsv(period)
      toast.success("Export ready", { description: `${PERIOD_LABELS[period]} visit log is downloading.` })
    } catch (err) {
      toast.error("Export failed", { description: formatApiError(err) })
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Reports"
        description="Volume, throughput and patterns across your workspace. Every number here is computed from live visit records."
        actions={
          <div className="flex items-center gap-2">
            <Select value={period} onValueChange={(v) => setPeriod(v as ExportPeriod)}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(Object.keys(PERIOD_LABELS) as ExportPeriod[]).map((p) => (
                  <SelectItem key={p} value={p}>{PERIOD_LABELS[p]}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button onClick={handleExport} loading={exporting}>
              <Download className="size-4" /> Export CSV
            </Button>
          </div>
        }
      />

      {isError && <QueryErrorState message="Couldn't load report data." retry={() => void refetch()} />}

      <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-5">
        <KpiCard index={0} label="Visits, last 30 days" value={summary?.month ?? 0} icon={<CalendarDays className="size-5" />} accent="primary" />
        <KpiCard index={1} label="Visits, last 7 days" value={summary?.week ?? 0} icon={<CalendarDays className="size-5" />} accent="info" />
        <KpiCard index={2} label="Average time on site" value={summary?.avg_duration_minutes ?? 0} suffix="min" icon={<Clock className="size-5" />} accent="violet" />
        <KpiCard index={3} label="Repeat visitors" value={summary?.repeat_visitors ?? 0} icon={<Repeat className="size-5" />} accent="cyan" hint="2+ visits" />
        <KpiCard index={4} label="Total visits" value={summary?.total ?? 0} icon={<Users className="size-5" />} accent="warning" hint="all time" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <ChartCard title="Daily visits" description="Scheduled vs. checked in · last 14 days" className="lg:col-span-2">
          {isLoading ? <Skeleton className="h-64 w-full" /> : flow.length === 0 ? <EmptyState title="No data yet" className="py-10" /> : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={flow} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={palette.grid} vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} interval={1} />
                  <YAxis tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip labelFormatter={(_, p) => formatDate(String(p?.full ?? ""))} />} cursor={{ stroke: palette.grid }} />
                  <Line type="monotone" dataKey="Visits" stroke={palette.series[0]} strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
                  <Line type="monotone" dataKey="Checked in" stroke={palette.series[1]} strokeWidth={2} dot={false} strokeDasharray="4 3" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>

        <ChartCard title="By status" description="All visits on record">
          {isLoading ? <Skeleton className="h-64 w-full" /> : statusData.length === 0 ? <EmptyState title="No data yet" className="py-10" /> : (
            <div className="flex h-64 flex-col">
              <div className="h-36">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={statusData} dataKey="value" nameKey="name" innerRadius={42} outerRadius={64} paddingAngle={2} stroke="none">
                      {statusData.map((d) => <Cell key={d.status} fill={d.color} />)}
                    </Pie>
                    <Tooltip content={<ChartTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              <ul className="mt-2 flex-1 space-y-1 overflow-y-auto text-xs">
                {statusData.map((d) => (
                  <li key={d.status} className="flex items-center gap-2">
                    <StatusChip status={d.status as VisitStatus} size="sm" />
                    <span className="ml-auto tabular-nums text-muted-foreground">
                      {d.value} · {totalStatus ? Math.round((d.value / totalStatus) * 100) : 0}%
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Peak arrival hours" description="Expected arrival time · last 30 days">
          {isLoading ? <Skeleton className="h-56 w-full" /> : peak.every((p) => p.Visits === 0) ? <EmptyState title="No data yet" className="py-8" /> : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={peak} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke={palette.grid} vertical={false} />
                  <XAxis dataKey="hour" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(h) => `${h}h`} />
                  <YAxis tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip labelFormatter={(l) => `${l}:00`} />} cursor={{ fill: palette.grid }} />
                  <Bar dataKey="Visits" radius={[6, 6, 0, 0]} fill={palette.series[2]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>

        <ChartCard title="Visits by department" description="Based on the host's department">
          {isLoading ? <Skeleton className="h-56 w-full" /> : depts.length === 0 ? (
            <EmptyState title="No department data" description="Assign hosts to departments in Settings to see this breakdown." className="py-8" />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={depts} layout="vertical" margin={{ top: 0, right: 12, left: 8, bottom: 0 }}>
                  <CartesianGrid stroke={palette.grid} horizontal={false} />
                  <XAxis type="number" tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={90} tick={{ fill: palette.tick, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: palette.grid }} />
                  <Bar dataKey="Visits" radius={[0, 6, 6, 0]} fill={palette.series[3]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </ChartCard>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm"><FileBarChart2 className="size-4 text-accent" /> Raw exports</CardTitle>
          <CardDescription>Spreadsheet-ready CSV of the full visit log with visitor, host, department, building, timestamps and duration. Cells are formula-safe.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2 pt-0">
          {(Object.keys(PERIOD_LABELS) as ExportPeriod[]).map((p) => (
            <Button key={p} variant="outline" size="sm" disabled={exporting} onClick={() => { setPeriod(p); void exportReportsCsv(p).catch((e) => toast.error("Export failed", { description: formatApiError(e) })) }}>
              <Download className="size-3.5" /> {PERIOD_LABELS[p]}
            </Button>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
