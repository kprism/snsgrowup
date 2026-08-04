from celery.result import AsyncResult
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from contents.models import ContentItem
from .services import inspect_feed
from .tasks import collect_rss_task


RSS_TASK_SESSION_KEY = "active_rss_collect_task_id"


def _press_profile_or_forbidden(request):
    if request.user.account_type != "press":
        return None, HttpResponseForbidden("신문사 사용자만 이용할 수 있습니다.")
    return getattr(request.user, "press_profile", None), None


@login_required
def rss_dashboard(request):
    profile, forbidden = _press_profile_or_forbidden(request)
    if forbidden:
        return forbidden

    article_count = ContentItem.objects.filter(
        owner=request.user,
        source_type=ContentItem.SourceType.RSS,
    ).count()
    return render(
        request,
        "press_accounts/rss_dashboard.html",
        {
            "profile": profile,
            "article_count": article_count,
            "active_task_id": request.session.get(RSS_TASK_SESSION_KEY, ""),
        },
    )


@login_required
def rss_check(request):
    if request.method != "POST":
        return redirect("press_accounts:rss_dashboard")
    profile, forbidden = _press_profile_or_forbidden(request)
    if forbidden:
        return forbidden
    if profile is None:
        messages.error(request, "신문사 프로필이 없습니다.")
        return redirect("press_accounts:rss_dashboard")

    try:
        info = inspect_feed(profile)
        profile.rss_verified = True
        profile.collection_status = "verified"
        profile.save(update_fields=["rss_verified", "collection_status"])
        messages.success(
            request,
            f"RSS 연결 확인 완료: {info['title'] or profile.press_name}, 현재 {info['entry_count']}건",
        )
    except ValueError as exc:
        profile.rss_verified = False
        profile.collection_status = "failed"
        profile.save(update_fields=["rss_verified", "collection_status"])
        messages.error(request, str(exc))
    return redirect("press_accounts:rss_dashboard")


@login_required
def rss_collect(request):
    if request.method != "POST":
        return redirect("press_accounts:rss_dashboard")
    profile, forbidden = _press_profile_or_forbidden(request)
    if forbidden:
        return forbidden
    if profile is None:
        return JsonResponse({"ok": False, "message": "신문사 프로필이 없습니다."}, status=400)

    active_task_id = request.session.get(RSS_TASK_SESSION_KEY)
    if active_task_id:
        active = AsyncResult(active_task_id)
        if active.state not in {"SUCCESS", "FAILURE", "REVOKED"}:
            return JsonResponse({"ok": True, "task_id": active_task_id, "already_running": True})

    task = collect_rss_task.delay(profile.pk, request.user.pk)
    request.session[RSS_TASK_SESSION_KEY] = task.id
    request.session.modified = True
    return JsonResponse({"ok": True, "task_id": task.id, "already_running": False})


@login_required
def rss_collect_status(request, task_id):
    profile, forbidden = _press_profile_or_forbidden(request)
    if forbidden:
        return forbidden
    session_task_id = request.session.get(RSS_TASK_SESSION_KEY)
    if not session_task_id or session_task_id != task_id:
        return JsonResponse({"ok": False, "message": "조회할 수 없는 작업입니다."}, status=404)

    result = AsyncResult(task_id)
    payload = result.info if isinstance(result.info, dict) else {}
    response = {
        "ok": True,
        "task_id": task_id,
        "state": result.state,
        "current": payload.get("current", 0),
        "total": payload.get("total", 0),
        "percent": payload.get("percent", 0),
        "message": payload.get("message", "작업을 준비하고 있습니다."),
    }

    if result.state == "SUCCESS":
        response.update(result.result or {})
        response["article_count"] = ContentItem.objects.filter(
            owner=request.user,
            source_type=ContentItem.SourceType.RSS,
        ).count()
        request.session.pop(RSS_TASK_SESSION_KEY, None)
        request.session.modified = True
    elif result.state == "FAILURE":
        response["message"] = "RSS 수집에 실패했습니다. 작업 로그를 확인해 주세요."
        request.session.pop(RSS_TASK_SESSION_KEY, None)
        request.session.modified = True

    return JsonResponse(response)
