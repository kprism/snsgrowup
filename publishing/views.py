from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .forms import AutomationSettingForm
from .models import AutomationSetting, PublishingBatch, PublishingTask, PublishQueue
from .services import ensure_batch_tasks, retry_task
from .tasks import publish_facebook_task


def _queue_for_task(task):
    try:
        return task.publish_queue
    except PublishQueue.DoesNotExist:
        return None


def _decorate_task_queue(task, now=None):
    now = now or timezone.now()
    queue = _queue_for_task(task)
    task.ui_queue = queue
    task.ui_queue_status = queue.status if queue else ""
    task.ui_queue_label = queue.get_status_display() if queue else ""
    task.ui_eta_at = None
    task.ui_eta_seconds = None

    if queue:
        eta_at = queue.next_retry_at if queue.status == PublishQueue.Status.RETRY and queue.next_retry_at else queue.scheduled_at
        task.ui_eta_at = eta_at
        if queue.status in [PublishQueue.Status.SCHEDULED, PublishQueue.Status.RETRY] and eta_at:
            task.ui_eta_seconds = max(0, int((eta_at - now).total_seconds()))
    return task


def _queue_summary(tasks, now=None):
    now = now or timezone.now()
    counts = {value: 0 for value in PublishQueue.Status.values}
    next_eta = None
    for task in tasks:
        _decorate_task_queue(task, now=now)
        queue = task.ui_queue
        if not queue:
            continue
        counts[queue.status] = counts.get(queue.status, 0) + 1
        eta_at = task.ui_eta_at
        if queue.status in [PublishQueue.Status.SCHEDULED, PublishQueue.Status.RETRY] and eta_at:
            if next_eta is None or eta_at < next_eta:
                next_eta = eta_at
    return counts, next_eta


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

    batches = list(base_qs.prefetch_related("contents", "channels__platform", "tasks__publish_queue").order_by("-created_at"))
    for batch in batches:
        if batch.contents.exists() and batch.channels.exists() and not batch.tasks.exists():
            ensure_batch_tasks(batch=batch)

    now = timezone.now()
    batches = list(base_qs.prefetch_related("contents", "channels__platform", "tasks__publish_queue").order_by("-created_at"))
    for batch in batches:
        tasks = list(batch.tasks.all())
        total = len(tasks)
        success = sum(task.status == PublishingTask.Status.SUCCESS for task in tasks)
        failed = sum(task.status == PublishingTask.Status.FAILED for task in tasks)
        connection_required = sum(task.status == PublishingTask.Status.CONNECTION_REQUIRED for task in tasks)
        processing = sum(task.status == PublishingTask.Status.PROCESSING for task in tasks)
        pending = sum(task.status == PublishingTask.Status.PENDING for task in tasks)
        finished = success + failed
        queue_counts, next_eta = _queue_summary(tasks, now=now)
        batch.ui_counts = {
            "total": total,
            "success": success,
            "failed": failed,
            "connection_required": connection_required,
            "processing": processing,
            "pending": pending,
        }
        batch.ui_queue_counts = queue_counts
        batch.ui_next_eta = next_eta
        batch.ui_next_eta_seconds = max(0, int((next_eta - now).total_seconds())) if next_eta else None
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
def automation_settings(request):
    setting, _ = AutomationSetting.objects.get_or_create(owner=request.user)
    if request.method == "POST":
        form = AutomationSettingForm(request.POST, instance=setting)
        if form.is_valid():
            form.save()
            messages.success(request, "자동발행 설정을 저장했습니다.")
            return redirect("publishing:automation_settings")
    else:
        form = AutomationSettingForm(instance=setting)
    return render(request, "publishing/automation_settings.html", {"form": form, "setting": setting})


@login_required
def batch_detail(request, pk):
    batch = get_object_or_404(
        PublishingBatch.objects.prefetch_related(
            "contents",
            "channels__platform",
            "tasks__content",
            "tasks__channel__platform",
            "tasks__publish_queue",
        ),
        pk=pk,
        owner=request.user,
    )
    ensure_batch_tasks(batch=batch)
    tasks = list(batch.tasks.all())
    queue_counts, next_eta = _queue_summary(tasks)
    batch.ui_tasks = tasks
    batch.ui_next_eta = next_eta
    task_counts = {
        "all": len(tasks),
        "pending": sum(task.status == PublishingTask.Status.PENDING for task in tasks),
        "connection_required": sum(task.status == PublishingTask.Status.CONNECTION_REQUIRED for task in tasks),
        "processing": sum(task.status == PublishingTask.Status.PROCESSING for task in tasks),
        "success": sum(task.status == PublishingTask.Status.SUCCESS for task in tasks),
        "failed": sum(task.status == PublishingTask.Status.FAILED for task in tasks),
    }
    finished = task_counts["success"] + task_counts["failed"]
    progress = round((finished / task_counts["all"]) * 100) if task_counts["all"] else 0
    return render(
        request,
        "publishing/batch_detail.html",
        {
            "batch": batch,
            "task_counts": task_counts,
            "queue_counts": queue_counts,
            "progress": progress,
        },
    )


@login_required
def publish_result(request, pk):
    batch = get_object_or_404(
        PublishingBatch.objects.prefetch_related("tasks__content", "tasks__channel__platform", "tasks__publish_queue"),
        pk=pk,
        owner=request.user,
    )
    return render(request, "publishing/publish_result.html", {"batch": batch})


@login_required
@require_GET
def publish_status(request, pk):
    batch = get_object_or_404(
        PublishingBatch.objects.prefetch_related("tasks__content", "tasks__channel__platform", "tasks__publish_queue"),
        pk=pk,
        owner=request.user,
    )
    now = timezone.now()
    tasks = list(batch.tasks.all())
    total = len(tasks)
    success = sum(task.status == PublishingTask.Status.SUCCESS for task in tasks)
    failed = sum(task.status == PublishingTask.Status.FAILED for task in tasks)
    connection_required = sum(task.status == PublishingTask.Status.CONNECTION_REQUIRED for task in tasks)
    processing = sum(task.status == PublishingTask.Status.PROCESSING for task in tasks)
    pending = sum(task.status == PublishingTask.Status.PENDING for task in tasks)
    finished = success + failed + connection_required
    percent = round((finished / total) * 100) if total else 100
    done = total == finished

    response_tasks = []
    for task in tasks:
        _decorate_task_queue(task, now=now)
        response_tasks.append(
            {
                "id": task.pk,
                "status": task.status,
                "status_label": task.get_status_display(),
                "content": task.content.title,
                "channel": task.channel.profile_name,
                "url": task.external_post_url,
                "error": task.error_message,
                "queue_status": task.ui_queue_status,
                "queue_label": task.ui_queue_label,
                "scheduled_at": task.ui_eta_at.isoformat() if task.ui_eta_at else None,
                "eta_seconds": task.ui_eta_seconds,
                "retry_count": task.ui_queue.retry_count if task.ui_queue else 0,
                "last_error": task.ui_queue.last_error if task.ui_queue else "",
            }
        )

    return JsonResponse(
        {
            "done": done,
            "percent": percent,
            "total": total,
            "success": success,
            "failed": failed,
            "connection_required": connection_required,
            "processing": processing,
            "pending": pending,
            "tasks": response_tasks,
        }
    )


@login_required
@require_POST
def task_execute(request, pk):
    task = get_object_or_404(
        PublishingTask.objects.select_related("batch", "channel__platform"),
        pk=pk,
        batch__owner=request.user,
    )
    if task.channel.platform.code != "facebook":
        messages.error(request, "현재 실제 게시 실행은 Facebook 작업만 지원합니다.")
    elif task.status == PublishingTask.Status.PROCESSING:
        messages.warning(request, "이미 처리 중인 작업입니다.")
    elif task.status == PublishingTask.Status.SUCCESS:
        messages.warning(request, "이미 성공한 작업입니다. 중복 게시를 방지하기 위해 다시 실행하지 않았습니다.")
    elif not task.channel.is_connected:
        messages.warning(request, "Facebook 페이지 연결이 필요합니다.")
    else:
        publish_facebook_task.delay(task.pk)
        messages.success(request, "Facebook 게시를 시작했습니다.")
        return redirect("publishing:publish_result", pk=task.batch_id)
    return redirect("publishing:batch_detail", pk=task.batch_id)


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
