from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
import re
import subprocess
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contents.models import ContentItem
from contents.views import PREVIEW_SESSION_KEY
from publishing.models import PublishingBatch
from social_channels.models import SocialAccount

from .ai_service import generate_growth_plan
from .models import GrowthAction


ACTION_TYPES = {value for value, _label in GrowthAction.ActionType.choices}
SUPPORTED_GROWTH_PLATFORMS = {"facebook", "instagram", "threads", "youtube"}


def _platform_search_url(platform: str, keyword: str, profile_url: str = "", section: str = "top") -> str:
    query = quote(keyword.strip())
    compact = quote("".join(keyword.split()))
    if platform == "facebook":
        section_path = {"posts": "posts", "pages": "pages", "groups": "groups", "people": "people"}.get(section, "top")
        return f"https://www.facebook.com/search/{section_path}?q={query}"
    if platform == "instagram":
        return f"https://www.instagram.com/explore/tags/{compact}/"
    if platform == "threads":
        return f"https://www.threads.net/search?q={query}"
    if platform == "youtube":
        return f"https://www.youtube.com/results?search_query={query}"
    return profile_url or "https://www.facebook.com/"


def _registered_accounts(user):
    return list(
        SocialAccount.objects.filter(user=user, is_active=True, platform__code__in=SUPPORTED_GROWTH_PLATFORMS)
        .select_related("platform")
        .order_by("platform__name", "profile_name")
    )


def _content_samples(user):
    return list(ContentItem.objects.filter(owner=user).order_by("-created_at").values("title", "body")[:20])


def _keyword_tokens(value: str) -> set[str]:
    ignored = {"관련", "지역", "오늘", "정보", "게시물", "미션", "수동", "계정"}
    return {token for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", value or "") if token not in ignored}


def _relevant_contents(user, action: GrowthAction, limit: int = 8):
    action_tokens = _keyword_tokens(" ".join([action.keyword, action.title, action.recommendation_reason]))
    ranked = []
    for item in ContentItem.objects.filter(owner=user).order_by("-created_at")[:80]:
        item_tokens = _keyword_tokens(f"{item.title} {item.body[:1200]}")
        score = len(action_tokens & item_tokens)
        if action.keyword and action.keyword.replace(" ", "") in f"{item.title}{item.body}".replace(" ", ""):
            score += 4
        ranked.append((score, item.created_at, item))
    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    matched = [item for score, _created, item in ranked if score > 0]
    return (matched or [item for _score, _created, item in ranked])[:limit]


def _account_for_action(user, action: GrowthAction):
    return (
        SocialAccount.objects.filter(user=user, is_active=True, platform__code=action.platform)
        .select_related("platform")
        .first()
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
        chart.append({
            "date": day,
            "label": day.strftime("%m.%d"),
            "total": total,
            "height": max(8, round((total / maximum) * 100)) if total else 8,
            "is_today": day == today,
        })
    return chart


def _channel_cards(user, accounts):
    today = timezone.localdate()
    cards = []
    for account in accounts:
        base = GrowthAction.objects.filter(owner=user, platform=account.platform.code)
        cards.append({
            "account": account,
            "platform": account.platform.code,
            "ready": base.filter(status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED]).count(),
            "completed_today": base.filter(status=GrowthAction.Status.COMPLETED, completed_at__date=today).count(),
        })
    return cards


@login_required
def action_center(request):
    accounts = _registered_accounts(request.user)
    selected_id = request.GET.get("account") or request.session.get("growth_selected_account_id")
    selected_account = next((item for item in accounts if str(item.pk) == str(selected_id)), None) if selected_id else None
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
    return render(request, "growth/action_center.html", {
        "accounts": accounts,
        "selected_account": selected_account,
        "selected_platform": selected_platform,
        "channel_cards": _channel_cards(request.user, accounts),
        "actions": active_actions,
        "history_actions": history_actions,
        "totals": totals,
        "growth_chart": _daily_growth_chart(request.user, selected_platform) if selected_platform else [],
    })


@login_required
@require_POST
def generate_actions(request):
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
            platform_code=platform,
            content_samples=_content_samples(request.user),
        )
    except Exception as exc:
        messages.error(request, f"AI 성장 전략 생성에 실패했습니다. 잠시 후 다시 시도해 주세요. ({exc})")
        return redirect(f"/growth/?account={account.pk}")

    GrowthAction.objects.filter(
        owner=request.user,
        platform=platform,
        status__in=[GrowthAction.Status.READY, GrowthAction.Status.STARTED],
    ).delete()

    created = 0
    for index, item in enumerate(plan.actions[:5]):
        action_type = str(item.get("type") or "like").strip().lower()
        if action_type not in ACTION_TYPES:
            action_type = GrowthAction.ActionType.LIKE
        try:
            score = max(1, min(100, int(item.get("score", 80))))
        except (TypeError, ValueError):
            score = 80
        search_keyword = str(item.get("search_keyword") or item.get("title") or "").strip()[:120]
        if not search_keyword:
            continue
        GrowthAction.objects.create(
            owner=request.user,
            platform=platform,
            keyword=search_keyword,
            action_type=action_type,
            title=str(item.get("title") or f"{search_keyword} 성장 미션 {index + 1}")[:200],
            target_url=_platform_search_url(platform, search_keyword, account.profile_url),
            target_label=f"{account.platform.name} · {search_keyword}"[:120],
            recommendation_reason=str(item.get("reason") or "AI가 미션별로 적합한 검색어를 생성했습니다.")[:255],
            priority_score=score,
            suggested_comment=str(item.get("comment") or ""),
        )
        created += 1

    request.session["growth_selected_account_id"] = account.pk
    request.session.modified = True
    messages.success(request, f"{account.platform.name} 미션 {created}개와 미션별 검색키워드를 만들었습니다.")
    return redirect(f"/growth/?account={account.pk}")


@login_required
def prepare_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    account = _account_for_action(request.user, action)
    profile_url = account.profile_url if account else ""
    return render(request, "growth/action_prepare.html", {
        "action": action,
        "account": account,
        "contents": _relevant_contents(request.user, action),
        "candidate_count_available": False,
        "search_links": {
            "posts": _platform_search_url(action.platform, action.keyword, profile_url, "posts"),
            "pages": _platform_search_url(action.platform, action.keyword, profile_url, "pages"),
            "groups": _platform_search_url(action.platform, action.keyword, profile_url, "groups"),
            "people": _platform_search_url(action.platform, action.keyword, profile_url, "people"),
            "profile": profile_url or action.target_url,
        },
    })


@login_required
@require_POST
def use_content_for_post(request, pk, content_pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user, action_type=GrowthAction.ActionType.POST)
    content = get_object_or_404(ContentItem, pk=content_pk, owner=request.user)
    account = _account_for_action(request.user, action)
    if not account or action.platform != "facebook":
        messages.error(request, "현재는 Facebook 연결 계정의 공식 게시 준비만 지원합니다.")
        return redirect("growth:prepare_action", pk=action.pk)

    request.session[PREVIEW_SESSION_KEY] = {
        "content_ids": [content.pk],
        "channel_ids": [account.pk],
        "action": PublishingBatch.Action.UPLOAD,
    }
    request.session.modified = True
    if action.status != GrowthAction.Status.COMPLETED:
        action.status = GrowthAction.Status.STARTED
        action.started_at = timezone.now()
        action.save(update_fields=["status", "started_at"])
    return redirect("contents:facebook_preview")


@login_required
@require_POST
def generate_story_video(request, pk, content_pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user, action_type=GrowthAction.ActionType.STORY)
    content = get_object_or_404(ContentItem, pk=content_pk, owner=request.user)
    if not content.representative_image:
        messages.error(request, "스토리 영상 제작에는 대표이미지가 필요합니다.")
        return redirect("growth:prepare_action", pk=action.pk)

    image_path = Path(content.representative_image.path)
    if not image_path.exists():
        messages.error(request, "대표이미지 원본 파일을 찾을 수 없습니다.")
        return redirect("growth:prepare_action", pk=action.pk)

    output_dir = Path(settings.MEDIA_ROOT) / "growth_story_exports" / str(request.user.pk)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"story_{content.pk}_{uuid.uuid4().hex[:8]}.mp4"

    filter_complex = (
        "[0:v]fps=25,split=2[bgsrc][fgsrc];"
        "[bgsrc]scale=1280:2276:force_original_aspect_ratio=increase,"
        "crop=1080:1920:x='100+35*sin(t*0.9)':y='178+45*cos(t*0.7)',"
        "gblur=sigma=14[bg];"
        "[fgsrc]scale=920:1380:force_original_aspect_ratio=decrease,"
        "pad=920:1380:(ow-iw)/2:(oh-ih)/2:color=black[fg];"
        "[bg][fg]overlay=x='80+20*sin(t*1.1)':y='270+24*cos(t*0.9)':shortest=1,"
        "fade=t=in:st=0:d=0.25,fade=t=out:st=4.45:d=0.55,format=yuv420p[v];"
        "[1:a]volume=0.055,afade=t=in:st=0:d=0.25,afade=t=out:st=4.35:d=0.65[a]"
    )
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "25", "-i", str(image_path),
        "-f", "lavfi", "-i", "sine=frequency=260:sample_rate=44100:duration=5",
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]", "-t", "5", "-r", "25",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", "-shortest", str(output_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=75)
    except subprocess.TimeoutExpired:
        messages.error(request, "스토리 영상 생성 시간이 초과되었습니다. 다른 이미지를 선택해 다시 시도해 주세요.")
        return redirect("growth:prepare_action", pk=action.pk)
    except subprocess.CalledProcessError as exc:
        error_detail = (exc.stderr or exc.stdout or "FFmpeg 처리 오류").strip().splitlines()
        error_message = error_detail[-1] if error_detail else "FFmpeg 처리 오류"
        messages.error(request, f"스토리 영상 생성에 실패했습니다: {error_message[:220]}")
        return redirect("growth:prepare_action", pk=action.pk)

    if not output_path.exists() or output_path.stat().st_size < 1024:
        messages.error(request, "스토리 영상 파일이 정상적으로 생성되지 않았습니다.")
        return redirect("growth:prepare_action", pk=action.pk)

    return FileResponse(
        open(output_path, "rb"),
        as_attachment=True,
        filename=f"SNSGROWUP_story_{content.pk}.mp4",
        content_type="video/mp4",
    )


@login_required
@require_POST
def start_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    if action.status != GrowthAction.Status.COMPLETED:
        action.status = GrowthAction.Status.STARTED
        action.started_at = timezone.now()
        action.save(update_fields=["status", "started_at"])
    return redirect("growth:prepare_action", pk=action.pk)


@login_required
@require_POST
def complete_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    action.status = GrowthAction.Status.COMPLETED
    action.completed_at = timezone.now()
    action.save(update_fields=["status", "completed_at"])
    messages.success(request, f"'{action.title}' 작업을 완료 처리했습니다.")
    account = _account_for_action(request.user, action)
    return redirect(f"/growth/?account={account.pk}" if account else "/growth/")


@login_required
@require_POST
def skip_action(request, pk):
    action = get_object_or_404(GrowthAction, pk=pk, owner=request.user)
    action.status = GrowthAction.Status.SKIPPED
    action.completed_at = timezone.now()
    action.save(update_fields=["status", "completed_at"])
    account = _account_for_action(request.user, action)
    return redirect(f"/growth/?account={account.pk}" if account else "/growth/")
