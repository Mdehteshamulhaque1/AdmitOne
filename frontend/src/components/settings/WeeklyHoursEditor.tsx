import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Input } from "@/components/ui/Input"
import { Switch } from "@/components/ui/Switch"
import type { WeeklyWindow, WeeklyWorkingHours } from "@/lib/types"
import { cn } from "@/lib/utils"

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

interface Props {
  value: WeeklyWorkingHours
  onChange: (next: WeeklyWorkingHours) => void
  /** Daily fallback used for days with no override. */
  fallback: { start: string; end: string }
  disabled?: boolean
}

/**
 * Per-weekday booking windows. A day without an entry follows the plain
 * daily hours; a day with an empty list is closed; several windows model a
 * lunch break. Mirrors the validation in the API (ordered, non-overlapping).
 */
export function WeeklyHoursEditor({ value, onChange, fallback, disabled }: Props) {
  const set = (day: number, windows: WeeklyWindow[] | undefined) => {
    const next = { ...value }
    if (windows === undefined) delete next[String(day)]
    else next[String(day)] = windows
    onChange(next)
  }

  return (
    <div className="divide-y divide-border rounded-xl border border-border">
      {DAYS.map((label, day) => {
        const key = String(day)
        const custom = key in value
        const windows = value[key] ?? []
        const closed = custom && windows.length === 0
        return (
          <div key={key} className="grid gap-3 px-3 py-2.5 sm:grid-cols-[7rem_1fr]">
            <div className="flex items-center justify-between gap-2 sm:flex-col sm:items-start sm:justify-start">
              <span className={cn("text-sm font-medium", closed && "text-muted-foreground")}>{label}</span>
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch
                  checked={!closed}
                  disabled={disabled}
                  onCheckedChange={(open) => set(day, open ? [{ ...fallback }] : [])}
                  aria-label={`${label} open`}
                />
                {closed ? "Closed" : "Open"}
              </label>
            </div>
            <div className="space-y-2">
              {!custom && (
                <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>Uses daily hours {fallback.start}–{fallback.end}</span>
                  {!disabled && (
                    <Button type="button" variant="ghost" size="sm" onClick={() => set(day, [{ ...fallback }])}>
                      Customise
                    </Button>
                  )}
                </div>
              )}
              {custom && !closed && (
                <>
                  {windows.map((w, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <Input
                        type="time"
                        value={w.start}
                        disabled={disabled}
                        onChange={(e) => set(day, windows.map((x, j) => (j === i ? { ...x, start: e.target.value } : x)))}
                        className="h-9 w-28"
                        aria-label={`${label} window ${i + 1} start`}
                      />
                      <span className="text-xs text-muted-foreground">to</span>
                      <Input
                        type="time"
                        value={w.end}
                        disabled={disabled}
                        onChange={(e) => set(day, windows.map((x, j) => (j === i ? { ...x, end: e.target.value } : x)))}
                        className="h-9 w-28"
                        aria-label={`${label} window ${i + 1} end`}
                      />
                      {!disabled && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="iconSm"
                          aria-label="Remove window"
                          onClick={() => {
                            const rest = windows.filter((_, j) => j !== i)
                            set(day, rest.length ? rest : undefined)
                          }}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      )}
                    </div>
                  ))}
                  {!disabled && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        const last = windows[windows.length - 1]
                        set(day, [...windows, { start: last ? last.end : fallback.start, end: fallback.end }])
                      }}
                    >
                      <Plus className="size-3.5" /> Add window (e.g. after lunch)
                    </Button>
                  )}
                </>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
