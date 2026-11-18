import { useEffect, useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { ArrowLeft, BadgeCheck, CalendarClock, Send, ShieldAlert, UserRoundPlus, Zap } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Input, Textarea } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Switch } from "@/components/ui/Switch"
import { Field } from "@/components/widgets/Field"
import { PageHeader } from "@/components/widgets/PageHeader"
import { PassCard } from "@/components/visits/PassCard"
import { useAuth } from "@/lib/auth"
import { useBuildings, useHosts, useRegisterVisit, useVisitor, useWalkInVisit } from "@/lib/queries"
import { DOCUMENT_TYPES, VEHICLE_TYPES, formatApiError, type RegisterVisitResponse } from "@/lib/types"
import { todayIso } from "@/lib/utils"

const visitorSchema = z.object({
  full_name: z.string().trim().min(2, "Full name is required"),
  phone: z.string().trim().min(7, "Enter a valid phone number"),
  email: z.string().trim().email("Enter a valid email").or(z.literal("")),
  company: z.string().trim(),
  designation: z.string().trim(),
  document_type: z.string(),
  document_number: z.string().trim(),
  vehicle_type: z.string(),
  vehicle_number: z.string().trim(),
})

const visitSchema = z
  .object({
    purpose: z.string().trim().min(3, "Purpose should be at least 3 characters").max(200, "Keep it under 200 characters"),
    host_id: z.string().min(1, "Select a host"),
    building_id: z.string().min(1, "Select a building"),
    visit_date: z.string().min(1, "Pick a date"),
    expected_arrival: z.string().min(1, "Arrival time is required"),
    expected_exit: z.string().min(1, "Exit time is required"),
    notes: z.string().trim(),
  })
  .refine((d) => !d.expected_arrival || !d.expected_exit || d.expected_exit > d.expected_arrival, {
    message: "Exit time must be after arrival",
    path: ["expected_exit"],
  })

const formSchema = z.object({ visitor: visitorSchema, visit: visitSchema })
type FormValues = z.infer<typeof formSchema>

function nextHour(offset = 1): string {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + offset)
  return `${String(d.getHours()).padStart(2, "0")}:00`
}

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
  const [issued, setIssued] = useState<RegisterVisitResponse | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      visitor: { full_name: "", phone: "", email: "", company: "", designation: "", document_type: "none", document_number: "", vehicle_type: "none", vehicle_number: "" },
      visit: { purpose: "", host_id: "", building_id: "", visit_date: todayIso(), expected_arrival: nextHour(1), expected_exit: nextHour(2), notes: "" },
    },
  })
  const { register, handleSubmit, watch, setValue, reset, formState: { errors } } = form

  // Prefill from an existing visitor profile (opened from the directory).
  useEffect(() => {
    const v = prefill.data
    if (!v) return
    setValue("visitor.full_name", v.full_name)
    setValue("visitor.phone", v.phone)
    setValue("visitor.email", v.email ?? "")
    setValue("visitor.company", v.company ?? "")
    setValue("visitor.designation", v.designation ?? "")
    setValue("visitor.document_type", v.document_type || "none")
    setValue("visitor.document_number", v.document_number ?? "")
    setValue("visitor.vehicle_type", v.vehicle_type || "none")
    setValue("visitor.vehicle_number", v.vehicle_number ?? "")
  }, [prefill.data, setValue])

  // Default the host to the current user and the building to the only one.
  useEffect(() => {
    if (user && hosts.data?.some((h) => h.id === user.id) && !watch("visit.host_id")) setValue("visit.host_id", String(user.id))
  }, [hosts.data, user, setValue, watch])
  useEffect(() => {
    if (buildings.data?.length === 1 && !watch("visit.building_id")) setValue("visit.building_id", String(buildings.data[0].id))
  }, [buildings.data, setValue, watch])

  const vehicleType = watch("visitor.vehicle_type")
  const blacklisted = prefill.data?.is_blacklisted ?? false

  const onSubmit = async (values: FormValues) => {
    const payload = {
      visitor: {
        ...values.visitor,
        document_type: values.visitor.document_type === "none" ? "" : values.visitor.document_type,
        vehicle_type: values.visitor.vehicle_type === "none" ? "" : values.visitor.vehicle_type,
      },
      visit: {
        purpose: values.visit.purpose,
        host: Number(values.visit.host_id),
        building: Number(values.visit.building_id),
        visit_date: values.visit.visit_date,
        expected_arrival: values.visit.expected_arrival,
        expected_exit: values.visit.expected_exit,
        notes: values.visit.notes,
      },
    }
    try {
      const result = walkIn ? await walkInVisit.mutateAsync(payload) : await registerVisit.mutateAsync(payload)
      for (const warning of result.warnings ?? []) {
        toast.warning("Schedule clash", { description: warning, duration: 8000 })
      }
      reset()
      if (walkIn && result.visit.qr) {
        setIssued(result)
      } else {
        toast.success("Visit registered", { description: `${result.visitor.full_name} is waiting for host approval.` })
        navigate("/dashboard/approvals")
      }
    } catch (err) {
      toast.error(walkIn ? "Walk-in registration failed" : "Registration failed", { description: formatApiError(err) })
    }
  }

  const submitting = registerVisit.isPending || walkInVisit.isPending

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title={walkIn ? "Register a walk-in" : "Register a visit"}
        description={walkIn ? "The visitor is here now: the visit is approved instantly and a single-use pass is issued." : "Pre-register a visitor so the host can approve before they arrive. The visitor receives a QR pass by email on approval."}
        actions={
          <Button variant="ghost" asChild>
            <Link to="/dashboard/visitors"><ArrowLeft className="size-4" /> Back</Link>
          </Button>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-border bg-card p-4">
        <div className="space-y-0.5">
          <p className="flex items-center gap-2 text-sm font-medium"><Zap className="size-4 text-warning" /> Walk-in mode</p>
          <p className="text-xs text-muted-foreground">Skips host approval and issues the pass immediately. Use it for visitors already at the desk.</p>
        </div>
        <Switch checked={walkIn} onCheckedChange={setWalkIn} aria-label="Toggle walk-in registration" />
      </div>

      {prefill.data && (
        <Alert variant={blacklisted ? "danger" : "info"}>
          <BadgeCheck className="mt-0.5 size-4 shrink-0" />
          <span>
            Pre-filled from <strong>{prefill.data.full_name}</strong>'s profile.
            {blacklisted ? " This visitor is blacklisted and cannot be approved." : " Details you change here update their profile."}
          </span>
        </Alert>
      )}

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><UserRoundPlus className="size-4 text-primary" /> Visitor</CardTitle>
            <CardDescription>Phone number identifies a visitor: registering the same number again reuses their profile.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="full_name" label="Full name" required error={errors.visitor?.full_name?.message}><Input id="full_name" autoComplete="off" {...register("visitor.full_name")} /></Field>
            <Field id="phone" label="Phone" required error={errors.visitor?.phone?.message}><Input id="phone" inputMode="tel" autoComplete="off" {...register("visitor.phone")} /></Field>
            <Field id="email" label="Email" hint="Needed to email the QR pass." error={errors.visitor?.email?.message}><Input id="email" type="email" autoComplete="off" {...register("visitor.email")} /></Field>
            <Field id="company" label="Company"><Input id="company" {...register("visitor.company")} /></Field>
            <Field id="designation" label="Designation"><Input id="designation" {...register("visitor.designation")} /></Field>
            <Field id="document_type" label="ID document">
              <Select value={watch("visitor.document_type")} onValueChange={(v) => setValue("visitor.document_type", v)}>
                <SelectTrigger id="document_type"><SelectValue placeholder="Select" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">Not recorded</SelectItem>
                  {DOCUMENT_TYPES.map((d) => <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            {watch("visitor.document_type") !== "none" && (
              <Field id="document_number" label="Document number"><Input id="document_number" {...register("visitor.document_number")} /></Field>
            )}
            <Field id="vehicle_type" label="Vehicle">
              <Select value={vehicleType} onValueChange={(v) => { setValue("visitor.vehicle_type", v); if (v === "none") setValue("visitor.vehicle_number", "") }}>
                <SelectTrigger id="vehicle_type"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {VEHICLE_TYPES.map((v) => <SelectItem key={v.value} value={v.value}>{v.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            {vehicleType !== "none" && (
              <Field id="vehicle_number" label="Vehicle number"><Input id="vehicle_number" {...register("visitor.vehicle_number")} /></Field>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><CalendarClock className="size-4 text-accent" /> Visit</CardTitle>
            <CardDescription>Who they are meeting, where and when.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="purpose" label="Purpose of visit" required error={errors.visit?.purpose?.message} className="sm:col-span-2"><Input id="purpose" placeholder="e.g. Technical interview, vendor delivery" {...register("visit.purpose")} /></Field>
            <Field id="host_id" label="Host" required error={errors.visit?.host_id?.message ?? (hosts.isError ? "Couldn't load hosts." : undefined)} hint={hosts.data && hosts.data.length === 0 ? "Add team members in Settings → Team first." : undefined}>
              <Select value={watch("visit.host_id")} onValueChange={(v) => setValue("visit.host_id", v, { shouldValidate: true })}>
                <SelectTrigger id="host_id"><SelectValue placeholder="Select host" /></SelectTrigger>
                <SelectContent>
                  {(hosts.data ?? []).map((h) => <SelectItem key={h.id} value={String(h.id)}>{h.full_name}{h.id === user?.id ? " (you)" : ""}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field id="building_id" label="Building" required error={errors.visit?.building_id?.message ?? (buildings.isError ? "Couldn't load buildings." : undefined)}>
              <Select value={watch("visit.building_id")} onValueChange={(v) => setValue("visit.building_id", v, { shouldValidate: true })}>
                <SelectTrigger id="building_id"><SelectValue placeholder="Select building" /></SelectTrigger>
                <SelectContent>
                  {(buildings.data ?? []).map((b) => <SelectItem key={b.id} value={String(b.id)}>{b.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field id="visit_date" label="Visit date" required error={errors.visit?.visit_date?.message}><Input id="visit_date" type="date" min={todayIso()} {...register("visit.visit_date")} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field id="expected_arrival" label="Arrival" required error={errors.visit?.expected_arrival?.message}><Input id="expected_arrival" type="time" {...register("visit.expected_arrival")} /></Field>
              <Field id="expected_exit" label="Exit" required error={errors.visit?.expected_exit?.message}><Input id="expected_exit" type="time" {...register("visit.expected_exit")} /></Field>
            </div>
            <Field id="notes" label="Notes for security" className="sm:col-span-2"><Textarea id="notes" rows={3} placeholder="Anything the gate should know (escort required, equipment, parking…)" {...register("visit.notes")} /></Field>
          </CardContent>
        </Card>

        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Alert variant={walkIn ? "warning" : "info"} className="flex-1">
            <ShieldAlert className="mt-0.5 size-4 shrink-0" />
            <span>
              {walkIn
                ? <>The visit is created as <strong>Approved</strong> and a single-use QR pass is shown for the gate.</>
                : <>The visit starts as <strong>Pending</strong>. The visitor receives a QR pass once the host approves it.</>}
            </span>
          </Alert>
          <Button type="submit" size="lg" loading={submitting} disabled={blacklisted} className="min-w-44">
            {walkIn ? <><BadgeCheck className="size-4" /> Issue walk-in pass</> : <><Send className="size-4" /> Register visit</>}
          </Button>
        </div>
      </form>

      <Dialog open={issued !== null} onOpenChange={(open) => { if (!open) { setIssued(null); navigate("/dashboard/security") } }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><BadgeCheck className="size-5 text-success" /> Pass ready</DialogTitle>
            <DialogDescription>
              {issued?.visitor.full_name} is approved. Show this pass at the gate or print it.
              {issued?.visitor.email && <Badge tone="info" size="sm" className="ml-2">Emailed</Badge>}
            </DialogDescription>
          </DialogHeader>
          {issued && <PassCard visit={issued.visit} orgName={org?.name ?? "SecureGate"} />}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setIssued(null); setWalkIn(true) }}>Register another</Button>
            <Button onClick={() => { setIssued(null); navigate("/dashboard/security") }}>Go to gate</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
