import { Link } from "react-router-dom"
import { Compass, Home, ShieldOff } from "lucide-react"
import { Logo } from "@/components/logo"
import { Button } from "@/components/ui/Button"
import { useAuth } from "@/lib/auth"
import { cn } from "@/lib/utils"

function Frame({ inline, children }: { inline?: boolean; children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center justify-center gap-6 overflow-hidden px-6 text-center",
        inline ? "card-surface min-h-[60vh] py-16" : "min-h-screen",
      )}
    >
      {!inline && <div className="sg-aurora pointer-events-none absolute inset-0 -z-10" />}
      {children}
    </div>
  )
}

export function NotFoundPage({ inline = false }: { inline?: boolean }) {
  const { isAuthenticated } = useAuth()
  return (
    <Frame inline={inline}>
      <Logo className="size-12" />
      <div>
        <p className="font-display text-6xl font-black tracking-tight text-gradient">404</p>
        <h1 className="mt-2 text-lg font-semibold">This page is off the grid</h1>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has moved.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Button asChild variant={isAuthenticated ? "outline" : "primary"}>
          <Link to="/">
            <Home className="size-4" /> Home
          </Link>
        </Button>
        {isAuthenticated && (
          <Button asChild>
            <Link to="/dashboard">
              <Compass className="size-4" /> Open dashboard
            </Link>
          </Button>
        )}
      </div>
    </Frame>
  )
}

export function ForbiddenPage() {
  const { user } = useAuth()
  return (
    <Frame inline>
      <span className="flex size-14 items-center justify-center rounded-2xl bg-danger-soft text-danger">
        <ShieldOff className="size-7" />
      </span>
      <div>
        <h1 className="text-lg font-semibold">You don't have access to this area</h1>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">
          Your role{user?.role ? ` (${user.role.toLowerCase()})` : ""} doesn't include this capability.
          Ask a workspace admin if you need it.
        </p>
      </div>
      <Button asChild>
        <Link to="/dashboard">
          <Compass className="size-4" /> Back to dashboard
        </Link>
      </Button>
    </Frame>
  )
}
