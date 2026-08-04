import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
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
            messages.success(request, "SNS 계정이 등록되었습니다.")
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


@login_required
def facebook_connect(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    if account.platform.code != "facebook":
        return HttpResponseBadRequest("Facebook 계정만 연결할 수 있습니다.")

    redirect_uri = request.build_absolute_uri(request.path.replace("connect/", "callback/"))
    if not facebook_oauth.is_configured():
        return render(
            request,
            "social_channels/facebook_connect.html",
            {"account": account, "configured": False, "redirect_uri": redirect_uri},
        )

    state = secrets.token_urlsafe(32)
    request.session[f"facebook_oauth_state_{account.pk}"] = state
    request.session.modified = True
    account.connection_status = SocialAccount.ConnectionStatus.PENDING
    account.last_connection_error = ""
    account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
    return redirect(facebook_oauth.authorization_url(redirect_uri=redirect_uri, state=state))


@login_required
def facebook_callback(request, pk):
    account = get_object_or_404(SocialAccount.objects.select_related("platform"), pk=pk, user=request.user)
    expected_state = request.session.pop(f"facebook_oauth_state_{account.pk}", None)
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

    redirect_uri = request.build_absolute_uri(request.path)
    try:
        token_data = facebook_oauth.exchange_code(code=code, redirect_uri=redirect_uri)
        access_token = token_data["access_token"]
        profile = facebook_oauth.fetch_profile(access_token=access_token)
    except (facebook_oauth.FacebookOAuthError, KeyError) as exc:
        account.connection_status = SocialAccount.ConnectionStatus.ERROR
        account.last_connection_error = str(exc)
        account.save(update_fields=["connection_status", "last_connection_error", "updated_at"])
        messages.error(request, f"Facebook 연결에 실패했습니다: {exc}")
        return redirect("social_channels:account_list")

    account.external_account_id = str(profile.get("id", ""))
    account.profile_name = profile.get("name") or account.profile_name
    account.access_token = access_token
    account.token_expires_at = facebook_oauth.expiry_datetime(token_data)
    account.connected_at = timezone.now()
    account.connection_status = SocialAccount.ConnectionStatus.CONNECTED
    account.last_connection_error = ""
    account.granted_scopes = []
    account.save()

    PublishingTask.objects.filter(
        channel=account,
        status=PublishingTask.Status.CONNECTION_REQUIRED,
    ).update(status=PublishingTask.Status.PENDING, error_message="")

    messages.success(request, "Facebook 계정 연결이 완료되었습니다.")
    return redirect("social_channels:account_list")


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
