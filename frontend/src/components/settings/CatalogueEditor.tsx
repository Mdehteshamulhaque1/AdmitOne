import { useEffect, useState } from "react"
import { toast } from "sonner"
import { ChevronDown, ChevronUp, ListChecks, Plus, RotateCcw, Save, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { useAuth } from "@/lib/auth"
import { useOrganization, useUpdateOrganization } from "@/lib/queries"
import { ROOM_TYPES, formatApiError, type CatalogueCategory, type CataloguePurpose, type RoomType } from "@/lib/types"

/** Reporting buckets; must match the backend `VisitType` choices. */
const VISIT_TYPES = [
  { value: "TRAINING_WORKSHOP", label: "Training / Workshop" },
  { value: "INTERVIEW", label: "Interview" },
  { value: "CAMPUS_PLACEMENT", label: "Campus / Placement" },
  { value: "BUSINESS_MEETING", label: "Business Meeting" },
  { value: "CLIENT_MEETING", label: "Client Meeting" },
  { value: "VENDOR_DELIVERY", label: "Vendor / Delivery" },
  { value: "GUEST", label: "Guest" },
  { value: "OTHER", label: "Other" },
]

const NO_ROOM = "__none__"

function keyFrom(label: string): string {
  return label.trim().toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40)
}

/**
 * Edits the workspace's visitor catalogue: the "I am a…" categories and,
 * per category, the purposes a visitor can pick (each mapped to a visit type
 * for reporting and a suggested room type for approvals).
 */
export function CatalogueEditor() {
  const { can } = useAuth()
  const editable = can("manage_org")
  const org = useOrganization()
  const update = useUpdateOrganization()
  const [cats, setCats] = useState<CatalogueCategory[]>([])
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  useEffect(() => {
    if (org.data && !dirty) {
      setCats(org.data.visitor_catalogue.categories.map((c) => ({ ...c, purposes: c.purposes.map((p) => ({ ...p })) })))
      setOpenKey((k) => k ?? org.data?.visitor_catalogue.categories[0]?.key ?? null)
    }
  }, [org.data, dirty])

  const customised = Boolean((org.data?.visitor_policies ?? {}).visitor_catalogue)

  const edit = (fn: (draft: CatalogueCategory[]) => CatalogueCategory[]) => {
    setCats((c) => fn(c))
    setDirty(true)
  }
  const editCat = (key: string, patch: Partial<CatalogueCategory>) => edit((d) => d.map((c) => (c.key === key ? { ...c, ...patch } : c)))
  const editPurpose = (key: string, idx: number, patch: Partial<CataloguePurpose>) =>
    editCat(key, { purposes: cats.find((c) => c.key === key)!.purposes.map((p, i) => (i === idx ? { ...p, ...patch } : p)) })

  const addCategory = () => {
    let base = "NEW_CATEGORY"
    let i = 1
    while (cats.some((c) => c.key === base)) base = `NEW_CATEGORY_${++i}`
    edit((d) => [...d, { key: base, label: "New category", purposes: [{ label: "Other", visit_type: "OTHER", room_type: "" }] }])
    setOpenKey(base)
  }

  const save = async () => {
    for (const c of cats) {
      if (!c.label.trim()) return toast.error("Every category needs a label")
      if (c.purposes.some((p) => !p.label.trim())) return toast.error(`"${c.label}" has a purpose without a label`)
    }
    try {
      await update.mutateAsync({
        visitor_policies: {
          ...(org.data?.visitor_policies ?? {}),
          visitor_catalogue: { categories: cats.map((c) => ({ ...c, key: keyFrom(c.key) || keyFrom(c.label) })) },
        },
      })
      setDirty(false)
      toast.success("Visitor options saved")
    } catch (e) {
      toast.error("Could not save", { description: formatApiError(e) })
    }
  }

  const reset = async () => {
    try {
      await update.mutateAsync({ visitor_policies: { ...(org.data?.visitor_policies ?? {}), visitor_catalogue: {} } })
      setDirty(false)
      setConfirmReset(false)
      toast.success("Training-centre defaults restored")
    } catch (e) {
      toast.error("Could not reset", { description: formatApiError(e) })
    }
  }

  if (org.isLoading) return <Skeleton className="h-96 w-full" />
  if (org.isError || !org.data) return <QueryErrorState message="Couldn't load visitor options." retry={() => void org.refetch()} />

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm"><ListChecks className="size-4 text-primary" /> Who visits, and why</CardTitle>
          <CardDescription>
            Visitors pick one of these categories when they sign up and book, then a purpose from that category's list. Each purpose maps to a visit type for reports and a suggested room type that is highlighted when staff approve.
            {!customised && " You are using the training-centre defaults; edit anything below to customise."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {cats.map((c) => {
            const isOpen = openKey === c.key
            return (
              <div key={c.key} className="rounded-xl border border-border">
                <div className="flex items-center gap-2 px-3 py-2">
                  <button type="button" onClick={() => setOpenKey(isOpen ? null : c.key)} className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-hover" aria-label={isOpen ? "Collapse" : "Expand"}>
                    {isOpen ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                  </button>
                  <Input value={c.label} disabled={!editable} onChange={(e) => editCat(c.key, { label: e.target.value })} className="h-9 max-w-xs font-medium" aria-label="Category label" />
                  <span className="hidden font-mono text-[11px] text-muted-foreground sm:inline">{c.key}</span>
                  <span className="ml-auto text-xs text-muted-foreground">{c.purposes.length} purpose{c.purposes.length === 1 ? "" : "s"}</span>
                  {editable && (
                    <Button variant="ghost" size="iconSm" className="hover:text-danger" disabled={cats.length <= 1} onClick={() => edit((d) => d.filter((x) => x.key !== c.key))} aria-label={`Remove ${c.label}`}><Trash2 className="size-4" /></Button>
                  )}
                </div>
                {isOpen && (
                  <div className="border-t border-border px-3 py-3">
                    <div className="hidden grid-cols-[1fr_11rem_11rem_2rem] gap-2 px-1 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground sm:grid">
                      <span>Purpose shown to visitors</span><span>Counts as</span><span>Usual room</span><span />
                    </div>
                    <div className="space-y-2">
                      {c.purposes.map((p, i) => {
                        const isOther = p.label === "Other"
                        return (
                          <div key={i} className="grid gap-2 sm:grid-cols-[1fr_11rem_11rem_2rem]">
                            <Input value={p.label} disabled={!editable || isOther} onChange={(e) => editPurpose(c.key, i, { label: e.target.value })} className="h-9" aria-label="Purpose label" />
                            <Select value={p.visit_type} disabled={!editable} onValueChange={(v) => editPurpose(c.key, i, { visit_type: v })}>
                              <SelectTrigger className="h-9" aria-label="Visit type"><SelectValue /></SelectTrigger>
                              <SelectContent>{VISIT_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
                            </Select>
                            <Select value={p.room_type || NO_ROOM} disabled={!editable} onValueChange={(v) => editPurpose(c.key, i, { room_type: v === NO_ROOM ? "" : (v as RoomType) })}>
                              <SelectTrigger className="h-9" aria-label="Room type"><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value={NO_ROOM}>Any</SelectItem>
                                {ROOM_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
                              </SelectContent>
                            </Select>
                            <div className="flex items-center">
                              {editable && !isOther && (
                                <Button variant="ghost" size="iconSm" className="hover:text-danger" onClick={() => editCat(c.key, { purposes: c.purposes.filter((_, j) => j !== i) })} aria-label="Remove purpose"><Trash2 className="size-4" /></Button>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {editable && (
                      <Button variant="ghost" size="sm" className="mt-2" onClick={() => editCat(c.key, { purposes: [...c.purposes.filter((p) => p.label !== "Other"), { label: "", visit_type: "OTHER", room_type: "" }, ...c.purposes.filter((p) => p.label === "Other")] })}>
                        <Plus className="size-3.5" /> Add purpose
                      </Button>
                    )}
                    <p className="mt-2 text-[11px] text-muted-foreground">"Other" always stays at the end so visitors can type a purpose that isn't listed.</p>
                  </div>
                )}
              </div>
            )
          })}
          {editable && (
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <Button variant="outline" onClick={addCategory}><Plus className="size-4" /> Add category</Button>
              <div className="flex gap-2">
                {customised && <Button variant="ghost" onClick={() => setConfirmReset(true)}><RotateCcw className="size-4" /> Reset to defaults</Button>}
                <Button onClick={save} disabled={!dirty} loading={update.isPending}><Save className="size-4" /> Save changes</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      <ConfirmDialog
        open={confirmReset}
        onOpenChange={setConfirmReset}
        title="Reset to the training-centre defaults?"
        description="Your custom categories and purposes are replaced by the built-in list (Student, Parent, Recruiter, Vendor, Other). Existing visits keep the purpose they were booked with."
        confirmLabel="Reset"
        tone="danger"
        loading={update.isPending}
        onConfirm={reset}
      />
    </div>
  )
}
