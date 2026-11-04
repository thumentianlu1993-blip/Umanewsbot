"""Candidate-only ordinary draft seam. No issuer, route, persistence or provider."""
import re
from stable.services import content_review_decisions as kernel
from stable.services.text import normalize_whitespace

class _Gap(ValueError):
    pass

def _require(condition, code):
    if not condition:
        raise _Gap(code)

def _keys(value, names, code):
    _require(type(value) is dict, code)
    _require(all(type(k) is str for k in value) and set(value) == set(names.split()), code)

def _text(value):
    return type(value) is str and bool(value.strip())

def _review(snapshot, context, profile, attempt, verdict):
    sc, cc = 'snapshot_shape_invalid', 'context_shape_invalid'
    _keys(snapshot, 'source_site source_article_id source_url canonical_source_site body_ja_raw body_ja_normalized metadata', sc)
    _require(all(_text(snapshot[k]) for k in ['source_site','source_article_id','source_url','body_ja_raw','body_ja_normalized']), sc)
    _require(snapshot['canonical_source_site'] is None or _text(snapshot['canonical_source_site']), sc)
    meta = snapshot['metadata']
    _keys(meta, 'body_parse_status body_selector body_cleaning source_url discovered_source_site', sc)
    _require(all(_text(meta[k]) for k in ['body_parse_status','body_selector','source_url','discovered_source_site']), sc)
    _require(meta['body_parse_status'] == 'ok', sc)
    trace = meta['body_cleaning']
    _require(type(trace) is dict and _text(trace.get('body_html_sha256')) and type(trace.get('after_text')) is str, sc)
    _keys(context, 'expected capture_ref policy_ref protection template', cc)
    _require(_text(context['capture_ref']) and _text(context['policy_ref']) and type(context['protection']) is dict and type(context['template']) is dict, cc)
    expected = context['expected']
    _keys(expected, 'source_site source_article_id source_url body_html_sha256', cc)
    _require(all(_text(v) for v in expected.values()) and re.fullmatch('[0-9a-f]{64}', expected['body_html_sha256']) is not None, cc)
    _require(snapshot['source_site'] == meta['discovered_source_site'] == expected['source_site'] and snapshot['source_article_id'] == expected['source_article_id'] and snapshot['source_url'] == meta['source_url'] == expected['source_url'], 'source_binding_mismatch')
    _require(trace['body_html_sha256'] == expected['body_html_sha256'], 'capture_binding_mismatch')
    _require(trace['after_text'] == snapshot['body_ja_raw'] and normalize_whitespace(snapshot['body_ja_raw']) == snapshot['body_ja_normalized'], 'body_binding_mismatch')
    packet = dict(schema_version=1, source=dict(site=snapshot['source_site'],article_ref=snapshot['source_article_id'],capture_ref=context['capture_ref']),
        capture_sha256=trace['body_html_sha256'],policy_ref=context['policy_ref'],body_parse_status=meta['body_parse_status'],
        protection=context['protection'],template=context['template'],trace=trace)
    return dict(adapter_gaps=[], review=kernel.review_candidate(packet, verdict, profile=profile, attempt=attempt))

def _limits(value):
    code = 'copy_limits_invalid'
    _require(type(value) is dict and len(value) == 6, code)
    _keys(value, 'input_bytes output_bytes field_bytes container_items nodes depth', code)
    _require(all(type(v) is int and 0 < v <= 2147483647 for v in value.values()), code)
    _require(value['depth'] <= 64, code)
    return dict(value)


def _walk(value, limits, byte_limit, *, clone):
    """Finite builtin-tree accounting before allocation; no encoding/user hooks."""
    size, nodes, ancestors = 0, 0, set()

    def emit(count):
        nonlocal size
        size += count
        _require(size <= byte_limit, 'input_byte_limit')

    def walk(item, depth):
        nonlocal nodes
        kind = type(item)
        _require(kind is dict or kind is list or kind is str or kind is int or kind is bool or item is None, 'input_type_invalid')
        if (kind is dict or kind is list):
            _require(id(item) not in ancestors, 'input_cycle')
        _require(depth <= limits['depth'], 'input_depth_limit')
        nodes += 1
        _require(nodes <= limits['nodes'], 'input_node_limit')
        if (kind is dict or kind is list):
            _require(len(item) <= limits['container_items'], 'input_container_limit')
            ancestors.add(id(item))
            emit(1)
            out = ({} if kind is dict else []) if clone else None
            for index, entry in enumerate(item):
                if index:
                    emit(1)
                if kind is dict:
                    _require(type(entry) is str, 'input_type_invalid')
                    walk(entry, depth + 1)
                    emit(1)
                    child = walk(item[entry], depth + 1)
                    if clone:
                        out[entry] = child
                else:
                    child = walk(entry, depth + 1)
                    if clone:
                        out.append(child)
            emit(1)
            ancestors.remove(id(item))
            return out
        if kind is str:
            _require(len(item) <= limits['field_bytes'], 'input_field_limit')
            raw_size = 0
            emit(1)
            for char in item:
                point = ord(char)
                _require(not 0xD800 <= point <= 0xDFFF, 'input_type_invalid')
                width = 1 if point < 128 else 2 if point < 2048 else 3 if point < 65536 else 4
                raw_size += width
                _require(raw_size <= limits['field_bytes'], 'input_field_limit')
                wire_width = 2 if char in '\"\\\b\f\n\r\t' else 6 if point < 32 else width
                emit(wire_width)
            emit(1)
        elif kind is int:
            _require(item.bit_length() <= 63, 'input_type_invalid')
            emit(len(str(item)))
        elif kind is bool:
            emit(4 if item else 5)
        else:
            emit(4)
        return item if clone else None

    return walk(value, 0)


def _bounded_copy(value, limits, byte_limit):
    _walk(value, limits, byte_limit, clone=False)
    return _walk(value, limits, byte_limit, clone=True)


def shadow_review_draft(snapshot, *, caller_context, profile, copy_limits, attempt, verdict):
    """Only ordinary synchronous copies; explicit limits, no capture authentication."""
    try:
        limits = _limits(copy_limits)
        frame = _bounded_copy(dict(snapshot=snapshot, caller_context=caller_context,
            profile=profile, attempt=attempt, verdict=verdict), limits, limits['input_bytes'])
        _require(frame['verdict'] is None or type(frame['verdict']) is dict, 'input_type_invalid')
        result = _review(frame['snapshot'], frame['caller_context'], frame['profile'], frame['attempt'], frame['verdict'])
        try:
            return _bounded_copy(result, limits, limits['output_bytes'])
        except _Gap:
            raise _Gap('output_copy_limit') from None
    except _Gap as exc:
        # Only fixed internal codes, with no user fields; control envelope exemption.
        return dict(adapter_gaps=[str(exc)], review=None)
