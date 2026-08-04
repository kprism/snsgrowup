from django import forms

from .models import SocialAccount


class SocialAccountForm(forms.ModelForm):
    class Meta:
        model = SocialAccount
        fields = ("platform", "profile_name", "profile_url")
        labels = {
            "platform": "SNS 채널",
            "profile_name": "계정명 또는 채널명",
            "profile_url": "프로필 주소",
        }
        widgets = {
            "profile_name": forms.TextInput(attrs={"placeholder": "예: SNSGROWUP 공식 계정"}),
            "profile_url": forms.URLInput(attrs={"placeholder": "https://..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["platform"].queryset = self.fields["platform"].queryset.filter(is_active=True).order_by("name")

    def clean_profile_url(self):
        return self.cleaned_data["profile_url"].strip()
