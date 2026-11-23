import { useEffect, useState } from "react"
import {
  ArrowRight,
  Award,
  Briefcase,
  ClipboardCheck,
  Coffee,
  FlaskConical,
  GraduationCap,
  Handshake,
  Info,
  MessageCircle,
  Package,
  PenLine,
  Presentation,
  Users,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Button } from "@/components/ui/Button"
import { Skeleton } from "@/components/ui/Skeleton"
import { Chip, ChoiceTile, StepCard, StepSection } from "@/components/visitor/ui"
import { purposeLabels, type Draft } from "@/components/visitor/booking"
import { DEFAULT_VISITOR_CATEGORIES, OTHER_PURPOSE } from "@/lib/student-options"
import { useOrganizationContext, useVisitorAccount } from "@/lib/visitor-api"
import { cn } from "@/lib/utils"

/** What each preset purpose means, in the visitor's words. */
const PURPOSE_HELP: Record<string, string> = {
  "course enquiry / demo class": "Ask about courses or sit in on a demo class",
  "training session (daily attendance)": "Your regular class; attendance is marked",
  "lab practice": "Hands-on practice in the lab",
  "mock interview": "A practice interview with a trainer",
  "company interview": "An interview with a hiring company",
  "pool placement drive": "A placement drive with several companies",
  "grooming / soft-skills class": "Communication and soft-skills session",
  "assessment / test": "A written or online test",
  "fee payment / admission": "Pay fees or complete your admission",
  "certificate collection": "Collect a certificate or document",
  "casual visit": "A short visit to meet someone",
  "counselling session": "Talk to a counsellor about courses",
  "progress discussion": "Discuss a student's progress",
  "interview panel": "Sit on an interview panel",
  "guest lecture / seminar": "Give a talk or run a seminar",
  "partnership meeting": "Discuss hiring or a partnership",
  delivery: "Drop off goods or documents",
  "maintenance / repair": "Fix equipment or facilities",
  installation: "Install equipment",
  "business meeting": "A scheduled meeting with someone here",
}

const ICON_RULES: [RegExp, LucideIcon][] = [
  [/interview/i, Briefcase],
  [/placement/i, Users],
  [/lab/i, FlaskConical],
  [/lecture|seminar/i, Presentation],
  [/training|class|course|demo/i, GraduationCap],
  [/assessment|test/i, ClipboardCheck],
  [/fee|payment|admission/i, Wallet],
  [/certificate/i, Award],
  [/delivery/i, Package],
  [/maintenance|repair|installation/i, Wrench],
  [/counsel|progress/i, MessageCircle],
  [/partnership|business|meeting/i, Handshake],
  [/casual/i, Coffee],
]

function purposeIcon(label: string): LucideIcon {
  if (label === OTHER_PURPOSE) return PenLine
  return ICON_RULES.find(([re]) => re.test(label))?.[1] ?? Info
}

export function PurposeStep({
  slug,
  draft,
  setDraft,
  onBack,
  onNext,
}: {
  slug: string
  draft: Draft
  setDraft: (d: Draft) => void
  onBack?: () => void
  onNext: () => void
}) {
  const ctx = useOrganizationContext(slug)
  const account = useVisitorAccount()
  const [changingCategory, setChangingCategory] = useState(false)
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })

  const catalogue = ctx.data?.visitor_categories ?? []
  const offered = (key: string) => catalogue.length === 0 || catalogue.some((c) => c.key === key)
  // The account step's list, limited to what this company offers, plus anything only it offers.
  const categories = [
    ...DEFAULT_VISITOR_CATEGORIES.filter((c) => offered(c.value)),
    ...catalogue.filter((c) => !DEFAULT_VISITOR_CATEGORIES.some((d) => d.value === c.key)).map((c) => ({ value: c.key, label: c.label })),
  ]
  const accountCategory = account.data?.category ?? ""

  // Default to the category the visitor gave at sign-up.
  useEffect(() => {
    if (draft.category || !ctx.data || categories.length === 0) return
    const next = categories.some((c) => c.value === accountCategory) ? accountCategory : categories[0].value
    set({ category: next })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(ctx.data), accountCategory, categories.length])

  if (ctx.isLoading) return <Skeleton className="h-96 w-full rounded-2xl" />
  if (ctx.isError || !ctx.data) {
    return <Alert variant="danger"><span>This company's booking options didn't load. Go back and choose the company again.</span></Alert>
  }

  const current = categories.find((c) => c.value === draft.category)
  const purposes = draft.category ? purposeLabels(draft.category, catalogue) : []
  const valid = Boolean(draft.category && draft.purpose && (draft.purpose !== OTHER_PURPOSE || draft.purpose_other.trim()))

  return (
    <StepCard
      title="What is your visit for?"
      subtitle={<>Visiting <span className="font-medium text-foreground">{ctx.data.organization.name}</span>. Reception assigns your room when they approve.</>}
      onBack={onBack}
      action={
        <Button onClick={onNext} disabled={!valid}>
          Continue <ArrowRight className="size-4" />
        </Button>
      }
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-secondary px-4 py-3 text-sm">
        <span className="text-muted-foreground">Booking as</span>
        <span className="font-semibold">{current?.label ?? "Choose below"}</span>
        {categories.length > 1 && (
          <button type="button" onClick={() => setChangingCategory((v) => !v)} className="ml-auto text-sm font-medium text-primary hover:underline" aria-expanded={changingCategory}>
            {changingCategory ? "Done" : "Change"}
          </button>
        )}
        {changingCategory && (
          <div role="radiogroup" aria-label="Who is visiting" className="flex w-full flex-wrap gap-2 pt-1">
            {categories.map((c) => (
              <Chip
                key={c.value}
                role="radio"
                selected={draft.category === c.value}
                onClick={() => {
                  if (c.value !== draft.category) set({ category: c.value, purpose: "", purpose_other: "" })
                  setChangingCategory(false)
                }}
              >
                {c.label}
              </Chip>
            ))}
          </div>
        )}
      </div>

      <StepSection title="Choose one">
        <div role="radiogroup" aria-label="Purpose of visit" className="grid gap-3 sm:grid-cols-2">
          {purposes.map((label) => {
            const Icon = purposeIcon(label)
            return (
              <ChoiceTile
                key={label}
                selected={draft.purpose === label}
                onSelect={() => set({ purpose: label, purpose_other: label === OTHER_PURPOSE ? draft.purpose_other : "" })}
                icon={<Icon className="size-5" />}
                title={label === OTHER_PURPOSE ? "Something else" : label}
                description={label === OTHER_PURPOSE ? "Tell us the reason in a few words" : PURPOSE_HELP[label.toLowerCase()]}
              />
            )
          })}
        </div>
      </StepSection>

      {draft.purpose === OTHER_PURPOSE && (
        <div>
          <label htmlFor="p-other" className="text-sm font-semibold">
            Reason for your visit <span className="text-danger">*</span>
          </label>
          <textarea
            id="p-other"
            autoFocus
            rows={2}
            maxLength={120}
            value={draft.purpose_other}
            onChange={(e) => set({ purpose_other: e.target.value })}
            placeholder="For example: collect my offer letter from the placement office"
            className={cn(
              "mt-2 w-full resize-none rounded-lg border border-input bg-secondary/60 px-3 py-2.5 text-sm shadow-sm",
              "placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/40",
            )}
          />
          <p className="mt-1 text-right text-xs text-muted-foreground tabular-nums">{draft.purpose_other.length}/120</p>
        </div>
      )}
    </StepCard>
  )
}
