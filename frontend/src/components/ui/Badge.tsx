import * as React from "react"
import { cn } from "@/lib/utils"

export type BadgeTone =
  | "neutral"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "primary"
  | "cyan"
  | "violet"

const toneClasses: Record<BadgeTone, string> = {
  neutral: "bg-surface-2 text-muted-foreground border-border",
  success: "bg-success-soft text-success border-success/25",
  warning: "bg-warning-soft text-warning border-warning/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  info: "bg-info-soft text-info border-info/25",
  primary: "bg-primary-soft text-primary border-primary/25",
  cyan: "bg-accent-soft text-accent border-accent/25",
  violet: "bg-violet-soft text-violet border-violet/25",
}

const dotClasses: Record<BadgeTone, string> = {
  neutral: "bg-muted-foreground",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  info: "bg-info",
  primary: "bg-primary",
  cyan: "bg-accent",
  violet: "bg-violet",
}

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
  dot?: boolean
  size?: "sm" | "md"
}

export function Badge({ className, tone = "neutral", dot = false, size = "md", children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border font-medium",
        size === "md" ? "px-2.5 py-0.5 text-xs" : "px-2 py-px text-[11px]",
        toneClasses[tone],
        className,
      )}
      {...props}
    >
      {dot && <span className={cn("size-1.5 shrink-0 rounded-full", dotClasses[tone])} />}
      {children}
    </span>
  )
}
