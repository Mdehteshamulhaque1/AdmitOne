import { useCallback, useEffect, useId, useRef, useState } from "react"
import { Camera, CameraOff, RefreshCw, SwitchCamera } from "lucide-react"
import { Button } from "@/components/ui/Button"
import { cn } from "@/lib/utils"

type ScannerModule = typeof import("html5-qrcode")

interface QrScannerProps {
  /** Called once per decoded code; the same value is suppressed for `cooldownMs`. */
  onScan: (payload: string) => void
  paused?: boolean
  cooldownMs?: number
  className?: string
}

interface CameraInfo {
  id: string
  label: string
}

/**
 * Camera viewfinder built on html5-qrcode (loaded lazily so the library is
 * only downloaded on the gate screen).  Decoding runs locally in the browser;
 * the decoded string is handed to the parent, which verifies it with the API.
 */
export function QrScanner({ onScan, paused = false, cooldownMs = 2500, className }: QrScannerProps) {
  const regionId = useId().replace(/[:]/g, "")
  const scannerRef = useRef<InstanceType<ScannerModule["Html5Qrcode"]> | null>(null)
  const moduleRef = useRef<ScannerModule | null>(null)
  const lastRef = useRef<{ value: string; at: number }>({ value: "", at: 0 })
  const [cameras, setCameras] = useState<CameraInfo[]>([])
  const [cameraId, setCameraId] = useState<string | null>(null)
  const [status, setStatus] = useState<"idle" | "starting" | "running" | "error" | "unsupported">("idle")
  const [error, setError] = useState<string>("")
  const onScanRef = useRef(onScan)
  onScanRef.current = onScan

  const stop = useCallback(async () => {
    const scanner = scannerRef.current
    if (!scanner) return
    try {
      if (scanner.isScanning) await scanner.stop()
      scanner.clear()
    } catch {
      /* already stopped */
    }
  }, [])

  const start = useCallback(
    async (preferredId?: string | null) => {
      setStatus("starting")
      setError("")
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          setStatus("unsupported")
          setError("This browser does not support camera access. Use the manual entry below.")
          return
        }
        const mod = moduleRef.current ?? (await import("html5-qrcode"))
        moduleRef.current = mod
        const devices = await mod.Html5Qrcode.getCameras()
        const list = devices.map((d) => ({ id: d.id, label: d.label || `Camera ${d.id.slice(0, 4)}` }))
        setCameras(list)
        if (list.length === 0) {
          setStatus("error")
          setError("No camera was found on this device.")
          return
        }
        const back = list.find((c) => /back|rear|environment/i.test(c.label))
        const chosen = preferredId && list.some((c) => c.id === preferredId) ? preferredId : (back ?? list[0]).id
        setCameraId(chosen)

        await stop()
        const scanner = new mod.Html5Qrcode(regionId, { verbose: false })
        scannerRef.current = scanner
        await scanner.start(
          chosen,
          { fps: 10, qrbox: (w, h) => ({ width: Math.min(w, h) * 0.7, height: Math.min(w, h) * 0.7 }), aspectRatio: 1 },
          (decoded) => {
            const now = Date.now()
            if (decoded === lastRef.current.value && now - lastRef.current.at < cooldownMs) return
            lastRef.current = { value: decoded, at: now }
            onScanRef.current(decoded)
          },
          () => undefined,
        )
        setStatus("running")
      } catch (err) {
        setStatus("error")
        const message = err instanceof Error ? err.message : String(err)
        setError(
          /NotAllowed|Permission/i.test(message)
            ? "Camera permission was denied. Allow camera access in the browser and try again."
            : message || "Could not start the camera.",
        )
      }
    },
    [cooldownMs, regionId, stop],
  )

  useEffect(() => {
    void start()
    return () => {
      void stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const scanner = scannerRef.current
    if (!scanner || status !== "running") return
    try {
      if (paused) scanner.pause(true)
      else scanner.resume()
    } catch {
      /* not scanning */
    }
  }, [paused, status])

  const switchCamera = () => {
    if (cameras.length < 2 || !cameraId) return
    const idx = cameras.findIndex((c) => c.id === cameraId)
    const next = cameras[(idx + 1) % cameras.length]
    void start(next.id)
  }

  return (
    <div className={cn("space-y-3", className)}>
      <div className="sg-scan-frame aspect-square w-full">
        <div id={regionId} className="size-full" />
        {status === "running" && (
          <>
            <div className="pointer-events-none absolute inset-[12%]">
              <span className="sg-scan-corner left-0 top-0 rounded-tl-xl border-b-0 border-r-0" />
              <span className="sg-scan-corner right-0 top-0 rounded-tr-xl border-b-0 border-l-0" />
              <span className="sg-scan-corner bottom-0 left-0 rounded-bl-xl border-r-0 border-t-0" />
              <span className="sg-scan-corner bottom-0 right-0 rounded-br-xl border-l-0 border-t-0" />
            </div>
            {!paused && <span className="sg-scan-line pointer-events-none" />}
            {paused && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/55 text-sm font-medium text-white">
                Scanner paused
              </div>
            )}
          </>
        )}
        {status !== "running" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white/90">
            {status === "starting" ? (
              <>
                <RefreshCw className="size-6 animate-spin" />
                <p className="text-sm">Starting camera…</p>
              </>
            ) : (
              <>
                <CameraOff className="size-7 opacity-80" />
                <p className="max-w-xs text-sm leading-relaxed">{error || "Camera is off."}</p>
                {status !== "unsupported" && (
                  <Button size="sm" variant="glass" className="border-white/30 bg-white/15 text-white hover:bg-white/25" onClick={() => void start(cameraId)}>
                    <Camera className="size-4" /> Retry
                  </Button>
                )}
              </>
            )}
          </div>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span
            className={cn(
              "size-2 rounded-full",
              status === "running" && !paused ? "bg-success animate-pulse" : "bg-muted-foreground/50",
            )}
          />
          {status === "running" ? (paused ? "Paused" : "Live — point at a AdmitOne pass") : "Camera off"}
        </span>
        {cameras.length > 1 && (
          <Button variant="ghost" size="sm" onClick={switchCamera}>
            <SwitchCamera className="size-4" /> Switch camera
          </Button>
        )}
      </div>
    </div>
  )
}
