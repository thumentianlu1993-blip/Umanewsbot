from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import math
import os
import re
import stat
import sys
from typing import Iterable

from django.core.management.base import CommandError
from django.db import transaction

from stable.models import NewsArticle, OperationLog, SourceLanguage, TermEntry, TermType
from stable.services import content_contracts as binding_f01
from stable.services.article_entity_binding import BindingInputError, plan_article_entity_bindings
from stable.services.horse_profiles import reconcile_article_horse_links
from stable.services.terms import ArticleEntityResolution, resolve_article_entities
from stable.tasks import translate_article_task


def _source_default_tags(article: NewsArticle) -> list[str]:
    if not article.source_config_id:
        return []
    return list(article.source_config.default_tags or [])


def _tag_plan(article: NewsArticle, resolution: ArticleEntityResolution) -> dict[str, list[str] | bool]:
    current = list(dict.fromkeys(tag.strip() for tag in (article.tags_json or []) if tag and tag.strip()))
    machine_tags = list(resolution.machine_horse_tags)
    defaults = set(_source_default_tags(article))
    if "tags_json" in set(article.manually_edited_fields or []):
        return {
            "locked": True,
            "before": current,
            "after": current,
            "add": [],
            "delete": [],
        }
    previous_machine = set((article.translation_metadata or {}).get("machine_horse_tags") or [])
    active_horse_targets = set(
        TermEntry.objects.filter(is_active=True, term_type=TermType.HORSE, target_zh__in=current)
        .exclude(target_zh="")
        .values_list("target_zh", flat=True)
    )
    # Explicit reprocessing owns all unlocked horse-term tags on the selected
    # article.  Always include active horse targets: an interrupted/older run
    # may already have written incomplete provenance while leaving legacy tags.
    legacy_candidates = previous_machine | active_horse_targets
    delete = [tag for tag in current if tag in legacy_candidates and tag not in machine_tags and tag not in defaults]
    after = [tag for tag in current if tag not in delete]
    for tag in [*_source_default_tags(article), *machine_tags]:
        if tag and tag not in after:
            after.append(tag)
    return {
        "locked": False,
        "before": current,
        "after": after,
        "add": [tag for tag in after if tag not in current],
        "delete": delete,
    }


def build_article_entity_reprocess_plan(
    article: NewsArticle,
    *,
    resolution: ArticleEntityResolution | None = None,
) -> dict:
    resolution = resolution or resolve_article_entities(
        article.title_ja,
        article.body_ja_normalized or article.body_ja_raw,
        source_language=article.source_language or SourceLanguage.JAPANESE,
    )
    return {
        "article_id": article.id,
        "entities": resolution.as_dict(),
        "terms": [item.__dict__ for item in resolution.accepted_terms],
        "tags": _tag_plan(article, resolution),
        "links": reconcile_article_horse_links(article, resolution, commit=False),
    }


def _commit_article(article_id: int, *, translate_sync: bool) -> dict:
    with transaction.atomic():
        article = NewsArticle.objects.select_for_update().get(pk=article_id)
        before_public = {
            "id": article.id,
            "workflow_status": article.workflow_status,
            "published_to_web_at": article.published_to_web_at,
            "qq_delivery_count": article.qq_push_deliveries.count(),
        }
        pre_translation_resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        pre_translation_tag_plan = _tag_plan(article, pre_translation_resolution)
        if translate_sync:
            translation_outcome = translate_article_task.run(article.id, force=True, suppress_automation=True)
            if not translation_outcome or not translation_outcome.get("translated"):
                raise RuntimeError(
                    "synchronous translation did not complete: "
                    f"article={article.id} outcome={translation_outcome!r}"
                )
            article.refresh_from_db()
        resolution = resolve_article_entities(
            article.title_ja,
            article.body_ja_normalized or article.body_ja_raw,
            source_language=article.source_language or SourceLanguage.JAPANESE,
        )
        tag_plan = pre_translation_tag_plan if translate_sync else _tag_plan(article, resolution)
        if not tag_plan["locked"]:
            article.tags_json = tag_plan["after"]
        metadata = dict(article.translation_metadata or {})
        metadata["machine_horse_tags"] = list(resolution.machine_horse_tags)
        metadata["article_entity_resolution"] = resolution.as_dict()
        article.translation_metadata = metadata
        article.save(update_fields=["tags_json", "translation_metadata", "updated_at"])
        link_plan = reconcile_article_horse_links(article, resolution, commit=True)
        after_public = {
            "id": article.id,
            "workflow_status": article.workflow_status,
            "published_to_web_at": article.published_to_web_at,
            "qq_delivery_count": article.qq_push_deliveries.count(),
        }
        if before_public != after_public:
            raise RuntimeError(f"public identity changed: before={before_public} after={after_public}")
        OperationLog.objects.create(
            action_type="article_entities_reprocessed",
            target_type="news_article",
            target_id=str(article.id),
            detail=(
                f"tags_add={tag_plan['add']} tags_delete={tag_plan['delete']} "
                f"links_create={len(link_plan['create'])} links_update={len(link_plan['update'])} "
                f"links_delete={link_plan['delete_ids']} translate_sync={translate_sync}"
            ),
        )
        return {
            "article_id": article.id,
            "status": "committed",
            "entities": resolution.as_dict(),
            "terms": [item.__dict__ for item in resolution.accepted_terms],
            "tags": tag_plan,
            "links": link_plan,
        }


def reprocess_article_entities(
    article_ids: Iterable[int],
    *,
    commit: bool = False,
    translate_sync: bool = False,
) -> dict:
    ids = list(dict.fromkeys(int(article_id) for article_id in article_ids))
    results: list[dict] = []
    if not commit:
        articles = NewsArticle.objects.filter(id__in=ids).select_related("source_config")
        by_id = {article.id: article for article in articles}
        for article_id in ids:
            article = by_id.get(article_id)
            if article is None:
                results.append({"article_id": article_id, "status": "failed", "error": "article not found"})
                continue
            results.append({"status": "dry_run", **build_article_entity_reprocess_plan(article)})
        return {"mode": "dry_run", "article_ids": ids, "articles": results}

    for article_id in ids:
        try:
            results.append(_commit_article(article_id, translate_sync=translate_sync))
        except Exception as exc:
            OperationLog.objects.create(
                action_type="article_entities_reprocess_failed",
                target_type="news_article",
                target_id=str(article_id),
                detail=str(exc),
            )
            results.append({"article_id": article_id, "status": "failed", "error": str(exc)})
    return {"mode": "commit", "article_ids": ids, "articles": results}


# C188/C189 admission subset for the new read-only branch only.
_BD_LIMITS = {
    "MAX_RAW_ID_ARGUMENTS": 64,
    "MAX_UNIQUE_DIAGNOSTIC_IDS": 16,
    "ID_MIN": 1,
    "ID_MAX": 9223372036854775807,
    "EXPLICIT_AUDIT_RAW_ID_COUNT": 1,
    "MAX_INPUT_PATH_UTF8_BYTES": 4096,
    "MAX_FILE_BYTES": 1048576,
    "MAX_FD_READ_BYTES": 1048577,
    "READ_CHUNK_BYTES": 65536,
    "MAX_JSON_DEPTH": 24,
    "MAX_JSON_NODES": 16384,
    "MAX_JSON_CONTAINER_ITEMS": 256,
    "MAX_JSON_OBJECT_MEMBERS": 128,
    "MAX_JSON_KEY_UTF8_BYTES": 256,
    "MAX_JSON_STRING_UTF8_BYTES": 262144,
    "MAX_JSON_NUMBER_TOKEN_BYTES": 64,
    "MAX_IDENTITY_INPUTS": 8,
    "MAX_RELATION_INPUTS": 16,
    "MAX_CONTEXTS": 64,
    "MAX_ARTIFACTS": 8,
    "MAX_F01_DOCUMENT_CANONICAL_BYTES": 65536,
    "MAX_F01_DOCUMENTS_CANONICAL_BYTES_TOTAL": 262144,
    "MAX_F01_SOURCE_REFS": 8,
    "MAX_F01_EVIDENCE": 32,
    "MAX_F01_MATERIALS": 32,
    "MAX_F01_REFERENCE_ARRAY_ITEMS": 32,
    "MAX_SOURCE_DOCUMENT_DECODED_BYTES": 131072,
    "MAX_ARTIFACT_DECODED_BYTES": 65536,
    "MAX_DECODED_BYTES_TOTAL": 262144,
    "MAX_SOURCE_B64_CHARS": 174764,
    "MAX_ARTIFACT_B64_CHARS": 87384,
    "MAX_DECODED_JSON_NODES_TOTAL": 16384,
    "MAX_ASSERTIONS_PER_ARTIFACT": 32,
    "MAX_ASSERTIONS_TOTAL": 128,
    "MAX_SOURCE_TITLE_UTF8_BYTES": 4096,
    "MAX_SOURCE_BODY_RAW_UTF8_BYTES": 65536,
    "MAX_SOURCE_BODY_NORMALIZED_UTF8_BYTES": 65536,
    "MAX_SOURCE_LANGUAGE_UTF8_BYTES": 64,
    "MAX_SOURCE_FIELD_UTF8_BYTES_TOTAL": 131072,
    "MAX_SOURCE_CANONICAL_BYTES": 262144,
    "MAX_METADATA_CANONICAL_BYTES": 262144,
    "MAX_METADATA_STRING_UTF8_BYTES": 16384,
    "MAX_RESOLUTION_CANONICAL_BYTES": 131072,
    "MAX_ENTITIES": 32,
    "MAX_SUPPRESSED_ENTITIES": 32,
    "MAX_ACCEPTED_TERMS": 32,
    "MAX_ACCEPTED_TERM_IDS": 64,
    "MAX_MACHINE_HORSE_TAGS": 32,
    "MAX_ENTITY_REFERENCE_ARRAY_ITEMS": 64,
    "MAX_ENTITY_STRING_UTF8_BYTES": 4096,
    "MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL": 1048576,
    "MAX_ARTICLE_OUTPUT_JSON_BYTES": 65536,
    "MAX_INVOCATION_OUTPUT_JSON_BYTES": 262144,
    "MAX_TEXT_SUMMARY_UTF8_BYTES": 4096,
    "MAX_ERROR_JSON_BYTES": 1024,
    "MAX_PATH_COMPONENTS": 64,
    "MAX_OWNED_FILE_DESCRIPTORS": 3,
    "MAX_READ_CALLS": 32,
    "MAX_JSON_INTEGER_BITS": 192
}
_BD_CODES = (
    'invalid_flags',
    'invalid_ids',
    'input_limit',
    'article_not_found',
    'input_location_invalid',
    'input_file_type',
    'input_io_error',
    'input_changed',
    'input_utf8_invalid',
    'input_json_invalid',
    'input_shape_invalid',
    'input_base64_invalid',
    'input_scope_mismatch',
    'f01_invalid',
    'binding_input_invalid',
    'persisted_resolution_missing',
    'full_snapshot_unavailable',
    'invalid_snapshot',
    'diagnostic_query_error',
)
_BD_SOURCE_FIELDS = ("title_ja", "body_ja_raw", "body_ja_normalized", "source_language")
_BD_VALUES_FIELDS = ("id", *_BD_SOURCE_FIELDS, "translation_metadata", "updated_at")
_BD_RESOLUTION_KEYS = ("source_language", "entities", "suppressed_candidates", "accepted_terms",
                       "accepted_term_ids", "machine_horse_tags")
_BD_ENVELOPE_KEYS = ("schema_version", "article_id", "observed_source_fields_sha256",
                     "persisted_resolution_sha256", "article_input", "identity_inputs", "relation_inputs",
                     "source_document_base64", "relationship_artifacts_base64", "contexts")
_BD_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_BD_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _bd_fail(code, limit=None):
    error = CommandError(code)
    if limit is not None:
        error.diagnostic_limit = limit
    raise error from None


def _bd_cap(size, name):
    if size > _BD_LIMITS[name]:
        _bd_fail("input_limit", name)


def _bd_utf8_size(value, maximum, tag, invalid="invalid_snapshot"):
    if type(value) is not str:
        _bd_fail(invalid)
    if len(value) > maximum:
        _bd_fail("input_limit", tag)
    count = 0
    try:
        for index in range(0, len(value), 512):
            count += len(value[index:index + 512].encode("utf-8", errors="strict"))
            if count > maximum:
                _bd_fail("input_limit", tag)
    except UnicodeError:
        _bd_fail(invalid)
    return count


def _binding_diagnostic_validate_ids(ids, *, explicit=False):
    if type(ids) is not list and type(ids) is not tuple:
        _bd_fail("invalid_ids")
    if not ids or (explicit and len(ids) != _BD_LIMITS["EXPLICIT_AUDIT_RAW_ID_COUNT"]):
        _bd_fail("invalid_ids")
    _bd_cap(len(ids), "MAX_RAW_ID_ARGUMENTS")
    result = []
    seen = set()
    for value in ids:
        if type(value) is not int or not _BD_LIMITS["ID_MIN"] <= value <= _BD_LIMITS["ID_MAX"]:
            _bd_fail("invalid_ids")
        if value not in seen:
            seen.add(value)
            result.append(value)
            _bd_cap(len(result), "MAX_UNIQUE_DIAGNOSTIC_IDS")
    return result


def _binding_diagnostic_read_file(path):
    """One local ordinary file, lexical path admission and owned dirfd traversal."""
    if type(path) is not str or not path:
        _bd_fail("input_location_invalid")
    _bd_utf8_size(path, _BD_LIMITS["MAX_INPUT_PATH_UTF8_BYTES"], "MAX_INPUT_PATH_UTF8_BYTES",
                  "input_location_invalid")
    if "\0" in path or path.startswith("//") or "://" in path or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path):
        _bd_fail("input_location_invalid")
    absolute = os.path.abspath(os.path.normpath(path))
    parts = [part for part in absolute.split(os.sep) if part]
    _bd_cap(len(parts), "MAX_PATH_COMPONENTS")
    if not parts:
        _bd_fail("input_file_type")
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
    if any(type(getattr(os, flag, None)) is not int or getattr(os, flag) == 0 for flag in required):
        _bd_fail("input_io_error")
    if not getattr(os, "supports_dir_fd", None):
        _bd_fail("input_io_error")
    owned = []
    def opened(name, flags, **kwargs):
        fd = os.open(name, flags, **kwargs)
        owned.append(fd)
        _bd_cap(len(owned), "MAX_OWNED_FILE_DESCRIPTORS")
        return fd
    def close_one(fd):
        owned.remove(fd)
        os.close(fd)
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        parent = opened(os.sep, directory_flags)
        if not stat.S_ISDIR(os.fstat(parent).st_mode):
            _bd_fail("input_file_type")
        for component in parts[:-1]:
            next_parent = opened(component, directory_flags, dir_fd=parent)
            if not stat.S_ISDIR(os.fstat(next_parent).st_mode):
                _bd_fail("input_file_type")
            close_one(parent)
            parent = next_parent
        visible = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(visible.st_mode):
            _bd_fail("input_file_type")
        _bd_cap(visible.st_size, "MAX_FILE_BYTES")
        fd = opened(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                    dir_fd=parent)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _bd_fail("input_file_type")
        _bd_cap(before.st_size, "MAX_FILE_BYTES")
        data = bytearray()
        for _ in range(_BD_LIMITS["MAX_READ_CALLS"]):
            request = min(_BD_LIMITS["READ_CHUNK_BYTES"], _BD_LIMITS["MAX_FD_READ_BYTES"] - len(data))
            chunk = os.read(fd, request)
            if not chunk:
                break
            data.extend(chunk)
            _bd_cap(len(data), "MAX_FILE_BYTES")
        else:
            _bd_fail("input_limit", "MAX_READ_CALLS")
        after = os.fstat(fd)
        fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                      value.st_mtime_ns, value.st_ctime_ns)
        if fingerprint(before) != fingerprint(after):
            _bd_fail("input_changed")
        return bytes(data)
    except OSError as error:
        _bd_fail("input_file_type" if error.errno in (errno.ELOOP, errno.ENOTDIR) else "input_io_error")
    except (TypeError, NotImplementedError):
        _bd_fail("input_io_error")
    finally:
        unwinding = sys.exc_info()[0] is not None
        close_error = False
        for fd in reversed(owned):
            try:
                os.close(fd)
            except OSError:
                close_error = True
        if close_error and not unwinding:
            _bd_fail("input_io_error")


def _bd_container_limit(path, kind):
    """Path-aware package/decoded lexer caps; strings in keys are already decoded."""
    if path == ("relationship_artifacts_base64",) and kind == "object":
        return "MAX_ARTIFACTS"
    if kind == "array":
        top = {"identity_inputs": "MAX_IDENTITY_INPUTS", "relation_inputs": "MAX_RELATION_INPUTS",
               "contexts": "MAX_CONTEXTS"}
        if len(path) == 1 and path[0] in top:
            return top[path[0]]
        if path == ("assertions",):
            return "MAX_ASSERTIONS_PER_ARTIFACT"
        if "snapshot" in path and path and path[0] in ("article_input", "identity_inputs", "relation_inputs"):
            return {"source_refs": "MAX_F01_SOURCE_REFS", "evidence": "MAX_F01_EVIDENCE",
                    "materials": "MAX_F01_MATERIALS", "candidate_ids": "MAX_F01_REFERENCE_ARRAY_ITEMS",
                    "evidence_refs": "MAX_F01_REFERENCE_ARRAY_ITEMS"}.get(path[-1], "MAX_JSON_CONTAINER_ITEMS")
    return "MAX_JSON_OBJECT_MEMBERS" if kind == "object" else "MAX_JSON_CONTAINER_ITEMS"


def _binding_diagnostic_json_preflight(data, *, decoded=False):
    """Bounded iterative token scanner. Does not build or parse a JSON value tree."""
    if type(data) is not bytes:
        _bd_fail("input_shape_invalid")
    _bd_cap(len(data), "MAX_FILE_BYTES")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeError:
        _bd_fail("input_utf8_invalid")
    length = len(text)
    index = 0
    nodes = 0
    assertions = 0
    frames = []
    root_done = False
    def node():
        nonlocal nodes
        nodes += 1
        _bd_cap(nodes, "MAX_JSON_NODES")
    def string_at(start, key=False):
        cursor = start + 1
        size = 0
        result = [] if key else None
        cap = "MAX_JSON_KEY_UTF8_BYTES" if key else "MAX_JSON_STRING_UTF8_BYTES"
        escapes = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
        while cursor < length:
            char = text[cursor]
            cursor += 1
            if char == '"':
                return "".join(result) if key else None, cursor
            if char == "\\":
                if cursor >= length:
                    _bd_fail("input_json_invalid")
                escape = text[cursor]
                cursor += 1
                if escape == "u":
                    digits = text[cursor:cursor + 4]
                    if len(digits) != 4 or re.fullmatch(r"[0-9a-fA-F]{4}", digits) is None:
                        _bd_fail("input_json_invalid")
                    code = int(digits, 16)
                    cursor += 4
                    if 0xD800 <= code <= 0xDBFF:
                        if text[cursor:cursor + 2] != "\\u":
                            _bd_fail("input_json_invalid")
                        digits = text[cursor + 2:cursor + 6]
                        if len(digits) != 4 or re.fullmatch(r"[0-9a-fA-F]{4}", digits) is None:
                            _bd_fail("input_json_invalid")
                        low = int(digits, 16)
                        if not 0xDC00 <= low <= 0xDFFF:
                            _bd_fail("input_json_invalid")
                        code = 0x10000 + ((code - 0xD800) << 10) + low - 0xDC00
                        cursor += 6
                    elif 0xDC00 <= code <= 0xDFFF:
                        _bd_fail("input_json_invalid")
                    char = chr(code)
                elif escape in escapes:
                    char = escapes[escape]
                else:
                    _bd_fail("input_json_invalid")
            elif ord(char) < 32:
                _bd_fail("input_json_invalid")
            size += len(char.encode("utf-8"))
            _bd_cap(size, cap)
            if key:
                result.append(char)
        _bd_fail("input_json_invalid")
    while True:
        while index < length and text[index] in " \t\r\n":
            index += 1
        if not frames and root_done:
            if index != length:
                _bd_fail("input_json_invalid")
            return {"nodes": nodes, "assertions": assertions}
        if index >= length:
            _bd_fail("input_json_invalid")
        frame = frames[-1] if frames else None
        char = text[index]
        if frame and frame["state"] == "colon":
            if char != ":":
                _bd_fail("input_json_invalid")
            frame["state"] = "value"
            index += 1
            continue
        if frame and frame["state"] == "comma_or_end":
            end = "}" if frame["kind"] == "object" else "]"
            if char == end:
                if frame["path"] == ("assertions",):
                    assertions += frame["count"]
                frames.pop()
                index += 1
                continue
            if char != ",":
                _bd_fail("input_json_invalid")
            frame["state"] = "key" if frame["kind"] == "object" else "value"
            index += 1
            continue
        if frame and frame["kind"] == "object" and frame["state"] in ("key", "key_or_end"):
            if char == "}" and frame["state"] == "key_or_end":
                frames.pop()
                index += 1
                continue
            if char != '"':
                _bd_fail("input_json_invalid")
            key, index = string_at(index, key=True)
            node()
            if key in frame["keys"]:
                _bd_fail("input_json_invalid")
            frame["keys"].add(key)
            frame["count"] += 1
            _bd_cap(frame["count"], _bd_container_limit(frame["path"], "object"))
            frame["key"] = key
            frame["state"] = "colon"
            continue
        if frame and frame["kind"] == "array" and frame["state"] == "value_or_end" and char == "]":
            frames.pop()
            index += 1
            continue
        if frame:
            if frame["kind"] == "array":
                path = (*frame["path"], frame["count"])
                frame["count"] += 1
                _bd_cap(frame["count"], _bd_container_limit(frame["path"], "array"))
            else:
                path = (*frame["path"], frame["key"])
            frame["state"] = "comma_or_end"
        else:
            path = ()
            root_done = True
        node()
        if char in "[{":
            _bd_cap(len(frames) + 1, "MAX_JSON_DEPTH")
            kind = "object" if char == "{" else "array"
            frames.append({"kind": kind, "path": path, "state": "key_or_end" if kind == "object" else "value_or_end",
                           "count": 0, "keys": set()})
            index += 1
        elif char == '"':
            _, index = string_at(index)
        elif char in "-0123456789":
            end = index
            while end < length and text[end] in "-+0123456789.eE":
                end += 1
                _bd_cap(end - index, "MAX_JSON_NUMBER_TOKEN_BYTES")
            token = text[index:end]
            if _BD_NUMBER.fullmatch(token) is None:
                _bd_fail("input_json_invalid")
            if "." in token or "e" in token or "E" in token:
                if not math.isfinite(float(token)):
                    _bd_fail("input_json_invalid")
            else:
                _bd_cap(int(token).bit_length(), "MAX_JSON_INTEGER_BITS")
            index = end
        else:
            literal = next((value for value in ("true", "false", "null") if text.startswith(value, index)), None)
            if literal is None:
                _bd_fail("input_json_invalid")
            index += len(literal)


def _bd_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _bd_fail("input_json_invalid")
        result[key] = value
    return result


def _bd_float(token):
    value = float(token)
    if not math.isfinite(value):
        _bd_fail("input_json_invalid")
    return value


def _bd_load_json(data, *, preflight=True):
    if preflight:
        _binding_diagnostic_json_preflight(data)
    try:
        return json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=_bd_pairs,
                          parse_float=_bd_float, parse_constant=lambda _: _bd_fail("input_json_invalid"))
    except RecursionError:
        _bd_fail("input_limit", "MAX_JSON_DEPTH")
    except UnicodeError:
        _bd_fail("input_utf8_invalid")
    except (ValueError, OverflowError):
        _bd_fail("input_json_invalid")


def _bd_native_tree(value, *, string_limit, string_tag, invalid="invalid_snapshot", package=False):
    """Iterative native JSON validation, including cycles; no user object hooks."""
    stack = [(False, value, 1, ())]
    active = set()
    nodes = 0
    while stack:
        exiting, current, depth, path = stack.pop()
        if exiting:
            active.remove(id(current))
            continue
        nodes += 1
        _bd_cap(nodes, "MAX_JSON_NODES")
        kind = type(current)
        if kind is dict or kind is list:
            if id(current) in active:
                _bd_fail(invalid)
            _bd_cap(depth, "MAX_JSON_DEPTH")
            active.add(id(current))
            stack.append((True, current, depth, path))
            tag = _bd_container_limit(path, "object" if kind is dict else "array") if package else (
                "MAX_JSON_OBJECT_MEMBERS" if kind is dict else "MAX_JSON_CONTAINER_ITEMS")
            _bd_cap(len(current), tag)
            if kind is dict:
                for key, child in current.items():
                    if type(key) is not str:
                        _bd_fail(invalid)
                    nodes += 1
                    _bd_cap(nodes, "MAX_JSON_NODES")
                    _bd_utf8_size(key, _BD_LIMITS["MAX_JSON_KEY_UTF8_BYTES"], "MAX_JSON_KEY_UTF8_BYTES", invalid)
                    stack.append((False, child, depth + 1, (*path, key)))
            else:
                for index, child in enumerate(current):
                    stack.append((False, child, depth + 1, (*path, index)))
        elif kind is str:
            _bd_utf8_size(current, string_limit, string_tag, invalid)
        elif kind is int:
            _bd_cap(current.bit_length(), "MAX_JSON_INTEGER_BITS")
        elif kind is float:
            if not math.isfinite(current):
                _bd_fail(invalid)
        elif current is None or kind is bool:
            pass
        else:
            _bd_fail(invalid)


def _bd_canonical_chunks(value):
    """Canonical JSON in small tokens, after native admission; no giant dumps chunk."""
    pending = [(False, value)]
    escapes = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
    while pending:
        literal, current = pending.pop()
        if literal:
            yield current
        elif type(current) is str:
            yield b'"'
            for index in range(0, len(current), 512):
                block = []
                for char in current[index:index + 512]:
                    block.append(escapes.get(char, "\\u%04x" % ord(char) if ord(char) < 32 else char))
                yield "".join(block).encode("utf-8")
            yield b'"'
        elif type(current) is dict:
            yield b"{"
            pending.append((True, b"}"))
            items = sorted(current.items())
            for index in range(len(items) - 1, -1, -1):
                key, child = items[index]
                pending.extend([(False, child), (True, b":"), (False, key)])
                if index:
                    pending.append((True, b","))
        elif type(current) is list:
            yield b"["
            pending.append((True, b"]"))
            for index in range(len(current) - 1, -1, -1):
                pending.append((False, current[index]))
                if index:
                    pending.append((True, b","))
        elif current is None:
            yield b"null"
        elif type(current) is bool:
            yield b"true" if current else b"false"
        else:
            yield json.dumps(current, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("ascii")


def _bd_encoded(value, maximum, tag):
    output = bytearray()
    for chunk in _bd_canonical_chunks(value):
        if len(output) + len(chunk) > maximum:
            _bd_fail("input_limit", tag)
        output.extend(chunk)
    return bytes(output)


def _bd_resolution_shape(value):
    if type(value) is not dict or set(value) != set(_BD_RESOLUTION_KEYS) or type(value["source_language"]) is not str:
        _bd_fail("invalid_snapshot")
    caps = {"entities": "MAX_ENTITIES", "suppressed_candidates": "MAX_SUPPRESSED_ENTITIES",
            "accepted_terms": "MAX_ACCEPTED_TERMS", "accepted_term_ids": "MAX_ACCEPTED_TERM_IDS",
            "machine_horse_tags": "MAX_MACHINE_HORSE_TAGS"}
    for key, tag in caps.items():
        if type(value[key]) is not list:
            _bd_fail("invalid_snapshot")
        _bd_cap(len(value[key]), tag)
    for key in ("entities", "suppressed_candidates"):
        for entity in value[key]:
            if type(entity) is not dict:
                _bd_fail("invalid_snapshot")
            for field in ("field_name", "matched_text"):
                if type(entity.get(field)) is not str:
                    _bd_fail("invalid_snapshot")
            if type(entity.get("start")) is not int or type(entity.get("end")) is not int:
                _bd_fail("invalid_snapshot")
            for child in entity.values():
                if type(child) is list:
                    _bd_cap(len(child), "MAX_ENTITY_REFERENCE_ARRAY_ITEMS")
    if any(type(x) is not dict for x in value["accepted_terms"]) or any(type(x) is not int for x in value["accepted_term_ids"]) or any(type(x) is not str for x in value["machine_horse_tags"]):
        _bd_fail("invalid_snapshot")


def _binding_diagnostic_native_preflight(value, *, scope):
    """Resource-only scopes for already returned rows; never reads the database."""
    if scope == "aggregate":
        if type(value) is not list:
            _bd_fail("invalid_snapshot")
        total = 0
        for item in value:
            _bd_native_tree(item, string_limit=_BD_LIMITS["MAX_JSON_STRING_UTF8_BYTES"],
                            string_tag="MAX_JSON_STRING_UTF8_BYTES")
            total += len(_bd_encoded(item, _BD_LIMITS["MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL"],
                                     "MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL"))
            _bd_cap(total, "MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL")
        return total
    if scope == "source":
        if type(value) is not dict or set(value) != set(_BD_SOURCE_FIELDS):
            _bd_fail("invalid_snapshot")
        tags = ("MAX_SOURCE_TITLE_UTF8_BYTES", "MAX_SOURCE_BODY_RAW_UTF8_BYTES",
                "MAX_SOURCE_BODY_NORMALIZED_UTF8_BYTES", "MAX_SOURCE_LANGUAGE_UTF8_BYTES")
        total = 0
        for key, tag in zip(_BD_SOURCE_FIELDS, tags):
            if key == "source_language" and value[key] is None:
                continue
            total += _bd_utf8_size(value[key], _BD_LIMITS[tag], tag)
        _bd_cap(total, "MAX_SOURCE_FIELD_UTF8_BYTES_TOTAL")
        tag = "MAX_SOURCE_CANONICAL_BYTES"
    elif scope == "metadata":
        _bd_native_tree(value, string_limit=_BD_LIMITS["MAX_METADATA_STRING_UTF8_BYTES"],
                        string_tag="MAX_METADATA_STRING_UTF8_BYTES")
        tag = "MAX_METADATA_CANONICAL_BYTES"
    elif scope == "resolution":
        _bd_native_tree(value, string_limit=_BD_LIMITS["MAX_ENTITY_STRING_UTF8_BYTES"],
                        string_tag="MAX_ENTITY_STRING_UTF8_BYTES")
        _bd_resolution_shape(value)
        tag = "MAX_RESOLUTION_CANONICAL_BYTES"
    else:
        _bd_fail("invalid_snapshot")
    return len(_bd_encoded(value, _BD_LIMITS[tag], tag))


def _bd_base64_prediction(value, encoded_tag, decoded_tag):
    if type(value) is not str:
        _bd_fail("input_shape_invalid")
    _bd_cap(len(value), encoded_tag)
    if not value.isascii() or len(value) % 4 or re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", value) is None:
        _bd_fail("input_base64_invalid")
    padding = len(value) - len(value.rstrip("="))
    if padding and len(value) < 4:
        _bd_fail("input_base64_invalid")
    predicted = 3 * (len(value) // 4) - padding
    _bd_cap(predicted, decoded_tag)
    return predicted


def _binding_diagnostic_decode_package(bundle):
    """Admit all document/base64 sizes before any decode; never parses F01."""
    _bd_native_tree(bundle, string_limit=_BD_LIMITS["MAX_JSON_STRING_UTF8_BYTES"],
                    string_tag="MAX_JSON_STRING_UTF8_BYTES", invalid="input_shape_invalid", package=True)
    if type(bundle) is not dict:
        _bd_fail("input_shape_invalid")
    article = bundle.get("article_input")
    identities = bundle.get("identity_inputs")
    relations = bundle.get("relation_inputs")
    artifacts = bundle.get("relationship_artifacts_base64")
    if type(article) is not dict or type(identities) is not list or type(relations) is not list or type(artifacts) is not dict:
        _bd_fail("input_shape_invalid")
    total = 0
    for document in [article, *identities, *relations]:
        if type(document) is not dict:
            _bd_fail("input_shape_invalid")
        total += len(_bd_encoded(document, _BD_LIMITS["MAX_F01_DOCUMENT_CANONICAL_BYTES"],
                                 "MAX_F01_DOCUMENT_CANONICAL_BYTES"))
        _bd_cap(total, "MAX_F01_DOCUMENTS_CANONICAL_BYTES_TOTAL")
    encoded = [(None, bundle.get("source_document_base64"), "MAX_SOURCE_B64_CHARS", "MAX_SOURCE_DOCUMENT_DECODED_BYTES")]
    encoded.extend((key, value, "MAX_ARTIFACT_B64_CHARS", "MAX_ARTIFACT_DECODED_BYTES") for key, value in artifacts.items())
    total = 0
    for _, value, encoded_tag, decoded_tag in encoded:
        total += _bd_base64_prediction(value, encoded_tag, decoded_tag)
        _bd_cap(total, "MAX_DECODED_BYTES_TOTAL")
    decoded = []
    for key, value, _, _ in encoded:
        try:
            data = base64.b64decode(value, validate=True)
        except (ValueError, binascii.Error):
            _bd_fail("input_base64_invalid")
        if base64.b64encode(data).decode("ascii") != value:
            _bd_fail("input_base64_invalid")
        decoded.append((key, data))
    nodes = assertions = 0
    for _, data in decoded:
        stats = _binding_diagnostic_json_preflight(data, decoded=True)
        nodes += stats["nodes"]
        assertions += stats["assertions"]
        _bd_cap(nodes, "MAX_DECODED_JSON_NODES_TOTAL")
        _bd_cap(assertions, "MAX_ASSERTIONS_TOTAL")
    for key, data in decoded:
        document = _bd_load_json(data, preflight=False)
        if key is None and type(document) is dict:
            for field, tag in (("title", "MAX_SOURCE_TITLE_UTF8_BYTES"), ("body", "MAX_SOURCE_BODY_RAW_UTF8_BYTES")):
                if field in document:
                    _bd_utf8_size(document[field], _BD_LIMITS[tag], tag, "input_shape_invalid")
    return {"source_document": decoded[0][1], "relationship_artifacts": {key: data for key, data in decoded[1:]}}


def _bd_envelope(bundle):
    if type(bundle) is not dict or set(bundle) != set(_BD_ENVELOPE_KEYS):
        _bd_fail("input_shape_invalid")
    if bundle["schema_version"] != "l01.readonly-audit.v1" or type(bundle["article_id"]) is not int or not 1 <= bundle["article_id"] <= _BD_LIMITS["ID_MAX"]:
        _bd_fail("input_shape_invalid")
    for field in ("observed_source_fields_sha256", "persisted_resolution_sha256"):
        if type(bundle[field]) is not str or _BD_HASH.fullmatch(bundle[field]) is None:
            _bd_fail("input_shape_invalid")
    if type(bundle["contexts"]) is not list or type(bundle["relationship_artifacts_base64"]) is not dict:
        _bd_fail("input_shape_invalid")
    for key in bundle["relationship_artifacts_base64"]:
        if type(key) is not str or _BD_HASH.fullmatch(key) is None:
            _bd_fail("input_shape_invalid")


def _bd_sha(value):
    return hashlib.sha256(_bd_encoded(value, _BD_LIMITS["MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL"],
                                     "MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL")).hexdigest()


def _binding_diagnostic_encode_output(value, *, as_json=True, scope="invocation"):
    tags = {"article": "MAX_ARTICLE_OUTPUT_JSON_BYTES", "invocation": "MAX_INVOCATION_OUTPUT_JSON_BYTES",
            "text": "MAX_TEXT_SUMMARY_UTF8_BYTES", "error": "MAX_ERROR_JSON_BYTES"}
    if scope not in tags:
        _bd_fail("input_shape_invalid")
    tag = tags[scope]
    if not as_json:
        _bd_utf8_size(value, _BD_LIMITS[tag], tag, "input_shape_invalid")
        return value.encode("utf-8")
    _bd_native_tree(value, string_limit=_BD_LIMITS["MAX_JSON_STRING_UTF8_BYTES"],
                    string_tag="MAX_JSON_STRING_UTF8_BYTES", invalid="input_shape_invalid")
    return _bd_encoded(value, _BD_LIMITS[tag], tag)


def _binding_diagnostic_error_details(error):
    code = error.args[0] if error.args and type(error.args[0]) is str and error.args[0] in _BD_CODES else "binding_input_invalid"
    payload = {"mode": "l01_binding_diagnostics", "status": "diagnostic/input_limit" if code == "input_limit" else "diagnostic/error",
               "code": code, "input_accepted": False, "articles": [], "proposed_bindings": []}
    limit = getattr(error, "diagnostic_limit", None)
    if type(limit) is str and limit in _BD_LIMITS:
        payload["limit"] = limit
    return code, payload


def _bd_gap(article_id, code):
    return {"article_id": article_id, "status": "not_found" if code == "article_not_found" else "input_gap",
            "code": code, "snapshot_accepted": False, "counts": None, "candidates": [], "proposed_bindings": []}


def diagnose_article_entity_bindings(article_ids, *, binding_input=None):
    """Read stored DTOs once; only explicit, scoped bytes may reach conditional core."""
    ids = _binding_diagnostic_validate_ids(article_ids, explicit=binding_input is not None)
    bundle = decoded = None
    if binding_input is not None:
        bundle = _bd_load_json(_binding_diagnostic_read_file(binding_input))
        _bd_envelope(bundle)
        if bundle["article_id"] != ids[0]:
            _bd_fail("input_scope_mismatch")
        decoded = _binding_diagnostic_decode_package(bundle)
    try:
        rows = list(NewsArticle.objects.filter(id__in=ids).values(*_BD_VALUES_FIELDS))
    except RecursionError:
        _bd_fail("input_limit")
    except Exception:
        _bd_fail("diagnostic_query_error")
    by_id = {row["id"]: row for row in rows}
    admitted = {}
    total = 0
    for article_id in ids:
        row = by_id.get(article_id)
        if row is None:
            admitted[article_id] = (None, None, "article_not_found")
            continue
        source = {field: row[field] for field in _BD_SOURCE_FIELDS}
        metadata = row["translation_metadata"]
        try:
            source_size = _binding_diagnostic_native_preflight(source, scope="source")
            metadata_size = _binding_diagnostic_native_preflight(metadata, scope="metadata")
            if type(metadata) is not dict:
                _bd_fail("invalid_snapshot")
            total += source_size + metadata_size
            _bd_cap(total, "MAX_ACCEPTED_INPUT_CANONICAL_BYTES_TOTAL")
            if "article_entity_resolution" not in metadata:
                gap = "full_snapshot_unavailable" if "entities" in metadata or "suppressed_entities" in metadata else "persisted_resolution_missing"
                admitted[article_id] = (source, None, gap)
                continue
            resolution = metadata["article_entity_resolution"]
            _binding_diagnostic_native_preflight(resolution, scope="resolution")
            admitted[article_id] = (source, resolution, None)
        except CommandError as error:
            if error.args != ("invalid_snapshot",):
                raise
            admitted[article_id] = (None, None, "invalid_snapshot")
    if bundle is not None:
        source, resolution, gap = admitted[ids[0]]
        if gap:
            _bd_fail(gap)
        if bundle["observed_source_fields_sha256"] != _bd_sha(source) or bundle["persisted_resolution_sha256"] != _bd_sha(resolution):
            _bd_fail("input_scope_mismatch")
    articles = []
    for article_id in ids:
        source, resolution, gap = admitted[article_id]
        if gap:
            articles.append(_bd_gap(article_id, gap))
            continue
        candidates = []
        for entity in resolution["entities"]:
            candidate = {"entity_payload_sha256": _bd_sha(entity),
                         "occurrence": {key: entity[key] for key in ("field_name", "start", "end", "matched_text")},
                         "reasons": ["snapshot_unversioned", "missing_identity_and_relationship_inputs"]}
            for key in ("entity_type", "term_type", "classification"):
                if key in entity:
                    candidate[key] = entity[key]
            candidates.append(candidate)
        result = {"article_id": article_id, "status": "candidate_only", "snapshot_accepted": True,
                  "counts": {key: len(resolution[key]) for key in _BD_RESOLUTION_KEYS if key != "source_language"},
                  "candidates": candidates, "proposed_bindings": [], "persisted_snapshot_version": "unversioned",
                  "canonical_article_mapping": "unproven", "source_coordinate_binding": "unproven",
                  "source_authentication": "unproven", "input_completeness": "unproven"}
        if bundle is not None:
            try:
                article = binding_f01.parse_input(bundle["article_input"])
                identities = [binding_f01.parse_input(value) for value in bundle["identity_inputs"]]
                relations = [binding_f01.parse_input(value) for value in bundle["relation_inputs"]]
            except RecursionError:
                _bd_fail("input_limit")
            except (ValueError, TypeError, KeyError):
                _bd_fail("f01_invalid")
            try:
                conditional = plan_article_entity_bindings(
                    resolution, article_input=article, identity_inputs=identities, relation_inputs=relations,
                    source_document=decoded["source_document"], relationship_artifacts=decoded["relationship_artifacts"],
                    contexts=bundle["contexts"])
            except RecursionError:
                _bd_fail("input_limit")
            except BindingInputError:
                _bd_fail("binding_input_invalid")
            result["explicit_input_audit"] = {"scope": "conditional_structural_proposals_only", "core_result": conditional}
        _binding_diagnostic_encode_output(result, as_json=True, scope="article")
        articles.append(result)
    payload = {"mode": "l01_binding_diagnostics", "status": "completed_with_gaps", "input_accepted": True,
               "article_ids": ids, "articles": articles, "proposed_bindings": []}
    return payload
