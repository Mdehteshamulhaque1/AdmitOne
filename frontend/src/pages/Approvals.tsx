import { useMemo, useState } from "react"
import { toast } from "sonner"
import { Ban, CheckCircle2, ClipboardCheck, DoorOpen, IdCard, Mail, MessageSquareText, Phone, UserRound, XCircle } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Skeleton } from "@/components/ui/Skeleton"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { StatusChip } from "@/components/widgets/StatusChip"
import { AssignRoomDialog } from "@/components/visits/AssignRoomDialog"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { ID_PROOFS, maskId } from "@/components/visitor/booking"
import { categoryLabel } from "@/lib/student-options"
import { useApproveVisit, useRejectVisit, useVisitList, useVisits } from "@/lib/queries"
import { VISIT_SOURCE_LABELS, formatApiError, type Visit } from "@/lib/types"
import { cn, formatClock, formatDate, formatRelative, todayIso } from "@/lib/utils"

type Tab = "today" | "upcoming" | "overdue"

const TABS: { key: Tab; label: string; empty: string }[] = [
  { key: "today", label: "Today", empty: "No requests for today are waiting." },
  { key: "upcoming", label: "Upcoming", empty: "No requests for later dates are waiting." },
  { key: "overdue", label: "Past due", empty: "Nothing is past its visit date." },
]

/** Day + date block on the left of each request: the first thing reception scans for. */
function WhenBlock({ v }: { v: Visit }) {
  const d = new Date(`${v.visit_date}T12:00:00`)
  return (
    <div className="flex w-full shrink-0 items-center gap-3 sm:w-20 sm:flex-col sm:items-start sm:gap-0">
      <div className="text-xs font-medium text-muted-foreground">{d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}</div>
      <div className="text-lg font-semibold tabular-nums leading-tight">{formatClock(v.expected_arrival)}</div>
      <div className="text-xs text-muted-foreground tabular-nums">to {formatClock(v.expected_exit)}</div>
    </div>
  )
}

function RequestCard({
  v,
  busy,
  onOpen,
  onApprove,
  onDecline,
}: {
  v: Visit
  busy: boolean
  onOpen: () => void
  onApprove: () => void
  onDecline: () => void
}) {
  const blocked = v.visitor.is_blacklisted
  const profile = [v.visitor.qualification, v.visitor.passing_year ? `batch ${v.visitor.passing_year}` : "", v.visitor.university].filter(Boolean).join(", ")
  return (
    <li className="rounded-2xl border border-border bg-card shadow-card">
      <div className="flex flex-col gap-4 p-4 sm:flex-row sm:p-5">
        <WhenBlock v={v} />
        <div className="hidden w-px self-stretch bg-border sm:block" aria-hidden="true" />
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
          <div className="flex items-center gap-3">
            <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-12 rounded-xl" />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold hover:text-primary">{v.visitor.full_name}</span>
                {blocked && <Badge tone="danger" size="sm"><Ban className="size-3" /> Blacklisted</Badge>}
              </div>
              <div className="truncate text-xs text-muted-foreground">
                {[v.visitor_category ? categoryLabel(v.visitor_category) : v.visitor.company || "Visitor", profile].filter(Boolean).join(" · ")}
              </div>
            </div>
          </div>
          <div className="mt-3 text-sm">
            <span className="font-medium">{v.purpose}</span>
            <span className="text-muted-foreground">{v.host_name ? ` · meeting ${v.host_name}` : ""}</span>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1"><Phone className="size-3" /> {v.visitor.phone}</span>
            {v.visitor.email && <span className="inline-flex items-center gap-1"><Mail className="size-3" /> {v.visitor.email}</span>}
            <span>{VISIT_SOURCE_LABELS[v.source] ?? v.source}, {formatRelative(v.registered_at)}</span>
            {v.visitor.document_type && (
              <span className="inline-flex items-center gap-1">
                <IdCard className="size-3" /> {ID_PROOFS.find((p) => p.value === v.visitor.document_type)?.label ?? v.visitor.document_type}
                {v.visitor.document_number ? <span className="font-mono">{maskId(v.visitor.document_number)}</span> : null}
              </span>
            )}
            {v.room_label && <span className="inline-flex items-center gap-1 text-primary"><DoorOpen className="size-3" /> {v.room_label}</span>}
          </div>
          {v.notes && (
            <p className="mt-2 inline-flex items-start gap-1.5 rounded-lg bg-secondary px-2.5 py-1.5 text-xs">
              <MessageSquareText className="mt-0.5 size-3 shrink-0 text-muted-foreground" /> {v.notes}
            </p>
          )}
        </button>
        <div className="flex shrink-0 gap-2 sm:flex-col sm:justify-center">
          <Button
            className="flex-1 sm:min-w-44"
            onClick={onApprove}
            disabled={blocked || busy}
            title={blocked ? "Blacklisted visitors cannot be approved" : undefined}
          >
            <CheckCircle2 className="size-4" /> Approve & assign room
          </Button>
          <Button variant="outline" className="flex-1 text-danger hover:bg-danger-soft" onClick={onDecline} disabled={busy}>
            <XCircle className="size-4" /> Decline
          </Button>
        </div>
      </div>
    </li>
  )
}

export function ApprovalsPage() {
  const pendingQuery = useVisitList({ status: "PENDING", ordering: "visit_date", page_size: 100 }, { refetchInterval: 30_000 })
  const recentQuery = useVisits({ status: "APPROVED,REJECTED,CANCELLED", page_size: 8 })
  const recent = recentQuery.data?.results ?? []

  const [rejecting, setRejecting] = useState<Visit | null>(null)
  const [approving, setApproving] = useState<Visit | null>(null)
  const [selected, setSelected] = useState<Visit | null>(null)
  const approve = useApproveVisit()
  const reject = useRejectVisit()

  const today = todayIso()
  const groups = useMemo(() => {
    const sorted = [...pendingQuery.data].sort((a, b) => `${a.visit_date}${a.expected_arrival}`.localeCompare(`${b.visit_date}${b.expected_arrival}`))
    return {
      today: sorted.filter((v) => v.visit_date === today),
      upcoming: sorted.filter((v) => v.visit_date > today),
      overdue: sorted.filter((v) => v.visit_date < today),
    }
  }, [pendingQuery.data, today])
  const firstWithItems = TABS.find((t) => groups[t.key].length > 0)?.key ?? "today"
  const [tab, setTab] = useState<Tab | null>(null)
  const current = tab ?? firstWithItems
  const list = groups[current]
  const total = pendingQuery.data.length

  // Approval goes through the room picker: staff send the visitor to the right
  // room (lab, interview cabin, placement hall...) in the same step.
  const onApprove = async (v: Visit, room: number | null) => {
    try {
      const res = await approve.mutateAsync({ id: v.id, room })
      toast.success(`${v.visitor.full_name} approved`, { description: res.detail })
      setApproving(null)
    } catch (e) {
      toast.error("Approval failed", { description: formatApiError(e) })
    }
  }

  const onReject = async (reason: string) => {
    if (!rejecting) return
    try {
      await reject.mutateAsync({ id: rejecting.id, reason })
      toast.success(`${rejecting.visitor.full_name}'s request declined`)
      setRejecting(null)
    } catch (e) {
      toast.error("Couldn't decline the request", { description: formatApiError(e) })
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Approvals"
        description={total === 0 ? "No visit requests are waiting for a decision." : `${total} visit request${total === 1 ? "" : "s"} waiting for a decision. Approving issues a single-use QR pass and emails it to the visitor.`}
      />

      {pendingQuery.isError && <QueryErrorState message="The approval queue didn't load." retry={() => void pendingQuery.refetch()} />}

      <div role="tablist" aria-label="Requests" className="inline-flex rounded-xl border border-border bg-card p-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={current === t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors",
              current === t.key ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
            <span className={cn("rounded-full px-1.5 text-xs tabular-nums", current === t.key ? "bg-white/20" : t.key === "overdue" && groups.overdue.length ? "bg-warning-soft text-warning" : "bg-secondary")}>
              {groups[t.key].length}
            </span>
          </button>
        ))}
      </div>

      {pendingQuery.isLoading ? (
        <div className="space-y-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-36 w-full rounded-2xl" />)}</div>
      ) : list.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card p-6">
          <EmptyState
            icon={<ClipboardCheck className="size-6" />}
            title={total === 0 ? "You're all caught up" : TABS.find((t) => t.key === current)!.empty}
            description={total === 0 ? "New requests from visitors and reception appear here." : "Check the other tabs for requests on other days."}
          />
        </div>
      ) : (
        <>
          {current === "overdue" && (
            <p className="text-sm text-warning">These visit dates have passed. Decline them, or approve if the visit is still happening.</p>
          )}
          <ul className="space-y-3">
            {list.map((v) => (
              <RequestCard
                key={v.id}
                v={v}
                busy={approve.isPending || reject.isPending}
                onOpen={() => setSelected(v)}
                onApprove={() => setApproving(v)}
                onDecline={() => setRejecting(v)}
              />
            ))}
          </ul>
        </>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold">Recent decisions</h2>
        {recentQuery.isLoading ? (
          <Skeleton className="h-40 w-full rounded-2xl" />
        ) : recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">Decisions you make appear here.</p>
        ) : (
          <ul className="divide-y divide-border rounded-2xl border border-border bg-card">
            {recent.map((v) => (
              <li key={v.id}>
                <button type="button" onClick={() => setSelected(v)} className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-hover">
                  <UserRound className="size-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">{v.visitor.full_name}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {v.purpose} · {formatDate(v.visit_date)}{v.rejection_reason || v.cancelled_reason ? ` · “${v.rejection_reason || v.cancelled_reason}”` : ""}
                    </div>
                  </div>
                  <StatusChip status={v.status} size="sm" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <ConfirmDialog
        open={rejecting !== null}
        onOpenChange={(o) => !o && setRejecting(null)}
        title="Decline this request?"
        description={rejecting ? `${rejecting.visitor.full_name}'s visit on ${formatDate(rejecting.visit_date)} at ${formatClock(rejecting.expected_arrival)}. The visitor sees your reason.` : undefined}
        confirmLabel="Decline request"
        tone="danger"
        reasonLabel="Reason (optional, kept in the audit trail)"
        reasonPlaceholder="e.g. Host unavailable that day"
        loading={reject.isPending}
        onConfirm={onReject}
      />
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
