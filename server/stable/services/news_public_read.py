"""精确稿件的只读展示对象；公开内容、关系均来自该回执。"""
from types import SimpleNamespace
from django.db.models import Q
from stable.models import ArticleHorseLink, ArticleRaceLink, HorseProfile, RaceEvent, RacingRegion
from stable.services.news_feed import visible_entries


def display_article(entry):
    if entry.kind == "legacy":
        article = entry.article
        article.public_horse_links = list(article.horse_links.filter(status__in=["auto", "manual"], horse_profile__review_status="published").select_related("horse_profile"))
        article.public_race_links = list(article.race_links.filter(status__in=["auto", "manual"], event__visibility_status="published").select_related("event"))
        article.public_entry_id = entry.pk
        return article
    receipt = entry.receipt
    relations = receipt.verified_relations
    horses = HorseProfile.objects.filter(pk__in=relations.get("horse_ids", []), review_status="published")
    races = RaceEvent.objects.filter(pk__in=relations.get("race_ids", []), visibility_status="published")
    return SimpleNamespace(
        pk=receipt.pk, id=receipt.pk, source_article_id=entry.article_id, public_entry_id=entry.pk,
        receipt=receipt, public_path=receipt.public_path, public_list_detail_url=receipt.public_path,
        effective_title=receipt.content["title"], effective_body=receipt.content["body"], effective_summary=receipt.content["summary"],
        published_to_web_at=receipt.published_at, published_at=receipt.published_at, racing_region=entry.primary_region,
        get_racing_region_display=lambda: dict(RacingRegion.choices).get(entry.primary_region, entry.primary_region),
        cover_image_url=receipt.content.get("cover_url", ""), source_url=receipt.content.get("source_url", ""),
        public_horse_links=[SimpleNamespace(horse_profile=horse) for horse in horses],
        public_race_links=[SimpleNamespace(event=race) for race in races],
    )


def related_horse_entries(horse_ids, *, primary_id=None, limit=12):
    horse_ids = sorted(set(horse_ids))
    if not horse_ids or limit <= 0:
        return []
    p01 = Q(pk__in=[])
    for horse_id in horse_ids:
        p01 |= Q(kind="p01", receipt__verified_relations__horse_ids__contains=[horse_id])
    legacy = Q(kind="legacy", article__horse_links__horse_profile_id__in=horse_ids,
        article__horse_links__horse_profile__review_status="published", article__horse_links__status__in=["auto", "manual"])
    rows = visible_entries().filter(p01 | legacy).distinct().order_by("-sort_time", "-feed_seq")[:limit]
    profiles = {horse.pk: horse for horse in HorseProfile.objects.filter(pk__in=horse_ids, review_status="published")}
    result = []
    for row in rows:
        article = display_article(row)
        linked = [link.horse_profile for link in article.public_horse_links if link.horse_profile.pk in profiles]
        if not linked:
            continue
        linked.sort(key=lambda horse: (horse.pk != primary_id, horse.pk))
        profile = linked[0]
        result.append({"article": article, "horse_profile": profile, "source_horse_profile": profile,
                       "is_descendant": primary_id is not None and profile.pk != primary_id})
    return result


def related_race_articles(event_id, *, limit=30):
    rows = visible_entries().filter(
        Q(kind="p01", receipt__verified_relations__race_ids__contains=[event_id]) |
        Q(kind="legacy", article__race_links__event_id=event_id, article__race_links__status__in=["auto", "manual"])
    ).distinct().order_by("-sort_time", "-feed_seq")[:limit]
    groups = {"pre_race": [], "post_race": [], "related": []}
    for row in rows:
        if row.kind == "p01":
            group = "related"
        else:
            link = row.article.race_links.filter(event_id=event_id, status__in=["auto", "manual"]).first()
            group = link.link_type if link and link.link_type in groups else "related"
        groups[group].append(display_article(row))
    return groups
