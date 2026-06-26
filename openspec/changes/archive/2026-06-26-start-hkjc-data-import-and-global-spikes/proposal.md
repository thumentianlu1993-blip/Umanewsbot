## Why

国际赛马资讯扩展已经上线第一版新闻源和 HKJC 外部数据缓存入口。现在需要把数据库来源推进到下一步：正式启动香港 HKJC 的受控样本导入闭环，同时为英国、法国、美国产出可复查的结构化数据 spike，判断哪些来源能进入后续正式导入。

日本 netkeiba 外部数据导入已经在其他线程继续，本 change 不续跑日本、不扩大日本导入范围，避免多个导入窗口和运维结论互相覆盖。

## What Changes

- 启动 HKJC 外部赛马数据导入的受控执行链路：
  - 从样本 payload 开始，覆盖赛日、单场比赛和单匹马资料。
  - 明确 dry-run、commit、统计查询、马名索引查询和生产验收口径。
  - 在真实网络抓取实现前，继续要求 commit 必须提供 `--payload-file`，不得用占位 payload 写库。
- 为 HKJC 后续真实网络抓取补充可实施的适配计划：
  - 确认公开入口、请求参数、限速、失败隔离和字段映射。
  - 只在样本验证通过后进入小批量真实请求。
  - 补齐 `HKJC_IMPORT_*` 配置入口、`.env.example` 和 runbook，使限速和批量上限可由运行环境控制。
- 对英法美数据库来源产出受控 spike：
  - 英国：`Sporting Life + BHA`，聚焦 racecards、results、horse profile、官方搜索和监管信息。
  - 美国：`Equibase`，聚焦 entries、results、charts/PDF、horse profile。
  - 法国：`France Galop`，只评估结构化赛程、报名、出马、赛果和马匹资料，不抓法语新闻正文进入新闻链路。
- spike 阶段不得写入正式 `ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias` 表，不加入 Celery Beat、生产管理命令调度或正式导入队列。
- 补充仓库文档和运维 runbook，记录 HKJC 样本导入结果、英法美样本 URL、请求次数、限速设置、失败情况、字段覆盖和后续正式导入建议。

## Capabilities

### New Capabilities

- `global-racing-data-import-readiness`: 约束 HKJC 正式受控导入启动、英法美数据库 spike、正式表写入边界、生产执行口径和后续导入准入标准。

### Modified Capabilities

- 无。日本 netkeiba 导入、新闻抓取、公开前台比赛页和马匹页不在本 change 修改范围内。

## Impact

- 代码范围：
  - `server/stable/services/external_hkjc_data.py`
  - `server/stable/management/commands/import_hkjc_external_data.py`
  - 后续新增的英法美 spike 脚本、管理命令或文档化探测工具
  - 相关测试覆盖 HKJC payload 写入、上限检查、索引查询和 spike 不写正式表
- 数据库：
  - 优先复用现有 `External*` 表。
  - HKJC 样本 commit 会写入正式外部缓存表。
  - 英法美 spike 不写正式外部缓存表；如需保存样本，只能进入隔离 fixture、临时文件或仓库文档。
- 运维：
  - 执行 HKJC commit 前必须先在本地或隔离数据库完成验证；生产 commit 前必须确认没有正在运行的外部导入锁、完成数据库备份，并保留 payload、命令、run_id、备份路径和统计结果。
  - 真实网络抓取仍需低频、限速、单来源互斥和小批量。
  - 不创建前台比赛页、赛果页、马匹页，也不改变新闻自动发布和 QQ 推送规则。
- 文档：
  - 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`。
  - 更新或扩展 `docs/global_racing_data_source_spikes.md`，把英法美 spike 从“入口建议”推进到“执行证据与准入判断”。
