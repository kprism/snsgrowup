from django.urls import path

from . import views

app_name = "publishing"

urlpatterns = [
    path("", views.batch_list, name="batch_list"),
]
