import { Logo } from "@/components/logo"
import { purposeText, usePublicHosts, type Draft, type Step } from "@/components/visitor/booking"
import { categoryLabel } from "@/lib/student-options"
import { cn, formatDate } from "@/lib/utils"
import type { OrganizationResult, VisitorVisit } from "@/lib/visitor-api"

export interface PassPerson {
  name: string
  category: string
  email: string
}

function PassRow({ label, value, placeholder, wide }: { label: string; value?: string | null; placeholder: string; wide?: boolean }) {
  return (
    <div className={cn("min-w-0", wide && "col-span-2")}>
      <dt className="text-[11px] text-nav-muted">{label}</dt>
      <dd className={cn("mt-0.5 truncate text-sm", value ? "font-medium text-nav-foreground" : "text-nav-muted/70")}>{value || placeholder}</dd>
    </div>
  )
}

/**
 * The visitor's pass, filled in live as they move through the steps. Before
 * approval it is a draft: the QR block explains when the real pass arrives.
 */
export function VisitorPass({ person, org, draft, step, visit }: { person: PassPerson; org: OrganizationResult | null; draft: Draft; step: Step; visit: VisitorVisit | null }) {
  const hosts = usePublicHosts(org?.slug ?? "", draft.department)
  const host = hosts.data?.find((h) => String(h.id) === draft.host)
  const category = categoryLabel(draft.category || person.category)
  const status = visit ? "Awaiting approval" : step === "confirm" ? "Ready to send" : "Draft"

  return (
    <section aria-label="Your visitor pass preview" className="relative overflow-hidden rounded-2xl bg-nav text-nav-foreground shadow-lift">
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5 bg-nav-accent" />
      <div className="flex items-center justify-between gap-3 px-6 pb-4 pt-5">
        <div className="flex items-center gap-2">
          <Logo size={26} />
          <span className="text-sm font-semibold">Visitor pass</span>
        </div>
        <span
          className={cn(
            "rounded-full px-2.5 py-1 text-[11px] font-semibold",
            visit ? "bg-amber-400/15 text-amber-300" : step === "confirm" ? "bg-nav-active text-nav-accent" : "bg-white/8 text-nav-muted",
          )}
        >
          {status}
        </span>
      </div>

      <div className="flex items-center gap-4 px-6 pb-5">
        <span className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-nav-border bg-white/5 text-xs text-nav-muted">
          {draft.photo_url ? <img src={draft.photo_url} alt="" className="size-full object-cover" /> : "Photo"}
        </span>
        <div className="min-w-0">
          <div className="truncate text-xl font-semibold leading-tight tracking-tight">{person.name || <span className="text-nav-muted/70">Your name</span>}</div>
          <div className="mt-0.5 truncate text-sm text-nav-muted">{[category, person.email].filter(Boolean).join(" · ") || "Who you are"}</div>
        </div>
      </div>

      <div aria-hidden="true" className="relative h-5">
        <span className="absolute -left-2.5 top-0 size-5 rounded-full bg-background" />
        <span className="absolute -right-2.5 top-0 size-5 rounded-full bg-background" />
        <span className="absolute inset-x-5 top-1/2 border-t border-dashed border-nav-border" />
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-3.5 px-6 py-4">
        <PassRow label="Visiting" value={org?.name} placeholder="Choose a company" wide />
        <PassRow label="Purpose" value={purposeText(draft)} placeholder="Why you're visiting" wide />
        <PassRow label="Meeting" value={host?.name} placeholder="Who you're meeting" wide />
        <PassRow label="Date" value={draft.visit_date ? formatDate(draft.visit_date) : null} placeholder="Pick a date" />
        <PassRow label="Arrival" value={draft.slot ? `${draft.slot.start}–${draft.slot.end}` : null} placeholder="Pick a time" />
        <PassRow label="Room" value={visit?.room_label ? `Room ${visit.room_label}` : null} placeholder="Assigned on approval" wide />
      </dl>

      <div className="mx-6 mb-6 flex items-center gap-3 rounded-xl border border-nav-border bg-white/[0.03] p-3">
        <span aria-hidden="true" className="grid size-12 shrink-0 grid-cols-4 gap-0.5 rounded-md bg-white/90 p-1.5">
          {[1, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 0, 1, 0, 1, 1].map((on, i) => (
            <span key={i} className={cn("rounded-[1px]", on ? "bg-nav" : "bg-transparent")} />
          ))}
        </span>
        <p className="text-xs leading-snug text-nav-muted">
          {visit ? (
            <>
              Reference <span className="font-mono text-nav-foreground">{visit.reference.slice(0, 8)}</span>. Your QR code arrives by email and under My visits once your host approves.
            </>
          ) : (
            "Your single-use QR code is issued when your host approves the visit."
          )}
        </p>
      </div>
    </section>
  )
}
