import { useMemo, useState } from "react"
import { toast } from "sonner"
import { DoorOpen, Pencil, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { Switch } from "@/components/ui/Switch"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { Field } from "@/components/widgets/Field"
import { useAuth } from "@/lib/auth"
import { useBuildings, useRoomMutations, useRooms } from "@/lib/queries"
import { ROOM_TYPES, formatApiError, type Room, type RoomPayload, type RoomType } from "@/lib/types"

const NO_FLOOR = "__none__"

interface RoomForm {
  building: string
  floor: string
  number: string
  name: string
  room_type: RoomType
  capacity: string
  is_active: boolean
}

/** Rooms per building and floor; staff assign them to visits on approval. */
export function RoomsTab() {
  const { can } = useAuth()
  const editable = can("manage_buildings")
  const buildings = useBuildings()
  const rooms = useRooms()
  const { create, update, remove } = useRoomMutations()
  const [editing, setEditing] = useState<Room | "new" | null>(null)
  const [deleting, setDeleting] = useState<Room | null>(null)
  const [filterBuilding, setFilterBuilding] = useState("all")
  const [form, setForm] = useState<RoomForm>({ building: "", floor: NO_FLOOR, number: "", name: "", room_type: "CLASSROOM", capacity: "", is_active: true })
  const [errors, setErrors] = useState<Record<string, string>>({})

  const buildingList = buildings.data ?? []
  const roomList = rooms.data ?? []
  const floorsOf = (buildingId: string) => buildingList.find((b) => String(b.id) === buildingId)?.floor_list ?? []

  const open = (r: Room | "new") => {
    setErrors({})
    setForm(
      r === "new"
        ? { building: buildingList[0] ? String(buildingList[0].id) : "", floor: NO_FLOOR, number: "", name: "", room_type: "CLASSROOM", capacity: "", is_active: true }
        : { building: String(r.building), floor: r.floor ? String(r.floor) : NO_FLOOR, number: r.number, name: r.name, room_type: r.room_type, capacity: r.capacity ? String(r.capacity) : "", is_active: r.is_active },
    )
    setEditing(r)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.building || !form.number.trim()) {
      setErrors({ number: form.number.trim() ? "" : "Room number is required", building: form.building ? "" : "Choose a building" })
      return
    }
    const payload: RoomPayload = {
      building: Number(form.building),
      floor: form.floor === NO_FLOOR ? null : Number(form.floor),
      number: form.number.trim(),
      name: form.name.trim(),
      room_type: form.room_type,
      capacity: form.capacity ? Number(form.capacity) : 0,
      is_active: form.is_active,
    }
    try {
      if (editing === "new") await create.mutateAsync(payload)
      else if (editing) await update.mutateAsync({ id: editing.id, data: payload })
      toast.success(editing === "new" ? "Room added" : "Room updated")
      setEditing(null)
    } catch (err) {
      const body = (err as { data?: Record<string, unknown> }).data
      const next: Record<string, string> = {}
      if (body && typeof body === "object") {
        for (const [k, v] of Object.entries(body)) next[k] = Array.isArray(v) ? v.map(String).join(" ") : String(v)
      }
      setErrors(next)
      toast.error("Could not save room", { description: formatApiError(err) })
    }
  }

  const onDelete = async () => {
    if (!deleting) return
    try {
      await remove.mutateAsync(deleting.id)
      toast.success("Room removed")
      setDeleting(null)
    } catch (err) {
      toast.error("Could not remove room", { description: formatApiError(err) })
    }
  }

  // Group for display: building -> floor -> rooms
  const groups = useMemo(() => {
    const visible = filterBuilding === "all" ? roomList : roomList.filter((r) => String(r.building) === filterBuilding)
    const map = new Map<string, Map<string, Room[]>>()
    for (const r of visible) {
      const floors = map.get(r.building_name) ?? new Map<string, Room[]>()
      const key = r.floor_name || "No floor"
      floors.set(key, [...(floors.get(key) ?? []), r])
      map.set(r.building_name, floors)
    }
    return [...map.entries()]
  }, [roomList, filterBuilding])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted-foreground">
          Labs, classrooms, interview cabins, placement halls. Staff pick one when approving a visit; trainers scan passes at the door to record attendance.
        </p>
        <div className="flex items-center gap-2">
          {buildingList.length > 1 && (
            <Select value={filterBuilding} onValueChange={setFilterBuilding}>
              <SelectTrigger className="w-44"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All buildings</SelectItem>
                {buildingList.map((b) => <SelectItem key={b.id} value={String(b.id)}>{b.name}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          {editable && <Button onClick={() => open("new")} disabled={buildingList.length === 0}><Plus className="size-4" /> Add room</Button>}
        </div>
      </div>

      {rooms.isLoading || buildings.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : roomList.length === 0 ? (
        <EmptyState icon={<DoorOpen className="size-6" />} title="No rooms yet" description="Add rooms per floor, e.g. 301 Java Lab, 402 Interview cabin, 501 Placement hall." />
      ) : (
        <div className="space-y-5">
          {groups.map(([buildingName, floors]) => (
            <section key={buildingName} className="card-surface overflow-hidden">
              <div className="border-b border-border bg-surface-2 px-4 py-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{buildingName}</div>
              {[...floors.entries()].map(([floorName, list]) => (
                <div key={floorName} className="border-b border-border/60 last:border-0">
                  <div className="px-4 pt-3 text-xs font-medium text-muted-foreground">{floorName}</div>
                  <ul className="divide-y divide-border/60">
                    {list.map((r) => (
                      <li key={r.id} className="flex items-center gap-3 px-4 py-2.5">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft font-mono text-xs font-bold text-primary">{r.number}</span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">{r.name || r.room_type_label}</div>
                          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                            <Badge size="sm">{r.room_type_label}</Badge>
                            {r.capacity > 0 && <span>{r.capacity} seats</span>}
                            {!r.is_active && <Badge tone="warning" size="sm">Not in use</Badge>}
                          </div>
                        </div>
                        {editable && (
                          <div className="flex gap-1">
                            <Button variant="ghost" size="iconSm" onClick={() => open(r)} aria-label={`Edit room ${r.number}`}><Pencil className="size-4" /></Button>
                            <Button variant="ghost" size="iconSm" className="hover:text-danger" onClick={() => setDeleting(r)} aria-label={`Remove room ${r.number}`}><Trash2 className="size-4" /></Button>
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </section>
          ))}
        </div>
      )}

      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing === "new" ? "Add room" : "Edit room"}</DialogTitle>
            <DialogDescription>Floors come from the building's floor count under Buildings.</DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
            <Field id="r-bld" label="Building" required error={errors.building}>
              <Select value={form.building} onValueChange={(v) => setForm((f) => ({ ...f, building: v, floor: NO_FLOOR }))}>
                <SelectTrigger id="r-bld"><SelectValue placeholder="Choose" /></SelectTrigger>
                <SelectContent>{buildingList.map((b) => <SelectItem key={b.id} value={String(b.id)}>{b.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field id="r-floor" label="Floor" error={errors.floor}>
              <Select value={form.floor} onValueChange={(v) => setForm((f) => ({ ...f, floor: v }))}>
                <SelectTrigger id="r-floor"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_FLOOR}>Not specified</SelectItem>
                  {floorsOf(form.building).map((fl) => <SelectItem key={fl.id} value={String(fl.id)}>{fl.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field id="r-num" label="Room number / door code" required error={errors.number}>
              <Input id="r-num" value={form.number} onChange={(e) => setForm((f) => ({ ...f, number: e.target.value }))} placeholder="e.g. 301" maxLength={30} autoFocus />
            </Field>
            <Field id="r-name" label="Name" hint="Optional, e.g. Java Lab" error={errors.name}>
              <Input id="r-name" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} maxLength={120} />
            </Field>
            <Field id="r-type" label="Room type" error={errors.room_type}>
              <Select value={form.room_type} onValueChange={(v) => setForm((f) => ({ ...f, room_type: v as RoomType }))}>
                <SelectTrigger id="r-type"><SelectValue /></SelectTrigger>
                <SelectContent>{ROOM_TYPES.map((t) => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field id="r-cap" label="Capacity" hint="Seats; leave blank if not tracked" error={errors.capacity}>
              <Input id="r-cap" type="number" min={0} value={form.capacity} onChange={(e) => setForm((f) => ({ ...f, capacity: e.target.value }))} />
            </Field>
            <div className="flex items-center gap-3 sm:col-span-2">
              <Switch id="r-active" checked={form.is_active} onCheckedChange={(v) => setForm((f) => ({ ...f, is_active: v }))} />
              <label htmlFor="r-active" className="text-sm">In use (can be assigned and scanned)</label>
            </div>
            <DialogFooter className="sm:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              <Button type="submit" loading={create.isPending || update.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Remove room ${deleting?.number}?`}
        description="Visits assigned to it will show no room; attendance already recorded there is deleted with it. Prefer marking it 'not in use' to keep history."
        confirmLabel="Remove"
        tone="danger"
        loading={remove.isPending}
        onConfirm={onDelete}
      />
    </div>
  )
}
