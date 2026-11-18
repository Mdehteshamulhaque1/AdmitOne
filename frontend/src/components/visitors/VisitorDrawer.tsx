import { useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"
import {
  Ban,
  Building,
  Calendar,
  Car,
  Clock,
  IdCard,
  Mail,
  MapPin,
  Pencil,
  Phone,
  ShieldCheck,
  Siren,
  UserPlus,
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
import { BlacklistDialog } from "@/components/visitors/BlacklistDialog"
import { VisitorEditDialog } from "@/components/visitors/VisitorEditDialog"
import { useAuth } from "@/lib/auth"
import { useUnblacklistVisitor, useVisitorVisits } from "@/lib/queries"
import { formatApiError, type Visit, type Visitor } from "@/lib/types"
import { formatClock, formatDate, formatDuration } from "@/lib/utils"

function InfoRow({ icon, label, value }: { icon: React.ReactNode; label: string; value?: string }) {
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

export function VisitorDrawer({
  visitor,
  open,
  onOpenChange,
  onOpenVisit,
}: {
  visitor: Visitor | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onOpenVisit?: (visit: Visit) => void
}) {
  const { can, org } = useAuth()
  const visits = useVisitorVisits(open && visitor ? visitor.id : null)
  const unblacklist = useUnblacklistVisitor()
  const [editing, setEditing] = useState(false)
  const [banning, setBanning] = useState(false)
  const [lifting, setLifting] = useState(false)
  const [current, setCurrent] = useState<Visitor | null>(null)

  const v = (current && visitor && current.id === visitor.id ? current : visitor) ?? null
  const list = visits.data ?? []
  const activePassVisit = list.find((x) => x.qr && x.qr.is_valid && (x.status === "APPROVED" || x.status === "CHECKED_IN"))

  const lift = async () => {
    if (!v) return
    try {
      const res = await unblacklist.mutateAsync(v.id)
      toast.success("Blacklist lifted", { description: res.detail })
      setCurrent({ ...v, is_blacklisted: false, blacklist_reason: "" })
      setLifting(false)
    } catch (e) {
      toast.error("Could not lift blacklist", { description: formatApiError(e) })
    }
  }

  return (
    <Drawer open={open} onOpenChange={onOpenChange}>
      <DrawerContent className="max-w-xl">
        <DrawerHeader className="pl-12">
          <DrawerTitle>Visitor profile</DrawerTitle>
          <DrawerDescription>Identity, documents and visit history</DrawerDescription>
        </DrawerHeader>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {v && (
            <div className="space-y-6">
              <div className="flex items-start gap-4">
                <Avatar name={v.full_name} src={v.photo} className="size-16 text-xl" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-lg font-bold tracking-tight">{v.full_name}</h3>
                    {v.is_blacklisted ? (
                      <Badge tone="danger" dot><Ban className="size-3" /> Blacklisted</Badge>
                    ) : (
                      <Badge tone="success" dot>Active</Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {[v.company, v.designation].filter(Boolean).join(" · ") || "Independent visitor"}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {v.visit_count ?? list.length} visit{(v.visit_count ?? list.length) === 1 ? "" : "s"} · since {formatDate(v.created_at)}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                {can("create_visitor") && (
                  <>
                    <Button size="sm" asChild>
                      <Link to={`/dashboard/register-visit?visitor=${v.id}`}>
                        <UserPlus className="size-4" /> New visit
                      </Link>
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                      <Pencil className="size-4" /> Edit
                    </Button>
                  </>
                )}
                {!v.is_blacklisted && can("blacklist_visitor") && (
                  <Button size="sm" variant="outline" className="border-danger/30 text-danger hover:bg-danger-soft" onClick={() => setBanning(true)}>
                    <Ban className="size-4" /> Blacklist
                  </Button>
                )}
                {v.is_blacklisted && can("manage_org") && (
                  <Button size="sm" variant="outline" onClick={() => setLifting(true)}>
                    <ShieldCheck className="size-4" /> Lift blacklist
                  </Button>
                )}
              </div>

              {v.is_blacklisted && (
                <div className="flex items-start gap-3 rounded-xl border border-danger/30 bg-danger-soft p-3 text-sm">
                  <Siren className="mt-0.5 size-4 shrink-0 text-danger" />
                  <div>
                    <div className="font-semibold text-danger">Entry denied</div>
                    <div className="text-xs text-muted-foreground">
                      Reason: {v.blacklist_reason ? v.blacklist_reason.replace(/_/g, " ").toLowerCase() : "not specified"}. Approvals and check-ins are blocked.
                    </div>
                  </div>
                </div>
              )}

              {activePassVisit ? (
                <PassCard visit={activePassVisit} orgName={org?.name ?? "AdmitOne"} compact />
              ) : (
                <div className="rounded-2xl border border-dashed border-border px-4 py-3 text-center text-xs text-muted-foreground">
                  No active QR pass — an approved visit generates one automatically.
                </div>
              )}

              <div>
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Contact & identity</h4>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <InfoRow icon={<Phone className="size-4" />} label="Phone" value={v.phone} />
                  <InfoRow icon={<Mail className="size-4" />} label="Email" value={v.email} />
                  {v.document_type !== undefined && (
                    <InfoRow
                      icon={<IdCard className="size-4" />}
                      label="ID document"
                      value={v.document_type ? `${v.document_type.replace(/_/g, " ")} · ${v.document_number || "no number"}` : ""}
                    />
                  )}
                  <InfoRow icon={<Car className="size-4" />} label="Vehicle" value={[v.vehicle_type, v.vehicle_number].filter(Boolean).join(" ")} />
                  {v.address !== undefined && (
                    <InfoRow icon={<MapPin className="size-4" />} label="Address" value={v.address} />
                  )}
                  {v.emergency_contact !== undefined && (
                    <InfoRow icon={<Siren className="size-4" />} label="Emergency contact" value={[v.emergency_contact, v.emergency_phone].filter(Boolean).join(" · ")} />
                  )}
                </div>
                {v.special_notes && (
                  <div className="mt-3 rounded-xl border border-border bg-surface-2 p-3 text-sm">
                    <div className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Special notes</div>
                    {v.special_notes}
                  </div>
                )}
              </div>

              <Separator />

              <div>
                <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Visit history{visits.data ? ` · ${list.length}` : ""}
                </h4>
                {visits.isLoading ? (
                  <div className="space-y-2">
                    <Skeleton className="h-16 w-full" />
                    <Skeleton className="h-16 w-full" />
                  </div>
                ) : visits.isError ? (
                  <p className="text-sm text-danger">Couldn't load visits.</p>
                ) : list.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
                    No visits recorded yet.
                  </div>
                ) : (
                  <ul className="space-y-2.5">
                    {list.map((visit) => (
                      <li key={visit.id}>
                        <button
                          type="button"
                          onClick={() => onOpenVisit?.(visit)}
                          className="w-full rounded-xl border border-border bg-card p-3.5 text-left transition-colors hover:border-primary/30 hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-sm font-semibold">{visit.purpose}</span>
                            <StatusChip status={visit.status} size="sm" />
                          </div>
                          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            <span className="inline-flex items-center gap-1"><Calendar className="size-3" /> {formatDate(visit.visit_date)}</span>
                            <span className="inline-flex items-center gap-1"><Clock className="size-3" /> {formatClock(visit.expected_arrival)}–{formatClock(visit.expected_exit)}</span>
                            {visit.host_name && (
                              <span className="inline-flex items-center gap-1"><Building className="size-3" /> {visit.host_name}</span>
                            )}
                            {visit.duration_minutes > 0 && (
                              <span className="inline-flex items-center gap-1 text-primary"><Clock className="size-3" /> {formatDuration(visit.duration_minutes)} on site</span>
                            )}
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>

        <VisitorEditDialog visitor={v} open={editing} onOpenChange={setEditing} onSaved={setCurrent} />
        <BlacklistDialog visitor={v} open={banning} onOpenChange={(o) => {
          setBanning(o)
          if (!o && v) setCurrent({ ...v, is_blacklisted: true })
        }} />
        <ConfirmDialog
          open={lifting}
          onOpenChange={setLifting}
          title="Lift the blacklist?"
          description={`${v?.full_name ?? "This visitor"} will be able to be approved and checked in again.`}
          confirmLabel="Lift blacklist"
          loading={unblacklist.isPending}
          onConfirm={lift}
        />
      </DrawerContent>
    </Drawer>
  )
}
