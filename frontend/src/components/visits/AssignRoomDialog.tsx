import { useEffect, useMemo, useState } from "react"
import { DoorOpen, Plus, Sparkles } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/Button"
import { Input } from "@/components/ui/Input"
import { Chip } from "@/components/widgets/Choice"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Field } from "@/components/widgets/Field"
import { useAuth } from "@/lib/auth"
import { useBuildings, useOrganization, useRoomMutations, useRooms } from "@/lib/queries"
import { ROOM_TYPES, formatApiError, type Room, type RoomType, type Visit } from "@/lib/types"
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
  const { can } = useAuth()
  const canAdd = can("manage_buildings")
  const buildings = useBuildings()
  const { create } = useRoomMutations()
  const [value, setValue] = useState<string>(NONE)
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState({ number: "", name: "", room_type: "" as RoomType | "", building: "", floor: "" })

  const suggested = visit ? suggestedRoomType(visit, org.data?.visitor_catalogue) : ""
  const suggestedLabel = ROOM_TYPES.find((t) => t.value === suggested)?.label ?? ""

  useEffect(() => {
    if (open) {
      setValue(visit?.room ? String(visit.room) : NONE)
      setDraft({ number: "", name: "", room_type: (suggested as RoomType) || "", building: "", floor: "" })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, visit?.room])

  // The suggested type (from the purpose) loads with the workspace settings: pre-select it.
  useEffect(() => {
    if (open && suggested) setDraft((d) => (d.room_type ? d : { ...d, room_type: suggested as RoomType }))
  }, [open, suggested])

  // No rooms yet: open the "add a room" form straight away (for people allowed to add rooms).
  useEffect(() => {
    if (open) setAdding(canAdd && rooms.data !== undefined && rooms.data.length === 0)
  }, [open, canAdd, rooms.data])

  const buildingList = buildings.data ?? []
  const buildingId = draft.building || (buildingList[0] ? String(buildingList[0].id) : "")
  const floors = [...(buildingList.find((b) => String(b.id) === buildingId)?.floor_list ?? [])].sort((a, b) => a.level - b.level)
  const floorId = draft.floor || (floors.length === 1 ? String(floors[0].id) : "")

  const addRoom = async () => {
    if (!draft.number.trim() || !buildingId) return
    try {
      const room = await create.mutateAsync({
        building: Number(buildingId),
        floor: floorId ? Number(floorId) : null,
        number: draft.number.trim(),
        name: draft.name.trim(),
        room_type: (draft.room_type || "OTHER") as RoomType,
      })
      setValue(String(room.id))
      setAdding(false)
      toast.success(`Room ${room.number} added`, { description: "Selected for this visit." })
    } catch (e) {
      toast.error("The room wasn't added", { description: formatApiError(e) })
    }
  }

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

        {!(none && adding) && (
        <Field
          id="room-pick"
          label="Room"
          hint={none ? (canAdd ? "No rooms yet. Add one below." : "No rooms yet. Ask an admin to add rooms under Settings → Rooms.") : "The visitor sees the room on their pass; trainers scan the pass at the door for attendance."}
        >
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
        )}

        {canAdd && !adding && (
          <button type="button" onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
            <Plus className="size-4" /> Add a new room
          </button>
        )}

        {canAdd && adding && (
          <div className="space-y-4 rounded-xl border border-border p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">Add a room</div>
              {!none && (
                <button type="button" onClick={() => setAdding(false)} className="text-xs font-medium text-muted-foreground hover:text-foreground">Cancel</button>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
              <Field id="new-room-number" label="Room number" required>
                <Input id="new-room-number" value={draft.number} onChange={(e) => setDraft((d) => ({ ...d, number: e.target.value }))} placeholder="e.g. 101" maxLength={30} autoFocus />
              </Field>
              <Field id="new-room-name" label="Room name" hint="Optional.">
                <Input id="new-room-name" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="e.g. Counselling room" maxLength={100} />
              </Field>
            </div>
            <div>
              <div className="mb-2 text-sm font-medium">Type</div>
              <div role="radiogroup" aria-label="Room type" className="flex flex-wrap gap-2">
                {ROOM_TYPES.map((t) => (
                  <Chip key={t.value} role="radio" className="h-8 text-xs" selected={draft.room_type === t.value} onClick={() => setDraft((d) => ({ ...d, room_type: t.value }))}>
                    {t.label}
                  </Chip>
                ))}
              </div>
            </div>
            {buildingList.length > 1 && (
              <div>
                <div className="mb-2 text-sm font-medium">Building</div>
                <div role="radiogroup" aria-label="Building" className="flex flex-wrap gap-2">
                  {buildingList.map((b) => (
                    <Chip key={b.id} role="radio" className="h-8 text-xs" selected={buildingId === String(b.id)} onClick={() => setDraft((d) => ({ ...d, building: String(b.id), floor: "" }))}>{b.name}</Chip>
                  ))}
                </div>
              </div>
            )}
            {floors.length > 1 && (
              <div>
                <div className="mb-2 text-sm font-medium">Floor</div>
                <div role="radiogroup" aria-label="Floor" className="flex flex-wrap gap-2">
                  {floors.map((f) => (
                    <Chip key={f.id} role="radio" className="h-8 text-xs" selected={floorId === String(f.id)} onClick={() => setDraft((d) => ({ ...d, floor: String(f.id) }))}>{f.name}</Chip>
                  ))}
                </div>
              </div>
            )}
            {buildingList.length === 0 && !buildings.isLoading && (
              <p className="text-xs text-danger">Add a building under Settings → Buildings first.</p>
            )}
            <Button type="button" variant="secondary" className="w-full" onClick={addRoom} loading={create.isPending} disabled={!draft.number.trim() || !buildingId}>
              <Plus className="size-4" /> Add room and select it
            </Button>
          </div>
        )}

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
