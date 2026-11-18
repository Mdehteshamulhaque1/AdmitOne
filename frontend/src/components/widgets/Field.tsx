import type { ReactNode } from "react"
import { Label } from "@/components/ui/Label"
import { cn } from "@/lib/utils"

interface FieldProps {
  id?: string
  label: string
  hint?: string
  error?: string
  required?: boolean
  className?: string
  children: ReactNode
}

/** Label + control + hint/error in one consistent block. */
export function Field({ id, label, hint, error, required, className, children }: FieldProps) {
  return (
    <div className={cn("space-y-1.5", className)}>
      <Label htmlFor={id} className="flex items-center gap-1">
        {label}
        {required && <span className="text-danger" aria-hidden="true">*</span>}
      </Label>
      {children}
      {error ? (
        <p className="text-xs text-danger" role="alert">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}
