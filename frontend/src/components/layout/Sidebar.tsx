import { NavLink } from "react-router-dom"
import {
  BarChart3,
  Ban,
  Building2,
  CalendarRange,
  CheckCheck,
  LayoutDashboard,
  LogOut,
  ScanLine,
  ScrollText,
  Settings,
  UserPlus,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react"
import { Logo } from "@/components/logo"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/Tooltip"
import { useAuth } from "@/lib/auth"
import { usePendingCount } from "@/hooks/use-pending-count"
import { cn } from "@/lib/utils"
import type { Permission } from "@/lib/types"

/**
 * A nav entry and the permission it requires.
 *
 * `perm` names a permission the server already enforces on the matching
 * endpoint. Hiding a link is a courtesy to the operator; refusing the request
 * is the server's job. `perm: undefined` means every signed-in member sees it.
 */
interface NavItem {
  label: string
  href: string
  icon: LucideIcon
  perm?: Permission
  end?: boolean
}

export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [{ label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, end: true }],
  },
  {
    label: "Visitors",
    items: [
      { label: "Visits", href: "/dashboard/visits", icon: CalendarRange },
      { label: "Visitor directory", href: "/dashboard/visitors", icon: Users },
      { label: "Register visit", href: "/dashboard/register-visit", icon: UserPlus, perm: "create_visitor" },
    ],
  },
  {
    label: "Operations",
    items: [
      { label: "Approvals", href: "/dashboard/approvals", icon: CheckCheck, perm: "approve_visitor" },
      { label: "Gate scanner", href: "/dashboard/security", icon: ScanLine, perm: "scan_qr" },
      { label: "Blacklist", href: "/dashboard/blacklist", icon: Ban },
    ],
  },
  {
    label: "Insights",
    items: [
      { label: "Reports", href: "/dashboard/reports", icon: BarChart3, perm: "view_reports" },
      { label: "Audit log", href: "/dashboard/audit", icon: ScrollText, perm: "view_audit_logs" },
    ],
  },
  {
    label: "Workspace",
    items: [
      { label: "Team", href: "/dashboard/team", icon: UsersRound, perm: "manage_users" },
      { label: "Settings", href: "/dashboard/settings", icon: Settings },
    ],
  },
]

function Item({
  item,
  collapsed,
  badge,
  onNavigate,
}: {
  item: NavItem
  collapsed: boolean
  badge?: number
  onNavigate?: () => void
}) {
  const Icon = item.icon
  const content = (
    <NavLink
      to={item.href}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
          collapsed && "justify-center px-0",
          isActive
            ? "bg-primary-soft text-primary"
            : "text-muted-foreground hover:bg-hover hover:text-foreground",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-primary" aria-hidden="true" />
          )}
          <Icon className={cn("size-[18px] shrink-0", isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
          {!collapsed && <span className="truncate">{item.label}</span>}
          {badge ? (
            <span
              className={cn(
                "flex min-w-5 items-center justify-center rounded-full bg-warning-soft px-1.5 text-[11px] font-bold text-warning",
                collapsed ? "absolute -right-0.5 -top-0.5 size-4 min-w-0 px-0 text-[9px]" : "ml-auto h-5",
              )}
            >
              {badge > 99 ? "99+" : badge}
            </span>
          ) : null}
        </>
      )}
    </NavLink>
  )

  if (collapsed) {
    return (
      <Tooltip delayDuration={100}>
        <TooltipTrigger asChild>{content}</TooltipTrigger>
        <TooltipContent side="right">{item.label}</TooltipContent>
      </Tooltip>
    )
  }
  return content
}

export function Sidebar({
  collapsed,
  forceVisible = false,
  onNavigate,
}: {
  collapsed: boolean
  forceVisible?: boolean
  onNavigate?: () => void
}) {
  const { user, org, logout, can } = useAuth()
  const pending = usePendingCount()

  return (
    <aside
      className={cn(
        "sticky top-0 h-screen shrink-0 flex-col border-r border-border bg-elevated/80 backdrop-blur-xl transition-[width] duration-300",
        forceVisible ? "flex w-72" : "hidden lg:flex",
        !forceVisible && (collapsed ? "w-[72px]" : "w-64"),
      )}
      aria-label="Primary"
    >
      <div className={cn("flex h-16 items-center border-b border-border", collapsed ? "justify-center px-0" : "px-5")}>
        <NavLink to="/dashboard" className="flex items-center gap-2.5" aria-label="SecureGate dashboard">
          <Logo size={32} />
          {!collapsed && (
            <span className="text-lg font-bold tracking-tight">
              Secure<span className="text-gradient">Gate</span>
            </span>
          )}
        </NavLink>
      </div>

      <nav className={cn("flex-1 space-y-5 overflow-y-auto py-4", collapsed ? "px-2.5" : "px-3")}>
        {NAV_GROUPS.map((group) => {
          // Fails closed: before the server has answered, `can` is false for
          // every permission, so only the ungated entries render.
          const items = group.items.filter((i) => i.perm === undefined || can(i.perm))
          if (items.length === 0) return null
          return (
            <div key={group.label}>
              {!collapsed && (
                <div className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/70">
                  {group.label}
                </div>
              )}
              <div className="space-y-0.5">
                {items.map((item) => (
                  <Item
                    key={item.href}
                    item={item}
                    collapsed={collapsed}
                    onNavigate={onNavigate}
                    badge={item.href === "/dashboard/approvals" ? pending : undefined}
                  />
                ))}
              </div>
            </div>
          )
        })}
      </nav>

      <div className="border-t border-border p-3">
        {!collapsed && (
          <NavLink
            to="/dashboard/settings"
            onClick={onNavigate}
            className="mb-2 flex items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2.5 transition hover:border-border-strong"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary">
              <Building2 className="size-4" />
            </span>
            <div className="min-w-0">
              <div className="truncate text-xs font-semibold">{org?.name ?? "Workspace"}</div>
              <div className="truncate text-[11px] text-muted-foreground">{user?.email}</div>
            </div>
          </NavLink>
        )}
        <button
          onClick={logout}
          className={cn(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-danger-soft hover:text-danger",
            collapsed && "justify-center px-0",
          )}
        >
          <LogOut className="size-[18px] shrink-0" />
          {!collapsed && "Sign out"}
        </button>
      </div>
    </aside>
  )
}
