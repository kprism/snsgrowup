from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import GrowthAction


@login_required
def action_center(request):
    actions = GrowthAction.objects.filter(owner=request.user)
    totals = {
        "all": actions.count(),
        "completed": actions.filter(status=GrowthAction.Status.COMPLETED).count(),
        "started": actions.filter(status=GrowthAction.Status.STARTED).count(),
    }
    return render(request, "growth/action_center.html", {"actions": actions, "totals": totals})


@login_required
@require_POST
def start_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    if action.status != GrowthAction.Status.COMPLETED:
        action.status = GrowthAction.Status.STARTED
        action.started_at = timezone.now()
        action.save(update_fields=["status", "started_at"])
    return redirect(action.target_url)


@login_required
@require_POST
def complete_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    action.status = GrowthAction.Status.COMPLETED
    action.completed_at = timezone.now()
    action.save(update_fields=["status", "completed_at"])
    messages.success(request, f"'{action.title}' 작업을 완료 처리했습니다.")
    return redirect("growth:action_center")


@login_required
@require_POST
def skip_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    action.status = GrowthAction.Status.SKIPPED
    action.save(update_fields=["status"])
    return redirect("growth:action_center")
