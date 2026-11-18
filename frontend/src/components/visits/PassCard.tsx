import { useRef } from "react"
import { QRCodeSVG } from "qrcode.react"
import { Clock, Printer, ShieldCheck, ShieldX } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Badge } from "@/components/ui/Badge"
import { CopyButton } from "@/components/widgets/CopyButton"
import type { Visit } from "@/lib/types"
import { formatDate, formatDateTime } from "@/lib/utils"

export function passPayload(visit: Visit): string | null {
  // The raw credential is only sent to roles that print passes; the gate
  // role sees status fields only.
  return visit.qr?.token && visit.qr?.signature ? `${visit.qr.token}|${visit.qr.signature}` : null
}

/** Opens a print-friendly window with the pass; works without extra libraries. */
export function printPass(visit: Visit, orgName: string) {
  const payload = passPayload(visit)
  if (!payload) return
  const svg = document.getElementById(`pass-qr-${visit.id}`)?.outerHTML ?? ""
  const w = window.open("", "_blank", "width=480,height=640")
  if (!w) return
  const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] ?? c)
  w.document.write(`<!doctype html><html><head><title>Visitor pass</title>
  <style>
    body{font-family:Inter,system-ui,sans-serif;margin:0;padding:32px;color:#0b1220;background:#fff}
    .card{border:1px solid #cbd5e1;border-radius:20px;padding:28px;max-width:380px;margin:0 auto;text-align:center}
    .org{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#64748b;font-weight:600}
    h1{font-size:22px;margin:8px 0 2px}
    .meta{font-size:13px;color:#475569;margin:2px 0}
    .qr{margin:20px auto 12px;width:200px;height:200px}
    .qr svg{width:200px;height:200px}
    .note{font-size:11px;color:#64748b;margin-top:14px}
    @media print{body{padding:0}}
  </style></head><body>
  <div class="card">
    <div class="org">${esc(orgName)} · Visitor pass</div>
    <h1>${esc(visit.visitor.full_name)}</h1>
    <div class="meta">${esc(visit.visitor.company || "")}</div>
    <div class="meta">${esc(visit.purpose)} · ${esc(formatDate(visit.visit_date))} · ${esc(visit.expected_arrival.slice(0, 5))}–${esc(visit.expected_exit.slice(0, 5))}</div>
    ${visit.host_name ? `<div class="meta">Host: ${esc(visit.host_name)}</div>` : ""}
    <div class="qr">${svg}</div>
    <div class="meta">Single-use · expires ${esc(formatDateTime(visit.qr?.expires_at))}</div>
    <div class="note">Present this code at the security gate. Ref ${esc(visit.visit_id.slice(0, 8).toUpperCase())}</div>
  </div>
  <script>window.onload=function(){window.print()}</script>
  </body></html>`)
  w.document.close()
}

export function PassCard({ visit, orgName, compact = false }: { visit: Visit; orgName: string; compact?: boolean }) {
  const payload = passPayload(visit)
  const ref = useRef<HTMLDivElement>(null)
  if (!visit.qr) {
    return (
      <div className="rounded-2xl border border-dashed border-border px-4 py-4 text-center text-xs text-muted-foreground">
        No QR pass on this visit. Approving the visit issues one automatically.
      </div>
    )
  }
  if (!payload) {
    // Status only: this role scans passes at the gate and does not print them.
    return (
      <div className={`flex items-center justify-between gap-3 rounded-2xl border p-4 text-sm ${visit.qr.is_valid ? "border-primary/30 bg-primary-soft" : "border-border bg-surface-2"}`}>
        <span className={`flex items-center gap-2 font-semibold ${visit.qr.is_valid ? "text-primary" : "text-muted-foreground"}`}>
          {visit.qr.is_valid ? <ShieldCheck className="size-4" /> : <ShieldX className="size-4" />}
          {visit.qr.is_valid ? "Pass issued and valid" : visit.qr.is_used ? "Pass already used" : "Pass expired"}
        </span>
        <span className="text-xs text-muted-foreground">Expires {formatDateTime(visit.qr.expires_at)}</span>
      </div>
    )
  }
  const valid = visit.qr.is_valid
  return (
    <div
      ref={ref}
      className={`rounded-2xl border p-4 ${valid ? "border-primary/30 bg-primary-soft" : "border-border bg-surface-2"}`}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className={`flex items-center gap-2 text-sm font-semibold ${valid ? "text-primary" : "text-muted-foreground"}`}>
          {valid ? <ShieldCheck className="size-4" /> : <ShieldX className="size-4" />}
          {valid ? "Active QR pass" : visit.qr.is_used ? "Pass used" : "Pass expired"}
        </div>
        <Badge tone={valid ? "success" : "neutral"} size="sm">
          {valid ? "Single-use" : visit.qr.is_used ? "Redeemed" : "Expired"}
        </Badge>
      </div>
      <div className={`flex ${compact ? "items-center gap-4" : "flex-col items-center gap-4 sm:flex-row"}`}>
        <div className={`shrink-0 rounded-xl bg-white p-2.5 shadow-sm ${valid ? "" : "opacity-50 grayscale"}`}>
          <QRCodeSVG id={`pass-qr-${visit.id}`} value={payload} size={compact ? 112 : 148} fgColor="#0f172a" level="M" />
        </div>
        <div className="min-w-0 flex-1 space-y-2 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <Clock className="size-3.5 shrink-0" />
            <span>Expires {formatDateTime(visit.qr.expires_at)}</span>
          </div>
          <div className="truncate font-mono text-[11px]">Ref {visit.visit_id.slice(0, 8).toUpperCase()}</div>
          <p className="text-[11px] leading-relaxed">
            Scan at the gate; the pass is consumed on first successful check-in and rejects replays.
          </p>
          {valid && (
            <div className="flex flex-wrap gap-2 pt-1">
              <Button type="button" variant="outline" size="sm" onClick={() => printPass(visit, orgName)}>
                <Printer className="size-3.5" /> Print
              </Button>
              <CopyButton value={payload} label="Copy code" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
