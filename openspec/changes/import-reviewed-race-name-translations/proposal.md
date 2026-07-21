# 已审核赛事中文名统一导入与生产写入

## Why

生产已有 `8867` 场 `basic/runners/results` 完整的历史年度赛事，其中 `8663` 场没有独立中文展示名、仍以原文回退。用户已完成五地区（日本/中国香港/美国/英国/法国）`2023` 个审核分组（`1301` 个源 RaceSeries）的中文名审核，需要把审核结果经统一预演、受审 bundle 和多重门禁后安全写入生产 `RaceSeries.chinese_name` / `RaceEvent.chinese_name`，并同步完成一条用户点名的香港身份修正。

本 change 是既有任务的管理层封装：权威业务契约、设计和发布边界已在 `docs/changes/import-reviewed-race-name-translations/`（spec/design/test_cases/rollout）与 `docs/race_name_translation_handoff_20260720.md` 中冻结，工具链代码已实现并通过多轮只读 review 返修。本 change 跟踪从"生产只读访问恢复"到"受控写入完成"的剩余受门禁路径。

## What Changes

- 以 OpenSpec change 形式跟踪既有已审核赛事中文名导入任务的剩余执行路径（无新代码设计）。
- 重新生成全新时间戳候选（旧候选全部失效），完成 Excel QA、deterministic bundle、全量测试与文档指纹。
- 最终只读复审方式变更：原交接要求复用 codex reviewer 会话 `019f7bfb-2543-7523-aebd-3d496bc96422`；经用户 2026-07-21 明确决定，改由 Claude Code 对该精确受审候选做等价完整只读复审，审核链替换记录于 `docs/decisions.md`。
- 复审 `APPROVED` 后重新取得用户对该精确版本的发布授权，再按 rollout 执行 staging/commit/备份/verify-only/apply/独立 verifier/抽检。

## Capabilities

### New Capabilities

- `race-name-translation-import`：一次性、可审计的赛事中文名批量导入。输入为五份 SHA 锁定工作簿；输出为 manifest、生产 before 快照、dry-run、rollback-before、用户审核 Excel 与十二成员受审 bundle；写入为单事务全字段 CAS + OperationLog，配独立 verifier 与对象级 rollback。权威规则见 `docs/changes/import-reviewed-race-name-translations/spec.md`。

### Modified Capabilities

（无；本任务不修改任何现有规格行为、模型、迁移、新闻/发布/QQ 链路或公开开关。）

## Impact

- 受影响代码：`runtime/tools/` 下本任务工具链（已实现，未提交）；`server/stable/test_race_name_translation_apply.py`。
- 受影响数据（仅授权后一次写入）：`1300` 个 `RaceSeries.chinese_name`、`8883` 个 `RaceEvent.chinese_name`（含 Event `96` 精确 allowlist 与 `219` 场同系列原文回退）、香港 Event `16446` 的 `race_series_id/series_key` 与 HistoricalRaceEventTarget `49052` 的 `race_series_id`。
- 不部署镜像、不重启服务、不改公开状态；正式动作是一次受控数据写入。
- 依赖：生产 SSH/容器只读访问（已于 2026-07-21 确认恢复）；`~/Downloads` 三份用户审核工作簿的本地读取权限。
