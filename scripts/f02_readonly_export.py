"""F02 有界只读导出。导入无外部调用；原文只落 R 托管文件，stdout 仅收据。"""
from __future__ import annotations

import hashlib
import argparse
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
from urllib.parse import urlsplit, urlunsplit


class ExportError(RuntimeError):
    pass


REGIONS = ("japan", "hong_kong", "united_kingdom", "france", "united_states")
LIMITS = {"cohort": 10000, "sources": 100, "crawl_jobs": 20000, "windows": 20000,
          "decisions": 100000, "homepage_exposures": 20000}
FIELDS = {
    "cohort": "id source_config_id crawl_job_id source_site source_mode racing_region source_language first_seen_at published_at published_at_verified updated_at workflow_status crawl_status translation_status translation_error_category translation_provider translation_model translation_retry_count translated_at automation_status publish_ready_at published_to_web_at withdrawn_at duplicate_of_id score_total quality_score input_sha256 has_original_html empty_body content_bytes".split(),
    "sources": "id source_site source_mode racing_region source_language enabled production_approved deleted_at effective_crawl_interval_minutes last_crawl_status last_crawl_at last_error_category failure_streak backoff_until".split(),
    "crawl_jobs": "id source_id status started_at finished_at success_count fail_count".split(),
    "windows": "id kind racing_region source_id window_start window_end status attempt_count started_at finished_at".split(),
    "decisions": "id window_id article_id status reason score rank".split(),
    "homepage_exposures": "id article_id event_id channel slot status activated_at replaced_at".split(),
    "aggregates": "racing_region source_site source_mode workflow_status translation_status translation_error_category automation_status article_count empty_body missing_html ever_public current_public duplicate_linked".split(),
}
FILENAMES = {"cohort": "cohort_metadata.jsonl", "aggregates": "funnel_aggregates.jsonl"}
CODE_FIELDS = {"source_site", "source_mode", "racing_region", "source_language", "workflow_status", "crawl_status",
               "translation_status", "translation_error_category", "translation_provider", "translation_model",
               "automation_status", "status", "kind", "reason", "channel"}
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


def digest(value):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, default=lambda x: x.isoformat()) + "\n").encode("utf-8")


def clean_row(row, dataset):
    result = {key: row[key] for key in FIELDS[dataset] if key in row}
    for key in CODE_FIELDS & result.keys():
        value = result[key]
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{0,128}", value)):
            result[key] = "unknown"
    return result


def safe_root(output_root, observation_id):
    root = Path(output_root)
    if not root.is_absolute() or ".." in root.parts or root.parts[-3:] != ("runtime", "next_version", "F02"):
        raise ExportError("invalid_output_root")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", observation_id):
        raise ExportError("invalid_observation_id")
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ExportError("symlink_output_root")
    if (root / observation_id).exists() or (root / observation_id).is_symlink():
        raise ExportError("observation_already_exists")
    return root


def write_files(output_root, observation_id, files, receipt):
    root = safe_root(output_root, observation_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / observation_id
    directory.mkdir(mode=0o700)  # exclusive; do not replace a previous/unknown outcome
    try:
        payloads = dict(files)
        payloads["receipt.json"] = encoded(receipt)
        hashes = {}
        for name, payload in payloads.items():
            fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            hashes[name] = digest(payload)
        manifest = {"schema_version": 1, "files": hashes, "complete": True,
                    "kind": receipt["kind"], "observation_id": observation_id}
        fd = os.open(directory / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(manifest))
            stream.flush()
            os.fsync(stream.fileno())
        return {"complete": True, "kind": receipt["kind"], "counts": receipt["counts"],
                "manifest_sha256": digest(encoded(manifest)), "observation_id": observation_id}
    except BaseException:
        shutil.rmtree(directory)
        raise


def publish_metadata(snapshot, output_root, observation_id):
    observation = snapshot["observation"]
    if observation.get("read_only") != "on" or observation.get("isolation") != "repeatable read":
        raise ExportError("unsafe_transaction")
    counts = {key: snapshot["counts"].get(key) for key in LIMITS}
    for dataset, limit in LIMITS.items():
        count = counts.get(dataset)
        if type(count) is not int or not 0 <= count <= limit:
            raise ExportError("detail_budget_exceeded")
        rows = snapshot[dataset]
        if len(rows) != count or len({r["id"] for r in rows}) != count:
            raise ExportError("detail_count_mismatch")
    regions = {region: 0 for region in REGIONS}
    for row in snapshot["cohort"]:
        if row["racing_region"] not in regions or not HASH_RE.fullmatch(row["input_sha256"]):
            raise ExportError("invalid_cohort_input")
        regions[row["racing_region"]] += 1
    if regions != {r: snapshot["region_counts"].get(r, 0) for r in REGIONS}:
        raise ExportError("region_count_mismatch")
    if sum(row["article_count"] for row in snapshot["aggregates"]) != counts["cohort"]:
        raise ExportError("aggregate_count_mismatch")
    files = {FILENAMES.get(key, key + ".jsonl"): b"".join(encoded(clean_row(row, key)) for row in snapshot[key])
             for key in (*LIMITS, "aggregates")}
    safe_observation = {key: observation.get(key) for key in ("observed_at", "start", "read_only", "isolation", "release_sha", "script_sha256", "schema_sha256")}
    receipt = {"kind": "metadata", "counts": counts, "region_counts": regions, "observation": safe_observation,
               "complete": True, "effective_settings_verified": False, "holdout_status": "waiting_R_split",
               "human_verification_status": "not_reviewed", "limits": LIMITS}
    return write_files(output_root, observation_id, files, receipt)


class Redactor(HTMLParser):
    safe_tags = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol", "li", "table", "tr", "td", "th", "figcaption", "br"}
    blocked_tags = {"script", "style", "form", "input", "button", "textarea", "select", "nav", "header", "footer", "iframe", "svg"}
    void_tags = {"br", "img", "input", "meta", "link", "hr", "source", "area", "embed", "wbr", "col", "base", "param", "track"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.output = []

    def handle_starttag(self, tag, attrs):
        identifiers = " ".join(v or "" for k, v in attrs if k in {"class", "id"}).lower()
        blocked = bool(self.stack and self.stack[-1][1]) or tag in self.blocked_tags or bool(re.search(r"\b(account|login|signin|auth|tracking)\b", identifiers))
        if not blocked and tag in self.safe_tags:
            self.output.append("<" + tag + ">")
        if tag not in self.void_tags:
            self.stack.append((tag, blocked))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                blocked = self.stack[index][1]
                del self.stack[index:]
                if not blocked and tag in self.safe_tags:
                    self.output.append("</" + tag + ">")
                break

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.output.append(html.escape(data))


def redact_html(value):
    parser = Redactor()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


def publish_content(rows, selection, output_root, observation_id):
    selected = validate_selection(selection)
    if len(rows) != len(selected) or {r["id"] for r in rows} != set(selected) or len({r["id"] for r in rows}) != len(rows):
        raise ExportError("content_id_mismatch")
    total = 0
    result = []
    for row in rows:
        original = {key: row.get(key, "") or "" for key in CONTENT_FIELDS}
        if any(not isinstance(v, str) for v in original.values()):
            raise ExportError("invalid_content_type")
        byte_count = sum(len(v.encode("utf-8")) for v in original.values())
        if byte_count > 512 * 1024:
            raise ExportError("article_content_budget_exceeded")
        total += byte_count
        if total > 30 * 1024 * 1024:
            raise ExportError("total_content_budget_exceeded")
        actual = digest(original["title_ja"] + "\n" + (original["body_ja_normalized"] or original["body_ja_raw"]))
        expected = selected[row["id"]]
        updated_at = row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"]
        if actual != expected["input_sha256"] or updated_at != expected["updated_at"]:
            raise ExportError("stale_input")
        clean = {key: redact_text(value) for key, value in original.items()}
        clean["original_content_html"] = redact_text(redact_html(original["original_content_html"]))
        clean.update(id=row["id"], input_sha256=actual, updated_at=updated_at,
                     source_url=safe_url(row.get("source_url", "")), raw_content_sha256=digest(encoded(original)),
                     model_annotation_status="none", machine_validation_status="not_run", structural_validation_status="passed",
                     human_verification_status="not_reviewed", evidence_resolution="unknown")
        clean["redacted_content_sha256"] = digest(encoded(clean))
        result.append(clean)
    payload = b"".join(encoded(row) for row in result)
    if len(payload) > 30 * 1024 * 1024:
        raise ExportError("serialized_content_budget_exceeded")
    receipt = {"kind": "sealed_content", "counts": {"articles": len(rows)}, "custodian": "R",
               "source_observation_id": selection["source_observation_id"], "release_sha": selection["release_sha"],
               "selection_sha256": digest(encoded(selection)), "complete": True, "input_bytes": total,
               "holdout_status": "waiting_R_split", "redaction_limits": "No raw offsets; redacted-away blocks remain unevaluable",
               "human_verification_status": "not_reviewed"}
    return write_files(output_root, observation_id, {"content.jsonl": payload}, receipt)


CONTENT_FIELDS = "title_ja body_ja_raw body_ja_normalized original_content_html translated_title_zh translated_body_zh title_zh body_zh summary_zh".split()


def validate_selection(selection):
    if selection.get("custodian") != "R" or not re.fullmatch(r"[a-f0-9]{40}", selection.get("release_sha", "")):
        raise ExportError("invalid_custodian_or_release")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", selection.get("source_observation_id", "")):
        raise ExportError("invalid_source_observation")
    samples = selection.get("samples", [])
    if not 1 <= len(samples) <= 150:
        raise ExportError("selection_budget_exceeded")
    result = {}
    for row in samples:
        if type(row.get("id")) is not int or row["id"] <= 0 or row["id"] in result:
            raise ExportError("invalid_selection_id")
        if not HASH_RE.fullmatch(row.get("input_sha256", "")) or not isinstance(row.get("updated_at"), str):
            raise ExportError("invalid_selection_input")
        result[row["id"]] = row
    return result


def safe_url(value):
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        host = parts.hostname
        if ":" in host:
            host = "[" + host + "]"
        if parts.port:
            host += ":" + str(parts.port)
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return ""


def redact_text(value):
    value = re.sub(r"(?i)\b(?:Bearer\s+\S+|(?:api[_-]?key|password|cookie|token|secret)\s*[=:]\s*[^\s<]+)", "[REDACTED]", value)
    value = re.sub(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,254}@[A-Za-z0-9.-]{1,254}\.[A-Za-z]{2,63}", "[EMAIL]", value)
    return re.sub(r"https?://[^\s<>\"']+", lambda m: safe_url(m.group()), value)


def collect_metadata(connection, release_sha, script_sha):
    def collect(cursor, observation, schema_sha):
        start, cutoff = observation["start"], observation["observed_at"]
        args = (start, cutoff, list(REGIONS))
        cohort_where = "first_seen_at >= %s AND first_seen_at < %s AND racing_region = ANY(%s)"
        interval_where = "started_at >= %s AND started_at < %s"
        window_where = "window_start >= %s AND window_start < %s"
        decision_where = "window_id IN (SELECT id FROM public.stable_productionwindow WHERE " + window_where + " AND kind='publish')"
        exposure_where = "channel='homepage' AND article_id IN (SELECT id FROM public.stable_newsarticle WHERE " + cohort_where + ")"
        counts = query(cursor, "/* counts */ SELECT " + ",".join([
            "(SELECT count(*) FROM public.stable_newsarticle WHERE " + cohort_where + ") AS cohort",
            "(SELECT count(*) FROM public.stable_newssource) AS sources",
            "(SELECT count(*) FROM public.stable_crawljob WHERE " + interval_where + ") AS crawl_jobs",
            "(SELECT count(*) FROM public.stable_productionwindow WHERE " + window_where + " AND kind IN ('crawl','publish')) AS windows",
            "(SELECT count(*) FROM public.stable_windowcandidatedecision WHERE " + decision_where + ") AS decisions",
            "(SELECT count(*) FROM public.stable_racenewsexposure WHERE " + exposure_where + ") AS homepage_exposures",
        ]), args + (start, cutoff) * 3 + args, 1)[0]
        for key, limit in LIMITS.items():
            if type(counts[key]) is not int or not 0 <= counts[key] <= limit:
                raise ExportError("detail_budget_exceeded")
        snapshot = {"observation": {**observation, "release_sha": release_sha, "script_sha256": script_sha, "schema_sha256": schema_sha}, "counts": counts}
        regions = query(cursor, "/* region_counts */ SELECT racing_region,count(*) AS n FROM public.stable_newsarticle WHERE " + cohort_where + " GROUP BY racing_region", args, 5)
        snapshot["region_counts"] = {r["racing_region"]: r["n"] for r in regions}
        expressions = ["encode(sha256(convert_to(title_ja || E'\\n' || COALESCE(NULLIF(body_ja_normalized,''),body_ja_raw,''),'UTF8')),'hex') AS input_sha256",
                       "original_content_html <> '' AS has_original_html", "body_ja_raw = '' AND body_ja_normalized = '' AS empty_body",
                       "(" + "+".join("octet_length(" + c + ")" for c in CONTENT_FIELDS) + ") AS content_bytes"]
        snapshot["cohort"] = query(cursor, "/* cohort */ SELECT " + columns([c for c in FIELDS["cohort"] if c not in DERIVED]) + "," + ",".join(expressions) + " FROM public.stable_newsarticle WHERE " + cohort_where + " ORDER BY id", args, LIMITS["cohort"])
        specs = {
            "sources": ("stable_newssource", "TRUE", None),
            "crawl_jobs": ("stable_crawljob", interval_where, (start, cutoff)),
            "windows": ("stable_productionwindow", window_where + " AND kind IN ('crawl','publish')", (start, cutoff)),
            "decisions": ("stable_windowcandidatedecision", decision_where, (start, cutoff)),
            "homepage_exposures": ("stable_racenewsexposure", exposure_where, args),
        }
        for key, (table, where, params) in specs.items():
            snapshot[key] = query(cursor, "/* " + key + " */ SELECT " + columns(FIELDS[key]) + " FROM public." + table + " WHERE " + where + " ORDER BY id", params, LIMITS[key])
        group = "racing_region,source_site,source_mode,workflow_status,translation_status,translation_error_category,automation_status"
        aggregation = ",count(*) AS article_count,count(*) FILTER (WHERE body_ja_raw='' AND body_ja_normalized='') AS empty_body,count(*) FILTER (WHERE original_content_html='') AS missing_html,count(*) FILTER (WHERE published_to_web_at IS NOT NULL) AS ever_public,count(*) FILTER (WHERE workflow_status='published' AND published_to_web_at IS NOT NULL AND withdrawn_at IS NULL) AS current_public,count(*) FILTER (WHERE duplicate_of_id IS NOT NULL) AS duplicate_linked"
        snapshot["aggregates"] = query(cursor, "/* aggregates */ SELECT " + group + aggregation + " FROM public.stable_newsarticle WHERE " + cohort_where + " GROUP BY " + group + " ORDER BY " + group, args, LIMITS["cohort"])
        return snapshot
    return readonly(connection, collect)


DERIVED = {"input_sha256", "has_original_html", "empty_body", "content_bytes"}
TABLES = {"cohort": "stable_newsarticle", "sources": "stable_newssource", "crawl_jobs": "stable_crawljob",
          "windows": "stable_productionwindow", "decisions": "stable_windowcandidatedecision", "homepage_exposures": "stable_racenewsexposure"}
REQUIRED_SCHEMA = {TABLES[key]: set(FIELDS[key]) - DERIVED for key in LIMITS}
REQUIRED_SCHEMA["stable_newsarticle"].update(CONTENT_FIELDS + ["source_url"])
REQUIRED_SCHEMA["django_migrations"] = {"app", "name"}


def columns(names):
    # Only constants maintained above are passed here, never CLI/manifest strings.
    if any(not re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in names):
        raise ExportError("invalid_column_constant")
    return ",".join('"' + name + '"' for name in names)


def query(cursor, sql, params, limit):
    cursor.execute(sql, params)
    rows = cursor.fetchmany(limit + 1)
    if len(rows) > limit:
        raise ExportError("query_row_budget_exceeded")
    return rows


def readonly(connection, callback):
    cursor = connection.cursor()
    try:
        cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '15s'")
        cursor.execute("SET LOCAL lock_timeout = '1s'")
        cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '15s'")
        cursor.execute("SET LOCAL TIME ZONE 'UTC'")
        cursor.execute("SET LOCAL search_path = pg_catalog, public")
        observation = query(cursor, "/* observation */ SELECT transaction_timestamp() AS observed_at, transaction_timestamp()-interval '28 days' AS start, current_setting('transaction_read_only') AS read_only,current_setting('transaction_isolation') AS isolation", None, 1)[0]
        if observation["read_only"] != "on" or observation["isolation"] != "repeatable read":
            raise ExportError("unsafe_transaction")
        schema = query(cursor, "/* schema */ SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=ANY(%s) ORDER BY table_name,column_name", (list(REQUIRED_SCHEMA),), 1000)
        actual = {}
        for row in schema:
            actual.setdefault(row["table_name"], set()).add(row["column_name"])
        if any(not required <= actual.get(table, set()) for table, required in REQUIRED_SCHEMA.items()):
            raise ExportError("schema_mismatch")
        return callback(cursor, observation, digest(encoded(schema)))
    except ExportError:
        raise
    except Exception:
        raise ExportError("database_read_failed") from None  # never expose DSN/server error text
    finally:
        connection.rollback()
        cursor.close()


def connect_database():
    keys = {"host": "POSTGRES_HOST", "port": "POSTGRES_PORT", "dbname": "POSTGRES_DB", "user": "POSTGRES_USER", "password": "POSTGRES_PASSWORD"}
    if any(not os.environ.get(key) for key in keys.values()):
        raise ExportError("missing_explicit_database_environment")
    try:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(**{key: os.environ[value] for key, value in keys.items()},
                               sslmode=os.environ.get("POSTGRES_SSLMODE", "prefer"), connect_timeout=8,
                               autocommit=True, row_factory=dict_row,
                               options="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=15000")
    except Exception:
        raise ExportError("database_connection_unavailable") from None


def collect_content(connection, selection):
    selected = validate_selection(selection)
    def collect(cursor, observation, schema_sha):
        if schema_sha != selection.get("source_schema_sha256"):
            raise ExportError("source_schema_drift")
        length_sql = "+".join("octet_length(" + key + ")" for key in CONTENT_FIELDS)
        lengths = query(cursor, "/* content_sizes */ SELECT id,(" + length_sql + ") AS content_bytes FROM public.stable_newsarticle WHERE id=ANY(%s::bigint[]) ORDER BY id", (sorted(selected),), 150)
        if {r["id"] for r in lengths} != set(selected):
            raise ExportError("content_id_mismatch")
        if any(r["content_bytes"] > 512 * 1024 for r in lengths) or sum(r["content_bytes"] for r in lengths) > 30 * 1024 * 1024:
            raise ExportError("content_budget_exceeded")
        return query(cursor, "/* selected_content */ SELECT id,updated_at,source_url," + columns(CONTENT_FIELDS) + " FROM public.stable_newsarticle WHERE id=ANY(%s::bigint[]) ORDER BY id", (sorted(selected),), 150)
    return readonly(connection, collect)


def bound_selection(path, expected_sha, release_sha):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)) or path.stat().st_size > 256 * 1024 or path.stat().st_mode & 0o077:
        raise ExportError("invalid_selection_file")
    data = path.read_bytes()
    if not HASH_RE.fullmatch(expected_sha or "") or digest(data) != expected_sha:
        raise ExportError("selection_hash_mismatch")
    selection = json.loads(data)
    validate_selection(selection)
    if selection["release_sha"] != release_sha:
        raise ExportError("selection_release_mismatch")
    for key in ["source_schema_sha256", "source_metadata_manifest_sha256"]:
        if not HASH_RE.fullmatch(selection.get(key, "")):
            raise ExportError("selection_missing_source_binding")
    return selection


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["plan", "metadata", "content"], default="plan")
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--observation-id", required=True)
    parser.add_argument("--expected-script-sha256")
    parser.add_argument("--expected-release-sha")
    parser.add_argument("--resident-marker", type=Path, default=Path("/app/.umanews-release-commit"))
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--selection-sha256")
    args = parser.parse_args(argv)
    connection = None
    prior_handler = None
    try:
        safe_root(args.output_root, args.observation_id)
        script_sha = digest(Path(__file__).read_bytes())
        if args.mode == "plan":
            plan = {"schema_version": 1, "script_sha256": script_sha, "fields": FIELDS, "limits": LIMITS,
                    "statement_timeout_seconds": 15, "lock_timeout_seconds": 1, "wall_timeout_seconds": 180,
                    "cohort_days": 28, "required_schema": {k: sorted(v) for k, v in REQUIRED_SCHEMA.items()},
                    "content_limit": 150, "article_byte_limit": 512 * 1024, "total_byte_limit": 30 * 1024 * 1024,
                    "live_executed": False, "custodian": "R"}
            receipt = write_files(args.output_root, args.observation_id, {"query_contract.json": encoded(plan)}, {"kind": "plan", "counts": {"datasets": len(LIMITS)}, "complete": True})
        else:
            if script_sha != args.expected_script_sha256:
                raise ExportError("script_binding_mismatch")
            if not re.fullmatch(r"[a-f0-9]{40}", args.expected_release_sha or "") or not args.resident_marker.is_absolute():
                raise ExportError("invalid_release_binding")
            if args.resident_marker.read_text().strip() != args.expected_release_sha:
                raise ExportError("resident_release_mismatch")
            selection = None
            if args.mode == "content":
                if args.selection is None:
                    raise ExportError("missing_R_selection")
                selection = bound_selection(args.selection, args.selection_sha256, args.expected_release_sha)
            def expire(signum, frame):
                raise ExportError("wall_timeout")
            prior_handler = signal.signal(signal.SIGALRM, expire)
            signal.alarm(180)
            connection = connect_database()
            if args.mode == "metadata":
                snapshot = collect_metadata(connection, args.expected_release_sha, script_sha)
                receipt = publish_metadata(snapshot, args.output_root, args.observation_id)
            else:
                rows = collect_content(connection, selection)
                receipt = publish_content(rows, selection, args.output_root, args.observation_id)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except ExportError as exc:
        print(json.dumps({"complete": False, "error_code": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"complete": False, "error_code": "local_operation_failed"}))
        return 1
    finally:
        if prior_handler is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, prior_handler)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass  # no traceback/server credentials on cleanup


if __name__ == "__main__":
    sys.exit(main())
