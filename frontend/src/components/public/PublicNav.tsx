import { useState, type ReactNode } from "react"
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom"
import { ChevronDown, Menu, Moon, Sun, X } from "lucide-react"
import { LogoWordmark } from "@/components/logo"
import { Button } from "@/components/ui/Button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/DropdownMenu"
import { useTheme } from "@/lib/theme"
import { cn } from "@/lib/utils"

interface MenuLink {
  label: string
  to: string
  hint?: string
}

interface MenuEntry {
  label: string
  to?: string
  items?: MenuLink[]
}

/** The public site's menu, like a gate-pass portal's top bar. */
export const PUBLIC_MENU: MenuEntry[] = [
  { label: "Home", to: "/" },
  {
    label: "Administration",
    items: [
      { label: "Admin sign in", to: "/admin", hint: "Admins, reception and security" },
      { label: "Create a staff account", to: "/admin?mode=register" },
      { label: "Approvals", to: "/dashboard/approvals", hint: "Approve or decline requests" },
      { label: "Gate scanner", to: "/dashboard/security", hint: "Scan passes, see who's inside" },
      { label: "Reports", to: "/dashboard/reports" },
    ],
  },
  {
    label: "E-Services",
    items: [
      { label: "Apply for a visitor pass", to: "/visitor", hint: "Book a visit online" },
      { label: "Track my application", to: "/visitor?view=visits", hint: "See if your host approved" },
      { label: "Download my QR pass", to: "/visitor?view=visits" },
      { label: "Reschedule or cancel a visit", to: "/visitor?view=visits" },
    ],
  },
  { label: "Public Notice", to: "/notices" },
  {
    label: "Rules & Guidelines",
    items: [
      { label: "Visitor pass rules", to: "/rules#pass" },
      { label: "Identity proof", to: "/rules#id" },
      { label: "Photo guidelines", to: "/rules#photo" },
      { label: "At the gate", to: "/rules#gate" },
    ],
  },
]

const itemClass = "inline-flex h-9 items-center gap-1 rounded-lg px-3 text-sm font-medium transition-colors"

export function PublicNav({ right }: { right?: ReactNode }) {
  const { resolved, toggle } = useTheme()
  const navigate = useNavigate()
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [section, setSection] = useState<string | null>(null)

  const isActive = (entry: MenuEntry) =>
    entry.to ? location.pathname === entry.to : entry.items?.some((i) => location.pathname === i.to.split(/[?#]/)[0])

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur-xl">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-4 px-4 sm:px-6">
        <Link to="/" aria-label="AdmitOne home" className="shrink-0"><LogoWordmark /></Link>

        <nav aria-label="Main" className="hidden flex-1 items-center gap-0.5 lg:flex">
          {PUBLIC_MENU.map((entry) =>
            entry.items ? (
              <DropdownMenu key={entry.label}>
                <DropdownMenuTrigger className={cn(itemClass, "data-[state=open]:bg-hover", isActive(entry) ? "text-primary" : "text-muted-foreground hover:text-foreground")}>
                  {entry.label} <ChevronDown className="size-3.5" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-64 p-1.5">
                  {entry.items.map((item) => (
                    <DropdownMenuItem key={item.label} onSelect={() => navigate(item.to)} className="flex-col items-start gap-0 py-2">
                      <span className="text-sm font-medium">{item.label}</span>
                      {item.hint && <span className="text-xs text-muted-foreground">{item.hint}</span>}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : (
              <NavLink
                key={entry.label}
                to={entry.to!}
                end
                className={({ isActive: active }) => cn(itemClass, active ? "text-primary" : "text-muted-foreground hover:text-foreground")}
              >
                {entry.label}
              </NavLink>
            ),
          )}
        </nav>

        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          {right}
          <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
            {resolved === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setOpen((o) => !o)} aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open}>
            {open ? <X className="size-5" /> : <Menu className="size-5" />}
          </Button>
        </div>
      </div>

      {open && (
        <nav aria-label="Main menu" className="max-h-[calc(100vh-4rem)] overflow-y-auto border-t border-border bg-background px-4 pb-4 pt-2 lg:hidden">
          {PUBLIC_MENU.map((entry) =>
            entry.items ? (
              <div key={entry.label} className="border-b border-border last:border-0">
                <button
                  type="button"
                  onClick={() => setSection((s) => (s === entry.label ? null : entry.label))}
                  aria-expanded={section === entry.label}
                  className="flex w-full items-center justify-between py-3 text-sm font-medium"
                >
                  {entry.label} <ChevronDown className={cn("size-4 transition-transform", section === entry.label && "rotate-180")} />
                </button>
                {section === entry.label && (
                  <ul className="pb-2">
                    {entry.items.map((item) => (
                      <li key={item.label}>
                        <Link to={item.to} onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-sm text-muted-foreground hover:bg-hover hover:text-foreground">
                          {item.label}
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <Link key={entry.label} to={entry.to!} onClick={() => setOpen(false)} className="block border-b border-border py-3 text-sm font-medium last:border-0">
                {entry.label}
              </Link>
            ),
          )}
        </nav>
      )}
    </header>
  )
}

/** Page frame for the public pages (start page, notices, rules). */
export function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <PublicNav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-16 pt-8 sm:px-6 sm:pt-10">{children}</main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-5 text-xs text-muted-foreground sm:px-6">
          <span>AdmitOne visitor pass system</span>
          <span className="flex gap-4">
            <Link to="/notices" className="hover:text-foreground">Public notice</Link>
            <Link to="/rules" className="hover:text-foreground">Rules & guidelines</Link>
            <Link to="/about" className="hover:text-foreground">About</Link>
          </span>
        </div>
      </footer>
    </div>
  )
}
