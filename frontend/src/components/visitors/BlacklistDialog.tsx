import { useState } from "react"
import { toast } from "sonner"
import { Ban } from "lucide-react"
import { Button } from "@/components/ui/Button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog"
import { Textarea } from "@/components/ui/Input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/Select"
import { Field } from "@/components/widgets/Field"
import { useBlacklistVisitor } from "@/lib/queries"
import { BLACKLIST_REASONS, formatApiError, type BlacklistReason } from "@/lib/types"

export function BlacklistDialog({
  visitor,
  open,
  onOpenChange,
}: {
  visitor: { id: number; full_name: string } | null
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [reason, setReason] = useState<BlacklistReason | "">("")
  const [comment, setComment] = useState("")
  const blacklist = useBlacklistVisitor()

  const submit = async () => {
    if (!visitor || !reason) return
    try {
      const res = await blacklist.mutateAsync({ id: visitor.id, reason, comment })
      toast.success("Visitor blacklisted", { description: res.detail })
      setReason("")
      setComment("")
      onOpenChange(false)
    } catch (e) {
      toast.error("Could not blacklist", { description: formatApiError(e) })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="size-5 text-danger" /> Blacklist {visitor?.full_name}
          </DialogTitle>
          <DialogDescription>
            A blacklisted visitor cannot be approved or checked in at any gate until an admin lifts the ban.
            This action is recorded in the audit log.
          </DialogDescription>
        </DialogHeader>
        <Field id="bl-reason" label="Reason" required>
          <Select value={reason} onValueChange={(v) => setReason(v as BlacklistReason)}>
            <SelectTrigger id="bl-reason">
              <SelectValue placeholder="Choose a reason" />
            </SelectTrigger>
            <SelectContent>
              {BLACKLIST_REASONS.map((r) => (
                <SelectItem key={r.value} value={r.value}>
                  {r.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field id="bl-comment" label="Notes" hint="Optional context for other staff (max 1000 characters).">
          <Textarea
            id="bl-comment"
            rows={3}
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="What happened?"
          />
        </Field>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="danger" disabled={!reason} loading={blacklist.isPending} onClick={submit}>
            <Ban className="size-4" /> Blacklist visitor
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
