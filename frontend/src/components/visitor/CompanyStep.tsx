import { useEffect, useState } from "react"
import { Building2, Search, XCircle } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Input } from "@/components/ui/Input"
import { Skeleton } from "@/components/ui/Skeleton"
import { ChoiceTile, StepCard } from "@/components/visitor/ui"
import { formatApiError } from "@/lib/types"
import { useOrganizationContext, useOrganizationSearch, type OrganizationResult } from "@/lib/visitor-api"

/**
 * Which company the visitor is visiting. Skipped automatically when the
 * booking link names the company or only one company takes bookings, the way
 * a clinic's own booking page never asks which clinic you mean.
 */
export function CompanyStep({
  preset,
  selected,
  onPick,
}: {
  preset: string
  selected: OrganizationResult | null
  onPick: (org: OrganizationResult, auto: boolean) => void
}) {
  const [q, setQ] = useState("")
  const directory = useOrganizationSearch(q)
  const all = useOrganizationSearch("")
  const presetCtx = useOrganizationContext(preset)

  // Booking link: the company is known.
  useEffect(() => {
    if (preset && presetCtx.data) {
      const o = presetCtx.data.organization
      onPick({ id: o.id, name: o.name, slug: o.slug, tagline: o.tagline, city: o.city, country: o.country, buildings: presetCtx.data.buildings }, true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, presetCtx.data])

  // Only one company takes bookings: nothing to choose.
  useEffect(() => {
    if (!preset && all.data?.length === 1) onPick(all.data[0], true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preset, all.data])

  const list = directory.data ?? []
  const showSearch = (all.data?.length ?? 0) > 6

  if ((preset && presetCtx.isLoading) || all.isLoading) return <Skeleton className="h-72 w-full rounded-2xl" />

  return (
    <StepCard title="Which company are you visiting?" subtitle="Choose the company that invited you. If you have a booking link from them, open it and this step is skipped.">
      {preset && presetCtx.isError && (
        <Alert variant="danger">
          <XCircle className="mt-0.5 size-4 shrink-0" />
          <span>No company matches the link <code>/{preset}</code>. Choose it from the list below.</span>
        </Alert>
      )}
      {showSearch && (
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by company name or city" className="pl-9" aria-label="Search companies" />
        </div>
      )}
      {directory.isError ? (
        <Alert variant="danger"><span>The company list didn't load. {formatApiError(directory.error)}</span></Alert>
      ) : directory.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
      ) : list.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          {q ? `No company matches “${q}”. Check the spelling, or ask your host for their booking link.` : "No companies are taking bookings yet."}
        </p>
      ) : (
        <div role="radiogroup" aria-label="Companies" className="grid gap-3 sm:grid-cols-2">
          {list.map((o) => (
            <ChoiceTile
              key={o.id}
              selected={selected?.id === o.id}
              onSelect={() => onPick(o, false)}
              icon={<Building2 className="size-5" />}
              title={o.name}
              description={[o.tagline, o.city].filter(Boolean).join(", ") || undefined}
            />
          ))}
        </div>
      )}
    </StepCard>
  )
}
