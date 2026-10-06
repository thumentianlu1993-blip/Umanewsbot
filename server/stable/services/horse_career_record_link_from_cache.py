"""A034 RED 占位：正常导入、完整签名、零写入；真实 RED 核验前不实现。"""


def apply_career_record_link_from_cache(
    *, snapshot, candidate, raw_bytes, expected_sha256, ref, source_ref,
    entity_versions, as_of, max_age_seconds, expected_updated_at, actor,
    selected_row_sha, record_pk, source_identity_pk, event_pk, binding_pk,
    expected_binding_manifest_sha256, expected_record_updated_at,
):
    """未实现状态固定返回；不读 DB/文件、不修改输入、不调用 writer。"""
    return {"status": "blocked", "reason": "career_link_not_implemented", "published": False}
