import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import {
  Ban,
  CheckCircle2,
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
import { Skeleton } from "@/components/ui/Skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { StatusChip } from "@/components/widgets/StatusChip"
import { QrScanner } from "@/components/security/QrScanner"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { useAuth } from "@/lib/auth"
import { useCheckIn, useCheckOut, useScanPass, useVisitList } from "@/lib/queries"
import { formatApiError, type ScanResult, type Visit } from "@/lib/types"
import { cn, formatClock, formatRelative } from "@/lib/utils"

interface ScanOutcome {
  ok: boolean
  detail: string
  visit: Visit | null
  at: Date
  payload: string
}

function ScanResultCard({ outcome, onDismiss, onOpen }: { outcome: ScanOutcome; onDismiss: () => void; onOpen: (v: Visit) => void }) {
  const v = outcome.visit
  return (
    <div
      role="status"
      className={cn(
        "rounded-2xl border p-4 animate-scale-in",
        outcome.ok ? "border-success/40 bg-success-soft" : "border-danger/40 bg-danger-soft",
      )}
    >
      <div className="flex items-start gap-3">
        <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl", outcome.ok ? "bg-success text-white" : "bg-danger text-white")}>
          {outcome.ok ? <CheckCircle2 className="size-6" /> : <XCircle className="size-6" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className={cn("text-base font-bold", outcome.ok ? "text-success" : "text-danger")}>
            {outcome.ok ? "Entry granted" : "Entry denied"}
          </div>
          <div className="text-sm text-foreground">{outcome.detail}</div>
          {v && (
            <div className="mt-3 flex items-center gap-3 rounded-xl bg-card/70 p-3">
              <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-10" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-semibold">{v.visitor.full_name}</span>
                  <StatusChip status={v.status} size="sm" />
                  {v.visitor.is_blacklisted && <Badge tone="danger" size="sm"><Ban className="size-3" /> Blacklisted</Badge>}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {v.purpose} · {v.host_name ? `Host ${v.host_name}` : "No host"} · {formatClock(v.expected_arrival)}–{formatClock(v.expected_exit)}
                </div>
              </div>
              <Button size="sm" variant="outline" onClick={() => onOpen(v)}>Details</Button>
            </div>
          )}
          <div className="mt-2 text-[11px] text-muted-foreground">{outcome.at.toLocaleTimeString()}</div>
        </div>
        <Button variant="ghost" size="iconSm" onClick={onDismiss} aria-label="Dismiss">
          <XCircle className="size-4" />
        </Button>
      </div>
    </div>
  )
}

export function SecurityPage() {
  const { can } = useAuth()
  const scan = useScanPass()
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
      inFlight.current = true
      let result: ScanOutcome
      try {
        const res = await scan.mutateAsync({ payload: value })
        result = { ok: true, detail: res.detail, visit: res.visit, at: new Date(), payload: value }
        toast.success("Checked in", { description: res.visit?.visitor.full_name })
      } catch (e) {
        const data = (e as { data?: ScanResult }).data
        result = {
          ok: false,
          detail: data?.detail ?? formatApiError(e),
          visit: data?.visit ?? null,
          at: new Date(),
          payload: value,
        }
        toast.error("Entry denied", { description: result.detail })
      } finally {
        inFlight.current = false
      }
      setOutcome(result)
      setHistory((h) => [result, ...h].slice(0, 12))
    },
    [scan],
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
        title="Gate scanner"
        description="Scan a visitor's QR pass to verify the signature, check expiry and single-use, then admit them in one step."
        actions={
          <Badge tone="success" className="gap-1.5">
            <ShieldCheck className="size-3" /> {inside.data.length} on site
          </Badge>
        }
      />

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-2">
          {outcome && <ScanResultCard outcome={outcome} onDismiss={() => setOutcome(null)} onOpen={setSelected} />}
          <Card>
            <CardContent className="space-y-4 p-4 sm:p-5">
              <div className="flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold">
                  <ScanLine className="size-4 text-primary" /> Camera
                </h3>
                <Button variant="ghost" size="sm" onClick={() => setCameraOn((c) => !c)}>
                  {cameraOn ? "Turn off" : "Turn on"}
                </Button>
              </div>
              {cameraOn ? (
                <QrScanner onScan={(p) => void handleScan(p)} paused={scan.isPending} />
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
                  <Button type="submit" disabled={!manual.trim()} loading={scan.isPending}>Verify</Button>
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
                      <span className="truncate">{h.visit?.visitor.full_name ?? "Unknown pass"}</span>
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
