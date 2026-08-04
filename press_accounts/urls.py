from django.urls import path

from . import views

app_name = "press_accounts"

urlpatterns = [
    path("", views.rss_dashboard, name="rss_dashboard"),
    path("check/", views.rss_check, name="rss_check"),
    path("collect/", views.rss_collect, name="rss_collect"),
    path("collect/status/<str:task_id>/", views.rss_collect_status, name="rss_collect_status"),
]
