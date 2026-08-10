import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from publishing.models import PublishingTask

from . import youtube_oauth
from .models import SocialAccount


def _youtube_callback_uri(request):
    configured = getattr(settings, "YOUTUBE_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return request.build_absolute_uri(reverse("social_channels:youtube_callback"))


@login_required
def youtube_connect(request, pk):
    account = get_object_or_404(
        SocialAccount.objects.select_related("platform"),
        pk=pk,
        user=request.user,
    )
    if account.platform.code != "youtube":
        return HttpResponseBadRequest("YouTube 계정만 연결할 수 있습니다.")

    redirect_uri = _youtube_callback_uri(request)
    if not youtube_oauth.is_configured():
        return render(
            request,
            "social_channels/youtube_connect.html",
            {"account": account, "configured": False, "redirect_uri": redirect_uri},
        )

    state = secrets.token_urlsafe(32)
    request.session["youtube_oauth_state"] = state
    request.session["youtube_oauth_account_id"] = account.pk
    request.session.modified = True

    account.connection_status = SocialAccount.ConnectionStatus.PENDING
    account.last_connection_error = ""
    account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])

    return redirect(youtube_oauth.authorization_url(redirect_uri=redirect_uri, state=state))


@login_required
def youtube_callback(request):
    account_id = request.session.pop("youtube_oauth_account_id", None)
    expected_state = request.session.pop("youtube_oauth_state", None)
    request.session.modified = True

    if not account_id:
        messages.error(request, "YouTube 연결 세션이 만료되었습니다. 채널 화면에서 다시 시작해 주세요.")
        return redirect("social_channels:account_list")

    account = get_object_or_404(
        SocialAccount.objects.select_related("platform"),
        pk=account_id,
        user=request.user,
        platform__code="youtube",
    )

    if not expected_state or request.GET.get("state") != expected_state:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = "OAuth 상태값이 일치하지 않습니다. 다시 연결해 주세요."
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    if request.GET.get("error"):
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = request.GET.get(
            "error_description",
            "YouTube 연결이 취소되거나 거부되었습니다.",
        )
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("인증 코드가 없습니다.")

    redirect_uri = _youtube_callback_uri(request)
    try:
        token_data = youtube_oauth.exchange_code(code=code, redirect_uri=redirect_uri)
        channel = youtube_oauth.fetch_my_channel(access_token=token_data["access_token"])
    except (youtube_oauth.YouTubeOAuthError, KeyError) as exc:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = str(exc)
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, f"YouTube 연결에 실패했습니다: {exc}")
        return redirect("social_channels:account_list")

    snippet = channel.get("snippet") or {}
    channel_id = str(channel.get("id") or "")
    if not channel_id:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = "YouTube 채널 ID를 확인할 수 없습니다."
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    account.external_account_id = channel_id
    account.profile_name = snippet.get("title") or account.profile_name
    account.profile_url = f"https://www.youtube.com/channel/{channel_id}"
    account.access_token = token_data["access_token"]
    account.refresh_token = token_data.get("refresh_token") or account.refresh_token
    account.token_expires_at = youtube_oauth.expiry_datetime(token_data)
    account.connected_at = timezone.now()
    account.connection_status = SocialAccount.ConnectionStatus.CONNECTED
    account.last_connection_error = ""
    account.granted_scopes = youtube_oauth.granted_scopes(token_data)
    account.save()

    PublishingTask.objects.filter(
        channel=account,
        status=PublishingTask.Status.CONNECTION_REQUIRED,
    ).update(status=PublishingTask.Status.PENDING, error_message="")

    messages.success(request, f"YouTube 채널 ‘{account.profile_name}’ 연결이 완료되었습니다.")
    return redirect("social_channels:account_list")


@login_required
@require_POST
def youtube_disconnect(request, pk):
    account = get_object_or_404(
        SocialAccount.objects.select_related("platform"),
        pk=pk,
        user=request.user,
    )
    if account.platform.code != "youtube":
        return HttpResponseBadRequest("YouTube 계정만 연결 해제할 수 있습니다.")

    account.external_account_id = ""
    account.access_token = ""
    account.refresh_token = ""
    account.token_expires_at = None
    account.connected_at = None
    account.connection_status = SocialAccount.ConnectionStatus.URL_ONLY
    account.last_connection_error = ""
    account.granted_scopes = []
    account.save()

    PublishingTask.objects.filter(
        channel=account,
        status=PublishingTask.Status.PENDING,
    ).update(
        status=PublishingTask.Status.CONNECTION_REQUIRED,
        error_message="공식 API 연결이 필요합니다.",
    )
    messages.success(request, "YouTube 연결을 해제했습니다.")
    return redirect("social_channels:account_list")
