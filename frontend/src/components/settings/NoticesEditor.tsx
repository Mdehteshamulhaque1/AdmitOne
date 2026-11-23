import { useEffect, useState } from "react"
import { toast } from "sonner"
import { Megaphone, Plus, Save, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input, Textarea } from "@/components/ui/Input"
import { Skeleton } from "@/components/ui/Skeleton"
import { useAuth } from "@/lib/auth"
import { useOrganization, useUpdateOrganization } from "@/lib/queries"
import { formatApiError } from "@/lib/types"
import { todayIso } from "@/lib/utils"

export interface PublicNotice {
  title: string
  body: string
  published_on: string
  until: string
}

const MAX = 20

/** Admin-written notices shown on the public "Public notice" page. */
export function NoticesEditor() {
  const { can } = useAuth()
  const editable = can("manage_org")
  const org = useOrganization()
  const update = useUpdateOrganization()
  const [notices, setNotices] = useState<PublicNotice[]>([])
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    const saved = (org.data?.visitor_policies?.public_notices as PublicNotice[] | undefined) ?? []
    setNotices(saved)
    setDirty(false)
  }, [org.data])

  const change = (i: number, patch: Partial<PublicNotice>) => {
    setNotices((list) => list.map((n, j) => (j === i ? { ...n, ...patch } : n)))
    setDirty(true)
  }

  const save = async () => {
    if (notices.some((n) => !n.title.trim())) {
      toast.error("Every notice needs a title")
      return
    }
    try {
      // Settings are saved as one block: keep every other visitor setting as it is.
      await update.mutateAsync({ visitor_policies: { ...(org.data?.visitor_policies ?? {}), public_notices: notices } })
      toast.success("Notices published")
      setDirty(false)
    } catch (e) {
      toast.error("Notices weren't saved", { description: formatApiError(e) })
    }
  }

  if (org.isLoading) return <Skeleton className="h-64 w-full" />

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2"><Megaphone className="size-4 text-primary" /> Public notices</CardTitle>
          <CardDescription>Shown to everyone on the Public Notice page before they apply for a pass. Newest first; a notice disappears after its “show until” date.</CardDescription>
        </div>
        {editable && (
          <Button
            variant="outline"
            size="sm"
            disabled={notices.length >= MAX}
            onClick={() => {
              setNotices((list) => [{ title: "", body: "", published_on: todayIso(), until: "" }, ...list])
              setDirty(true)
            }}
          >
            <Plus className="size-4" /> New notice
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {notices.length === 0 ? (
          <EmptyState icon={<Megaphone className="size-6" />} title="No notices published" description="Use notices for gate closures, holidays, new rules or timing changes." />
        ) : (
          notices.map((n, i) => (
            <div key={i} className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex gap-3">
                <Input value={n.title} onChange={(e) => change(i, { title: e.target.value })} placeholder="Title, e.g. Gate 2 closed on Saturday" maxLength={120} disabled={!editable} aria-label="Notice title" />
                {editable && (
                  <Button variant="ghost" size="icon" aria-label="Delete notice" onClick={() => { setNotices((list) => list.filter((_, j) => j !== i)); setDirty(true) }}>
                    <Trash2 className="size-4" />
                  </Button>
                )}
              </div>
              <Textarea rows={2} value={n.body} onChange={(e) => change(i, { body: e.target.value })} placeholder="Details visitors should know" maxLength={1000} disabled={!editable} aria-label="Notice details" />
              <div className="flex flex-wrap gap-4 text-sm">
                <label className="flex items-center gap-2 text-muted-foreground">
                  Published
                  <Input type="date" className="h-9 w-auto" value={n.published_on} onChange={(e) => change(i, { published_on: e.target.value })} disabled={!editable} />
                </label>
                <label className="flex items-center gap-2 text-muted-foreground">
                  Show until
                  <Input type="date" className="h-9 w-auto" value={n.until} min={n.published_on} onChange={(e) => change(i, { until: e.target.value })} disabled={!editable} />
                </label>
              </div>
            </div>
          ))
        )}
        {editable && (
          <div className="flex justify-end">
            <Button onClick={save} loading={update.isPending} disabled={!dirty}>
              <Save className="size-4" /> Publish changes
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
