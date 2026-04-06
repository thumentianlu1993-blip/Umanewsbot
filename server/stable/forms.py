from __future__ import annotations

from django import forms

from .models import NewsArticle, NewsImage, PushTarget


class NewsArticleAdminForm(forms.ModelForm):
    class Meta:
        model = NewsArticle
        fields = ["title_zh", "body_zh", "push_summary_zh", "editor_notes", "status"]
        widgets = {
            "body_zh": forms.Textarea(attrs={"rows": 16, "cols": 140}),
            "push_summary_zh": forms.Textarea(attrs={"rows": 5, "cols": 140}),
            "editor_notes": forms.Textarea(attrs={"rows": 4, "cols": 120}),
        }


class NewsImageAdminForm(forms.ModelForm):
    class Meta:
        model = NewsImage
        fields = ["caption_zh", "caption_ja", "sort_order", "local_path", "original_url"]


class PushArticleForm(forms.Form):
    targets = forms.ModelMultipleChoiceField(
        queryset=PushTarget.objects.none(),
        required=False,
        help_text="不选则默认推送到所有默认群。",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["targets"].queryset = PushTarget.objects.filter(is_active=True)
