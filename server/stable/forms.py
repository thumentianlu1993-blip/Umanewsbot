from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .models import (
    ArticleHorseLinkStatus,
    HorseProfile,
    HorseProfileCompleteness,
    HorseRaceRecord,
    HorseRaceResultStatus,
    NewsArticle,
    NewsImage,
    NewsSource,
    PushTarget,
    RaceEvent,
    RaceEventAlias,
    RaceGrade,
    RacingRegion,
    SourceLanguage,
    TermCandidate,
    TermEntry,
    TermType,
)
from .services.term_admin import serialize_aliases, sync_term_source_aliases, validate_term_payload
from .services.news_attribution import set_article_regions


HORSE_PROFILE_LOCK_CHOICES = [
    ("display_name_zh", "中文展示名"),
    ("original_name", "原始名称"),
    ("english_name", "英文名"),
    ("japanese_name", "日文名"),
    ("racing_region", "地区"),
    ("country", "国家/地区"),
    ("sex", "性别"),
    ("color", "毛色"),
    ("birth_date", "出生日期"),
    ("owner_name", "马主"),
    ("trainer_name", "练马师"),
    ("breeder_name", "生产牧场"),
    ("racing_career_status", "赛马生涯状态"),
    ("records_synced_through", "履历同步日期"),
    ("official_or_source_start_count", "来源生涯实际出赛总数"),
    ("intro", "简介"),
    ("sire_text", "父"),
    ("dam_text", "母"),
    ("sire_sire_text", "父父"),
    ("sire_dam_text", "父母"),
    ("dam_sire_text", "母父"),
    ("dam_dam_text", "母母"),
]


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
        fields = [
            "content_category",
            "attribution_locked",
            "title_zh",
            "body_zh",
            "summary_zh",
            "push_summary_zh",
            "editor_notes",
            "workflow_status",
            "status",
        ]
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


class RaceEventForm(forms.ModelForm):
    aliases_text = forms.CharField(label="别名", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = RaceEvent
        fields = [
            "year",
            "slug",
            "series_key",
            "original_name",
            "chinese_name",
            "country_region",
            "racecourse",
            "grade_text",
            "normalized_grade",
            "surface",
            "distance_text",
            "eligibility_text",
            "race_datetime",
            "timezone_name",
            "local_date",
            "local_start_time",
            "priority",
            "status",
            "visibility_status",
            "data_quality_status",
            "is_featured",
            "notes",
        ]
        widgets = {
            "eligibility_text": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 3}),
            "race_datetime": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "local_date": forms.DateInput(attrs={"type": "date"}),
            "local_start_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["normalized_grade"].choices = [("", "未设置"), *RaceGrade.choices]
        if self.instance.pk:
            self.fields["aliases_text"].initial = "\n".join(
                self.instance.aliases.filter(is_active=True).order_by("source_language", "text").values_list("text", flat=True)
            )

    def clean_aliases_text(self):
        raw = self.cleaned_data.get("aliases_text") or ""
        aliases: list[str] = []
        seen: set[str] = set()
        for item in raw.replace(";", "\n").replace("|", "\n").splitlines():
            value = item.strip()
            if value and value not in seen:
                seen.add(value)
                aliases.append(value)
        return aliases

    def save(self, commit=True):
        instance = super().save(commit=commit)
        if commit:
            aliases = self.cleaned_data.get("aliases_text") or []
            instance.aliases.update(is_active=False)
            for alias in aliases:
                RaceEventAlias.objects.update_or_create(
                    event=instance,
                    source_language="",
                    text=alias,
                    defaults={"alias_type": "alias", "source": "manual", "is_active": True},
                )
        return instance


class HorseProfileForm(forms.ModelForm):
    locked_fields = forms.MultipleChoiceField(
        label="人工锁定字段",
        required=False,
        choices=HORSE_PROFILE_LOCK_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        help_text="被锁定字段不会被外部补全候选覆盖。",
    )

    class Meta:
        model = HorseProfile
        fields = [
            "display_name_zh",
            "original_name",
            "english_name",
            "japanese_name",
            "racing_region",
            "country",
            "sex",
            "color",
            "birth_date",
            "owner_name",
            "trainer_name",
            "breeder_name",
            "racing_career_status",
            "records_synced_through",
            "official_or_source_start_count",
            "official_start_count_source",
            "official_start_count_source_url",
            "official_start_count_verified_at",
            "career_record_authority_status",
            "career_history_last_verified_at",
            "intro",
            "sire_text",
            "dam_text",
            "sire_sire_text",
            "sire_dam_text",
            "dam_sire_text",
            "dam_dam_text",
            "sire_horse_profile",
            "dam_horse_profile",
            "is_featured",
            "review_notes",
            "locked_fields",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date"}),
            "records_synced_through": forms.DateInput(attrs={"type": "date"}),
            "official_start_count_verified_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
            "career_history_last_verified_at": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local"},
            ),
            "intro": forms.Textarea(attrs={"rows": 4}),
            "review_notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "display_name_zh": "中文展示名",
            "original_name": "原始名称",
            "english_name": "英文名",
            "japanese_name": "日文名",
            "racing_region": "地区",
            "country": "国家/地区",
            "sex": "性别",
            "color": "毛色",
            "birth_date": "出生日期",
            "owner_name": "马主",
            "trainer_name": "练马师",
            "breeder_name": "生产牧场",
            "racing_career_status": "赛马生涯状态",
            "records_synced_through": "履历同步至",
            "official_or_source_start_count": "来源生涯实际出赛总数",
            "official_start_count_source": "官方总出赛数来源",
            "official_start_count_source_url": "官方总出赛数来源 URL",
            "official_start_count_verified_at": "官方总出赛数核验时间",
            "career_record_authority_status": "逐场履历权威状态",
            "career_history_last_verified_at": "生涯履历最后核验时间",
            "intro": "简介",
            "sire_text": "父",
            "dam_text": "母",
            "sire_sire_text": "父父",
            "sire_dam_text": "父母",
            "dam_sire_text": "母父",
            "dam_dam_text": "母母",
            "sire_horse_profile": "父系马匹页面",
            "dam_horse_profile": "母系马匹页面",
            "is_featured": "推荐展示",
            "review_notes": "审核备注",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["racing_region"].choices = RacingRegion.choices
        parent_queryset = HorseProfile.objects.exclude(pk=self.instance.pk).order_by("racing_region", "display_name_zh", "original_name", "id")
        self.fields["sire_horse_profile"].queryset = parent_queryset
        self.fields["dam_horse_profile"].queryset = parent_queryset
        self.fields["sire_horse_profile"].required = False
        self.fields["dam_horse_profile"].required = False
        for field_name in (
            "official_start_count_verified_at",
            "career_history_last_verified_at",
        ):
            self.fields[field_name].input_formats = [
                "%Y-%m-%dT%H:%M",
            ]
        self.fields["locked_fields"].initial = sorted((self.instance.manual_lock_flags or {}).keys())

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected = set(self.cleaned_data.get("locked_fields") or [])
        existing = instance.manual_lock_flags or {}
        instance.manual_lock_flags = {field: True for field in selected if field in dict(HORSE_PROFILE_LOCK_CHOICES)}
        for key, value in existing.items():
            if key not in dict(HORSE_PROFILE_LOCK_CHOICES) and value:
                instance.manual_lock_flags[key] = value
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class HorseRaceRecordForm(forms.ModelForm):
    class Meta:
        model = HorseRaceRecord
        fields = [
            "event",
            "race_name",
            "race_year",
            "race_date",
            "race_date_precision",
            "race_name_normalized",
            "race_region",
            "race_number",
            "grade_text",
            "normalized_grade",
            "racecourse",
            "distance_text",
            "distance_meters",
            "surface",
            "race_type_text",
            "horse_number",
            "barrier",
            "jockey_name",
            "carried_weight",
            "finish_time",
            "prize_text",
            "finish_position",
            "result_status",
            "start_status",
            "is_overseas",
            "is_major_win",
            "major_win_order",
            "source_name",
            "source_url",
        ]
        widgets = {
            "race_date": forms.DateInput(attrs={"type": "date"}),
        }
        labels = {
            "event": "关联赛事",
            "race_name": "比赛名",
            "race_year": "年份",
            "race_date": "比赛日期",
            "race_date_precision": "日期精度",
            "race_name_normalized": "规范化比赛名",
            "race_region": "举办地区",
            "race_number": "场次号",
            "grade_text": "等级文本",
            "normalized_grade": "标准等级",
            "racecourse": "马场",
            "distance_text": "距离原文",
            "distance_meters": "距离（米）",
            "surface": "场地",
            "race_type_text": "赛事类型原文",
            "horse_number": "马号",
            "barrier": "闸位",
            "jockey_name": "骑师",
            "carried_weight": "负磅",
            "finish_time": "完成时间",
            "prize_text": "奖金原文",
            "finish_position": "名次",
            "result_status": "结果",
            "start_status": "实际出赛状态",
            "is_overseas": "海外远征",
            "is_major_win": "主胜鞍",
            "major_win_order": "主胜鞍排序",
            "source_name": "来源名",
            "source_url": "来源链接",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["normalized_grade"].choices = [("", "未设置"), *RaceGrade.choices]
        self.fields["surface"].required = False
        self.fields["race_date_precision"].required = False
        self.fields["result_status"].choices = HorseRaceResultStatus.choices
        self.fields["start_status"].required = False
        self.fields["major_win_order"].required = False
        self.fields["source_url"].required = True

    def clean_major_win_order(self):
        return self.cleaned_data.get("major_win_order") or 0


class HorseArticleLinkForm(forms.Form):
    article_id = forms.IntegerField(label="文章 ID", min_value=1)
    status = forms.ChoiceField(label="状态", choices=[(ArticleHorseLinkStatus.MANUAL, "人工确认"), (ArticleHorseLinkStatus.CANDIDATE, "候选")])


class ArticleEditorForm(forms.ModelForm):
    tags_text = forms.CharField(
        label="标签",
        required=False,
        help_text="多个标签用逗号分隔，例如：赛事, 马匹, 赛后复盘",
    )
    publish_without_cover = forms.BooleanField(required=False, widget=forms.HiddenInput())
    related_regions = forms.MultipleChoiceField(
        label="关联地区",
        choices=RacingRegion.choices,
        required=False,
        help_text="文章同时属于其他地区时勾选。主地区不需要重复勾选。",
    )
    related_regions_present = forms.CharField(
        required=False,
        initial="1",
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = NewsArticle
        fields = [
            "racing_region",
            "related_regions",
            "content_category",
            "attribution_locked",
            "title_zh",
            "summary_zh",
            "body_zh",
            "source_note",
            "editor_notes",
        ]
        widgets = {
            "racing_region": forms.Select(),
            "content_category": forms.Select(),
            "title_zh": forms.TextInput(attrs={"placeholder": "请输入中文标题"}),
            "summary_zh": forms.Textarea(attrs={"rows": 4, "placeholder": "请输入中文摘要"}),
            "body_zh": forms.Textarea(attrs={"rows": 26, "placeholder": "支持普通文本和基础 Markdown 风格书写"}),
            "source_note": forms.TextInput(attrs={"placeholder": "例如：netkeiba / JRA"}),
            "editor_notes": forms.Textarea(attrs={"rows": 3, "placeholder": "给自己看的备注"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tags_text"].initial = ", ".join(self.instance.tags_json or [])
        self.fields["related_regions"].initial = [
            link.region for link in self.instance.related_region_links.all()
        ] if self.instance.pk else []
        self.fields["racing_region"].required = False
        self.fields["content_category"].required = False
        self.fields["attribution_locked"].required = False
        self.fields["related_regions"].choices = [
            (value, label) for value, label in RacingRegion.choices if value != RacingRegion.OTHER
        ]
        self.fields["racing_region"].choices = [
            (value, label) for value, label in RacingRegion.choices if value != RacingRegion.OTHER
        ]

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

    def clean_racing_region(self):
        return self.cleaned_data.get("racing_region") or self.instance.racing_region or RacingRegion.JAPAN

    def clean_content_category(self):
        return self.cleaned_data.get("content_category") or self.instance.content_category or "news"

    def clean_related_regions(self):
        if (
            self.is_bound
            and "related_regions_present" not in self.data
            and "related_regions" not in self.data
        ):
            return [link.region for link in self.instance.related_region_links.all()]
        regions = list(self.cleaned_data.get("related_regions") or [])
        primary = self.cleaned_data.get("racing_region")
        return [region for region in regions if region != primary]

    def save(self, commit=True):
        instance = super().save(commit=False)
        tags = [item.strip() for item in self.cleaned_data.get("tags_text", "").split(",") if item.strip()]
        instance.tags_json = tags
        if commit:
            instance.mark_manual_edits(["title_zh", "summary_zh", "body_zh", "source_note", "editor_notes", "tags_json"])
            instance.save()
            self.save_related_regions(instance)
        return instance

    def save_related_regions(self, instance: NewsArticle) -> None:
        set_article_regions(
            instance,
            primary_region=instance.racing_region,
            related_regions=self.cleaned_data.get("related_regions") or [],
            attribution_source="manual",
            reason="article_editor",
            evidence={"form": "ArticleEditorForm"},
            content_category=instance.content_category,
            save=True,
        )


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
        fields = [
            "term_type",
            "source_language",
            "racing_region",
            "source_ja",
            "target_zh",
            "translation_status",
            "race_grade",
            "priority",
            "is_active",
            "notes",
        ]
        widgets = {
            "source_ja": forms.TextInput(attrs={"placeholder": "例如：イクイノックス / Ascot / 香港打吡大赛"}),
            "target_zh": forms.TextInput(attrs={"placeholder": "例如：春秋分；暂无中文名的马可留空"}),
            "priority": forms.NumberInput(attrs={"placeholder": "数字越大优先级越高"}),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "备注、使用场景、特殊说明"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["term_type"].choices = TermType.choices
        self.fields["source_language"].required = False
        self.fields["translation_status"].required = False
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
            "translation_status": cleaned_data.get("translation_status"),
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
                    "translation_status": self.cleaned_data.get("translation_status"),
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
        instance.translation_status = normalized["translation_status"]
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


class HeadlineControlForm(forms.Form):
    article_id = forms.IntegerField(required=True, min_value=1)
    expected_version = forms.IntegerField(required=True, min_value=0)

    def clean_article_id(self):
        article_id = self.cleaned_data["article_id"]
        from stable.models import NewsArticle
        try:
            article = NewsArticle.objects.get(pk=article_id)
        except NewsArticle.DoesNotExist:
            raise forms.ValidationError("文章不存在。")
        from stable.services.editorial_headlines import is_headline_eligible
        if not is_headline_eligible(article):
            raise forms.ValidationError("该文章不满足头条资格。")
        return article_id
