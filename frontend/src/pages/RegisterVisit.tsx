import { useEffect, useMemo, useState, type ReactNode } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { ArrowLeft, BadgeCheck, CalendarClock, ChevronDown, History, Send, UserRoundCheck, Zap } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Input, Textarea } from "@/components/ui/Input"
import { Field } from "@/components/widgets/Field"
import { Chip, ChoiceTile } from "@/components/widgets/Choice"
import { PageHeader } from "@/components/widgets/PageHeader"
import { SearchableSelect } from "@/components/widgets/SearchableSelect"
import { PassCard } from "@/components/visits/PassCard"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { useBuildings, useHosts, useRegisterVisit, useVisitor, useWalkInVisit } from "@/lib/queries"
import { NOTE_PRESETS } from "@/lib/student-options"
import { DOCUMENT_TYPES, ROLE_LABELS, VEHICLE_TYPES, formatApiError, type RegisterVisitResponse, type Visitor } from "@/lib/types"
import { cn, todayIso } from "@/lib/utils"

/** What visitors usually come to the desk for; reception can still type anything. */
const COMMON_PURPOSES = ["Interview", "Meeting", "Training session", "Fee payment / admission", "Counselling", "Delivery", "Maintenance", "Casual visit"]
const DURATIONS = [
  { minutes: 30, label: "30 min" },
  { minutes: 60, label: "1 hour" },
  { minutes: 120, label: "2 hours" },
  { minutes: 240, label: "Half day" },
]

const pad = (n: number) => String(n).padStart(2, "0")
function nowHHMM() {
  const d = new Date()
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function nextHalfHour() {
  const d = new Date()
  d.setMinutes(d.getMinutes() < 30 ? 30 : 60, 0, 0)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function addMinutes(hhmm: string, minutes: number) {
  const [h, m] = hhmm.split(":").map(Number)
  const total = Math.min(h * 60 + m + minutes, 23 * 60 + 59)
  return `${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}
function isoInDays(days: number) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function Section({ step, title, hint, children }: { step: number; title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-card shadow-card">
      <header className="flex items-start gap-3 border-b border-border px-5 py-4 sm:px-6">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-sm font-semibold text-primary tabular-nums">{step}</span>
        <div>
          <h2 className="font-semibold">{title}</h2>
          {hint && <p className="text-sm text-muted-foreground">{hint}</p>}
        </div>
      </header>
      <div className="space-y-5 p-5 sm:p-6">{children}</div>
    </section>
  )
}

function Label({ children, required }: { children: ReactNode; required?: boolean }) {
  return (
    <div className="mb-2 text-sm font-medium">
      {children} {required && <span className="text-danger">*</span>}
    </div>
  )
}

const EMPTY_VISITOR = { full_name: "", phone: "", email: "", company: "", designation: "", document_type: "", document_number: "", vehicle_type: "none", vehicle_number: "" }

export function RegisterVisitPage() {
  const navigate = useNavigate()
  const { org, user } = useAuth()
  const [searchParams] = useSearchParams()
  const prefillId = Number(searchParams.get("visitor") ?? "") || null
  const prefill = useVisitor(prefillId)
  const hosts = useHosts()
  const buildings = useBuildings()
  const registerVisit = useRegisterVisit()
  const walkInVisit = useWalkInVisit()

  const [walkIn, setWalkIn] = useState(searchParams.get("walkin") === "1")
  const [visitor, setVisitor] = useState(EMPTY_VISITOR)
  const [usedProfile, setUsedProfile] = useState<Visitor | null>(null)
  const [purpose, setPurpose] = useState("")
  const [hostId, setHostId] = useState("")
  const [buildingId, setBuildingId] = useState("")
  const [date, setDate] = useState(todayIso())
  const [arrival, setArrival] = useState(nextHalfHour())
  const [duration, setDuration] = useState(60)
  const [notes, setNotes] = useState<string[]>([])
  const [extraNote, setExtraNote] = useState("")
  const [showMore, setShowMore] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [issued, setIssued] = useState<RegisterVisitResponse | null>(null)

  const setV = (k: keyof typeof EMPTY_VISITOR, value: string) => {
    setVisitor((v) => ({ ...v, [k]: value }))
    setErrors((e) => ({ ...e, [k]: "" }))
  }
  const fill = (v: Visitor) => {
    setVisitor({
      full_name: v.full_name,
      phone: v.phone,
      email: v.email ?? "",
      company: v.company ?? "",
      designation: v.designation ?? "",
      document_type: v.document_type ?? "",
      document_number: v.document_number ?? "",
      vehicle_type: v.vehicle_type || "none",
      vehicle_number: v.vehicle_number ?? "",
    })
    setUsedProfile(v)
    setErrors({})
  }

  // Opened from the visitor directory: start from that profile.
  useEffect(() => {
    if (prefill.data) fill(prefill.data)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill.data])

  // Phone first, like a front desk: a returning visitor is found by number.
  const digits = visitor.phone.replace(/\D/g, "")
  const [lookup, setLookup] = useState("")
  useEffect(() => {
    const t = setTimeout(() => setLookup(digits.length >= 6 ? digits : ""), 300)
    return () => clearTimeout(t)
  }, [digits])
  const match = useQuery({
    queryKey: ["visitors", "phone-lookup", lookup],
    queryFn: () => api<{ results: Visitor[] }>(`/api/visitors/?q=${encodeURIComponent(lookup)}&page_size=3`),
    enabled: Boolean(lookup) && !usedProfile,
    staleTime: 30_000,
  })
  const returning = match.data?.results.find((v) => v.phone.replace(/\D/g, "").endsWith(lookup) || lookup.endsWith(v.phone.replace(/\D/g, "")))

  // Sensible defaults: you are the host; the only building is the building.
  useEffect(() => {
    if (!hostId && user && hosts.data?.some((h) => h.id === user.id)) setHostId(String(user.id))
  }, [hosts.data, user, hostId])
  useEffect(() => {
    if (!buildingId && buildings.data?.length) setBuildingId(String(buildings.data[0].id))
  }, [buildings.data, buildingId])

  const start = walkIn ? nowHHMM() : arrival
  const end = addMinutes(start, duration)
  const host = hosts.data?.find((h) => String(h.id) === hostId)
  const blacklisted = Boolean(usedProfile?.is_blacklisted || prefill.data?.is_blacklisted)
  const hostList = hosts.data ?? []

  const summary = useMemo(() => {
    const who = visitor.full_name.trim() || "Visitor"
    const when = walkIn ? `now until ${end}` : `${date === todayIso() ? "today" : date} ${start}–${end}`
    return `${walkIn ? "Walk-in" : "Pre-registered"}: ${who}${purpose ? `, ${purpose}` : ""}${host ? `, with ${host.id === user?.id ? "you" : host.full_name}` : ""}, ${when}`
  }, [visitor.full_name, walkIn, end, date, start, purpose, host, user])

  const validate = () => {
    const e: Record<string, string> = {}
    if (visitor.full_name.trim().length < 2) e.full_name = "Enter the visitor's full name."
    if (digits.length < 7) e.phone = "Enter a phone number with at least 7 digits."
    if (visitor.email && !/^\S+@\S+\.\S+$/.test(visitor.email)) e.email = "Enter a valid email, or leave it empty."
    if (purpose.trim().length < 3) e.purpose = "Choose or type a purpose (at least 3 characters)."
    if (!hostId) e.host = "Choose who they're meeting."
    if (!buildingId) e.building = "Choose a building."
    if (!walkIn && !date) e.date = "Pick a date."
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const submit = async () => {
    if (!validate()) {
      toast.error("Some details are missing", { description: "Check the highlighted fields." })
      return
    }
    const payload = {
      visitor: {
        ...visitor,
        document_type: visitor.document_type,
        vehicle_type: visitor.vehicle_type === "none" ? "" : visitor.vehicle_type,
      },
      visit: {
        purpose: purpose.trim(),
        host: Number(hostId),
        building: Number(buildingId),
        visit_date: walkIn ? todayIso() : date,
        expected_arrival: start,
        expected_exit: end,
        notes: [...notes, extraNote.trim()].filter(Boolean).join("; "),
      },
    }
    try {
      const result = walkIn ? await walkInVisit.mutateAsync(payload) : await registerVisit.mutateAsync(payload)
      for (const warning of result.warnings ?? []) toast.warning("Schedule clash", { description: warning, duration: 8000 })
      if (walkIn && result.visit.qr) {
        setIssued(result)
      } else {
        toast.success("Visit registered", { description: `${result.visitor.full_name} is waiting for host approval.` })
        navigate("/dashboard/approvals")
      }
    } catch (err) {
      toast.error(walkIn ? "The walk-in pass wasn't issued" : "The visit wasn't registered", { description: formatApiError(err) })
    }
  }

  const resetForm = () => {
    setVisitor(EMPTY_VISITOR)
    setUsedProfile(null)
    setPurpose("")
    setNotes([])
    setExtraNote("")
    setErrors({})
  }

  const submitting = registerVisit.isPending || walkInVisit.isPending

  return (
    <div className="mx-auto max-w-3xl space-y-5 pb-28">
      <PageHeader
        title="Register a visit"
        description="For visitors at the desk now, or people you want to let in later."
        actions={
          <Button variant="ghost" asChild>
            <Link to="/dashboard/visits"><ArrowLeft className="size-4" /> Visits</Link>
          </Button>
        }
      />

      <div role="radiogroup" aria-label="Visit type" className="grid gap-3 sm:grid-cols-2">
        <ChoiceTile
          selected={walkIn}
          onSelect={() => setWalkIn(true)}
          icon={<Zap className="size-5" />}
          title="Here now (walk-in)"
          description="Approved straight away; the pass is shown to hand over at the gate."
        />
        <ChoiceTile
          selected={!walkIn}
          onSelect={() => setWalkIn(false)}
          icon={<CalendarClock className="size-5" />}
          title="Coming later"
          description="Pre-register for a date and time; the host approves and the pass is emailed."
        />
      </div>

      {blacklisted && (
        <Alert variant="danger"><span>This visitor is on the blacklist and can't be admitted. Talk to an admin before continuing.</span></Alert>
      )}

      <Section step={1} title="Visitor" hint="Start with the phone number: returning visitors are found automatically.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="phone" label="Phone" required error={errors.phone}>
            <Input id="phone" inputMode="tel" autoComplete="off" value={visitor.phone} onChange={(e) => { setV("phone", e.target.value); if (usedProfile) setUsedProfile(null) }} placeholder="Mobile number" />
          </Field>
          <Field id="full_name" label="Full name" required error={errors.full_name}>
            <Input id="full_name" autoComplete="off" value={visitor.full_name} onChange={(e) => setV("full_name", e.target.value)} />
          </Field>
        </div>
        {returning && !usedProfile && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-primary/40 bg-primary-soft px-4 py-3 text-sm">
            <History className="size-4 text-primary" />
            <span className="min-w-0 flex-1">
              <span className="font-semibold">{returning.full_name}</span> has visited before
              {returning.visit_count ? ` (${returning.visit_count} visit${returning.visit_count === 1 ? "" : "s"})` : ""}
              {returning.company ? `, ${returning.company}` : ""}.
              {returning.is_blacklisted && <Badge tone="danger" size="sm" className="ml-2">Blacklisted</Badge>}
            </span>
            <Button size="sm" variant="outline" onClick={() => fill(returning)}>Use these details</Button>
          </div>
        )}
        {usedProfile && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <UserRoundCheck className="size-4 text-success" /> Using {usedProfile.full_name}'s saved details. Changes here update their profile.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="email" label="Email" hint={walkIn ? "Optional." : "Needed to email the QR pass."} error={errors.email}>
            <Input id="email" type="email" autoComplete="off" value={visitor.email} onChange={(e) => setV("email", e.target.value)} />
          </Field>
          <Field id="company" label="Company or college" hint="Optional.">
            <Input id="company" value={visitor.company} onChange={(e) => setV("company", e.target.value)} />
          </Field>
        </div>

        <div>
          <button type="button" onClick={() => setShowMore((s) => !s)} aria-expanded={showMore} className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
            <ChevronDown className={cn("size-4 transition-transform", showMore && "rotate-180")} />
            {showMore ? "Hide ID and vehicle" : "Add ID or vehicle (optional)"}
          </button>
          {showMore && (
            <div className="mt-4 space-y-4">
              <Field id="designation" label="Designation">
                <Input id="designation" value={visitor.designation} onChange={(e) => setV("designation", e.target.value)} placeholder="e.g. HR Manager" />
              </Field>
              <div>
                <Label>ID document</Label>
                <div role="radiogroup" aria-label="ID document" className="flex flex-wrap gap-2">
                  <Chip role="radio" selected={!visitor.document_type} onClick={() => { setV("document_type", ""); setV("document_number", "") }}>Not recorded</Chip>
                  {DOCUMENT_TYPES.map((d) => (
                    <Chip key={d.value} role="radio" selected={visitor.document_type === d.value} onClick={() => setV("document_type", d.value)}>{d.label}</Chip>
                  ))}
                </div>
                {visitor.document_type && (
                  <Input className="mt-3" aria-label="Document number" value={visitor.document_number} onChange={(e) => setV("document_number", e.target.value)} placeholder="Document number" />
                )}
              </div>
              <div>
                <Label>Vehicle</Label>
                <div role="radiogroup" aria-label="Vehicle" className="flex flex-wrap gap-2">
                  {VEHICLE_TYPES.map((v) => (
                    <Chip key={v.value} role="radio" selected={visitor.vehicle_type === v.value} onClick={() => { setV("vehicle_type", v.value); if (v.value === "none") setV("vehicle_number", "") }}>{v.label}</Chip>
                  ))}
                </div>
                {visitor.vehicle_type !== "none" && (
                  <Input className="mt-3" aria-label="Vehicle number" value={visitor.vehicle_number} onChange={(e) => setV("vehicle_number", e.target.value)} placeholder="Vehicle number, e.g. UP16 AB 1234" />
                )}
              </div>
            </div>
          )}
        </div>
      </Section>

      <Section step={2} title="Visit" hint="Why they're here and who they're meeting.">
        <div>
          <Label required>Purpose</Label>
          <div role="radiogroup" aria-label="Common purposes" className="flex flex-wrap gap-2">
            {COMMON_PURPOSES.map((p) => (
              <Chip key={p} role="radio" selected={purpose === p} onClick={() => { setPurpose(p); setErrors((e) => ({ ...e, purpose: "" })) }}>{p}</Chip>
            ))}
          </div>
          <Input
            className="mt-3"
            aria-label="Purpose of visit"
            value={COMMON_PURPOSES.includes(purpose) ? "" : purpose}
            onChange={(e) => { setPurpose(e.target.value); setErrors((er) => ({ ...er, purpose: "" })) }}
            placeholder="Or type the purpose, e.g. Technical interview for Java role"
            maxLength={200}
          />
          {errors.purpose && <p className="mt-1.5 text-xs text-danger">{errors.purpose}</p>}
        </div>

        <div>
          <Label required>Meeting</Label>
          {hosts.isError ? (
            <p className="text-sm text-danger">The list of people didn't load.</p>
          ) : hostList.length === 0 && !hosts.isLoading ? (
            <p className="text-sm text-muted-foreground">Nobody can host visits yet. Add team members under Team first.</p>
          ) : hostList.length <= 6 ? (
            <div role="radiogroup" aria-label="Host" className="grid gap-3 sm:grid-cols-2">
              {hostList.map((h) => (
                <ChoiceTile
                  key={h.id}
                  selected={hostId === String(h.id)}
                  onSelect={() => { setHostId(String(h.id)); setErrors((e) => ({ ...e, host: "" })) }}
                  icon={<span className="text-sm font-semibold">{h.full_name.split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("")}</span>}
                  title={`${h.full_name}${h.id === user?.id ? " (you)" : ""}`}
                  description={ROLE_LABELS[h.role]}
                />
              ))}
            </div>
          ) : (
            <SearchableSelect
              id="host"
              value={hostId}
              onChange={(v) => { setHostId(v); setErrors((e) => ({ ...e, host: "" })) }}
              options={hostList.map((h) => ({ value: String(h.id), label: `${h.full_name}${h.id === user?.id ? " (you)" : ""}`, description: ROLE_LABELS[h.role] }))}
              placeholder="Search people"
            />
          )}
          {errors.host && <p className="mt-1.5 text-xs text-danger">{errors.host}</p>}
        </div>

        {(buildings.data?.length ?? 0) > 1 && (
          <div>
            <Label required>Building</Label>
            <div role="radiogroup" aria-label="Building" className="flex flex-wrap gap-2">
              {buildings.data!.map((b) => (
                <Chip key={b.id} role="radio" selected={buildingId === String(b.id)} onClick={() => setBuildingId(String(b.id))}>{b.name}</Chip>
              ))}
            </div>
          </div>
        )}
      </Section>

      <Section step={3} title="When" hint={walkIn ? "They're here now. How long will they stay?" : "When they'll arrive and how long they'll stay."}>
        {!walkIn && (
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label required>Date</Label>
              <div role="radiogroup" aria-label="Date" className="flex flex-wrap gap-2">
                <Chip role="radio" selected={date === todayIso()} onClick={() => setDate(todayIso())}>Today</Chip>
                <Chip role="radio" selected={date === isoInDays(1)} onClick={() => setDate(isoInDays(1))}>Tomorrow</Chip>
                <Input type="date" aria-label="Pick another date" min={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} className="h-9 w-auto" />
              </div>
              {errors.date && <p className="mt-1.5 text-xs text-danger">{errors.date}</p>}
            </div>
            <div>
              <Label required>Arrival time</Label>
              <Input type="time" aria-label="Arrival time" value={arrival} onChange={(e) => setArrival(e.target.value)} className="h-9 w-36" />
            </div>
          </div>
        )}
        <div>
          <Label required>How long</Label>
          <div role="radiogroup" aria-label="Duration" className="flex flex-wrap gap-2">
            {DURATIONS.map((d) => (
              <Chip key={d.minutes} role="radio" selected={duration === d.minutes} onClick={() => setDuration(d.minutes)}>{d.label}</Chip>
            ))}
          </div>
          <p className="mt-2 text-sm text-muted-foreground tabular-nums">
            {walkIn ? "From now" : `From ${start}`} until <span className="font-medium text-foreground">{end}</span>
          </p>
        </div>
        <div>
          <Label>Notes for the gate</Label>
          <div className="flex flex-wrap gap-2">
            {NOTE_PRESETS.map((n) => (
              <Chip key={n} selected={notes.includes(n)} onClick={() => setNotes((cur) => (cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]))}>{n}</Chip>
            ))}
          </div>
          <Textarea className="mt-3" rows={2} value={extraNote} onChange={(e) => setExtraNote(e.target.value)} placeholder="Anything else security should know" aria-label="Other notes" />
        </div>
      </Section>

      <div className="fixed inset-x-0 bottom-16 z-30 border-t border-border bg-background/95 backdrop-blur lg:bottom-0 lg:left-auto lg:w-[calc(100%-var(--sidebar-w,16rem))]">
        <div className="mx-auto flex max-w-3xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p className="min-w-0 truncate text-sm text-muted-foreground" title={summary}>{summary}</p>
          <Button size="lg" onClick={submit} loading={submitting} disabled={blacklisted} className="shrink-0">
            {walkIn ? <><BadgeCheck className="size-4" /> Issue pass now</> : <><Send className="size-4" /> Register visit</>}
          </Button>
        </div>
      </div>

      <Dialog open={issued !== null} onOpenChange={(open) => { if (!open) { setIssued(null); resetForm() } }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><BadgeCheck className="size-5 text-success" /> Pass ready</DialogTitle>
            <DialogDescription>
              {issued?.visitor.full_name} is approved. Show this pass at the gate or print it.
              {issued?.visitor.email && <Badge tone="info" size="sm" className="ml-2">Emailed</Badge>}
            </DialogDescription>
          </DialogHeader>
          {issued && <PassCard visit={issued.visit} orgName={org?.name ?? "AdmitOne"} />}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setIssued(null); resetForm() }}>Register another</Button>
            <Button onClick={() => { setIssued(null); navigate("/dashboard/security") }}>Go to gate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
