# 已审核赛事中文名统一导入生产发布报告（2026-07-21）

## 结论

2026-07-21 已按受审 bundle 完成生产正式写入：单事务 apply 成功，独立 verifier 全绿，写后抽检通过。本批共更新 `1300` 个 `RaceSeries.chinese_name`、`8883` 个 `RaceEvent.chinese_name`（审核表 `8663` 场 + Event `96` + `219` 场同系列原文回退），并把香港 Event `16446` 与 HistoricalRaceEventTarget `49052` 同事务从系列 `6019` 改绑到 `5963`。未修改 `original_name`、来源证据、公开状态、manual lock 或任何范围外对象。

## 授权与审核链

- 最终复审：Claude Code 等价复审两轮（替代无法恢复的原 codex reviewer 会话，用户 2026-07-21 决定，见 `docs/decisions.md`），结论 APPROVED、actionable finding 清零。
- 用户发布授权：2026-07-21 用户针对精确候选 `unified-import-preview-20260720T220245Z` 回复“发布吧”。
- 授权记录：`authorizationRef=user-explicit-fabueba-20260721`、`authorizationTime=2026-07-21T08:17:29Z`，已写入 OperationLog `105230` detail。

## 关键身份

| 项 | 值 |
|---|---|
| 候选目录 | `outputs/translate-race-names-20260719/unified-import-preview-20260720T220245Z` |
| 发布提交 | `8e9dba572b537f9535cd37573f0aaaf18153281c`（approved parent `353464c7`，COMMIT_TRANSITION_OK） |
| bundle archive SHA-256 | `bf28bb90dd9a3880a125d6193e73efe1821711189343430146a82c6cd491e6e4` |
| bundle-index 原始 SHA | `72706e95832a0595f0e7b7177e76fb1865e250f92e7b39e31142481fe8bc333a` |
| bundle content SHA | `014a43c2670f5504c12814a3fea92dde5bedf9f8dea741954a326216361780f4` |
| manifest content SHA | `3567eb18e528ad015b3c8fa4098bfdbb2855b31d5b1cc710388b48fff5409451` |
| 生产备份 | `/opt/umanewsbot/backups/race-name-translation/pre-race-name-translation-20260721T080706Z.dump` |
| 备份大小 / SHA-256 | `225591170` bytes / `51a0f8ae191c1824d2392cdc2f070be4887b728a4e14cd88a57a2897901d1388` |
| 备份校验 | 权限 `0600`、非空、PostgreSQL 16.14、`pg_restore -l` 通过 |
| OperationLog | `105230`，`race_name_translations_applied`，batch `3567eb18e528ad015b3c8fa4098bfdbb`，admin=NULL |
| 写后聚合快照 SHA | `82ac9d1337db3385b8c8e9d20748c1f985942847731e61be2dba6dbbb5b30336` |

## 执行记录

1. 发布冻结指纹复核（content_manifest `37afa4ef…`，tracked_diff 与审核基线一致，仅文档增量）→ staging `INDEX_TRANSITION_OK` → 不可变提交 `8e9dba57` → `COMMIT_TRANSITION_OK` → 从该提交导出 bundle，archive SHA 与 receipt 逐项一致。
2. 生产 custom-format 备份按 rollout 固定脚本完成并独立校验（见上表）。
3. bundle 上传服务器并复制进 `umanewsbot-web-1`；宿主机与容器内分别复算全部 12 成员 size/SHA 与 bundle-index 原始 SHA，全部一致。
4. verify-only：`applyReady` 全绿，计数 `1300/8883/1/1`。
5. commit 前再次复算同一目录（通过），随后 `--commit` 单事务写入：`seriesCount=1300 eventCount=8883 historicalTargetCount=1 identityCorrectionCount=1`。
6. 独立 verifier（applied 模式）：`ok=true`，OperationLog `105230`，八项 bundle/artifact SHA 逐项匹配。
7. 写后抽检：Event `96` = 京成杯秋季赛；Event `16446` = 洋紫荆短途锦标、系列 `5963`、key 已更新、`original_name` 保留；Target `49052` → `5963`；Series `6125` = 京成杯秋季赛；`/healthz/`（本地+公网）与 `/races/` 200；`/races/2026/jra-2026-0905-01/`、`/races/2012/hong_kong-hong-kong-surface-bauhinia-sprint-trophy-2012/`、`/races/2010/japan-keisei-hai-autumn-2010/` 均显示新中文名且无让赛残留。
8. 服务器与容器临时文件已清理；备份保留。

## 让赛残留说明（范围外、非本批回归）

全库扫描发现 `9` 个 2026 香港赛历 Event（如 `洋紫荆短途锦标 (让赛)`，ID `145-163` 段）与 `9` 个对应 RaceSeries、以及日本 RaceSeries `285`（`京成杯秋季让赛`）的中文名仍含让赛字样。它们均有独立中文名、不在本批 1301 个系列与 8885 场 Event 范围内，按“已有独立中文名不得覆盖”规则保持原样。是否按“让赛不展示”规则另行清理 2026 赛历对象，属于后续独立任务，需用户决策。

## 运维教训（已回写 deploy_runbook）

经 ssh 用 stdin 传递脚本时，`docker compose exec` 会耗尽共享 stdin，导致脚本剩余部分丢失、trap 误删备份产物；固定脚本必须先落为远程临时文件再执行。

## 回滚路径

首选对象级 rollback：以同一 bundle 运行 `apply_race_name_translation_manifest.py --rollback-commit`（需唯一 apply OperationLog、完整 bundle 一致、after-state 全行 CAS）；失败则按 rollout 事故流程整库恢复，恢复点为上表备份。
