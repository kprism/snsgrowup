from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, reverse_lazy
from django.views.generic import RedirectView

urlpatterns = [
    path("", include("dashboard.urls")),
    path("accounts/", include("accounts.urls")),
    path("channels/", include("social_channels.urls")),
    path("contents/", include("contents.urls")),
    path("publishing/", include("publishing.urls")),
    path(
        "settings/automation/",
        RedirectView.as_view(url=reverse_lazy("publishing:automation_settings"), permanent=False),
        name="automation_settings_legacy",
    ),
    path("rss/", include("press_accounts.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
