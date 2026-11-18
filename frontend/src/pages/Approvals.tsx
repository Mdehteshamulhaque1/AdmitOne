import { useState } from "react"
import { toast } from "sonner"
import { Ban, CheckCircle2, ClipboardCheck, Clock3, Mail, MessageSquareText, Phone, XCircle } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Skeleton } from "@/components/ui/Skeleton"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { StatusChip } from "@/components/widgets/StatusChip"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { useApproveVisit, useRejectVisit, useVisitList, useVisits } from "@/lib/queries"
import { VISIT_SOURCE_LABELS, formatApiError, type Visit } from "@/lib/types"
import { formatClock, formatDate, formatRelative } from "@/lib/utils"

export function ApprovalsPage() {
  const pendingQuery = useVisitList({ status: "PENDING", ordering: "visit_date", page_size: 100 }, { refetchInterval: 30_000 })
  const recentQuery = useVisits({ status: "APPROVED,REJECTED,CANCELLED", page_size: 8 })
  const pending = pendingQuery.data
  const recent = recentQuery.data?.results ?? []

  const [rejecting, setRejecting] = useState<Visit | null>(null)
  const [selected, setSelected] = useState<Visit | null>(null)
  const [actingId, setActingId] = useState<number | null>(null)
  const approve = useApproveVisit()
  const reject = useRejectVisit()

  const onApprove = async (v: Visit) => {
    setActingId(v.id)
    try {
      const res = await approve.mutateAsync(v.id)
      toast.success("Visit approved", { description: res.detail })
    } catch (e) {
      toast.error("Approval failed", { description: formatApiError(e) })
    } finally {
      setActingId(null)
    }
  }

  const onReject = async (reason: string) => {
    if (!rejecting) return
    try {
      await reject.mutateAsync({ id: rejecting.id, reason })
      toast.success("Visit rejected")
      setRejecting(null)
    } catch (e) {
      toast.error("Rejection failed", { description: formatApiError(e) })
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Approvals"
        description="Approving a visit issues a signed, single-use QR pass and emails it to the visitor when an address is on file."
        actions={
          <Badge tone="warning" className="gap-1.5">
            <Clock3 className="size-3" /> {pending.length} pending
          </Badge>
        }
      />

      {pendingQuery.isError && <QueryErrorState message="Couldn't load the approval queue." retry={() => void pendingQuery.refetch()} />}

      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Waiting for your decision</h3>
        {pendingQuery.isLoading ? (
          <div className="space-y-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-28 w-full" />)}</div>
        ) : pending.length === 0 ? (
          <div className="card-surface p-6">
            <EmptyState icon={<ClipboardCheck className="size-6" />} title="You're all caught up" description="There are no visits waiting for approval right now." />
          </div>
        ) : (
          <ul className="space-y-3">
            {pending.map((v) => {
              const blocked = v.visitor.is_blacklisted
              return (
                <li key={v.id} className="card-surface overflow-hidden">
                  <div className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
                    <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-11" />
                    <button type="button" onClick={() => setSelected(v)} className="min-w-0 flex-1 text-left">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold hover:text-primary">{v.visitor.full_name}</span>
                        <span className="text-xs text-muted-foreground">{v.visitor.company || "Independent"}</span>
                        <Badge size="sm">{VISIT_SOURCE_LABELS[v.source] ?? v.source}</Badge>
                        {blocked && <Badge tone="danger" size="sm"><Ban className="size-3" /> Blacklisted</Badge>}
                        <span className="text-xs text-muted-foreground">· requested {formatRelative(v.registered_at)}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{v.purpose}</span>
                        <span>{formatDate(v.visit_date)} · {formatClock(v.expected_arrival)}–{formatClock(v.expected_exit)}</span>
                        {v.host_name && <span>Host {v.host_name}</span>}
                        {v.building_name && <span>· {v.building_name}</span>}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                        <span className="inline-flex items-center gap-1"><Phone className="size-3" /> {v.visitor.phone}</span>
                        {v.visitor.email && <span className="inline-flex items-center gap-1"><Mail className="size-3" /> {v.visitor.email}</span>}
                        {v.notes && <span className="inline-flex items-center gap-1 italic"><MessageSquareText className="size-3" /> {v.notes}</span>}
                      </div>
                    </button>
                    <div className="flex shrink-0 gap-2">
                      <Button
                        variant="outline"
                        className="border-danger/30 text-danger hover:bg-danger-soft"
                        onClick={() => setRejecting(v)}
                        disabled={reject.isPending || actingId === v.id}
                      >
                        <XCircle className="size-4" /> Reject
                      </Button>
                      <Button
                        className="min-w-28"
                        onClick={() => onApprove(v)}
                        disabled={blocked || (approve.isPending && actingId !== v.id)}
                        loading={actingId === v.id}
                        title={blocked ? "Blacklisted visitors cannot be approved" : undefined}
                      >
                        <CheckCircle2 className="size-4" /> Approve
                      </Button>
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section>
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Recent decisions</h3>
        {recentQuery.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">No past decisions yet.</p>
        ) : (
          <div className="card-surface overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wider text-muted-foreground">
                  <th className="px-4 py-3">Visitor</th>
                  <th className="px-4 py-3">Purpose</th>
                  <th className="px-4 py-3">Visit date</th>
                  <th className="px-4 py-3">Decision</th>
                  <th className="px-4 py-3">Note</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((v) => (
                  <tr key={v.id} className="cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-hover" onClick={() => setSelected(v)}>
                    <td className="px-4 py-3 font-medium">{v.visitor.full_name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{v.purpose}</td>
                    <td className="px-4 py-3 text-muted-foreground">{formatDate(v.visit_date)}</td>
                    <td className="px-4 py-3"><StatusChip status={v.status} /></td>
                    <td className="max-w-[16rem] truncate px-4 py-3 text-xs italic text-muted-foreground">{v.rejection_reason || v.cancelled_reason || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={rejecting !== null}
        onOpenChange={(o) => !o && setRejecting(null)}
        title="Reject this visit?"
        description={rejecting ? `${rejecting.visitor.full_name}'s visit on ${formatDate(rejecting.visit_date)} at ${formatClock(rejecting.expected_arrival)}.` : undefined}
        confirmLabel="Confirm rejection"
        tone="danger"
        reasonLabel="Reason (optional, kept in the audit trail)"
        reasonPlaceholder="e.g. Host unavailable that day"
        loading={reject.isPending}
        onConfirm={onReject}
      />
      <VisitDrawer visitId={selected?.id ?? null} initial={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
