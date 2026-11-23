import { useState } from "react"
import { ArrowRight, Camera, ClipboardList, IdCard, QrCode, ShieldAlert, UserCheck } from "lucide-react"
import { Button } from "@/components/ui/Button"

const STEPS = [
  { icon: ClipboardList, title: "Apply online", text: "Sign in, choose the purpose of your visit, the person you're meeting and a free time." },
  { icon: Camera, title: "Add your photo and ID", text: "Upload a recent photo and enter the number of one identity proof (Aadhaar, passport, PAN, driving licence or company ID)." },
  { icon: UserCheck, title: "Wait for approval", text: "Your host approves the request. You'll see the status under My visits and get your QR pass by email." },
  { icon: QrCode, title: "Show the pass at the gate", text: "Bring your QR pass and the ORIGINAL identity proof you entered. Reception checks both before letting you in." },
]

const RULES = [
  "The pass is valid only for the date and time shown on it, and only once.",
  "The pass is personal and can't be transferred to anyone else.",
  "Arrive a few minutes early; entry may be refused if the ID doesn't match.",
]

/** Read-before-you-apply screen, like a gate-pass counter's notice board. */
export function Instructions({ onAccept }: { onAccept: () => void }) {
  const [agreed, setAgreed] = useState(false)
  return (
    <section className="rounded-2xl border border-border bg-card shadow-card">
      <div className="space-y-6 p-5 sm:p-7">
        <header>
          <h2 className="text-xl font-semibold tracking-tight">Before you start</h2>
          <p className="mt-1 text-sm text-muted-foreground">How the online visitor pass works. It takes about 3 minutes.</p>
        </header>

        <ol className="space-y-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-4">
              <span className="relative flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <s.icon className="size-5" />
                <span className="absolute -right-1.5 -top-1.5 flex size-5 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground tabular-nums">{i + 1}</span>
              </span>
              <div>
                <h3 className="text-sm font-semibold">{s.title}</h3>
                <p className="mt-0.5 text-sm text-muted-foreground">{s.text}</p>
              </div>
            </li>
          ))}
        </ol>

        <div className="rounded-xl border border-warning/30 bg-warning-soft p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-warning"><ShieldAlert className="size-4" /> Please note</div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {RULES.map((r) => <li key={r}>{r}</li>)}
          </ul>
        </div>

        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <IdCard className="size-4 shrink-0" /> Keep your identity proof ready before you begin.
        </div>
      </div>
      <footer className="flex flex-col gap-3 border-t border-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7">
        <label className="flex cursor-pointer items-center gap-2.5 text-sm">
          <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="size-4 accent-[var(--sg-primary)]" />
          I have read these instructions
        </label>
        <Button onClick={onAccept} disabled={!agreed}>
          Start my application <ArrowRight className="size-4" />
        </Button>
      </footer>
    </section>
  )
}
