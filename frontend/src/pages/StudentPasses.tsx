import { useMemo, useRef, useState } from "react"
import { QRCodeCanvas } from "qrcode.react"
import { toast } from "sonner"
import { Ban, CalendarClock, GraduationCap, LogIn, LogOut, Mail, MessageCircle, Plus, Printer, RefreshCcw, Users } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Button } from "@/components/ui/Button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input } from "@/components/ui/Input"
import { Skeleton } from "@/components/ui/Skeleton"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { Chip } from "@/components/widgets/Choice"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { IssuePassDialog } from "@/components/students/IssuePassDialog"
import { StudentPassCard } from "@/components/students/StudentPassCard"
import { ID_PROOFS, maskId } from "@/components/visitor/booking"
import { useAuth } from "@/lib/auth"
import { useStudentAttendance, useStudentPass, useStudentPassMutations, useStudentPasses } from "@/lib/queries"
import { formatApiError, type StudentPass } from "@/lib/types"
import { cn, formatDate, formatDateTime, todayIso } from "@/lib/utils"

const FILTERS = [
  { key: "", label: "All" },
  { key: "ACTIVE", label: "Active" },
  { key: "EXPIRING", label: "Expiring soon" },
  { key: "EXPIRED", label: "Expired" },
  { key: "REVOKED", label: "Revoked" },
] as const

const STATUS_CHIP: Record<string, string> = {
  ACTIVE: "bg-success-soft text-success",
  UPCOMING: "bg-info-soft text-info",
  EXPIRED: "bg-warning-soft text-warning",
  REVOKED: "bg-danger-soft text-danger",
}

function StatusPill({ sp }: { sp: StudentPass }) {
  const label = sp.status === "ACTIVE" && sp.days_left <= 15 ? `${sp.days_left} days left` : sp.status.charAt(0) + sp.status.slice(1).toLowerCase()
  return <span className={cn("rounded-full px-2.5 py-0.5 text-xs font-semibold", sp.status === "ACTIVE" && sp.days_left <= 15 ? "bg-warning-soft text-warning" : STATUS_CHIP[sp.status])}>{label}</span>
}

function Tile({ label, value, icon, tone, active, onClick }: { label: string; value?: number; icon: React.ReactNode; tone: string; active?: boolean; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className={cn("flex items-center gap-3 rounded-2xl border bg-card p-4 text-left shadow-card transition", active ? "border-primary ring-1 ring-primary" : "border-border hover:border-primary/50")}>
      <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", tone)}>{icon}</span>
      <span>
        <span className="block text-xl font-semibold tabular-nums">{value ?? "—"}</span>
        <span className="block text-xs text-muted-foreground">{label}</span>
      </span>
    </button>
  )
}

/** Detail view: the ID card, actions and the last scans. */
function PassDetail({ id, orgName, onClose }: { id: number | null; orgName: string; onClose: () => void }) {
  const pass = useStudentPass(id)
  const { renew, revoke, sendEmail } = useStudentPassMutations()
  const [revoking, setRevoking] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const sp = pass.data

  const message = sp
    ? [`${orgName} student pass`, `${sp.student.full_name} (${sp.admission_number})`, `${sp.course}${sp.batch ? `, ${sp.batch}` : ""}`,
       `Valid ${formatDate(sp.valid_from)} to ${formatDate(sp.valid_until)}`, "Show the QR code at the gate when you arrive and leave."].join("\n")
    : ""

  const print = () => {
    if (!sp) return
    const qr = canvasRef.current?.toDataURL("image/png") ?? ""
    const w = window.open("", "_blank", "width=480,height=640")
    if (!w) return toast.error("Allow pop-ups to print the ID card.")
    const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
    w.document.write(`<!doctype html><html><head><title>${esc(sp.admission_number)}</title><style>
      body{font-family:Segoe UI,Arial,sans-serif;margin:24px} .card{width:340px;border:2px solid #1d2330;border-radius:14px;overflow:hidden}
      .top{background:#1d2330;color:#fff;padding:12px 16px;font-weight:700} .body{display:flex;gap:12px;padding:14px 16px}
      .photo{width:84px;height:104px;object-fit:cover;border-radius:8px;background:#eee} h2{margin:0 0 4px;font-size:18px} p{margin:2px 0;font-size:13px;color:#333}
      .qr{display:flex;gap:12px;align-items:center;padding:0 16px 16px} .qr img{width:120px;height:120px} .small{font-size:11px;color:#555}</style></head><body>
      <div class="card"><div class="top">${esc(orgName)} &middot; Student pass</div>
      <div class="body">${sp.student.photo ? `<img class="photo" src="${esc(sp.student.photo)}">` : '<div class="photo"></div>'}
      <div><h2>${esc(sp.student.full_name)}</h2><p><b>${esc(sp.admission_number)}</b></p><p>${esc(sp.course)}${sp.batch ? " &middot; " + esc(sp.batch) : ""}</p><p>${esc(sp.student.phone)}</p></div></div>
      <div class="qr"><img src="${qr}"><div><p class="small">Valid from</p><p><b>${esc(formatDate(sp.valid_from))}</b></p><p class="small">Valid until</p><p><b>${esc(formatDate(sp.valid_until))}</b></p></div></div></div>
      <script>window.onload=function(){window.print()}<\/script></body></html>`)
    w.document.close()
  }

  const doRenew = async () => {
    if (!sp) return
    try {
      const res = await renew.mutateAsync(sp.id)
      toast.success("Pass renewed", { description: res.detail })
    } catch (e) {
      toast.error("Renewal failed", { description: formatApiError(e) })
    }
  }
  const doRevoke = async (reason: string) => {
    if (!sp) return
    try {
      const res = await revoke.mutateAsync({ id: sp.id, reason })
      toast.success("Pass revoked", { description: res.detail })
      setRevoking(false)
    } catch (e) {
      toast.error("Couldn't revoke the pass", { description: formatApiError(e) })
    }
  }
  const doEmail = async () => {
    if (!sp) return
    try {
      const res = await sendEmail.mutateAsync(sp.id)
      toast.success(res.detail)
    } catch (e) {
      toast.error("Email not sent", { description: formatApiError(e) })
    }
  }

  return (
    <Dialog open={id !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Student pass</DialogTitle>
          <DialogDescription>{sp ? `Issued ${formatDate(sp.issued_at)}${sp.issued_by_name ? ` by ${sp.issued_by_name}` : ""}${sp.renewed_count ? `, renewed ${sp.renewed_count}×` : ""}.` : ""}</DialogDescription>
        </DialogHeader>
        {pass.isLoading || !sp ? (
          <Skeleton className="h-72 w-full" />
        ) : (
          <div className="grid gap-6 md:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
            <div className="space-y-3">
              <StudentPassCard sp={sp} orgName={orgName} />
              {sp.payload && <QRCodeCanvas ref={canvasRef} value={sp.payload} size={480} marginSize={2} className="hidden" aria-hidden="true" />}
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" onClick={print} disabled={!sp.payload}><Printer className="size-4" /> Print ID card</Button>
                <Button variant="outline" onClick={() => void doEmail()} loading={sendEmail.isPending} disabled={!sp.student.email}><Mail className="size-4" /> Email pass</Button>
                <Button variant="outline" className="col-span-2" onClick={() => window.open(`https://wa.me/${sp.student.phone.replace(/\D/g, "").replace(/^(\d{10})$/, "91$1")}?text=${encodeURIComponent(message)}`, "_blank", "noopener,noreferrer")}>
                  <MessageCircle className="size-4" /> Send details on WhatsApp
                </Button>
              </div>
            </div>
            <div className="space-y-5">
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div><dt className="text-xs text-muted-foreground">Status</dt><dd className="mt-1"><StatusPill sp={sp} /></dd></div>
                <div><dt className="text-xs text-muted-foreground">Today</dt><dd className="mt-1 font-medium">{sp.today ? `${sp.today.direction} at ${new Date(sp.today.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Not scanned yet"}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Email</dt><dd className="mt-1 truncate font-medium">{sp.student.email || "—"}</dd></div>
                <div><dt className="text-xs text-muted-foreground">ID proof</dt><dd className="mt-1 font-medium">{sp.student.document_type ? `${ID_PROOFS.find((p) => p.value === sp.student.document_type)?.label ?? sp.student.document_type} ${maskId(sp.student.document_number ?? "")}` : "—"}</dd></div>
                {sp.revoked_reason && <div className="col-span-2"><dt className="text-xs text-muted-foreground">Revoked because</dt><dd className="mt-1 font-medium text-danger">{sp.revoked_reason}</dd></div>}
              </dl>
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => void doRenew()} loading={renew.isPending}><RefreshCcw className="size-4" /> Renew 6 months</Button>
                {sp.status !== "REVOKED" && <Button variant="outline" className="text-danger hover:bg-danger-soft" onClick={() => setRevoking(true)}><Ban className="size-4" /> Revoke</Button>}
              </div>
              <div>
                <h3 className="mb-2 text-sm font-semibold">Recent gate scans</h3>
                {(sp.recent_scans ?? []).length === 0 ? (
                  <p className="text-sm text-muted-foreground">No scans yet.</p>
                ) : (
                  <ul className="divide-y divide-border rounded-xl border border-border text-sm">
                    {sp.recent_scans!.map((s) => (
                      <li key={s.id} className="flex items-center gap-3 px-3 py-2">
                        {s.direction === "IN" ? <LogIn className="size-4 text-success" /> : <LogOut className="size-4 text-muted-foreground" />}
                        <span className="w-10 font-medium">{s.direction}</span>
                        <span className="flex-1 text-muted-foreground">{formatDateTime(s.scanned_at)}</span>
                        <span className="truncate text-xs text-muted-foreground">{s.scanned_by_name}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}
        <ConfirmDialog
          open={revoking}
          onOpenChange={setRevoking}
          title="Revoke this pass?"
          description="The QR code stops opening the gate straight away. You can renew it later to reactivate it."
          confirmLabel="Revoke pass"
          tone="danger"
          reasonLabel="Reason (shown to the guard and kept in the audit log)"
          reasonPlaceholder="e.g. Left the course, fees pending"
          loading={revoke.isPending}
          onConfirm={doRevoke}
        />
      </DialogContent>
    </Dialog>
  )
}

function Attendance() {
  const [date, setDate] = useState(todayIso())
  const att = useStudentAttendance(date)
  const scans = att.data?.scans ?? []
  const summary = useMemo(() => {
    const last = new Map<string, string>()
    for (const s of [...scans].reverse()) last.set(s.admission_number, s.direction)
    return { students: last.size, inside: [...last.values()].filter((d) => d === "IN").length }
  }, [scans])
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Input type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} className="h-9 w-auto" aria-label="Day" />
        <span className="text-sm text-muted-foreground">{summary.students} students came, {summary.inside} still inside</span>
      </div>
      {att.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : scans.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card p-6"><EmptyState icon={<CalendarClock className="size-6" />} title="No scans on this day" description="Student IN and OUT scans from the gate appear here." /></div>
      ) : (
        <ul className="divide-y divide-border rounded-2xl border border-border bg-card text-sm">
          {scans.map((s) => (
            <li key={s.id} className="flex items-center gap-3 px-4 py-2.5">
              <span className={cn("w-12 rounded-md px-2 py-0.5 text-center text-xs font-semibold", s.direction === "IN" ? "bg-success-soft text-success" : "bg-secondary text-muted-foreground")}>{s.direction}</span>
              <span className="w-16 tabular-nums text-muted-foreground">{new Date(s.scanned_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
              <span className="min-w-0 flex-1 truncate font-medium">{s.student_name}</span>
              <span className="hidden font-mono text-xs text-muted-foreground sm:block">{s.admission_number}</span>
              <span className="hidden truncate text-xs text-muted-foreground md:block">{s.course}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function StudentPassesPage() {
  const { org } = useAuth()
  const [q, setQ] = useState("")
  const [filter, setFilter] = useState("")
  const [tab, setTab] = useState<"passes" | "attendance">("passes")
  const [issuing, setIssuing] = useState(false)
  const [openId, setOpenId] = useState<number | null>(null)
  const list = useStudentPasses(q, filter)
  const counts = list.data?.counts
  const rows = list.data?.results ?? []
  const orgName = org?.name ?? "AdmitOne"

  return (
    <div className="space-y-6">
      <PageHeader
        title="Student passes"
        description="6-month gate passes for students who have taken admission. Students scan in and out every day; renew or revoke any time."
        actions={<Button onClick={() => setIssuing(true)}><Plus className="size-4" /> Issue pass</Button>}
      />
      {list.isError && <QueryErrorState message="Student passes didn't load." retry={() => void list.refetch()} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tile label="Active passes" value={counts?.ACTIVE} icon={<GraduationCap className="size-5" />} tone="bg-primary-soft text-primary" active={filter === "ACTIVE"} onClick={() => { setTab("passes"); setFilter("ACTIVE") }} />
        <Tile label={`Expiring in ${list.data?.expiring_soon_days ?? 15} days`} value={counts?.EXPIRING} icon={<CalendarClock className="size-5" />} tone="bg-warning-soft text-warning" active={filter === "EXPIRING"} onClick={() => { setTab("passes"); setFilter("EXPIRING") }} />
        <Tile label="Expired" value={counts?.EXPIRED} icon={<RefreshCcw className="size-5" />} tone="bg-secondary text-muted-foreground" active={filter === "EXPIRED"} onClick={() => { setTab("passes"); setFilter("EXPIRED") }} />
        <Tile label="Revoked" value={counts?.REVOKED} icon={<Ban className="size-5" />} tone="bg-danger-soft text-danger" active={filter === "REVOKED"} onClick={() => { setTab("passes"); setFilter("REVOKED") }} />
        <Tile label="Students inside now" value={counts?.INSIDE} icon={<Users className="size-5" />} tone="bg-success-soft text-success" active={tab === "attendance"} onClick={() => setTab("attendance")} />
      </div>

      <div role="tablist" aria-label="View" className="inline-flex rounded-xl border border-border bg-card p-1">
        {([["passes", "Passes"], ["attendance", "Today's attendance"]] as const).map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cn("rounded-lg px-3.5 py-1.5 text-sm font-medium", tab === k ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground")}>{label}</button>
        ))}
      </div>

      {tab === "attendance" ? (
        <Attendance />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <div role="radiogroup" aria-label="Filter" className="flex flex-wrap gap-2">
              {FILTERS.map((f) => <Chip key={f.key} role="radio" className="h-8 text-xs" selected={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}</Chip>)}
            </div>
            <SearchInput value={q} onChange={setQ} placeholder="Search name, admission no., phone, course" className="ml-auto w-full sm:w-80" />
          </div>
          {list.isLoading ? (
            <div className="space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
          ) : rows.length === 0 ? (
            <div className="rounded-2xl border border-border bg-card p-6">
              <EmptyState
                icon={<GraduationCap className="size-6" />}
                title={q || filter ? "No passes match" : "No student passes yet"}
                description={q || filter ? "Try another search or filter." : "Issue a 6-month pass when a student takes admission."}
                action={!q && !filter ? <Button size="sm" onClick={() => setIssuing(true)}><Plus className="size-4" /> Issue first pass</Button> : undefined}
              />
            </div>
          ) : (
            <ul className="divide-y divide-border rounded-2xl border border-border bg-card">
              {rows.map((sp) => (
                <li key={sp.id}>
                  <button type="button" onClick={() => setOpenId(sp.id)} className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-hover">
                    <Avatar name={sp.student.full_name} src={sp.student.photo} className="size-11 rounded-xl" />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="truncate font-semibold">{sp.student.full_name}</span>
                        <span className="font-mono text-xs text-muted-foreground">{sp.admission_number}</span>
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">{sp.course}{sp.batch ? ` · ${sp.batch}` : ""} · {sp.student.phone}</span>
                    </span>
                    <span className="hidden text-right text-xs text-muted-foreground sm:block">
                      <span className="block">until {formatDate(sp.valid_until)}</span>
                      {sp.today && <span className={cn("font-medium", sp.today.direction === "IN" ? "text-success" : "")}>{sp.today.direction === "IN" ? "Inside" : "Left"} today</span>}
                    </span>
                    <StatusPill sp={sp} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <IssuePassDialog open={issuing} onOpenChange={setIssuing} onIssued={(sp) => { setIssuing(false); setOpenId(sp.id) }} />
      <PassDetail id={openId} orgName={orgName} onClose={() => setOpenId(null)} />
    </div>
  )
}
