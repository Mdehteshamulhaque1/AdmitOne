import { useEffect, useMemo, useState } from "react"
import { DoorOpen, Sparkles } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Field } from "@/components/widgets/Field"
import { useOrganization, useRooms } from "@/lib/queries"
import { ROOM_TYPES, type Room, type Visit } from "@/lib/types"
import { cn } from "@/lib/utils"

const NONE = "__none__"

/** The room type the workspace catalogue suggests for this visit's purpose. */
function suggestedRoomType(visit: Visit, catalogue?: { categories: { key: string; purposes: { label: string; room_type: string }[] }[] }): string {
  if (!catalogue) return ""
  const cat = catalogue.categories.find((c) => c.key === visit.visitor_category)
  const pools = cat ? [cat] : catalogue.categories
  for (const c of pools) {
    const hit = c.purposes.find((p) => p.label.toLowerCase() === visit.purpose.toLowerCase())
    if (hit?.room_type) return hit.room_type
  }
  return ""
}

interface AssignRoomDialogProps {
  visit: Visit | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** "approve": confirm approves (room optional). "assign": confirm only sets the room. */
  mode: "approve" | "assign"
  loading?: boolean
  onConfirm: (roomId: number | null) => void | Promise<void>
}

/**
 * Pick the room a visitor will be sent to. Rooms are grouped by building and
 * floor; the ones matching the catalogue's suggested room type for the
 * visit's purpose are listed first and flagged.
 */
export function AssignRoomDialog({ visit, open, onOpenChange, mode, loading, onConfirm }: AssignRoomDialogProps) {
  const rooms = useRooms({ enabled: open })
  const org = useOrganization(open)
  const [value, setValue] = useState<string>(NONE)

  useEffect(() => {
    if (open) setValue(visit?.room ? String(visit.room) : NONE)
  }, [open, visit?.room])

  const suggested = visit ? suggestedRoomType(visit, org.data?.visitor_catalogue) : ""
  const suggestedLabel = ROOM_TYPES.find((t) => t.value === suggested)?.label ?? ""

  const groups = useMemo(() => {
    const active = (rooms.data ?? []).filter((r) => r.is_active || String(r.id) === value)
    const byKey = new Map<string, Room[]>()
    for (const r of active) {
      const key = [r.building_name, r.floor_name || "No floor"].join(" · ")
      byKey.set(key, [...(byKey.get(key) ?? []), r])
    }
    return [...byKey.entries()].map(([label, list]) => ({
      label,
      rooms: [...list].sort((a, b) => Number(b.room_type === suggested) - Number(a.room_type === suggested) || a.number.localeCompare(b.number, undefined, { numeric: true })),
    }))
  }, [rooms.data, suggested, value])

  const picked = (rooms.data ?? []).find((r) => String(r.id) === value) ?? null
  const none = (rooms.data ?? []).length === 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{mode === "approve" ? "Approve and assign a room" : visit?.room ? "Change room" : "Assign a room"}</DialogTitle>
          <DialogDescription>
            {visit ? (
              <>
                {visit.visitor.full_name} · {visit.purpose}
                {suggestedLabel && (
                  <span className="mt-1 flex items-center gap-1 text-primary"><Sparkles className="size-3.5" /> Usually a {suggestedLabel.toLowerCase()}</span>
                )}
              </>
            ) : null}
          </DialogDescription>
        </DialogHeader>

        <Field id="room-pick" label="Room" hint={none ? "No rooms yet. Add them under Settings → Rooms." : "The visitor sees the room on their pass; trainers scan the pass at the door for attendance."}>
          <Select value={value} onValueChange={setValue} disabled={rooms.isLoading || none}>
            <SelectTrigger id="room-pick"><SelectValue placeholder={rooms.isLoading ? "Loading rooms…" : "Choose a room"} /></SelectTrigger>
            <SelectContent>
              <SelectItem value={NONE}>{mode === "approve" ? "No room yet (assign later)" : "No room"}</SelectItem>
              {groups.map((g) => (
                <SelectGroup key={g.label}>
                  <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{g.label}</div>
                  {g.rooms.map((r) => (
                    <SelectItem key={r.id} value={String(r.id)}>
                      <span className={cn(r.room_type === suggested && "font-semibold text-primary")}>
                        {r.number}{r.name ? ` · ${r.name}` : ""} <span className="text-muted-foreground">({r.room_type_label}{r.capacity ? `, ${r.capacity} seats` : ""})</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectGroup>
              ))}
            </SelectContent>
          </Select>
        </Field>

        {picked && (
          <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-2 p-3 text-sm">
            <span className="flex size-9 items-center justify-center rounded-lg bg-primary-soft text-primary"><DoorOpen className="size-4" /></span>
            <div className="min-w-0">
              <div className="font-semibold">{picked.label}</div>
              <div className="text-xs text-muted-foreground">{picked.building_name}{picked.floor_name ? ` · ${picked.floor_name}` : ""}</div>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>Cancel</Button>
          <Button type="button" loading={loading} onClick={() => void onConfirm(value === NONE ? null : Number(value))}>
            {mode === "approve" ? (value === NONE ? "Approve without room" : "Approve & assign") : "Save room"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
