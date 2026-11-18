import { useEffect, useState } from "react"
import { toast } from "sonner"
import { ArrowRight, Building2, CheckCircle2, Eye, EyeOff, UserRound } from "lucide-react"
import { Alert } from "@/components/ui/Alert"
import { Button } from "@/components/ui/Button"
import { Card, CardContent } from "@/components/ui/Card"
import { Input } from "@/components/ui/Input"
import { Field } from "@/components/widgets/Field"
import { useAuth } from "@/lib/auth"
import { formatApiError } from "@/lib/types"
import { cn } from "@/lib/utils"
import { useVisitorLogin, useVisitorRegister } from "@/lib/visitor-api"

export type AuthRole = "visitor" | "staff"
export type AuthMode = "register" | "login"

/** Map a DRF error body to per-field messages; anything unmapped goes to `_`. */
function fieldErrors(err: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  const body = (err as { data?: unknown })?.data
  if (body && typeof body === "object" && !Array.isArray(body)) {
    for (const [k, v] of Object.entries(body as Record<string, unknown>)) {
      const msg = Array.isArray(v) ? v.map(String).join(" ") : typeof v === "string" ? v : ""
      if (!msg) continue
      if (k === "detail" || k === "non_field_errors") out._ = msg
      else out[k] = msg
    }
  }
  if (Object.keys(out).length === 0) out._ = formatApiError(err)
  return out
}

interface AuthPanelProps {
  role: AuthRole
  onRoleChange?: (role: AuthRole) => void
  initialMode?: AuthMode
  /** Called after a successful sign-in for the given role. */
  onSignedIn: (role: AuthRole) => void
  compact?: boolean
}

const ROLE_COPY: Record<AuthRole, { title: string; blurb: string; icon: typeof UserRound }> = {
  visitor: {
    title: "I'm visiting",
    blurb: "Book a visit, get your QR pass and manage your appointments.",
    icon: UserRound,
  },
  staff: {
    title: "I work here",
    blurb: "Approve visitor requests, run reception and the gate, see reports.",
    icon: Building2,
  },
}

export function AuthPanel({ role, onRoleChange, initialMode = "register", onSignedIn, compact }: AuthPanelProps) {
  const [mode, setMode] = useState<AuthMode>(initialMode)
  const [show, setShow] = useState(false)
  const [created, setCreated] = useState<string | null>(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [form, setForm] = useState({ email: "", password: "", full_name: "", phone: "", company: "" })
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((f) => ({ ...f, [k]: e.target.value }))
    setErrors((er) => ({ ...er, [k]: "", _: "" }))
  }

  const staff = useAuth()
  const visitorLogin = useVisitorLogin()
  const visitorRegister = useVisitorRegister()
  const [staffBusy, setStaffBusy] = useState(false)
  const busy = visitorLogin.isPending || visitorRegister.isPending || staffBusy

  useEffect(() => {
    setErrors({})
    setCreated(null)
  }, [role])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrors({})
    try {
      if (mode === "register") {
        // Create the account first; the person then signs in explicitly.
        if (role === "visitor") {
          await visitorRegister.mutateAsync({ ...form })
          // registration returns a session; drop it so the sign-in step is explicit
          const { clearVisitorToken } = await import("@/lib/visitor-api")
          clearVisitorToken()
        } else {
          setStaffBusy(true)
          await staff.register({ email: form.email, full_name: form.full_name, phone: form.phone, password: form.password })
          staff.logout()
        }
        setCreated(form.email)
        setMode("login")
        setForm((f) => ({ ...f, password: "" }))
        toast.success("Account created", { description: "Sign in with your email and password to continue." })
        return
      }
      if (role === "visitor") {
        await visitorLogin.mutateAsync({ email: form.email, password: form.password })
      } else {
        setStaffBusy(true)
        await staff.login(form.email, form.password)
      }
      toast.success("Signed in")
      onSignedIn(role)
    } catch (err) {
      setErrors(fieldErrors(err))
    } finally {
      setStaffBusy(false)
    }
  }

  const Icon = ROLE_COPY[role].icon

  return (
    <Card>
      <CardContent className={cn("p-5", compact ? "sm:p-6" : "sm:p-8")}>
        {onRoleChange && (
          <div className="mb-5 grid grid-cols-2 gap-2">
            {(["visitor", "staff"] as AuthRole[]).map((r) => {
              const C = ROLE_COPY[r]
              const active = r === role
              return (
                <button
                  key={r}
                  type="button"
                  onClick={() => onRoleChange(r)}
                  className={cn(
                    "flex items-start gap-3 rounded-xl border p-3 text-left transition",
                    active ? "border-primary bg-primary-soft" : "border-border bg-card hover:border-border-strong",
                  )}
                  aria-pressed={active}
                >
                  <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", active ? "bg-primary text-primary-foreground" : "bg-surface-2 text-muted-foreground")}>
                    <C.icon className="size-4" />
                  </span>
                  <span className="min-w-0">
                    <span className={cn("block text-sm font-semibold", active ? "text-primary" : "text-foreground")}>{C.title}</span>
                    <span className="block text-xs leading-snug text-muted-foreground">{C.blurb}</span>
                  </span>
                </button>
              )
            })}
          </div>
        )}

        <div className="mb-4 inline-flex rounded-xl border border-border bg-secondary p-1">
          {(["register", "login"] as AuthMode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => { setMode(m); setErrors({}) }}
              className={cn("rounded-lg px-4 py-1.5 text-sm font-medium transition-colors", mode === m ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
            >
              {m === "register" ? "1 · Create account" : "2 · Sign in"}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Icon className="size-5 text-primary" />
          <h2 className="text-xl font-bold tracking-tight">
            {mode === "register"
              ? role === "visitor" ? "Create your visitor account" : "Create your staff account"
              : role === "visitor" ? "Sign in as a visitor" : "Sign in to the console"}
          </h2>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          {mode === "register"
            ? role === "visitor"
              ? "Step 1 of 2. After creating the account you sign in, then fill in your visit details."
              : "Step 1 of 2. After creating the account you sign in, then set up or join your organisation."
            : "Step 2 of 2. Use the email and password you just created."}
        </p>

        {created && mode === "login" && (
          <Alert variant="success" className="mt-4">
            <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
            <span>Account for <strong>{created}</strong> is ready. Enter your password to sign in.</span>
          </Alert>
        )}
        {errors._ && (
          <Alert variant="danger" className="mt-4">
            <span>{errors._}</span>
          </Alert>
        )}

        <form onSubmit={submit} className="mt-5 grid gap-4 sm:grid-cols-2" noValidate>
          {mode === "register" && (
            <>
              <Field id="a-name" label="Full name" required error={errors.full_name}>
                <Input id="a-name" value={form.full_name} onChange={set("full_name")} autoComplete="name" />
              </Field>
              <Field id="a-phone" label={role === "visitor" ? "Mobile number" : "Phone"} required={role === "visitor"} error={errors.phone} hint={role === "visitor" ? "At least 7 digits; reception may call you." : undefined}>
                <Input id="a-phone" inputMode="tel" value={form.phone} onChange={set("phone")} autoComplete="tel" />
              </Field>
              {role === "visitor" && (
                <Field id="a-company" label="Company" className="sm:col-span-2" error={errors.company}>
                  <Input id="a-company" value={form.company} onChange={set("company")} autoComplete="organization" />
                </Field>
              )}
            </>
          )}
          <Field id="a-email" label="Email" required error={errors.email} className={mode === "login" ? "sm:col-span-2" : ""}>
            <Input id="a-email" type="email" value={form.email} onChange={set("email")} autoComplete="email" />
          </Field>
          <Field
            id="a-pw"
            label="Password"
            required
            error={errors.password}
            hint={mode === "register" ? "At least 8 characters, not all numbers, not a common word." : undefined}
            className={mode === "login" ? "sm:col-span-2" : ""}
          >
            <div className="relative">
              <Input id="a-pw" type={show ? "text" : "password"} value={form.password} onChange={set("password")} autoComplete={mode === "login" ? "current-password" : "new-password"} className="pr-10" />
              <button type="button" onClick={() => setShow((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" aria-label="Toggle password">
                {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
              </button>
            </div>
          </Field>
          <div className="sm:col-span-2">
            <Button type="submit" size="lg" className="w-full" loading={busy}>
              {mode === "register" ? "Create account" : "Sign in & continue"} <ArrowRight className="size-4" />
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
