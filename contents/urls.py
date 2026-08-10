from django.urls import path

from . import views

app_name = "contents"

urlpatterns = [
    path("", views.content_list, name="content_list"),
    path("facebook-preview/", views.facebook_preview, name="facebook_preview"),
    path("ai/facebook-draft/", views.ai_facebook_draft, name="ai_facebook_draft"),
    path("media/instagram/<int:pk>/<str:token>.jpg", views.instagram_media, name="instagram_media"),
    path("add/", views.content_create, name="content_create"),
    path("<int:pk>/edit/", views.content_update, name="content_update"),
    path("<int:pk>/delete/", views.content_delete, name="content_delete"),
]
