import { useRef, useState } from "react"
import { toast } from "sonner"
import { Camera, GraduationCap, ImagePlus, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Input } from "@/components/ui/Input"
import { Chip } from "@/components/widgets/Choice"
import { Field } from "@/components/widgets/Field"
import { ID_PROOFS, idProblem, normaliseId } from "@/components/visitor/booking"
import { shrinkPhoto } from "@/components/visitor/IdentityStep"
import { useStudentPassMutations } from "@/lib/queries"
import { ApiError } from "@/lib/api"
import { formatApiError, type StudentPass } from "@/lib/types"
import { formatDate, todayIso } from "@/lib/utils"

const COURSES = ["Python Full Stack", "Data Science", "Data Analytics", "Machine Learning & AI", "Django Web Development", "Software Testing"]

function sixMonthsEnd(start: string) {
  if (!start) return ""
  const [y, m, d] = start.split("-").map(Number)
  const target = new Date(y, m - 1 + 6, 1)
  const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate()
  const end = new Date(target.getFullYear(), target.getMonth(), Math.min(d, last))
  end.setDate(end.getDate() - 1)
  return `${end.getFullYear()}-${String(end.getMonth() + 1).padStart(2, "0")}-${String(end.getDate()).padStart(2, "0")}`
}

const EMPTY = { full_name: "", phone: "", email: "", admission_number: "", course: "", batch: "", document_type: "", document_number: "", valid_from: todayIso() }

/** Admission desk form: issue a 6-month pass to an admitted student. */
export function IssuePassDialog({ open, onOpenChange, onIssued }: { open: boolean; onOpenChange: (o: boolean) => void; onIssued: (sp: StudentPass) => void }) {
  const { issue } = useStudentPassMutations()
  const fileRef = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState(EMPTY)
  const [photo, setPhoto] = useState<Blob | null>(null)
  const [photoUrl, setPhotoUrl] = useState("")
  const [errors, setErrors] = useState<Record<string, string>>({})
  const set = (k: keyof typeof EMPTY, v: string) => {
    setForm((f) => ({ ...f, [k]: v }))
    setErrors((e) => ({ ...e, [k]: "" }))
  }

  const reset = () => {
    setForm({ ...EMPTY, valid_from: todayIso() })
    setPhoto(null)
    if (photoUrl) URL.revokeObjectURL(photoUrl)
    setPhotoUrl("")
    setErrors({})
  }

  const onFile = async (file?: File) => {
    if (!file) return
    if (!file.type.startsWith("image/")) return setErrors((e) => ({ ...e, photo: "Choose a photo (JPG or PNG)." }))
    try {
      const blob = await shrinkPhoto(file)
      if (photoUrl) URL.revokeObjectURL(photoUrl)
      setPhoto(blob)
      setPhotoUrl(URL.createObjectURL(blob))
      setErrors((e) => ({ ...e, photo: "" }))
    } catch {
      setErrors((e) => ({ ...e, photo: "That file couldn't be read as a photo." }))
    }
  }

  const validate = () => {
    const e: Record<string, string> = {}
    if (form.full_name.trim().length < 2) e.full_name = "Enter the student's full name."
    if (form.phone.replace(/\D/g, "").length < 7) e.phone = "Enter a contact number with at least 7 digits."
    if (form.email && !/^\S+@\S+\.\S+$/.test(form.email)) e.email = "Enter a valid email, or leave it empty."
    if (!form.admission_number.trim()) e.admission_number = "Enter the admission or roll number."
    if (form.course.trim().length < 2) e.course = "Choose or type the course."
    const idErr = idProblem(form.document_type, form.document_number)
    if (idErr) e.document_number = idErr
    if (!photo) e.photo = "Add the student's photo."
    setErrors(e)
    return Object.keys(e).length === 0
  }

  const submit = async () => {
    if (!validate()) return
    const fd = new FormData()
    for (const [k, v] of Object.entries(form)) {
      const value = k === "document_number" ? normaliseId(form.document_type, v) : v.trim()
      if (value) fd.append(k, value)
    }
    fd.append("photo", photo!, "photo.jpg")
    try {
      const sp = await issue.mutateAsync(fd)
      toast.success(`Pass issued to ${sp.student.full_name}`, {
        description: sp.emailed ? `Emailed to ${sp.student.email}. Valid until ${formatDate(sp.valid_until)}.` : `Valid until ${formatDate(sp.valid_until)}.`,
      })
      reset()
      onIssued(sp)
    } catch (err) {
      const data = err instanceof ApiError && typeof err.data === "object" && err.data ? (err.data as Record<string, unknown>) : null
      if (data) {
        const fieldErrors: Record<string, string> = {}
        for (const [k, v] of Object.entries(data)) if (k !== "detail") fieldErrors[k] = Array.isArray(v) ? String(v[0]) : String(v)
        setErrors(fieldErrors)
      }
      toast.error("The pass wasn't issued", { description: formatApiError(err) })
    }
  }

  const proof = ID_PROOFS.find((p) => p.value === form.document_type)

  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setErrors({}) }}>
      <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><GraduationCap className="size-5 text-primary" /> Issue a student pass</DialogTitle>
          <DialogDescription>For students who have taken admission. The pass is valid for 6 months and is emailed to the student.</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="flex flex-col gap-4 sm:flex-row">
            <div className="flex shrink-0 flex-col items-center gap-2">
              <span className="flex h-32 w-28 items-center justify-center overflow-hidden rounded-xl border border-dashed border-border-strong bg-secondary">
                {photoUrl ? <img src={photoUrl} alt="Student photo" className="size-full object-cover" /> : <Camera className="size-7 text-muted-foreground" />}
              </span>
              <input ref={fileRef} type="file" accept="image/jpeg,image/png" capture="user" className="sr-only" id="sp-photo" onChange={(e) => void onFile(e.target.files?.[0])} />
              <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                {photo ? <><RefreshCw className="size-3.5" /> Change</> : <><ImagePlus className="size-3.5" /> Add photo</>}
              </Button>
              {errors.photo && <p className="max-w-28 text-center text-xs text-danger">{errors.photo}</p>}
            </div>
            <div className="grid flex-1 gap-3 sm:grid-cols-2">
              <Field id="sp-name" label="Full name" required error={errors.full_name} className="sm:col-span-2">
                <Input id="sp-name" value={form.full_name} onChange={(e) => set("full_name", e.target.value)} />
              </Field>
              <Field id="sp-phone" label="Contact number" required error={errors.phone}>
                <Input id="sp-phone" inputMode="tel" value={form.phone} onChange={(e) => set("phone", e.target.value)} />
              </Field>
              <Field id="sp-email" label="Email" hint="The pass is emailed here." error={errors.email}>
                <Input id="sp-email" type="email" value={form.email} onChange={(e) => set("email", e.target.value)} />
              </Field>
              <Field id="sp-adm" label="Admission / roll no." required error={errors.admission_number}>
                <Input id="sp-adm" className="font-mono uppercase" value={form.admission_number} onChange={(e) => set("admission_number", e.target.value)} placeholder="e.g. PYS-2026-001" />
              </Field>
              <Field id="sp-batch" label="Batch" hint="Optional." error={errors.batch}>
                <Input id="sp-batch" value={form.batch} onChange={(e) => set("batch", e.target.value)} placeholder="e.g. Jan 2027 morning" />
              </Field>
            </div>
          </div>

          <div>
            <div className="mb-2 text-sm font-medium">Course <span className="text-danger">*</span></div>
            <div role="radiogroup" aria-label="Course" className="flex flex-wrap gap-2">
              {COURSES.map((c) => <Chip key={c} role="radio" className="h-8 text-xs" selected={form.course === c} onClick={() => set("course", c)}>{c}</Chip>)}
            </div>
            <Input className="mt-2" aria-label="Course" value={COURSES.includes(form.course) ? "" : form.course} onChange={(e) => set("course", e.target.value)} placeholder="Or type the course name" />
            {errors.course && <p className="mt-1 text-xs text-danger">{errors.course}</p>}
          </div>

          <div>
            <div className="mb-2 text-sm font-medium">ID proof <span className="text-danger">*</span></div>
            <div role="radiogroup" aria-label="ID proof" className="flex flex-wrap gap-2">
              {ID_PROOFS.map((p) => <Chip key={p.value} role="radio" className="h-8 text-xs" selected={form.document_type === p.value} onClick={() => set("document_type", p.value)}>{p.label}</Chip>)}
            </div>
            {proof && (
              <Input className="mt-2 font-mono" aria-label={`${proof.label} number`} value={form.document_number} onChange={(e) => set("document_number", e.target.value)} placeholder={proof.placeholder} />
            )}
            {errors.document_number && <p className="mt-1 text-xs text-danger">{errors.document_number}</p>}
          </div>

          <div className="flex flex-wrap items-end gap-4 rounded-xl bg-secondary px-4 py-3">
            <Field id="sp-from" label="Valid from">
              <Input id="sp-from" type="date" className="h-9 w-auto" value={form.valid_from} onChange={(e) => set("valid_from", e.target.value)} />
            </Field>
            <div className="pb-2 text-sm">
              Valid until <span className="font-semibold">{form.valid_from ? formatDate(sixMonthsEnd(form.valid_from)) : "—"}</span>
              <span className="text-muted-foreground"> (6 months)</span>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={issue.isPending}>Cancel</Button>
          <Button onClick={() => void submit()} loading={issue.isPending}><GraduationCap className="size-4" /> Issue 6-month pass</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
