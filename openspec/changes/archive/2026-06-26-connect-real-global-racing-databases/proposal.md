## Why

当前外部赛马数据库只完成了 HKJC fixture 样本写入和英法美只读 spike，还不能持续、可审计地从真实来源获取最近赛事与马匹资料。下一阶段需要把香港、英国、法国、美国四个地区的真实数据库接入打通，为后续比赛页、马匹页、新闻术语识别和赛程型内容打底。

## What Changes

- 新增真实外部赛马数据接入能力，按 `香港 -> 英国 -> 法国 -> 美国` 顺序推进。
- 香港阶段优先从 HKJC 官方公开 HTML 页面低频抓取最近 2 个月赛日、每场结果、涉及马匹详情；当前生产 dry-run 已达到用户确认的暂停边界，本轮不继续香港。
- 英国、法国、美国阶段从原先的只读 spike 升级为真实抓取目标，确认 racecard / result / horse profile 字段覆盖后按相同安全边界进入 dry-run、隔离验证和后续生产 commit 门禁。
- 所有真实抓取必须限速、单来源互斥、批量可控、dry-run 先行，并记录请求边界、覆盖统计、失败摘要和停止点。
- 按 2026-06-27 用户新边界，本会话完成英法美真实接入 proof：每地抓几个真实批次，证明最近窗口入口、单场结果和涉及马匹详情解析可用；完整最近 2 个月大量爬取后续另开会话单独执行。
- 不续跑日本 netkeiba；日本外部数据导入仍由其他线程处理。

## Capabilities

### New Capabilities

- `real-global-racing-data-ingestion`: 覆盖香港、英国、法国、美国真实赛马数据库的低频抓取、解析、正式外部缓存写入、马匹详情补抓和停止边界；本轮英法美以真实 dry-run proof 为准，完整大量爬取后续会话继续。

### Modified Capabilities

- `global-racing-data-import-readiness`: 本变更建立在 readiness 与 spike 规格之上，但不修改其已归档的样本准入要求；真实导入行为由新 capability 承载。

## Impact

- `server/stable/services/external_hkjc_data.py`：从占位网络 URL 扩展为 HKJC 官方 HTML 页面适配、赛日枚举、单场结果解析、马匹详情解析和低频请求控制。
- `server/stable/management/commands/import_hkjc_external_data.py`：新增最近 N 天 / 日期范围、网络 commit、请求间隔和停止边界参数。
- `server/stable/models.py`：优先复用现有 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse`、`ExternalHorseAlias`、`ExternalDataImportRun` 和 `ExternalDataImportLock`；仅在字段无法表达真实数据时新增迁移。
- `server/stable/tests.py` 或拆分测试文件：按 TDD 增加 HKJC HTML fixture 解析、dry-run 不写入、commit 写入、限速、上限、锁和幂等测试。
- `docs/`：更新当前状态、数据源调研报告、生产运行手册和回滚口径，明确真实抓取进度与尚未进入的地区。
- 生产运行：每个地区正式 commit 前必须先完成备份、dry-run、显式确认、健康检查和小批量验证。
