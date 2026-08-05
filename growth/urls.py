from django.urls import path

from . import views

app_name = "growth"

urlpatterns = [
    path("", views.action_center, name="action_center"),
    path("<int:pk>/start/", views.start_action, name="start_action"),
    path("<int:pk>/complete/", views.complete_action, name="complete_action"),
    path("<int:pk>/skip/", views.skip_action, name="skip_action"),
]
