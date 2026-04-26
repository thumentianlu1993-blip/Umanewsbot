from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag


BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "dd",
    "div",
    "dl",
    "dt",
    "fieldset",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def extract_article_text(node: Tag | BeautifulSoup | None) -> str:
    if node is None:
        return ""

    parts: list[str] = []

    def ensure_newline() -> None:
        if not parts:
            return
        if not parts[-1].endswith("\n"):
            parts.append("\n")

    def visit(current: Tag | BeautifulSoup) -> None:
        for child in current.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text:
                    parts.append(text)
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in {"script", "style"}:
                continue
            if child.name == "br":
                ensure_newline()
                continue

            is_block = child.name in BLOCK_TAGS
            if is_block:
                ensure_newline()
            visit(child)
            if is_block:
                ensure_newline()

    visit(node)
    return normalize_whitespace("".join(parts))
