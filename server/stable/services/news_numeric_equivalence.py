"""P01限定格式的数字等价比较；不推断事实归属，不修复模型证据跨度。"""
from collections import defaultdict
from datetime import date
from decimal import Decimal
import re
import unicodedata


MONTHS = "January February March April May June July August September October November December".split()
MONTH_NUMBER = {name.casefold(): index for index, name in enumerate(MONTHS, 1)}
MONTH_PATTERN = "(?:" + "|".join(MONTHS) + ")"
NORMALIZATION = "p01-explicit-numeric-equivalence-v2"


def explicit_date(text):
    """只解析完整且无歧义的年月日，不接受日期子串、推测年份或斜杠日期。"""
    text = unicodedata.normalize("NFKC", text).strip()
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        parts = tuple(map(int, match.groups()))
    else:
        match = re.fullmatch(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
        if match:
            parts = tuple(map(int, match.groups()))
        else:
            match = re.fullmatch(rf"({MONTH_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", text, re.I)
            if match:
                parts = (int(match[3]), MONTH_NUMBER[match[1].casefold()], int(match[2]))
            else:
                match = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_PATTERN}),?\s+(\d{{4}})", text, re.I)
                if not match:
                    return None
                parts = (int(match[3]), MONTH_NUMBER[match[2].casefold()], int(match[1]))
    try:
        return date(*parts).isoformat()
    except ValueError:
        return None


def same_explicit_date(canonical, original):
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", canonical)
                and explicit_date(canonical) is not None
                and explicit_date(canonical) == explicit_date(original))


_CN_DIGITS = {char: value for value, char in enumerate("零一二三四五六七八九")}
_CN_DIGITS.update({"〇": 0, "两": 2})
_CN_SMALL_UNITS = {"十": 10, "百": 100, "千": 1000}


def _chinese_integer(text):
    if all(char in _CN_DIGITS for char in text):
        return int("".join(str(_CN_DIGITS[char]) for char in text))
    total, digit, previous = 0, 0, 10000
    for char in text:
        if char in _CN_DIGITS:
            digit = _CN_DIGITS[char]
        else:
            unit = _CN_SMALL_UNITS[char]
            if unit >= previous:
                raise ValueError("noncanonical_chinese_number")
            total += (digit or 1) * unit
            digit, previous = 0, unit
    return total + digit


def _decimal(value):
    # 格式转换使用十进制定点运算，不做容差或四舍五入。
    return format(Decimal(value).normalize(), "f")


_CURRENCY = {"€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR", "欧元": "EUR",
             "£": "GBP", "gbp": "GBP", "英镑": "GBP", "usd": "USD", "us$": "USD",
             "美元": "USD", "美金": "USD", "hkd": "HKD", "hk$": "HKD", "港元": "HKD", "港币": "HKD"}
_CURRENCY_PATTERN = "(?:" + "|".join(re.escape(key) for key in sorted(_CURRENCY, key=len, reverse=True)) + ")"
_SCALES = {"": 1, "thousand": 1000, "million": 1000000, "billion": 1000000000,
           "千": 1000, "万": 10000, "百万": 1000000, "千万": 10000000, "亿": 100000000}
_SCALE_PATTERN = r"(?:thousand\b|million\b|billion\b|千万|百万|千|万|亿)"
_AMOUNT = r"[+-]?\d+(?:\.\d+)?"


def numeric_surface(text):
    """返回比较用文本；跨度只指向此规范文本，不冒充原文证据跨度。"""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    # 中文数词只在数值单位/序数语境处理，不替换普通词或任意专名。
    cn = r"[零〇一二两三四五六七八九十百千]+"
    def chinese(match):
        try:
            value = str(_chinese_integer(match[0]))
            # 月份、级别和比例具有明确数值含义；“一年/一次”等也可能只是
            # 英文不定冠词的自然译法，只作为匹配另一侧明确数字的备选证据。
            tail = text[match.end():]
            explicit = re.match(rf"\s*(?:月|成|割|级|班|档|万|亿)|[、,]\s*{cn}[成割]", tail)
            return value if explicit else f"〈word:{value}〉"
        except ValueError:
            return match[0]
    text = re.sub(r"(?<![\d.零〇一二两三四五六七八九十百千])" + cn + rf"(?=\s*(?:月|年|日|岁|成|割|胜|名|档|班|级|趟|次|届|个|匹|头|万|亿)|[、,]\s*{cn}[成割])", chinese, text)
    words = {word: number for number, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
    words.update({word: number for number, word in enumerate(
        "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split(), 1)})
    words.update({"dual": 2, "double": 2, "twice": 2, "triple": 3, "thrice": 3})
    word_pattern = "(?:" + "|".join(sorted(words, key=len, reverse=True)) + ")"
    # 不支持的复合表达整体保留，不能把 twenty-six 中的 six 当作 6 的证据。
    atom = "(?:" + word_pattern + "|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion|half|halves|quarter|quarters|thirds|fourths|fifths|sixths|sevenths|eighths|ninths|tenths|dozen|score|negative|minus|positive|plus)"
    def english_number(match):
        word = match[0].casefold()
        if word not in words:
            return match[0]
        if re.search(r"\b(?:gate|stall|barrier|class|group|grade)\s+$", text[:match.start()], re.I):
            return str(words[word])
        return f"〈word:{words[word]}〉"
    text = re.sub(rf"\b(?:[a-z]+[-‐‑‒–—−])+[a-z]+\b|\b{atom}(?:(?:[\s\-‐‑‒–—−]+)(?:(?:and(?:\s+a)?|point)[\s\-‐‑‒–—−]+)?{atom})*\b", english_number, text, flags=re.I)
    for number, month in enumerate(MONTHS, 1):
        text = re.sub(r"(\b\d{1,2}(?:st|nd|rd|th)?\s+)" + month + r"\b", lambda m: m[1] + str(number), text, flags=re.I)
        text = re.sub(r"\b" + month + r"(?=\s+\d{1,2}\b)", str(number), text, flags=re.I)
        text = re.sub(r"(\b(?:in|during|on|until|since|from|after|before|of)\s+)" + month + r"\b",
                      lambda m: m[1] + str(number), text, flags=re.I)

    def money(match):
        currency = _CURRENCY[match['currency'].casefold()]
        scale = _SCALES[(match['scale'] or '').casefold()]
        amount = _decimal(Decimal(match['amount']) * scale)
        return f"〈money:{currency}:{amount}〉"
    text = re.sub(rf"(?P<currency>{_CURRENCY_PATTERN})\s*(?P<amount>{_AMOUNT})\s*(?P<scale>{_SCALE_PATTERN})?",
                  money, text, flags=re.I)
    text = re.sub(rf"(?P<amount>{_AMOUNT})\s*(?P<scale>{_SCALE_PATTERN})?\s*(?P<currency>{_CURRENCY_PATTERN})",
                  money, text, flags=re.I)

    def clock(match):
        hour, minute = int(match['hour']), int(match['minute'])
        meridiem = match.groupdict().get('meridiem', '').casefold()
        if minute > 59 or hour > 23 or (meridiem and not 1 <= hour <= 12):
            return match[0]
        if meridiem:
            hour = hour % 12 + (12 if meridiem == 'p' else 0)
        return f"〈time:{hour:02d}:{minute:02d}〉"
    text = re.sub(r"\b(?P<hour>\d{1,2})[.:](?P<minute>\d{2})\s*(?P<meridiem>[ap])\.?m\.?\b", clock, text, flags=re.I)
    def chinese_clock(match):
        period, hour, minute = match[1], int(match[2]), int(match[3])
        if minute > 59 or hour > 23 or (period == '凌晨' and hour > 12) or (period in {'上午', '下午', '中午'} and not 1 <= hour <= 12):
            return match[0]
        if period in {'下午', '中午'}:
            hour = hour % 12 + 12
        elif period in {'上午', '凌晨'}:
            hour %= 12
        return f"〈time:{hour:02d}:{minute:02d}〉"
    text = re.sub(r"(凌晨|上午|下午|中午)?\s*(\d{1,2})[时点](\d{1,2})分", chinese_clock, text)
    # 已规范的time标记必须整体跳过，不能对其内部的数字再归一化。
    text = re.sub(r"〈[^〉]+〉|(?<![\dA-Za-z:.])(?P<hour>\d{1,2}):(?P<minute>\d{2})(?![\dA-Za-z:]|\.\d)",
                  lambda m: m[0] if m[0].startswith('〈') else clock(m), text)
    return text


_TOKEN = re.compile(r"〈(?:money|time|word):[^〉]+〉|\d+(?:\.\d+)?")


def _token_evidence(text):
    normalized = numeric_surface(text)
    spans, required = defaultdict(list), defaultdict(list)
    for match in _TOKEN.finditer(normalized):
        optional = match[0].startswith('〈word:')
        value = _decimal(match[0][6:-1]) if optional else match[0] if match[0].startswith('〈') else _decimal(match[0])
        spans[value].append([match.start(), match.end()])
        if not optional:
            required[value].append([match.start(), match.end()])
    return dict(spans), dict(required)


def numeric_tokens(text, *, include_optional=True):
    all_tokens, required = _token_evidence(text)
    return all_tokens if include_optional else required


def audit_equivalent_numbers(source, target):
    original, source_required = _token_evidence(source)
    translated, target_required = _token_evidence(target)
    differences = []
    for token in dict.fromkeys([*original, *translated]):
        left, right = original.get(token, []), translated.get(token, [])
        source_count, target_count = len(source_required.get(token, [])), len(target_required.get(token, []))
        if source_count > len(right) or target_count > len(left):
            differences.append({"token": token, "code": "source_excess" if source_count > len(right) else "translation_excess",
                                "source_count": len(left), "translated_count": len(right),
                                "source_required_count": source_count, "translated_required_count": target_count,
                                "source_spans": left, "translated_spans": right})
    return {"comparison_scope": "normalized_numeric_lexemes", "normalization": NORMALIZATION,
            "span_scope": "normalized_comparison_text", "fact_verdict": "not_assessed",
            "status": "surface_difference" if differences else "surface_match" if original else "no_numeric_lexemes",
            "source_token_count": sum(map(len, original.values())),
            "translated_token_count": sum(map(len, translated.values())), "differences": differences}
