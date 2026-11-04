"""D011 待运行的真实 Client GET 契约；不打印关注/CSRF token。

目标 RED 只应是合法前件之后缺失/错误 aria-label。全部数据为隔离库合成，
不 mock DTO、公开范围、producer 或 decoder；只对过期用例控制签名时钟。
"""
from html.parser import HTMLParser
import time
from unittest.mock import patch

from django.core.signing import BadSignature, SignatureExpired
from django.test import TestCase, override_settings
from django.urls import reverse

from stable.models import HorseFollow, HorseProfile, HorseProfileStatus, TermEntry
from stable.services.horse_profiles import (
    FOLLOW_COOKIE_MAX_AGE_SECONDS,
    FOLLOW_COOKIE_NAME,
    follow_horse,
    signed_follow_token,
    token_hash_from_cookie,
)


class _Forms(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.tags = []
        self.form = None
        self.button = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == "form":
            self.form = {"attrs": attrs, "inputs": [], "buttons": []}
        elif tag == "input" and self.form is not None:
            self.form["inputs"].append(attrs)
        elif tag == "button" and self.form is not None:
            self.button = {"attrs": attrs, "text": ""}

    def handle_data(self, data):
        if self.button is not None:
            self.button["text"] += data

    def handle_endtag(self, tag):
        if tag == "button" and self.button is not None:
            self.form["buttons"].append(self.button)
            self.button = None
        elif tag == "form" and self.form is not None:
            self.forms.append(self.form)
            self.form = None


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class FollowManagementButtonNameTests(TestCase):
    def setUp(self):
        self.serial = 0
        self.url = reverse("public-horse-follows")

    def _profile(self, name, *, term_name="术语备选", original="Original Runner",
                 english="", japanese="", status=HorseProfileStatus.PUBLISHED):
        self.serial += 1
        term = TermEntry(
            term_type="horse", source_language="ja", racing_region="japan",
            source_ja=f"D011 Synthetic {self.serial}", target_zh=term_name,
        )
        term.full_clean()
        term.save()
        profile = HorseProfile(
            primary_term=term, display_name_zh=name, original_name=original,
            english_name=english, japanese_name=japanese,
            racing_region="japan", review_status=status,
        )
        profile.full_clean()
        profile.save()
        return profile

    def _actor(self):
        cookie = signed_follow_token()
        token_hash = token_hash_from_cookie(cookie)
        self.assertTrue(bool(token_hash), "前件：真实 producer/decoder 必须成功")
        return cookie, token_hash

    def _follow(self, token_hash, *profiles):
        for profile in profiles:
            follow_horse(token_hash, profile, include_descendants=True)

    def _get(self, expected_profiles):
        """先核合法页面/目标/CSRF与关注无写；不比较整个cookie jar。"""
        before = list(HorseFollow.objects.order_by("pk").values())
        cookie_before = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_before = cookie_before.value if cookie_before is not None else None
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200, "前件：需要实际 GET 页面")
        after = list(HorseFollow.objects.order_by("pk").values())
        self.assertTrue(before == after, "GET 改变了 HorseFollow 行/字段/token 归属")
        self.assertFalse(FOLLOW_COOKIE_NAME in response.cookies,
                         "GET 不应设置/替换关注 cookie；CSRF cookie 不在此限制内")
        cookie_after = self.client.cookies.get(FOLLOW_COOKIE_NAME)
        cookie_after = cookie_after.value if cookie_after is not None else None
        self.assertTrue(cookie_before == cookie_after, "GET 旋转/创建了关注 cookie")
        expected_ids = {profile.pk for profile in expected_profiles}
        actual_ids = {follow.horse_profile_id for follow in response.context["follows"]}
        self.assertTrue(actual_ids == expected_ids, "前件：公开/token 可见 follow 集合不符")
        html = response.content.decode("utf-8")
        dom = _Forms(html)
        forms = [form for form in dom.forms if any(
            "unfollow" in button["attrs"].get("class", "").split()
            for button in form["buttons"]
        )]
        self.assertEqual(len(forms), len(expected_ids), "前件：取消表单数量不符")
        buttons = {}
        for profile in expected_profiles:
            action = reverse("public-horse-follow", args=[profile.pk])
            matched = [form for form in forms if form["attrs"].get("action") == action]
            self.assertEqual(len(matched), 1, "前件：表单必须按 profile ID 对应")
            form = matched[0]
            self.assertTrue(form["attrs"].get("method", "").lower() == "post",
                            "前件：原 POST 方法应保留")
            for name, expected in (("intent", "unfollow"), ("next", self.url)):
                fields = [field for field in form["inputs"] if field.get("name") == name]
                self.assertTrue(len(fields) == 1 and fields[0].get("value") == expected,
                                "前件：原 intent/next 应保持")
            csrf = [field for field in form["inputs"]
                    if field.get("name") == "csrfmiddlewaretoken"]
            self.assertTrue(len(csrf) == 1 and csrf[0].get("type") == "hidden"
                            and bool(csrf[0].get("value")),
                            "前件：保留非空 CSRF hidden；不比较跨响应 token 字节")
            candidates = [button for button in form["buttons"]
                          if "unfollow" in button["attrs"].get("class", "").split()]
            self.assertEqual(len(candidates), 1)
            button = candidates[0]
            self.assertTrue(button["attrs"].get("type") == "submit"
                            and button["text"].strip() == "取消", "原按钮动作/可见文字应保留")
            buttons[profile.pk] = button
        if not expected_profiles:
            self.assertTrue("还没有关注任何马匹" in html, "原无关注空态应保留")
        return response, dom, buttons

    def _names(self, buttons, literal_names):
        self.assertTrue(set(buttons) == set(literal_names), "前件：期望必须按表单对象绑定")
        for profile_id, literal in literal_names.items():
            label = buttons[profile_id]["attrs"].get("aria-label")
            # 不让失败消息回显表单、cookie 或 CSRF token。
            self.assertTrue(isinstance(label, str) and label.strip() == literal,
                            "业务 RED：取消按钮缺失或错误的动作+对象 aria-label")

    def test_two_public_horses_have_literal_object_names(self):
        first = self._profile("合成马甲")
        second = self._profile("合成马乙")
        cookie, actor = self._actor()
        self._follow(actor, first, second)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        _, _, buttons = self._get([first, second])
        self._names(buttons, {first.pk: "取消关注 合成马甲", second.pk: "取消关注 合成马乙"})

    def test_display_name_fallbacks_use_literal_expected_names(self):
        cases = (
            ({"term_name": "术语回退马"}, "术语回退马", "取消关注 术语回退马"),
            ({"term_name": "", "original": "Original Runner"},
             "Original Runner", "取消关注 Original Runner"),
            ({"term_name": "", "original": "", "english": "Fallback Horse"},
             "Fallback Horse", "取消关注 Fallback Horse"),
            ({"term_name": "", "original": "", "japanese": "合成カナ"},
             "合成カナ", "取消关注 合成カナ"),
        )
        cookie, actor = self._actor()
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        profiles, names = [], {}
        for changes, display, literal in cases:
            profile = self._profile("", **changes)
            self.assertTrue(profile.display_name == display, "前件：真实 display_name 回退不符")
            self._follow(actor, profile)
            profiles.append(profile)
            names[profile.pk] = literal
        _, _, buttons = self._get(profiles)
        self._names(buttons, names)

    def test_model_valid_empty_display_name_does_not_invent_identity(self):
        profile = self._profile("", term_name="", original="", english="", japanese="")
        self.assertTrue(profile.display_name == "", "前件：full_clean 合法的全空显示名")
        cookie, actor = self._actor()
        self._follow(actor, profile)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        _, _, buttons = self._get([profile])
        self._names(buttons, {profile.pk: "取消关注"})

    def test_same_name_profiles_keep_distinct_form_actions(self):
        first = self._profile("同名合成马")
        second = self._profile("同名合成马")
        self.assertNotEqual(first.pk, second.pk)
        cookie, actor = self._actor()
        self._follow(actor, first, second)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        _, _, buttons = self._get([first, second])
        self._names(buttons, {first.pk: "取消关注 同名合成马", second.pk: "取消关注 同名合成马"})

    def test_quotes_markup_and_extended_han_remain_attribute_data(self):
        profile = self._profile('合成" data-d011="注入 <svg onload=alert(1)> & 𠮷')
        cookie, actor = self._actor()
        self._follow(actor, profile)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        _, dom, buttons = self._get([profile])
        self.assertFalse(any("data-d011" in attrs or "onload" in attrs
                             for _, attrs in dom.tags), "名称不应注入额外 HTML 属性")
        self._names(buttons, {
            profile.pk: '取消关注 合成" data-d011="注入 <svg onload=alert(1)> & 𠮷',
        })

    def test_hidden_and_other_actor_profiles_do_not_leak(self):
        visible = self._profile("当前公开马")
        hidden = self._profile("隐藏合成马", status=HorseProfileStatus.HIDDEN)
        other = self._profile("其他访客马")
        cookie, actor = self._actor()
        _, other_actor = self._actor()
        self._follow(actor, visible, hidden)
        self._follow(other_actor, other)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        response, _, buttons = self._get([visible])
        html = response.content.decode("utf-8")
        self.assertTrue("隐藏合成马" not in html and "其他访客马" not in html,
                        "公开/访客隔离不应泄露名称")
        self._names(buttons, {visible.pk: "取消关注 当前公开马"})

    def test_no_follow_cookie_preserves_empty_state_and_existing_rows(self):
        profile = self._profile("非当前访客马")
        _, actor = self._actor()
        self._follow(actor, profile)
        self._get([])

    def test_invalid_follow_cookie_is_not_replaced_or_given_visibility(self):
        profile = self._profile("无效签名不可见马")
        cookie, actor = self._actor()
        self._follow(actor, profile)
        invalid = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
        with self.assertRaises(BadSignature):
            token_hash_from_cookie(invalid)
        self.client.cookies[FOLLOW_COOKIE_NAME] = invalid
        response, _, _ = self._get([])
        self.assertTrue("无效签名不可见马" not in response.content.decode("utf-8"))

    def test_expired_real_producer_cookie_is_not_replaced_or_used(self):
        profile = self._profile("过期签名不可见马")
        validation_now = time.time()
        with patch("django.core.signing.time.time",
                   return_value=validation_now - FOLLOW_COOKIE_MAX_AGE_SECONDS - 60):
            cookie, actor = self._actor()
        self._follow(actor, profile)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        with patch("django.core.signing.time.time", return_value=validation_now):
            with self.assertRaises(SignatureExpired):
                token_hash_from_cookie(cookie)
            response, _, _ = self._get([])
        self.assertTrue("过期签名不可见马" not in response.content.decode("utf-8"))

    def test_valid_cookie_without_follows_preserves_empty_state(self):
        cookie, _ = self._actor()
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        self._get([])

    def test_hidden_only_follows_remain_empty_without_name_disclosure(self):
        hidden = self._profile("仅隐藏合成马", status=HorseProfileStatus.HIDDEN)
        cookie, actor = self._actor()
        self._follow(actor, hidden)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        response, _, _ = self._get([])
        self.assertTrue("仅隐藏合成马" not in response.content.decode("utf-8"))

    def test_repeated_get_keeps_follow_state_without_comparing_csrf_bytes(self):
        profile = self._profile("重复读取合成马")
        cookie, actor = self._actor()
        self._follow(actor, profile)
        self.client.cookies[FOLLOW_COOKIE_NAME] = cookie
        # 每次各自核 CSRF 字段非空；不比较两响应的 CSRF token/cookie。
        self._get([profile])
        self._get([profile])
