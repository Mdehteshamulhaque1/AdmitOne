import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { motion } from "framer-motion"
import { TrendingDown, TrendingUp } from "lucide-react"
import { AnimatedNumber } from "@/components/widgets/AnimatedNumber"
import { Sparkline } from "@/components/widgets/Sparkline"
import { useChartPalette } from "@/lib/theme"
import { cn } from "@/lib/utils"

type Accent = "primary" | "cyan" | "info" | "warning" | "danger" | "violet"

interface KpiCardProps {
  label: string
  value: number
  suffix?: string
  icon: ReactNode
  accent?: Accent
  trend?: number | null
  trendLabel?: string
  sparkline?: number[]
  index?: number
  to?: string
  hint?: string
}

const iconBg: Record<Accent, string> = {
  primary: "bg-primary-soft text-primary",
  cyan: "bg-accent-soft text-accent",
  info: "bg-info-soft text-info",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  violet: "bg-violet-soft text-violet",
}

const sparkIndex: Record<Accent, number> = {
  primary: 0,
  info: 1,
  warning: 2,
  violet: 3,
  danger: 4,
  cyan: 1,
}

export function KpiCard({
  label,
  value,
  suffix,
  icon,
  accent = "primary",
  trend,
  trendLabel = "vs yesterday",
  sparkline,
  index = 0,
  to,
  hint,
}: KpiCardProps) {
  const palette = useChartPalette()
  const rising = (trend ?? 0) >= 0
  const body = (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: index * 0.05, ease: "easeOut" }}
      className={cn("group card-surface relative h-full overflow-hidden p-4 sm:p-5", to && "card-surface-hover")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className={cn("flex size-10 items-center justify-center rounded-xl transition-transform duration-300 group-hover:scale-105", iconBg[accent])}>
          {icon}
        </div>
        {trend !== undefined && trend !== null && (
          <span
            title={trendLabel}
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold",
              rising ? "bg-success-soft text-success" : "bg-danger-soft text-danger",
            )}
          >
            {rising ? <TrendingUp className="size-3.5" /> : <TrendingDown className="size-3.5" />}
            {Math.abs(trend)}%
          </span>
        )}
      </div>
      <div className="mt-4 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            <AnimatedNumber value={value} />
            {suffix && <span className="ml-1 text-base font-semibold text-muted-foreground">{suffix}</span>}
          </div>
          <div className="mt-1 text-sm font-medium leading-snug text-muted-foreground">{label}</div>
          {hint && <div className="mt-0.5 text-xs text-muted-foreground/80">{hint}</div>}
        </div>
        {sparkline && sparkline.length > 1 && (
          <Sparkline data={sparkline} color={palette.series[sparkIndex[accent]]} height={32} width={64} className="hidden shrink-0 opacity-80 sm:block" />
        )}
      </div>
    </motion.div>
  )
  if (to) {
    return (
      <Link to={to} className="block h-full rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        {body}
      </Link>
    )
  }
  return body
}
