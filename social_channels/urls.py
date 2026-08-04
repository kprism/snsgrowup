from django.urls import path

from . import views

app_name = "social_channels"

urlpatterns = [
    path("", views.account_list, name="account_list"),
    path("add/", views.account_create, name="account_create"),
    path("<int:pk>/edit/", views.account_update, name="account_update"),
    path("<int:pk>/delete/", views.account_delete, name="account_delete"),
]
