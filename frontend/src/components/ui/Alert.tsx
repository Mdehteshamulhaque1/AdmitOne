import * as React from "react"
import { cn } from "@/lib/utils"

const tones = {
  default: "border-border bg-surface-2 text-foreground",
  info: "border-info/25 bg-info-soft text-foreground [&_svg]:text-info",
  warning: "border-warning/30 bg-warning-soft text-foreground [&_svg]:text-warning",
  danger: "border-danger/30 bg-danger-soft text-foreground [&_svg]:text-danger",
  success: "border-success/30 bg-success-soft text-foreground [&_svg]:text-success",
} as const

export function Alert({
  className,
  variant = "default",
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { variant?: keyof typeof tones }) {
  return (
    <div
      role="alert"
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm leading-relaxed",
        tones[variant],
        className,
      )}
      {...props}
    >
      {children}
    </div>
  )
}
