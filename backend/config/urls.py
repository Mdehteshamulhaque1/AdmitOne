from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve

admin.site.site_header = "AdmitOne administration"
admin.site.site_title = "AdmitOne admin"
admin.site.index_title = "Workspace data"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]

if settings.ENVIRONMENT != "development" and settings.MEDIA_ROOT:
    # Production serves MEDIA_ROOT (photos, avatars, logos) through Django.
    # django.views.static.serve joins with safe_join (no `..` escape) and does
    # not list directories. Identity documents live in PRIVATEMEDIA_ROOT, which
    # visits.E002 forces OUTSIDE MEDIA_ROOT, so they are never reachable here.
    urlpatterns += [
        path("media/<path:path>", serve, {"document_root": settings.MEDIA_ROOT})
    ]
elif settings.DEBUG and settings.MEDIA_ROOT:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
