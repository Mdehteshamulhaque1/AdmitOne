import { useRef, useState } from "react"
import { ArrowRight, Camera, ImagePlus, RefreshCw, ShieldCheck } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Button } from "@/components/ui/Button"
import { Input } from "@/components/ui/Input"
import { ID_PROOFS, idProblem, normaliseId, type Draft } from "@/components/visitor/booking"
import { Chip, StepCard, StepSection } from "@/components/visitor/ui"

const MAX_SOURCE_BYTES = 15 * 1024 * 1024
const MAX_EDGE = 800

/** Shrink a phone photo on the device (max 800px, JPEG) before it is uploaded. */
export async function shrinkPhoto(file: File): Promise<Blob> {
  const url = URL.createObjectURL(file)
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image()
      el.onload = () => resolve(el)
      el.onerror = () => reject(new Error("unreadable"))
      el.src = url
    })
    const scale = Math.min(1, MAX_EDGE / Math.max(img.width, img.height))
    const canvas = document.createElement("canvas")
    canvas.width = Math.round(img.width * scale)
    canvas.height = Math.round(img.height * scale)
    canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height)
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/jpeg", 0.85))
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * Gate-pass identity, like an office or court gate-pass counter: a recent
 * photo and one identity proof. The original ID is checked at the gate.
 */
export function IdentityStep({ draft, setDraft, onBack, onNext }: { draft: Draft; setDraft: (d: Draft) => void; onBack: () => void; onNext: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [photoError, setPhotoError] = useState("")
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })

  const proof = ID_PROOFS.find((p) => p.value === draft.document_type)
  const problem = draft.document_type ? idProblem(draft.document_type, draft.document_number) : null
  const valid = Boolean(draft.photo && draft.document_type && !problem)

  const onFile = async (file: File | undefined) => {
    setPhotoError("")
    if (!file) return
    if (!file.type.startsWith("image/")) return setPhotoError("Choose a photo (JPG or PNG).")
    if (file.size > MAX_SOURCE_BYTES) return setPhotoError("That photo is too large. Choose one under 15 MB.")
    setBusy(true)
    try {
      const blob = await shrinkPhoto(file)
      if (draft.photo_url) URL.revokeObjectURL(draft.photo_url)
      set({ photo: blob, photo_url: URL.createObjectURL(blob) })
    } catch {
      setPhotoError("That file couldn't be read as a photo. Try another one.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <StepCard
      title="Your photo and ID proof"
      subtitle="Reception matches your face and your original ID at the gate before handing over the pass."
      onBack={onBack}
      action={
        <Button
          onClick={() => {
            setTouched(true)
            if (valid) {
              set({ document_number: normaliseId(draft.document_type, draft.document_number) })
              onNext()
            }
          }}
        >
          Continue <ArrowRight className="size-4" />
        </Button>
      }
    >
      <StepSection title="Recent photo" hint="Face clearly visible, no cap or sunglasses. JPG or PNG.">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="flex size-32 shrink-0 items-center justify-center overflow-hidden rounded-2xl border border-dashed border-border-strong bg-secondary">
            {draft.photo_url ? (
              <img src={draft.photo_url} alt="Your photo" className="size-full object-cover" />
            ) : (
              <Camera className="size-8 text-muted-foreground" aria-hidden="true" />
            )}
          </div>
          <div className="space-y-2">
            <input ref={fileRef} type="file" accept="image/jpeg,image/png" capture="user" className="sr-only" id="i-photo" onChange={(e) => void onFile(e.target.files?.[0])} />
            <Button variant="outline" onClick={() => fileRef.current?.click()} loading={busy}>
              {draft.photo ? <><RefreshCw className="size-4" /> Change photo</> : <><ImagePlus className="size-4" /> Upload or take photo</>}
            </Button>
            <p className="text-xs text-muted-foreground">On a phone this opens the camera.</p>
            {photoError && <p className="text-xs text-danger">{photoError}</p>}
            {touched && !draft.photo && !photoError && <p className="text-xs text-danger">Add a photo to continue.</p>}
          </div>
        </div>
      </StepSection>

      <StepSection title="Identity proof" hint="Bring the original of the ID you choose here.">
        <div role="radiogroup" aria-label="Identity proof" className="flex flex-wrap gap-2">
          {ID_PROOFS.map((p) => (
            <Chip key={p.value} role="radio" selected={draft.document_type === p.value} onClick={() => set({ document_type: p.value, document_number: draft.document_type === p.value ? draft.document_number : "" })}>
              {p.label}
            </Chip>
          ))}
        </div>
        {touched && !draft.document_type && <p className="mt-2 text-xs text-danger">Choose your identity proof.</p>}
      </StepSection>

      {proof && (
        <div>
          <label htmlFor="i-number" className="text-sm font-semibold">
            {proof.label} number <span className="text-danger">*</span>
          </label>
          <Input
            id="i-number"
            className="mt-2 font-mono tracking-wide"
            value={draft.document_number}
            onChange={(e) => set({ document_number: e.target.value })}
            onBlur={() => setTouched(true)}
            placeholder={proof.placeholder}
            maxLength={60}
            autoComplete="off"
            aria-invalid={touched && Boolean(problem)}
          />
          <p className={touched && problem ? "mt-1.5 text-xs text-danger" : "mt-1.5 text-xs text-muted-foreground"}>
            {touched && problem ? problem : `Format: ${proof.hint}.`}
          </p>
        </div>
      )}

      <Alert variant="info">
        <ShieldCheck className="mt-0.5 size-4 shrink-0" />
        <span>Your ID number is visible only to authorised staff, and only the last 4 characters appear on screens.</span>
      </Alert>
    </StepCard>
  )
}
