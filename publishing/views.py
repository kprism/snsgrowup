from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import PublishingBatch, PublishingTask
from .services import retry_task


@login_required
def batch_list(request):
    batches = (
        PublishingBatch.objects.filter(owner=request.user)
        .prefetch_related("contents", "channels__platform", "tasks")
        .order_by("-created_at")
    )
    return render(request, "publishing/batch_list.html", {"batches": batches})


@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(
        PublishingBatch.objects.prefetch_related(
            "contents",
            "channels__platform",
            "tasks__content",
            "tasks__channel__platform",
        ),
        pk=pk,
        owner=request.user,
    )
    task_counts = {
        "all": batch.tasks.count(),
        "pending": batch.tasks.filter(status=PublishingTask.Status.PENDING).count(),
        "connection_required": batch.tasks.filter(status=PublishingTask.Status.CONNECTION_REQUIRED).count(),
        "processing": batch.tasks.filter(status=PublishingTask.Status.PROCESSING).count(),
        "success": batch.tasks.filter(status=PublishingTask.Status.SUCCESS).count(),
        "failed": batch.tasks.filter(status=PublishingTask.Status.FAILED).count(),
    }
    return render(
        request,
        "publishing/batch_detail.html",
        {"batch": batch, "task_counts": task_counts},
    )


@login_required
@require_POST
def task_retry(request, pk):
    task = get_object_or_404(
        PublishingTask.objects.select_related("batch", "channel"),
        pk=pk,
        batch__owner=request.user,
    )
    retry_task(task=task)
    if task.status == PublishingTask.Status.CONNECTION_REQUIRED:
        messages.warning(request, "채널의 공식 API 연결이 필요합니다.")
    else:
        messages.success(request, "작업을 다시 대기열에 등록했습니다.")
    return redirect("publishing:batch_detail", pk=task.batch_id)
