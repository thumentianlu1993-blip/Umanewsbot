"""仅比较数字表面片段，提供差异证据，不判定事实真伪。"""

import re


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _numeric_spans(text: str) -> dict:
    spans = {}
    for match in _NUMBER_RE.finditer(text):
        spans.setdefault(match.group(), []).append([match.start(), match.end()])
    return spans


def audit_numeric_surfaces(source_text: str, translated_text: str) -> dict:
    """核对一对已清洗、相互对应的完整字段中的原始数字 token。

    不归一化数字、单位或日期，不配对不同 token，不推断事实归属。
    每个差异保留双方全部出现位置；跨度是各自输入的半开字符位置。
    表面一致或没有数字都不代表事实审校通过。
    """
    if type(source_text) is not str or type(translated_text) is not str:
        raise TypeError("source_text and translated_text must be strings")

    source_spans = _numeric_spans(source_text)
    translated_spans = _numeric_spans(translated_text)
    differences = []
    # 源文首次出现顺序在先，再追加仅在译文出现的 token。
    for token in dict.fromkeys([*source_spans, *translated_spans]):
        original = source_spans.get(token, [])
        translated = translated_spans.get(token, [])
        source_count = len(original)
        translated_count = len(translated)
        if source_count == translated_count:
            continue
        differences.append({
            "token": token,
            "code": "source_excess" if source_count > translated_count else "translation_excess",
            "source_count": source_count,
            "translated_count": translated_count,
            "source_spans": original,
            "translated_spans": translated,
        })

    if not source_spans and not translated_spans:
        status = "no_numeric_lexemes"
    elif differences:
        status = "surface_difference"
    else:
        status = "surface_match"

    return {
        "comparison_scope": "raw_numeric_lexemes",
        "fact_verdict": "not_assessed",
        "status": status,
        "source_token_count": sum(len(spans) for spans in source_spans.values()),
        "translated_token_count": sum(len(spans) for spans in translated_spans.values()),
        "differences": differences,
    }
