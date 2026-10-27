"""读取已保存的独立事件与日志证据，不调用外网、不修改数据库。"""
import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from stable.services.news_quality_report import build_report


def read_artifact(path, sha, *, lines=False):
    if not path:
        return None
    raw = Path(path).read_bytes()
    if len(raw) > 32*1024*1024 or hashlib.sha256(raw).hexdigest() != sha:
        raise CommandError("证据文件超限或 SHA-256 不匹配")
    if lines:
        return [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    return json.loads(raw)


class Command(BaseCommand):
    help = "生成 P01 只读报告；真实周验收必须带独立事件、访问对账和窗口证据。"

    def add_arguments(self, parser):
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
        for name in ("events", "exposure", "access", "evidence"):
            parser.add_argument("--"+name)
            parser.add_argument("--"+name+"-sha256")
        parser.add_argument("--output")

    def handle(self, *args, **options):
        try:
            events = read_artifact(options["events"], options["events_sha256"]) or []
            exposures = read_artifact(options["exposure"], options["exposure_sha256"], lines=True)
            access = read_artifact(options["access"], options["access_sha256"])
            evidence = read_artifact(options["evidence"], options["evidence_sha256"])
            result = build_report(start=options["start"], end=options["end"], independent_events=events,
                exposure_records=exposures, exposure_access=access, evidence=evidence)
        except (OSError, ValueError, TypeError) as error:
            raise CommandError(str(error)) from error
        result["input_artifacts"] = {key: options[key+"_sha256"] for key in ("events", "exposure", "access", "evidence") if options[key]}
        output = json.dumps(result, ensure_ascii=False, indent=2, default=str)+"\n"
        if options["output"]:
            with Path(options["output"]).open("x", encoding="utf-8") as stream:
                stream.write(output)
        else:
            self.stdout.write(output)
