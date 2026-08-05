import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from publishing.models import PublishingTask

from . import facebook_oauth
from .forms import SocialAccountForm
from .models import SocialAccount


@login_required
def account_list(request):
    accounts = request.user.social_accounts.select_related("platform").order_by("platform__name", "profile_name")
    return render(request, "social_channels/account_list.html", {"accounts": accounts})


@login_required
def account_create(request):
    if request.method == "POST":
        form = SocialAccountForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.save()

            platform_code = account.platform.code
            if platform_code == "instagram":
                messages.success(request, "Instagram 계정이 등록되었습니다. 이제 공식 API 연결을 진행합니다.")
                return redirect("social_channels:instagram_connect", pk=account.pk)
            if platform_code == "facebook":
                messages.success(request, "Facebook 계정이 등록되었습니다. 이제 공식 API 연결을 진행합니다.")
                return redirect("social_channels:facebook_connect", pk=account.pk)

            messages.success(request, "SNS 계정이 등록되었습니다. 채널 목록에서 다음 연결 단계를 진행해 주세요.")
            return redirect("social_channels:account_list")
    else:
        form = SocialAccountForm()
    return render(request, "social_channels/account_form.html", {"form": form})


@login_required
def account_update(request, pk):
    account = get_object_or_404(SocialAccount, pk=pk, user=request.user)
    if request.method == "POST":
        form = SocialAccountForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, "SNS 계정 정보가 수정되었습니다.")
            return redirect("social_channels:account_list")
    else:
        form = SocialAccountForm(instance=account)
    return render(request, "social_channels/account_form.html", {"form": form, "account": account})


@login_required
def account_delete(request, pk):
    account = get_object_or_404(SocialAccount, pk=pk, user=request.user)
    if request.method == "POST":
        account.delete()
        messages.success(request, "SNS 계정이 삭제되었습니다.")
        return redirect("social_channels:account_list")
    return render(request, "social_channels/account_confirm_delete.html", {"account": account})


def _facebook_callback_uri(request):
    return request.build_absolute_uri(reverse("social_channels:facebook_callback"))


@login_required
def facebook_connect(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "facebook":
        return HttpResponseBadRequest("Facebook 계정만 연결할 수 있습니다.")

    redirect_uri = _facebook_callback_uri(request)
    if not facebook_oauth.is_configured():
        return render(
            request,
            "social_channels/facebook_connect.html",
            {"account": account, "configured": False, "redirect_uri": redirect_uri},
        )

    state = secrets.token_urlsafe(32)
    request.session["facebook_oauth_state"] = state
    request.session["facebook_oauth_account_id"] = account.pk
    request.session.modified = True

    account.connection_status = SocialAccount.ConnectionStatus.PENDING
    account.last_connection_error = ""
    account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
    return redirect(facebook_oauth.authorization_url(redirect_uri=redirect_uri, state=state))


@login_required
def facebook_callback(request):
    account_id = request.session.pop("facebook_oauth_account_id", None)
    expected_state = request.session.pop("facebook_oauth_state", None)
    request.session.modified = True

    if not account_id:
        messages.error(request, "Facebook 연결 세션이 만료되었습니다. 채널 화면에서 다시 시작해 주세요.")
        return redirect("social_channels:account_list")

    account = get_object_or_404(
        SocialAccount.objects.select_related("platform"),
        pk=account_id,
        user=request.user,
        platform__code="facebook",
    )

    if not expected_state or request.GET.get("state") != expected_state:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = "OAuth 상태값이 일치하지 않습니다. 다시 연결해 주세요."
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    if request.GET.get("error"):
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = request.GET.get("error_description", "Facebook 연결이 취소되거나 거부되었습니다.")
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("인증 코드가 없습니다.")

    redirect_uri = _facebook_callback_uri(request)
    try:
        token_data = facebook_oauth.exchange_code(code=code, redirect_uri=redirect_uri)
        user_access_token = token_data["access_token"]
        profile = facebook_oauth.fetch_profile(access_token=user_access_token)
        permissions = facebook_oauth.fetch_permissions(access_token=user_access_token)
        pages = facebook_oauth.fetch_managed_pages(access_token=user_access_token)
    except (facebook_oauth.FacebookOAuthError, KeyError) as exc:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = str(exc)
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, f"Facebook 연결에 실패했습니다: {exc}")
        return redirect("social_channels:account_list")

    expires_at = facebook_oauth.expiry_datetime(token_data)
    request.session[f"facebook_pages_{account.pk}"] = pages
    request.session[f"facebook_profile_{account.pk}"] = {
        "id": str(profile.get("id", "")),
        "name": str(profile.get("name", "")),
        "permissions": permissions,
        "expires_at": expires_at.isoformat() if expires_at else "",
    }
    request.session.modified = True

    if not pages:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = (
            "관리 가능한 Facebook 페이지를 찾지 못했습니다. "
            "페이지 관리자 권한과 pages_show_list 권한을 확인해 주세요."
        )
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, account.last_connection_error)
        return redirect("social_channels:account_list")

    return redirect("social_channels:facebook_page_select", pk=account.pk)


@login_required
def facebook_page_select(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "facebook":
        return HttpResponseBadRequest("Facebook 계정만 연결할 수 있습니다.")

    session_key = f"facebook_pages_{account.pk}"
    pages = request.session.get(session_key) or []
    profile = request.session.get(f"facebook_profile_{account.pk}") or {}
    if not pages:
        messages.warning(request, "페이지 선택 정보가 만료되었습니다. Facebook 연결을 다시 시작해 주세요.")
        return redirect("social_channels:facebook_connect", pk=account.pk)

    if request.method == "POST":
        selected_id = request.POST.get("page_id", "").strip()
        selected = next((page for page in pages if page.get("id") == selected_id), None)
        if not selected:
            messages.error(request, "연결할 Facebook 페이지를 선택해 주세요.")
        else:
            account.external_account_id = selected["id"]
            account.profile_name = selected["name"]
            account.profile_url = selected.get("link") or f"https://www.facebook.com/{selected['id']}"
            account.access_token = selected["access_token"]
            account.token_expires_at = None
            account.connected_at = timezone.now()
            account.connection_status = SocialAccount.ConnectionStatus.CONNECTED
            account.last_connection_error = ""
            account.granted_scopes = profile.get("permissions") or []
            account.save()

            request.session.pop(session_key, None)
            request.session.pop(f"facebook_profile_{account.pk}", None)
            request.session.modified = True

            PublishingTask.objects.filter(
                channel=account,
                status=PublishingTask.Status.CONNECTION_REQUIRED,
            ).update(status=PublishingTask.Status.PENDING, error_message="")

            messages.success(request, f"Facebook 페이지 ‘{account.profile_name}’ 연결이 완료되었습니다.")
            return redirect("social_channels:account_list")

    return render(
        request,
        "social_channels/facebook_page_select.html",
        {"account": account, "pages": pages, "facebook_profile": profile},
    )


@login_required
@require_POST
def facebook_disconnect(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "facebook":
        return HttpResponseBadRequest("Facebook 계정만 연결 해제할 수 있습니다.")

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
    messages.success(request, "Facebook 연결을 해제했습니다.")
    return redirect("social_channels:account_list")
