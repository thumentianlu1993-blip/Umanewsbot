# 法国发布与验收证据

## 2026-11-10 容量恢复与自然调度验收（进行中）

02:17、02:27自然任务已由Beat派发，但业务检查受 `artifact_min_free_disk` 阻断，不能计为验收成功。实际可用空间约4.09GB，原raw归档最低空闲阈值为8GiB。沿用本次用户对同范围上线前问题的明确授权，准备容量恢复包 `ade45ccee795404c71cd44261c959885fdf723950f13582eaccb1fe98b2c23ed`：仅将四应用的raw最低空闲阈值调整为4GiB，保留512MiB归档根目录高水位、单文件限制和其余配置；启动前要求空闲量仍大于4GiB加完整高水位及单文件预留。

四份本任务重复传输镜像归档已逐个核对本机副本SHA后清理，生产可用空间从4,093,079,552增至5,222,649,856字节；数据库备份、已加载镜像和其他任务文件保留。需要冷恢复旧镜像时可从本机保留的原归档重新传输。包已通过21项基础协调测试、修订后6项聚焦协调测试、4项清理中断/重放测试与原reviewer复审。恢复流程已先停Beat并取得双worker active/reserved/active_confirm全零快照，再应用配置并恢复服务。生产runner退出0、生成complete、释放发布锁；四应用运行且镜像/环境/Django版本一致、双worker首轮pong、Web及双域健康通过，QQ关闭。自然业务验收尚未完成。

证据目录：`historical-handoff/application-identity/capacity-recovery/`，包含 `archive-cleanup-receipt.json`、`release-package.json`、`coordinator-tests.log`、`coordination-fixes-tests.log`、`cleanup-tests.log` 和 `rereview.log`。旧失败记录保留，失败尝试不替代成功检查。

## 2026-11-10 02:12 后台恢复完成，自然调度验收进行中

- 用户明确批准 `fbc29af2f2d4`，并授权同范围上线前新发现问题直接修复、复验和执行。执行前发现 Django 优先读取的 `/app/.umanews-release-commit` 仍为49bcc，原fbc仅修容器环境不足；本次同范围技术修订未重复请求确认。
- 执行包 SHA `9f1c07c116f97ed142ba6217a36e92e1506f845c12959ce73c1007fd89aff8e1`；代码候选仍 `0d05fa9bde87f2ca465442ad3c54422db50a1c12`。修正镜像 OCI `sha256:2fa852b01378c076bf1b9c45cf30c8242bebfdcb70ab0ebcd29daca728dd8bc4`，1022文件hash/mode比对仅release marker变化，镜像配置及旧层未变化。
- 20项协调故障场景、新镜像四入口真实启动、0.25 CPU双worker就绪、四应用Django有效版本及独立只读review均通过。生产one-off只读核验21目标窗口/来源策略/锁与归属/开关/Beat时点/队列、完整数据交接收据和Nginx配置通过后才重建服务。
- 生产runner退出0并生成独立complete；四应用使用修正镜像，环境与实际Django版本均为0d05，双worker真实pong、beat运行、Webhealthy、双域health通过，QQfalse、restart0、OOMfalse，发布锁已释放。无迁移、不重跑数据apply、不新建数据库备份。
- 21个未来目标自然调度与公开预览验收正在进行，正式卡接管及赛后真实更新仍待对应事件节点。

本次证据位于本机 `historical-handoff/application-identity/` 的 `prelaunch-audit.json`、`image-file-proof.json`、`startup-green.json`、`coordinator-tests.log`、`review.log`、`production-state.json` 和 `production-evidence/complete.json`。生产固定目录仍为0d05 root，维护入口必须追加最终 `france-application-identity-0d05fa9b/release-identity.json`，见部署手册。

## 2026-11-10 此前部分发布与恢复过程（历史）

- PR #293 合并提交 `7ea0e260ebe657ef711f532522d0ba6fc686ae12`；合并树与781项/0跳过CI所测树一致，七个生产变更文件逐字节核对通过。
- 获准包 SHA `5a4bf241cc9343cafd6ff4d25318c99bd5d56cbf91192814567254d4ed41da3b`；生产候选 `0d05fa9bde87f2ca465442ad3c54422db50a1c12`，应用 OCI `sha256:f9fbf121495de84cff6debb4976e9091b9f1f3e401ea53a4c31ed1df41c12bf8`。新固定目录为 `/opt/umanews-release-0d05fa9b-france-handoff-20261110/umanewsbot`。
- 无迁移、无配置值变更。原intent、schema凭据和备份保留；新增备份937,620,564字节，TOC 1,401项，SHA `09264631649fe67704c2481b413797ee4b91f8de5f1c7bcfab531c0a377d78f0`，仅保存在生产私有目录。
- 真实FG探针16条报名、Geny探针6条正式卡通过；整包dry-run回滚通过，随后apply与committed检查通过。10场旧登记原位升级、80匹runner映射、49项日港换绑与法国80目标/511行同事务提交。
- 公网80/80页面通过，实际赛果511行，字段、非出走语义和10场AQPS展示吻合。双域health200。旧URL按既有设计保持200并展示event784规范入口链接；此前“跳转”的描述不是HTTP重定向行为。
- Web已使用新镜像且健康。原协调者立即发送一次10秒ping，专用worker在0.25 CPU下约20秒才完成启动，导致workers_not_ready。失败路径已逐一确认beat及双worker停止，保留健康Web。一轮中间resume遇Geny navigation_rejected，后续相同安全约束诊断成功；第二轮resume数据仅返回replay，仍在同一worker就绪检查失败。
- 数据激活收据有效，不能再称“法国数据未提交”；后台自动调度尚未恢复，不能称整体上线验收完成。21个未来目标自然调度、正式卡接管和赛后自然更新仍待后续验证。

实际证据：本机 `historical-handoff/production-attempt-01/`、`production-resume-01/`、`production-evidence/`、`public-http-acceptance.json`、`public-health-and-canonical.json`，均位于 `/Users/mentianlu/.codex/runtime/france-race-automation-20261109/` 下。只修正后台重复就绪等待的后继包 `494666fa685d4f1666856e6d80aff287fff5e6836f5a3170d1b5993eea9eb46e` 位于 `historical-handoff/worker-readiness/`，4项等待单测、9项协调故障测试、0.25 CPU两个独立worker的真实就绪验证及独立复审均通过。用户已批准并实际执行，双worker第4轮检查同时pong，随后父驻留检查发现四应用 `UMANEWS_RELEASE_COMMIT` 仍为旧 `9c8891b8`；实际镜像均正确为f9fb。失败路径确认三个后台停止、Web健康，完成凭据未生成。生产证据保存在该目录 `production-evidence/`。

版本标识修复在独立 `historical-handoff/release-identity/` 准备：仅新增四应用的显式Compose环境覆盖，真实生产只读配置比对已确认其余有效配置完全相同。包含同镜像Web重建及Nginx验证reload、后台恢复与失败回退；原 `.env` 和数据不变。原后台包未包含配置变化/Web重建，新包 `fbc29af2f2d410bbd9d7fef84070e5ea69aa74f1f2ef84ce31093abe509a9e60` 已完成基础15场景与Web恢复修复后6项聚焦验证，独立复审通过；当时待交付确认；随后已获批准，执行前审计发现镜像内版本文件仍旧，因此由上文9f1c包取代，未直接执行fbc包。

## 2026-11-09 至交接修订前的历史记录

以下段落保留当时的失败状态；当前状态以文首最新记录为准。

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
