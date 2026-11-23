import { useCallback, useState } from "react"
import { Link, useSearchParams } from "react-router-dom"
import { Ban, Eye, UserPlus, Users } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table"
import { PageHeader } from "@/components/widgets/PageHeader"
import { Pagination } from "@/components/widgets/Pagination"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { VisitDrawer } from "@/components/visits/VisitDrawer"
import { VisitorDrawer } from "@/components/visitors/VisitorDrawer"
import { useAuth } from "@/lib/auth"
import { useVisitors } from "@/lib/queries"
import type { Visit, Visitor } from "@/lib/types"
import { formatDate, formatRelative } from "@/lib/utils"

const PAGE_SIZE = 20

export function VisitorsPage() {
  const { can } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const q = searchParams.get("q") ?? ""
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1)
  const filter = searchParams.get("filter") ?? "all"
  const ordering = searchParams.get("ordering") ?? "-created_at"
  const [selected, setSelected] = useState<Visitor | null>(null)
  const [selectedVisit, setSelectedVisit] = useState<Visit | null>(null)

  const { data, isLoading, isError, isFetching, refetch } = useVisitors({
    search: q,
    page,
    blacklisted: filter === "blacklisted" ? true : filter === "active" ? false : undefined,
    ordering,
  })

  const update = useCallback(
    (patch: Record<string, string | undefined>, resetPage = true) => {
      const next = new URLSearchParams(searchParams)
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined || v === "") next.delete(k)
        else next.set(k, v)
      }
      if (resetPage) next.delete("page")
      setSearchParams(next, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const visitors = data?.visitors ?? []
  const total = data?.total ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        title="Visitor directory"
        description="Everyone who has ever been registered in your workspace, with their visit history and status."
        actions={
          can("create_visitor") && (
            <Button asChild>
              <Link to="/dashboard/register-visit">
                <UserPlus className="size-4" /> Register visit
              </Link>
            </Button>
          )
        }
      />

      {isError && <QueryErrorState message="Couldn't load visitors." retry={() => void refetch()} />}

      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={q} onChange={(v) => update({ q: v })} placeholder="Search by name, phone, email or company…" className="w-full sm:w-80" autoFocus={Boolean(q)} />
        <Select value={filter} onValueChange={(v) => update({ filter: v === "all" ? undefined : v })}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All visitors</SelectItem>
            <SelectItem value="active">Active only</SelectItem>
            <SelectItem value="blacklisted">Blacklisted</SelectItem>
          </SelectContent>
        </Select>
        <Select value={ordering} onValueChange={(v) => update({ ordering: v })}>
          <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="-created_at">Newest first</SelectItem>
            <SelectItem value="created_at">Oldest first</SelectItem>
            <SelectItem value="full_name">Name A–Z</SelectItem>
            <SelectItem value="-visit_count">Most visits</SelectItem>
            <SelectItem value="-last_visit_at">Recently visited</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="card-surface overflow-hidden">
        {isLoading ? (
          <div className="space-y-3 p-5">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : visitors.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Users className="size-6" />}
              title={q || filter !== "all" ? "No visitors match" : "No visitors yet"}
              description={q || filter !== "all" ? "Try a different search or filter." : "Register a visit to start building your directory."}
              action={
                can("create_visitor") && (
                  <Button size="sm" asChild>
                    <Link to="/dashboard/register-visit"><UserPlus className="size-4" /> Register visit</Link>
                  </Button>
                )
              }
            />
          </div>
        ) : (
          <>
            <div className="hidden md:block">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Visitor</TableHead>
                    <TableHead>Company</TableHead>
                    <TableHead>Contact</TableHead>
                    <TableHead>ID document</TableHead>
                    <TableHead>Visits</TableHead>
                    <TableHead>Last visit</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visitors.map((v) => (
                    <TableRow key={v.id} className="cursor-pointer" onClick={() => setSelected(v)}>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <Avatar name={v.full_name} src={v.photo} />
                          <div className="min-w-0">
                            <div className="truncate font-medium">{v.full_name}</div>
                            <div className="truncate text-xs text-muted-foreground">{v.designation || `Since ${formatDate(v.created_at)}`}</div>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{v.company || "—"}</TableCell>
                      <TableCell>
                        <div className="text-sm">{v.phone}</div>
                        <div className="truncate text-xs text-muted-foreground">{v.email}</div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {v.document_type ? (
                          <span className="text-xs">
                            {v.document_type.replace(/_/g, " ")}
                            <span className="block font-mono text-muted-foreground/70">{v.document_number || "—"}</span>
                          </span>
                        ) : "—"}
                      </TableCell>
                      <TableCell className="tabular-nums">{v.visit_count ?? 0}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{v.last_visit_at ? formatRelative(v.last_visit_at) : "—"}</TableCell>
                      <TableCell>
                        {v.is_blacklisted ? (
                          <Badge tone="danger" dot><Ban className="size-3" /> Blacklisted</Badge>
                        ) : (
                          <Badge tone="success" dot>Active</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="iconSm" onClick={(e) => { e.stopPropagation(); setSelected(v) }} aria-label={`View ${v.full_name}`}>
                          <Eye className="size-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <ul className="divide-y divide-border md:hidden">
              {visitors.map((v) => (
                <li key={v.id}>
                  <button type="button" onClick={() => setSelected(v)} className="flex w-full items-center gap-3 p-4 text-left">
                    <Avatar name={v.full_name} src={v.photo} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-medium">{v.full_name}</span>
                        {v.is_blacklisted ? <Badge tone="danger" size="sm">Blacklisted</Badge> : <Badge tone="success" size="sm">Active</Badge>}
                      </div>
                      <div className="truncate text-xs text-muted-foreground">{v.company || v.phone}</div>
                      <div className="text-xs text-muted-foreground">{v.visit_count ?? 0} visits</div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
            <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={(p) => update({ page: String(p) }, false)} label="visitors" isFetching={isFetching} />
          </>
        )}
      </div>

      <VisitorDrawer
        visitor={selected}
        open={selected !== null}
        onOpenChange={(o) => !o && setSelected(null)}
        onOpenVisit={(visit) => setSelectedVisit(visit)}
      />
      <VisitDrawer visitId={selectedVisit?.id ?? null} initial={selectedVisit} open={selectedVisit !== null} onOpenChange={(o) => !o && setSelectedVisit(null)} />
    </div>
  )
}
