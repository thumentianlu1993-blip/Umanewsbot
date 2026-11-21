# 上线验收发现的英国身份登记缺口

北京时间 2026-11-22 01:47 自然发现首次运行新代码：21005 的回执由
`uk_awaiting_final_card` 变为 `strong_identity_required`，仍未写入时间、名单或赛果。
只读核验：赛事属于已批准的 RaceSeries 6604，但该系列的 RaceSeriesName 为零；
该场也没有 RaceResultSourceIdentity 或 RaceEventIdentityKey。现有 uk_target_v1
保留已审核日期 2026-11-21、赛场 Haydock Park、name_keys betfairchase/lancashirechase，
external_race_id 为空。

`uk_collection._select_card` 现在能够通过赛种同义词和跨日日期卡查找来源；
`uk_race_source.source_observation` 只输出来源身份，不输出独立身份种子凭证。
`race_source_identity.resolve_observation` 只认可已有来源/身份键、带出处的已审核系列名称
或有效种子凭证。上述输入均为空，因此拒绝登记符合当前安全规则。

这说明本次模块与隔离测试未覆盖真实“只有审核目标、没有系列名称或来源身份”的冷启动背景，
不能以通过测试和部署成功宣称英国自动恢复闭环通过。

后续应先选定可追溯的身份凭证接续方式，保持日期、赛场、唯一候选、审核来源、冲突拒绝及
授权有效性检查，补充缺少系列名称/来源身份的完整发现—登记—claim—公开回归。
不得直接信任调用方 event_id、仅凭模糊名称绑定，或手工填本场赛果替代通用修复。
本次仅记录实际发现；未新增身份数据、修改生产策略、放宽身份检查或发布后续代码。
