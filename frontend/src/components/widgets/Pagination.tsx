import { ChevronLeft, ChevronRight } from "lucide-react"
import { Button } from "@/components/ui/Button"

interface PaginationProps {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  label?: string
  isFetching?: boolean
}

export function Pagination({ page, pageSize, total, onPageChange, label = "items", isFetching }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1
  const end = Math.min(total, page * pageSize)
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
      <p className="text-xs text-muted-foreground sm:text-sm">
        {total === 0 ? `No ${label}` : `${start}–${end} of ${total} ${label}`}
        {isFetching && <span className="ml-2 text-xs text-muted-foreground/70">Updating…</span>}
      </p>
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground sm:text-sm">
          Page {page} of {totalPages}
        </span>
        <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page">
          <ChevronLeft className="size-4" /> <span className="hidden sm:inline">Prev</span>
        </Button>
        <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label="Next page">
          <span className="hidden sm:inline">Next</span> <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  )
}
