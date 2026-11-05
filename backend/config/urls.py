from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from apps.users.admin_site import admin_site


urlpatterns = [
    # Admin
    path("admin/", admin_site.urls),

    # API Schema & Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/schema/swagger-ui/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="swagger-ui",
    ),

    #User App
    path("api/users/", include("apps.users.urls")),
]

# Django Debug Toolbar (Development only)
if settings.DEBUG:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
    ]

    # Static and Media files (Development only)
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
