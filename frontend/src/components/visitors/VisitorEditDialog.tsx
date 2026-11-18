import { useEffect } from "react"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { toast } from "sonner"
import { Button } from "@/components/ui/Button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog"
import { Input, Textarea } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Field } from "@/components/widgets/Field"
import { useUpdateVisitor } from "@/lib/queries"
import { DOCUMENT_TYPES, VEHICLE_TYPES, formatApiError, type Visitor } from "@/lib/types"

const schema = z.object({
  full_name: z.string().trim().min(2, "Full name is required"),
  phone: z.string().trim().min(7, "Enter a valid phone number"),
  email: z.string().trim().email("Enter a valid email").or(z.literal("")),
  company: z.string().trim(),
  designation: z.string().trim(),
  document_type: z.string(),
  document_number: z.string().trim(),
  vehicle_type: z.string(),
  vehicle_number: z.string().trim(),
  emergency_contact: z.string().trim(),
  emergency_phone: z.string().trim(),
  special_notes: z.string().trim(),
})
type Values = z.infer<typeof schema>

function toValues(v: Visitor): Values {
  return {
    full_name: v.full_name,
    phone: v.phone,
    email: v.email ?? "",
    company: v.company ?? "",
    designation: v.designation ?? "",
    document_type: v.document_type || "none",
    document_number: v.document_number ?? "",
    vehicle_type: v.vehicle_type || "none",
    vehicle_number: v.vehicle_number ?? "",
    emergency_contact: v.emergency_contact ?? "",
    emergency_phone: v.emergency_phone ?? "",
    special_notes: v.special_notes ?? "",
  }
}

export function VisitorEditDialog({
  visitor,
  open,
  onOpenChange,
  onSaved,
}: {
  visitor: Visitor | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onSaved?: (visitor: Visitor) => void
}) {
  const update = useUpdateVisitor()
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: visitor ? toValues(visitor) : undefined })
  const { register, handleSubmit, reset, watch, setValue, formState } = form

  useEffect(() => {
    if (visitor && open) reset(toValues(visitor))
  }, [visitor, open, reset])

  const onSubmit = async (values: Values) => {
    if (!visitor) return
    try {
      const saved = await update.mutateAsync({
        id: visitor.id,
        data: {
          ...values,
          document_type: values.document_type === "none" ? "" : values.document_type,
          vehicle_type: values.vehicle_type === "none" ? "" : values.vehicle_type,
        },
      })
      toast.success("Visitor updated")
      onSaved?.(saved)
      onOpenChange(false)
    } catch (e) {
      toast.error("Could not save", { description: formatApiError(e) })
    }
  }

  const err = (k: keyof Values) => formState.errors[k]?.message

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit visitor</DialogTitle>
          <DialogDescription>Changes apply to every future visit for this person.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="grid gap-4 sm:grid-cols-2">
          <Field id="ev-name" label="Full name" required error={err("full_name")}>
            <Input id="ev-name" {...register("full_name")} />
          </Field>
          <Field id="ev-phone" label="Phone" required error={err("phone")}>
            <Input id="ev-phone" {...register("phone")} />
          </Field>
          <Field id="ev-email" label="Email" error={err("email")}>
            <Input id="ev-email" type="email" {...register("email")} />
          </Field>
          <Field id="ev-company" label="Company">
            <Input id="ev-company" {...register("company")} />
          </Field>
          <Field id="ev-designation" label="Designation">
            <Input id="ev-designation" {...register("designation")} />
          </Field>
          <Field id="ev-doc" label="ID document">
            <Select value={watch("document_type")} onValueChange={(v) => setValue("document_type", v)}>
              <SelectTrigger id="ev-doc"><SelectValue placeholder="Select" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Not recorded</SelectItem>
                {DOCUMENT_TYPES.map((d) => (
                  <SelectItem key={d.value} value={d.value}>{d.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field id="ev-docno" label="Document number">
            <Input id="ev-docno" {...register("document_number")} />
          </Field>
          <Field id="ev-vehicle" label="Vehicle">
            <Select value={watch("vehicle_type")} onValueChange={(v) => setValue("vehicle_type", v)}>
              <SelectTrigger id="ev-vehicle"><SelectValue /></SelectTrigger>
              <SelectContent>
                {VEHICLE_TYPES.map((v) => (
                  <SelectItem key={v.value} value={v.value}>{v.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {watch("vehicle_type") !== "none" && (
            <Field id="ev-vehno" label="Vehicle number">
              <Input id="ev-vehno" {...register("vehicle_number")} />
            </Field>
          )}
          <Field id="ev-ec" label="Emergency contact">
            <Input id="ev-ec" {...register("emergency_contact")} />
          </Field>
          <Field id="ev-ep" label="Emergency phone">
            <Input id="ev-ep" {...register("emergency_phone")} />
          </Field>
          <Field id="ev-notes" label="Special notes" className="sm:col-span-2">
            <Textarea id="ev-notes" rows={3} {...register("special_notes")} />
          </Field>
          <DialogFooter className="sm:col-span-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={update.isPending}>
              Save changes
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
