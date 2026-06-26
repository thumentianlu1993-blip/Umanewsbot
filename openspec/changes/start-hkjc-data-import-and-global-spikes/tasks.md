## 0. Pre-declared hypotheses

- H1: HKJC 样本 payload 可以覆盖赛日、单场比赛和单匹马资料三类入口，并在隔离数据库中完成 dry-run 与 commit 闭环。
- H2: HKJC 生产 commit 只有在隔离验证、导入锁检查、长导入窗口检查、数据库备份和用户显式确认后才可执行。
- H3: HKJC 真实网络小样本需要先补齐可配置的限速和批量上限，再进入 dry-run；没有稳定字段前不得 commit。
- H4: 英法美 spike 可以在只读或 fixture 隔离模式下产出字段覆盖矩阵，且正式 `External*` 表和 `ExternalHorseAlias` 计数保持不变。
- H5: 本轮不会产生公开比赛页、赛果页、马匹页、今日赛程模块或新闻分发策略变化。

## 1. HKJC 样本导入闭环

- [x] 1.1 (integration) 准备或生成 HKJC 赛日、单场比赛、单匹马资料的最小真实样本 payload，并记录样本来源和字段口径。
- [x] 1.2 (application) 补齐 HKJC 样本导入测试，覆盖 dry-run 不写表、commit 写入 `External*` 缓存、`ExternalHorseAlias` 派生、`--stats-run-id` 和 `--lookup-name`。
- [x] 1.3 (integration) 在本地或隔离数据库执行 HKJC 赛日样本 dry-run 和 commit，确认 `coverage_stats`、`run_id`、写入数量和样本马名索引查询结果。
- [x] 1.4 (integration) 在本地或隔离数据库执行 HKJC 单场比赛与单匹马样本 dry-run 和 commit，确认字段映射、马名中英文关系和幂等 upsert 行为。
- [x] 1.5 (operations) 若需要生产 HKJC 样本 commit，先完成数据库备份或快照、导入锁检查、长导入窗口检查、容器健康检查和用户显式确认。
- [x] 1.6 (operations) 记录 HKJC 样本 payload 路径、命令、run_id、备份路径、统计结果、回滚清理口径和是否允许进入真实网络小样本。

## 2. HKJC 真实网络小样本准备

- [x] 2.1 (integration) 调研 HKJC 赛日、单场比赛和马匹资料的公开入口、请求参数和返回 payload 形状，优先复用公开 JSON/API 或页面脚本 payload。
- [x] 2.2 (application) 补齐 `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS`、`HKJC_IMPORT_MAX_RACES_PER_RUN`、`HKJC_IMPORT_MAX_HORSES_PER_RUN` 等 settings、`.env.example` 和 runbook 说明，确保真实网络小样本可由环境配置限速和批量上限。
- [x] 2.3 (integration) 为 HKJC 真实网络请求增加只读 dry-run 探测路径，记录请求 URL、请求次数、返回状态、限速和解析字段，不写正式缓存表。
- [x] 2.4 (application) 补充 HKJC 网络 dry-run 测试，覆盖无 commit 不写表、入口失败不进入正式写库、无 payload commit 仍被拒绝、环境配置可覆盖默认限速和批量上限。
- [x] 2.5 (operations) 在生产或等价环境执行 HKJC 网络小样本前检查 `ExternalDataImportLock`、容器状态、`/healthz/`、数据库备份路径和是否存在其他长导入窗口。
- [x] 2.6 (integration) 在通过安全检查后执行 HKJC 真实网络小样本 dry-run；只有字段稳定、备份完成且用户确认后，才执行低频小样本 commit。

## 3. 英法美数据库 spike

- [x] 3.1 (integration) 为美国 `Equibase` 执行只读 spike，覆盖 entries、results、charts/PDF 和 horse profile 的可访问性、字段覆盖和解析风险。
- [x] 3.2 (integration) 为英国 `Sporting Life + BHA` 执行只读 spike，分别覆盖 racecards、results、horse profile、官方搜索和监管/补字段入口。
- [x] 3.3 (integration) 为法国 `France Galop` 执行只读 spike，只评估结构化赛程、报名、出马、赛果和马匹资料入口，不抓法语新闻正文进入主链路。
- [x] 3.4 (application) 增加 spike 隔离性测试或检查脚本，记录 spike 前后正式 `External*` 表和 `ExternalHorseAlias` 计数，确认英法美 spike 不写入正式表、不创建马名索引、不加入 Celery Beat 或正式导入队列。
- [x] 3.5 (operations) 为英法美每个 spike 记录样本 URL、请求次数、限速设置、请求方式、失败摘要、样本保存位置和准入状态。

## 4. 文档和准入判断

- [x] 4.1 (operations) 更新 `docs/global_racing_data_source_spikes.md`，把英法美从入口建议推进为执行证据、字段覆盖矩阵和正式导入准入判断。
- [x] 4.2 (operations) 更新 `docs/deploy_runbook.md`，补充 HKJC 样本导入、真实网络小样本、导入锁检查、统计查询、马名索引查询和回滚清理步骤。
- [x] 4.3 (operations) 更新 `docs/current_state.md`，记录本轮 HKJC 执行状态、英法美 spike 结论和明确不包含日本续跑。
- [x] 4.4 (operations) 更新 `docs/project_status.md`，保留项目级摘要，并注明前台比赛页、赛果页、马匹页仍不是本轮产物。
- [x] 4.5 (operations) 若本轮形成新的来源准入或生产执行决策，更新 `docs/decisions.md`。

## 5. 验证与收尾

- [x] 5.1 (application) 执行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 5.2 (application) 执行 HKJC 导入和 spike 相关 Django 测试。
- [x] 5.3 (application) 执行完整 `stable` 测试或说明无法执行的原因。
- [x] 5.4 (operations) 执行 `openspec validate start-hkjc-data-import-and-global-spikes --strict`。
- [x] 5.5 (operations) 执行 `openspec validate --all` 和 `git diff --check`。
- [x] 5.6 (operations) 在完成实现与验证后，整理本 change 是否可归档，若可归档则提醒执行 `/opsx:archive`。
