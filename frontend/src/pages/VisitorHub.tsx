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
  DoorOpen,
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
import { categoryLabel } from "@/lib/student-options"
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
  /** Catalogue category key (who is visiting); drives the purpose list. */
  category: string
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
  category: "",
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
  const [picked, setPicked] = useState("")
  const directory = useOrganizationSearch(q)
  const presetCtx = useOrganizationContext(preset)

  useEffect(() => {
    if (preset && presetCtx.data) {
      const o = presetCtx.data.organization
      onPick({ id: o.id, name: o.name, slug: o.slug, tagline: o.tagline, city: o.city, country: o.country, buildings: presetCtx.data.buildings })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, presetCtx.data])

  const list = directory.data ?? []
  const floorsLabel = (floors: { level: number; name: string }[]) => {
    if (floors.length === 0) return ""
    const sorted = [...floors].sort((a, b) => a.level - b.level)
    return floors.length <= 3 ? sorted.map((f) => f.name).join(", ") : `${sorted[0].name} – ${sorted[sorted.length - 1].name} (${floors.length} floors)`
  }

  return (
    <Card>
      <CardContent className="p-5 sm:p-7">
        <h2 className="text-xl font-bold tracking-tight">Where are you visiting?</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Pick the company from the directory below. Each entry lists its buildings and floors; use the search box to narrow the list. If you were given a booking link, it is already selected.
        </p>
        {preset && presetCtx.isError && (
          <Alert variant="danger" className="mt-4"><XCircle className="mt-0.5 size-4 shrink-0" /><span>We couldn't find an organisation for the link <code>/{preset}</code>. Choose it from the directory instead.</span></Alert>
        )}
        {preset && presetCtx.isLoading && <Skeleton className="mt-4 h-12 w-full" />}

        <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_1fr]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by company, building or city…" className="h-11 pl-9" aria-label="Filter the directory" />
          </div>
          <Select
            value={picked}
            onValueChange={(slug) => {
              setPicked(slug)
              const org = list.find((o) => o.slug === slug)
              if (org) onPick(org)
            }}
          >
            <SelectTrigger className="h-11" aria-label="Choose a company from the directory">
              <SelectValue placeholder={directory.isLoading ? "Loading directory…" : `Choose a company (${list.length})`} />
            </SelectTrigger>
            <SelectContent className="max-h-80">
              {list.map((o) => (
                <SelectItem key={o.slug} value={o.slug}>
                  <span className="font-medium">{o.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {[o.city, ...o.buildings.map((b) => `${b.name}${b.floors.length ? ` · ${floorsLabel(b.floors)}` : ""}`)].filter(Boolean).join(" · ")}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="mt-4 overflow-hidden rounded-xl border border-border">
          <div className="grid grid-cols-[1fr_1fr_auto] gap-3 border-b border-border bg-surface-2 px-3.5 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <span>Company</span>
            <span>Building · floors</span>
            <span className="sr-only">Select</span>
          </div>
          {directory.isLoading ? (
            <div className="space-y-2 p-3"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /></div>
          ) : directory.isError ? (
            <p className="p-4 text-sm text-danger">Couldn't load the directory. {formatApiError(directory.error)}</p>
          ) : list.length === 0 ? (
            <p className="p-5 text-center text-sm text-muted-foreground">
              {q ? <>No company matches “{q}”. Try another spelling, or ask your host for their booking link.</> : "No organisations are registered yet."}
            </p>
          ) : (
            <ul className="max-h-[26rem] divide-y divide-border overflow-y-auto">
              {list.map((o) => (
                <li key={o.id}>
                  <button
                    type="button"
                    onClick={() => { setPicked(o.slug); onPick(o) }}
                    className="grid w-full grid-cols-[1fr_1fr_auto] items-center gap-3 px-3.5 py-3 text-left transition hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="flex min-w-0 items-center gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><Building2 className="size-4" /></span>
                      <span className="min-w-0">
                        <span className="block truncate font-semibold">{o.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{[o.tagline, o.city, o.country].filter(Boolean).join(" · ") || o.slug}</span>
                      </span>
                    </span>
                    <span className="min-w-0 space-y-0.5 text-xs text-muted-foreground">
                      {o.buildings.length === 0 ? (
                        <span>No buildings listed</span>
                      ) : (
                        o.buildings.map((b) => (
                          <span key={b.id} className="block truncate">
                            <span className="font-medium text-foreground">{b.name}</span>
                            {b.floors.length > 0 ? ` · ${floorsLabel(b.floors)}` : ""}
                          </span>
                        ))
                      )}
                    </span>
                    <ArrowRight className="size-4 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------- details step */

function DetailsStep({ slug, draft, setDraft, onBack, onNext }: { slug: string; draft: Draft; setDraft: (d: Draft) => void; onBack: () => void; onNext: () => void }) {
  const ctx = useOrganizationContext(slug)
  const account = useVisitorAccount()
  const hosts = usePublicHosts(slug, draft.department)
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })
  const categories = ctx.data?.visitor_categories ?? []
  const category = categories.find((c) => c.key === draft.category)
  const purposes = category?.purposes ?? []
  const building = ctx.data?.buildings.find((b) => String(b.id) === draft.building)
  const valid = draft.category && draft.purpose && (draft.purpose !== "Other" || draft.purpose_other.trim()) && draft.host

  // Pre-select the category the visitor chose at sign-up (e.g. Student) so
  // the usual case is "pick a purpose, pick a host".
  const accountCategory = account.data?.category ?? ""
  const buildingCount = ctx.data?.buildings.length ?? 0
  useEffect(() => {
    const next: Partial<Draft> = {}
    if (!draft.category && categories.length > 0) {
      next.category = categories.some((c) => c.key === accountCategory) ? accountCategory : categories[0].key
    }
    // One building: there is nothing to choose, so pre-select it.
    if (!draft.building && buildingCount === 1) next.building = String(ctx.data!.buildings[0].id)
    if (Object.keys(next).length) setDraft({ ...draft, ...next })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [categories.length, accountCategory, buildingCount])

  if (ctx.isLoading) return <Skeleton className="h-96 w-full" />
  if (ctx.isError || !ctx.data) return <Alert variant="danger">Couldn't load the booking form. <Button variant="ghost" size="sm" onClick={onBack}>Choose another organisation</Button></Alert>

  return (
    <Card>
      <CardContent className="space-y-6 p-5 sm:p-7">
        <div>
          <h2 className="text-xl font-bold tracking-tight">What brings you to {ctx.data.organization.name}?</h2>
          <p className="mt-1 text-sm text-muted-foreground">Choose who you are and what you're coming for; the team assigns your room when they approve.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="d-cat" label="I am a" required>
            <Select value={draft.category} onValueChange={(v) => set({ category: v, purpose: "", purpose_other: "" })}>
              <SelectTrigger id="d-cat"><SelectValue placeholder="Choose who you are" /></SelectTrigger>
              <SelectContent>{categories.map((c) => <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field id="d-purpose" label="Purpose of visit" required hint={purposes.find((p) => p.label === draft.purpose)?.room_type ? "You'll be sent to the right room for this." : undefined}>
            <Select value={draft.purpose} onValueChange={(v) => set({ purpose: v })} disabled={!draft.category}>
              <SelectTrigger id="d-purpose"><SelectValue placeholder={draft.category ? "Choose a purpose" : "Pick who you are first"} /></SelectTrigger>
              <SelectContent>{purposes.map((p) => <SelectItem key={p.label} value={p.label}>{p.label}</SelectItem>)}</SelectContent>
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
          <Field id="d-bld" label="Building" hint="Staff confirm the exact room when they approve.">
            <Select value={draft.building || "any"} onValueChange={(v) => set({ building: v === "any" ? "" : v, floor: "" })}>
              <SelectTrigger id="d-bld"><SelectValue placeholder="Choose a building" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Not sure</SelectItem>
                {ctx.data.buildings.map((b) => <SelectItem key={b.id} value={String(b.id)}>{b.name}{b.address ? ` · ${b.address}` : ""}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field id="d-floor" label="Floor" hint={building && building.floors.length === 0 ? "This building has no floors listed." : undefined}>
            <Select value={draft.floor || "any"} onValueChange={(v) => set({ floor: v === "any" ? "" : v })} disabled={!building || building.floors.length === 0}>
              <SelectTrigger id="d-floor"><SelectValue placeholder={building ? "Choose a floor" : "Pick a building first"} /></SelectTrigger>
              <SelectContent>
                <SelectItem value="any">Not sure</SelectItem>
                {(building?.floors ?? []).slice().sort((a, b) => a.level - b.level).map((f) => <SelectItem key={f.id} value={String(f.id)}>{f.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
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

/** The next `days` calendar days as dropdown options, starting today. */
function upcomingDays(days = 30): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = []
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  for (let i = 0; i < days; i++) {
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
    const label = `${i === 0 ? "Today · " : i === 1 ? "Tomorrow · " : ""}${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}`
    out.push({ value, label })
    d.setDate(d.getDate() + 1)
  }
  return out
}

function ScheduleStep({ slug, draft, setDraft, onBack, onNext }: { slug: string; draft: Draft; setDraft: (d: Draft) => void; onBack: () => void; onNext: () => void }) {
  const avail = usePublicAvailability(slug, draft.host, draft.visit_date)
  const days = upcomingDays()
  const slots = avail.data?.slots ?? []
  return (
    <Card>
      <CardContent className="space-y-6 p-5 sm:p-7">
        <div>
          <h2 className="text-xl font-bold tracking-tight">When would you like to come?</h2>
          <p className="mt-1 text-sm text-muted-foreground">Only times inside working hours when your host is free are listed.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="s-date" label="Date" required hint="Next 30 days.">
            <Select value={draft.visit_date} onValueChange={(v) => setDraft({ ...draft, visit_date: v, slot: null })}>
              <SelectTrigger id="s-date"><SelectValue placeholder="Choose a date" /></SelectTrigger>
              <SelectContent>{days.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field
            id="s-time"
            label="Arrival time"
            required
            hint={avail.data ? `${avail.data.slot_duration_minutes}-minute slots` : undefined}
            error={avail.isError ? formatApiError(avail.error) : draft.visit_date && avail.data && slots.length === 0 ? "No free slots on this day. Try another date." : undefined}
          >
            <Select
              value={draft.slot?.start ?? ""}
              onValueChange={(start) => setDraft({ ...draft, slot: slots.find((s) => s.start === start) ?? null })}
              disabled={!draft.visit_date || avail.isLoading || slots.length === 0}
            >
              <SelectTrigger id="s-time"><SelectValue placeholder={!draft.visit_date ? "Pick a date first" : avail.isLoading ? "Checking availability…" : "Choose a time"} /></SelectTrigger>
              <SelectContent>{slots.map((s) => <SelectItem key={s.start} value={s.start}>{s.start} – {s.end}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
        </div>
        {draft.visit_date && !avail.isLoading && slots.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted-foreground">Or tap a time</div>
            <SlotGrid slots={slots} value={draft.slot} onChange={(slot) => setDraft({ ...draft, slot })} loading={false} />
          </div>
        )}
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
        category: draft.category,
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
    ["Visit", `${categoryLabel(draft.category, ctx.data?.visitor_categories)} · ${draft.purpose === "Other" ? draft.purpose_other : draft.purpose}`],
    ["Meeting", host ? `${host.name}${host.designation ? `, ${host.designation}` : ""}${dept ? ` (${dept.name})` : ""}` : "—"],
    ["Location", [bld?.name, bld?.floors.find((f) => String(f.id) === draft.floor)?.name].filter(Boolean).join(", ") || "To be confirmed"],
    ["When", draft.slot ? `${formatDate(draft.visit_date)} · ${draft.slot.start}–${draft.slot.end}` : "—"],
    ["You", account.data ? `${account.data.full_name} · ${account.data.phone} · ${account.data.email}` : "—"],
    ...(account.data && (account.data.university || account.data.qualification || account.data.state)
      ? [["Profile", [account.data.qualification, account.data.passing_year ? `batch ${account.data.passing_year}` : "", account.data.university, account.data.state].filter(Boolean).join(" · ")] as [string, string]]
      : []),
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
          <Link to="/" aria-label="AdmitOne home"><LogoWordmark /></Link>
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
