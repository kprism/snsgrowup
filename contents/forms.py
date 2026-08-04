from django import forms

from .models import ContentItem


class ContentItemForm(forms.ModelForm):
    class Meta:
        model = ContentItem
        fields = ("title", "body", "representative_image", "source_url")
        labels = {
            "title": "콘텐츠 제목",
            "body": "본문",
            "representative_image": "대표 이미지",
            "source_url": "참고 링크",
        }
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "SNS에 전달할 핵심 제목을 입력하세요"}),
            "body": forms.Textarea(attrs={"rows": 12, "placeholder": "콘텐츠 내용을 입력하세요"}),
            "source_url": forms.URLInput(attrs={"placeholder": "https://..."}),
        }

    def clean_title(self):
        return self.cleaned_data["title"].strip()
