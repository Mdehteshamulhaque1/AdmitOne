import { QRCodeSVG } from "qrcode.react"
import { Logo } from "@/components/logo"
import { cn, formatDate } from "@/lib/utils"
import type { StudentPass } from "@/lib/types"

const STATUS_STYLE: Record<string, string> = {
  ACTIVE: "bg-emerald-400/15 text-emerald-300",
  UPCOMING: "bg-sky-400/15 text-sky-300",
  EXPIRED: "bg-amber-400/15 text-amber-300",
  REVOKED: "bg-red-400/15 text-red-300",
}

/** ID-card style student pass: photo, details, validity and the QR. */
export function StudentPassCard({ sp, orgName, className }: { sp: StudentPass; orgName: string; className?: string }) {
  const usable = sp.status === "ACTIVE" || sp.status === "UPCOMING"
  return (
    <div className={cn("relative w-full max-w-sm overflow-hidden rounded-2xl bg-nav text-nav-foreground shadow-lift", className)}>
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5 bg-nav-accent" />
      <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-4">
        <div className="flex min-w-0 items-center gap-2">
          <Logo size={24} />
          <span className="truncate text-sm font-semibold">{orgName}</span>
        </div>
        <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-semibold", STATUS_STYLE[sp.status])}>
          {sp.status === "ACTIVE" ? "Student pass" : sp.status.charAt(0) + sp.status.slice(1).toLowerCase()}
        </span>
      </div>
      <div className="flex gap-4 px-5 pb-4">
        <span className="flex h-24 w-20 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-nav-border bg-white/5 text-xs text-nav-muted">
          {sp.student.photo ? <img src={sp.student.photo} alt="" className="size-full object-cover" /> : "Photo"}
        </span>
        <div className="min-w-0 space-y-1">
          <div className="truncate text-lg font-semibold leading-tight">{sp.student.full_name}</div>
          <div className="font-mono text-sm text-nav-accent">{sp.admission_number}</div>
          <div className="truncate text-sm text-nav-muted">{sp.course}{sp.batch ? ` · ${sp.batch}` : ""}</div>
          <div className="text-xs text-nav-muted">{sp.student.phone}</div>
        </div>
      </div>
      <div aria-hidden="true" className="relative h-5">
        <span className="absolute -left-2.5 top-0 size-5 rounded-full bg-background" />
        <span className="absolute -right-2.5 top-0 size-5 rounded-full bg-background" />
        <span className="absolute inset-x-5 top-1/2 border-t border-dashed border-nav-border" />
      </div>
      <div className="flex items-center gap-4 px-5 py-4">
        <div className={cn("rounded-xl bg-white p-2", !usable && "opacity-40 grayscale")}>
          {sp.payload ? <QRCodeSVG value={sp.payload} size={112} fgColor="#0f172a" level="M" /> : <div className="size-28" />}
        </div>
        <dl className="space-y-2 text-xs">
          <div>
            <dt className="text-nav-muted">Valid from</dt>
            <dd className="font-medium">{formatDate(sp.valid_from)}</dd>
          </div>
          <div>
            <dt className="text-nav-muted">Valid until</dt>
            <dd className="font-medium">{formatDate(sp.valid_until)}</dd>
          </div>
          <div className="text-nav-muted">Scan at entry and exit every day.</div>
        </dl>
      </div>
    </div>
  )
}
