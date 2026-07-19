from __future__ import annotations

from stable.models import RacingRegion


# 结构化赛事和马匹数据仍只覆盖变更前的五个地区。新闻地区扩展不得
# 隐式扩大历史批次、赛事日历、准实时或马匹补全范围。
RACE_DATA_REGIONS = (
    RacingRegion.JAPAN,
    RacingRegion.HONG_KONG,
    RacingRegion.UNITED_KINGDOM,
    RacingRegion.FRANCE,
    RacingRegion.UNITED_STATES,
)
HORSE_PROFILE_REGIONS = RACE_DATA_REGIONS
RACE_LIVE_SUPPORTED_REGIONS = RACE_DATA_REGIONS

# 仅用于编辑已有结构化数据；保留历史 OTHER 值不代表开放对应采集或执行能力。
RACE_EVENT_FORM_REGIONS = (*RACE_DATA_REGIONS, RacingRegion.OTHER)
HORSE_PROFILE_FORM_REGIONS = (*HORSE_PROFILE_REGIONS, RacingRegion.OTHER)

NEW_REGION_NEWS_REGIONS = (
    RacingRegion.IRELAND,
    RacingRegion.CANADA,
    RacingRegion.UNITED_ARAB_EMIRATES,
    RacingRegion.SAUDI_ARABIA,
    RacingRegion.AUSTRALIA,
)
NEWS_PRODUCTION_REGIONS = (*RACE_DATA_REGIONS, *NEW_REGION_NEWS_REGIONS)
NEWS_ATTRIBUTION_REGIONS = (*NEWS_PRODUCTION_REGIONS, RacingRegion.OTHER)
