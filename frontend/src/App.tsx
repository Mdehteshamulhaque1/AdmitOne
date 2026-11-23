import { lazy, Suspense, type ReactNode } from "react"
import { Navigate, Route, Routes, useSearchParams } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { PageLoader } from "@/components/widgets/PageLoader"
import { useAuth } from "@/lib/auth"
import type { Permission } from "@/lib/types"
import { ForbiddenPage, NotFoundPage } from "@/pages/Error"
import { DashboardPage } from "@/pages/Dashboard"
import { AdminLoginPage } from "@/pages/auth/AdminLogin"
import { PortalChooserPage } from "@/pages/auth/PortalChooser"
import { NoticesPage } from "@/pages/public/Notices"
import { RulesPage } from "@/pages/public/Rules"
import { OnboardingPage } from "@/pages/Onboarding"

const LandingPage = lazy(() => import("@/pages/Landing"))

// Console routes stay out of the entry bundle so the first paint only carries
// the landing/auth screens. Each page downloads on first navigation; Reports
// takes recharts with it and the gate screen takes the camera decoder.
const lazyPage = <T extends Record<string, unknown>>(
  loader: () => Promise<T>,
  pick: (m: T) => React.ComponentType,
) => lazy(() => loader().then((m) => ({ default: pick(m) })))

const ApprovalsPage = lazyPage(() => import("@/pages/Approvals"), (m) => m.ApprovalsPage)
const AuditLogPage = lazyPage(() => import("@/pages/AuditLog"), (m) => m.AuditLogPage)
const BlacklistPage = lazyPage(() => import("@/pages/Blacklist"), (m) => m.BlacklistPage)
const RegisterVisitPage = lazyPage(() => import("@/pages/RegisterVisit"), (m) => m.RegisterVisitPage)
const ReportsPage = lazyPage(() => import("@/pages/Reports"), (m) => m.ReportsPage)
const SecurityPage = lazyPage(() => import("@/pages/Security"), (m) => m.SecurityPage)
const SettingsPage = lazyPage(() => import("@/pages/Settings"), (m) => m.SettingsPage)
const TeamPage = lazyPage(() => import("@/pages/Team"), (m) => m.TeamPage)
const VisitorHubPage = lazyPage(() => import("@/pages/VisitorHub"), (m) => m.VisitorHubPage)
const VisitorsPage = lazyPage(() => import("@/pages/Visitors"), (m) => m.VisitorsPage)
const StudentPassesPage = lazyPage(() => import("@/pages/StudentPasses"), (m) => m.StudentPassesPage)
const VisitsPage = lazyPage(() => import("@/pages/Visits"), (m) => m.VisitsPage)

function LazyRoute({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>
}

/** Old `/login?role=…` links: send people to the matching portal. */
function LoginRedirect() {
  const [params] = useSearchParams()
  if (params.get("role") === "staff") {
    return <Navigate to={params.get("mode") === "register" ? "/admin?mode=register" : "/admin"} replace />
  }
  return <Navigate to="/visitor" replace />
}

function Protected({ children, perm }: { children: ReactNode; perm?: Permission }) {
  const { isAuthenticated, loading, org, can } = useAuth()

  if (loading) return <PageLoader />
  if (!isAuthenticated) return <Navigate to="/admin" replace />
  // A signed-in user with no workspace has not finished onboarding; every
  // console route is meaningless until they do.
  if (org === null) return <Navigate to="/onboarding" replace />
  // `can` fails closed: capabilities are empty until the server has answered,
  // so a gated route is never reachable with unknown permissions.
  if (perm && !can(perm)) return <ForbiddenPage />
  return children
}

export default function App() {
  return (
    <Routes>
      {/* Front door: two portals (visitor, admin) on the same backend. */}
      <Route path="/" element={<PortalChooserPage />} />
      <Route path="/notices" element={<NoticesPage />} />
      <Route path="/rules" element={<RulesPage />} />
      <Route
        path="/about"
        element={
          <Suspense fallback={<PageLoader />}>
            <LandingPage />
          </Suspense>
        }
      />
      {/* Admin portal sign-in; the console itself lives under /dashboard. */}
      <Route path="/admin" element={<AdminLoginPage />} />
      <Route path="/login" element={<LoginRedirect />} />
      <Route path="/signup" element={<Navigate to="/admin?mode=register" replace />} />
      <Route path="/start" element={<Navigate to="/" replace />} />
      <Route path="/onboarding" element={<OnboardingPage />} />
      {/* One stepwise visitor page: account -> organisation -> details ->
          schedule -> review -> confirmation, plus "My visits". The older
          /book and /my-visit links keep working. */}
      <Route path="/visitor" element={<LazyRoute><VisitorHubPage /></LazyRoute>} />
      <Route path="/book" element={<LazyRoute><VisitorHubPage /></LazyRoute>} />
      <Route path="/book/:slug" element={<LazyRoute><VisitorHubPage /></LazyRoute>} />
      <Route path="/my-visit" element={<Navigate to="/visitor?view=visits" replace />} />

      <Route
        path="/dashboard"
        element={
          <Protected>
            <AppShell />
          </Protected>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="visits" element={<LazyRoute><VisitsPage /></LazyRoute>} />
        <Route path="visitors" element={<LazyRoute><VisitorsPage /></LazyRoute>} />
        <Route
          path="register-visit"
          element={
            <Protected perm="create_visitor">
              <LazyRoute><RegisterVisitPage /></LazyRoute>
            </Protected>
          }
        />
        <Route
          path="approvals"
          element={
            <Protected perm="approve_visitor">
              <LazyRoute><ApprovalsPage /></LazyRoute>
            </Protected>
          }
        />
        <Route
          path="security"
          element={
            <Protected perm="scan_qr">
              <LazyRoute><SecurityPage /></LazyRoute>
            </Protected>
          }
        />
        <Route path="blacklist" element={<LazyRoute><BlacklistPage /></LazyRoute>} />
        <Route
          path="student-passes"
          element={
            <Protected perm="manage_student_passes">
              <LazyRoute><StudentPassesPage /></LazyRoute>
            </Protected>
          }
        />
        <Route
          path="reports"
          element={
            <Protected perm="view_reports">
              <LazyRoute><ReportsPage /></LazyRoute>
            </Protected>
          }
        />
        <Route
          path="audit"
          element={
            <Protected perm="view_audit_logs">
              <LazyRoute><AuditLogPage /></LazyRoute>
            </Protected>
          }
        />
        <Route
          path="team"
          element={
            <Protected perm="manage_users">
              <LazyRoute><TeamPage /></LazyRoute>
            </Protected>
          }
        />
        <Route path="settings" element={<LazyRoute><SettingsPage /></LazyRoute>} />
        <Route path="settings/:tab" element={<LazyRoute><SettingsPage /></LazyRoute>} />
        <Route path="*" element={<NotFoundPage inline />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
