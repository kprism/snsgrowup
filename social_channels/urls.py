from django.urls import path

from . import views

app_name = "social_channels"

urlpatterns = [
    path("", views.account_list, name="account_list"),
    path("add/", views.account_create, name="account_create"),
    path("<int:pk>/edit/", views.account_update, name="account_update"),
    path("<int:pk>/delete/", views.account_delete, name="account_delete"),
    path("<int:pk>/facebook/connect/", views.facebook_connect, name="facebook_connect"),
    path("facebook/callback/", views.facebook_callback, name="facebook_callback"),
    path("<int:pk>/facebook/pages/", views.facebook_page_select, name="facebook_page_select"),
    path("<int:pk>/facebook/disconnect/", views.facebook_disconnect, name="facebook_disconnect"),
]
