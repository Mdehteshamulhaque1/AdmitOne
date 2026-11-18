import { useState } from "react"
import { toast } from "sonner"
import {
  Ban,
  Building,
  CalendarDays,
  CheckCircle2,
  Clock,
  LogIn,
  LogOut,
  Mail,
  MessageSquareText,
  Phone,
  RefreshCw,
  UserRound,
  XCircle,
} from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/Drawer"
import { Separator } from "@/components/ui/Separator"
import { Skeleton } from "@/components/ui/Skeleton"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { StatusChip } from "@/components/widgets/StatusChip"
import { PassCard } from "@/components/visits/PassCard"
import { useAuth } from "@/lib/auth"
import {
  useApproveVisit,
  useCancelVisit,
  useCheckIn,
  useCheckOut,
  useReissuePass,
  useRejectVisit,
  useVisit,
} from "@/lib/queries"
import { VISIT_SOURCE_LABELS, formatApiError, type Visit } from "@/lib/types"
import { formatClock, formatDate, formatDateTime, formatDuration } from "@/lib/utils"

function Row({ icon, label, value }: { icon: React.ReactNode; label: string; value?: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-surface-2 text-muted-foreground">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="truncate text-sm font-medium">{value || "—"}</div>
      </div>
    </div>
  )
}

function Timeline({ visit }: { visit: Visit }) {
  const steps: { label: string; at: string | null; by?: string; detail?: string; tone: "done" | "danger" | "muted" }[] = [
    { label: "Registered", at: visit.registered_at, by: visit.created_by_name, tone: "done" },
  ]
  if (visit.approved_at) steps.push({ label: "Approved · pass issued", at: visit.approved_at, tone: "done" })
  if (visit.rejected_at) steps.push({ label: "Rejected", at: visit.rejected_at, detail: visit.rejection_reason, tone: "danger" })
  if (visit.arriving_at) steps.push({ label: "Visitor announced arrival", at: visit.arriving_at, tone: "muted" })
  if (visit.checked_in_at) steps.push({ label: "Checked in", at: visit.checked_in_at, by: visit.checked_in_by_name, tone: "done" })
  if (visit.checked_out_at) steps.push({ label: "Checked out", at: visit.checked_out_at, by: visit.checked_out_by_name, tone: "done" })
  if (visit.cancelled_at) steps.push({ label: "Cancelled", at: visit.cancelled_at, detail: visit.cancelled_reason, tone: "danger" })
  return (
    <ol className="relative space-y-4 border-l border-border pl-5">
      {steps.map((s, i) => (
        <li key={i} className="relative">
          <span
            className={`absolute -left-[26px] top-1 size-3 rounded-full ring-4 ring-card ${
              s.tone === "danger" ? "bg-danger" : s.tone === "muted" ? "bg-accent" : "bg-primary"
            }`}
          />
          <div className="text-sm font-medium">{s.label}</div>
          <div className="text-xs text-muted-foreground">
            {formatDateTime(s.at)}
            {s.by ? ` · by ${s.by}` : ""}
          </div>
          {s.detail && <div className="mt-1 text-xs italic text-muted-foreground">“{s.detail}”</div>}
        </li>
      ))}
    </ol>
  )
}

export function VisitDrawer({
  visitId,
  initial,
  open,
  onOpenChange,
}: {
  visitId: number | null
  initial?: Visit | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { can, org } = useAuth()
  const query = useVisit(open ? visitId : null)
  const visit = query.data ?? initial ?? null

  const approve = useApproveVisit()
  const reject = useRejectVisit()
  const checkIn = useCheckIn()
  const checkOut = useCheckOut()
  const reissue = useReissuePass()
  const cancel = useCancelVisit()
  const [confirm, setConfirm] = useState<"reject" | "cancel" | "checkin" | null>(null)

  const run = async (label: string, fn: () => Promise<{ detail: string }>) => {
    try {
      const res = await fn()
      toast.success(label, { description: res.detail })
      setConfirm(null)
    } catch (e) {
      toast.error(`${label} failed`, { description: formatApiError(e) })
    }
  }

  const busy = approve.isPending || reject.isPending || checkIn.isPending || checkOut.isPending || reissue.isPending || cancel.isPending

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent className="max-w-xl">
        <DrawerHeader className="pl-12">
          <DrawerTitle>Visit details</DrawerTitle>
          <DrawerDescription>
            {visit ? `Ref ${visit.visit_id.slice(0, 8).toUpperCase()} · ${VISIT_SOURCE_LABELS[visit.source] ?? visit.source}` : "Loading…"}
          </DrawerDescription>
        </DrawerHeader>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {!visit ? (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-40 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex items-start gap-4">
                <Avatar name={visit.visitor.full_name} src={visit.visitor.photo} className="size-14 text-lg" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-bold tracking-tight">{visit.visitor.full_name}</h3>
                    <StatusChip status={visit.status} />
                    {visit.visitor.is_blacklisted && (
                      <Badge tone="danger" dot><Ban className="size-3" /> Blacklisted</Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {[visit.visitor.company, visit.visitor.designation].filter(Boolean).join(" · ") || "Independent visitor"}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <span className="inline-flex items-center gap-1"><Phone className="size-3" /> {visit.visitor.phone}</span>
                    {visit.visitor.email && (
                      <span className="inline-flex items-center gap-1"><Mail className="size-3" /> {visit.visitor.email}</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex flex-wrap gap-2">
                {visit.status === "PENDING" && can("approve_visitor") && (
                  <>
                    <Button size="sm" disabled={busy} loading={approve.isPending} onClick={() => run("Visit approved", () => approve.mutateAsync(visit.id))}>
                      <CheckCircle2 className="size-4" /> Approve
                    </Button>
                    <Button size="sm" variant="outline" className="border-danger/30 text-danger hover:bg-danger-soft" disabled={busy} onClick={() => setConfirm("reject")}>
                      <XCircle className="size-4" /> Reject
                    </Button>
                  </>
                )}
                {visit.status === "APPROVED" && can("checkin_visitor") && (
                  <Button size="sm" disabled={busy} onClick={() => setConfirm("checkin")}>
                    <LogIn className="size-4" /> Manual check-in
                  </Button>
                )}
                {visit.status === "CHECKED_IN" && can("checkout_visitor") && (
                  <Button size="sm" disabled={busy} loading={checkOut.isPending} onClick={() => run("Visitor checked out", () => checkOut.mutateAsync(visit.id))}>
                    <LogOut className="size-4" /> Check out
                  </Button>
                )}
                {visit.status === "APPROVED" && visit.qr && !visit.qr.is_valid && can("approve_visitor") && (
                  <Button size="sm" variant="secondary" disabled={busy} loading={reissue.isPending} onClick={() => run("Pass re-issued", () => reissue.mutateAsync(visit.id))}>
                    <RefreshCw className="size-4" /> Re-issue pass
                  </Button>
                )}
                {(visit.status === "PENDING" || visit.status === "APPROVED") && (can("approve_visitor") || can("create_visitor")) && (
                  <Button size="sm" variant="ghost" className="text-muted-foreground hover:text-danger" disabled={busy} onClick={() => setConfirm("cancel")}>
                    Cancel visit
                  </Button>
                )}
              </div>

              {(visit.status === "APPROVED" || visit.status === "CHECKED_IN") && (
                <PassCard visit={visit} orgName={org?.name ?? "AdmitOne"} />
              )}

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Row icon={<MessageSquareText className="size-4" />} label="Purpose" value={visit.purpose} />
                <Row icon={<CalendarDays className="size-4" />} label="Visit date" value={formatDate(visit.visit_date)} />
                <Row icon={<Clock className="size-4" />} label="Expected window" value={`${formatClock(visit.expected_arrival)} – ${formatClock(visit.expected_exit)}`} />
                <Row icon={<UserRound className="size-4" />} label="Host" value={visit.host_name} />
                <Row icon={<Building className="size-4" />} label="Building" value={visit.building_name} />
                <Row icon={<Clock className="size-4" />} label="Time on site" value={formatDuration(visit.duration_minutes)} />
              </div>
              {visit.notes && (
                <div className="rounded-xl border border-border bg-surface-2 p-3 text-sm">
                  <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Notes for staff</div>
                  {visit.notes}
                </div>
              )}

              <Separator />
              <div>
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Timeline</h4>
                <Timeline visit={visit} />
              </div>
            </div>
          )}
        </div>

        {visit && (
          <>
            <ConfirmDialog
              open={confirm === "reject"}
              onOpenChange={(o) => !o && setConfirm(null)}
              title="Reject this visit?"
              description={`${visit.visitor.full_name} will be notified that the visit on ${formatDate(visit.visit_date)} was declined.`}
              confirmLabel="Reject visit"
              tone="danger"
              reasonLabel="Reason (shared in the audit trail)"
              reasonPlaceholder="e.g. Host unavailable that day"
              loading={reject.isPending}
              onConfirm={(reason) => run("Visit rejected", () => reject.mutateAsync({ id: visit.id, reason }))}
            />
            <ConfirmDialog
              open={confirm === "cancel"}
              onOpenChange={(o) => !o && setConfirm(null)}
              title="Cancel this visit?"
              description="The visit is kept in history as cancelled and any issued QR pass stops working immediately."
              confirmLabel="Cancel visit"
              tone="danger"
              reasonLabel="Reason"
              reasonMaxLength={120}
              loading={cancel.isPending}
              onConfirm={(reason) => run("Visit cancelled", () => cancel.mutateAsync({ id: visit.id, reason }))}
            />
            <ConfirmDialog
              open={confirm === "checkin"}
              onOpenChange={(o) => !o && setConfirm(null)}
              title="Check in without scanning?"
              description="Use this only when the visitor cannot present their pass. The entry is logged against your account."
              confirmLabel="Check in"
              loading={checkIn.isPending}
              onConfirm={() => run("Visitor checked in", () => checkIn.mutateAsync(visit.id))}
            />
          </>
        )}
      </DrawerContent>
    </Drawer>
  )
}
