"""A032 的 RED 占位入口；业务实现须等隔离 PG 实际 RED 后再开始。"""


def apply_basic_profile_from_cache(
    *, snapshot, candidate, raw_bytes, expected_sha256, ref, source_ref,
    entity_versions, as_of, max_age_seconds, expected_updated_at, actor,
):
    """有完整调用签名且明确不写；用于业务断言缺失能力的 RED。"""
    return {"status": "blocked", "reason": "not_implemented", "published": False}
