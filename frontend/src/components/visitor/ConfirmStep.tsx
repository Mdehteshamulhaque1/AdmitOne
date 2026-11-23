import { useState, type ReactNode } from "react"
import { Building2, CalendarDays, CheckCircle2, ClipboardList, DoorOpen, IdCard, Plus, UserRound, Users, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/Button"
import { Input } from "@/components/ui/Input"
import { ID_PROOFS, maskId, purposeForSubmit, purposeText, usePublicHosts, type Draft, type Step } from "@/components/visitor/booking"
import { Chip, StepCard, StepSection } from "@/components/visitor/ui"
import { categoryLabel, NOTE_PRESETS } from "@/lib/student-options"
import { formatApiError } from "@/lib/types"
import { formatDate } from "@/lib/utils"
import { useCreateBooking, useOrganizationContext, useVisitorAccount, type OrganizationResult, type VisitorVisit } from "@/lib/visitor-api"

function Row({ icon, label, children, onEdit }: { icon: ReactNode; label: string; children: ReactNode; onEdit?: () => void }) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <span className="mt-0.5 text-muted-foreground">{icon}</span>
      <div className="min-w-0 flex-1">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="mt-0.5 text-sm font-medium">{children}</dd>
      </div>
      {onEdit && (
        <button type="button" onClick={onEdit} className="text-sm font-medium text-primary hover:underline">
          Change
        </button>
      )}
    </div>
  )
}

/** Check everything, add notes for the host, send the request. */
export function ConfirmStep({
  org,
  draft,
  setDraft,
  canChangeCompany,
  onEdit,
  onBack,
  onDone,
}: {
  org: OrganizationResult
  draft: Draft
  setDraft: (d: Draft) => void
  canChangeCompany: boolean
  onEdit: (step: Step) => void
  onBack: () => void
  onDone: (v: VisitorVisit) => void
}) {
  const account = useVisitorAccount()
  const ctx = useOrganizationContext(org.slug)
  const hosts = usePublicHosts(org.slug, draft.department)
  const create = useCreateBooking()
  const [note, setNote] = useState("")
  const host = hosts.data?.find((h) => String(h.id) === draft.host)
  const dept = ctx.data?.departments.find((d) => String(d.id) === draft.department)
  const custom = draft.notes.filter((n) => !NOTE_PRESETS.includes(n))

  const toggle = (n: string) => setDraft({ ...draft, notes: draft.notes.includes(n) ? draft.notes.filter((x) => x !== n) : [...draft.notes, n] })
  const addNote = () => {
    const text = note.trim()
    if (text && !draft.notes.includes(text)) setDraft({ ...draft, notes: [...draft.notes, text] })
    setNote("")
  }

  const submit = async () => {
    if (!draft.slot) return
    try {
      const res = await create.mutateAsync({
        organization: org.slug,
        category: draft.category,
        ...purposeForSubmit(draft, ctx.data?.visitor_categories ?? []),
        department: draft.department ? Number(draft.department) : null,
        building: null,
        floor: null,
        host: Number(draft.host),
        visit_date: draft.visit_date,
        expected_arrival: draft.slot.start,
        expected_exit: draft.slot.end,
        notes: draft.notes.join("; "),
        document_type: draft.document_type,
        document_number: draft.document_number,
        photo: draft.photo,
      })
      toast.success("Request sent", { description: res.message })
      onDone(res.visit)
    } catch (err) {
      toast.error("The request wasn't sent", { description: formatApiError(err) })
    }
  }

  return (
    <StepCard
      title="Confirm your visit"
      subtitle="Check the details, then send the request. Your host approves it and your QR pass arrives by email and under My visits."
      onBack={onBack}
      action={
        <Button size="lg" onClick={submit} loading={create.isPending}>
          <CheckCircle2 className="size-4" /> Send request
        </Button>
      }
    >
      <dl className="divide-y divide-border rounded-xl border border-border">
        <Row icon={<Building2 className="size-4" />} label="Company" onEdit={canChangeCompany ? () => onEdit("company") : undefined}>
          {[org.name, org.city].filter(Boolean).join(", ")}
        </Row>
        <Row icon={<ClipboardList className="size-4" />} label="Purpose" onEdit={() => onEdit("purpose")}>
          {purposeText(draft)} <span className="font-normal text-muted-foreground">as {categoryLabel(draft.category, ctx.data?.visitor_categories)}</span>
        </Row>
        <Row icon={<Users className="size-4" />} label="Meeting" onEdit={() => onEdit("time")}>
          {host ? `${host.name}${host.designation ? `, ${host.designation}` : ""}` : "—"}
          {dept && <span className="font-normal text-muted-foreground"> ({dept.name})</span>}
        </Row>
        <Row icon={<CalendarDays className="size-4" />} label="Date and time" onEdit={() => onEdit("time")}>
          {draft.slot ? `${formatDate(draft.visit_date)}, ${draft.slot.start}–${draft.slot.end}` : "—"}
        </Row>
        <Row icon={<IdCard className="size-4" />} label="Photo and ID proof" onEdit={() => onEdit("identity")}>
          <span className="flex items-center gap-3">
            {draft.photo_url && <img src={draft.photo_url} alt="" className="size-10 rounded-lg object-cover" />}
            <span>
              {ID_PROOFS.find((p) => p.value === draft.document_type)?.label ?? "—"}{" "}
              <span className="font-mono font-normal text-muted-foreground">{maskId(draft.document_number)}</span>
              <span className="block text-xs font-normal text-muted-foreground">Bring the original to the gate.</span>
            </span>
          </span>
        </Row>
        <Row icon={<DoorOpen className="size-4" />} label="Room">
          <span className="font-normal text-muted-foreground">Reception assigns it when they approve; it appears on your pass.</span>
        </Row>
        <Row icon={<UserRound className="size-4" />} label="You">
          {account.data ? [account.data.full_name, account.data.phone, account.data.email].filter(Boolean).join(", ") : "—"}
        </Row>
      </dl>

      <StepSection title="Anything your host should know?" hint="Optional. Tap any that apply, or add your own.">
        <div className="flex flex-wrap gap-2">
          {NOTE_PRESETS.map((n) => (
            <Chip key={n} selected={draft.notes.includes(n)} onClick={() => toggle(n)}>
              {n}
            </Chip>
          ))}
          {custom.map((n) => (
            <span key={n} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-primary bg-primary px-3 text-sm font-medium text-primary-foreground">
              {n}
              <button type="button" onClick={() => toggle(n)} aria-label={`Remove note: ${n}`} className="rounded-sm opacity-80 hover:opacity-100">
                <X className="size-3.5" />
              </button>
            </span>
          ))}
        </div>
        <form
          className="mt-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            addNote()
          }}
        >
          <Input id="c-note" value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} placeholder="Add a note, e.g. arriving by metro" aria-label="Add your own note" />
          <Button type="submit" variant="outline" disabled={!note.trim()}>
            <Plus className="size-4" /> Add
          </Button>
        </form>
      </StepSection>
    </StepCard>
  )
}
