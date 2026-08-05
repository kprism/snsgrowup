import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("snsgrowup")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "dispatch-due-publish-queues": {
        "task": "publishing.tasks.dispatch_due_publish_queues",
        "schedule": 10.0,
    },
}
