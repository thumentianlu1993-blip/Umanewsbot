## Context

当前仓库已经具备外部赛马数据缓存的通用模型：`ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalRaceOdds`、`ExternalHorse`、`ExternalHorseHistory`、`ExternalHorseAlias`、`ExternalDataImportRun`、`ExternalDataImportError` 和 `ExternalDataImportLock`。这些模型已经支持 `source`、`racing_region`、`source_language` 和原始 payload，能够承载不同地区的结构化赛马数据。

日本 netkeiba 导入已经在其他线程继续，本轮不干预。HKJC 在国际化扩展中已经拥有 `HKJCExternalDataImporter` 与 `import_hkjc_external_data` 命令，当前安全边界是：默认 dry-run；commit 必须提供 `--payload-file`；真实网络抓取尚未实现；提交只写外部缓存表和马名索引，不生成前台比赛、赛果或马匹页面。

英法美数据库来源目前只有 spike 文档和入口建议。上一轮文档明确：`Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 不得加入正式导入队列，不得写正式外部数据表，必须先通过小样本、限速、只读或 fixture 方式确认字段覆盖和访问风险。

## Goals / Non-Goals

**Goals:**

- 启动 HKJC 的正式受控样本导入闭环，先从 payload 文件验证赛日、单场、单马三类入口。
- 为 HKJC 后续真实网络抓取形成清晰实现计划和低风险验收路径。
- 对英国、美国、法国数据库源产出可复查 spike：样本 URL、请求次数、限速、字段覆盖、失败情况、解析样本和正式导入建议。
- 保证英法美 spike 不写正式外部缓存表、不加入生产调度、不污染马名索引。
- 将执行结果写回 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md` 和 `docs/global_racing_data_source_spikes.md`。

**Non-Goals:**

- 不续跑日本 netkeiba 外部数据导入。
- 不实现公开比赛页、赛果页、马匹页、今日赛程模块或数据检索前台。
- 不把英法美 spike 直接升级为正式导入。
- 不抓取法语新闻正文进入新闻审核、翻译、自动发布或 QQ 推送主链路。
- 不把外部马名索引批量写入正式 `TermEntry`。
- 不改变现有新闻抓取、自动发布、QQ 自动推送和公开文章 URL 规则。

## Decisions

### 1. HKJC 先完成 payload commit 闭环，再考虑真实网络抓取

本轮第一步不直接写网络爬虫，而是先用小样本 payload 验证现有 `HKJCExternalDataImporter` 的行为：

- `--race-date --payload-file` 覆盖赛日多场比赛。
- `--race-id --payload-file` 覆盖单场比赛。
- `--horse-id --payload-file` 覆盖单匹马资料。
- 每次 commit 后必须查询 `--stats-run-id` 和 `--lookup-name`。

原因：HKJC 写库路径已经存在，先验证字段映射、上限检查、马名索引和统计查询，比直接打开真实网络请求风险更低。

备选方案是直接实现 HKJC 网络抓取。该方案进展快，但如果页面结构、API 参数或 payload 口径不稳定，会把网络问题和写库问题混在一起，不利于定位。

### 2. HKJC commit 继续要求 `--payload-file`

在真实网络抓取实现前，`--commit` 必须拒绝无 payload 的占位导入。后续如果实现真实网络抓取，也必须显式开关、低频限速、小批量执行，并保留 dry-run。

原因：占位 payload 会制造“导入成功但没有真实数据”的假象。HKJC 进入正式缓存前，必须能追溯样本来源、字段形状和写入结果。

### 3. HKJC 生产 commit 必须先完成隔离验证和备份

HKJC 样本 commit 的第一验收面是本地或隔离数据库。生产 commit 只有在以下条件都满足时才能执行：

- 同一 payload 已完成 dry-run 和隔离数据库 commit。
- 生产没有运行中的 `ExternalDataImportLock`，且没有 netkeiba 长导入窗口。
- 已按 runbook 创建数据库备份或快照，并记录备份路径。
- 运维人员显式确认本次只执行低频小样本。

原因：HKJC commit 会写入正式 `External*` 缓存和 `ExternalHorseAlias`。即使不影响新闻主链路，也属于生产数据变更，必须保留可回滚证据。

### 4. HKJC 网络参数必须进入运行配置

真实网络小样本如需新增或启用 `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS`、`HKJC_IMPORT_MAX_RACES_PER_RUN`、`HKJC_IMPORT_MAX_HORSES_PER_RUN` 等参数，必须同步 `server/app/settings.py`、`.env.example` 和 `docs/deploy_runbook.md`，不得只依赖 importer 内部默认值。

原因：生产限速和批量上限需要能在不改代码的情况下下调，runbook 也需要展示实际启用边界。

### 5. 英法美 spike 使用隔离产物，不写正式表

英法美 spike 产物可以是：

- 仓库文档报告。
- 隔离 fixture。
- 临时 JSON/HTML/PDF 样本。
- 只读解析命令输出。
- spike 前后的正式 `External*` 和 `ExternalHorseAlias` 表计数检查。

不得写入 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse`、`ExternalHorseAlias` 或任何正式缓存表。

原因：这些来源的访问限制、页面结构、字段完整度和合规风险尚未验证。先把字段覆盖和请求边界做实，才能决定是否进入后续正式导入 change。

### 6. spike 按“国家/地区独立报告 + 统一准入判断”组织

每个地区的 spike 报告至少包含：

- 样本入口和实际请求 URL。
- 请求次数、限速、User-Agent 或浏览器方式说明。
- 成功/失败状态和错误摘要。
- 比赛、出马、赛果、马匹 profile 字段覆盖矩阵。
- 解析样本保存位置。
- 是否建议进入正式导入，以及下一步最小实现范围。

最后需要一个统一准入判断表，列出 `ready_for_formal_import`、`needs_more_spike`、`not_recommended` 或等价状态。

### 7. 实施时不得和生产长导入窗口重叠

HKJC commit 或真实网络小样本执行前，必须确认：

- 没有同来源 `ExternalDataImportLock` 运行中。
- 没有生产 netkeiba 长导入窗口需要避免部署或重启。
- 生产容器和 `/healthz/` 正常。
- 数据库备份或快照已完成并可定位。
- payload、命令、run_id 和统计结果已记录。

原因：外部导入属于低频运维动作，本项目既有约定是不要在长导入窗口叠加部署、重建或另一个外部请求导入。

## Risks / Trade-offs

- [HKJC payload 样本不代表真实网络字段] -> 样本 commit 只证明写库路径可靠；真实网络抓取必须另有小样本 dry-run 和字段对照。
- [HKJC 马名中英文关系不完整] -> commit 后必须用 `--lookup-name` 抽检英文名、繁中名和 external horse ID 关系，不把外部索引当正式中文译名。
- [Equibase 访问限制或 PDF chart 解析成本高] -> 美国 spike 先评估 HTML/PDF 可访问性和字段覆盖，不承诺全量。
- [Sporting Life/BHA 字段分散] -> 英国 spike 分开评估商业页面和官方页面，避免把两个来源误当成一个稳定 API。
- [France Galop 法语字段和 JS 会话复杂] -> 法国只评估结构化数据入口，报告中明确字段语言和解析难度，不进入新闻正文链路。
- [spike 意外写入正式表] -> 测试和任务必须检查正式表计数或使用隔离数据库/fixture，确保 spike 不污染生产缓存。
- [HKJC 生产样本难以回滚] -> 生产 commit 前必须完成数据库备份，并在文档中记录按 `source=hkjc`、`run_id` 或样本外部 ID 的清理口径。
- [HKJC 限速配置未接入运行环境] -> 真实网络小样本实现必须补齐 settings、`.env.example` 和 runbook，确保生产可以调低请求频率和批量上限。

## Migration Plan

1. 本地或隔离数据库准备 HKJC 小样本 payload，覆盖赛日、单场、单马。
2. 对 HKJC 样本执行 dry-run，确认 `coverage_stats` 和上限口径。
3. 对隔离数据库执行 HKJC 样本 commit，验证 `External*` 写入、`ExternalHorseAlias`、`--stats-run-id` 和 `--lookup-name`。
4. 如需生产 HKJC 样本 commit，先确认导入锁、长导入窗口、容器健康和数据库备份，再经用户确认后执行。
5. 若需要真实网络抓取，先补齐运行配置，再实现或验证单赛日/单场/单马的只读请求入口，以低频小样本执行，不进入全量。
6. 分别执行美国、英国、法国 spike，仅保存隔离产物和报告，并记录正式表前后计数不变。
7. 更新文档和 OpenSpec 状态，给出每个来源是否进入后续正式导入 change 的判断。

回滚策略：

- HKJC 样本 commit 如需撤销，优先基于生产前数据库备份恢复；若只需撤销小样本，按 `source=hkjc`、`run_id` 或样本外部 ID 清理外部缓存记录；正式实现前必须在文档中写清清理口径。
- spike 无正式表写入，回滚只需删除临时文件或修正文档结论。
- 若生产执行出现异常，停止命令、确认导入锁释放，并保持新闻主链路不变。

## Open Questions

- HKJC 真实网络抓取优先使用公开 JSON/API、页面脚本 payload，还是 HTML 解析，需要在样本探测中确认。
- HKJC 第一批生产样本应选择最近一个赛日，还是先选择已完赛且字段稳定的历史赛日。
- 英国正式导入候选是否以 `Sporting Life` 为主、`BHA` 为校验补字段来源，需 spike 后决定。
- Equibase PDF chart 是否值得进入首个正式美国导入范围，需 spike 后决定。
