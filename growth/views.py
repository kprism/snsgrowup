from datetime import timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contents.models import ContentItem
from social_channels.models import SocialAccount

from .ai_service import generate_growth_plan
from .models import GrowthAction


ACTION_TYPES = {value for value, _label in GrowthAction.ActionType.choices}
SUPPORTED_GROWTH_PLATFORMS = {"facebook", "instagram", "threads", "youtube"}


def _platform_search_url(platform: str, keyword: str, profile_url: str = "") -> str:
    query = quote(keyword.strip())
    compact = quote("".join(keyword.split()))
    if platform == "facebook":
        return f"https://www.facebook.com/search/top?q={query}"
    if platform == "instagram":
        return f"https://www.instagram.com/explore/tags/{compact}/"
    if platform == "threads":
        return f"https://www.threads.net/search?q={query}"
    if platform == "youtube":
        return f"https://www.youtube.com/results?search_query={query}"
    return profile_url or "https://www.facebook.com/"


def _registered_accounts(user):
    return list(
        SocialAccount.objects.filter(
            user=user,
            is_active=True,
            platform__code__in=SUPPORTED_GROWTH_PLATFORMS,
        )
        .select_related("platform")
        .order_by("platform__name", "profile_name")
    )


def _content_samples(user):
    return list(
        ContentItem.objects.filter(owner=user)
        .order_by("-created_at")
        .values("title", "body")[:15]
    )


def _daily_growth_chart(user, platform: str):
    today = timezone.localdate()
    start = today - timedelta(days=6)
    rows = (
        GrowthAction.objects.filter(
            owner=user,
            platform=platform,
            status=GrowthAction.Status.COMPLETED,
            completed_at__date__gte=start,
        )
        .annotate(day=TruncDate("completed_at"))
        .values("day")
        .annotate(total=Count("id"))
    )
    counts = {row["day"]: row["total"] for row in rows}
    maximum = max(counts.values(), default=1)
    chart = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        total = counts.get(day, 0)
        chart.append(
            {
                "date": day,
                "label": day.strftime("%m.%d"),
                "total": total,
                "height": max(8, round((total / maximum) * 100)) if total else 8,
                "is_today": day == today,
            }
        )
    return chart


def _channel_cards(user, accounts):
    today = timezone.localdate()
    cards = []
    for account in accounts:
        platform = account.platform.code
        base = GrowthAction.objects.filter(owner=user, platform=platform)
        cards.append(
            {
                "account": account,
                "platform": platform,
                "ready": base.filter(status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED]).count(),
                "completed_today": base.filter(
                    status=GrowthAction.Status.COMPLETED,
                    completed_at__date=today,
                ).count(),
            }
        )
    return cards


@login_required
def action_center(request):
    accounts = _registered_accounts(request.user)
    selected_account = None
    selected_id = request.GET.get("account") or request.session.get("growth_selected_account_id")
    if selected_id:
        selected_account = next((item for item in accounts if str(item.pk) == str(selected_id)), None)
    if not selected_account and accounts:
        selected_account = accounts[0]

    selected_platform = selected_account.platform.code if selected_account else ""
    if selected_account:
        request.session["growth_selected_account_id"] = selected_account.pk

    all_actions = GrowthAction.objects.filter(owner=request.user)
    platform_actions = all_actions.filter(platform=selected_platform) if selected_platform else all_actions.none()
    active_actions = platform_actions.filter(
        status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED]
    ).order_by("-priority_score", "id")
    history_actions = platform_actions.filter(
        status__in=[GrowthAction.Status.COMPLETED, GrowthAction.Status.SKIPPED]
    ).order_by("-completed_at", "-created_at")[:20]

    totals = {
        "all": platform_actions.count(),
        "completed": platform_actions.filter(status=GrowthAction.Status.COMPLETED).count(),
        "started": platform_actions.filter(status=GrowthAction.Status.STARTED).count(),
    }
    session_key = f"growth_{selected_platform}" if selected_platform else "growth_none"
    suggestions = request.session.get(f"{session_key}_keyword_suggestions", [])
    analysis_summary = request.session.get(f"{session_key}_analysis_summary", "")

    return render(
        request,
        "growth/action_center.html",
        {
            "accounts": accounts,
            "selected_account": selected_account,
            "selected_platform": selected_platform,
            "channel_cards": _channel_cards(request.user, accounts),
            "actions": active_actions,
            "history_actions": history_actions,
            "totals": totals,
            "suggestions": suggestions,
            "analysis_summary": analysis_summary,
            "growth_chart": _daily_growth_chart(request.user, selected_platform) if selected_platform else [],
        },
    )


@login_required
@require_POST
def generate_actions(request):
    keyword = request.POST.get("keyword", "").strip()
    account = get_object_or_404(
        SocialAccount.objects.select_related("platform"),
        pk=request.POST.get("account_id"),
        user=request.user,
        is_active=True,
        platform__code__in=SUPPORTED_GROWTH_PLATFORMS,
    )
    platform = account.platform.code

    try:
        plan = generate_growth_plan(
            profile_name=account.profile_name,
            platform_name=account.platform.name,
            content_samples=_content_samples(request.user),
            requested_keyword=keyword,
        )
    except Exception as exc:
        messages.error(request, f"AI 성장 전략 생성에 실패했습니다. 잠시 후 다시 시도해 주세요. ({exc})")
        return redirect(f"/growth/?account={account.pk}")

    selected_keyword = keyword or plan.keywords[0]
    GrowthAction.objects.filter(
        owner=request.user,
        platform=platform,
        status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED],
    ).delete()

    created = 0
    for index, item in enumerate(plan.actions):
        action_type = str(item.get("type") or "like").strip().lower()
        if action_type not in ACTION_TYPES:
            action_type = GrowthAction.ActionType.LIKE
        try:
            score = max(1, min(100, int(item.get("score", 80))))
        except (TypeError, ValueError):
            score = 80
        GrowthAction.objects.create(
            owner=request.user,
            platform=platform,
            keyword=selected_keyword[:120],
            action_type=action_type,
            title=str(item.get("title") or f"{selected_keyword} 성장 미션 {index + 1}")[:200],
            target_url=_platform_search_url(platform, selected_keyword, account.profile_url),
            target_label=f"{account.platform.name} · {selected_keyword}"[:120],
            recommendation_reason=str(item.get("reason") or "AI가 채널 콘텐츠 성향을 분석해 추천했습니다.")[:255],
            priority_score=score,
            suggested_comment=str(item.get("comment") or ""),
        )
        created += 1

    session_key = f"growth_{platform}"
    request.session[f"{session_key}_keyword_suggestions"] = plan.keywords
    request.session[f"{session_key}_analysis_summary"] = plan.summary
    request.session["growth_selected_account_id"] = account.pk
    request.session.modified = True
    messages.success(request, f"{account.platform.name} 성장 미션 {created}개를 만들었습니다.")
    return redirect(f"/growth/?account={account.pk}")


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
    return redirect(f"/growth/?platform={action.platform}")


@login_required
@require_POST
def skip_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    action.status = GrowthAction.Status.SKIPPED
    action.completed_at = timezone.now()
    action.save(update_fields=["status", "completed_at"])
    return redirect(f"/growth/?platform={action.platform}")
