import { useEffect, useState } from "react"
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"
import { motion } from "framer-motion"
import { CalendarCheck2, Moon, QrCode, ShieldCheck, Sun } from "lucide-react"
import { Background } from "@/components/background"
import { LogoWordmark } from "@/components/logo"
import { AuthPanel, type AuthMode, type AuthRole } from "@/components/auth/AuthPanel"
import { Button } from "@/components/ui/Button"
import { useAuth } from "@/lib/auth"
import { useTheme } from "@/lib/theme"
import { getVisitorToken } from "@/lib/visitor-api"

/**
 * The single entry point for everyone: pick a role (visitor or staff), create
 * an account, sign in. Visitors continue to the booking steps; staff continue
 * to their workspace (or onboarding if they have none yet).
 */
export function WelcomePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { resolved, toggle } = useTheme()
  const { isAuthenticated, loading } = useAuth()
  const [role, setRole] = useState<AuthRole>(params.get("role") === "staff" ? "staff" : "visitor")
  const mode: AuthMode = params.get("mode") === "login" ? "login" : "register"

  useEffect(() => {
    const r = params.get("role")
    if (r === "staff" || r === "visitor") setRole(r)
  }, [params])

  if (!loading && isAuthenticated && role === "staff") return <Navigate to="/dashboard" replace />
  if (role === "visitor" && getVisitorToken() && params.get("switch") !== "1") return <Navigate to="/visitor" replace />

  const onSignedIn = (r: AuthRole) => navigate(r === "visitor" ? "/visitor" : "/dashboard", { replace: true })

  return (
    <div className="min-h-screen">
      <Background />
      <header className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
        <Link to="/" aria-label="AdmitOne home"><LogoWordmark /></Link>
        <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
          {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </Button>
      </header>
      <main className="mx-auto grid max-w-6xl gap-10 px-4 pb-16 pt-4 sm:px-6 lg:grid-cols-[1fr_30rem] lg:items-start lg:pt-10">
        <section className="space-y-6 lg:pt-8">
          <motion.h1 initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            One account.<br /><span className="text-gradient">Whichever side of the gate you're on.</span>
          </motion.h1>
          <p className="max-w-lg text-muted-foreground">
            Visitors create an account, sign in and book a visit in a few guided steps. Staff create an account, sign in and
            approve those requests after checking the details and timing.
          </p>
          <ol className="space-y-3 text-sm">
            {[
              [CalendarCheck2, "Visitor books", "Chooses the organisation, person, date and a free time slot."],
              [ShieldCheck, "Staff approves", "Reviews who is coming, why and when, then approves or declines."],
              [QrCode, "Pass at the gate", "A single-use signed QR pass is issued and scanned on arrival."],
            ].map(([Icon, t, d], i) => {
              const I = Icon as typeof ShieldCheck
              return (
                <li key={i} className="flex items-start gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><I className="size-4" /></span>
                  <span><span className="font-semibold">{t as string}</span><span className="block text-muted-foreground">{d as string}</span></span>
                </li>
              )
            })}
          </ol>
        </section>
        <AuthPanel role={role} onRoleChange={(r) => { setRole(r); navigate(`/login?role=${r}`, { replace: true }) }} initialMode={mode} onSignedIn={onSignedIn} />
      </main>
    </div>
  )
}
