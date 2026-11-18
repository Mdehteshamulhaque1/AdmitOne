import { Badge, type BadgeTone } from "@/components/ui/Badge"
import { VISIT_STATUS_LABELS, type VisitStatus } from "@/lib/types"

export const STATUS_TONES: Record<VisitStatus, BadgeTone> = {
  PENDING: "warning",
  APPROVED: "info",
  REJECTED: "danger",
  CHECKED_IN: "success",
  CHECKED_OUT: "neutral",
  CANCELLED: "violet",
  ARCHIVED: "neutral",
}

export function StatusChip({ status, size = "md" }: { status: VisitStatus; size?: "sm" | "md" }) {
  return (
    <Badge tone={STATUS_TONES[status] ?? "neutral"} dot size={size}>
      {VISIT_STATUS_LABELS[status] ?? status}
    </Badge>
  )
}
