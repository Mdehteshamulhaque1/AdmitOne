import { useEffect, useMemo, useState } from "react"
import { ArrowRight, ChevronLeft, ChevronRight, Sun, Sunrise, Sunset } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Button } from "@/components/ui/Button"
import { Skeleton } from "@/components/ui/Skeleton"
import {
  initials,
  upcomingDays,
  usePublicAvailability,
  usePublicAvailabilityCalendar,
  usePublicHosts,
  type Draft,
} from "@/components/visitor/booking"
import { Chip, ChoiceTile, StepCard, StepSection } from "@/components/visitor/ui"
import { formatApiError, type AvailabilitySlot } from "@/lib/types"
import { useOrganizationContext } from "@/lib/visitor-api"
import { cn, formatDate } from "@/lib/utils"

const DAYS = upcomingDays(90)
const WEEKS = Math.ceil(DAYS.length / 7)

const PERIODS: { key: string; label: string; icon: typeof Sun; test: (h: number) => boolean }[] = [
  { key: "morning", label: "Morning", icon: Sunrise, test: (h) => h < 12 },
  { key: "afternoon", label: "Afternoon", icon: Sun, test: (h) => h >= 12 && h < 17 },
  { key: "evening", label: "Evening", icon: Sunset, test: (h) => h >= 17 },
]

/** Who the visitor meets and when: host cards, a week strip of dates, time chips. */
export function TimeStep({
  slug,
  draft,
  setDraft,
  onBack,
  onNext,
}: {
  slug: string
  draft: Draft
  setDraft: (d: Draft) => void
  onBack: () => void
  onNext: () => void
}) {
  const ctx = useOrganizationContext(slug)
  const hosts = usePublicHosts(slug, draft.department)
  const calendar = usePublicAvailabilityCalendar(slug, draft.host)
  const avail = usePublicAvailability(slug, draft.host, draft.visit_date)
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })

  const departments = ctx.data?.departments ?? []
  const hostList = hosts.data ?? []
  const counts = calendar.data?.days ?? {}
  const selectedIndex = DAYS.findIndex((d) => d.value === draft.visit_date)
  const [week, setWeek] = useState(Math.max(0, Math.floor(Math.max(selectedIndex, 0) / 7)))

  // One person takes bookings: they are the host.
  useEffect(() => {
    if (hostList.length === 1 && draft.host !== String(hostList[0].id)) set({ host: String(hostList[0].id), visit_date: "", slot: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hosts.data])

  // Like an appointment app: open on the earliest day with a free slot.
  useEffect(() => {
    if (!calendar.data || draft.visit_date) return
    const first = DAYS.findIndex((d) => (counts[d.value] ?? 0) > 0)
    if (first >= 0) {
      set({ visit_date: DAYS[first].value, slot: null })
      setWeek(Math.floor(first / 7))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calendar.data])

  const slots = avail.data?.slots ?? []
  const grouped = useMemo(
    () =>
      PERIODS.map((p) => ({ ...p, slots: slots.filter((s) => p.test(Number(s.start.slice(0, 2)))) })).filter((p) => p.slots.length > 0),
    [slots],
  )
  const host = hostList.find((h) => String(h.id) === draft.host)
  const weekDays = DAYS.slice(week * 7, week * 7 + 7)
  const freeDays = DAYS.filter((d) => (counts[d.value] ?? 0) > 0).length

  return (
    <StepCard
      title="Who are you meeting, and when?"
      subtitle="Only times inside working hours when your host is free are shown."
      onBack={onBack}
      action={
        <Button onClick={onNext} disabled={!draft.host || !draft.slot}>
          Continue <ArrowRight className="size-4" />
        </Button>
      }
    >
      <StepSection title="Person you're meeting" hint={hostList.length === 1 ? "The only person taking bookings here." : undefined}>
        {departments.length > 1 && (
          <div role="radiogroup" aria-label="Department" className="mb-3 flex flex-wrap gap-2">
            <Chip role="radio" selected={!draft.department} onClick={() => set({ department: "", host: "", visit_date: "", slot: null })}>
              All departments
            </Chip>
            {departments.map((d) => (
              <Chip key={d.id} role="radio" selected={draft.department === String(d.id)} onClick={() => set({ department: String(d.id), host: "", visit_date: "", slot: null })}>
                {d.name}
              </Chip>
            ))}
          </div>
        )}
        {hosts.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
        ) : hosts.isError ? (
          <Alert variant="danger"><span>The list of people didn't load. {formatApiError(hosts.error)}</span></Alert>
        ) : hostList.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border p-5 text-center text-sm text-muted-foreground">
            Nobody {draft.department ? "in this department " : ""}is taking bookings yet. Call reception to arrange your visit.
          </p>
        ) : (
          <div role="radiogroup" aria-label="Person you're meeting" className="grid gap-3 sm:grid-cols-2">
            {hostList.map((h) => (
              <ChoiceTile
                key={h.id}
                selected={draft.host === String(h.id)}
                onSelect={() => draft.host !== String(h.id) && set({ host: String(h.id), visit_date: "", slot: null })}
                icon={<span className="text-sm font-semibold">{initials(h.name)}</span>}
                title={h.name}
                description={h.designation || undefined}
              />
            ))}
          </div>
        )}
      </StepSection>

      {draft.host && (
        <StepSection
          title="Date"
          hint={calendar.isLoading ? "Checking which days are free…" : calendar.data ? `${freeDays} of the next 90 days have free times` : undefined}
          aside={
            <div className="flex items-center gap-1">
              <span className="mr-1 text-xs font-medium text-muted-foreground tabular-nums">
                {weekDays[0]?.day} {weekDays[0]?.month} – {weekDays[weekDays.length - 1]?.day} {weekDays[weekDays.length - 1]?.month}
              </span>
              <Button variant="outline" size="iconSm" onClick={() => setWeek((w) => Math.max(0, w - 1))} disabled={week === 0} aria-label="Previous week">
                <ChevronLeft className="size-4" />
              </Button>
              <Button variant="outline" size="iconSm" onClick={() => setWeek((w) => Math.min(WEEKS - 1, w + 1))} disabled={week >= WEEKS - 1} aria-label="Next week">
                <ChevronRight className="size-4" />
              </Button>
            </div>
          }
        >
          <div role="radiogroup" aria-label="Date" className="grid grid-cols-7 gap-1.5 sm:gap-2">
            {weekDays.map((d) => {
              const count = counts[d.value]
              const full = count === 0
              const active = draft.visit_date === d.value
              return (
                <button
                  key={d.value}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-label={`${formatDate(d.value)}${full ? ", no free times" : count ? `, ${count} free times` : ""}`}
                  disabled={full}
                  onClick={() => set({ visit_date: d.value, slot: null })}
                  className={cn(
                    "flex flex-col items-center rounded-xl border px-1 py-2 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card hover:border-primary/50",
                    full && "cursor-not-allowed border-dashed bg-transparent opacity-45 hover:border-border",
                  )}
                >
                  <span className={cn("text-[11px] font-medium", active ? "text-primary-foreground/80" : "text-muted-foreground")}>{d.weekday}</span>
                  <span className="text-lg font-semibold leading-tight tabular-nums">{d.day}</span>
                  <span className={cn("text-[10px] tabular-nums", active ? "text-primary-foreground/80" : "text-muted-foreground")}>
                    {full ? "Full" : count ? `${count} free` : d.month}
                  </span>
                </button>
              )
            })}
          </div>
        </StepSection>
      )}

      {draft.host && draft.visit_date && (
        <StepSection
          title="Arrival time"
          hint={avail.data ? `${formatDate(draft.visit_date)}. Each visit slot is ${avail.data.slot_duration_minutes} minutes${host ? ` with ${host.name}` : ""}.` : undefined}
        >
          {avail.isLoading ? (
            <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-9" />)}</div>
          ) : avail.isError ? (
            <Alert variant="warning"><span>{formatApiError(avail.error)}</span></Alert>
          ) : grouped.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border p-4 text-center text-sm text-muted-foreground">No free times on this day. Pick another date.</p>
          ) : (
            <div className="space-y-4">
              {grouped.map((p) => (
                <div key={p.key}>
                  <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <p.icon className="size-3.5" /> {p.label}
                  </div>
                  <div role="radiogroup" aria-label={`${p.label} times`} className="grid grid-cols-4 gap-2 sm:grid-cols-6">
                    {p.slots.map((s: AvailabilitySlot) => (
                      <Chip key={s.start} role="radio" selected={draft.slot?.start === s.start} onClick={() => set({ slot: s })}>
                        {s.start}
                      </Chip>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </StepSection>
      )}
    </StepCard>
  )
}
