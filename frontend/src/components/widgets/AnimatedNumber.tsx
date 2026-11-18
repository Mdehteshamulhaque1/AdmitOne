import { useEffect, useRef, useState } from "react"
import { useInView, useReducedMotion } from "framer-motion"

interface AnimatedNumberProps {
  value: number
  duration?: number
  className?: string
  inView?: boolean
}

export function AnimatedNumber({
  value,
  duration = 700,
  className,
  inView = false,
}: AnimatedNumberProps) {
  const ref = useRef<HTMLSpanElement>(null)
  const [display, setDisplay] = useState(0)
  const prev = useRef(0)
  const raf = useRef<number | null>(null)
  const isInView = useInView(ref, { once: true, margin: "-60px" })
  const reduce = useReducedMotion()

  const ready = !inView || isInView

  useEffect(() => {
    if (!ready) return
    if (reduce) {
      setDisplay(value)
      prev.current = value
      return
    }
    const from = prev.current
    const to = value
    if (from === to) return
    const start = performance.now()
    const step = (now: number) => {
      const p = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - p, 3)
      setDisplay(Math.round(from + (to - from) * eased))
      if (p < 1) raf.current = requestAnimationFrame(step)
      else prev.current = to
    }
    raf.current = requestAnimationFrame(step)
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current)
    }
  }, [ready, value, duration, reduce])

  return (
    <span ref={ref} className={className}>
      {display.toLocaleString()}
    </span>
  )
}