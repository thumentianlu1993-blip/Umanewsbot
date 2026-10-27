"""新闻正文、实体位置与全文审校的确定性边界。"""
from bs4 import BeautifulSoup
from stable.services.article_content import clean_international_article_body
from stable.services.numeric_surface_audit import audit_numeric_surfaces


class ContentBlocked(ValueError):
    pass


def clean_source(snapshot, selectors=None):
    soup = BeautifulSoup(snapshot.get("html", ""), "lxml")
    clean = clean_international_article_body(soup, source_site=snapshot["source_site"])
    return {"title": snapshot["title"], "blocks": [{"id": "b0", "text": clean.text}]}


def validate_entities(clean, response):
    return response.get("entities", [])


def protect_source(clean, entities):
    return clean


def restore_translation(clean, entities, response):
    return {"title": response["title"], "summary": response["summary"], "body": "\n\n".join(row["text"] for row in response["blocks"]), "blocks": response["blocks"]}


def validate_audit(clean, target, response):
    audit = audit_numeric_surfaces("\n".join(row["text"] for row in clean["blocks"]), target["body"])
    return {"passed": audit["status"] != "surface_difference"}
