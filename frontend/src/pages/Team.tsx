import { useState } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Eye, EyeOff, KeyRound, Lock, Pencil, ShieldCheck, UserMinus, UserPlus, UsersRound } from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/Dialog"
import { EmptyState } from "@/components/ui/EmptyState"
import { Input } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Skeleton } from "@/components/ui/Skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/Table"
import { ConfirmDialog } from "@/components/widgets/ConfirmDialog"
import { Field } from "@/components/widgets/Field"
import { PageHeader } from "@/components/widgets/PageHeader"
import { QueryErrorState } from "@/components/widgets/QueryErrorState"
import { SearchInput } from "@/components/widgets/SearchInput"
import { useAuth } from "@/lib/auth"
import { useBuildings, useDepartments, useTeam, useTeamMutations } from "@/lib/queries"
import { ROLE_DESCRIPTIONS, ROLE_LABELS, formatApiError, type Role, type TeamMember } from "@/lib/types"
import { formatRelative } from "@/lib/utils"

const ROLES: Role[] = ["ADMIN", "RECEPTIONIST", "SECURITY"]
const ROLE_TONE: Record<Role, "primary" | "info" | "warning"> = { ADMIN: "primary", RECEPTIONIST: "info", SECURITY: "warning" }

const memberSchema = z.object({
  full_name: z.string().trim().min(2, "Full name is required"),
  email: z.string().trim().email("Enter a valid email"),
  phone: z.string().trim(),
  role: z.enum(["ADMIN", "RECEPTIONIST", "SECURITY"]),
  password: z.string().min(8, "At least 8 characters"),
  designation: z.string().trim(),
  employee_id: z.string().trim(),
  department: z.string(),
  building: z.string(),
})
type MemberValues = z.infer<typeof memberSchema>

const editSchema = memberSchema.omit({ email: true, password: true }).extend({
  password: z.string().refine((v) => v === "" || v.length >= 8, "At least 8 characters"),
})
type EditValues = z.infer<typeof editSchema>

function RoleSelect({ value, onChange, id }: { value: string; onChange: (v: Role) => void; id?: string }) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Role)}>
      <SelectTrigger id={id}><SelectValue placeholder="Choose a role" /></SelectTrigger>
      <SelectContent>
        {ROLES.map((r) => (
          <SelectItem key={r} value={r}>
            <span className="font-medium">{ROLE_LABELS[r]}</span>
            <span className="block text-xs text-muted-foreground">{ROLE_DESCRIPTIONS[r]}</span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function OrgSelects({ form, departments, buildings }: {
  form: { watch: (k: "department" | "building") => string; setValue: (k: "department" | "building", v: string) => void }
  departments: { id: number; name: string }[]
  buildings: { id: number; name: string }[]
}) {
  return (
    <>
      <Field id="m-dept" label="Department">
        <Select value={form.watch("department")} onValueChange={(v) => form.setValue("department", v)}>
          <SelectTrigger id="m-dept"><SelectValue placeholder="None" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">No department</SelectItem>
            {departments.map((d) => <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </Field>
      <Field id="m-bld" label="Building">
        <Select value={form.watch("building")} onValueChange={(v) => form.setValue("building", v)}>
          <SelectTrigger id="m-bld"><SelectValue placeholder="None" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">Any building</SelectItem>
            {buildings.map((b) => <SelectItem key={b.id} value={String(b.id)}>{b.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </Field>
    </>
  )
}

/** Common designations at a training institute (suggestions; any text is allowed). */
const DESIGNATIONS = [
  "Centre Incharge", "Branch Manager", "HR Manager", "HR Executive", "Trainer", "Python Trainer",
  "Data Science Trainer", "Student Counsellor", "Placement Officer", "Placement Coordinator",
  "Front Desk Executive", "Accounts Executive", "Lab Assistant", "Security Officer",
]

function DesignationOptions() {
  return (
    <datalist id="designation-options">
      {DESIGNATIONS.map((d) => <option key={d} value={d} />)}
    </datalist>
  )
}

export function TeamPage() {
  const { user } = useAuth()
  const [search, setSearch] = useState("")
  const { data: members, isLoading, isError, refetch } = useTeam(search)
  const departments = useDepartments()
  const buildings = useBuildings()
  const { create, update, deactivate } = useTeamMutations()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<TeamMember | null>(null)
  const [removing, setRemoving] = useState<TeamMember | null>(null)
  const [showPw, setShowPw] = useState(false)

  const addForm = useForm<MemberValues>({
    resolver: zodResolver(memberSchema),
    defaultValues: { full_name: "", email: "", phone: "", role: "RECEPTIONIST", password: "", designation: "", employee_id: "", department: "none", building: "none" },
  })
  const editForm = useForm<EditValues>({ resolver: zodResolver(editSchema) })

  const openEdit = (m: TeamMember) => {
    editForm.reset({
      full_name: m.full_name,
      phone: m.phone ?? "",
      role: m.role,
      password: "",
      designation: m.employee?.designation ?? "",
      employee_id: m.employee?.employee_id ?? "",
      department: m.employee?.department ? String(m.employee.department) : "none",
      building: m.employee?.building ? String(m.employee.building) : "none",
    })
    setShowPw(false)
    setEditing(m)
  }

  const onAdd = async (values: MemberValues) => {
    try {
      await create.mutateAsync({
        ...values,
        department: values.department === "none" ? null : Number(values.department),
        building: values.building === "none" ? null : Number(values.building),
      })
      toast.success("Member added", { description: `${values.full_name} can sign in with the password you set.` })
      addForm.reset()
      setAdding(false)
    } catch (e) {
      toast.error("Could not add member", { description: formatApiError(e) })
    }
  }

  const onEdit = async (values: EditValues) => {
    if (!editing) return
    try {
      await update.mutateAsync({
        id: editing.id,
        data: {
          full_name: values.full_name,
          phone: values.phone,
          role: values.role,
          designation: values.designation,
          employee_id: values.employee_id || undefined,
          department: values.department === "none" ? null : Number(values.department),
          building: values.building === "none" ? null : Number(values.building),
          ...(values.password ? { password: values.password } : {}),
        },
      })
      toast.success("Member updated")
      setEditing(null)
    } catch (e) {
      toast.error("Could not update member", { description: formatApiError(e) })
    }
  }

  const toggleActive = async (m: TeamMember) => {
    try {
      if (m.is_active) {
        await deactivate.mutateAsync(m.id)
        toast.success("Member deactivated", { description: `${m.full_name} can no longer sign in.` })
      } else {
        await update.mutateAsync({ id: m.id, data: { is_active: true } })
        toast.success("Member reactivated")
      }
      setRemoving(null)
    } catch (e) {
      toast.error("Action failed", { description: formatApiError(e) })
    }
  }

  const list = members ?? []
  const admins = list.filter((m) => m.role === "ADMIN" && m.is_active).length

  return (
    <div className="space-y-5">
      <DesignationOptions />
      <PageHeader
        title="Team"
        description="Everyone who can sign in to this workspace. Roles decide what each person can do; the server enforces them on every request."
        actions={
          <Button onClick={() => setAdding(true)}>
            <UserPlus className="size-4" /> Add member
          </Button>
        }
      />
      {isError && <QueryErrorState message="Couldn't load the team." retry={() => void refetch()} />}

      <div className="grid gap-3 sm:grid-cols-3">
        {ROLES.map((r) => (
          <div key={r} className="card-surface flex items-start gap-3 p-4">
            <Badge tone={ROLE_TONE[r]}>{ROLE_LABELS[r]}</Badge>
            <div className="min-w-0 text-xs text-muted-foreground">
              <div className="text-base font-bold text-foreground">{list.filter((m) => m.role === r && m.is_active).length}</div>
              {ROLE_DESCRIPTIONS[r]}
            </div>
          </div>
        ))}
      </div>

      <SearchInput value={search} onChange={setSearch} placeholder="Search by name, email, designation or employee ID…" className="w-full sm:w-96" />

      <div className="card-surface overflow-hidden">
        {isLoading ? (
          <div className="space-y-3 p-5">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
        ) : list.length === 0 ? (
          <div className="p-5"><EmptyState icon={<UsersRound className="size-6" />} title="No members found" description="Add colleagues so they can approve visits, run reception or staff the gate." /></div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Member</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Department</TableHead>
                <TableHead>Employee ID</TableHead>
                <TableHead>Last sign-in</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right"><span className="sr-only">Actions</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((m) => {
                const isSelf = m.id === user?.id
                const lastAdmin = m.role === "ADMIN" && m.is_active && admins <= 1
                return (
                  <TableRow key={m.id} className={m.is_active ? "" : "opacity-60"}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <Avatar name={m.full_name} />
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 font-medium">
                            {m.full_name}
                            {isSelf && <Badge size="sm">You</Badge>}
                          </div>
                          <div className="truncate text-xs text-muted-foreground">{m.email}{m.employee?.designation ? ` · ${m.employee.designation}` : ""}</div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell><Badge tone={ROLE_TONE[m.role]}>{ROLE_LABELS[m.role]}</Badge></TableCell>
                    <TableCell className="text-muted-foreground">{m.employee?.department_name || "—"}</TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">{m.employee?.employee_id || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{m.last_login ? formatRelative(m.last_login) : "Never"}</TableCell>
                    <TableCell>
                      {m.is_locked ? <Badge tone="danger" dot><Lock className="size-3" /> Locked</Badge> : m.is_active ? <Badge tone="success" dot>Active</Badge> : <Badge dot>Deactivated</Badge>}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button variant="ghost" size="iconSm" onClick={() => openEdit(m)} aria-label={`Edit ${m.full_name}`}><Pencil className="size-4" /></Button>
                        {!isSelf && (
                          <Button
                            variant="ghost"
                            size="iconSm"
                            className={m.is_active ? "hover:text-danger" : "hover:text-success"}
                            disabled={lastAdmin}
                            title={lastAdmin ? "The last active admin cannot be deactivated" : m.is_active ? "Deactivate" : "Reactivate"}
                            onClick={() => (m.is_active ? setRemoving(m) : void toggleActive(m))}
                            aria-label={m.is_active ? `Deactivate ${m.full_name}` : `Reactivate ${m.full_name}`}
                          >
                            {m.is_active ? <UserMinus className="size-4" /> : <ShieldCheck className="size-4" />}
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Add member */}
      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add a team member</DialogTitle>
            <DialogDescription>Set an initial password and share it securely; they can change it from their account page.</DialogDescription>
          </DialogHeader>
          <form onSubmit={addForm.handleSubmit(onAdd)} noValidate className="grid gap-4 sm:grid-cols-2">
            <Field id="m-name" label="Full name" required error={addForm.formState.errors.full_name?.message}><Input id="m-name" {...addForm.register("full_name")} /></Field>
            <Field id="m-email" label="Work email" required error={addForm.formState.errors.email?.message}><Input id="m-email" type="email" autoComplete="off" {...addForm.register("email")} /></Field>
            <Field id="m-role" label="Role" required><RoleSelect id="m-role" value={addForm.watch("role")} onChange={(v) => addForm.setValue("role", v)} /></Field>
            <Field id="m-pw" label="Initial password" required error={addForm.formState.errors.password?.message} hint="At least 8 characters, not too common.">
              <div className="relative">
                <Input id="m-pw" type={showPw ? "text" : "password"} autoComplete="new-password" className="pr-10" {...addForm.register("password")} />
                <button type="button" onClick={() => setShowPw((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-label="Toggle password">
                  {showPw ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </Field>
            <Field id="m-phone" label="Phone"><Input id="m-phone" {...addForm.register("phone")} /></Field>
            <Field id="m-desig" label="Designation"><Input id="m-desig" list="designation-options" placeholder="e.g. Trainer, Counsellor, HR Manager" {...addForm.register("designation")} /></Field>
            <Field id="m-eid" label="Employee ID" hint="Leave blank to generate one."><Input id="m-eid" {...addForm.register("employee_id")} /></Field>
            <OrgSelects form={addForm} departments={departments.data ?? []} buildings={buildings.data ?? []} />
            <DialogFooter className="sm:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
              <Button type="submit" loading={create.isPending}><UserPlus className="size-4" /> Add member</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Edit member */}
      <Dialog open={editing !== null} onOpenChange={(o) => !o && setEditing(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit {editing?.full_name}</DialogTitle>
            <DialogDescription>{editing?.email}</DialogDescription>
          </DialogHeader>
          <form onSubmit={editForm.handleSubmit(onEdit)} noValidate className="grid gap-4 sm:grid-cols-2">
            <Field id="e-name" label="Full name" required error={editForm.formState.errors.full_name?.message}><Input id="e-name" {...editForm.register("full_name")} /></Field>
            <Field id="e-phone" label="Phone"><Input id="e-phone" {...editForm.register("phone")} /></Field>
            <Field id="e-role" label="Role" hint={editing?.id === user?.id ? "You cannot change your own role." : undefined}>
              <div className={editing?.id === user?.id ? "pointer-events-none opacity-60" : ""}>
                <RoleSelect id="e-role" value={editForm.watch("role")} onChange={(v) => editForm.setValue("role", v)} />
              </div>
            </Field>
            <Field id="e-desig" label="Designation"><Input id="e-desig" list="designation-options" {...editForm.register("designation")} /></Field>
            <Field id="e-eid" label="Employee ID"><Input id="e-eid" {...editForm.register("employee_id")} /></Field>
            <Field id="e-pw" label="Reset password" error={editForm.formState.errors.password?.message} hint="Leave blank to keep the current password.">
              <div className="relative">
                <Input id="e-pw" type={showPw ? "text" : "password"} autoComplete="new-password" className="pr-10" {...editForm.register("password")} />
                <button type="button" onClick={() => setShowPw((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-label="Toggle password">
                  {showPw ? <EyeOff className="size-4" /> : <KeyRound className="size-4" />}
                </button>
              </div>
            </Field>
            <OrgSelects form={editForm} departments={departments.data ?? []} buildings={buildings.data ?? []} />
            <DialogFooter className="sm:col-span-2">
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              <Button type="submit" loading={update.isPending}>Save changes</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Deactivate ${removing?.full_name}?`}
        description="They will be signed out and unable to log in. Their history, approvals and audit entries are kept. You can reactivate them later."
        confirmLabel="Deactivate"
        tone="danger"
        loading={deactivate.isPending}
        onConfirm={() => { if (removing) void toggleActive(removing) }}
      />
    </div>
  )
}
