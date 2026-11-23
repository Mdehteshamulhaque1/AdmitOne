import { NavLink } from "react-router-dom"
import {
  BarChart3,
  Ban,
  CalendarRange,
  CheckCheck,
  GraduationCap,
  LayoutDashboard,
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
export interface NavItem {
  label: string
  href: string
  icon: LucideIcon
  perm?: Permission
  end?: boolean
}

/** Grouped by task: what happens today first, records and admin after. */
export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Today",
    items: [
      { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, end: true },
      { label: "Approvals", href: "/dashboard/approvals", icon: CheckCheck, perm: "approve_visitor" },
      { label: "Gate scanner", href: "/dashboard/security", icon: ScanLine, perm: "scan_qr" },
    ],
  },
  {
    label: "Records",
    items: [
      { label: "Visits", href: "/dashboard/visits", icon: CalendarRange },
      { label: "Visitors", href: "/dashboard/visitors", icon: Users },
      { label: "Student passes", href: "/dashboard/student-passes", icon: GraduationCap, perm: "manage_student_passes" },
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

/** The main action, pinned above the link list instead of buried in it. */
export const PRIMARY_ACTION: NavItem = {
  label: "Register visit",
  href: "/dashboard/register-visit",
  icon: UserPlus,
  perm: "create_visitor",
}

function WithTooltip({ show, label, children }: { show: boolean; label: string; children: React.ReactElement }) {
  if (!show) return children
  return (
    <Tooltip delayDuration={100}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}

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
  return (
    <WithTooltip show={collapsed} label={item.label}>
      <NavLink
        to={item.href}
        end={item.end}
        onClick={onNavigate}
        className={({ isActive }) =>
          cn(
            "group relative flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nav-accent",
            collapsed && "justify-center px-0",
            isActive ? "bg-nav-active text-nav-foreground" : "text-nav-muted hover:bg-nav-hover hover:text-nav-foreground",
          )
        }
      >
        {({ isActive }) => (
          <>
            <span
              aria-hidden="true"
              className={cn(
                "absolute inset-y-2 left-0 w-1 rounded-r-full bg-nav-accent transition-opacity",
                isActive ? "opacity-100" : "opacity-0",
              )}
            />
            <Icon className={cn("size-[18px] shrink-0", isActive && "text-nav-accent")} />
            {!collapsed && <span className="truncate">{item.label}</span>}
            {badge ? (
              <span
                aria-label={`${badge} waiting`}
                className={cn(
                  "flex items-center justify-center rounded-full bg-amber-400 font-bold text-amber-950",
                  collapsed ? "absolute right-1.5 top-1 size-4 text-[9px]" : "ml-auto h-5 min-w-5 px-1.5 text-[11px]",
                )}
              >
                {badge > 99 ? "99+" : badge}
              </span>
            ) : null}
          </>
        )}
      </NavLink>
    </WithTooltip>
  )
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
  const { org, can } = useAuth()
  const pending = usePendingCount()
  const showAction = can(PRIMARY_ACTION.perm!)

  return (
    <aside
      className={cn(
        "sticky top-0 h-screen shrink-0 flex-col border-r border-nav-border bg-nav text-nav-foreground transition-[width] duration-300",
        forceVisible ? "flex w-72" : "hidden lg:flex",
        !forceVisible && (collapsed ? "w-[72px]" : "w-64"),
      )}
      aria-label="Primary"
    >
      <div className={cn("flex h-16 items-center gap-2.5 border-b border-nav-border", collapsed ? "justify-center px-0" : "px-4")}>
        <NavLink to="/dashboard" onClick={onNavigate} className="flex min-w-0 items-center gap-2.5 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nav-accent" aria-label="AdmitOne dashboard">
          <Logo size={32} />
          {!collapsed && (
            <span className="min-w-0 leading-tight">
              <span className="block text-[15px] font-bold tracking-tight">AdmitOne</span>
              <span className="block truncate text-xs text-nav-muted">{org?.name ?? "Your workspace"}</span>
            </span>
          )}
        </NavLink>
      </div>

      {showAction && (
        <div className={cn("pt-4", collapsed ? "px-2.5" : "px-3")}>
          <WithTooltip show={collapsed} label={PRIMARY_ACTION.label}>
            <NavLink
              to={PRIMARY_ACTION.href}
              onClick={onNavigate}
              className={cn(
                "flex h-10 items-center justify-center gap-2 rounded-lg bg-nav-accent text-sm font-semibold text-[#0b1020] transition hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70",
                collapsed ? "px-0" : "px-3",
              )}
            >
              <UserPlus className="size-[18px] shrink-0" />
              {!collapsed && PRIMARY_ACTION.label}
            </NavLink>
          </WithTooltip>
        </div>
      )}

      <nav className={cn("flex-1 space-y-5 overflow-y-auto py-4", collapsed ? "px-2.5" : "px-3")}>
        {NAV_GROUPS.map((group) => {
          // Fails closed: before the server has answered, `can` is false for
          // every permission, so only the ungated entries render.
          const items = group.items.filter((i) => i.perm === undefined || can(i.perm))
          if (items.length === 0) return null
          return (
            <div key={group.label} role="group" aria-label={group.label}>
              {collapsed ? (
                <div className="mx-3 mb-2 h-px bg-nav-border" aria-hidden="true" />
              ) : (
                <div className="mb-1 px-3 text-xs font-semibold text-nav-muted/80">{group.label}</div>
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
    </aside>
  )
}
