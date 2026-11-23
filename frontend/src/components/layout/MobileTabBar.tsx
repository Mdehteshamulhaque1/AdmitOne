import { NavLink } from "react-router-dom"
import { CalendarRange, CheckCheck, LayoutDashboard, Menu, ScanLine, UserPlus, Users } from "lucide-react"
import { useAuth } from "@/lib/auth"
import { usePendingCount } from "@/hooks/use-pending-count"
import { cn } from "@/lib/utils"
import type { NavItem } from "@/components/layout/Sidebar"

/**
 * Bottom tab bar for phones and small tablets. The four tabs depend on what
 * the member can do (a guard gets the scanner, an approver gets approvals);
 * "More" opens the full navigation drawer.
 */
export function MobileTabBar({ onMore }: { onMore: () => void }) {
  const { can } = useAuth()
  const pending = usePendingCount()

  const candidates: (NavItem | false)[] = [
    { label: "Home", href: "/dashboard", icon: LayoutDashboard, end: true },
    can("scan_qr") && { label: "Scan", href: "/dashboard/security", icon: ScanLine },
    can("approve_visitor") && { label: "Approvals", href: "/dashboard/approvals", icon: CheckCheck },
    can("create_visitor") && { label: "Register", href: "/dashboard/register-visit", icon: UserPlus },
    { label: "Visits", href: "/dashboard/visits", icon: CalendarRange },
    { label: "Visitors", href: "/dashboard/visitors", icon: Users },
  ]
  const tabs = candidates.filter((t): t is NavItem => Boolean(t)).slice(0, 4)

  return (
    <nav
      aria-label="Quick navigation"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-nav-border bg-nav text-nav-foreground lg:hidden"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="mx-auto grid max-w-lg grid-cols-5">
        {tabs.map((tab) => (
          <li key={tab.href}>
            <NavLink
              to={tab.href}
              end={tab.end}
              className={({ isActive }) =>
                cn(
                  "relative flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nav-accent",
                  isActive ? "text-nav-accent" : "text-nav-muted hover:text-nav-foreground",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span aria-hidden="true" className={cn("absolute inset-x-5 top-0 h-0.5 rounded-b-full bg-nav-accent", !isActive && "opacity-0")} />
                  <span className="relative">
                    <tab.icon className="size-5" />
                    {tab.href === "/dashboard/approvals" && pending > 0 && (
                      <span className="absolute -right-2.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-amber-400 px-1 text-[9px] font-bold text-amber-950">
                        {pending > 99 ? "99+" : pending}
                      </span>
                    )}
                  </span>
                  {tab.label}
                </>
              )}
            </NavLink>
          </li>
        ))}
        <li>
          <button
            type="button"
            onClick={onMore}
            className="flex h-16 w-full flex-col items-center justify-center gap-1 text-[11px] font-medium text-nav-muted transition-colors hover:text-nav-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nav-accent"
          >
            <Menu className="size-5" />
            More
          </button>
        </li>
      </ul>
    </nav>
  )
}
