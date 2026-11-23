import { useEffect, useState } from "react"
import { Sparkles } from "lucide-react"
import { Logo } from "@/components/logo"
import type { Step } from "@/components/visitor/booking"

/** One upbeat line per step, matched to what the visitor is doing right now. */
const STEP_LINES: Record<Step, { line: string; sub: string }> = {
  account: { line: "Every great opportunity starts with walking through the right door.", sub: "Let's get yours ready." },
  company: { line: "The right place is already expecting you.", sub: "Pick where you're headed." },
  purpose: { line: "Know your why, and every door opens a little faster.", sub: "Tell us what brings you in." },
  time: { line: "Being on time is the first impression you never get to redo.", sub: "Choose a slot that suits you." },
  identity: { line: "Smile, it's your best ID.", sub: "A clear photo gets you through the gate in seconds." },
  confirm: { line: "You're one tap away from your next big step.", sub: "Check the details and send it." },
  done: { line: "Request sent. Good things are already on their way.", sub: "We'll let you know the moment your host approves." },
}

/** Short, true facts about how AdmitOne keeps visits safe and quick. */
const DID_YOU_KNOW = [
  "Your pass is signed and works only once, so nobody can copy it.",
  "No queue at the counter: your pass is ready on your phone before you arrive.",
  "Your host approves before you travel, so you never make a wasted trip.",
  "Only the last 4 digits of your ID ever appear on screen.",
  "Reception assigns your room in advance, so you walk straight in.",
  "The gate scans your pass in about a second.",
]

function useReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)")
    if (!mq) return
    const on = () => setReduced(mq.matches)
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [])
  return reduced
}

/** Side card on the booking page: a step-matched line and a rotating "did you know". */
export function Inspiration({ step, name }: { step: Step; name?: string }) {
  const { line, sub } = STEP_LINES[step]
  const reduced = useReducedMotion()
  const [tip, setTip] = useState(0)
  const [fade, setFade] = useState(true)

  useEffect(() => {
    if (reduced) return
    const id = window.setInterval(() => {
      setFade(false)
      window.setTimeout(() => {
        setTip((t) => (t + 1) % DID_YOU_KNOW.length)
        setFade(true)
      }, 300)
    }, 6000)
    return () => window.clearInterval(id)
  }, [reduced])

  const first = name?.trim().split(/\s+/)[0]

  return (
    <section aria-label="A note for you" className="relative overflow-hidden rounded-2xl bg-nav p-6 text-nav-foreground shadow-lift">
      <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1.5 bg-nav-accent" />

      <div className="flex items-center gap-2 text-sm text-nav-muted">
        <Logo size={22} />
        {first ? <span>Welcome, <span className="font-semibold text-nav-foreground">{first}</span></span> : <span>Welcome to AdmitOne</span>}
      </div>

      <blockquote key={step} className="mt-6 animate-fade-in">
        <p className="text-[1.35rem] font-semibold leading-snug tracking-tight">{line}</p>
        <footer className="mt-2 text-sm text-nav-muted">{sub}</footer>
      </blockquote>

      <div className="mt-8 rounded-xl border border-nav-border bg-white/[0.04] p-4" aria-live="polite">
        <div className="flex items-center gap-1.5 text-xs font-semibold text-nav-accent">
          <Sparkles className="size-3.5" /> Did you know?
        </div>
        <p className={`mt-1.5 min-h-[2.5rem] text-sm leading-snug text-nav-foreground/90 transition-opacity duration-300 ${fade ? "opacity-100" : "opacity-0"}`}>
          {DID_YOU_KNOW[tip]}
        </p>
        <div className="mt-3 flex gap-1" aria-hidden="true">
          {DID_YOU_KNOW.map((_, i) => (
            <span key={i} className={`h-1 flex-1 rounded-full ${i === tip ? "bg-nav-accent" : "bg-white/10"}`} />
          ))}
        </div>
      </div>
    </section>
  )
}
