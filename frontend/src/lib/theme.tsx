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
  if (meta) meta.content = resolved === "dark" ? "#0f131a" : "#F5F7FA"
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
    series: ["#2f6bff", "#d97706", "#475467", "#be185d", "#65a30d"],
    grid: "rgba(16, 24, 40, 0.08)",
    tick: "#667085",
    tooltipBg: "#ffffff",
  },
  dark: {
    series: ["#5b8cff", "#fbbf24", "#98a2b3", "#f472b6", "#a3e635"],
    grid: "rgba(152, 162, 179, 0.12)",
    tick: "#98a2b3",
    tooltipBg: "#171c25",
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
    APPROVED: "#2f6bff",
    REJECTED: "#dc2626",
    CHECKED_IN: "#16a34a",
    CHECKED_OUT: "#64748b",
    CANCELLED: "#9333ea",
    ARCHIVED: "#94a3b8",
  },
  dark: {
    PENDING: "#fbbf24",
    APPROVED: "#5b8cff",
    REJECTED: "#f87171",
    CHECKED_IN: "#4ade80",
    CHECKED_OUT: "#94a3b8",
    CANCELLED: "#d8b4fe",
    ARCHIVED: "#64748b",
  },
}
