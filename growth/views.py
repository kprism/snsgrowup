from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contents.models import ContentItem
from social_channels.models import SocialAccount

from .ai_service import generate_growth_plan
from .models import GrowthAction


ACTION_TYPES = {value for value, _label in GrowthAction.ActionType.choices}


def _instagram_keyword_url(keyword: str) -> str:
    tag = "".join(keyword.split())
    return f"https://www.instagram.com/explore/tags/{quote(tag)}/"


def _page_context(user):
    account = (
        SocialAccount.objects.filter(user=user, is_active=True, platform__code="facebook")
        .select_related("platform")
        .first()
    )
    contents = list(
        ContentItem.objects.filter(owner=user)
        .order_by("-created_at")
        .values("title", "body")[:15]
    )
    return account, contents


@login_required
def action_center(request):
    actions = GrowthAction.objects.filter(owner=request.user)
    totals = {
        "all": actions.count(),
        "completed": actions.filter(status=GrowthAction.Status.COMPLETED).count(),
        "started": actions.filter(status=GrowthAction.Status.STARTED).count(),
    }
    suggestions = request.session.get("growth_keyword_suggestions", [])
    analysis_summary = request.session.get("growth_analysis_summary", "")
    return render(
        request,
        "growth/action_center.html",
        {
            "actions": actions,
            "totals": totals,
            "suggestions": suggestions,
            "analysis_summary": analysis_summary,
        },
    )


@login_required
@require_POST
def generate_actions(request):
    keyword = request.POST.get("keyword", "").strip()
    account, contents = _page_context(request.user)
    profile_name = account.profile_name if account else request.user.display_name

    try:
        plan = generate_growth_plan(
            profile_name=profile_name,
            content_samples=contents,
            requested_keyword=keyword,
        )
    except Exception as exc:
        messages.error(request, f"AI 성장 전략 생성에 실패했습니다: {exc}")
        return redirect("growth:action_center")

    selected_keyword = keyword or plan.keywords[0]
    GrowthAction.objects.filter(
        owner=request.user,
        status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED],
    ).delete()

    created = 0
    for index, item in enumerate(plan.actions):
        action_type = str(item.get("type") or "like").strip().lower()
        if action_type not in ACTION_TYPES:
            action_type = GrowthAction.ActionType.LIKE
        score = item.get("score", 80)
        try:
            score = max(1, min(100, int(score)))
        except (TypeError, ValueError):
            score = 80
        GrowthAction.objects.create(
            owner=request.user,
            action_type=action_type,
            title=str(item.get("title") or f"{selected_keyword} 성장 미션 {index + 1}")[:200],
            target_url=_instagram_keyword_url(selected_keyword),
            target_label=selected_keyword[:120],
            recommendation_reason=str(item.get("reason") or "AI가 페이지 콘텐츠 성향을 분석해 추천했습니다.")[:255],
            priority_score=score,
            suggested_comment=str(item.get("comment") or ""),
        )
        created += 1

    request.session["growth_keyword_suggestions"] = plan.keywords
    request.session["growth_analysis_summary"] = plan.summary
    request.session.modified = True
    messages.success(request, f"페이지 콘텐츠 성향을 분석해 AI 성장 미션 {created}개를 만들었습니다.")
    return redirect("growth:action_center")


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
