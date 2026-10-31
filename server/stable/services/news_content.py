"""全文边界、实体 occurrence、占位恢复与语义审校；模型输出只作为数据。"""
from __future__ import annotations

import re
from copy import deepcopy

from bs4 import BeautifulSoup, NavigableString, Tag, Comment, CData
from stable.services.article_content import _STRUCTURED_NOISE_SELECTORS, _SCMP_STRUCTURED_NOISE_SELECTORS, scmp_body_access_restricted
from stable.services.news_numeric_equivalence import audit_equivalent_numbers, numeric_surface, numeric_tokens
from stable.services.news_pipeline import digest

BODY_SELECTORS = {
    "netkeiba": [".News_Txt"], "jra": [".news_body"],
    "sponichi": ["[data-component='article-body']"],
    "hkjc_news": [".horses-racing-news-content"],
    "scmp_racing": [".article-body"],
    "sporting_life": ["[class*='Article__ArticleBody']", "article .article-body"],
    "bha": [".article-body"], "sky_sports_racing": [".sdc-article-body"],
    "france_galop_news": [".field--name-body", ".field-name-body"],
    "tdn": ["span[itemprop='articleBody']", ".entry-content"],
    "tdn_france": ["span[itemprop='articleBody']", ".entry-content"],
    "horse_racing_nation": [".article-body"],
}
AUDIT_CHECKS = frozenset({"names", "numbers_units", "dates", "placings", "negation", "modality", "attribution", "completeness", "unsupported_claims"})
TOKEN_RE = re.compile(r"__P01_ENTITY_\d{3}__")
BLOCK_TAGS = frozenset({"p", "blockquote", "table", "ul", "ol", "h2", "h3", "h4", "h5", "figcaption", "pre"})


class ContentBlocked(ValueError):
    pass


def model_schema(function):
    """合法JSON的错误字段类型也属于内容拒绝，不能逃逸成调度器异常。"""
    from functools import wraps
    @wraps(function)
    def checked(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ContentBlocked:
            raise
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as error:
            raise ContentBlocked("model_schema_invalid:" + type(error).__name__) from error
    return checked


def bounded_json(value, depth=0, count=None):
    count = count if count is not None else [0]
    count[0] += 1
    if depth > 12 or count[0] > 10000:
        raise ContentBlocked("response_structure_limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                raise ContentBlocked("invalid_key")
            bounded_json(item, depth + 1, count)
    elif isinstance(value, list):
        for item in value:
            bounded_json(item, depth + 1, count)
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ContentBlocked("invalid_json")
    elif isinstance(value, str) and len(value.encode()) > 1000000:
        raise ContentBlocked("response_text_limit")


# 行内标签不产生空格；仅 HTML 结构边界提供分隔，不把自动链接当作分词。
_TEXT_BOUNDARIES = frozenset({
    "br", "hr", "div", "p", "section", "article", "header", "footer", "aside", "nav", "main",
    "address", "figure", "figcaption", "blockquote", "ul", "ol", "li", "table", "tr", "td", "th",
    "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
})


def _text_parts(node):
    if isinstance(node, Comment):
        return
    if isinstance(node, NavigableString):
        if type(node) in (NavigableString, CData):
            yield str(node)
    elif isinstance(node, Tag) and node.name not in {"script", "style"}:
        boundary = node.name in _TEXT_BOUNDARIES
        if boundary:
            yield " "
        for child in node.children:
            yield from _text_parts(child)
        if boundary:
            yield " "


def _text(node):
    return " ".join("".join(_text_parts(node)).split())


def clean_source(snapshot, selectors=None):
    html = snapshot.get("html", "")
    if not isinstance(html, str) or not html.strip() or len(html.encode()) > 2000000:
        raise ContentBlocked("body_boundary_missing_or_oversized")
    soup = BeautifulSoup(html, "lxml")
    root, matched = None, ""
    for selector in selectors or BODY_SELECTORS.get(snapshot["source_site"], []):
        if selector.strip() in {"html", "body", "main", "article", ".content", ".region-content", "*"}:
            raise ContentBlocked("body_boundary_too_broad")
        nodes = soup.select(selector)
        if len(nodes) > 1:
            raise ContentBlocked("body_boundary_ambiguous")
        if nodes:
            root, matched = nodes[0], selector
            break
    if root is None or root.name in {"html", "body", "main"}:
        raise ContentBlocked("body_boundary_not_found")
    if snapshot["source_site"] == "scmp_racing" and scmp_body_access_restricted(root):
        raise ContentBlocked("body_access_restricted")
    removed = []
    noise_selectors = _STRUCTURED_NOISE_SELECTORS + (_SCMP_STRUCTURED_NOISE_SELECTORS if snapshot["source_site"] == "scmp_racing" else ())
    for selector in noise_selectors:
        for node in list(root.select(selector)):
            if node.parent is None:
                continue
            removed.append({"selector": selector, "html_sha": digest(str(node)), "reason": "structured_noise"})
            node.decompose()
    blocks = []
    def append(text, tag):
        text = text.strip()
        if text:
            blocks.append({"id": f"b{len(blocks)}", "text": text, "tag": tag})
    def walk(node):
        inline = []
        def flush():
            append(" ".join("".join(inline).split()), "text")
            inline.clear()
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                if type(child) in (NavigableString, CData):
                    inline.append(str(child))
            elif isinstance(child, Tag) and child.name in BLOCK_TAGS:
                flush()
                if child.name == "table":
                    text = "\n".join(" | ".join(_text(cell) for cell in row.find_all(["th", "td"], recursive=False)) for row in child.find_all("tr"))
                elif child.name in {"ul", "ol"}:
                    text = "\n".join("- " + _text(item) for item in child.find_all("li", recursive=False))
                else:
                    text = _text(child)
                append(text, child.name)
            elif isinstance(child, Tag) and child.find(list(BLOCK_TAGS)):
                flush()
                walk(child)
            elif isinstance(child, Tag):
                inline.append("".join(_text_parts(child)))
        flush()
    walk(root)
    if not blocks or len(blocks) > 1000 or not snapshot.get("title", "").strip():
        raise ContentBlocked("body_empty_or_unbounded")
    if any(TOKEN_RE.search(row["text"]) for row in blocks) or TOKEN_RE.search(snapshot["title"]):
        raise ContentBlocked("reserved_token_in_source")
    value = {"title": snapshot["title"], "blocks": blocks, "source_sha": digest(snapshot), "selector": matched, "removed": removed}
    value["suspicious_block_ids"] = [row["id"] for row in blocks
        if row["tag"] not in {"blockquote", "table", "figcaption"} and len(row["text"]) < 500
        and re.search(r"subscribe|sign up|register now|広告|有料会員|無料登録|点击.*下载|立即投注", row["text"], re.I)]
    value["clean_sha"] = digest({"title": value["title"], "blocks": blocks})
    return value


def block_map(clean):
    return {"title": clean["title"], **{row["id"]: row["text"] for row in clean["blocks"]}}


@model_schema
def validate_entities(clean, response, *, contract_version="legacy"):
    if contract_version == "context-v2":
        return context_entities(clean, response)
    bounded_json(response)
    if type(response) is not dict or set(response) != {"coverage", "entities"} or response["coverage"] != "complete":
        raise ContentBlocked("entity_schema_or_coverage")
    rows = response["entities"]
    if type(rows) is not list or len(rows) > 128:
        raise ContentBlocked("entity_count_limit")
    texts = block_map(clean)
    validated = []
    spans = {}
    for item in rows:
        required = {"block_id", "start", "end", "text", "type"}
        if type(item) is not dict or set(item) != required:
            raise ContentBlocked("entity_schema")
        block, start, end = item["block_id"], item["start"], item["end"]
        if (type(block) is not str or block not in texts or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(texts[block]) or texts[block][start:end] != item["text"]):
            raise ContentBlocked("entity_span_invalid")
        if type(item["type"]) is not str or item["type"] not in {"horse", "person", "race", "organization", "place", "common_word"}:
            raise ContentBlocked("entity_type_invalid")
        if any(start < other_end and end > other_start for other_start, other_end in spans.get(block, [])):
            raise ContentBlocked("entity_span_overlap")
        spans.setdefault(block, []).append((start, end))
        if item["type"] == "common_word":
            continue
        validated.append({**item, "replacement": item["text"], "provenance": "original_name", "source_sha": clean["source_sha"]})
    for index, item in enumerate(sorted(validated, key=lambda row: (row["block_id"], row["start"]))):
        item["token"] = f"__P01_ENTITY_{index:03}__"
    return validated


def protect_source(clean, entities):
    texts = block_map(clean)
    for item in sorted(entities, key=lambda row: (row["block_id"], -row["start"])):
        block = item["block_id"]
        texts[block] = texts[block][:item["start"]] + item["token"] + texts[block][item["end"]:]
    return {"title": texts["title"], "blocks": [{"id": row["id"], "text": texts[row["id"]]} for row in clean["blocks"]]}


@model_schema
def restore_translation(clean, entities, response):
    bounded_json(response)
    if type(response) is not dict or set(response) != {"title", "summary", "blocks"}:
        raise ContentBlocked("translation_schema")
    rows = response["blocks"]
    if type(rows) is not list or any(type(row) is not dict or set(row) != {"id", "text"} for row in rows):
        raise ContentBlocked("translation_blocks_schema")
    if [row["id"] for row in rows] != [row["id"] for row in clean["blocks"]]:
        raise ContentBlocked("translation_block_coverage")
    texts = {"title": response["title"], "summary": response["summary"], **{row["id"]: row["text"] for row in rows}}
    if any(type(text) is not str or not text.strip() for text in texts.values()):
        raise ContentBlocked("translation_empty")
    known = {item["token"] for item in entities}
    for block, text in texts.items():
        found = TOKEN_RE.findall(text)
        expected = {item["token"] for item in entities if item["block_id"] == block}
        if block == "summary":
            if set(found) - known:
                raise ContentBlocked("unknown_placeholder")
        elif set(found) != expected or len(found) != len(expected):
            raise ContentBlocked("placeholder_coverage")
        for item in entities:
            text = text.replace(item["token"], item["replacement"])
        if "__P01_ENTITY" in text:
            raise ContentBlocked("placeholder_residue")
        texts[block] = text
    blocks = [{"id": row["id"], "text": texts[row["id"]]} for row in rows]
    return {"title": texts["title"], "summary": texts["summary"], "body": "\n\n".join(row["text"] for row in blocks), "blocks": blocks}


@model_schema
def validate_audit(clean, target, response, *, contract_version="legacy"):
    if contract_version == "context-v2":
        return context_audit(clean, target, response)
    bounded_json(response)
    failed = {"passed": False, "reason": "audit_schema_or_unknown", "source_sha": clean["source_sha"], "target_sha": digest(target)}
    if (type(response) is not dict or set(response) != {"verdict", "checks", "issues"}
            or response.get("verdict") not in {"pass", "fail", "uncertain"}
            or type(response.get("checks")) is not dict or set(response["checks"]) != AUDIT_CHECKS
            or any(type(value) is not bool for value in response["checks"].values())
            or type(response.get("issues")) is not list or len(response["issues"]) > 128):
        return failed
    sources = block_map(clean)
    targets = {"title": target["title"], **{row["id"]: row["text"] for row in target["blocks"]}}
    if target.get("manual"):
        pairs = {"title": (clean["title"], target["title"]), "body": ("\n\n".join(row["text"] for row in clean["blocks"]), target["body"])}
    else:
        pairs = {key: (text, targets.get(key, "")) for key, text in sources.items()}
    diagnostics = {key: audit_equivalent_numbers(original, translated) for key, (original, translated) in pairs.items()}
    for issue in response["issues"]:
        if type(issue) is not dict or set(issue) != {"kind", "block_id", "source_span", "target_span"}:
            return failed
        block = issue["block_id"]
        target_block = "body" if target.get("manual") and block != "title" else block
        if block not in sources or target_block not in targets or issue["kind"] not in AUDIT_CHECKS:
            return failed
        for field, texts in (("source_span", sources), ("target_span", targets)):
            span = issue[field]
            if type(span) is not list or len(span) != 2 or any(type(i) is not int for i in span) or not 0 <= span[0] <= span[1] <= len(texts[target_block if field == "target_span" else block]):
                return failed
    numeric_ok = all(row["status"] != "surface_difference" for row in diagnostics.values())
    source_numbers = set(numeric_tokens("\n".join(sources.values())))
    summary_numbers = set(numeric_tokens(target["summary"], include_optional=False))
    numeric_ok = numeric_ok and not (summary_numbers - source_numbers)
    passed = response["verdict"] == "pass" and all(response["checks"].values()) and not response["issues"] and numeric_ok
    return {"passed": passed, "reason": "passed" if passed else "facts_or_numeric_difference", "source_sha": clean["source_sha"], "clean_sha": clean["clean_sha"], "target_sha": digest(target), "model": deepcopy(response), "numeric": diagnostics}


def resolve_known_entities(clean, occurrences, *, language):
    """只采纳现有确定性 resolver 已确认的同一 occurrence；不新增实体或译名。"""
    from stable.services.terms import resolve_article_entities
    texts = block_map(clean)
    resolutions = {}
    result = deepcopy(occurrences)
    for item in result:
        block = item["block_id"]
        if block not in resolutions:
            resolutions[block] = resolve_article_entities("", texts[block], source_language=language)
        resolution = resolutions[block]
        matches = [candidate for candidate in resolution.entities
            if candidate.start == item["start"] and candidate.end == item["end"]
            and candidate.matched_text == item["text"] and not candidate.conflict_flags
            and candidate.term_id in resolution.accepted_term_ids and candidate.confidence >= 90
            and candidate.target_zh and not candidate.needs_preserve
            and (candidate.entity_type == item["type"] or (item["type"] == "person" and candidate.entity_type in {"jockey", "trainer", "owner", "person"}))]
        if len(matches) == 1:
            candidate = matches[0]
            item.update(replacement=candidate.target_zh, term_id=candidate.term_id,
                        provenance="confirmed_term_occurrence", identity_evidence=candidate.evidence)
    return result


def manual_translation(target):
    return {**target, "blocks": [{"id": "body", "text": target["body"]}], "manual": True}


@model_schema
def validate_body_review(clean, response):
    bounded_json(response)
    expected = set(clean.get("suspicious_block_ids", []))
    if type(response) is not dict or set(response) != {"decisions"} or type(response["decisions"]) is not list or len(response["decisions"]) != len(expected):
        raise ContentBlocked("body_review_schema")
    seen, removed = set(), set()
    for row in response["decisions"]:
        if (type(row) is not dict or set(row) != {"id", "decision", "reason"} or row["id"] not in expected
                or row["id"] in seen or row["decision"] not in {"keep", "remove"}
                or type(row["reason"]) is not str or not 0 < len(row["reason"]) <= 1000):
            raise ContentBlocked("body_review_uncertain_or_invalid")
        seen.add(row["id"])
        if row["decision"] == "remove":
            removed.add(row["id"])
    value = deepcopy(clean)
    value["blocks"] = [row for row in clean["blocks"] if row["id"] not in removed]
    if not value["blocks"]:
        raise ContentBlocked("body_review_empty")
    value["body_review"] = deepcopy(response)
    value["clean_sha"] = digest({"title": value["title"], "blocks": value["blocks"]})
    return value


# context-v2：模型给语义及原文引用，字符定位由确定性代码完成。
def stable_source(clean):
    return deepcopy({key: value for key, value in clean.items() if key != "body_review_attempt_id"})


def exact_span(text, quote, context):
    if any(type(value) is not str or not value for value in (text, quote, context)):
        raise ContentBlocked("context_required")
    def positions(haystack, needle):
        start = 0
        while True:
            found = haystack.find(needle, start)
            if found < 0:
                return
            yield found
            start = found + 1
    offsets = positions(context, quote)
    offset = next(offsets, None)
    if offset is None or next(offsets, None) is not None:
        raise ContentBlocked("context_not_unique")
    starts = positions(text, context)
    start = next(starts, None)
    if start is None or next(starts, None) is not None:
        raise ContentBlocked("context_not_unique")
    return start + offset, start + offset + len(quote)


def context_entities(clean, response):
    bounded_json(response)
    if (type(response) is not dict or set(response) != {"coverage", "entities"}
            or response["coverage"] != "complete" or type(response["entities"]) is not list
            or len(response["entities"]) > 128):
        raise ContentBlocked("entity_schema_or_coverage")
    texts, translated, contexts = block_map(clean), [], {}
    for row in response["entities"]:
        if type(row) is not dict or set(row) != {"block_id", "text", "type", "context"}:
            raise ContentBlocked("entity_context_schema")
        block = row["block_id"]
        if type(block) is not str or block not in texts:
            raise ContentBlocked("entity_block_invalid")
        start, end = exact_span(texts[block], row["text"], row["context"])
        translated.append({key: value for key, value in row.items() if key != "context"} | {"start": start, "end": end})
        contexts[(block, start, end)] = row["context"]
    rows = validate_entities(clean, {"coverage": "complete", "entities": translated})
    return [row | {"context": contexts[(row["block_id"], row["start"], row["end"])],
                   "contract_version": "context-v2"} for row in rows]


def hard_translation_checks(clean, target):
    sources = block_map(clean)
    targets = {"title": target["title"], **{row["id"]: row["text"] for row in target["blocks"]}}
    if target.get("manual"):
        pairs = {"title": (clean["title"], target["title"]),
                 "body": ("\n\n".join(row["text"] for row in clean["blocks"]), target["body"])}
    else:
        if [row["id"] for row in target["blocks"]] != [row["id"] for row in clean["blocks"]]:
            raise ContentBlocked("translation_block_coverage")
        pairs = {key: (value, targets[key]) for key, value in sources.items()}
    numeric = {key: audit_equivalent_numbers(*pair) for key, pair in pairs.items()}
    bad = [key for key, value in numeric.items() if value["status"] == "surface_difference"]
    summary_extra = set(numeric_tokens(target["summary"], include_optional=False)) - set(numeric_tokens("\n".join(sources.values())))
    if summary_extra:
        bad.append("summary")
    return {"passed": not bad, "numeric": numeric, "repair_block_ids": sorted(set(bad)),
            "summary_difference": sorted(summary_extra), "target_sha": digest(target)}


def context_audit(clean, target, response):
    bounded_json(response)
    failed = {"passed": False, "evidence_valid": False, "reason": "audit_schema_or_unknown",
              "source_sha": clean["source_sha"], "target_sha": digest(target), "repair_block_ids": []}
    if (type(response) is not dict or set(response) != {"verdict", "checks", "issues"}
            or response.get("verdict") not in {"pass", "fail", "uncertain"}
            or type(response.get("checks")) is not dict or set(response["checks"]) != AUDIT_CHECKS
            or any(type(v) is not bool for v in response["checks"].values())
            or type(response.get("issues")) is not list or len(response["issues"]) > 128):
        return failed
    sources = block_map(clean)
    targets = {"title": target["title"], "summary": target["summary"],
               **{row["id"]: row["text"] for row in target["blocks"]}}
    normalized, repair = [], set()
    try:
        for issue in response["issues"]:
            if (type(issue) is not dict or set(issue) != {"kind", "source", "target", "missing"}
                    or issue["kind"] not in AUDIT_CHECKS or type(issue["missing"]) is not bool):
                return failed
            spans = {}
            for side, texts in (("source", sources), ("target", targets)):
                ref = issue[side]
                if type(ref) is not dict or set(ref) != {"block_id", "quote", "context"} or ref["block_id"] not in texts:
                    return failed
                if side == "target" and issue["missing"]:
                    if ref["quote"] != "":
                        return failed
                    exact_span(texts[ref["block_id"]], ref["context"], ref["context"])
                    spans[side] = None
                else:
                    spans[side] = list(exact_span(texts[ref["block_id"]], ref["quote"], ref["context"]))
            repair.add(issue["target"]["block_id"])
            normalized.append({**issue, "located": spans})
    except (ContentBlocked, TypeError, KeyError):
        return failed
    if (response["verdict"] == "pass" and (response["issues"] or not all(response["checks"].values()))
            or response["verdict"] != "pass" and not response["issues"]):
        return failed
    hard = hard_translation_checks(clean, target)
    passed = response["verdict"] == "pass" and hard["passed"]
    return {**failed, "passed": passed, "evidence_valid": True, "verdict": response["verdict"],
            "reason": "passed" if passed else "facts_or_numeric_difference", "clean_sha": clean["clean_sha"],
            "model": deepcopy(response), "located_issues": normalized, "numeric": hard["numeric"],
            "repair_block_ids": sorted(repair | set(hard["repair_block_ids"]))}


def protected_translation_map(raw):
    if (type(raw) is not dict or set(raw) != {"title", "summary", "blocks"} or type(raw["blocks"]) is not list
            or any(type(row) is not dict or set(row) != {"id", "text"} for row in raw["blocks"])):
        raise ContentBlocked("repair_structure")
    ids = [row["id"] for row in raw["blocks"]]
    if any(type(key) is not str or key in {"title", "summary"} for key in ids) or len(set(ids)) != len(ids):
        raise ContentBlocked("repair_structure")
    texts = {"title": raw["title"], "summary": raw["summary"], **{row["id"]: row["text"] for row in raw["blocks"]}}
    if any(type(value) is not str for value in texts.values()):
        raise ContentBlocked("repair_structure")
    return texts


@model_schema
def merge_translation_patch(base, patch, required):
    bounded_json(patch)
    texts = protected_translation_map(base)
    if (not required or len(set(required)) != len(required) or not set(required) <= set(texts)
            or type(patch) is not dict or set(patch) != {"base_raw_sha", "replacements"}
            or patch["base_raw_sha"] != digest(base) or type(patch["replacements"]) is not list):
        raise ContentBlocked("repair_patch_schema")
    rows = patch["replacements"]
    if (any(type(row) is not dict or set(row) != {"id", "text"} or type(row["text"]) is not str or not row["text"].strip() for row in rows)
            or len(rows) != len(required) or {row["id"] for row in rows} != set(required)):
        raise ContentBlocked("repair_patch_coverage")
    texts.update({row["id"]: row["text"] for row in rows})
    return {"title": texts["title"], "summary": texts["summary"],
            "blocks": [{"id": row["id"], "text": texts[row["id"]]} for row in base["blocks"]]}


def translation_repair_ids(clean, entities, raw):
    """仅结构安全时定位空块/占位错误；否则使用明确的全文修复。"""
    try:
        texts = protected_translation_map(raw)
        if [row["id"] for row in raw["blocks"]] != [row["id"] for row in clean["blocks"]]:
            return None
    except ContentBlocked:
        return None
    known, bad = {row["token"] for row in entities}, []
    for block, text in texts.items():
        found = TOKEN_RE.findall(text)
        expected = {row["token"] for row in entities if row["block_id"] == block}
        wrong = (set(found) - known) if block == "summary" else (set(found) != expected or len(found) != len(expected))
        residue = TOKEN_RE.sub("", text)
        if not text.strip() or wrong or "__P01_ENTITY" in residue:
            bad.append(block)
    return sorted(bad) or None
