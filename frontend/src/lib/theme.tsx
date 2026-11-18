import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

export type ThemePreference = "system" | "light" | "dark"
export type ResolvedTheme = "light" | "dark"

const STORAGE_KEY = "sg_theme"

interface ThemeContextValue {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (pref: ThemePreference) => void
  toggle: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readPreference(): ThemePreference {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === "light" || raw === "dark" || raw === "system") return raw
  } catch {
    /* storage unavailable (private mode) */
  }
  return "system"
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined" || !window.matchMedia) return "light"
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

function apply(resolved: ResolvedTheme) {
  const root = document.documentElement
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) meta.content = resolved === "dark" ? "#0A0E1F" : "#F5F6FB"
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference)
  const [system, setSystem] = useState<ResolvedTheme>(systemTheme)

  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const onChange = () => setSystem(mq.matches ? "dark" : "light")
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [])

  const resolved: ResolvedTheme = preference === "system" ? system : preference

  useEffect(() => {
    apply(resolved)
  }, [resolved])

  const setPreference = useCallback((pref: ThemePreference) => {
    setPreferenceState(pref)
    try {
      localStorage.setItem(STORAGE_KEY, pref)
    } catch {
      /* ignore */
    }
  }, [])

  const toggle = useCallback(() => {
    setPreference(resolved === "dark" ? "light" : "dark")
  }, [resolved, setPreference])

  const value = useMemo(
    () => ({ preference, resolved, setPreference, toggle }),
    [preference, resolved, setPreference, toggle],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider")
  return ctx
}

export interface ChartPalette {
  series: [string, string, string, string, string]
  grid: string
  tick: string
  tooltipBg: string
}

const PALETTES: Record<ResolvedTheme, ChartPalette> = {
  light: {
    series: ["#4f46e5", "#7c3aed", "#d97706", "#0891b2", "#dc2626"],
    grid: "rgba(30, 27, 75, 0.08)",
    tick: "#6b7194",
    tooltipBg: "#ffffff",
  },
  dark: {
    series: ["#818cf8", "#a78bfa", "#fbbf24", "#22d3ee", "#f87171"],
    grid: "rgba(152, 162, 195, 0.12)",
    tick: "#8f98ba",
    tooltipBg: "#131b35",
  },
}

/** Chart colours that match the active theme (Recharts needs real strings). */
export function useChartPalette(): ChartPalette {
  const { resolved } = useTheme()
  return PALETTES[resolved]
}

export const STATUS_COLORS: Record<ResolvedTheme, Record<string, string>> = {
  light: {
    PENDING: "#d97706",
    APPROVED: "#4f46e5",
    REJECTED: "#dc2626",
    CHECKED_IN: "#16a34a",
    CHECKED_OUT: "#64748b",
    CANCELLED: "#9333ea",
    ARCHIVED: "#94a3b8",
  },
  dark: {
    PENDING: "#fbbf24",
    APPROVED: "#818cf8",
    REJECTED: "#f87171",
    CHECKED_IN: "#4ade80",
    CHECKED_OUT: "#94a3b8",
    CANCELLED: "#c084fc",
    ARCHIVED: "#64748b",
  },
}
