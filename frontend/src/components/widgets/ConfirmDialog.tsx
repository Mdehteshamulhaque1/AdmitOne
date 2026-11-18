import { useState, type ReactNode } from "react"
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
import { Label } from "@/components/ui/Label"

interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  tone?: "default" | "danger"
  /** When set, shows an optional textarea whose value is passed to onConfirm. */
  reasonLabel?: string
  reasonPlaceholder?: string
  reasonMaxLength?: number
  loading?: boolean
  onConfirm: (reason: string) => void | Promise<void>
  children?: ReactNode
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  reasonLabel,
  reasonPlaceholder,
  reasonMaxLength = 300,
  loading,
  onConfirm,
  children,
}: ConfirmDialogProps) {
  const [reason, setReason] = useState("")
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setReason("")
        onOpenChange(o)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        {children}
        {reasonLabel && (
          <div className="space-y-1.5">
            <Label htmlFor="confirm-reason">{reasonLabel}</Label>
            <Textarea
              id="confirm-reason"
              rows={3}
              value={reason}
              maxLength={reasonMaxLength}
              onChange={(e) => setReason(e.target.value)}
              placeholder={reasonPlaceholder}
            />
            <p className="text-right text-[11px] text-muted-foreground">
              {reason.length}/{reasonMaxLength}
            </p>
          </div>
        )}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            loading={loading}
            onClick={() => void onConfirm(reason.trim())}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
