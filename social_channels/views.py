from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

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
