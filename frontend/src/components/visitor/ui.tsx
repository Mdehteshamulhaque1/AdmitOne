import type { ReactNode } from "react"
import { ArrowLeft, Check } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { cn } from "@/lib/utils"

export { Chip, ChoiceTile } from "@/components/widgets/Choice"

/** One booking step: a title, a short line of help, the body and the footer actions. */
export function StepCard({
  title,
  subtitle,
  children,
  onBack,
  backLabel = "Back",
  action,
}: {
  title: string
  subtitle?: ReactNode
  children: ReactNode
  onBack?: () => void
  backLabel?: string
  action?: ReactNode
}) {
  return (
    <section className="rounded-2xl border border-border bg-card shadow-card">
      <div className="space-y-7 p-5 sm:p-7">
        <header>
          <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
          {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
        </header>
        {children}
      </div>
      {(onBack || action) && (
        <footer className="flex items-center justify-between gap-3 border-t border-border px-5 py-4 sm:px-7">
          {onBack ? (
            <Button variant="ghost" onClick={onBack}>
              <ArrowLeft className="size-4" /> {backLabel}
            </Button>
          ) : (
            <span />
          )}
          {action}
        </footer>
      )}
    </section>
  )
}

/** A labelled group inside a step ("Who are you meeting?", "Pick a date"). */
export function StepSection({ title, hint, children, aside }: { title: string; hint?: ReactNode; children: ReactNode; aside?: ReactNode }) {
  return (
    <div>
      <div className="mb-3 flex items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
        </div>
        {aside}
      </div>
      {children}
    </div>
  )
}

/** Segmented progress bar for the visible steps. */
export function StepProgress({ steps, current }: { steps: { key: string; label: string }[]; current: string }) {
  const idx = current === "done" ? steps.length : steps.findIndex((s) => s.key === current)
  const label = steps[Math.min(Math.max(idx, 0), steps.length - 1)]?.label
  return (
    <nav aria-label="Booking progress">
      <p className="mb-2 text-sm text-muted-foreground sm:hidden">
        {current === "done" ? "Request sent" : <>Step {idx + 1} of {steps.length}: <span className="font-medium text-foreground">{label}</span></>}
      </p>
      <ol className="grid gap-1.5 sm:gap-2" style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}>
        {steps.map((s, i) => {
          const done = i < idx
          const active = i === idx
          return (
            <li key={s.key} aria-current={active ? "step" : undefined}>
              <span className={cn("block h-1.5 rounded-full transition-colors", done || active ? "bg-primary" : "bg-muted")} />
              <span className={cn("mt-2 hidden items-center gap-1.5 text-xs font-medium sm:flex", active ? "text-foreground" : done ? "text-primary" : "text-muted-foreground")}>
                {done ? <Check className="size-3.5" /> : <span className="tabular-nums">{i + 1}</span>}
                {s.label}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
