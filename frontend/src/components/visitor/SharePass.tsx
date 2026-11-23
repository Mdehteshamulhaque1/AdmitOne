import { useRef } from "react"
import { QRCodeCanvas } from "qrcode.react"
import { Download, MessageCircle } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/Button"
import { formatDate } from "@/lib/utils"
import type { VisitorVisit } from "@/lib/visitor-api"

/** The pass as a WhatsApp-ready message (the QR image travels separately). */
export function passMessage(visit: VisitorVisit) {
  return [
    `My visitor pass for ${visit.organization_name}`,
    `Date: ${formatDate(visit.visit_date)}, ${visit.expected_arrival}-${visit.expected_exit}`,
    visit.host_name ? `Meeting: ${visit.host_name}` : "",
    visit.room_label ? `Room: ${visit.room_label}${visit.floor_name ? `, ${visit.floor_name}` : ""}` : "",
    `Reference: ${visit.reference.slice(0, 8).toUpperCase()}`,
    "Show the QR pass and the original ID at the gate.",
    `${window.location.origin}/visitor?view=visits`,
  ]
    .filter(Boolean)
    .join("\n")
}

/**
 * "Send to WhatsApp" and "Save QR image" for an approved pass. On phones the
 * share sheet sends the QR picture itself to WhatsApp; elsewhere WhatsApp
 * opens with the details typed in, and the image can be saved and attached.
 */
export function SharePass({ visit, payload }: { visit: VisitorVisit; payload: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const pngBlob = () =>
    new Promise<Blob>((resolve, reject) => {
      const canvas = canvasRef.current
      if (!canvas) return reject(new Error("no canvas"))
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("encode"))), "image/png")
    })

  const fileName = `admitone-pass-${visit.reference.slice(0, 8)}.png`

  const sendToWhatsApp = async () => {
    const text = passMessage(visit)
    // Phones: the share sheet sends the QR picture itself. Desktops (where the
    // OS share panel may not list WhatsApp) go straight to WhatsApp with text.
    const touch = window.matchMedia("(pointer: coarse)").matches
    try {
      const file = new File([await pngBlob()], fileName, { type: "image/png" })
      if (touch && navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], text, title: "AdmitOne visitor pass" })
        return
      }
    } catch (e) {
      if ((e as Error).name === "AbortError") return // the visitor closed the share sheet
    }
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank", "noopener,noreferrer")
  }

  const saveImage = async () => {
    try {
      const url = URL.createObjectURL(await pngBlob())
      const a = document.createElement("a")
      a.href = url
      a.download = fileName
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      toast.error("The QR image couldn't be saved. Take a screenshot instead.")
    }
  }

  return (
    <div className="grid w-full grid-cols-2 gap-2">
      <QRCodeCanvas ref={canvasRef} value={payload} size={640} marginSize={4} fgColor="#0f172a" level="M" className="hidden" aria-hidden="true" />
      <Button type="button" className="bg-[#1f9d55] text-white hover:bg-[#188a49]" onClick={() => void sendToWhatsApp()}>
        <MessageCircle className="size-4" /> Send to WhatsApp
      </Button>
      <Button type="button" variant="outline" onClick={() => void saveImage()}>
        <Download className="size-4" /> Save QR image
      </Button>
    </div>
  )
}
