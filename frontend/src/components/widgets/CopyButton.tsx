import { useState } from "react"
import { Check, Copy } from "lucide-react"
import { Button, type ButtonProps } from "@/components/ui/Button"

export function CopyButton({ value, label = "Copy", ...props }: { value: string; label?: string } & Omit<ButtonProps, "onClick" | "children">) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      /* clipboard unavailable: nothing else to do */
    }
  }
  return (
    <Button type="button" variant="outline" size="sm" onClick={copy} {...props}>
      {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
      {copied ? "Copied" : label}
    </Button>
  )
}
