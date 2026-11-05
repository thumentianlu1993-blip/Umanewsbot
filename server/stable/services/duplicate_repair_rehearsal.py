"""隔离恢复演练的纯数据规划；不提供数据库或网络入口。"""
import copy
import hashlib
import json
from collections import defaultdict
from datetime import datetime

NEWS = "stable_newsarticle"
TERM = "stable_termcandidate"
EVIDENCE = "stable_termcandidateevidence"
WINDOW = "stable_windowcandidatedecision"
MOVABLE_NEWS = {"stable_newssnapshot", "stable_translationrun", "stable_automationlog", WINDOW}
PROTECTED = {"stable_qqpushdelivery", "stable_windowtargetdecision"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_plan(before, news_keep_ids, rejected_keep_ids, *, observed_at=None):
    after = copy.deepcopy(before)
    mappings = {}
    for table, keys in [(NEWS, ("source_site", "source_article_id")),
                        (TERM, ("term_type", "source_language", "normalized_key"))]:
        groups = defaultdict(list)
        ids = set()
        for row in before[table]:
            if row["id"] in ids or any(not isinstance(row.get(k), str) or not row[k] for k in keys):
                raise ValueError("duplicate primary key or invalid identity")
            ids.add(row["id"])
            groups[tuple(row[k] for k in keys)].append(row)
        mapping, keep = {}, []
        selected, rejected = set(), set()
        for rows in groups.values():
            if len(rows) < 2:
                raise ValueError("scope must contain complete duplicate groups only")
            if table == NEWS:
                anchors = [r for r in rows if r["id"] in news_keep_ids]
                if len(anchors) != 1:
                    raise ValueError("each news group requires one reviewed anchor")
                anchor = anchors[0]; selected.add(anchor["id"])
                for field in ("source_url", "title_ja"):
                    if len({r.get(field) for r in rows}) != 1:
                        raise ValueError("news identity evidence differs")
                for row in rows:
                    # save()为草稿也分配slug；公开视图还要求published及发布时间。
                    if row["id"] != anchor["id"] and (row.get("published_to_web_at")
                            or row.get("workflow_status") == "published" or row.get("manually_edited_fields")):
                        raise ValueError("cannot remove public or manually edited news identity")
            else:
                if len({r["source_ja"] for r in rows}) != 1:
                    raise ValueError("term source text differs")
                for row in rows:
                    if any(row.get(f) for f in ("target_zh", "suggested_target_zh", "aliases_ja", "aliases_zh",
                            "accepted_term_id", "merged_into_term_id", "merged_into_candidate_id")):
                        raise ValueError("term names or formal identities require separate review")
                    if row["status"] not in {"pending", "rejected"}:
                        raise ValueError("unexpected term review state")
                    if row["status"] == "pending" and row.get("reviewed_at"):
                        raise ValueError("pending term has reviewed history")
                reviewed = [r for r in rows if r["status"] == "rejected"]
                if len(reviewed) > 1 or (reviewed and reviewed[0]["id"] not in rejected_keep_ids):
                    raise ValueError("rejected state needs explicit unique anchor")
                anchor = reviewed[0] if reviewed else min(rows, key=lambda r: r["id"])
                if reviewed: rejected.add(anchor["id"])
            mapping.update({r["id"]: anchor["id"] for r in rows})
            keep.append(copy.deepcopy(anchor))
        if table == NEWS and selected != set(news_keep_ids):
            raise ValueError("news anchor scope differs")
        if table == TERM and rejected != set(rejected_keep_ids):
            raise ValueError("rejected anchor scope differs")
        mappings[table] = mapping
        after[table] = keep

    allowed = {NEWS, TERM, EVIDENCE, "stable_productionwindow", *MOVABLE_NEWS, *PROTECTED}
    for table, rows in before.items():
        if table not in allowed and rows:
            raise ValueError("unreviewed inbound relationship: " + table)
    for row in before.get("stable_productionwindow", []):
        lease = row.get("lease_expires_at")
        if row["status"] != "succeeded":
            raise ValueError("active or leased production window")
        if lease and (not observed_at or not row.get("finished_at") or
                datetime.fromisoformat(lease) >= datetime.fromisoformat(observed_at) or
                datetime.fromisoformat(row["finished_at"]) >= datetime.fromisoformat(observed_at)):
            raise ValueError("window lease has not demonstrably expired")
    for table in PROTECTED:
        for row in before.get(table, []):
            if mappings[NEWS].get(row["article_id"]) != row["article_id"]:
                raise ValueError("delivery/target decision must stay on its original anchor")
            if table == "stable_qqpushdelivery" and row["status"] != "sent":
                raise ValueError("unfinished delivery")
    for table in MOVABLE_NEWS:
        for row in after.get(table, []):
            row["article_id"] = mappings[NEWS][row["article_id"]]

    def collapse(table, keys, compare, union_fields=()):
        groups = defaultdict(list)
        for row in after.get(table, []): groups[tuple(row[k] for k in keys)].append(row)
        result = []
        for rows in groups.values():
            rows.sort(key=lambda r: r["id"])
            anchor = rows[0]
            if len(rows) > 1:
                if any(len({digest(r.get(f)) for r in rows}) != 1 for f in compare):
                    raise ValueError("conflicting child record: " + table)
                if table == WINDOW and anchor["status"] != "blocked":
                    raise ValueError("only historical blocked decisions may collapse")
                for field in union_fields:
                    anchor[field] = stable_union(r.get(field, []) for r in rows)
            result.append(anchor)
        after[table] = result

    collapse(WINDOW, ("window_id", "article_id"), ("status", "score", "rank"))
    for row in after.get(EVIDENCE, []):
        if row["article_id"] in mappings[NEWS]:
            raise ValueError("cross-domain evidence requires a new plan")
        row["candidate_id"] = mappings[TERM][row["candidate_id"]]
    collapse(EVIDENCE, ("candidate_id", "article_id"), ("occurrence_count", "confidence"),
             ("contexts", "source_fields", "detectors", "reasons"))
    for row in after[TERM]:
        originals = [r for r in before[TERM] if mappings[TERM][r["id"]] == row["id"]]
        evidence = [e for e in after.get(EVIDENCE, []) if e["candidate_id"] == row["id"]]
        row["first_seen_at"] = min(r["first_seen_at"] for r in originals)
        row["last_seen_at"] = max(r["last_seen_at"] for r in originals)
        row["detection_reasons"] = stable_union(r["detection_reasons"] for r in sorted(originals, key=lambda r: r["id"]))
        row["article_count"] = len({e["article_id"] for e in evidence})
        row["occurrence_count"] = sum(e["occurrence_count"] for e in evidence)
        row["confidence"] = max(e["confidence"] for e in evidence) if evidence else max(r["confidence"] for r in originals)
    for rows in after.values(): rows.sort(key=lambda r: r["id"])
    return {"before_sha256": digest(before), "after": after, "after_sha256": digest(after), "mappings": mappings}


def stable_union(groups):
    result, seen = [], set()
    for group in groups:
        if not isinstance(group, list): raise ValueError("expected an evidence array")
        for value in group:
            identity = digest(value)
            if identity not in seen:
                seen.add(identity); result.append(value)
    return result
