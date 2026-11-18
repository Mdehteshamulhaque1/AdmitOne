import { useState } from "react"
import { toast } from "sonner"
import { Ban, ShieldCheck, ShieldOff } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { EmptyState } from "@/components/ui/EmptyState"
import { Skeleton } from "@/components/ui/Skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { PageHeader } from "@/components/widgets/PageHeader"
import { Pagination } from "@/components/widgets/Pagination"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { useAuth } from "@/lib/auth"
import { useBlacklist, useUnblacklistVisitor } from "@/lib/queries"
import { formatApiError, type BlacklistEntry } from "@/lib/types"
import { formatDate } from "@/lib/utils"

const PAGE_SIZE = 20

export function BlacklistPage() {
  const { can } = useAuth()
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(1)
  const [lifting, setLifting] = useState<BlacklistEntry | null>(null)
  const { data, isLoading, isError, isFetching, refetch } = useBlacklist({ search, page })
  const unblacklist = useUnblacklistVisitor()

  const lift = async () => {
    if (!lifting) return
    try {
      const res = await unblacklist.mutateAsync(lifting.visitor.id)
      toast.success("Blacklist lifted", { description: res.detail })
      setLifting(null)
    } catch (e) {
      toast.error("Could not lift blacklist", { description: formatApiError(e) })
    }
  }

  const rows = data?.results ?? []

  return (
    <div className="space-y-5">
      <PageHeader
        title="Blacklist"
        description="Visitors denied entry across every gate in your workspace. Security can add entries; only admins can lift them."
        actions={
          <Badge tone="danger" className="gap-1.5">
            <Ban className="size-3" /> {data?.count ?? 0} active
          </Badge>
        }
      />
      {isError && <QueryErrorState message="Couldn't load the blacklist." retry={() => void refetch()} />}

      <SearchInput value={search} onChange={(v) => { setSearch(v); setPage(1) }} placeholder="Search by name, phone, company or note…" className="w-full sm:w-96" />

      <div className="card-surface overflow-hidden">
        {isLoading ? (
          <div className="space-y-3 p-5">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : rows.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<ShieldCheck className="size-6" />}
              title={search ? "No matches" : "Nobody is blacklisted"}
              description={search ? "Try a different search." : "Blacklist a visitor from their profile in the directory when needed."}
            />
          </div>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Visitor</TableHead>
                  <TableHead>Reason</TableHead>
                  <TableHead>Notes</TableHead>
                  <TableHead>Added</TableHead>
                  {can("manage_org") && <TableHead className="text-right"><span className="sr-only">Actions</span></TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar name={entry.visitor.full_name} src={entry.visitor.photo} />
                        <div className="min-w-0">
                          <div className="truncate font-medium">{entry.visitor.full_name}</div>
                          <div className="truncate text-xs text-muted-foreground">{entry.visitor.phone}{entry.visitor.company ? ` · ${entry.visitor.company}` : ""}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell><Badge tone="danger">{entry.reason_label}</Badge></TableCell>
                    <TableCell className="max-w-[20rem] whitespace-normal text-sm text-muted-foreground">{entry.comment || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(entry.created_at)}
                      {entry.added_by_name && <span className="block text-xs">by {entry.added_by_name}</span>}
                    </TableCell>
                    {can("manage_org") && (
                      <TableCell className="text-right">
                        <Button variant="outline" size="sm" onClick={() => setLifting(entry)}>
                          <ShieldOff className="size-3.5" /> Lift
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <Pagination page={page} pageSize={PAGE_SIZE} total={data?.count ?? 0} onPageChange={setPage} label="entries" isFetching={isFetching} />
          </>
        )}
      </div>

      <ConfirmDialog
        open={lifting !== null}
        onOpenChange={(o) => !o && setLifting(null)}
        title="Lift this blacklist entry?"
        description={lifting ? `${lifting.visitor.full_name} will be allowed to be approved and checked in again. This is recorded in the audit log.` : undefined}
        confirmLabel="Lift blacklist"
        loading={unblacklist.isPending}
        onConfirm={lift}
      />
    </div>
  )
}
