import { useEffect, useState } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import {
  Building2,
  Clock,
  DoorOpen,
  ExternalLink,
  ListChecks,
  KeyRound,
  Layers,
  Link2,
  Megaphone,
  Plus,
  Save,
  Trash2,
  UserRound,
  Pencil,
} from "lucide-react"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input, Textarea } from "@/components/ui/Input"
import { Skeleton } from "@/components/ui/Skeleton"
import { Switch } from "@/components/ui/Switch"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { CopyButton } from "@/components/widgets/CopyButton"
import { Field } from "@/components/widgets/Field"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { useAuth } from "@/lib/auth"
import {
  useBuildingMutations,
  useBuildings,
  useChangePassword,
  useDepartmentMutations,
  useDepartments,
  useOrganization,
  useUpdateOrganization,
  useUpdateProfile,
} from "@/lib/queries"
import { ROLE_LABELS, formatApiError, type Building, type Department, type WeeklyWorkingHours } from "@/lib/types"
import { CatalogueEditor } from "@/components/settings/CatalogueEditor"
import { NoticesEditor } from "@/components/settings/NoticesEditor"
import { RoomsTab } from "@/components/settings/RoomsTab"
import { WeeklyHoursEditor } from "@/components/settings/WeeklyHoursEditor"

type Tab = "workspace" | "buildings" | "rooms" | "departments" | "visitors" | "notices" | "account"
const TABS: { value: Tab; label: string; icon: typeof Building2; adminOnly?: boolean }[] = [
  { value: "workspace", label: "Workspace", icon: Building2 },
  { value: "buildings", label: "Buildings", icon: Layers },
  { value: "rooms", label: "Rooms", icon: DoorOpen },
  { value: "departments", label: "Departments", icon: Layers },
  { value: "visitors", label: "Visitor options", icon: ListChecks },
  { value: "notices", label: "Public notices", icon: Megaphone },
  { value: "account", label: "My account", icon: UserRound },
]

/* ---------------------------------------------------------------- workspace */

const orgSchema = z.object({
  name: z.string().trim().min(2, "Workspace name is required"),
  tagline: z.string().trim(),
  address: z.string().trim(),
  city: z.string().trim(),
  country: z.string().trim(),
  timezone: z.string().trim().min(1, "Timezone is required"),
  working_hours_start: z.string().min(1, "Required"),
  working_hours_end: z.string().min(1, "Required"),
  reminder_offsets: z.string().trim(),
  slot_duration: z.coerce.number().int().min(5).max(480),
})
type OrgValues = z.infer<typeof orgSchema>

function WorkspaceTab() {
  const { can } = useAuth()
  const editable = can("manage_org")
  const org = useOrganization()
  const update = useUpdateOrganization()
  const form = useForm<OrgValues>({ resolver: zodResolver(orgSchema) })
  const [weekly, setWeekly] = useState<WeeklyWorkingHours>({})

  useEffect(() => {
    if (!org.data) return
    setWeekly(org.data.weekly_working_hours ?? {})
    const policies = org.data.visitor_policies ?? {}
    const offsets = Array.isArray(policies.reminder_offsets_hours) ? (policies.reminder_offsets_hours as number[]) : [24, 1]
    form.reset({
      name: org.data.name,
      tagline: org.data.tagline ?? "",
      address: org.data.address ?? "",
      city: org.data.city ?? "",
      country: org.data.country ?? "",
      timezone: org.data.timezone,
      working_hours_start: org.data.working_hours_start.slice(0, 5),
      working_hours_end: org.data.working_hours_end.slice(0, 5),
      reminder_offsets: offsets.join(", "),
      slot_duration: typeof policies.slot_duration_minutes === "number" ? policies.slot_duration_minutes : 30,
    })
  }, [org.data, form])

  const onSubmit = async (values: OrgValues) => {
    const offsets = values.reminder_offsets
      .split(/[,\s]+/)
      .filter(Boolean)
      .map((n) => Number(n))
    if (offsets.some((n) => !Number.isInteger(n) || n <= 0)) {
      form.setError("reminder_offsets", { message: "Use whole hours, e.g. 24, 1" })
      return
    }
    try {
      await update.mutateAsync({
        name: values.name,
        tagline: values.tagline,
        address: values.address,
        city: values.city,
        country: values.country,
        timezone: values.timezone,
        working_hours_start: values.working_hours_start,
        working_hours_end: values.working_hours_end,
        weekly_working_hours: weekly,
        visitor_policies: {
          ...(org.data?.visitor_policies ?? {}),
          reminder_offsets_hours: offsets,
          slot_duration_minutes: values.slot_duration,
        },
      })
      toast.success("Workspace settings saved")
    } catch (e) {
      toast.error("Could not save", { description: formatApiError(e) })
    }
  }

  if (org.isLoading) return <Skeleton className="h-96 w-full" />
  if (org.isError || !org.data) return <QueryErrorState message="Couldn't load workspace settings." retry={() => void org.refetch()} />

  const bookingUrl = `${window.location.origin}${org.data.booking_path}`
  const errors = form.formState.errors

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-5 lg:col-span-2">
        {!editable && (
          <div className="rounded-xl border border-border bg-surface-2 px-4 py-3 text-sm text-muted-foreground">
            Only workspace admins can change these settings. You can still review them here.
          </div>
        )}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Identity</CardTitle>
            <CardDescription>Shown to visitors on the booking page, passes and emails.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="o-name" label="Workspace name" required error={errors.name?.message}><Input id="o-name" disabled={!editable} {...form.register("name")} /></Field>
            <Field id="o-tag" label="Tagline"><Input id="o-tag" disabled={!editable} {...form.register("tagline")} /></Field>
            <Field id="o-addr" label="Address" className="sm:col-span-2"><Textarea id="o-addr" rows={2} disabled={!editable} {...form.register("address")} /></Field>
            <Field id="o-city" label="City"><Input id="o-city" disabled={!editable} {...form.register("city")} /></Field>
            <Field id="o-country" label="Country"><Input id="o-country" disabled={!editable} {...form.register("country")} /></Field>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm"><Clock className="size-4 text-primary" /> Hours & scheduling</CardTitle>
            <CardDescription>Working hours bound the public booking slots; the timezone decides what "today" means for your dashboard and reports.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2">
            <Field id="o-tz" label="Timezone (IANA)" required error={errors.timezone?.message} hint="e.g. Asia/Kolkata, Europe/London, America/New_York">
              <Input id="o-tz" list="tz-list" disabled={!editable} {...form.register("timezone")} />
              <datalist id="tz-list">
                {["UTC", "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "Europe/London", "Europe/Berlin", "America/New_York", "America/Los_Angeles", "Australia/Sydney"].map((tz) => (
                  <option key={tz} value={tz} />
                ))}
              </datalist>
            </Field>
            <Field id="o-slot" label="Appointment slot (minutes)" error={errors.slot_duration?.message}>
              <Input id="o-slot" type="number" min={5} max={480} step={5} disabled={!editable} {...form.register("slot_duration")} />
            </Field>
            <Field id="o-start" label="Working hours start" required error={errors.working_hours_start?.message}><Input id="o-start" type="time" disabled={!editable} {...form.register("working_hours_start")} /></Field>
            <Field id="o-end" label="Working hours end" required error={errors.working_hours_end?.message}><Input id="o-end" type="time" disabled={!editable} {...form.register("working_hours_end")} /></Field>
            <Field id="o-rem" label="Visitor reminders (hours before)" error={errors.reminder_offsets?.message} hint="Comma-separated. Reminder emails go out this many hours before the visit." className="sm:col-span-2">
              <Input id="o-rem" placeholder="24, 1" disabled={!editable} {...form.register("reminder_offsets")} />
            </Field>
            <div className="space-y-1.5 sm:col-span-2">
              <div className="text-sm font-medium">Booking windows per weekday</div>
              <p className="text-xs text-muted-foreground">
                Override the daily hours for specific days: close weekends, or add a lunch break by using two windows. Visitors can only book inside these windows.
              </p>
              <WeeklyHoursEditor
                value={weekly}
                onChange={setWeekly}
                disabled={!editable}
                fallback={{ start: form.watch("working_hours_start") || "09:00", end: form.watch("working_hours_end") || "18:00" }}
              />
            </div>
          </CardContent>
        </Card>

        {editable && (
          <div className="flex justify-end">
            <Button type="submit" loading={update.isPending}><Save className="size-4" /> Save changes</Button>
          </div>
        )}
      </form>

      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm"><Link2 className="size-4 text-accent" /> Public booking link</CardTitle>
            <CardDescription>Share this so visitors can pre-book a visit themselves. Bookings arrive as pending approvals.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <code className="block truncate rounded-lg bg-surface-2 px-3 py-2 text-xs">{bookingUrl}</code>
            <div className="flex flex-wrap gap-2">
              <CopyButton value={bookingUrl} label="Copy link" />
              <Button variant="outline" size="sm" asChild>
                <Link to={org.data.booking_path} target="_blank" rel="noreferrer"><ExternalLink className="size-3.5" /> Open</Link>
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">Visitors sign up, book and manage their visits (pass, reschedule, cancel) at <code className="text-foreground">{window.location.origin}/visitor</code>; this link pre-selects your workspace.</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Workspace</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-muted-foreground">Slug</span><code className="text-xs">{org.data.slug}</code></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Created</span><span>{new Date(org.data.created_at).toLocaleDateString()}</span></div>
            <div className="flex justify-between"><span className="text-muted-foreground">Timezone</span><span>{org.data.timezone}</span></div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- buildings */

const buildingSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  address: z.string().trim(),
  floors: z.coerce.number().int().min(1).max(500),
  entry_gates: z.coerce.number().int().min(1).max(100),
  exit_gates: z.coerce.number().int().min(1).max(100),
  has_reception_desk: z.boolean(),
})
type BuildingValues = z.infer<typeof buildingSchema>

function BuildingsTab() {
  const { can } = useAuth()
  const editable = can("manage_buildings")
  const buildings = useBuildings()
  const { create, update, remove } = useBuildingMutations()
  const [editing, setEditing] = useState<Building | "new" | null>(null)
  const [deleting, setDeleting] = useState<Building | null>(null)
  const form = useForm<BuildingValues>({ resolver: zodResolver(buildingSchema) })

  const open = (b: Building | "new") => {
    form.reset(
      b === "new"
        ? { name: "", address: "", floors: 1, entry_gates: 1, exit_gates: 1, has_reception_desk: true }
        : { name: b.name, address: b.address ?? "", floors: b.floors, entry_gates: b.entry_gates, exit_gates: b.exit_gates, has_reception_desk: b.has_reception_desk ?? true },
    )
    setEditing(b)
  }

  const onSubmit = async (values: BuildingValues) => {
    try {
      if (editing === "new") await create.mutateAsync(values)
      else if (editing) await update.mutateAsync({ id: editing.id, data: values })
      toast.success(editing === "new" ? "Building added" : "Building updated")
      setEditing(null)
    } catch (e) {
      toast.error("Could not save building", { description: formatApiError(e) })
    }
  }

  const onDelete = async () => {
    if (!deleting) return
    try {
      await remove.mutateAsync(deleting.id)
      toast.success("Building removed")
      setDeleting(null)
    } catch (e) {
      toast.error("Could not remove building", { description: formatApiError(e) })
    }
  }

  const list = buildings.data ?? []
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Visits are assigned to a building so the gate knows where the visitor is headed.</p>
        {editable && <Button onClick={() => open("new")}><Plus className="size-4" /> Add building</Button>}
      </div>
      {buildings.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : list.length === 0 ? (
        <EmptyState icon={<Building2 className="size-6" />} title="No buildings" description="Add your first building to start assigning visits." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((b) => (
            <div key={b.id} className="card-surface flex flex-col gap-3 p-4">
              <div className="flex items-start gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary"><Building2 className="size-5" /></span>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-semibold">{b.name}</div>
                  <div className="truncate text-xs text-muted-foreground">{b.address || "No address"}</div>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 text-xs">
                <Badge size="sm">{b.floors} floor{b.floors === 1 ? "" : "s"}</Badge>
                <Badge size="sm">{b.entry_gates} entry</Badge>
                <Badge size="sm">{b.exit_gates} exit</Badge>
                {b.has_reception_desk && <Badge tone="primary" size="sm">Reception</Badge>}
              </div>
              {editable && (
                <div className="mt-auto flex gap-1">
                  <Button variant="ghost" size="sm" onClick={() => open(b)}><Pencil className="size-3.5" /> Edit</Button>
                  <Button variant="ghost" size="sm" className="hover:text-danger" disabled={list.length <= 1} onClick={() => setDeleting(b)}><Trash2 className="size-3.5" /> Remove</Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing === "new" ? "Add building" : "Edit building"}</DialogTitle>
            <DialogDescription>Gate counts are informational; floors appear on the public booking form.</DialogDescription>
          </DialogHeader>
          <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="grid gap-4 sm:grid-cols-2">
            <Field id="b-name" label="Name" required error={form.formState.errors.name?.message} className="sm:col-span-2"><Input id="b-name" {...form.register("name")} /></Field>
            <Field id="b-addr" label="Address" className="sm:col-span-2"><Textarea id="b-addr" rows={2} {...form.register("address")} /></Field>
            <Field id="b-floors" label="Floors" error={form.formState.errors.floors?.message}><Input id="b-floors" type="number" min={1} {...form.register("floors")} /></Field>
            <div className="flex items-end gap-3 pb-1">
              <Switch id="b-rec" checked={form.watch("has_reception_desk")} onCheckedChange={(v) => form.setValue("has_reception_desk", v)} />
              <label htmlFor="b-rec" className="text-sm">Has reception desk</label>
            </div>
            <Field id="b-entry" label="Entry gates"><Input id="b-entry" type="number" min={1} {...form.register("entry_gates")} /></Field>
            <Field id="b-exit" label="Exit gates"><Input id="b-exit" type="number" min={1} {...form.register("exit_gates")} /></Field>
            <DialogFooter className="sm:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              <Button type="submit" loading={create.isPending || update.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title={`Remove ${deleting?.name}?`} description="Existing visits keep their history; they will simply show no building." confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={onDelete} />
    </div>
  )
}

/* -------------------------------------------------------------- departments */

function DepartmentsTab() {
  const { can } = useAuth()
  const editable = can("manage_departments")
  const departments = useDepartments()
  const { create, update, remove } = useDepartmentMutations()
  const [editing, setEditing] = useState<Department | "new" | null>(null)
  const [deleting, setDeleting] = useState<Department | null>(null)
  const [name, setName] = useState("")
  const [code, setCode] = useState("")

  const open = (d: Department | "new") => {
    setName(d === "new" ? "" : d.name)
    setCode(d === "new" ? "" : d.code)
    setEditing(d)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    try {
      if (editing === "new") await create.mutateAsync({ name: name.trim(), code: code.trim() })
      else if (editing) await update.mutateAsync({ id: editing.id, data: { name: name.trim(), code: code.trim() } })
      toast.success(editing === "new" ? "Department added" : "Department updated")
      setEditing(null)
    } catch (err) {
      toast.error("Could not save department", { description: formatApiError(err) })
    }
  }

  const onDelete = async () => {
    if (!deleting) return
    try {
      await remove.mutateAsync(deleting.id)
      toast.success("Department removed")
      setDeleting(null)
    } catch (err) {
      toast.error("Could not remove department", { description: formatApiError(err) })
    }
  }

  const list = departments.data ?? []
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Departments group hosts for the public booking form and power the department report.</p>
        {editable && <Button onClick={() => open("new")}><Plus className="size-4" /> Add department</Button>}
      </div>
      {departments.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : list.length === 0 ? (
        <EmptyState icon={<Layers className="size-6" />} title="No departments yet" description="Add departments such as Engineering, HR or Sales." />
      ) : (
        <div className="card-surface divide-y divide-border">
          {list.map((d) => (
            <div key={d.id} className="flex items-center gap-3 px-4 py-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft font-mono text-xs font-bold text-accent">{d.code || d.name.slice(0, 2).toUpperCase()}</span>
              <div className="min-w-0 flex-1">
                <div className="font-medium">{d.name}</div>
                <div className="text-xs text-muted-foreground">{d.member_count ?? 0} member{d.member_count === 1 ? "" : "s"}</div>
              </div>
              {editable && (
                <div className="flex gap-1">
                  <Button variant="ghost" size="iconSm" onClick={() => open(d)} aria-label={`Edit ${d.name}`}><Pencil className="size-4" /></Button>
                  <Button variant="ghost" size="iconSm" className="hover:text-danger" onClick={() => setDeleting(d)} aria-label={`Remove ${d.name}`}><Trash2 className="size-4" /></Button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{editing === "new" ? "Add department" : "Edit department"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-4">
            <Field id="d-name" label="Name" required><Input id="d-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
            <Field id="d-code" label="Short code" hint="Optional, e.g. ENG"><Input id="d-code" value={code} onChange={(e) => setCode(e.target.value)} maxLength={20} /></Field>
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              <Button type="submit" disabled={!name.trim()} loading={create.isPending || update.isPending}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog open={deleting !== null} onOpenChange={(o) => !o && setDeleting(null)} title={`Remove ${deleting?.name}?`} description="Members keep their accounts; they will simply have no department." confirmLabel="Remove" tone="danger" loading={remove.isPending} onConfirm={onDelete} />
    </div>
  )
}

/* ------------------------------------------------------------------ account */

const profileSchema = z.object({ full_name: z.string().trim().min(2, "Full name is required"), phone: z.string().trim() })
const passwordSchema = z
  .object({ current_password: z.string().min(1, "Required"), new_password: z.string().min(8, "At least 8 characters"), confirm: z.string() })
  .refine((d) => d.new_password === d.confirm, { message: "Passwords do not match", path: ["confirm"] })

function AccountTab() {
  const { user, refreshUser } = useAuth()
  const updateProfile = useUpdateProfile()
  const changePassword = useChangePassword()
  const profile = useForm<z.infer<typeof profileSchema>>({ resolver: zodResolver(profileSchema), defaultValues: { full_name: user?.full_name ?? "", phone: user?.phone ?? "" } })
  const pw = useForm<z.infer<typeof passwordSchema>>({ resolver: zodResolver(passwordSchema), defaultValues: { current_password: "", new_password: "", confirm: "" } })

  const saveProfile = async (values: z.infer<typeof profileSchema>) => {
    try {
      await updateProfile.mutateAsync(values)
      await refreshUser()
      toast.success("Profile updated")
    } catch (e) {
      toast.error("Could not update profile", { description: formatApiError(e) })
    }
  }

  const savePassword = async (values: z.infer<typeof passwordSchema>) => {
    try {
      const res = await changePassword.mutateAsync({ current_password: values.current_password, new_password: values.new_password })
      toast.success("Password changed", { description: res.detail })
      pw.reset()
    } catch (e) {
      toast.error("Could not change password", { description: formatApiError(e) })
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm"><UserRound className="size-4 text-primary" /> Profile</CardTitle>
          <CardDescription>{user?.email} · {user?.role ? ROLE_LABELS[user.role] : ""}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={profile.handleSubmit(saveProfile)} noValidate className="space-y-4">
            <Field id="p-name" label="Full name" required error={profile.formState.errors.full_name?.message}><Input id="p-name" {...profile.register("full_name")} /></Field>
            <Field id="p-phone" label="Phone"><Input id="p-phone" {...profile.register("phone")} /></Field>
            <div className="flex justify-end"><Button type="submit" loading={updateProfile.isPending}><Save className="size-4" /> Save</Button></div>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm"><KeyRound className="size-4 text-warning" /> Change password</CardTitle>
          <CardDescription>Other devices keep their session until it expires; sign out there if needed.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={pw.handleSubmit(savePassword)} noValidate className="space-y-4">
            <Field id="pw-cur" label="Current password" required error={pw.formState.errors.current_password?.message}><Input id="pw-cur" type="password" autoComplete="current-password" {...pw.register("current_password")} /></Field>
            <Field id="pw-new" label="New password" required error={pw.formState.errors.new_password?.message} hint="At least 8 characters; avoid common words and your own name."><Input id="pw-new" type="password" autoComplete="new-password" {...pw.register("new_password")} /></Field>
            <Field id="pw-conf" label="Confirm new password" required error={pw.formState.errors.confirm?.message}><Input id="pw-conf" type="password" autoComplete="new-password" {...pw.register("confirm")} /></Field>
            <div className="flex justify-end"><Button type="submit" variant="secondary" loading={changePassword.isPending}>Update password</Button></div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}

/* --------------------------------------------------------------------- page */

export function SettingsPage() {
  const { tab } = useParams<{ tab?: string }>()
  const navigate = useNavigate()
  const active: Tab = (TABS.find((t) => t.value === tab)?.value ?? "workspace") as Tab

  return (
    <div className="space-y-5">
      <PageHeader title="Settings" description="Workspace identity, buildings and rooms, departments, visitor options and your own account." />
      <Tabs value={active} onValueChange={(v) => navigate(`/dashboard/settings/${v}`, { replace: true })}>
        <TabsList className="h-auto flex-wrap justify-start">
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value} className="gap-1.5">
              <t.icon className="size-3.5" /> {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div className="pt-1">
        {active === "workspace" && <WorkspaceTab />}
        {active === "buildings" && <BuildingsTab />}
        {active === "rooms" && <RoomsTab />}
        {active === "departments" && <DepartmentsTab />}
        {active === "visitors" && <CatalogueEditor />}
        {active === "notices" && <NoticesEditor />}
        {active === "account" && <AccountTab />}
      </div>
    </div>
  )
}
