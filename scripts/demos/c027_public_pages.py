#!/usr/bin/env python3
"""固定main的合成公开页演示：专属SQLite、内存队列、无出站网络，仅loopback。"""
from argparse import ArgumentParser
from datetime import datetime, time, timedelta
import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import types
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

SOURCE_MAIN = "6e6aded22764ebee3d6a97f2834f47d4b4baa7bb"
ROOT = Path(__file__).resolve().parents[2]


def configure(runtime):
    sys.path.insert(0, str(ROOT / "server"))
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False  # 不载入任何开发/生产.env。
    os.environ.update(DJANGO_SETTINGS_MODULE="c027_demo_settings", DB_ENGINE="sqlite",
        SQLITE_DB_PATH=str(runtime / "synthetic.sqlite3"), DEBUG="true", SECRET_KEY="c027-synthetic-local-only",
        MEDIA_STORAGE_BACKEND="local", USE_STATICFILES_MANIFEST="false", QQ_CHANNEL_ENABLED="false",
        QQ_PUSH_ENABLED="false", MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED="false",
        CELERY_BROKER_URL="memory://", CELERY_RESULT_BACKEND="cache+memory://")
    module = types.ModuleType("c027_demo_settings")
    original = importlib.import_module("app.settings")
    module.__dict__.update({k: getattr(original, k) for k in dir(original) if k.isupper()})
    module.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(runtime / "synthetic.sqlite3")}}
    module.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "c027-demo"}}
    module.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    module.STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
    module.MEDIA_ROOT = runtime / "media"
    module.STATIC_ROOT = runtime / "static"
    module.ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
    module.SECRET_KEY = "c027-synthetic-local-only"
    module.RACE_FIELD_NORMALIZED_DISPLAY_ENABLED = True
    module.RACE_EVENT_PUBLIC_CACHE_SECONDS = 0
    module.CELERY_BEAT_SCHEDULE = {}
    module.CELERY_TASK_ALWAYS_EAGER = False
    # 模型/抓取/通知的运行开关全部在独立settings里关闭；不改真实配置。
    for key in list(module.__dict__):
        if key.endswith(("_ENABLED", "_ALLOW_NETWORK")) and key not in {"RACE_FIELD_NORMALIZED_DISPLAY_ENABLED"}:
            setattr(module, key, False)
    sys.modules[module.__name__] = module
    def blocked(*args, **kwargs):
        raise RuntimeError("C027 demo outbound network is disabled")
    socket.create_connection = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    import django
    django.setup()
    from app.celery import app
    app.conf.update(broker_url="memory://", result_backend="cache+memory://", task_always_eager=False)


def seed_and_verify(runtime):
    from django.core.management import call_command
    from django.test import Client
    from django.test.utils import setup_test_environment
    from django.utils import timezone
    from stable.models import RaceEvent, NewsArticle
    from stable.services.race_information_display import event_grade_field
    call_command("migrate", interactive=False, verbosity=0)
    now = timezone.now()
    today = now.astimezone(ZoneInfo("Asia/Shanghai")).date()
    rows = [
        ("date-only", 0, "【合成演示】秋季一级赛", "japan", "Group 1", None),
        ("g2", 1, "【合成演示】二级赛", "united_kingdom", "G2", time(14, 30)),
        ("jpn1", 2, "【合成演示】泥地一级赛", "japan", "Jpn1", None),
        ("local-g1", 3, "【合成演示】香港本土一级赛", "hong_kong", "Local G1", None),
        ("g3", 4, "【合成演示】三级赛（第五场）", "france", "G3", time(21, 15)),
        ("german-g1", 6, "【合成演示】德国一级赛", "germany", "Group 1", None),
        ("outside-seven", 7, "【合成演示】七天外重点赛", "united_states", "G1", None),
    ]
    created = {}
    for slug, delta, name, region, grade, clock in rows:
        day = today + timedelta(days=delta)
        event, _ = RaceEvent.objects.get_or_create(slug="c027-" + slug, year=day.year, defaults=dict(
            chinese_name=name, original_name="SYNTHETIC " + slug, country_region=region,
            racecourse="合成演示赛场", grade_text=grade, normalized_grade="", surface="turf",
            distance_text="2000 m", local_date=day, local_start_time=clock,
            race_datetime=datetime.combine(day, clock, ZoneInfo("Asia/Shanghai")) if clock else None,
            timezone_name="Asia/Shanghai" if clock else "Europe/Berlin" if region=="germany" else "Asia/Tokyo",
            status="scheduled", visibility_status="published", priority="p1", source_refs={"synthetic_demo": True}))
        if event.local_date != day:
            raise RuntimeError("演示日期已过，请使用新的专属runtime目录，禁止复用旧日期冒充当前窗口")
        created[slug] = event
    NewsArticle.objects.get_or_create(source_site="netkeiba", source_article_id="c027-synthetic-disclaimer",
        defaults=dict(source_mode="latest", racing_region="japan", source_language="ja",
            title_ja="C027 Synthetic Demo", title_zh="合成演示｜首页与赛事日历首批成果",
            translated_title_zh="合成演示｜首页与赛事日历首批成果",
            body_ja_raw="Synthetic demo only", body_ja_normalized="Synthetic demo only",
            body_zh="本地合成演示数据，所有赛事和新闻均非真实记录。演示固定 main 的 U01/U02 页面，未部署生产。",
            translated_body_zh="本地合成演示数据，所有赛事和新闻均非真实记录。演示固定 main 的 U01/U02 页面，未部署生产。",
            summary_zh="验证今天起七天最多四场、缺时刻不造时间、等级标签与筛选一致、详情返回保留筛选。",
            translated_summary_zh="所有记录均为合成演示，QQ/抓取/通知均关闭。",
            workflow_status="published", published_at=now, published_to_web_at=now,
            source_url="https://example.invalid/c027", score_total=99, tags_json=["合成演示"]))
    setup_test_environment()
    client = Client()
    home = client.get("/")
    assert home.status_code == 200
    entries = home.context["today_races"]
    assert [row["event"].pk for row in entries] == [created[k].pk for k in ("date-only","g2","jpn1","local-g1")]
    assert entries[0]["clock_known"] is False and created["date-only"].local_start_time is None
    listing = "/races/?tab=all&grade=g1&year=" + str(today.year)
    response = client.get(listing)
    assert response.status_code == 200
    events = [e for group in response.context["groups"] for e in group["events"]]
    assert set(e.pk for e in events) == {created[k].pk for k in ("date-only","jpn1","german-g1","outside-seven")}
    assert all(event_grade_field(e).code in {"G1","JPN1","JG1"} for e in events)
    assert event_grade_field(created["local-g1"]).code == ""  # 无可信地方体系profile，禁止冒充国际G1。
    target = next(e for e in events if e.pk == created["german-g1"].pk)
    detail = client.get(target.public_list_detail_url)
    assert detail.status_code == 200
    back = detail.context["public_return_url"]
    returned = client.get(back)
    assert returned.status_code == 200
    assert returned.context["filters"]["grade"] == "g1" and returned.context["filters"]["year"] == str(today.year)
    (runtime / "verification.json").write_text(json.dumps({"source_main": SOURCE_MAIN,
        "candidate_sha": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "synthetic": True, "date_beijing": today.isoformat(), "home_card_count": len(entries),
        "home_names": [e["event"].chinese_name for e in entries], "date_only_clock_known": entries[0]["clock_known"],
        "g1_card_names": [e.chinese_name for e in events], "g1_codes": [event_grade_field(e).code for e in events],
        "detail_path": target.public_list_detail_url, "return_path": back,
        "return_filters": returned.context["filters"], "local_db": str(runtime / "synthetic.sqlite3"),
        "isolation": "SQLite/locmem cache+email+broker; outbound sockets denied; no worker or Beat"},
        ensure_ascii=False, indent=2) + "\n")
    print("C027 verified: 4 home cards, known/unknown clock, grade sets, signed return filters", flush=True)


def main():
    parser = ArgumentParser()
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    marker = runtime / "c027-synthetic-demo.json"
    if (runtime / "synthetic.sqlite3").exists() and not marker.exists():
        raise SystemExit("拒绝使用未登记的数据库")
    marker.write_text(json.dumps({"synthetic": True, "source_main": SOURCE_MAIN}))
    configure(runtime)
    seed_and_verify(runtime)
    if not args.verify_only:
        from django.core.management import call_command
        print(f"Synthetic demo only: http://127.0.0.1:{args.port}/", flush=True)
        call_command("runserver", f"127.0.0.1:{args.port}", use_reloader=False)


if __name__ == "__main__":
    main()
