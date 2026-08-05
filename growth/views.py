from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import GrowthAction


def _instagram_keyword_url(keyword: str) -> str:
    tag = "".join(keyword.split()).lstrip("#")
    return f"https://www.instagram.com/explore/tags/{quote(tag)}/"


def _create_instagram_actions(*, owner, keyword: str) -> int:
    target_url = _instagram_keyword_url(keyword)
    GrowthAction.objects.filter(
        owner=owner,
        status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED, GrowthAction.Status.SKIPPED],
    ).delete()

    specs = [
        {
            "action_type": GrowthAction.ActionType.POST,
            "title": f"'{keyword}' 관련 게시물 1건 발행",
            "priority_score": 100,
            "recommendation_reason": "먼저 내 계정의 주제 신호를 만든 뒤 관련 계정과 상호작용하면 방문 전환을 측정하기 쉽습니다.",
        },
        {
            "action_type": GrowthAction.ActionType.COMMENT,
            "title": f"'{keyword}' 상위 게시물 3건에 진짜 의견 남기기",
            "priority_score": 96,
            "recommendation_reason": "내용과 직접 연결된 구체적인 댓글은 단순 좋아요보다 프로필 방문 가능성이 높습니다.",
            "suggested_comment": "게시물의 구체적인 내용을 한 가지 언급하고, 내 경험이나 질문을 한 문장 덧붙이세요. 같은 문구를 반복 복사하지 마세요.",
        },
        {
            "action_type": GrowthAction.ActionType.LIKE,
            "title": f"'{keyword}' 최근 게시물 8건 살펴보고 좋아요",
            "priority_score": 90,
            "recommendation_reason": "최근에도 꾸준히 활동하며 댓글에 반응하는 계정을 먼저 선택하세요. 무작위 연속 클릭은 피합니다.",
        },
        {
            "action_type": GrowthAction.ActionType.STORY,
            "title": f"'{keyword}' 관련 활동 계정 스토리 5건 보기",
            "priority_score": 84,
            "recommendation_reason": "최근 게시와 스토리가 모두 활성화된 계정은 현재 접속 가능성이 상대적으로 높습니다.",
        },
        {
            "action_type": GrowthAction.ActionType.FOLLOW,
            "title": f"'{keyword}' 관련성이 높은 계정 1명 팔로우 검토",
            "priority_score": 76,
            "recommendation_reason": "최근 활동, 주제 일치, 실제 댓글 교류가 확인되는 계정만 선택하세요. 팔로우는 자동이 아니라 최종 확인 후 직접 수행합니다.",
        },
    ]

    actions = [
        GrowthAction(
            owner=owner,
            platform="instagram",
            keyword=keyword,
            target_url=target_url,
            target_label=f"Instagram #{keyword}",
            status=GrowthAction.Status.READY,
            **spec,
        )
        for spec in specs
    ]
    GrowthAction.objects.bulk_create(actions)
    return len(actions)


@login_required
def action_center(request):
    if request.method == "POST" and request.POST.get("command") == "generate":
        keyword = request.POST.get("keyword", "").strip()
        if not keyword:
            messages.error(request, "성장할 주제 또는 키워드를 입력해 주세요.")
        elif len(keyword) > 120:
            messages.error(request, "키워드는 120자 이하로 입력해 주세요.")
        else:
            count = _create_instagram_actions(owner=request.user, keyword=keyword)
            messages.success(request, f"'{keyword}' 기준 Instagram 성장 액션 {count}건을 만들었습니다.")
        return redirect("growth:action_center")

    actions = GrowthAction.objects.filter(owner=request.user)
    totals = {
        "all": actions.count(),
        "completed": actions.filter(status=GrowthAction.Status.COMPLETED).count(),
        "started": actions.filter(status=GrowthAction.Status.STARTED).count(),
    }
    active_keyword = actions.exclude(keyword="").values_list("keyword", flat=True).first() or ""
    return render(
        request,
        "growth/action_center.html",
        {"actions": actions, "totals": totals, "active_keyword": active_keyword},
    )


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
