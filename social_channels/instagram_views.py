import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from publishing.models import PublishingTask

from . import facebook_oauth, instagram_oauth
from .models import SocialAccount


def _instagram_callback_uri(request):
    return request.build_absolute_uri(reverse("social_channels:instagram_callback"))


@login_required
def instagram_connect(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "instagram":
        return HttpResponseBadRequest("Instagram 계정만 연결할 수 있습니다.")

    if not facebook_oauth.is_configured():
        messages.error(request, "Meta 앱 설정이 완료되지 않았습니다.")
        return redirect("social_channels:account_list")

    state = secrets.token_urlsafe(32)
    request.session["instagram_oauth_state"] = state
    request.session["instagram_oauth_account_id"] = account.pk
    request.session.modified = True

    account.connection_status = SocialAccount.ConnectionStatus.PENDING
    account.last_connection_error = ""
    account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])

    return redirect(
        facebook_oauth.authorization_url(
            redirect_uri=_instagram_callback_uri(request),
            state=state,
        )
    )


@login_required
def instagram_callback(request):
    account_id = request.session.pop("instagram_oauth_account_id", None)
    expected_state = request.session.pop("instagram_oauth_state", None)
    request.session.modified = True

    if not account_id:
        messages.error(request, "Instagram 연결 세션이 만료되었습니다. 다시 시작해 주세요.")
        return redirect("social_channels:account_list")

    account = get_object_or_404(
        SocialAccount.objects.select_related("platform"),
        pk=account_id,
        user=request.user,
        platform__code="instagram",
    )

    if not expected_state or request.GET.get("state") != expected_state:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = "OAuth 상태값이 일치하지 않습니다. 다시 연결해 주세요."
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    if request.GET.get("error"):
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = request.GET.get("error_description", "Instagram 연결이 취소되거나 거부되었습니다.")
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("인증 코드가 없습니다.")

    try:
        token_data = facebook_oauth.exchange_code(code=code, redirect_uri=_instagram_callback_uri(request))
        user_access_token = token_data["access_token"]
        permissions = facebook_oauth.fetch_permissions(access_token=user_access_token)
        pages = facebook_oauth.fetch_managed_pages(access_token=user_access_token)
        instagram_accounts = instagram_oauth.fetch_professional_accounts(pages=pages)
    except (facebook_oauth.FacebookOAuthError, instagram_oauth.InstagramOAuthError, KeyError) as exc:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = str(exc)
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, f"Instagram 연결에 실패했습니다: {exc}")
        return redirect("social_channels:account_list")

    if not instagram_accounts:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = (
            "연결 가능한 Instagram 프로페셔널 계정을 찾지 못했습니다. "
            "Instagram 계정을 비즈니스 또는 크리에이터 계정으로 전환하고 Facebook 페이지에 연결해 주세요."
        )
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    request.session[f"instagram_accounts_{account.pk}"] = instagram_accounts
    request.session[f"instagram_permissions_{account.pk}"] = permissions
    request.session.modified = True
    return redirect("social_channels:instagram_account_select", pk=account.pk)


@login_required
def instagram_account_select(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "instagram":
        return HttpResponseBadRequest("Instagram 계정만 연결할 수 있습니다.")

    session_key = f"instagram_accounts_{account.pk}"
    candidates = request.session.get(session_key) or []
    permissions = request.session.get(f"instagram_permissions_{account.pk}") or []
    if not candidates:
        messages.warning(request, "Instagram 계정 선택 정보가 만료되었습니다. 연결을 다시 시작해 주세요.")
        return redirect("social_channels:instagram_connect", pk=account.pk)

    if request.method == "POST":
        selected_id = request.POST.get("instagram_id", "").strip()
        selected = next((item for item in candidates if item.get("id") == selected_id), None)
        if not selected:
            messages.error(request, "연결할 Instagram 계정을 선택해 주세요.")
        else:
            account.external_account_id = selected["id"]
            account.profile_name = selected.get("username") or selected.get("name") or "Instagram"
            account.profile_url = selected.get("profile_url") or "https://www.instagram.com/"
            account.access_token = selected["access_token"]
            account.token_expires_at = None
            account.connected_at = timezone.now()
            account.connection_status = SocialAccount.ConnectionStatus.CONNECTED
            account.last_connection_error = ""
            account.granted_scopes = permissions
            account.save()

            request.session.pop(session_key, None)
            request.session.pop(f"instagram_permissions_{account.pk}", None)
            request.session.modified = True

            PublishingTask.objects.filter(
                channel=account,
                status=PublishingTask.Status.CONNECTION_REQUIRED,
            ).update(status=PublishingTask.Status.PENDING, error_message="")

            messages.success(request, f"Instagram 계정 ‘{account.profile_name}’ 연결이 완료되었습니다.")
            return redirect("social_channels:account_list")

    return render(
        request,
        "social_channels/instagram_account_select.html",
        {"account": account, "candidates": candidates},
    )


@login_required
@require_POST
def instagram_disconnect(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "instagram":
        return HttpResponseBadRequest("Instagram 계정만 연결 해제할 수 있습니다.")

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
        error_message="Instagram 공식 API 연결이 필요합니다.",
    )
    messages.success(request, "Instagram 연결을 해제했습니다.")
    return redirect("social_channels:account_list")
