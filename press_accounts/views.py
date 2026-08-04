from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from contents.models import ContentItem
from .services import collect_feed, inspect_feed


@login_required
def rss_dashboard(request):
    if request.user.account_type != "press":
        return HttpResponseForbidden("신문사 사용자만 이용할 수 있습니다.")

    profile = getattr(request.user, "press_profile", None)
    article_count = ContentItem.objects.filter(
        owner=request.user,
        source_type=ContentItem.SourceType.RSS,
    ).count()
    return render(
        request,
        "press_accounts/rss_dashboard.html",
        {"profile": profile, "article_count": article_count},
    )


@login_required
def rss_check(request):
    if request.method != "POST":
        return redirect("press_accounts:rss_dashboard")
    if request.user.account_type != "press":
        return HttpResponseForbidden("신문사 사용자만 이용할 수 있습니다.")

    profile = getattr(request.user, "press_profile", None)
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
    if request.user.account_type != "press":
        return HttpResponseForbidden("신문사 사용자만 이용할 수 있습니다.")

    profile = getattr(request.user, "press_profile", None)
    if profile is None:
        messages.error(request, "신문사 프로필이 없습니다.")
        return redirect("press_accounts:rss_dashboard")

    try:
        result = collect_feed(profile)
        messages.success(
            request,
            f"RSS 수집 완료: 신규 {result.created}건, 중복 {result.skipped}건, 제외 {result.failed}건",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("press_accounts:rss_dashboard")
