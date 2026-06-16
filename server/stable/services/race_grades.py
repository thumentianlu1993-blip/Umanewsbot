from __future__ import annotations

import re
import unicodedata

from stable.models import RaceGrade


RACE_PRIORITY_BY_GRADE = {
    RaceGrade.G1: "P0",
    RaceGrade.JPN1: "P0",
    RaceGrade.G2: "P1",
    RaceGrade.JPN2: "P1",
    RaceGrade.JG1: "P1",
    RaceGrade.G3: "P2",
    RaceGrade.JPN3: "P2",
    RaceGrade.JG2: "P2",
    RaceGrade.JG3: "P2",
    RaceGrade.LISTED: "P2",
    RaceGrade.OPEN: "P2",
    RaceGrade.THREE_WIN: "P3",
    RaceGrade.TWO_WIN: "P3",
    RaceGrade.ONE_WIN: "P3",
    RaceGrade.NEWCOMER: "P3",
    RaceGrade.MAIDEN: "P3",
    RaceGrade.LOCAL_GRADE: "P2",
    RaceGrade.OTHER: "P3",
}

RACE_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def normalize_race_grade(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip()
    if not text:
        return ""
    upper = text.upper()

    explicit = {
        "G1": RaceGrade.G1,
        "GI": RaceGrade.G1,
        "GⅠ": RaceGrade.G1,
        "G2": RaceGrade.G2,
        "GII": RaceGrade.G2,
        "GⅡ": RaceGrade.G2,
        "G3": RaceGrade.G3,
        "GIII": RaceGrade.G3,
        "GⅢ": RaceGrade.G3,
        "JPN1": RaceGrade.JPN1,
        "JPNI": RaceGrade.JPN1,
        "JPNⅠ": RaceGrade.JPN1,
        "JPN2": RaceGrade.JPN2,
        "JPNII": RaceGrade.JPN2,
        "JPNⅡ": RaceGrade.JPN2,
        "JPN3": RaceGrade.JPN3,
        "JPNIII": RaceGrade.JPN3,
        "JPNⅢ": RaceGrade.JPN3,
        "JG1": RaceGrade.JG1,
        "JG2": RaceGrade.JG2,
        "JG3": RaceGrade.JG3,
        "J-G1": RaceGrade.JG1,
        "J-G2": RaceGrade.JG2,
        "J-G3": RaceGrade.JG3,
        "J・G1": RaceGrade.JG1,
        "J・G2": RaceGrade.JG2,
        "J・G3": RaceGrade.JG3,
        "L": RaceGrade.LISTED,
        "LISTED": RaceGrade.LISTED,
        "OP": RaceGrade.OPEN,
        "OPEN": RaceGrade.OPEN,
        "3WIN": RaceGrade.THREE_WIN,
        "2WIN": RaceGrade.TWO_WIN,
        "1WIN": RaceGrade.ONE_WIN,
        "NEWCOMER": RaceGrade.NEWCOMER,
        "MAIDEN": RaceGrade.MAIDEN,
        "LOCAL_GRADE": RaceGrade.LOCAL_GRADE,
        "OTHER": RaceGrade.OTHER,
    }
    if upper in explicit:
        return explicit[upper]

    patterns = [
        (RaceGrade.JG1, r"J[\s・.-]*G(?:1|I|Ⅰ)"),
        (RaceGrade.JG2, r"J[\s・.-]*G(?:2|II|Ⅱ)"),
        (RaceGrade.JG3, r"J[\s・.-]*G(?:3|III|Ⅲ)"),
        (RaceGrade.JPN1, r"JPN\s*(?:1|I|Ⅰ)"),
        (RaceGrade.JPN2, r"JPN\s*(?:2|II|Ⅱ)"),
        (RaceGrade.JPN3, r"JPN\s*(?:3|III|Ⅲ)"),
        (RaceGrade.G1, r"(?:^|[^A-Z0-9])G\s*(?:1|I|Ⅰ)(?:[^A-Z0-9]|$)"),
        (RaceGrade.G2, r"(?:^|[^A-Z0-9])G\s*(?:2|II|Ⅱ)(?:[^A-Z0-9]|$)"),
        (RaceGrade.G3, r"(?:^|[^A-Z0-9])G\s*(?:3|III|Ⅲ)(?:[^A-Z0-9]|$)"),
        (RaceGrade.LISTED, r"(?:LISTED|リステッド|リステッド競走|(?:^|[^A-Z])L(?:[^A-Z]|$))"),
        (RaceGrade.OPEN, r"(?:OPEN|オープン|オープン特別|(?:^|[^A-Z])OP(?:[^A-Z]|$))"),
        (RaceGrade.THREE_WIN, r"(?:3勝|３勝|3WIN|3勝クラス)"),
        (RaceGrade.TWO_WIN, r"(?:2勝|２勝|2WIN|2勝クラス)"),
        (RaceGrade.ONE_WIN, r"(?:1勝|１勝|1WIN|1勝クラス)"),
        (RaceGrade.NEWCOMER, r"(?:新馬|メイクデビュー)"),
        (RaceGrade.MAIDEN, r"(?:未勝利)"),
    ]
    for grade, pattern in patterns:
        if re.search(pattern, upper):
            return grade
    return ""


def race_priority_for_grade(grade: str) -> str:
    normalized = normalize_race_grade(grade)
    if not normalized:
        return ""
    return RACE_PRIORITY_BY_GRADE.get(normalized, "P3")


def better_race_priority(current: str, candidate: str) -> str:
    if not candidate:
        return current
    if not current:
        return candidate
    return candidate if RACE_PRIORITY_ORDER.get(candidate, 99) < RACE_PRIORITY_ORDER.get(current, 99) else current
