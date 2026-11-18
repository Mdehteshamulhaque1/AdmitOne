import { useEffect, useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { QRCodeSVG } from "qrcode.react"
import { toast } from "sonner"
import {
  ArrowLeft,
  ArrowRight,
  Building2,
  CalendarDays,
  CalendarPlus,
  Check,
  CheckCircle2,
  ClipboardList,
  Clock,
  LogOut,
  MapPin,
  Navigation,
  QrCode,
  Search,
  ShieldCheck,
  Sparkles,
  UserRound,
  Users,
  XCircle,
} from "lucide-react"
import { AuthPanel } from "@/components/auth/AuthPanel"
import { Background } from "@/components/background"
import { LogoWordmark } from "@/components/logo"
import { Alert } from "@/components/ui/Alert"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Card, CardContent } from "@/components/ui/Card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Input, Textarea } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { Field } from "@/components/widgets/Field"
import { StatusChip } from "@/components/widgets/StatusChip"
import { api } from "@/lib/api"
import { useTheme } from "@/lib/theme"
import { formatApiError, type AvailabilitySlot, type BookingHost, type HostAvailabilityResponse } from "@/lib/types"
import { cn, formatDate, formatDateTime, todayIso } from "@/lib/utils"
import {
  getVisitorToken,
  useAnnounceArrival,
  useBookingAvailability,
  useCancelBooking,
  useCreateBooking,
  useOrganizationContext,
  useOrganizationSearch,
  useRescheduleBooking,
  useVisitorAccount,
  useVisitorBookings,
  useVisitorLogout,
  type OrganizationResult,
  type VisitorVisit,
} from "@/lib/visitor-api"
import { Moon, Sun } from "lucide-react"

type Step = "account" | "organisation" | "details" | "schedule" | "review" | "done"
const STEPS: { key: Step; label: string }[] = [
  { key: "account", label: "Your account" },
  { key: "organisation", label: "Where" },
  { key: "details", label: "Visit details" },
  { key: "schedule", label: "When" },
  { key: "review", label: "Review" },
  { key: "done", label: "Confirmed" },
]

interface Draft {
  visit_type: string
  purpose: string
  purpose_other: string
  department: string
  building: string
  floor: string
  host: string
  visit_date: string
  slot: AvailabilitySlot | null
  notes: string
}
const EMPTY_DRAFT: Draft = {
  visit_type: "",
  purpose: "",
  purpose_other: "",
  department: "",
  building: "",
  floor: "",
  host: "",
  visit_date: "",
  slot: null,
  notes: "",
}

function usePublicHosts(slug: string, department: string) {
  return useQuery({
    queryKey: ["visitor", "hosts", slug, department],
    queryFn: () =>
      api<BookingHost[]>(`/api/public/booking/${encodeURIComponent(slug)}/hosts/${department ? `?department=${department}` : ""}`),
    enabled: Boolean(slug),
  })
}

function usePublicAvailability(slug: string, host: string, date: string) {
  return useQuery({
    queryKey: ["visitor", "slots", slug, host, date],
    queryFn: () =>
      api<HostAvailabilityResponse>(`/api/public/booking/${encodeURIComponent(slug)}/availability/?host=${host}&date=${date}`),
    enabled: Boolean(slug && host && date),
    retry: false,
  })
}

/* ------------------------------------------------------------- step rail */

function StepRail({ current }: { current: Step }) {
  const idx = STEPS.findIndex((s) => s.key === current)
  return (
    <ol className="flex items-center gap-1 overflow-x-auto pb-1 sm:gap-2" aria-label="Booking progress">
      {STEPS.map((s, i) => {
        const done = i < idx
        const active = i === idx
        return (
          <li key={s.key} className="flex shrink-0 items-center gap-1 sm:gap-2">
            <span
              className={cn(
                "flex size-7 items-center justify-center rounded-full border text-xs font-semibold transition-colors",
                done && "border-primary bg-primary text-primary-foreground",
                active && "border-primary bg-primary-soft text-primary",
                !done && !active && "border-border bg-card text-muted-foreground",
              )}
            >
              {done ? <Check className="size-3.5" /> : i + 1}
            </span>
            <span className={cn("hidden text-xs font-medium sm:block", active ? "text-foreground" : "text-muted-foreground")}>{s.label}</span>
            {i < STEPS.length - 1 && <span className={cn("mx-1 h-px w-4 sm:w-8", done ? "bg-primary" : "bg-border")} />}
          </li>
        )
      })}
    </ol>
  )
}

/* -------------------------------------------------- organisation step */

function OrganisationStep({ preset, onPick }: { preset: string; onPick: (org: OrganizationResult) => void }) {
  const [q, setQ] = useState("")
  const search = useOrganizationSearch(q)
  const presetCtx = useOrganizationContext(preset)

  useEffect(() => {
    if (preset && presetCtx.data) {
      const o = presetCtx.data.organization
      onPick({ id: o.id, name: o.name, slug: o.slug, tagline: o.tagline, city: o.city, country: o.country })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, presetCtx.data])

  return (
    <Card>
      <CardContent className="p-5 sm:p-7">
        <h2 className="text-xl font-bold tracking-tight">Where are you visiting?</h2>
        <p className="mt-1 text-sm text-muted-foreground">Search the organisation by name or city. If you were given a booking link, it is already selected.</p>
        {preset && presetCtx.isError && (
          <Alert variant="danger" className="mt-4"><XCircle className="mt-0.5 size-4 shrink-0" /><span>We couldn't find an organisation for the link <code>/{preset}</code>. Search for it below instead.</span></Alert>
        )}
        {preset && presetCtx.isLoading && <Skeleton className="mt-4 h-12 w-full" />}
        <div className="relative mt-5">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Acme, Northwind, Pune…" className="h-11 pl-9" autoFocus />
        </div>
        <div className="mt-3 space-y-2">
          {q.trim().length < 2 ? (
            <p className="text-xs text-muted-foreground">Type at least two characters.</p>
          ) : search.isLoading ? (
            <Skeleton className="h-14 w-full" />
          ) : (search.data ?? []).length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-4 text-center text-sm text-muted-foreground">No organisation matches “{q}”. Check the spelling or ask your host for their booking link.</p>
          ) : (
            (search.data ?? []).map((o) => (
              <button
                key={o.id}
                type="button"
                onClick={() => onPick(o)}
                className="flex w-full items-center gap-3 rounded-xl border border-border bg-card p-3.5 text-left transition hover:border-primary/40 hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><Building2 className="size-5" /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold">{o.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">{[o.tagline, o.city, o.country].filter(Boolean).join(" · ") || o.slug}</span>
                </span>
                <ArrowRight className="size-4 text-muted-foreground" />
              </button>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------- details step */

function DetailsStep({ slug, draft, setDraft, onBack, onNext }: { slug: string; draft: Draft; setDraft: (d: Draft) => void; onBack: () => void; onNext: () => void }) {
  const ctx = useOrganizationContext(slug)
  const hosts = usePublicHosts(slug, draft.department)
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })
  const purposes = ctx.data?.purposes[draft.visit_type] ?? []
  const building = ctx.data?.buildings.find((b) => String(b.id) === draft.building)
  const valid = draft.visit_type && draft.purpose && (draft.purpose !== "Other" || draft.purpose_other.trim()) && draft.host

  if (ctx.isLoading) return <Skeleton className="h-96 w-full" />
  if (ctx.isError || !ctx.data) return <Alert variant="danger">Couldn't load the booking form. <Button variant="ghost" size="sm" onClick={onBack}>Choose another organisation</Button></Alert>

  return (
    <Card>
      <CardContent className="space-y-6 p-5 sm:p-7">
        <div>
          <h2 className="text-xl font-bold tracking-tight">What brings you to {ctx.data.organization.name}?</h2>
          <p className="mt-1 text-sm text-muted-foreground">Pick the type of visit and the person you are meeting.</p>
        </div>

        <div>
          <div className="mb-2 text-sm font-medium">Type of visit</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {ctx.data.visit_types.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => set({ visit_type: t.value, purpose: "", purpose_other: "" })}
                className={cn(
                  "rounded-xl border px-3 py-2.5 text-left text-sm font-medium transition",
                  draft.visit_type === t.value ? "border-primary bg-primary-soft text-primary" : "border-border bg-card hover:border-border-strong",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="d-purpose" label="Purpose" required>
            <Select value={draft.purpose} onValueChange={(v) => set({ purpose: v })} disabled={!draft.visit_type}>
              <SelectTrigger id="d-purpose"><SelectValue placeholder={draft.visit_type ? "Choose a purpose" : "Pick a visit type first"} /></SelectTrigger>
              <SelectContent>{purposes.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          {draft.purpose === "Other" && (
            <Field id="d-other" label="Describe the purpose" required><Input id="d-other" maxLength={120} value={draft.purpose_other} onChange={(e) => set({ purpose_other: e.target.value })} /></Field>
          )}
          <Field id="d-dept" label="Department" hint="Optional; narrows the list of people.">
            <Select value={draft.department || "any"} onValueChange={(v) => set({ department: v === "any" ? "" : v, host: "" })}>
              <SelectTrigger id="d-dept"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Any department</SelectItem>
                {ctx.data.departments.map((d) => <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field id="d-host" label="Person you are meeting" required error={hosts.data && hosts.data.length === 0 ? "Nobody is available for booking in this department yet." : undefined}>
            <Select value={draft.host} onValueChange={(v) => set({ host: v, slot: null })}>
              <SelectTrigger id="d-host"><SelectValue placeholder={hosts.isLoading ? "Loading…" : "Choose a host"} /></SelectTrigger>
              <SelectContent>
                {(hosts.data ?? []).map((h) => (
                  <SelectItem key={h.id} value={String(h.id)}>{h.name}{h.designation ? ` · ${h.designation}` : ""}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {ctx.data.buildings.length > 1 && (
            <Field id="d-bld" label="Building">
              <Select value={draft.building || "any"} onValueChange={(v) => set({ building: v === "any" ? "" : v, floor: "" })}>
                <SelectTrigger id="d-bld"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Not sure</SelectItem>
                  {ctx.data.buildings.map((b) => <SelectItem key={b.id} value={String(b.id)}>{b.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
          )}
          {building && building.floors.length > 0 && (
            <Field id="d-floor" label="Floor">
              <Select value={draft.floor || "any"} onValueChange={(v) => set({ floor: v === "any" ? "" : v })}>
                <SelectTrigger id="d-floor"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Not sure</SelectItem>
                  {building.floors.map((f) => <SelectItem key={f.id} value={String(f.id)}>{f.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border pt-5">
          <Button variant="ghost" onClick={onBack}><ArrowLeft className="size-4" /> Back</Button>
          <Button onClick={onNext} disabled={!valid}>Choose a time <ArrowRight className="size-4" /></Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------ schedule step */

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

function ScheduleStep({ slug, draft, setDraft, onBack, onNext }: { slug: string; draft: Draft; setDraft: (d: Draft) => void; onBack: () => void; onNext: () => void }) {
  const avail = usePublicAvailability(slug, draft.host, draft.visit_date)
  return (
    <Card>
      <CardContent className="space-y-6 p-5 sm:p-7">
        <div>
          <h2 className="text-xl font-bold tracking-tight">When would you like to come?</h2>
          <p className="mt-1 text-sm text-muted-foreground">Only times inside working hours when your host is free are shown.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-[14rem_1fr]">
          <Field id="s-date" label="Date" required>
            <Input id="s-date" type="date" min={todayIso()} value={draft.visit_date} onChange={(e) => setDraft({ ...draft, visit_date: e.target.value, slot: null })} />
          </Field>
          <div>
            <div className="mb-1.5 text-sm font-medium">Available times {avail.data ? <span className="text-xs text-muted-foreground">· {avail.data.slot_duration_minutes} min slots</span> : null}</div>
            {draft.visit_date ? (
              <SlotGrid slots={avail.data?.slots ?? []} value={draft.slot} onChange={(slot) => setDraft({ ...draft, slot })} loading={avail.isLoading} error={avail.isError ? formatApiError(avail.error) : undefined} />
            ) : (
              <p className="text-sm text-muted-foreground">Pick a date to see free slots.</p>
            )}
          </div>
        </div>
        <div className="flex items-center justify-between gap-3 border-t border-border pt-5">
          <Button variant="ghost" onClick={onBack}><ArrowLeft className="size-4" /> Back</Button>
          <Button onClick={onNext} disabled={!draft.slot}>Review booking <ArrowRight className="size-4" /></Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* -------------------------------------------------------- review step */

function ReviewStep({ org, slug, draft, setDraft, onBack, onDone }: { org: OrganizationResult; slug: string; draft: Draft; setDraft: (d: Draft) => void; onBack: () => void; onDone: (v: VisitorVisit) => void }) {
  const account = useVisitorAccount()
  const ctx = useOrganizationContext(slug)
  const hosts = usePublicHosts(slug, draft.department)
  const create = useCreateBooking()
  const host = hosts.data?.find((h) => String(h.id) === draft.host)
  const dept = ctx.data?.departments.find((d) => String(d.id) === draft.department)
  const bld = ctx.data?.buildings.find((b) => String(b.id) === draft.building)

  const submit = async () => {
    if (!draft.slot) return
    try {
      const res = await create.mutateAsync({
        organization: slug,
        visit_type: draft.visit_type,
        purpose: draft.purpose,
        purpose_other: draft.purpose_other,
        department: draft.department ? Number(draft.department) : null,
        building: draft.building ? Number(draft.building) : null,
        floor: draft.floor ? Number(draft.floor) : null,
        host: Number(draft.host),
        visit_date: draft.visit_date,
        expected_arrival: draft.slot.start,
        expected_exit: draft.slot.end,
        notes: draft.notes,
      })
      toast.success("Booking submitted", { description: res.message })
      onDone(res.visit)
    } catch (err) {
      toast.error("Booking failed", { description: formatApiError(err) })
    }
  }

  const rows: [string, string][] = [
    ["Organisation", [org.name, org.city].filter(Boolean).join(" · ")],
    ["Visit", `${ctx.data?.visit_types.find((t) => t.value === draft.visit_type)?.label ?? draft.visit_type} · ${draft.purpose === "Other" ? draft.purpose_other : draft.purpose}`],
    ["Meeting", host ? `${host.name}${host.designation ? `, ${host.designation}` : ""}${dept ? ` (${dept.name})` : ""}` : "—"],
    ["Location", [bld?.name, bld?.floors.find((f) => String(f.id) === draft.floor)?.name].filter(Boolean).join(", ") || "To be confirmed"],
    ["When", draft.slot ? `${formatDate(draft.visit_date)} · ${draft.slot.start}–${draft.slot.end}` : "—"],
    ["You", account.data ? `${account.data.full_name} · ${account.data.phone} · ${account.data.email}` : "—"],
  ]

  return (
    <Card>
      <CardContent className="space-y-6 p-5 sm:p-7">
        <div>
          <h2 className="text-xl font-bold tracking-tight">Review and submit</h2>
          <p className="mt-1 text-sm text-muted-foreground">Your host will approve the request; you'll find your QR pass here once they do.</p>
        </div>
        <dl className="divide-y divide-border rounded-xl border border-border">
          {rows.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[6.5rem_1fr] gap-3 px-4 py-2.5 text-sm">
              <dt className="text-muted-foreground">{k}</dt>
              <dd className="font-medium">{v}</dd>
            </div>
          ))}
        </dl>
        <Field id="r-notes" label="Anything your host should know?" hint="Optional, e.g. accessibility needs, parking, equipment.">
          <Textarea id="r-notes" rows={3} maxLength={1000} value={draft.notes} onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
        </Field>
        <div className="flex items-center justify-between gap-3 border-t border-border pt-5">
          <Button variant="ghost" onClick={onBack} disabled={create.isPending}><ArrowLeft className="size-4" /> Back</Button>
          <Button size="lg" onClick={submit} loading={create.isPending}><CheckCircle2 className="size-4" /> Submit booking</Button>
        </div>
      </CardContent>
    </Card>
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
          <div className="flex items-center gap-2"><ClipboardList className="size-4 text-primary" /> {visit.visit_type_label} · {visit.purpose}</div>
          {visit.building_name && <div className="flex items-center gap-2"><MapPin className="size-4 text-primary" /> {[visit.building_name, visit.floor_name].filter(Boolean).join(", ")}</div>}
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
              <div className="mt-1 font-mono text-xs text-muted-foreground">Ref {visit.reference.slice(0, 8)}</div>
              {!visit.qr?.is_valid && <Badge tone="neutral" className="mt-2">This pass has already been used or has expired</Badge>}
            </div>
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
          <div className="mt-1 text-sm text-muted-foreground">{v.visit_type_label} · {v.purpose}{v.host_name ? ` · with ${v.host_name}` : ""}</div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-1"><CalendarDays className="size-3" /> {formatDate(v.visit_date)}</span>
            <span className="inline-flex items-center gap-1"><Clock className="size-3" /> {v.expected_arrival}–{v.expected_exit}</span>
            {v.building_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3" /> {v.building_name}</span>}
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
  const { resolved, toggle } = useTheme()
  const account = useVisitorAccount()
  const logout = useVisitorLogout()
  const signedIn = Boolean(getVisitorToken()) && !account.isError

  const [step, setStep] = useState<Step>("account")
  const [view, setView] = useState<"book" | "visits">(params.get("view") === "visits" ? "visits" : "book")
  const [org, setOrg] = useState<OrganizationResult | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [done, setDone] = useState<VisitorVisit | null>(null)
  const preset = slugParam ?? ""

  // Skip the account step for a returning visitor.
  useEffect(() => {
    if (signedIn && account.data && step === "account") setStep("organisation")
    if (!signedIn && step !== "account") setStep("account")
  }, [signedIn, account.data, step])

  const restart = () => {
    setOrg(null)
    setDraft(EMPTY_DRAFT)
    setDone(null)
    setView("book")
    setStep(signedIn ? "organisation" : "account")
    if (slugParam) navigate("/visitor", { replace: true })
  }

  const slug = org?.slug ?? ""
  const showRail = view === "book"

  return (
    <div className="min-h-screen">
      <Background />
      <header className="sticky top-0 z-30 border-b border-border bg-background/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <Link to="/" aria-label="SecureGate home"><LogoWordmark /></Link>
          <div className="flex items-center gap-1 sm:gap-2">
            {signedIn && account.data && (
              <>
                <div className="hidden sm:flex rounded-xl border border-border bg-card p-1">
                  <button type="button" onClick={() => { setView("book"); if (done) restart() }} className={cn("rounded-lg px-3 py-1.5 text-sm font-medium", view === "book" ? "bg-primary-soft text-primary" : "text-muted-foreground hover:text-foreground")}>Book a visit</button>
                  <button type="button" onClick={() => setView("visits")} className={cn("rounded-lg px-3 py-1.5 text-sm font-medium", view === "visits" ? "bg-primary-soft text-primary" : "text-muted-foreground hover:text-foreground")}>My visits</button>
                </div>
                <span className="hidden items-center gap-2 text-sm text-muted-foreground md:inline-flex"><UserRound className="size-4" /> {account.data.full_name}</span>
                <Button variant="ghost" size="sm" onClick={() => logout.mutate(undefined, { onSettled: () => { setStep("account"); setView("book"); toast.success("Signed out") } })} aria-label="Sign out"><LogOut className="size-4" /><span className="hidden sm:inline">Sign out</span></Button>
              </>
            )}
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">{resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}</Button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-10">
        {signedIn && account.data && (
          <div className="mb-4 flex rounded-xl border border-border bg-card p-1 sm:hidden">
            <button type="button" onClick={() => { setView("book"); if (done) restart() }} className={cn("flex-1 rounded-lg px-3 py-2 text-sm font-medium", view === "book" ? "bg-primary-soft text-primary" : "text-muted-foreground")}>Book a visit</button>
            <button type="button" onClick={() => setView("visits")} className={cn("flex-1 rounded-lg px-3 py-2 text-sm font-medium", view === "visits" ? "bg-primary-soft text-primary" : "text-muted-foreground")}>My visits</button>
          </div>
        )}

        {view === "visits" && signedIn ? (
          <MyVisits onBookAnother={restart} />
        ) : (
          <div className="grid gap-8 lg:grid-cols-[1fr_18rem]">
            <div className="space-y-5">
              <div>
                <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
                  <ShieldCheck className="size-3.5 text-primary" /> Visitor booking
                </div>
                <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">Book your visit in a few steps</h1>
                <p className="mt-1 text-sm text-muted-foreground">Create an account once, choose where and when, and keep your QR pass right here.</p>
              </div>
              {showRail && <StepRail current={step} />}

              {step === "account" && (
                <AuthPanel role="visitor" initialMode="register" compact onSignedIn={() => setStep("organisation")} />
              )}
              {step === "organisation" && (
                <OrganisationStep preset={preset} onPick={(o) => { setOrg(o); setDraft(EMPTY_DRAFT); setStep("details") }} />
              )}
              {step === "details" && org && (
                <DetailsStep slug={slug} draft={draft} setDraft={setDraft} onBack={() => { setOrg(null); setStep("organisation"); if (slugParam) navigate("/visitor", { replace: true }) }} onNext={() => setStep("schedule")} />
              )}
              {step === "schedule" && org && (
                <ScheduleStep slug={slug} draft={draft} setDraft={setDraft} onBack={() => setStep("details")} onNext={() => setStep("review")} />
              )}
              {step === "review" && org && (
                <ReviewStep org={org} slug={slug} draft={draft} setDraft={setDraft} onBack={() => setStep("schedule")} onDone={(v) => { setDone(v); setStep("done") }} />
              )}
              {step === "done" && done && <DoneStep visit={done} onAnother={restart} onManage={() => setView("visits")} />}
            </div>

            <aside className="space-y-4 lg:pt-24">
              {org && step !== "done" && (
                <div className="card-surface p-4">
                  <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Booking with</div>
                  <div className="mt-1 font-semibold">{org.name}</div>
                  <div className="text-xs text-muted-foreground">{[org.tagline, org.city].filter(Boolean).join(" · ")}</div>
                  {draft.visit_date && draft.slot && (
                    <div className="mt-3 flex items-center gap-2 text-sm"><CalendarDays className="size-4 text-primary" /> {formatDate(draft.visit_date)} · {draft.slot.start}</div>
                  )}
                </div>
              )}
              <div className="card-surface space-y-3 p-4 text-sm">
                <div className="flex items-center gap-2 font-semibold"><Sparkles className="size-4 text-primary" /> How it works</div>
                <ol className="space-y-2 text-muted-foreground">
                  <li className="flex gap-2"><span className="font-semibold text-foreground">1.</span> Submit a request with your details and preferred time.</li>
                  <li className="flex gap-2"><span className="font-semibold text-foreground">2.</span> Your host approves it. You get a single-use QR pass by email and under My visits.</li>
                  <li className="flex gap-2"><span className="font-semibold text-foreground">3.</span> Show the pass at the gate. Security scans it and you're in.</li>
                </ol>
                {signedIn && account.data?.last_login && (
                  <p className="border-t border-border pt-3 text-xs text-muted-foreground">Signed in as {account.data.email} · last sign-in {formatDateTime(account.data.last_login)}</p>
                )}
              </div>
              <p className="px-1 text-xs text-muted-foreground">Staff member? <Link to="/login?role=staff" className="font-medium text-primary hover:underline">Sign in to the console</Link>.</p>
            </aside>
          </div>
        )}
      </main>
    </div>
  )
}
