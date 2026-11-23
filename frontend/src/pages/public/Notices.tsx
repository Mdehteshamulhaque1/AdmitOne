import { useQuery } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { CalendarDays, Megaphone } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Skeleton } from "@/components/ui/Skeleton"
import { PublicLayout } from "@/components/public/PublicNav"
import { api } from "@/lib/api"
import { formatApiError } from "@/lib/types"
import { formatDate } from "@/lib/utils"

interface Notice {
  organization: string
  organization_slug: string
  title: string
  body: string
  published_on: string
  until: string
}

export function NoticesPage() {
  const notices = useQuery({
    queryKey: ["public", "notices"],
    queryFn: () => api<{ notices: Notice[] }>("/api/public/notices/"),
    staleTime: 60_000,
  })
  const list = notices.data?.notices ?? []
  const manyOrgs = new Set(list.map((n) => n.organization_slug)).size > 1

  return (
    <PublicLayout>
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight">Public notice</h1>
        <p className="mt-2 text-muted-foreground">Announcements from the administration about visits, gate timings and closures. Please read them before you apply for a pass.</p>

        <div className="mt-8 space-y-4">
          {notices.isLoading ? (
            [...Array(2)].map((_, i) => <Skeleton key={i} className="h-28 w-full rounded-2xl" />)
          ) : notices.isError ? (
            <Alert variant="danger"><span>Notices didn't load. {formatApiError(notices.error)}</span></Alert>
          ) : list.length === 0 ? (
            <div className="rounded-2xl border border-border bg-card p-8 text-center">
              <Megaphone className="mx-auto size-7 text-muted-foreground" />
              <p className="mt-3 font-medium">No notices right now</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Gate timings are normal. You can <Link to="/visitor" className="font-medium text-primary hover:underline">apply for a visitor pass</Link>.
              </p>
            </div>
          ) : (
            list.map((n, i) => (
              <article key={`${n.organization_slug}-${i}`} className="rounded-2xl border border-border bg-card p-5 shadow-card">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1"><CalendarDays className="size-3.5" /> {n.published_on ? formatDate(n.published_on) : ""}</span>
                  {manyOrgs && <span>{n.organization}</span>}
                  {n.until && <span>Valid until {formatDate(n.until)}</span>}
                </div>
                <h2 className="mt-2 text-lg font-semibold tracking-tight">{n.title}</h2>
                {n.body && <p className="mt-1.5 whitespace-pre-line text-sm text-muted-foreground">{n.body}</p>}
              </article>
            ))
          )}
        </div>
      </div>
    </PublicLayout>
  )
}
