from django.urls import path

from . import views

app_name = "publishing"

urlpatterns = [
    path("", views.batch_list, name="batch_list"),
    path("<int:pk>/", views.batch_detail, name="batch_detail"),
    path("<int:pk>/result/", views.publish_result, name="publish_result"),
    path("<int:pk>/status/", views.publish_status, name="publish_status"),
    path("tasks/<int:pk>/execute/", views.task_execute, name="task_execute"),
    path("tasks/<int:pk>/retry/", views.task_retry, name="task_retry"),
]
