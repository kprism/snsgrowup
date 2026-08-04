from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import PublishingBatch, PublishingTask
from .services import ensure_batch_tasks, retry_task


@login_required
def batch_list(request):
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    base_qs = PublishingBatch.objects.filter(owner=request.user)
    if query:
        base_qs = base_qs.filter(
            Q(id__icontains=query)
            | Q(contents__title__icontains=query)
            | Q(channels__profile_name__icontains=query)
            | Q(channels__platform__name__icontains=query)
        ).distinct()
    if status in PublishingBatch.Status.values:
        base_qs = base_qs.filter(status=status)

    batches = list(
        base_qs.prefetch_related("contents", "channels__platform", "tasks").order_by("-created_at")
    )

    for batch in batches:
        if batch.contents.exists() and batch.channels.exists() and not batch.tasks.exists():
            ensure_batch_tasks(batch=batch)

    batches = list(
        base_qs.prefetch_related("contents", "channels__platform", "tasks").order_by("-created_at")
    )
    for batch in batches:
        tasks = list(batch.tasks.all())
        total = len(tasks)
        success = sum(task.status == PublishingTask.Status.SUCCESS for task in tasks)
        failed = sum(task.status == PublishingTask.Status.FAILED for task in tasks)
        connection_required = sum(task.status == PublishingTask.Status.CONNECTION_REQUIRED for task in tasks)
        processing = sum(task.status == PublishingTask.Status.PROCESSING for task in tasks)
        pending = sum(task.status == PublishingTask.Status.PENDING for task in tasks)
        finished = success + failed
        batch.ui_counts = {
            "total": total,
            "success": success,
            "failed": failed,
            "connection_required": connection_required,
            "processing": processing,
            "pending": pending,
        }
        batch.ui_progress = round((finished / total) * 100) if total else 0
        batch.ui_content_titles = list(batch.contents.values_list("title", flat=True)[:2])

    all_owner_qs = PublishingBatch.objects.filter(owner=request.user)
    totals = all_owner_qs.aggregate(
        total=Count("id", distinct=True),
        pending=Count("id", filter=Q(status=PublishingBatch.Status.PENDING), distinct=True),
        processing=Count("id", filter=Q(status=PublishingBatch.Status.PROCESSING), distinct=True),
        completed=Count("id", filter=Q(status=PublishingBatch.Status.COMPLETED), distinct=True),
        failed=Count("id", filter=Q(status__in=[PublishingBatch.Status.FAILED, PublishingBatch.Status.PARTIAL]), distinct=True),
    )
    return render(
        request,
        "publishing/batch_list.html",
        {
            "batches": batches,
            "totals": totals,
            "query": query,
            "selected_status": status,
            "status_choices": PublishingBatch.Status.choices,
        },
    )


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
    ensure_batch_tasks(batch=batch)
    task_counts = {
        "all": batch.tasks.count(),
        "pending": batch.tasks.filter(status=PublishingTask.Status.PENDING).count(),
        "connection_required": batch.tasks.filter(status=PublishingTask.Status.CONNECTION_REQUIRED).count(),
        "processing": batch.tasks.filter(status=PublishingTask.Status.PROCESSING).count(),
        "success": batch.tasks.filter(status=PublishingTask.Status.SUCCESS).count(),
        "failed": batch.tasks.filter(status=PublishingTask.Status.FAILED).count(),
    }
    finished = task_counts["success"] + task_counts["failed"]
    progress = round((finished / task_counts["all"]) * 100) if task_counts["all"] else 0
    return render(
        request,
        "publishing/batch_detail.html",
        {"batch": batch, "task_counts": task_counts, "progress": progress},
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
