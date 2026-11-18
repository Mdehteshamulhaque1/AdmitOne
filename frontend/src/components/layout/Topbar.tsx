import { useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import {
  Bell,
  Check,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Settings,
  Sun,
  UserRound,
} from "lucide-react"
import { Avatar } from "@/components/ui/Avatar"
import { Badge } from "@/components/ui/Badge"
import { Button } from "@/components/ui/Button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu"
import { StatusChip } from "@/components/widgets/StatusChip"
import { useAuth } from "@/lib/auth"
import { useVisitList } from "@/lib/queries"
import { useTheme, type ThemePreference } from "@/lib/theme"
import { ROLE_LABELS } from "@/lib/types"
import { formatDate } from "@/lib/utils"

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
]

export function Topbar({
  onMenu,
  onCollapse,
  collapsed,
}: {
  onMenu: () => void
  onCollapse: () => void
  collapsed: boolean
}) {
  const { user, logout, can } = useAuth()
  const { preference, resolved, setPreference } = useTheme()
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const [showNotifications, setShowNotifications] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const canApprove = can("approve_visitor")
  const { data: pendingVisits } = useVisitList(
    { status: "PENDING", page_size: 8 },
    { refetchInterval: canApprove ? 45_000 : undefined },
  )
  const { data: arrivingToday } = useVisitList(
    { date: "today", status: "APPROVED", page_size: 8, ordering: "expected_arrival" },
    { refetchInterval: 60_000 },
  )
  const pending = canApprove ? pendingVisits.length : 0
  const notificationCount = pending + arrivingToday.length

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement?.tagName ?? "").toLowerCase()
      if (e.key === "/" && tag !== "input" && tag !== "textarea" && tag !== "select") {
        e.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  const submitSearch = (e: React.FormEvent) => {
    e.preventDefault()
    const q = search.trim()
    navigate(`/dashboard/visitors${q ? `?q=${encodeURIComponent(q)}` : ""}`)
  }

  const ThemeIcon = resolved === "dark" ? Moon : Sun

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/75 backdrop-blur-xl">
      <div className="flex h-16 items-center gap-2 px-4 sm:gap-3 lg:px-6">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenu} aria-label="Open navigation">
          <Menu className="size-5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="hidden lg:inline-flex"
          onClick={onCollapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeftOpen className="size-5" /> : <PanelLeftClose className="size-5" />}
        </Button>

        <form onSubmit={submitSearch} className="relative hidden max-w-md flex-1 sm:block">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={inputRef}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search visitors by name, phone or company…"
            aria-label="Search visitors"
            className="h-10 w-full rounded-lg border border-input bg-card pl-9 pr-10 text-sm placeholder:text-muted-foreground/70 focus:border-ring focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
          <kbd className="pointer-events-none absolute right-3 top-1/2 hidden -translate-y-1/2 rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground md:block">
            /
          </kbd>
        </form>

        <div className="ml-auto flex items-center gap-1">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Change theme">
                <ThemeIcon className="size-[18px]" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuLabel>Appearance</DropdownMenuLabel>
              {THEME_OPTIONS.map((opt) => (
                <DropdownMenuItem key={opt.value} onClick={() => setPreference(opt.value)}>
                  <opt.icon className="size-4 text-muted-foreground" />
                  <span className="flex-1">{opt.label}</span>
                  {preference === opt.value && <Check className="size-4 text-primary" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu open={showNotifications} onOpenChange={setShowNotifications}>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Notifications" className="relative">
                <Bell className="size-[18px]" />
                {notificationCount > 0 && (
                  <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-warning px-1 text-[10px] font-bold leading-4 text-white">
                    {notificationCount > 9 ? "9+" : notificationCount}
                  </span>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[22rem] p-0">
              <div className="max-h-[26rem] overflow-y-auto">
                {canApprove && (
                  <section>
                    <div className="flex items-center justify-between px-3 pb-1 pt-3 text-xs font-semibold text-muted-foreground">
                      <span>Waiting for approval</span>
                      {pending > 0 && <Badge tone="warning" size="sm">{pending}</Badge>}
                    </div>
                    {pendingVisits.length === 0 ? (
                      <p className="px-3 pb-3 text-sm text-muted-foreground">Nothing to approve.</p>
                    ) : (
                      pendingVisits.map((v) => (
                        <Link
                          key={v.id}
                          to="/dashboard/approvals"
                          onClick={() => setShowNotifications(false)}
                          className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-hover"
                        >
                          <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-8" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium">{v.visitor.full_name}</div>
                            <div className="truncate text-xs text-muted-foreground">
                              {v.purpose} · {formatDate(v.visit_date)}
                            </div>
                          </div>
                          <StatusChip status={v.status} />
                        </Link>
                      ))
                    )}
                  </section>
                )}
                <DropdownMenuSeparator className="my-0" />
                <section>
                  <div className="flex items-center justify-between px-3 pb-1 pt-3 text-xs font-semibold text-muted-foreground">
                    <span>Expected today</span>
                    {arrivingToday.length > 0 && <Badge tone="info" size="sm">{arrivingToday.length}</Badge>}
                  </div>
                  {arrivingToday.length === 0 ? (
                    <p className="px-3 pb-3 text-sm text-muted-foreground">No approved arrivals today.</p>
                  ) : (
                    arrivingToday.map((v) => (
                      <Link
                        key={v.id}
                        to={`/dashboard/visits?date=today&status=APPROVED`}
                        onClick={() => setShowNotifications(false)}
                        className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-hover"
                      >
                        <Avatar name={v.visitor.full_name} src={v.visitor.photo} className="size-8" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium">{v.visitor.full_name}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {v.expected_arrival.slice(0, 5)} · {v.host_name || "No host"}
                          </div>
                        </div>
                        {v.arriving_at && <Badge tone="cyan" size="sm">On the way</Badge>}
                      </Link>
                    ))
                  )}
                </section>
              </div>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                className="ml-1 flex items-center gap-2 rounded-full p-1 outline-none transition hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Account menu"
              >
                <Avatar name={user?.full_name ?? "?"} className="size-9" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <DropdownMenuLabel>
                <div className="text-sm font-semibold text-foreground">{user?.full_name}</div>
                <div className="truncate text-xs font-normal text-muted-foreground">{user?.email}</div>
                <div className="mt-1.5">
                  <Badge tone="primary" size="sm">
                    {user?.role ? ROLE_LABELS[user.role] : "Unknown role"}
                  </Badge>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate("/dashboard/settings/account")}>
                <UserRound className="size-4 text-muted-foreground" /> My account
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => navigate("/dashboard/settings")}>
                <Settings className="size-4 text-muted-foreground" /> Workspace settings
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={logout} className="text-danger focus:text-danger">
                Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
