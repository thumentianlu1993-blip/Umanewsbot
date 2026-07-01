from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import NewsArticle, NewsImage, NewsSource, PushTarget, RaceGrade, RacingRegion, SourceLanguage, TermCandidate, TermEntry, TermType
from .services.term_admin import serialize_aliases, sync_term_source_aliases, validate_term_payload


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
            "racing_region",
            "source_language",
            "source_kind",
            "adapter_key",
            "source_site",
            "source_mode",
            "enabled",
            "crawl_interval_minutes",
            "production_approved",
            "effective_crawl_interval_minutes",
            "backoff_until",
            "manual_pause_reason",
            "failure_streak",
            "success_streak",
            "last_error_category",
            "allow_event_boost",
            "priority",
            "logo_url",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
            "manual_pause_reason": forms.Textarea(attrs={"rows": 3}),
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
        label="原文别名",
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
        fields = ["term_type", "source_language", "racing_region", "source_ja", "target_zh", "race_grade", "priority", "is_active", "notes"]
        widgets = {
            "source_ja": forms.TextInput(attrs={"placeholder": "例如：イクイノックス / Ascot / 香港打吡大赛"}),
            "target_zh": forms.TextInput(attrs={"placeholder": "例如：春秋分"}),
            "priority": forms.NumberInput(attrs={"placeholder": "数字越大优先级越高"}),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "备注、使用场景、特殊说明"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["term_type"].choices = TermType.choices
        self.fields["source_language"].required = False
        self.fields["source_language"].initial = self.instance.source_language or SourceLanguage.JAPANESE
        self.fields["source_language"].choices = [
            (SourceLanguage.JAPANESE, "日文"),
            (SourceLanguage.ENGLISH, "英文"),
            (SourceLanguage.CHINESE_TRADITIONAL, "繁体中文"),
        ]
        self.fields["racing_region"].required = False
        self.fields["racing_region"].choices = [("", "全局通用"), *RacingRegion.choices]
        self.fields["race_grade"].choices = [("", "未设置"), *RaceGrade.choices]
        self.fields["aliases_ja_text"].initial = serialize_aliases(self.instance.aliases_ja or [])
        self.fields["aliases_zh_text"].initial = serialize_aliases(self.instance.aliases_zh or [])

    def clean(self):
        cleaned_data = super().clean()
        payload = {
            "term_type": cleaned_data.get("term_type"),
            "source_language": cleaned_data.get("source_language"),
            "racing_region": cleaned_data.get("racing_region"),
            "source_ja": cleaned_data.get("source_ja"),
            "target_zh": cleaned_data.get("target_zh"),
            "aliases_ja": cleaned_data.get("aliases_ja_text", ""),
            "aliases_zh": cleaned_data.get("aliases_zh_text", ""),
            "race_grade": cleaned_data.get("race_grade", ""),
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
                    "source_language": self.cleaned_data.get("source_language") or SourceLanguage.JAPANESE,
                    "racing_region": self.cleaned_data.get("racing_region") or "",
                    "source_ja": self.cleaned_data["source_ja"],
                    "target_zh": self.cleaned_data["target_zh"],
                    "aliases_ja": self.cleaned_data.get("aliases_ja_text", ""),
                    "aliases_zh": self.cleaned_data.get("aliases_zh_text", ""),
                    "race_grade": self.cleaned_data.get("race_grade", ""),
                    "priority": self.cleaned_data.get("priority"),
                    "is_active": self.cleaned_data.get("is_active"),
                    "notes": self.cleaned_data.get("notes", ""),
                },
                instance_id=self.instance.pk,
            )
        instance.term_type = normalized["term_type"]
        instance.source_language = normalized["source_language"]
        instance.racing_region = normalized["racing_region"]
        instance.source_ja = normalized["source_ja"]
        instance.target_zh = normalized["target_zh"]
        instance.aliases_ja = normalized["aliases_ja"]
        instance.aliases_zh = normalized["aliases_zh"]
        instance.race_grade = normalized["race_grade"]
        instance.priority = normalized["priority"]
        instance.is_active = normalized["is_active"]
        instance.notes = normalized["notes"]
        if commit:
            instance.save()
            sync_term_source_aliases(instance, instance.source_language)
        return instance


class ArticleQuickTermForm(forms.Form):
    source_language = forms.ChoiceField(
        label="原文语言",
        choices=[
            (SourceLanguage.JAPANESE, "日文"),
            (SourceLanguage.ENGLISH, "英文"),
            (SourceLanguage.CHINESE_TRADITIONAL, "繁体中文"),
        ],
        initial=SourceLanguage.JAPANESE,
        required=False,
    )
    source_ja = forms.CharField(
        label="原文",
        max_length=80,
        strip=True,
        error_messages={
            "required": "原文不能为空，请先选择或粘贴原文片段。",
            "max_length": "原文过长，请只选择一个短词或短语。",
        },
        widget=forms.TextInput(attrs={"maxlength": 80, "placeholder": "选中原文后自动填入，也可手工粘贴"}),
    )
    term_type = forms.ChoiceField(
        label="术语类型",
        choices=TermType.choices,
        initial=TermType.HORSE,
        error_messages={"invalid_choice": "术语类型不合法。"},
    )
    target_zh = forms.CharField(
        label="中文译词",
        max_length=255,
        strip=True,
        error_messages={"required": "中文译词不能为空。"},
        widget=forms.TextInput(attrs={"placeholder": "请输入中文译法"}),
    )

    def clean_source_ja(self):
        value = (self.cleaned_data.get("source_ja") or "").strip()
        if not value:
            raise forms.ValidationError("原文不能为空，请先选择或粘贴原文片段。")
        if len(value) > 80:
            raise forms.ValidationError("原文过长，请只选择一个短词或短语。")
        if "\n" in value or "\r" in value:
            raise forms.ValidationError("原文不能包含换行，请不要选择整段正文。")
        return value

    def to_payload(self, article: NewsArticle) -> dict:
        title = article.title_ja or article.effective_title
        return {
            "term_type": self.cleaned_data["term_type"],
            "source_language": self.cleaned_data.get("source_language") or article.source_language or SourceLanguage.JAPANESE,
            "racing_region": article.racing_region or "",
            "source_ja": self.cleaned_data["source_ja"],
            "target_zh": self.cleaned_data["target_zh"],
            "aliases_ja": [],
            "aliases_zh": [],
            "race_grade": "",
            "priority": 0,
            "is_active": True,
            "notes": f"从文章 #{article.pk} 快速添加：{title}",
        }


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


class TermCandidateAcceptForm(forms.Form):
    term_type = forms.ChoiceField(label="术语类型", choices=TermType.choices)
    source_language = forms.ChoiceField(label="原文语言", choices=[
        (SourceLanguage.JAPANESE, "日文"),
        (SourceLanguage.ENGLISH, "英文"),
        (SourceLanguage.CHINESE_TRADITIONAL, "繁体中文"),
    ], required=False)
    source_ja = forms.CharField(label="原文", max_length=255)
    target_zh = forms.CharField(label="中文译词", max_length=255)
    aliases_ja_text = forms.CharField(label="原文别名", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    aliases_zh_text = forms.CharField(label="中文别名", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    priority = forms.IntegerField(label="优先级", initial=0)
    notes = forms.CharField(label="正式术语备注", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    review_notes = forms.CharField(label="审核备注", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, candidate: TermCandidate, **kwargs):
        super().__init__(*args, **kwargs)
        self.candidate = candidate
        self.fields["term_type"].choices = [
            choice for choice in TermType.choices if choice[0] in {"horse", "race", "jockey", "owner"}
        ]
        if not self.is_bound:
            self.initial.update(
                {
                    "term_type": candidate.term_type,
                    "source_language": candidate.source_language,
                    "source_ja": candidate.source_ja,
                    "target_zh": candidate.target_zh or candidate.suggested_target_zh,
                    "aliases_ja_text": serialize_aliases(candidate.aliases_ja or []),
                    "aliases_zh_text": serialize_aliases(candidate.aliases_zh or []),
                }
            )

    def clean(self):
        cleaned = super().clean()
        normalized, errors = validate_term_payload(
            {
                "term_type": cleaned.get("term_type"),
                "source_language": cleaned.get("source_language"),
                "source_ja": cleaned.get("source_ja"),
                "target_zh": cleaned.get("target_zh"),
                "aliases_ja": cleaned.get("aliases_ja_text"),
                "aliases_zh": cleaned.get("aliases_zh_text"),
                "priority": cleaned.get("priority"),
                "is_active": True,
                "notes": cleaned.get("notes"),
            }
        )
        for field, messages in errors.items():
            mapped_field = {"aliases_ja": "aliases_ja_text", "aliases_zh": "aliases_zh_text"}.get(field, field)
            for message in messages:
                self.add_error(mapped_field if mapped_field in self.fields else None, message)
        self.normalized_payload = normalized
        self.normalized_payload["review_notes"] = cleaned.get("review_notes", "")
        return cleaned


class TermCandidateMergeForm(forms.Form):
    target_candidate = forms.ModelChoiceField(label="目标候选", queryset=TermCandidate.objects.none(), required=False)
    target_term = forms.ModelChoiceField(label="目标正式术语", queryset=TermEntry.objects.none(), required=False)
    add_as_alias = forms.BooleanField(label="将候选原文加入正式术语原文别名", required=False)
    review_notes = forms.CharField(label="审核备注", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, candidate: TermCandidate, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["target_candidate"].queryset = (
            TermCandidate.objects.filter(status="pending", source_language=candidate.source_language)
            .exclude(pk=candidate.pk)
            .order_by("-last_seen_at")
        )
        self.fields["target_term"].queryset = TermEntry.objects.all().order_by("-priority", "source_ja")

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("target_candidate")) == bool(cleaned.get("target_term")):
            raise forms.ValidationError("必须且只能选择一个合并目标。")
        if cleaned.get("add_as_alias") and not cleaned.get("target_term"):
            self.add_error("add_as_alias", "只有合并到正式术语时才能添加原文别名。")
        return cleaned


class TermCandidateReviewForm(forms.Form):
    review_notes = forms.CharField(label="审核备注", required=False, widget=forms.Textarea(attrs={"rows": 3}))
