from django.urls import path

from . import views

app_name = "publishing"

urlpatterns = [
    path("", views.batch_list, name="batch_list"),
    path("<int:pk>/", views.batch_detail, name="batch_detail"),
    path("tasks/<int:pk>/execute/", views.task_execute, name="task_execute"),
    path("tasks/<int:pk>/retry/", views.task_retry, name="task_retry"),
]
