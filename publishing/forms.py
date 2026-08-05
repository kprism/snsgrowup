from django import forms

from .models import AutomationSetting


class AutomationSettingForm(forms.ModelForm):
    class Meta:
        model = AutomationSetting
        fields = [
            "enabled",
            "min_interval_seconds",
            "max_interval_seconds",
            "use_random_delay",
            "retry_enabled",
            "use_ai",
            "auto_tags",
        ]
        labels = {
            "enabled": "자동발행 사용",
            "min_interval_seconds": "최소 간격(초)",
            "max_interval_seconds": "최대 간격(초)",
            "use_random_delay": "랜덤 간격 사용",
            "retry_enabled": "실패 시 자동 재시도",
            "use_ai": "AI 게시문 생성",
            "auto_tags": "추천 태그 자동 사용",
        }
        widgets = {
            "min_interval_seconds": forms.NumberInput(attrs={"min": 30, "step": 1}),
            "max_interval_seconds": forms.NumberInput(attrs={"min": 30, "step": 1}),
        }

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("min_interval_seconds")
        maximum = cleaned.get("max_interval_seconds")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error("max_interval_seconds", "최대 간격은 최소 간격보다 크거나 같아야 합니다.")
        return cleaned
