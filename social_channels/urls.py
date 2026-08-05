from django.urls import path

from . import instagram_views, views

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
    path("<int:pk>/instagram/connect/", instagram_views.instagram_connect, name="instagram_connect"),
    path("instagram/callback/", instagram_views.instagram_callback, name="instagram_callback"),
    path("<int:pk>/instagram/accounts/", instagram_views.instagram_account_select, name="instagram_account_select"),
    path("<int:pk>/instagram/disconnect/", instagram_views.instagram_disconnect, name="instagram_disconnect"),
]
