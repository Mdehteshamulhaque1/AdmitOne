import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  Ban,
  CheckCircle2,
  DoorOpen,
  GraduationCap,
  IdCard,
  Keyboard,
  LogIn,
  LogOut,
  ScanLine,
  ShieldAlert,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Card, CardContent } from "@/components/ui/Card"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { StatusChip } from "@/components/widgets/StatusChip"
import { QrScanner } from "@/components/security/QrScanner"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { ID_PROOFS } from "@/components/visitor/booking"
import { useAuth } from "@/lib/auth"
import { useCheckIn, useCheckOut, useRoomScan, useRooms, useScanPass, useVisitList } from "@/lib/queries"
import { formatApiError, type ScanResult, type StudentPass, type Visit } from "@/lib/types"
import { cn, formatClock, formatDate, formatRelative } from "@/lib/utils"

type ScanMode = "gate" | "room"

interface ScanOutcome {
  ok: boolean
  title: string
  detail: string
  visit: Visit | null
  /** Set when a 6-month student pass was scanned. */
  student?: StudentPass | null
  direction?: "IN" | "OUT"
  at: Date
  payload: string
}

function ScanResultCard({ outcome, onDismiss, onOpen }: { outcome: ScanOutcome; onDismiss: () => void; onOpen: (v: Visit) => void }) {
  const v = outcome.visit
  const proof = v?.visitor.document_type ? ID_PROOFS.find((p) => p.value === v.visitor.document_type)?.label ?? v.visitor.document_type : null
  return (
    <div
      role="status"
      className={cn(
        "overflow-hidden rounded-2xl border-2 animate-scale-in",
        outcome.ok ? "border-success bg-success-soft" : "border-danger bg-danger-soft",
      )}
    >
      <div className={cn("flex items-center gap-3 px-4 py-3 text-white", outcome.ok ? "bg-success" : "bg-danger")}>
        {outcome.ok ? <CheckCircle2 className="size-7 shrink-0" /> : <XCircle className="size-7 shrink-0" />}
        <div className="min-w-0 flex-1">
          <div className="text-xl font-bold leading-tight">{outcome.title}</div>
          <div className="text-sm text-white/90">{outcome.detail}</div>
        </div>
        <Button variant="ghost" size="iconSm" onClick={onDismiss} aria-label="Dismiss" className="text-white hover:bg-white/15 hover:text-white">
          <XCircle className="size-4" />
        </Button>
      </div>
      {outcome.student && (
        <div className="flex gap-4 p-4">
          <Avatar name={outcome.student.student.full_name} src={outcome.student.student.photo} className="size-24 shrink-0 rounded-2xl text-2xl" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-lg font-semibold">{outcome.student.student.full_name}</span>
              <Badge tone="primary" size="sm"><GraduationCap className="size-3" /> Student</Badge>
              {outcome.ok && outcome.direction && (
                <Badge tone={outcome.direction === "IN" ? "success" : "neutral"} size="sm">{outcome.direction}</Badge>
              )}
            </div>
            <div className="text-sm text-muted-foreground">
              <span className="font-mono">{outcome.student.admission_number}</span> · {outcome.student.course}{outcome.student.batch ? ` · ${outcome.student.batch}` : ""}
            </div>
            <div className="text-xs text-muted-foreground">Pass valid until {formatDate(outcome.student.valid_until)}</div>
            {outcome.ok && (
              <div className="flex items-center gap-2 rounded-lg bg-card/80 px-2.5 py-1.5 text-xs">
                <IdCard className="size-4 shrink-0 text-muted-foreground" /> Match the face to the photo.
              </div>
            )}
            <div className="text-[11px] text-muted-foreground">{outcome.at.toLocaleTimeString()}</div>
          </div>
        </div>
      )}
      {v && (
        <div className="flex gap-4 p-4">
          <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-24 shrink-0 rounded-2xl text-2xl" />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate text-lg font-semibold">{v.visitor.full_name}</span>
              {v.visitor.is_blacklisted && <Badge tone="danger" size="sm"><Ban className="size-3" /> Blacklisted</Badge>}
            </div>
            <div className="text-sm text-muted-foreground">
              {v.purpose} · {v.host_name ? `meeting ${v.host_name}` : "no host"} · {formatClock(v.expected_arrival)}–{formatClock(v.expected_exit)}
            </div>
            {v.room_label && <div className="inline-flex items-center gap-1 text-sm font-medium text-primary"><DoorOpen className="size-4" /> Room {v.room_label}</div>}
            {outcome.ok && (
              <div className="flex items-center gap-2 rounded-lg bg-card/80 px-2.5 py-1.5 text-xs">
                <IdCard className="size-4 shrink-0 text-muted-foreground" />
                {proof ? (
                  <span>Check the original <strong>{proof}</strong>{v.visitor.document_number ? <> ending <span className="font-mono">{v.visitor.document_number.slice(-4)}</span></> : null} and match the face to the photo.</span>
                ) : (
                  <span>No ID was given online. Ask for a photo ID and match the face.</span>
                )}
              </div>
            )}
            <div className="flex items-center gap-2 pt-1">
              <StatusChip status={v.status} size="sm" />
              <span className="text-[11px] text-muted-foreground">{outcome.at.toLocaleTimeString()}</span>
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => onOpen(v)}>Details</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ReadyCard({ mode }: { mode: ScanMode }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-dashed border-border-strong bg-card px-4 py-4">
      <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary"><ScanLine className="size-6" /></span>
      <div>
        <div className="font-semibold">Ready to scan</div>
        <div className="text-sm text-muted-foreground">
          {mode === "gate" ? "Hold the visitor's QR pass up to the camera, or use a barcode scanner." : "Scan the visitor's pass at the room door to mark attendance."}
        </div>
      </div>
    </div>
  )
}

export function SecurityPage() {
  const { can } = useAuth()
  const scan = useScanPass()
  const roomScan = useRoomScan()
  const rooms = useRooms()
  const [mode, setMode] = useState<ScanMode>("gate")
  const [roomId, setRoomId] = useState("")
  const checkIn = useCheckIn()
  const checkOut = useCheckOut()
  const [outcome, setOutcome] = useState<ScanOutcome | null>(null)
  const [history, setHistory] = useState<ScanOutcome[]>([])
  const [manual, setManual] = useState("")
  const [search, setSearch] = useState("")
  const [selected, setSelected] = useState<Visit | null>(null)
  const [confirmManual, setConfirmManual] = useState<Visit | null>(null)
  const [cameraOn, setCameraOn] = useState(true)
  const inFlight = useRef(false)

  const inside = useVisitList({ status: "CHECKED_IN", ordering: "-checked_in_at", page_size: 100 }, { refetchInterval: 30_000 })
  const expected = useVisitList(
    { date: "today", status: "APPROVED,PENDING", ordering: "expected_arrival", page_size: 100 },
    { refetchInterval: 30_000 },
  )

  const handleScan = useCallback(
    async (payload: string) => {
      const value = payload.trim()
      if (!value || inFlight.current) return
      if (mode === "room" && !roomId) {
        toast.error("Choose the room first", { description: "Pick which room you are scanning at." })
        return
      }
      inFlight.current = true
      let result: ScanOutcome
      try {
        if (mode === "room") {
          // Room scans record attendance; they do not consume the pass.
          const res = await roomScan.mutateAsync({ payload: value, room: Number(roomId) })
          result = { ok: true, title: "Attendance recorded", detail: res.detail, visit: res.visit, at: new Date(), payload: value }
          toast.success("Attendance recorded", { description: res.visit?.visitor.full_name })
        } else {
          const res = await scan.mutateAsync({ payload: value })
          if (res.kind === "student") {
            const title = res.direction === "OUT" ? "Student exit" : "Student entry"
            result = { ok: true, title, detail: res.detail, visit: null, student: res.student_pass ?? null, direction: res.direction, at: new Date(), payload: value }
            toast.success(title, { description: res.student_pass?.student.full_name })
          } else {
            result = { ok: true, title: "Entry granted", detail: res.detail, visit: res.visit, at: new Date(), payload: value }
            toast.success("Checked in", { description: res.visit?.visitor.full_name })
          }
        }
      } catch (e) {
        const data = (e as { data?: ScanResult }).data
        result = {
          ok: false,
          title: mode === "room" ? "Not recorded" : "Entry denied",
          detail: data?.detail ?? formatApiError(e),
          visit: data?.visit ?? null,
          student: data?.student_pass ?? null,
          at: new Date(),
          payload: value,
        }
        toast.error(result.title, { description: result.detail })
      } finally {
        inFlight.current = false
      }
      setOutcome(result)
      setHistory((h) => [result, ...h].slice(0, 12))
    },
    [scan, roomScan, mode, roomId],
  )

  // Hardware barcode scanners type the payload and press Enter: capture it
  // globally when no field is focused so the gate works without the camera.
  useEffect(() => {
    let buffer = ""
    let last = 0
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName ?? "").toLowerCase()
      if (tag === "input" || tag === "textarea" || tag === "select") return
      const now = Date.now()
      if (now - last > 400) buffer = ""
      last = now
      if (e.key === "Enter") {
        if (buffer.includes("|")) void handleScan(buffer)
        buffer = ""
      } else if (e.key.length === 1) {
        buffer += e.key
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [handleScan])

  const doCheckOut = async (v: Visit) => {
    try {
      const res = await checkOut.mutateAsync(v.id)
      toast.success("Checked out", { description: res.detail })
    } catch (e) {
      toast.error("Check-out failed", { description: formatApiError(e) })
    }
  }

  const doManualCheckIn = async (v: Visit) => {
    try {
      const res = await checkIn.mutateAsync(v.id)
      toast.success("Checked in", { description: res.detail })
      setConfirmManual(null)
    } catch (e) {
      toast.error("Check-in failed", { description: formatApiError(e) })
    }
  }

  const filter = (list: Visit[]) => {
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter(
      (v) =>
        v.visitor.full_name.toLowerCase().includes(q) ||
        v.visitor.phone.includes(q) ||
        v.purpose.toLowerCase().includes(q) ||
        (v.host_name ?? "").toLowerCase().includes(q),
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={mode === "gate" ? "Gate scanner" : "Room attendance"}
        description={
          mode === "gate"
            ? "Scan a visitor's QR pass to verify the signature, check expiry and single-use, then admit them in one step."
            : "Scan a checked-in visitor's pass at the room door to record attendance. The same pass can be scanned at every room they attend."
        }
        actions={
          <Badge tone="success" className="gap-1.5">
            <ShieldCheck className="size-3" /> {inside.data.length} on site
          </Badge>
        }
      />

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          {outcome ? <ScanResultCard outcome={outcome} onDismiss={() => setOutcome(null)} onOpen={setSelected} /> : <ReadyCard mode={mode} />}
          <Card>
            <CardContent className="space-y-4 p-4 sm:p-5">
              <div className="grid grid-cols-2 gap-2">
                {([["gate", "Gate entry", ShieldCheck], ["room", "Room attendance", DoorOpen]] as const).map(([m, label, Icon]) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => { setMode(m); setOutcome(null) }}
                    aria-pressed={mode === m}
                    className={cn(
                      "flex items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition",
                      mode === m ? "border-primary bg-primary-soft text-primary" : "border-border bg-card hover:border-border-strong",
                    )}
                  >
                    <Icon className="size-4" /> {label}
                  </button>
                ))}
              </div>
              {mode === "room" && (
                <div className="space-y-1.5">
                  <label htmlFor="scan-room" className="text-xs font-medium text-muted-foreground">Scanning at</label>
                  <Select value={roomId} onValueChange={setRoomId}>
                    <SelectTrigger id="scan-room"><SelectValue placeholder={rooms.isLoading ? "Loading rooms…" : (rooms.data ?? []).length === 0 ? "No rooms set up yet" : "Choose the room"} /></SelectTrigger>
                    <SelectContent>
                      {(rooms.data ?? []).filter((r) => r.is_active).map((r) => (
                        <SelectItem key={r.id} value={String(r.id)}>{r.number}{r.name ? ` · ${r.name}` : ""} <span className="text-muted-foreground">({r.building_name}{r.floor_name ? `, ${r.floor_name}` : ""})</span></SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {(rooms.data ?? []).length === 0 && !rooms.isLoading && (
                    <p className="text-[11px] text-muted-foreground">Admins add rooms under Settings → Rooms.</p>
                  )}
                </div>
              )}
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold">
                  <ScanLine className="size-4 text-primary" /> Camera
                </h3>
                <Button variant="ghost" size="sm" onClick={() => setCameraOn((c) => !c)}>
                  {cameraOn ? "Turn off" : "Turn on"}
                </Button>
              </div>
              {cameraOn ? (
                <QrScanner onScan={(p) => void handleScan(p)} paused={scan.isPending || roomScan.isPending || (mode === "room" && !roomId)} />
              ) : (
                <div className="flex aspect-square items-center justify-center rounded-2xl border border-dashed border-border text-sm text-muted-foreground">
                  Camera is off
                </div>
              )}
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  void handleScan(manual)
                  setManual("")
                }}
                className="space-y-2"
              >
                <label htmlFor="manual-code" className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                  <Keyboard className="size-3.5" /> Or paste / type the pass code
                </label>
                <div className="flex gap-2">
                  <Input id="manual-code" value={manual} onChange={(e) => setManual(e.target.value)} placeholder="token|signature" className="font-mono text-xs" />
                  <Button type="submit" disabled={!manual.trim() || (mode === "room" && !roomId)} loading={scan.isPending || roomScan.isPending}>{mode === "room" ? "Record" : "Verify"}</Button>
                </div>
                <p className="text-[11px] text-muted-foreground">A USB/Bluetooth barcode scanner also works anywhere on this page.</p>
              </form>
            </CardContent>
          </Card>

          {history.length > 1 && (
            <Card>
              <CardContent className="p-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Recent scans</h3>
                <ul className="space-y-1.5">
                  {history.slice(1).map((h, i) => (
                    <li key={i} className="flex items-center gap-2 text-xs">
                      <span className={cn("size-2 rounded-full", h.ok ? "bg-success" : "bg-danger")} />
                      <span className="truncate">{h.visit?.visitor.full_name ?? (h.student ? `${h.student.student.full_name} (${h.direction ?? "student"})` : "Unknown pass")}</span>
                      <span className="ml-auto shrink-0 text-muted-foreground">{h.at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4 lg:col-span-3">
          {(inside.isError || expected.isError) && (
            <QueryErrorState message="Couldn't load the gate roster." retry={() => { void inside.refetch(); void expected.refetch() }} />
          )}
          <SearchInput value={search} onChange={setSearch} placeholder="Filter by name, phone, host or purpose…" delay={150} />
          <Tabs defaultValue="inside">
            <TabsList>
              <TabsTrigger value="inside">
                Inside now <span className="ml-1.5 rounded-full bg-success-soft px-1.5 text-xs text-success">{inside.data.length}</span>
              </TabsTrigger>
              <TabsTrigger value="expected">
                Expected today <span className="ml-1.5 rounded-full bg-info-soft px-1.5 text-xs text-info">{expected.data.length}</span>
              </TabsTrigger>
            </TabsList>

            <TabsContent value="inside" className="space-y-2.5">
              {inside.isLoading ? (
                [...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 w-full" />)
              ) : filter(inside.data).length === 0 ? (
                <EmptyState icon={<Users className="size-6" />} title="Nobody on site" description="Visitors who have checked in will appear here until they check out." />
              ) : (
                filter(inside.data).map((v) => (
                  <div key={v.id} className="card-surface flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
                    <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-10" />
                    <button type="button" onClick={() => setSelected(v)} className="min-w-0 flex-1 text-left">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold hover:text-primary">{v.visitor.full_name}</span>
                        <StatusChip status={v.status} size="sm" />
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {v.purpose} · in {formatRelative(v.checked_in_at)}{v.building_name ? ` · ${v.building_name}` : ""}{v.host_name ? ` · Host ${v.host_name}` : ""}
                      </div>
                    </button>
                    {can("checkout_visitor") && (
                      <Button variant="outline" onClick={() => doCheckOut(v)} disabled={checkOut.isPending}>
                        <LogOut className="size-4" /> Check out
                      </Button>
                    )}
                  </div>
                ))
              )}
            </TabsContent>

            <TabsContent value="expected" className="space-y-2.5">
              {expected.isLoading ? (
                [...Array(3)].map((_, i) => <Skeleton key={i} className="h-20 w-full" />)
              ) : filter(expected.data).length === 0 ? (
                <EmptyState icon={<ShieldCheck className="size-6" />} title="Queue is clear" description="Approved visitors scheduled for today will appear here." />
              ) : (
                filter(expected.data).map((v) => (
                  <div key={v.id} className="card-surface flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
                    <span className="w-12 shrink-0 font-mono text-xs text-muted-foreground">{formatClock(v.expected_arrival)}</span>
                    <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-10" />
                    <button type="button" onClick={() => setSelected(v)} className="min-w-0 flex-1 text-left">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold hover:text-primary">{v.visitor.full_name}</span>
                        <StatusChip status={v.status} size="sm" />
                        {v.arriving_at && <Badge tone="cyan" size="sm">On the way</Badge>}
                        {v.visitor.is_blacklisted && <Badge tone="danger" size="sm"><Ban className="size-3" /> Blacklisted</Badge>}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {v.purpose} · until {formatClock(v.expected_exit)} · Host {v.host_name || "—"}
                      </div>
                    </button>
                    {v.status === "APPROVED" ? (
                      can("checkin_visitor") && (
                        <Button variant="outline" onClick={() => setConfirmManual(v)} disabled={v.visitor.is_blacklisted}>
                          <LogIn className="size-4" /> Manual check-in
                        </Button>
                      )
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs text-warning">
                        <ShieldAlert className="size-3.5" /> Needs approval
                      </span>
                    )}
                  </div>
                ))
              )}
            </TabsContent>
          </Tabs>
        </div>
      </div>

      <ConfirmDialog
        open={confirmManual !== null}
        onOpenChange={(o) => !o && setConfirmManual(null)}
        title="Check in without scanning?"
        description={confirmManual ? `${confirmManual.visitor.full_name} will be admitted and their pass marked as used. Use this only when the visitor cannot present the QR code.` : undefined}
        confirmLabel="Check in"
        loading={checkIn.isPending}
        onConfirm={() => { if (confirmManual) void doManualCheckIn(confirmManual) }}
      />
      <VisitDrawer visitId={selected?.id ?? null} initial={selected} open={selected !== null} onOpenChange={(o) => !o && setSelected(null)} />
    </div>
  )
}
