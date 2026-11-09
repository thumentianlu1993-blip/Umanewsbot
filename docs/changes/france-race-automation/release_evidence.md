# 2026-11-09 实际发布与恢复证据

## 当前结果

- PR #292 已合并，merge `907210eb89374980de2edaf0769c1542127eb649`。
- 生产候选 `49bccf898bf4cbd8a3fdfccfe9310f2633664864`，schema 0079，无新增迁移。
- 修正镜像 OCI digest `sha256:09a416b04f98a5621c5913f4d9b84968e1709be429364fe7f2ffb35912343ff8`；与原应用镜像核对的 1,015 文件内容一致，仅 9 文件补可执行位。
- 用户批准重新发布包 SHA `7c677c126a10d39987fbdf4a662c82fee5fe4bdfa7b6f2a5e79b61964789e8f0` 后，安装和重新发布实际执行。先补齐本包已约定的数据挂载目录，再按同包 `resume` 续跑。
- 北京时间约 23:38，Web healthy、Nginx 校验/reload 完成，`https://umafans.run/healthz/` 与 `https://www.umafans.run/healthz/` 均 200。这证明站点访问恢复，不代表法国业务验收完成。
- 生产 France Galop 探针读取 16 条报名，Geny 探针读取 6 条正式卡，阶段区分与解析通过。

## 当前阻塞与数据状态

数据 dry-run 在 `france_release.execute` 的 `owner_conflict` 检查停止，外层事务回滚。两种操作收据 `france_activation`、`france_release_data` 均不存在，未产生本包法国数据写入或 49 日港换绑。

全范围只读排查发现：

| event ID | 当前 owner | v1 登记状态 | 当前赛果行 | 本包目标行 |
|---|---|---|---:|---:|
| 772 | historical | retired | 8 | 8 |
| 828 | historical | retired | 7 | 7 |
| 830 | historical | retired | 5 | 5 |
| 833 | historical | retired | 8 | 8 |
| 785 | data_sync | enrolled | 0 | 6 |
| 790 | data_sync | enrolled | 0 | 9 |
| 791 | data_sync | enrolled | 0 | 13 |
| 839 | data_sync | enrolled | 0 | 7 |
| 840 | data_sync | enrolled | 0 | 7 |
| 841 | data_sync | enrolled | 0 | 10 |

十场均无人工锁、手工暂停原因、活动 claim 或 v2 binding。四场历史 owner 来自已完成的旧回填 manifest `f45f8043ffd3820305813d96aaeaae57d8aa5ce40c304eb04e06d59e7f1bd94a`。现有发布器同时拒绝历史 owner 和任何已有登记，不能绕过检查或删除旧登记解决。

本次前置验证遗漏了这部分生产控制状态；隔离回放及模拟协调测试未覆盖旧登记交接。拟议修正需保留原登记主键、旧来源/修订和 before/after 审计，并将显式交接与法国数据、日港换绑放在同一事务。用户于2026-11-10明确批准上述10场交接范围；已实施原位交接及离线验证，尚未改变生产归属。

## 运行与恢复边界

失败后普通 worker、race_sync_v2_worker、beat 按获准包停止。Web 保持已恢复状态；磁盘 `.env` 已安装目标配置，但 Web 当前驻留的是数据激活前的原配置。不得把磁盘配置当作驻留配置或已启用调度的证据。

固定 root：`/opt/umanews-release-49bccf89-france-20261109/umanewsbot`。
独立后继 stage：`/opt/umanews-external-staging/france-49bccf89-executable`。
后继 runtime：`runtime/france-repair-executable`，其中 `pinned-images.json` 固定修正应用镜像。操作此恢复流程时必须使用获准包入口及该 overlay，不能使用旧失败 intent 更换镜像续跑，也不能用无 overlay 的通用 Compose 命令替代。

原 937,609,698 字节数据库备份、SHA/TOC、原 intent 和 schema 完成凭据均保留；原 intent SHA `3ca75c37e09ef3085203dc2f4b52824f25456cc7dddf2e523f47825342f6d7a9`。本次只读 schema/database identity 校验通过，未重做迁移或 schema/static。

## 验证凭据与未完成项

既有业务范围 CI 772 项、候选 28 项及事务测试，另有修正镜像四个真实启动入口、12 项协调/续跑、3 项安装信号清理、实际 UID1000 目录权限 RED/GREEN；独立复审通过。以上证明各自覆盖范围，不替代本次失败的真实数据 dry-run。

尚未完成：旧登记显式交接、法国 80 页/59 场 511 行及 49 日港换绑、21 未来目标自然调度、最终驻留服务及 QQ 关闭验收。正式出马表接管与赛后自然更新按此前约定等待真实节点，不提前宣称完成。

本机完整证据目录：`/Users/mentianlu/.codex/runtime/france-race-automation-20261109/republish-executable/production-attempt/`；旧登记只读快照与提案在同级 `historical-handoff/`。人工门禁仅引用仓库根 `AGENTS.md`。

## 2026-11-10 十场交接修订代码验证

旧版owner_conflict已取得RED；新增显式legacy_handoffs与原位v1→v2交接后，61项法国/登记/转换/恢复/并发PostgreSQL测试通过。真实10场控制状态纳入80场511行整包回放，30旧检查点、10来源、22旧修订元数据保留；末59场投影后故障完整回滚。独立原reviewer上下文只读审核通过，无actionable finding。固定树CI、候选镜像与发布协调器验证仍单列，生产归属未变。

后续完整旧实体回放定位法语重音差异，已加入仅本10场有效的manifest绑定runner对应表和后续名称约束；这是代码审核返修，尚未生产执行。旧61项与35项镜像验证仅对应早期修订，最终交付采用返修后的固定提交CI与新候选镜像证据。
