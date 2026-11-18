import type { ReactNode } from "react"

interface ChartTooltipProps {
  active?: boolean
  payload?: { name: string; value: number | string; color?: string; dataKey?: string; payload?: Record<string, unknown> }[]
  label?: ReactNode
  format?: (v: number) => string
  labelFormatter?: (label: ReactNode, payload?: Record<string, unknown>) => ReactNode
}

export function ChartTooltip({ active, payload, label, format, labelFormatter }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const heading = labelFormatter ? labelFormatter(label, payload[0]?.payload) : label
  return (
    <div className="rounded-xl border border-border bg-popover px-3.5 py-2.5 text-popover-foreground shadow-lift">
      {heading !== undefined && heading !== null && heading !== "" && (
        <div className="mb-1.5 text-xs font-semibold">{heading}</div>
      )}
      <div className="space-y-1">
        {payload.map((p) => (
          <div key={p.dataKey ?? p.name} className="flex items-center gap-2 text-xs">
            <span className="size-2 rounded-full" style={{ background: p.color }} />
            <span className="text-muted-foreground">{p.name}</span>
            <span className="ml-auto pl-4 font-semibold">{format ? format(Number(p.value)) : p.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
