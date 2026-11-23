import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom"
import { ArrowLeft, CheckCheck, Moon, ScanLine, ShieldCheck, Sun, UserPlus } from "lucide-react"
import { AuthPanel } from "@/components/auth/AuthPanel"
import { LogoWordmark } from "@/components/logo"
import { Button } from "@/components/ui/Button"
import { PageLoader } from "@/components/widgets/PageLoader"
import { useAuth } from "@/lib/auth"
import { useTheme } from "@/lib/theme"

/** The admin portal's front door: staff sign-in (and staff sign-up) only. */
export function AdminLoginPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const { resolved, toggle } = useTheme()
  const { isAuthenticated, loading } = useAuth()

  if (loading) return <PageLoader />
  if (isAuthenticated) return <Navigate to="/dashboard" replace />

  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
      <aside className="hidden flex-col justify-between bg-nav p-10 text-nav-foreground lg:flex">
        <div>
          <Link to="/" className="inline-flex items-center gap-2 text-sm text-nav-muted hover:text-nav-foreground">
            <ArrowLeft className="size-4" /> Back to start
          </Link>
          <div className="mt-10 [&_*]:text-nav-foreground">
            <LogoWordmark />
          </div>
          <h1 className="mt-8 text-2xl font-semibold leading-snug tracking-tight">Admin console</h1>
          <p className="mt-2 text-sm text-nav-muted">For admins, reception and security staff of your organisation.</p>
          <ul className="mt-8 space-y-4 text-sm">
            {[
              [CheckCheck, "Approve or decline visit requests"],
              [UserPlus, "Register walk-in visitors at the desk"],
              [ScanLine, "Scan passes and see who's inside"],
              [ShieldCheck, "Every action is recorded in the audit log"],
            ].map(([Icon, text]) => {
              const I = Icon as typeof ShieldCheck
              return (
                <li key={text as string} className="flex items-center gap-3">
                  <span className="flex size-8 items-center justify-center rounded-lg bg-nav-active text-nav-accent"><I className="size-4" /></span>
                  {text as string}
                </li>
              )
            })}
          </ul>
        </div>
        <p className="text-xs text-nav-muted">Visiting someone? <Link to="/visitor" className="font-medium text-nav-accent hover:underline">Go to the visitor portal</Link>.</p>
      </aside>

      <main className="flex flex-col bg-background">
        <header className="flex h-16 items-center justify-between px-4 sm:px-8">
          <Link to="/" className="lg:hidden" aria-label="AdmitOne start page"><LogoWordmark /></Link>
          <span className="hidden lg:block" />
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
            {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
        </header>
        <div className="flex flex-1 items-start justify-center px-4 pb-16 pt-4 sm:px-8 lg:items-center lg:pt-0">
          <div className="w-full max-w-md">
            <AuthPanel
              role="staff"
              portal
              initialMode={params.get("mode") === "register" ? "register" : "login"}
              onSignedIn={() => navigate("/dashboard", { replace: true })}
            />
            <p className="mt-5 text-center text-sm text-muted-foreground lg:hidden">
              Visiting someone? <Link to="/visitor" className="font-medium text-primary hover:underline">Go to the visitor portal</Link>.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
