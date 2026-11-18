from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from . import management_views as mgmt
from . import views
from . import visitor_views as visitor

visitor_urlpatterns = [
    path("visitor/auth/register/", visitor.VisitorRegisterView.as_view(), name="api-visitor-register"),
    path("visitor/auth/login/", visitor.VisitorLoginView.as_view(), name="api-visitor-login"),
    path("visitor/auth/logout/", visitor.VisitorLogoutView.as_view(), name="api-visitor-logout"),
    path("visitor/me/", visitor.VisitorMeView.as_view(), name="api-visitor-me"),
    path("visitor/change-password/", visitor.VisitorChangePasswordView.as_view(), name="api-visitor-change-password"),
    path("visitor/organizations/", visitor.VisitorOrganizationSearchView.as_view(), name="api-visitor-orgs"),
    path("visitor/organizations/<slug:slug>/", visitor.VisitorOrganizationContextView.as_view(), name="api-visitor-org-context"),
    path("visitor/bookings/", visitor.VisitorBookingsView.as_view(), name="api-visitor-bookings"),
    path("visitor/bookings/<int:pk>/", visitor.VisitorBookingDetailView.as_view(), name="api-visitor-booking"),
    path("visitor/bookings/<int:pk>/availability/", visitor.VisitorBookingAvailabilityView.as_view(), name="api-visitor-booking-availability"),
    path("visitor/bookings/<int:pk>/reschedule/", visitor.VisitorBookingRescheduleView.as_view(), name="api-visitor-booking-reschedule"),
    path("visitor/bookings/<int:pk>/cancel/", visitor.VisitorBookingCancelView.as_view(), name="api-visitor-booking-cancel"),
    path("visitor/bookings/<int:pk>/arriving/", visitor.VisitorBookingArrivingView.as_view(), name="api-visitor-booking-arriving"),
]

router = DefaultRouter()
router.register("visitors", views.VisitorViewSet, basename="api-visitors")
router.register("visits", views.VisitViewSet, basename="api-visits")
router.register("buildings", mgmt.BuildingViewSet, basename="api-buildings")
router.register("departments", mgmt.DepartmentViewSet, basename="api-departments")
router.register("team", mgmt.TeamViewSet, basename="api-team")

urlpatterns = [
    path("health/", views.HealthCheckView.as_view(), name="api-health"),
    path("visits/register/", views.RegisterVisitView.as_view(), name="api-visit-register"),
    path("visits/walkin/", views.WalkInRegistrationView.as_view(), name="api-visit-walkin"),
    path("", include(router.urls)),
    path("auth/register/", views.RegisterView.as_view(), name="api-register"),
    path("auth/token/", views.LockoutTokenObtainPairView.as_view(), name="api-token"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="api-token-refresh"),
    path("auth/logout/", views.LogoutView.as_view(), name="api-logout"),
    path("auth/me/", views.CurrentUserView.as_view(), name="api-me"),
    path("auth/me/profile/", mgmt.ProfileView.as_view(), name="api-me-profile"),
    path("auth/change-password/", mgmt.ChangePasswordView.as_view(), name="api-change-password"),
    path("hosts/", views.HostListView.as_view(), name="api-hosts"),
    path("organizations/", views.OrganizationCreateView.as_view(), name="api-org-create"),
    path("organizations/me/", mgmt.OrganizationMeView.as_view(), name="api-org-me"),
    path("audit-logs/", mgmt.AuditLogListView.as_view(), name="api-audit-logs"),
    path("audit-logs/actions/", mgmt.AuditActionsView.as_view(), name="api-audit-actions"),
    path("blacklist/", mgmt.BlacklistListView.as_view(), name="api-blacklist"),
    path("time/", mgmt.ServerTimeView.as_view(), name="api-time"),
    path("public/booking/<slug:slug>/hosts/", views.PublicBookingHostsView.as_view(), name="api-public-booking-hosts"),
    path("public/booking/<slug:slug>/availability/", views.PublicBookingAvailabilityView.as_view(), name="api-public-booking-availability"),
    path("public/booking/<slug:slug>/", views.PublicBookingView.as_view(), name="api-public-booking"),
    path("dashboard/summary/", views.DashboardSummaryView.as_view(), name="api-dashboard-summary"),
    path("reports/export/", views.ReportExportView.as_view(), name="api-reports-export"),
] + visitor_urlpatterns
