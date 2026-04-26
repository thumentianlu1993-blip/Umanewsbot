from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import NewsArticle, NewsImage, NewsSource, PushTarget, TermEntry, TermType
from .services.term_admin import serialize_aliases, validate_term_payload


class BackendAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="用户名或邮箱",
        widget=forms.TextInput(attrs={"autofocus": True, "placeholder": "请输入用户名"}),
    )
    password = forms.CharField(
        label="密码",
        strip=False,
        widget=forms.PasswordInput(attrs={"placeholder": "请输入密码"}),
    )


class NewsArticleAdminForm(forms.ModelForm):
    class Meta:
        model = NewsArticle
        fields = ["title_zh", "body_zh", "summary_zh", "push_summary_zh", "editor_notes", "workflow_status", "status"]
        widgets = {
            "body_zh": forms.Textarea(attrs={"rows": 16, "cols": 140}),
            "summary_zh": forms.Textarea(attrs={"rows": 4, "cols": 120}),
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
        help_text="不选择则默认推送到所有默认群。",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["targets"].queryset = PushTarget.objects.filter(is_active=True)


class NewsSourceForm(forms.ModelForm):
    default_tags_text = forms.CharField(
        label="默认标签",
        required=False,
        help_text="多个标签用逗号分隔。",
    )

    class Meta:
        model = NewsSource
        fields = [
            "name",
            "homepage_url",
            "feed_url",
            "source_type",
            "language",
            "adapter_key",
            "source_site",
            "source_mode",
            "enabled",
            "crawl_interval_minutes",
            "priority",
            "logo_url",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_tags_text"].initial = ", ".join(self.instance.default_tags or [])

    def save(self, commit=True):
        instance = super().save(commit=False)
        tags = [item.strip() for item in self.cleaned_data.get("default_tags_text", "").split(",") if item.strip()]
        instance.default_tags = tags
        if commit:
            instance.save()
        return instance


class ArticleEditorForm(forms.ModelForm):
    tags_text = forms.CharField(
        label="标签",
        required=False,
        help_text="多个标签用逗号分隔，例如：赛事, 马匹, 赛后复盘",
    )
    publish_without_cover = forms.BooleanField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = NewsArticle
        fields = ["title_zh", "summary_zh", "body_zh", "source_note", "editor_notes"]
        widgets = {
            "title_zh": forms.TextInput(attrs={"placeholder": "请输入中文标题"}),
            "summary_zh": forms.Textarea(attrs={"rows": 4, "placeholder": "请输入中文摘要"}),
            "body_zh": forms.Textarea(attrs={"rows": 26, "placeholder": "支持普通文本和基础 Markdown 风格书写"}),
            "source_note": forms.TextInput(attrs={"placeholder": "例如：netkeiba / JRA"}),
            "editor_notes": forms.Textarea(attrs={"rows": 3, "placeholder": "给自己看的备注"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tags_text"].initial = ", ".join(self.instance.tags_json or [])

    def clean_title_zh(self):
        value = self.cleaned_data["title_zh"].strip()
        if not value:
            raise forms.ValidationError("标题不能为空。")
        return value

    def clean_body_zh(self):
        value = (self.cleaned_data.get("body_zh") or "").strip()
        if not value:
            raise forms.ValidationError("正文不能为空。")
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        tags = [item.strip() for item in self.cleaned_data.get("tags_text", "").split(",") if item.strip()]
        instance.tags_json = tags
        if commit:
            instance.mark_manual_edits(["title_zh", "summary_zh", "body_zh", "source_note", "editor_notes", "tags_json"])
            instance.save()
        return instance


class TermEntryForm(forms.ModelForm):
    aliases_ja_text = forms.CharField(
        label="日文别名",
        required=False,
        widget=forms.HiddenInput(),
    )
    aliases_zh_text = forms.CharField(
        label="中文别名",
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = TermEntry
        fields = ["term_type", "source_ja", "target_zh", "priority", "is_active", "notes"]
        widgets = {
            "source_ja": forms.TextInput(attrs={"placeholder": "例如：イクイノックス"}),
            "target_zh": forms.TextInput(attrs={"placeholder": "例如：春秋分"}),
            "priority": forms.NumberInput(attrs={"placeholder": "数字越大优先级越高"}),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "备注、使用场景、特殊说明"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["term_type"].choices = TermType.choices
        self.fields["aliases_ja_text"].initial = serialize_aliases(self.instance.aliases_ja or [])
        self.fields["aliases_zh_text"].initial = serialize_aliases(self.instance.aliases_zh or [])

    def clean(self):
        cleaned_data = super().clean()
        payload = {
            "term_type": cleaned_data.get("term_type"),
            "source_ja": cleaned_data.get("source_ja"),
            "target_zh": cleaned_data.get("target_zh"),
            "aliases_ja": cleaned_data.get("aliases_ja_text", ""),
            "aliases_zh": cleaned_data.get("aliases_zh_text", ""),
            "priority": cleaned_data.get("priority"),
            "is_active": cleaned_data.get("is_active"),
            "notes": cleaned_data.get("notes", ""),
        }
        normalized, field_errors = validate_term_payload(payload, instance_id=self.instance.pk)
        for field, errors in field_errors.items():
            for error in errors:
                self.add_error(field, error)
        if not field_errors:
            cleaned_data["aliases_ja_text"] = serialize_aliases(normalized["aliases_ja"])
            cleaned_data["aliases_zh_text"] = serialize_aliases(normalized["aliases_zh"])
            self._normalized_payload = normalized
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        normalized = getattr(self, "_normalized_payload", None)
        if normalized is None:
            normalized, _ = validate_term_payload(
                {
                    "term_type": self.cleaned_data["term_type"],
                    "source_ja": self.cleaned_data["source_ja"],
                    "target_zh": self.cleaned_data["target_zh"],
                    "aliases_ja": self.cleaned_data.get("aliases_ja_text", ""),
                    "aliases_zh": self.cleaned_data.get("aliases_zh_text", ""),
                    "priority": self.cleaned_data.get("priority"),
                    "is_active": self.cleaned_data.get("is_active"),
                    "notes": self.cleaned_data.get("notes", ""),
                },
                instance_id=self.instance.pk,
            )
        instance.term_type = normalized["term_type"]
        instance.source_ja = normalized["source_ja"]
        instance.target_zh = normalized["target_zh"]
        instance.aliases_ja = normalized["aliases_ja"]
        instance.aliases_zh = normalized["aliases_zh"]
        instance.priority = normalized["priority"]
        instance.is_active = normalized["is_active"]
        instance.notes = normalized["notes"]
        if commit:
            instance.save()
        return instance


class TermImportForm(forms.Form):
    import_mode = forms.ChoiceField(
        label="导入模式",
        choices=[("create", "新增模式"), ("upsert", "覆盖更新模式")],
        initial="create",
    )
    csv_file = forms.FileField(label="CSV 文件", required=False)
    csv_text = forms.CharField(
        label="CSV 文本",
        required=False,
        widget=forms.Textarea(attrs={"rows": 10, "placeholder": "可直接粘贴 CSV 内容"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        csv_file = cleaned_data.get("csv_file")
        csv_text = (cleaned_data.get("csv_text") or "").strip()
        if not csv_file and not csv_text:
            raise forms.ValidationError("请上传 CSV 文件，或直接粘贴 CSV 内容。")
        return cleaned_data
