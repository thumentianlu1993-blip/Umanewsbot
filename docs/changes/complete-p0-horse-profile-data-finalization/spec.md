# P0 马完整资料补全收尾规格

## 范围

本增量承接 `旧规格流程/changes/complete-p0-horse-profile-data/` 已确认设计，只完成尚未落地的五地区单马资料采集、统一候选 payload、完整生涯履历 payload、审核 artifact 和模块级审核处理。

首批范围固定为生产只读候选中的日本、中国香港、英国、法国、美国各 10 匹，共 50 匹。用户已确认 50 匹全部纳入本批；纳入本批不豁免身份补强或完整资料门禁。

## 必须行为

1. 五地区 adapter 必须复用现有受控来源客户端和网络开关，支持缓存、请求间隔、单批上限、来源 URL、原始证据和字段覆盖统计。
2. 统一候选必须包含 `basic_profile`、`pedigree`、`race_records`、`major_wins`、`aliases`、`source_evidence`、`raw_payload`、`confidence` 和 `failure_reason`。
3. 每条实际出赛履历必须生成可交给 `HorseRaceRecord` 幂等写入服务的 payload；退赛、取消出走、未完赛、失格和未知状态不得折叠。
4. 完整生涯按马匹来源抓取，不能从重点赛事总账反推。没有正式 `RaceEvent` 的普通比赛保留未关联履历。
5. dry-run 必须输出 JSONL、CSV、summary、失败/冲突清单、source evidence manifest 和模块 diff；不得写主数据。
6. 模块审核必须支持应用、忽略和冲突三种决定，并记录处理人、处理时间、结果摘要及 raw payload；冲突不得写主表。
7. 只有通过身份、硬字段、完整生涯和人工审核门禁的马才能计入首批完成。

## 非目标

- 本轮不执行生产 commit、自动首次发布或生产历史履历批量抓取。
- 不为普通比赛强行创建 `RaceEvent`。
- 不改变重点赛事 G1/G2/G3 覆盖政策。
- 不采集或公开第三方专有评级、评论和预测文本。

## 验收

- 五地区 adapter fixture 测试全部通过，且网络关闭时不发生请求。
- 统一 payload 和履历状态覆盖测试通过。
- artifact 可重复生成、manifest 能检测漂移、所有审核字段可追溯。
- 首批 50 匹只在本地或生产备份副本运行 dry-run；任何缺失或冲突明确进入 blocker。
