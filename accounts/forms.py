from __future__ import annotations

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction

from press_accounts.models import PressProfile

from .models import User


class BaseSignupForm(UserCreationForm):
    email = forms.EmailField(label="이메일")
    display_name = forms.CharField(label="이름 또는 닉네임", max_length=80)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "username", "display_name", "password1", "password2")
        labels = {"username": "사용자 아이디"}

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("이미 사용 중인 이메일입니다.")
        return email


class GeneralSignupForm(BaseSignupForm):
    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.account_type = User.AccountType.GENERAL
        if commit:
            user.save()
        return user


class PressSignupForm(BaseSignupForm):
    press_name = forms.CharField(label="신문사명", max_length=150)
    homepage_url = forms.URLField(label="신문사 홈페이지")
    rss_url = forms.URLField(label="RSS 주소", help_text="신문기사 RSS 주소를 입력하세요.")
    auto_collect = forms.BooleanField(label="RSS 기사 자동수집", required=False, initial=True)

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.account_type = User.AccountType.PRESS
        if not commit:
            return user

        user.save()
        PressProfile.objects.create(
            user=user,
            press_name=self.cleaned_data["press_name"],
            homepage_url=self.cleaned_data["homepage_url"],
            rss_url=self.cleaned_data["rss_url"],
            rss_verified=False,
            auto_collect=self.cleaned_data["auto_collect"],
            collection_status="pending_verification",
        )
        return user
