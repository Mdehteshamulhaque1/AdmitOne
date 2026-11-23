import type { ReactNode } from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

/** A selectable tile (radio semantics): purpose cards, host cards, company cards. */
export function ChoiceTile({
  selected,
  onSelect,
  icon,
  title,
  description,
  disabled,
  className,
}: {
  selected: boolean
  onSelect: () => void
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  disabled?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        "group relative flex w-full items-start gap-3 rounded-xl border bg-card p-3.5 text-left transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-primary bg-primary-soft ring-1 ring-primary" : "border-border hover:border-border-strong hover:bg-hover",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      {icon && (
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg transition-colors",
            selected ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground group-hover:text-foreground",
          )}
        >
          {icon}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold leading-snug">{title}</span>
        {description && <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{description}</span>}
      </span>
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border transition",
          selected ? "border-primary bg-primary text-primary-foreground" : "border-border-strong",
        )}
      >
        {selected && <Check className="size-3" />}
      </span>
    </button>
  )
}

/** A small toggle chip (notes, departments, categories, time slots). */
export function Chip({
  selected,
  onClick,
  children,
  disabled,
  className,
  role = "checkbox",
}: {
  selected: boolean
  onClick: () => void
  children: ReactNode
  disabled?: boolean
  className?: string
  role?: "checkbox" | "radio"
}) {
  return (
    <button
      type="button"
      role={role}
      aria-checked={selected}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg border px-3 text-sm font-medium tabular-nums transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-foreground hover:border-primary/50",
        disabled && "cursor-not-allowed border-dashed bg-transparent text-muted-foreground/60 line-through hover:border-border",
        className,
      )}
    >
      {children}
    </button>
  )
}
