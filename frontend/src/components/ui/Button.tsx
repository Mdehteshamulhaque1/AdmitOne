import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "success" | "accent" | "glass"
type ButtonSize = "sm" | "md" | "lg" | "icon" | "iconSm"

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-primary text-primary-foreground font-semibold hover:bg-primary-strong shadow-sm",
  secondary:
    "bg-card-soft text-foreground border border-border hover:border-border-strong hover:bg-card",
  outline:
    "border border-border bg-transparent text-foreground hover:border-border-strong hover:bg-hover",
  ghost: "bg-transparent text-muted-foreground hover:text-foreground hover:bg-hover",
  danger: "bg-destructive text-white hover:bg-red-500",
  success: "bg-success text-[#ffffff] font-semibold hover:brightness-110",
  accent:
    "bg-primary text-primary-foreground font-semibold hover:bg-primary-strong shadow-[0_10px_30px_-12px_rgba(47,107,255,0.6)]",
  glass:
    "border border-border bg-surface-2 text-foreground backdrop-blur-md hover:bg-hover hover:border-border-strong",
}

const sizeClasses: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-xs gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-11 px-6 text-sm gap-2",
  icon: "size-10",
  iconSm: "size-8",
}

function spawnRipple(e: React.PointerEvent<HTMLElement>) {
  const el = e.currentTarget
  const rect = el.getBoundingClientRect()
  const size = Math.max(rect.width, rect.height)
  const span = document.createElement("span")
  span.className = "sg-ripple"
  span.style.width = span.style.height = `${size}px`
  span.style.left = `${e.clientX - rect.left - size / 2}px`
  span.style.top = `${e.clientY - rect.top - size / 2}px`
  el.appendChild(span)
  window.setTimeout(() => span.remove(), 650)
}

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  asChild?: boolean
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      asChild = false,
      loading = false,
      disabled,
      children,
      onPointerDown,
      ...props
    },
    ref,
  ) => {
    const Comp = asChild ? Slot : "button"
    const classes = cn(
      "relative inline-flex shrink-0 select-none items-center justify-center overflow-hidden whitespace-nowrap rounded-lg font-medium transition-all duration-150 active:scale-[.97] disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none",
      variantClasses[variant],
      sizeClasses[size],
      className,
    )
    const content = asChild ? (
      children
    ) : (
      <>
        {loading && <Loader2 className="size-4 animate-spin" />}
        {children}
      </>
    )
    return (
      <Comp
        ref={ref}
        className={classes}
        disabled={disabled || loading}
        onPointerDown={(e: React.PointerEvent<HTMLElement>) => {
          if (!disabled && !loading) spawnRipple(e)
          onPointerDown?.(e as React.PointerEvent<HTMLButtonElement>)
        }}
        {...props}
      >
        {content}
      </Comp>
    )
  },
)
Button.displayName = "Button"

export { Button }
