import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { QRCodeSVG } from "qrcode.react"
import { toast } from "sonner"
import {
  CalendarDays,
  CalendarPlus,
  CheckCircle2,
  ClipboardList,
  Clock,
  DoorOpen,
  LogOut,
  MapPin,
  Navigation,
  QrCode,
  UserRound,
  Users,
} from "lucide-react"
import { AuthPanel } from "@/components/auth/AuthPanel"
import { Background } from "@/components/background"
import { PublicNav } from "@/components/public/PublicNav"
import { Alert } from "@/components/ui/Alert"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Card, CardContent } from "@/components/ui/Card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Input } from "@/components/ui/Input"
import { Skeleton } from "@/components/ui/Skeleton"
import { EMPTY_DRAFT, STEP_LABELS, type Draft, type Step } from "@/components/visitor/booking"
import { CompanyStep } from "@/components/visitor/CompanyStep"
import { IdentityStep } from "@/components/visitor/IdentityStep"
import { Instructions } from "@/components/visitor/Instructions"
import { ConfirmStep } from "@/components/visitor/ConfirmStep"
import { PurposeStep } from "@/components/visitor/PurposeStep"
import { SharePass } from "@/components/visitor/SharePass"
import { TimeStep } from "@/components/visitor/TimeStep"
import { StepProgress } from "@/components/visitor/ui"
import { Inspiration } from "@/components/visitor/Inspiration"
import type { PassPerson } from "@/components/visitor/VisitorPass"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { Field } from "@/components/widgets/Field"
import { StatusChip } from "@/components/widgets/StatusChip"
import { categoryLabel } from "@/lib/student-options"
import { formatApiError, type AvailabilitySlot } from "@/lib/types"
import { cn, formatDate, formatDateTime, todayIso } from "@/lib/utils"
import {
  getVisitorToken,
  useAnnounceArrival,
  useBookingAvailability,
  useCancelBooking,
  useRescheduleBooking,
  useVisitorAccount,
  useMyStudentPasses,
  useVisitorBookings,
  useVisitorLogout,
  type OrganizationResult,
  type VisitorVisit,
} from "@/lib/visitor-api"

/** Time slots as buttons (used when rescheduling from My visits). */
function SlotGrid({ slots, value, onChange, loading, error }: { slots: AvailabilitySlot[]; value: AvailabilitySlot | null; onChange: (s: AvailabilitySlot) => void; loading: boolean; error?: string }) {
  if (loading) return <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">{[...Array(8)].map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
  if (error) return <Alert variant="warning"><Clock className="mt-0.5 size-4 shrink-0" /><span>{error}</span></Alert>
  if (slots.length === 0) return <p className="rounded-xl border border-dashed border-border p-4 text-center text-sm text-muted-foreground">No free slots on this day. Try another date.</p>
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {slots.map((s) => {
        const active = value?.start === s.start
        return (
          <button
            key={s.start}
            type="button"
            onClick={() => onChange(s)}
            className={cn("rounded-lg border px-2 py-2 text-sm font-medium tabular-nums transition", active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:border-primary/40")}
          >
            {s.start}
          </button>
        )
      })}
    </div>
  )
}

/* ---------------------------------------------------------- done step */

function DoneStep({ visit, onAnother, onManage }: { visit: VisitorVisit; onAnother: () => void; onManage: () => void }) {
  return (
    <Card>
      <CardContent className="p-5 text-center sm:p-8">
        <span className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-success-soft text-success"><CheckCircle2 className="size-8" /></span>
        <h2 className="mt-4 text-2xl font-bold tracking-tight">Request sent to {visit.organization_name}</h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
          Your booking reference is <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-foreground">{visit.reference.slice(0, 8)}</code>.
          {visit.host_name ? ` ${visit.host_name} has been asked to approve it.` : " The host has been asked to approve it."} We'll email your QR pass when it is approved; it also appears under <strong>My visits</strong>.
        </p>
        <div className="mx-auto mt-5 grid max-w-md gap-2 rounded-xl border border-border p-4 text-left text-sm">
          <div className="flex items-center gap-2"><CalendarDays className="size-4 text-primary" /> {formatDate(visit.visit_date)} · {visit.expected_arrival}–{visit.expected_exit}</div>
          <div className="flex items-center gap-2"><ClipboardList className="size-4 text-primary" /> {visit.visitor_category ? categoryLabel(visit.visitor_category) : visit.visit_type_label} · {visit.purpose}</div>
          {visit.building_name && <div className="flex items-center gap-2"><MapPin className="size-4 text-primary" /> {[visit.building_name, visit.floor_name].filter(Boolean).join(", ")}</div>}
          <div className="flex items-center gap-2"><DoorOpen className="size-4 text-primary" /> <span className="text-muted-foreground">Your room is shown here and on your pass once the team assigns it.</span></div>
          <div className="flex items-center gap-2"><StatusChip status={visit.status} size="sm" /> <span className="text-muted-foreground">Awaiting host approval</span></div>
        </div>
        <div className="mt-6 flex flex-col justify-center gap-2 sm:flex-row">
          <Button onClick={onManage}><Users className="size-4" /> View my visits</Button>
          <Button variant="outline" onClick={onAnother}><CalendarPlus className="size-4" /> Book another visit</Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------- my visits */

function PassDialog({ visit, onClose }: { visit: VisitorVisit | null; onClose: () => void }) {
  const payload = visit?.qr ? `${visit.qr.token}|${visit.qr.signature}` : null
  return (
    <Dialog open={visit !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><QrCode className="size-5 text-primary" /> Your QR pass</DialogTitle>
          <DialogDescription>Show this at the gate. It works once and only for this visit.</DialogDescription>
        </DialogHeader>
        {visit && payload && (
          <div className="flex flex-col items-center gap-3">
            <div className={cn("rounded-2xl bg-white p-4 shadow-sm", !visit.qr?.is_valid && "opacity-50 grayscale")}>
              <QRCodeSVG value={payload} size={220} fgColor="#0f172a" level="M" />
            </div>
            <div className="text-center text-sm">
              <div className="font-semibold">{visit.organization_name}</div>
              <div className="text-muted-foreground">{formatDate(visit.visit_date)} · {visit.expected_arrival}–{visit.expected_exit}</div>
              {visit.room_label && <div className="mt-1 inline-flex items-center gap-1 font-medium text-primary"><DoorOpen className="size-3.5" /> Room {visit.room_label}{visit.floor_name ? ` · ${visit.floor_name}` : ""}</div>}
              <div className="mt-1 font-mono text-xs text-muted-foreground">Ref {visit.reference.slice(0, 8)}</div>
              {!visit.qr?.is_valid && <Badge tone="neutral" className="mt-2">This pass has already been used or has expired</Badge>}
            </div>
            {visit.qr?.is_valid && <SharePass visit={visit} payload={payload} />}
          </div>
        )}
        <DialogFooter><Button onClick={onClose}>Done</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function RescheduleDialog({ visit, onClose }: { visit: VisitorVisit | null; onClose: () => void }) {
  const [date, setDate] = useState("")
  const [slot, setSlot] = useState<AvailabilitySlot | null>(null)
  const avail = useBookingAvailability(visit?.id ?? null, date)
  const reschedule = useRescheduleBooking()
  useEffect(() => {
    setDate(visit?.visit_date ?? "")
    setSlot(null)
  }, [visit])
  const submit = async () => {
    if (!visit || !slot) return
    try {
      const res = await reschedule.mutateAsync({ id: visit.id, visit_date: date, expected_arrival: slot.start, expected_exit: slot.end })
      toast.success("Visit rescheduled", { description: res.detail })
      onClose()
    } catch (e) {
      toast.error("Could not reschedule", { description: formatApiError(e) })
    }
  }
  return (
    <Dialog open={visit !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reschedule your visit</DialogTitle>
          <DialogDescription>{visit?.host_name ? `Pick a new time when ${visit.host_name} is free.` : "Pick a new date and time."}</DialogDescription>
        </DialogHeader>
        <Field id="rs-date" label="New date"><Input id="rs-date" type="date" min={todayIso()} value={date} onChange={(e) => { setDate(e.target.value); setSlot(null) }} /></Field>
        <SlotGrid slots={avail.data?.slots ?? []} value={slot} onChange={setSlot} loading={avail.isLoading} error={avail.isError ? formatApiError(avail.error) : undefined} />
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={submit} disabled={!slot} loading={reschedule.isPending}>Confirm new time</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** An admitted student's 6-month pass, shown above their visits. */
function MyStudentPassCard() {
  const passes = useMyStudentPasses()
  const list = passes.data?.passes ?? []
  if (list.length === 0) return null
  return (
    <section className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Your student pass</h3>
      {list.map((p) => (
        <div key={p.id} className="flex flex-col gap-4 rounded-2xl bg-nav p-5 text-nav-foreground shadow-lift sm:flex-row sm:items-center">
          <div className={cn("self-center rounded-xl bg-white p-2", !p.payload && "opacity-40 grayscale")}>
            {p.payload ? <QRCodeSVG value={p.payload} size={150} fgColor="#0f172a" level="M" /> : <div className="size-[150px]" />}
          </div>
          <div className="min-w-0 space-y-1">
            <div className="text-sm text-nav-muted">{p.organization_name}</div>
            <div className="text-lg font-semibold">{p.student_name}</div>
            <div className="font-mono text-sm text-nav-accent">{p.admission_number}</div>
            <div className="text-sm text-nav-muted">{p.course}{p.batch ? ` · ${p.batch}` : ""}</div>
            <div className="text-sm">
              {p.status === "ACTIVE" && <>Valid until <span className="font-semibold">{formatDate(p.valid_until)}</span>. Scan it at the gate when you arrive and leave.</>}
              {p.status === "UPCOMING" && <>Starts on <span className="font-semibold">{formatDate(p.valid_from)}</span>.</>}
              {p.status === "EXPIRED" && <span className="text-amber-300">Expired on {formatDate(p.valid_until)}. Ask the office to renew it.</span>}
              {p.status === "REVOKED" && <span className="text-red-300">This pass has been cancelled. Please contact the office.</span>}
            </div>
          </div>
        </div>
      ))}
    </section>
  )
}

function MyVisits({ onBookAnother }: { onBookAnother: () => void }) {
  const bookings = useVisitorBookings()
  const cancel = useCancelBooking()
  const arrive = useAnnounceArrival()
  const [pass, setPass] = useState<VisitorVisit | null>(null)
  const [resched, setResched] = useState<VisitorVisit | null>(null)
  const [cancelling, setCancelling] = useState<VisitorVisit | null>(null)

  const list = bookings.data ?? []
  const upcoming = list.filter((v) => ["PENDING", "APPROVED", "CHECKED_IN"].includes(v.status))
  const past = list.filter((v) => !upcoming.includes(v))

  const announce = async (v: VisitorVisit) => {
    try {
      const res = await arrive.mutateAsync({ id: v.id })
      toast.success("Host notified", { description: res.detail })
    } catch (e) {
      toast.error("Could not notify host", { description: formatApiError(e) })
    }
  }
  const doCancel = async (reason: string) => {
    if (!cancelling) return
    try {
      const res = await cancel.mutateAsync({ id: cancelling.id, reason })
      toast.success("Visit cancelled", { description: res.detail })
      setCancelling(null)
    } catch (e) {
      toast.error("Could not cancel", { description: formatApiError(e) })
    }
  }

  const Item = ({ v }: { v: VisitorVisit }) => (
    <li className="card-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{v.organization_name}</span>
            <StatusChip status={v.status} size="sm" />
            {v.arriving_at && <Badge tone="cyan" size="sm">Arrival announced</Badge>}
          </div>
          <div className="mt-1 text-sm text-muted-foreground">{v.visitor_category ? categoryLabel(v.visitor_category) : v.visit_type_label} · {v.purpose}{v.host_name ? ` · with ${v.host_name}` : ""}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1"><CalendarDays className="size-3" /> {formatDate(v.visit_date)}</span>
            <span className="inline-flex items-center gap-1"><Clock className="size-3" /> {v.expected_arrival}–{v.expected_exit}</span>
            {v.building_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3" /> {[v.building_name, v.floor_name].filter(Boolean).join(", ")}</span>}
            {v.room_label && <span className="inline-flex items-center gap-1 font-medium text-primary"><DoorOpen className="size-3" /> Room {v.room_label}</span>}
            <span className="font-mono">Ref {v.reference.slice(0, 8)}</span>
          </div>
          {v.status === "REJECTED" && v.rejection_reason && <p className="mt-1 text-xs italic text-danger">Declined: {v.rejection_reason}</p>}
          {v.status === "PENDING" && <p className="mt-1 text-xs text-warning">Waiting for the host to approve. You'll get your pass here.</p>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {v.qr && (v.status === "APPROVED" || v.status === "CHECKED_IN") && (
            <Button size="sm" onClick={() => setPass(v)}><QrCode className="size-3.5" /> Pass</Button>
          )}
          {v.can_arrive && <Button size="sm" variant="secondary" onClick={() => announce(v)} disabled={arrive.isPending}><Navigation className="size-3.5" /> I'm arriving</Button>}
          {v.can_reschedule && <Button size="sm" variant="outline" onClick={() => setResched(v)}><Clock className="size-3.5" /> Reschedule</Button>}
          {v.can_cancel && <Button size="sm" variant="ghost" className="text-muted-foreground hover:text-danger" onClick={() => setCancelling(v)}>Cancel</Button>}
        </div>
      </div>
    </li>
  )

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight">My visits</h2>
          <p className="text-sm text-muted-foreground">Passes, approvals and history across every organisation you visit.</p>
        </div>
        <Button onClick={onBookAnother}><CalendarPlus className="size-4" /> New visit</Button>
      </div>
      <MyStudentPassCard />
      {bookings.isLoading ? (
        <div className="space-y-3">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-24 w-full" />)}</div>
      ) : list.length === 0 ? (
        <div className="card-surface p-8 text-center">
          <CalendarPlus className="mx-auto size-8 text-primary" />
          <p className="mt-3 font-semibold">No visits yet</p>
          <p className="text-sm text-muted-foreground">Book your first visit and it will appear here with its status and pass.</p>
        </div>
      ) : (
        <>
          {upcoming.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Upcoming & active</h3>
              <ul className="space-y-3">{upcoming.map((v) => <Item key={v.id} v={v} />)}</ul>
            </section>
          )}
          {past.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Past</h3>
              <ul className="space-y-3 opacity-80">{past.map((v) => <Item key={v.id} v={v} />)}</ul>
            </section>
          )}
        </>
      )}
      <PassDialog visit={pass} onClose={() => setPass(null)} />
      <RescheduleDialog visit={resched} onClose={() => setResched(null)} />
      <ConfirmDialog
        open={cancelling !== null}
        onOpenChange={(o) => !o && setCancelling(null)}
        title="Cancel this visit?"
        description={cancelling ? `Your booking at ${cancelling.organization_name} on ${formatDate(cancelling.visit_date)} will be cancelled and any pass voided.` : undefined}
        confirmLabel="Cancel visit"
        tone="danger"
        reasonLabel="Reason (optional)"
        reasonMaxLength={120}
        loading={cancel.isPending}
        onConfirm={doCancel}
      />
    </div>
  )
}

/* ---------------------------------------------------------------- page */

export function VisitorHubPage() {
  const { slug: slugParam } = useParams<{ slug?: string }>()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const account = useVisitorAccount()
  const logout = useVisitorLogout()
  const signedIn = Boolean(getVisitorToken()) && !account.isError

  const [step, setStep] = useState<Step>("account")
  const [view, setView] = useState<"book" | "visits">(params.get("view") === "visits" ? "visits" : "book")
  // Menu links (E-Services) switch views via ?view= while the page is open.
  const viewParam = params.get("view")
  useEffect(() => {
    setView(viewParam === "visits" ? "visits" : "book")
  }, [viewParam])
  const [org, setOrg] = useState<OrganizationResult | null>(null)
  /** True when the company was chosen for the visitor (booking link or the only company). */
  const [autoCompany, setAutoCompany] = useState(false)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [done, setDone] = useState<VisitorVisit | null>(null)
  const [preview, setPreview] = useState<PassPerson>({ name: "", category: "", email: "" })
  // Read-before-you-apply notice: shown once per browser session.
  const [readInstructions, setReadInstructions] = useState(() => {
    try {
      return sessionStorage.getItem("admitone_pass_instructions") === "1"
    } catch {
      return false
    }
  })
  const acceptInstructions = () => {
    try {
      sessionStorage.setItem("admitone_pass_instructions", "1")
    } catch {
      /* private mode: show it again next time */
    }
    setReadInstructions(true)
  }
  const preset = slugParam ?? ""

  // Skip the account step for a returning visitor.
  useEffect(() => {
    if (signedIn && account.data && step === "account") setStep("company")
    if (!signedIn && step !== "account") setStep("account")
  }, [signedIn, account.data, step])

  const restart = () => {
    setOrg(null)
    setAutoCompany(false)
    setDraft(EMPTY_DRAFT)
    setDone(null)
    setView("book")
    setStep(signedIn ? "company" : "account")
    if (slugParam) navigate("/visitor", { replace: true })
  }

  const pickCompany = (o: OrganizationResult, auto: boolean) => {
    if (o.id !== org?.id) setDraft(EMPTY_DRAFT)
    setOrg(o)
    setAutoCompany(auto)
    setStep("purpose")
  }

  const flow: Exclude<Step, "done">[] = ["account", ...(autoCompany ? [] : (["company"] as const)), "purpose", "time", "identity", "confirm"]
  const progress = flow.map((key) => ({ key, label: STEP_LABELS[key] }))
  const slug = org?.slug ?? ""

  return (
    <div className="min-h-screen">
      <Background />
      <PublicNav
        right={
          signedIn && account.data ? (
            <>
              <span className="hidden items-center gap-2 text-sm text-muted-foreground xl:inline-flex"><UserRound className="size-4" /> {account.data.full_name}</span>
              <Button variant="ghost" size="sm" onClick={() => logout.mutate(undefined, { onSettled: () => { restart(); setStep("account"); toast.success("Signed out") } })} aria-label="Sign out"><LogOut className="size-4" /><span className="hidden sm:inline">Sign out</span></Button>
            </>
          ) : null
        }
      />

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
        {signedIn && account.data && (
          <div className="mb-6 flex w-full rounded-xl border border-border bg-card p-1 sm:w-fit">
            <button type="button" onClick={() => { setView("book"); if (done) restart() }} className={cn("flex-1 rounded-lg px-3 py-2 text-sm font-medium", view === "book" ? "bg-primary-soft text-primary" : "text-muted-foreground")}>Book a visit</button>
            <button type="button" onClick={() => setView("visits")} className={cn("flex-1 rounded-lg px-3 py-2 text-sm font-medium", view === "visits" ? "bg-primary-soft text-primary" : "text-muted-foreground")}>My visits</button>
          </div>
        )}

        {view === "visits" && signedIn ? (
          <MyVisits onBookAnother={restart} />
        ) : (
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-10">
            <div className="min-w-0 space-y-6">
              <div>
                <h1 className="text-2xl font-semibold tracking-tight sm:text-[2rem]">{org && step !== "account" && step !== "company" ? `Book a visit to ${org.name}` : "Book a visit"}</h1>
                <p className="mt-1.5 max-w-xl text-sm text-muted-foreground sm:text-base">
                  Tell us why you're coming, pick a time with your host, and send the request. It takes about 3 minutes.
                </p>
              </div>
              {!readInstructions && step !== "done" ? (
                <Instructions onAccept={acceptInstructions} />
              ) : (
              <>
              {step !== "done" && <StepProgress steps={progress} current={step} />}

              {step === "account" && (
                <AuthPanel
                  role="visitor"
                  initialMode="login"
                  portal
                  onSignedIn={() => setStep("company")}
                  onPreview={(p) => setPreview({ name: p.full_name, category: p.category, email: p.email.includes("@") ? p.email : "" })}
                />
              )}
              {step === "company" && <CompanyStep preset={preset} selected={org} onPick={pickCompany} />}
              {step === "purpose" && org && (
                <PurposeStep slug={slug} draft={draft} setDraft={setDraft} onBack={autoCompany ? undefined : () => setStep("company")} onNext={() => setStep("time")} />
              )}
              {step === "time" && org && <TimeStep slug={slug} draft={draft} setDraft={setDraft} onBack={() => setStep("purpose")} onNext={() => setStep("identity")} />}
              {step === "identity" && org && <IdentityStep draft={draft} setDraft={setDraft} onBack={() => setStep("time")} onNext={() => setStep("confirm")} />}
              {step === "confirm" && org && (
                <ConfirmStep
                  org={org}
                  draft={draft}
                  setDraft={setDraft}
                  canChangeCompany={!autoCompany}
                  onEdit={setStep}
                  onBack={() => setStep("identity")}
                  onDone={(v) => { setDone(v); setStep("done") }}
                />
              )}
              {step === "done" && done && <DoneStep visit={done} onAnother={restart} onManage={() => setView("visits")} />}
              </>
              )}
            </div>

            <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
              <Inspiration step={readInstructions ? step : "account"} name={account.data?.full_name ?? preview.name} />
              <div className="rounded-2xl border border-border bg-card p-4 text-sm">
                <div className="font-semibold">How it works</div>
                <ol className="mt-2.5 space-y-2 text-muted-foreground">
                  <li className="flex gap-2.5"><span className="font-semibold text-foreground tabular-nums">1</span> Send a request with your reason and preferred time.</li>
                  <li className="flex gap-2.5"><span className="font-semibold text-foreground tabular-nums">2</span> Your host approves it and reception assigns your room. Your single-use QR pass arrives by email and under My visits.</li>
                  <li className="flex gap-2.5"><span className="font-semibold text-foreground tabular-nums">3</span> Show the pass at the gate. Security scans it and you're in.</li>
                </ol>
                {signedIn && account.data?.last_login && (
                  <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">Signed in as {account.data.email}. Last sign-in {formatDateTime(account.data.last_login)}.</p>
                )}
              </div>
              <p className="px-1 text-xs text-muted-foreground">Staff member? <Link to="/admin" className="font-medium text-primary hover:underline">Go to the admin portal</Link>.</p>
            </aside>
          </div>
        )}
      </main>
    </div>
  )
}
