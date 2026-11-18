import { useMemo, useState } from "react"
import { toast } from "sonner"
import { Download, ScrollText, X } from "lucide-react"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { PageHeader } from "@/components/widgets/PageHeader"
import { Pagination } from "@/components/widgets/Pagination"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { exportAuditCsv, useAuditActions, useAuditLogs } from "@/lib/queries"
import { formatApiError, type AuditLogEntry } from "@/lib/types"
import { cn, formatDateTime } from "@/lib/utils"

const PAGE_SIZE = 25

function actionTone(action: string): "success" | "danger" | "warning" | "info" | "neutral" {
  const a = action.toLowerCase()
  if (/reject|blacklist|denied|failed|deactivat|deleted|cancel/.test(a) && !/un-blacklist/.test(a)) return "danger"
  if (/approved|checked in|created|added|un-blacklist|re-issued/.test(a)) return "success"
  if (/checked out|archived|updated|changed|reset/.test(a)) return "info"
  if (/scan/.test(a)) return "warning"
  return "neutral"
}

export function AuditLogPage() {
  const [q, setQ] = useState("")
  const [action, setAction] = useState("")
  const [dateFrom, setDateFrom] = useState("")
  const [dateTo, setDateTo] = useState("")
  const [page, setPage] = useState(1)
  const [exporting, setExporting] = useState(false)

  const params = useMemo(
    () => ({ q, action, date_from: dateFrom, date_to: dateTo, page, page_size: PAGE_SIZE }),
    [q, action, dateFrom, dateTo, page],
  )
  const { data, isLoading, isError, isFetching, refetch } = useAuditLogs(params)
  const actions = useAuditActions()
  const hasFilters = Boolean(q || action || dateFrom || dateTo)

  const reset = () => {
    setQ("")
    setAction("")
    setDateFrom("")
    setDateTo("")
    setPage(1)
  }

  const onExport = async () => {
    setExporting(true)
    try {
      await exportAuditCsv({ q, action, date_from: dateFrom, date_to: dateTo })
      toast.success("Export ready", { description: "The CSV download has started." })
    } catch (e) {
      toast.error("Export failed", { description: formatApiError(e) })
    } finally {
      setExporting(false)
    }
  }

  const rows: AuditLogEntry[] = data?.results ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Audit log"
        description="Append-only record of every meaningful action in your workspace: who did what, to which record, from where."
        actions={
          <Button variant="outline" onClick={onExport} loading={exporting}>
            <Download className="size-4" /> Export CSV
          </Button>
        }
      />
      {isError && <QueryErrorState message="Couldn't load the audit log." retry={() => void refetch()} />}

      <div className="card-surface grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
        <SearchInput value={q} onChange={(v) => { setQ(v); setPage(1) }} placeholder="Search details, entity or actor…" className="lg:col-span-2" />
        <Select value={action || "all"} onValueChange={(v) => { setAction(v === "all" ? "" : v); setPage(1) }}>
          <SelectTrigger><SelectValue placeholder="Any action" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Any action</SelectItem>
            {(actions.data ?? []).map((a) => (
              <SelectItem key={a} value={a}>{a}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input type="date" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setPage(1) }} aria-label="From date" />
        <div className="flex gap-2">
          <Input type="date" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setPage(1) }} aria-label="To date" />
          {hasFilters && (
            <Button variant="ghost" size="icon" onClick={reset} aria-label="Clear filters">
              <X className="size-4" />
            </Button>
          )}
        </div>
      </div>

      <div className="card-surface overflow-hidden">
        {isLoading ? (
          <div className="space-y-3 p-5">{[...Array(8)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState icon={<ScrollText className="size-6" />} title={hasFilters ? "No entries match" : "No activity recorded yet"} description={hasFilters ? "Try widening the date range." : "Actions will appear here as your team uses AdmitOne."} />
          </div>
        ) : (
          <>
            <ol className="divide-y divide-border">
              {rows.map((entry) => (
                <li key={entry.id} className="flex gap-3 px-4 py-3 sm:gap-4">
                  <div className="w-[7.5rem] shrink-0 pt-0.5 font-mono text-[11px] leading-5 text-muted-foreground">
                    {formatDateTime(entry.created_at)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={actionTone(entry.action)} size="sm">{entry.action}</Badge>
                      {entry.entity_type && (
                        <span className="text-xs text-muted-foreground">
                          {entry.entity_type}
                          {entry.entity_id && <span className="font-mono"> #{entry.entity_id.slice(0, 8)}</span>}
                        </span>
                      )}
                    </div>
                    {entry.details && <p className="mt-1 whitespace-pre-wrap break-words text-sm">{entry.details}</p>}
                    <div className={cn("mt-1 text-xs text-muted-foreground")}>
                      {entry.actor ? `${entry.actor.full_name} · ${entry.actor.role.toLowerCase()}` : "System"}
                      {entry.ip_address && <span className="font-mono"> · {entry.ip_address}</span>}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data?.count ?? 0} onPageChange={setPage} label="entries" isFetching={isFetching} />
          </>
        )}
      </div>
    </div>
  )
}
