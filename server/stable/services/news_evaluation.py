"""离线样例盘点与评估包；不会抓取、调用模型或把合成样例转成 gold。"""
import hashlib
from collections import Counter
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from stable.services.news_pipeline import REGIONS, digest
from stable.services.news_model_gateway import reservation_amount, money


def inventory_files(root, rows):
    root = Path(root).resolve()
    result = []
    for row in rows:
        path = (root/row["path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 2000000:
            raise ValueError("cached_input_path_invalid")
        raw = path.read_bytes()
        result.append({**row, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "eligible_for_gold": row.get("origin") == "cached_real" and bool(row.get("provenance")) and bool(row.get("source_url"))})
    return {"schema": "p01-cache-inventory-v1", "files": result,
        "by_region": dict(Counter(row["region"] for row in result)),
        "real_provenance_count": sum(row["eligible_for_gold"] for row in result),
        "status": "inventory_only_not_gold"}


def validate_gold(rows, *, root):
    errors = []
    if len(rows) != 100:
        errors.append("requires_100_samples")
    regions, holdout, splits, ids, event_splits = Counter(), Counter(), Counter(), set(), {}
    source_shas = set()
    source_urls = set()
    for index, row in enumerate(rows):
        sid = row.get("id")
        if not sid or sid in ids:
            errors.append(f"sample_{index}:duplicate_or_missing_id")
        ids.add(sid)
        region, split, event = row.get("region"), row.get("split"), row.get("event_key")
        regions[region] += 1
        splits[split] += 1
        if split == "holdout":
            holdout[region] += 1
        if region not in REGIONS or split not in {"development", "holdout"} or not event:
            errors.append(f"sample_{index}:split_or_event_invalid")
        if event in event_splits and event_splits[event] != split:
            errors.append(f"sample_{index}:event_leaks_across_split")
        event_splits[event] = split
        if (row.get("origin") != "cached_real" or not row.get("provenance") or urlsplit(row.get("source_url", "")).scheme not in {"https", "http"}
                or row.get("annotation_origin") != "human" or not row.get("annotator")
                or not isinstance(row.get("annotations"), dict)
                or not {"body_blocks", "entities", "facts", "editorial"} <= set(row.get("annotations", {}))):
            errors.append(f"sample_{index}:real_input_or_human_annotation_missing")
        try:
            actual = inventory_files(root, [{"path": row["path"], "region": region}])["files"][0]["sha256"]
            if actual in source_shas or row.get("source_url") in source_urls:
                errors.append(f"sample_{index}:duplicate_source")
            source_shas.add(actual)
            source_urls.add(row.get("source_url"))
            if actual != row.get("sha256"):
                errors.append(f"sample_{index}:source_sha_mismatch")
        except (KeyError, OSError, ValueError):
            errors.append(f"sample_{index}:source_unavailable")
    if splits != {"development": 75, "holdout": 25}:
        errors.append("requires_75_25_split")
    for region in REGIONS:
        if regions[region] < 20 or holdout[region] < 5:
            errors.append(f"{region}:insufficient_gold_or_holdout")
    return {"valid": not errors, "errors": errors, "counts": dict(regions), "holdout": dict(holdout),
            "manifest_sha256": digest(rows), "status": "manifest_validated_not_model_evaluated" if not errors else "inputs_incomplete"}


def evaluation_package(samples, model_candidates):
    """只形成最大请求/金额清单；价格与模型缺失时包不可执行。"""
    errors = []
    counts = Counter(row.get("region") for row in samples)
    if len(samples) != 20 or any(counts[region] != 4 for region in REGIONS):
        errors.append("requires_20_samples_four_per_region")
    if not 1 <= len(model_candidates) <= 2:
        errors.append("requires_one_or_two_model_candidates")
    if any(not row.get("eligible_for_gold") or not row.get("sha256") for row in samples):
        errors.append("real_cached_provenance_missing")
    if len({row.get("sha256") for row in samples}) != len(samples) or len({row.get("source_url") for row in samples}) != len(samples):
        errors.append("duplicate_sample_sources")
    candidates = []
    for candidate in model_candidates:
        roles = candidate.get("models", {})
        required = {"event_classify", "body_review", "entity_check", "translate_full", "fact_audit"}
        if set(roles) != required:
            errors.append("fixed_stage_model_and_prices_missing")
            continue
        ceilings = []
        for stage, spec in roles.items():
            if (not spec.get("model") or not spec.get("prompt_version") or spec.get("provider") != "openai"
                    or type(spec.get("max_input_bytes")) is not int or not 0 < spec["max_input_bytes"] <= 200000
                    or type(spec.get("max_output_tokens")) is not int or not 0 < spec["max_output_tokens"] <= 200000
                    or stage in {"entity_check", "fact_audit"} and spec.get("quality_tier") != "strong"):
                errors.append("model_policy_incomplete")
                continue
            try:
                ceilings.append(money((Decimal(spec["max_input_bytes"]+2048)*money(spec["input_per_million"])+Decimal(spec["max_output_tokens"])*money(spec["output_per_million"]))/Decimal(1000000)))
            except (KeyError, ValueError):
                errors.append("prices_missing")
        candidates.append({"name": candidate.get("name"), "models": roles, "max_requests": len(samples)*10,
            "maximum_cost": str(max(ceilings)*len(samples)*10) if len(ceilings)==5 else None,
            "currency": candidate.get("currency")})
        if not candidate.get("currency"):
            errors.append("currency_missing")
    return {"schema": "p01-small-evaluation-v1", "status": "NOT_RUN", "package_ready": not errors,
        "input_sha256": digest(samples), "samples": samples, "candidates": candidates, "errors": errors,
        "max_requests_per_sample": 10, "external_calls_executed": 0}
