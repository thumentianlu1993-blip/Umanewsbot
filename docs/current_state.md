# 当前状态

## 2026-07-18 准实时赛前 racecard/off time 增量已发布，首轮英国 prepare 安全停止

- 用户在最新成功代码 review 后授权的冻结版本已发布。提交为
  `6646302b80c90cf406075516ab4812f2f4ebee18`，生产 checkout、web、普通 worker、Beat
  与独立 `race_live_worker` 均运行 AMD64 image
  `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`；镜像内
  registry SHA-256 为
  `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。
- 写前数据库备份为
  `/opt/umanewsbot/backups/db/pre-racecard-6646302b-20260718_105233.dump`，
  `196,919,649` bytes、权限 `0600`、SHA-256
  `6bdda3152cb3ee6a92fc774989dde7fc94614149066e01e4bb746d85fb9f7882`，
  `pg_restore -l` 通过；环境备份为
  `/opt/umanewsbot/.env.backup.pre-racecard-6646302b-20260718_105233`，回滚标签
  `umanewsbot:rollback-pre-racecard-6646302b-20260718_105233` 指向旧 image
  `sha256:111dbe46ba7a7024632ba2ca7c57c387b19ab39861f0147421a0245d08c38d7a`。
- 部署后 Django check、migration check、model drift 和镜像内 racecard sync/initializer v2
  `20/20` 通过；无 migration。web、两个 Celery 节点、Beat 和 Nginx 正常，内外 HTTP
  `/healthz/` 为 200。只有 `race_live_worker` 挂载 `/run/secrets:ro` 和
  `/run/race-live/racecards:rw`，web/普通 worker/Beat 均无这两类挂载。
- 生产继续保持 `RACE_LIVE_SCHEDULER_ENABLED=false`、
  `RACE_LIVE_RUNNER_MODE=disabled`。`race_live` 队列为 0；普通 worker 恢复 Beat 后正常
  处理既有新闻抓取任务，不与 live worker 混用队列。
- 首轮受控 prepare 只选择英国 event `924`，run 为
  `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-20260718T030337Z`。
  today/tomorrow 两个固定 GB 请求均为 HTTP 200，但严格赛场、日期、赛事名匹配得到
  `racecard_not_found`，因此 `completed=false`、未生成 `manifest.json`，不得运行
  initializer。report/request SHA-256 分别为
  `bd7a19f8867df38e21e88ae2db465f9b6c5be30ad3b520e6b7fa988c9f5ae46a` /
  `78fef17cc843d8f83588a716dffc7fab0de56a740b88edc2a5510e0b99afcf2d`。
- prepare 后赛事总量仍为 `9,867 events / 100,132 runners / 91,897 results`；live
  control/tracking/source/observation/revision/publication/incident 全为 0，仅按设计新增
  `1` 条 `RaceLiveHostBudget` 控制面记录。下一步必须先审核 event 924 与 TRA racecard 的
  身份/别名或覆盖缺口，再以受审数据修复和新 run-id 重跑；不得猜测开赛时间、放宽精确
  匹配或对 blocker artifact 运行 initializer。

## 2026-07-18 准实时赛前 racecard/off time 同步已实现，待独立代码审核

- 独立 worktree 为 `/Users/mentianlu/Code/umanews/.worktrees/realtime-racecard-sync`，
  分支 `codex/realtime-racecard-sync`，基线为最新
  `origin/main@234358979dea3620d04445bb569b30e4a5b2fe8a`。change artifacts 位于
  `docs/changes/realtime-racecard-sync/`；同一方案 reviewer 已关闭全部 P0/P1 并给出
  `APPROVED`。
- 新增显式 event ID 驱动的英国 TRA Free racecard prepare：固定请求
  `today/tomorrow + region_codes=gb`，经共享 HostBudget 1 RPS、最多一次且不超过 2 秒
  等待、`Europe/London` instant 转换、赛场/赛事名精确匹配后，原子生成不含 raw 或专有
  字段的 `manifest/report/requests`。零命中、多命中、baseline 漂移、条款/registry 或
  路径异常均只形成 blocker，不产生可 apply manifest。
- initializer 新增 schema v2：完整 run 目录只读加载并重算 companion SHA，锁内区分
  fresh/replay，逐字段核对 status/local date/timezone/旧时间，在同一事务补齐
  `race_datetime/local_start_time` 并初始化 participant/racecard/live shadow 行；不同
  manifest、人工锁、身份冲突或后段失败全部 fail closed/回滚。schema v1 保持兼容。
- `racecard_ready` 的有效赛前 claim 现在零 HTTP checkpoint：释放 claim、失败计数不增、
  `next_poll_at` 推进且不晚于 off time；到达 off time 后才在 owner/claim CAS 下晋级
  `awaiting_result` 并进入既有赛果请求。stale claim 或 owner 漂移保持零写入。
- 真实 RED 已记录在 change 的 `test_cases.md`。主代理复跑的 GREEN 为 SQLite 组合
  `203/203`、一次性本地 PostgreSQL 16 初始化/runner 并发与锁语义 `6/6`；Django check、
  migration drift、三份 Compose、`py_compile`、registry SHA 与 `git diff --check` 通过。
  新 registry SHA-256 为
  `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。
- 首次独立原生代码 review 找到两个 P2：同 run-id 并发异常清理可能删除赢家 artifact，
  以及赛事占用检查在 40 场时产生 322 次查询。两项均先补真实 RED，再加入 root 级发布
  锁/目录 inode 所有权校验和八类固定批量占用查询；修复后 racecard sync `13/13`、
  准实时相关组合 `184/184`，等待复用同一 reviewer session 限定复审。
- 当前只完成本地实现和验证：尚未 commit/push/deploy，未访问真实 TRA、未运行生产
  prepare/initializer，未改变生产 HostBudget 或赛事业务数据，scheduler 仍为 false、
  runner 仍为 disabled、公开 policy 未开启。下一门禁是独立代码 review；只有其成功后
  才向用户请求本任务新的发布授权。

## 2026-07-18 8,867 场已导入历史赛事已公开

- 生产只读 eligibility 审计确认 `8,867 eligible / 0 blocked`，地区分布为日本 `2,239`、中国香港 `473`、英国 `2,144`、法国 `652`、美国 `3,359`。原始审计位于 `/opt/umanewsbot/runtime/historical_publication/eligibility-20260718_031331/publication-manifest.json`，SHA-256 为 `2768e9f66fcba74dad95ffe4505d8283ff11c1d6e2c3fb2c2bde3b2f213a110e`。
- 正式不可变 scope 为 `/opt/umanewsbot/runtime/historical_publication/eligibility-20260718_031331/publication-scope-v1.json`，SHA-256 为 `c27491e4987a548a6c635c936b28211a1c0e2e1c8c0bd594b8467bfba539977a`；它固定 `8,867` 个 target ID 及逐目标 artifact SHA，不按线上动态查询扩张范围。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-historical-publication-8dec0076-20260718_041218.dump`，`195,414,204` bytes，SHA-256 为 `83a7524eb36bdb69e9cece8a749115022e9b94682b9dd37080df5756358a9d29`，`pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.historical-publication-8dec0076-20260718_041218`。
- dry-run、原子 apply 和独立 verifier 均为 `8,867 checked / 0 errors`。结果 SHA-256 依次为 `d830060cf33bd6ebb6ce6f5ed141799497e893fb74cdbaa79bbbfe5031dc0485`、`46f5a58eeefed4c35547308ede4cfcf7b83b1842d344cbd40e17a8ad9216853e`、`35cee37116bc0eeff4fa1bd940c01dc8f4ad8e8a9a908fd320d15a6417e04d2b`。
- 生产现有 `9,867 RaceEvent / 9,820 published / 8,867 published+complete / 100,132 runners / 91,897 results`；`8,867` 个 imported 历史目标全部已关联到公开且完整的赛事。
- 浏览器验收覆盖五区列表、赛事详情、历届、出马表、赛果和移动端。纯数字距离现按地区及赛事类型显示单位：日本、中国香港、法国为米；美国及英国平地为弗隆；英国障碍为英里。数据库原值、导入器、API 和 verifier 口径未改变。
- 最终运行代码 revision 为 `4af5e20a3c65ddad81bcf054f7fd1cb1f8d0dfde`，tree 为 `32928369f7c20c74425902ba3d13932d7a0c0043`，web、worker、Beat、`race_live_worker` 和 `umanewsbot:prod` 统一使用 AMD64 image `sha256:111dbe46ba7a7024632ba2ca7c57c387b19ab39861f0147421a0245d08c38d7a`。公网 `/healthz/` 和赛事页为 200，Redis `celery/unacked/race_live` 队列均为 0。
- 历史公开通过 `RaceEvent.visibility_status=published` 和 `data_quality_status=complete` 持久化，不依赖常驻抓取开关。生产仍保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`、`RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`。
- “已公开”不等于 `30,917` 条正式总账全部完成。总账当前另有 `20,544 pending / 1,467 source_unavailable / 31 identity_review_required / 8 ready`；后续抓取继续按这些缺口推进，不回退或重跑本次已公开的 `8,867` 场。

## 2026-07-18 准实时赛果安全基线已发布，shadow 因赛程时间缺口保持关闭

- 最新成功 review 后的整合冻结版本已按用户授权发布：生产 `HEAD=4f11b2273fd167c69d54b338a4e627a77dd010c2`、tree `277cb10ad56aee9a3156fa2b1632dd73377054c8`，source archive SHA-256 为 `e957e748b82b4933eeaab2f5721185e42e6f4e58b9e552ee10cfabace11ca2d5`。web、普通 worker、Beat 与独立 `race_live_worker` 均运行 image `sha256:c2b9e15e037406808bef1edbbef888728a8f0d6ae40c47418c6cd4e414803966`，OCI revision 与生产 checkout 一致。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-realtime-race-results-4f11b227-20260718_034437.dump`，`195,161,786` bytes、权限 `0600`、SHA-256 `f81a11ece1b75f5ff680e445b71b910ea453ee1fc26eeb24ac8df030daf72a01`，`pg_restore -l` 通过。环境备份为 `/opt/umanewsbot/.env.backup.pre-realtime-4f11b227-20260718_034437`；即时回滚标签 `umanewsbot:rollback-pre-realtime-4f11b227-20260718_034437` 指向旧 image `sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`。
- 生产已应用 `stable.0033` 至 `stable.0045`；Django check、migration drift、镜像内初始化器与 TRA runner `13/13`、registry SHA 和无 secret 检查通过。迁移后 `9,867 events / 100,132 runners / 91,897 results` 保持不变，所有 live control/tracking/observation/revision/publication/incident 行均为 `0`。
- TRA secret 仅存在于生产 `/opt/umanewsbot/runtime/secrets/the-racing-api-free.env`，为 `root:root 0600` regular file。生产配置保持 `RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`；普通 worker 只消费 `celery`，独立 worker 只消费 `race_live`，后者队列为 `0`，没有发送 live 网络任务或公开写入。
- 生产只读来源 proof 位于 `/opt/umanewsbot/runtime/race_live_source_proofs/production-proof-20260718_035358`：3 个固定 Free 端点均 HTTP 200，regions/racecards/results 分别为 `55 / 69 / 50`，请求元数据 SHA-256 为 `421a3d7976fbaee0e5c2ed20caaf8fa7b7647895fed6e2666971248ecbb6fc59`；未保存 raw payload，未连接业务写路径。
- 首轮英国 shadow 没有生成或应用 manifest。生产从 `2026-07-18` 起共有 `428` 条 future `RaceEvent`，其中英国 `72` 条，但 `race_datetime` 非空均为 `0`；当天英国 Group 3 event `924` 同样缺少 `race_datetime/local_start_time` 且无 runners/results。冻结初始化器要求 aware `race_datetime` 并精确匹配既有赛事，仓库也没有已审核的赛前 racecard/开赛时间写入路径，因此当前必须 fail closed。不得手工猜时间或绕过初始化门禁；需要把赛前 racecard 与开赛时间同步作为后续受审增量。
- web 重建后 Nginx 曾保留旧容器 IP 并短暂返回 502；重启 Nginx 重新解析 `web:8000` 后，本机和公网 HTTP `/healthz/` 均恢复 200。四个 app 服务 restart count 均为 `0`，近期 app 日志无 `Traceback/CRITICAL/ERROR/Exception`；公网 HTTPS 仍是既有未接入状态，不属于本变更验收。

## 2026-07-18 AI 赛事身份决定已完成生产写入

- AI 初审的 `267` 条决定已经按原 manifest 完成生产执行：`228` 条合并并关联、`21` 条保持独立、`18` 条非同赛／忽略；实际写入汇总为 `228` 个正向动作、`24` 个去重后的负向系列对和 `1` 个 John C. Harris Stakes `surface: dirt -> turf` 修复。
- 正式 manifest 仍为 `cf5e220e9c0a0c7b2daeb7ef5030ed3243059ec9bd36ba5e6e2390c0d89a0147`，actions 为 `9622460e82dc4d3449bf693bf2e7e107e43684c5b5dbf518bc700a4a24f53da1`，用户签署 approval SHA-256 为 `f02b0e4c11a605fe3d4f818856d699a8979c12b9884d04d93ed32adbb44b0584`。未重算或替换任何审核决定。
- 首次 apply 在 PostgreSQL 第一组锁查询被 `FOR UPDATE cannot be applied to the nullable side of an outer join` 拒绝，发生在业务写入前；prepared verifier、总量和 OperationLog 复核均证明零写入。技术修复改为只锁 target/event 基表、继续预取系列并独立锁定全部相关系列；本地相关测试 `52/52` 通过，PostgreSQL 专项在 SQLite 按设计跳过 1，同一原 reviewer 限定复审为 `APPROVED`。生产只读 smoke 成功锁定并回滚 `497 series / 267 targets / 261 events`。
- 最终代码 revision 为 `f396d04837c7161a351b920737ac030911dec3e3`，tree `f9bef70b59f2ee0dfa0bbd2a78c5c2c316e45d45`，source archive SHA-256 `fd0c66acb2cef161746e2b2d851106ac12ba475abdab0b5107f2871a1e557d72`。两个独立归档上下文构建得到相同 AMD64 image `sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`；生产 web/worker/beat 已统一运行该镜像。
- 最终写前备份为 `/opt/umanewsbot/backups/db/pre-race-series-identity-f396d048-20260718_014337.dump`，`194,307,039` bytes、权限 `0600`、SHA-256 `640791685f14d82cd8a47a9c83ce2b6fb4a361e8edafa824c9c2e6338c892707`，`pg_restore -l` 通过。即时代码回滚标签为 `umanewsbot:rollback-pre-f396d048-20260718_014256`，环境备份为 `/opt/umanewsbot/.env.backup.pre-f396d048-20260718_014256`。
- 正式 apply result SHA-256 为 `20fb046276e633ba9c682fc62ec865dca41acff2ce6bccd5ad74256fb02b3365`，rollback ledger SHA-256 为 `0a37af374fc06a2e19cb70360c1a512389f066d99f6927c079c76cc4389531e5`；事务内和独立写后 verifier 均为 `ok=true / error_count=0`，OperationLog ID 为 `96353`。
- 写后总量严格守恒：`9,867 events / 100,132 runners / 91,897 results` 未变化；正式目标关联由 `8,875` 增至 `9,103`，系列关系由 `0` 增至 `228`，John C. Harris event `507` 已为 `turf`。historical runner、锁、started receipt、翻译和外部导入均为 0；历史公开、常驻历史写入和网络开关保持关闭。内外 HTTP healthz、worker ping、active/reserved、Redis 队列和近期错误日志均通过。

## 2026-07-18 准实时暂定赛果主链已补齐生产 shadow 初始化路径

- The Racing API Free 自动化 runner 已完成真实 RED -> GREEN：固定 HTTPS host/path、仓库外 `0600` secret、审核 registry digest、条款/automation permission、1 RPS 共享 host budget、15 秒 timeout、2 MiB 上限、禁止 redirect，网络期间不持有数据库事务。Free racecards/results 请求上限按当前官方文档修正为 `500/50`；当前 registry SHA-256 为 `1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`。
- 合法且唯一匹配的结果先写 append-only observation 和 shadow revision，再经唯一 `admit_race_live_publication()` 重读 owner/claim、TRA supplemental authority、持久 policy/allowlist、coverage/registry digest、获准 racecard 参赛全集、身份审核和人工锁；通过后才物化公开暂定赛果并原子创建 `off time + 2h` 官方复核 incident。空列表或未命中只做短间隔 checkpoint，不会清空或覆盖现有赛果。
- 已新增默认关闭的 global/region/source/event 公开读取门。任一适用 policy 改为 off 时，已发布 live badge 和当前物化赛果立即从详情读取面隐藏；恢复后仅重显仍满足版本/digest 门禁的 revision。新增 publication policy、event allowlist、official marker/evidence/incident 五张只读后台观测面，人工 kill switch 继续走 CAS 审计。
- Celery task 只有显式 `RACE_LIVE_RUNNER_MODE=the_racing_api_free` 才进入真实 adapter；scheduler、runner 和三个 secret/registry 配置默认关闭/空。三份 Compose 只给独立 `race_live_worker` 挂载 `./runtime/secrets:/run/secrets:ro`，镜像内只复制受审 registry，不向 web、普通 worker或 beat 暴露 secret。
- 首次完整代码 review 的原生命令因模型容量中断，人工检查提出的旧时钟、incident replay、日历 read gate、raw official marker 与生产初始化路径问题均已取得 RED 并修复。新增 `initialize_race_live_events`，以严格 schema v1、manifest SHA、approved commit、赛事更新时间和人工锁为门禁，提供默认 dry-run、显式 apply、独立 verify、全事务、精确 replay 和逐 event 审计；migration 不隐式接管赛事。
- shadow 初始化只创建四层 shadow policy、精确 allowlist、host budget、live control/tracking、TRA supplemental source、approved participant/racecard revision；shadow 命中结果只写 observation、未发布 revision 与成功 checkpoint，不生成公开赛果、publication 或 official incident。初始化器与 TRA runner 聚焦 SQLite `13/13`，临时 PostgreSQL 初始化并发及既有锁测试 `5/5`。
- 首次成功原生完整 review 关闭旧时钟、incident replay、生产初始化和 raw official marker 等问题，但发现赛事日历对每场 live revision 单独执行读取门禁：40 场页面实际产生 `525` 次查询。新增查询预算 RED 后，日历改为固定批量加载 event/control/revision/observation/source/publication、四层 policy 与 allowlist；详情页继续使用单赛事判定，fail-closed 语义不变。修复后公开状态组 `6/6`、准实时/来源 proof/初始化 SQLite `160/160`、临时 PostgreSQL `5/5` 通过，40 场页面受 `<=12` 查询硬门禁约束；同一 reviewer 已限定复审为 `APPROVED`。
- 合并前冻结候选镜像为 `sha256:4a281e426e3299287c948bc6fe7d6e2d0fcda52dbaa322da8db9982530b5b099`，OCI revision 绑定原 approved parent `283bacf2cdc5ff97423b50ff46cfda2a87120a2b`。镜像内 Django check、实际交付的初始化器+TRA runner `13/13`、registry digest `1d801e95...fa32` 和无 `.env`/secret 检查通过；完整源码树 `160/160` 单独通过。整套源码测试不能误当镜像自测，因为其中部署契约会读取不会被打包的仓库根 Compose/源 registry；三份 Compose config、两个 worker 脚本、migration drift 和 diff check 已在完整源码树独立通过。
- `main@ccb56f7d` 的赛事身份 PostgreSQL 锁修复和生产证据已保留，并把准实时补丁重放为以该 main 为单一 parent 的整合树。准实时+来源 proof+初始化+赛事身份 SQLite 组合为 `180/180`（1 项 PostgreSQL 专用按设计跳过）；准实时 5 项与赛事身份 1 项 PostgreSQL 专用测试在临时 PostgreSQL 16 为 `6/6`。整合候选镜像 `sha256:87f8603320f856bbc4167f29b76c811fe6e2a06b62bfb72dd73b944840b73bcf` 绑定 parent `ccb56f7d526daf70357f193f716b23eacb26edbe`，镜像内 check、初始化器+TRA runner `13/13`、registry SHA 和无 secret 检查通过。
- 2026-07-17 的 run03 因本机代理把 DNS 映射到非公网 `198.18.1.15` 而在首请求前安全阻断；未放宽 DNS/SSRF 门禁，先前 run02 的 3/3 HTTP 200 proof 仍为最近一次成功真实窗口。
- 尚未创建任何生产 tracking/source/participant/policy/allowlist 行，未启动生产 live worker、未迁移、未公开、未购买订阅。原冻结提交已获授权并推送，但 `main` 随后新增赛事身份生产修复与证据；基于 `ccb56f7d` 的单父整合树仍须由同一 reviewer 复审并重新取得用户授权。之后才能备份并应用 `0033-0045`、生成并审核精确 event handoff manifest、先初始化单地区 shadow，再逐赛事审核 provisional allowlist。官方 marker 自动 apply、incident 告警/长期探针及官方地区 adapter 不属于首轮 TRA provisional 公开链，不能据当前状态宣称正式赛果自动化已完成。

## 2026-07-17 AI 赛事身份初审已固化，生产写入待精确授权

- 用户提供的 AI 初审工作簿为 `/Users/mentianlu/Downloads/生产赛事身份审核_213a818c_20260717_AI初审建议.xlsx`，SHA-256 为 `d93286e9e61ccf41770fe607740a972d025c8a00b2deb1d4a4f1890954852492`。正式输入共 `267` 条：`228` 条同意合并并关联、`21` 条保持独立、`18` 条非同赛／忽略；John C. Harris Stakes 另附 `surface: dirt -> turf` 的显式字段修复。
- 身份执行工具已进入代码 commit `8b9b97552a6cb8b4b4690dc6f8b1a1d4233991e5`，tree `ab1f58af54381e72c7c277f03a59a29676618dae`。它只移动经批准年度赛事的系列归属、建立正式目标关联和 `MERGED_INTO` 沿革；不删除 `RaceSeries`，不改变公开状态、赛事状态、出马表或赛果。保持独立和误命中会写入双向禁止自动合并规则，字段修复独立执行。
- 真实 RED 后 focused/相关组合测试最终 `50/50` 通过；Django check、迁移无漂移和 diff check 通过。同一 reviewer 连续复审了事务、锁、序列唯一性、正负决定冲突、跨地区误命中和 TOCTOU 修复，最终结论为 `APPROVED`，无剩余直接 P0/P1。
- 生产只读 prepare 已在现有 `213a818c` 运行环境中加载上述精确代码完成，没有部署、重启或写库。有效 artifact 位于 `/opt/umanewsbot/runtime/race_series_identity_review/prepare-8b9b9755-20260717_205349/artifact`；manifest SHA-256 为 `cf5e220e9c0a0c7b2daeb7ef5030ed3243059ec9bd36ba5e6e2390c0d89a0147`，actions SHA-256 为 `9622460e82dc4d3449bf693bf2e7e107e43684c5b5dbf518bc700a4a24f53da1`，prepared verifier 为 `ok=true / error_count=0`。
- `approval.json` 仍为 pending，尚未签署或执行生产 apply。下一门禁是用户对上述 commit、manifest 和 actions 的明确授权；授权后才可部署精确代码、生成并验证新数据库备份、再次 dry-run/verify、由 `admin` 串行 apply 并逐项验收。历史公开、常驻历史网络和写入开关继续关闭。

## 2026-07-17 赛事正式总账与公开赛程关联工具已发布，生产只读审计待身份审核

- 已确认此前“7 场未到期”只代表 `8032` 个历史详情验收目标中的 `not_due`，不代表生产全部未来赛程；生产在 `2026-07-18` 至 `2026-07-31` 另有 `44` 条公开 `scheduled RaceEvent`，多数尚未关联正式目标。
- 新增只读 reconciliation、historical/current/result 三层覆盖报告、HTML/CSV 审核表、manifest+approval 双 SHA 门禁、整批原子 apply/rollback 和逐目标 verifier。 `not_due` 只允许采用同系列同年度的唯一既有 `scheduled/postponed` 赛事，不创建、删除或公开赛事，也不改变目标/赛事其他状态。
- change 文档位于 `docs/changes/reconcile-race-event-coverage/`；真实 RED 后 focused `22/22`、相关组合 `101/101`、Django check、迁移漂移和 diff check 全部通过。首次代码 review 的 8 项事务、TOCTOU、artifact、快照、alias 和统计问题已修复，同一 reviewer 复审为 `APPROVED`。
- 用户已批准 commit `213a818c2845fd29a2afe742ea8d11f653269d9e`。该提交已推送并快进合入 `main`；两个独立 AMD64 构建得到相同 image ID `sha256:f3b2d4625322e7f96554288d4b710723ff9d01323dd3be654bcbc2ba0281a9d9`，tree `799f77db3f253e524f5f0095ed07a4fe9c8cd058`，source archive SHA-256 `c15bec6853266cd61c4852380ff1f6613cfe4bc9e1614ad3a5272d1edf9eb92a`。生产 web/worker/beat 与服务器 checkout 现均为该 revision；无迁移，HTTP healthz 和 `/races/` 正常。
- 部署前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-race-reconcile-213a818c-20260717_015716.dump`，SHA-256 `7958873ff243f5a3c1bb85075f74fa0daec6a040f33688b31f63db71e1eb0e3b`，`pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.pre-213a818c-20260717_015716`，回滚标签指向上一镜像 `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab`。
- 有效生产只读 artifact 为 `/opt/umanewsbot/runtime/race_event_reconciliation/prod-213a818c-mounted-20260717_021203`，manifest SHA-256 `5caee7d0ed093605aede28c2834d3acf8a75f9f20e2d88679924c3670f3c6a51`，verifier `ok=true / error_count=0`。基线为 `30,917 targets / 9,867 events / 100,132 runners / 91,897 results / 5,725 history winners`；分类为 `8,875 already_linked / 46 identity_conflict / 21,537 missing_event / 459 status_conflict / 0 exact_link`。
- 因该精确 manifest 没有可执行关联，approval 继续为 `pending`，没有签署、dry-run apply 或数据库关系写入。`not_held=459 / cancelled=15 / not_due=7` 是不同口径；2026 另有 `630 missing_event`，不得解释为未举办。严格赛果层因生产旧数据尚未写 `RaceEvent.result_confirmed_at` 而得到 `complete=0`，这是新显式确认字段缺口，不代表 `91,897` 条现有赛果消失。
- 只读明细进一步得到 `46` 条同名系列冲突和 `221` 条 2025–2026 别名/跨语言候选；其中 target `53418 / Tokai S` 与 event `83 / 東海S / 东海锦标` 日期、级别、场地类型和距离一致，但属于两个 `RaceSeries`。46 条中另有英国 Sprint Cup 命中香港同名赛事、美国 Hanshin Cup 命中日本阪神杯等跨地区同名技术噪声，必须排除后再做系列合并决定。审核文件为本地 `outputs/race_event_reconciliation_20260717/生产赛事身份审核_213a818c_20260717.xlsx` 与同名 HTML；确认系列身份后重新生成非零 `exact_link` 的 manifest，才允许进入备份、apply 和 verifier。
- 收口时无 historical one-off；常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史公开配置未开启。普通新闻 worker 有自然 crawl task 运行，Redis 主队列为 `0`；生产可用磁盘约 `3.6 GiB`，低于 `5 GiB` historical crawl 门槛，继续禁止在生产执行重型抓取。
## 2026-07-17 The Racing API 调整为暂定赛果公开主链

- 用户明确确认：对 The Racing API 已覆盖且通过身份/字段校验的目标赛事，不等待 JRA/NAR/HKJC 等官方来源二次复核即可把完整赛果推到前台；页面必须标注“暂定赛果”和更新时间。
- 官方来源改为异步复核链：一致则升级 official，不一致则保留 TRA observation 并原子显示官方 revision；正式/改判 authority 仍只属于持久、已审核的官方 source identity。
- 商业 API 信任不替代赛事/参赛马身份、完整字段、空结果、人工锁、冲突、条款、allowlist 和 mode 门禁。publication admission/read gate、TRA supplemental 数据库不可变量、基于 racecard 全集的完整性和 provisional 发布时创建官方复核 incident 已实现；官方 marker 自动 apply、incident 告警/长期探针和各地区官方 adapter 尚未实现。用户已授权测试先行、实现、shadow 与上线准备；实际生产发布仍须在最新成功代码 review 后取得一次新授权。

## 2026-07-17 准实时赛果完成 The Racing API Free 首个受控来源窗口

- 仓库外 `0600` secret 已投入使用，未把凭据复制到工作树、镜像、日志或 artifact。新增 proof runner 以精确 registry SHA、官方文档/条款证据、最多 3 请求预算、1.05 秒请求间隔、15 秒 timeout、2 MiB 上限、禁止 redirect/retry 和公网 IP/TLS 校验 fail closed；不访问 ORM，只保存脱敏 schema/计数/延迟/SHA。
- 多轮真实 RED 后，proof 测试 `9/9`；proof + 准实时 `126/126`；与 latest-main 相邻历史回归合并为 `262/262`（1 skip），隔离镜像、`--network none`，Django check 0 issues。reviewer P2 指出 proof 错误依赖长期 automation 许可，现已用 proof-only RED 解耦；生产/shadow adapter 仍须单独要求 automation 许可。后续两个质量建议也已修复：未来 proof 记录真实完成时间，未知 result status 不再伪造成 DNF；无效/倒退/异常时钟和无 partial artifact 均有自动化回归。
- run01 因本地代理 DNS 返回非公网地址于首个请求前安全阻断。run02 使用一次性本地容器固定经独立 DNS 审计的公网地址，三个 Free endpoint 均 HTTP 200：regions 55、racecards 10、results 0；未保存 raw/实体值、未写业务 DB、未连接生产。
- 这只是第一个观察窗口，只确认认证、端点和 schema。尚无已完赛样本，不能计算 result 覆盖或 p50/p95，也不能判断 provisional/official/corrected 或建议升级 Basic；至少四个真实赛日和正式重点赛事样本门槛保持不变。完整证据见 `docs/changes/realtime-race-results/source_proof_report.md`。
- proof runner 完整 review 的唯一 P2 和后续时钟测试覆盖 P2 均已由限定复审关闭并 `APPROVED`。本地 automation `tra-free-proof` 每日 06:30（本机时区）执行至多一次同一受控 proof；四个不同赛事日期且至少一个 results 非空后停止联网并提示汇总。它只写 gitignore runtime artifact，不改 tracked 文件或业务 DB。
- 当前仍不部署、不启动生产 live worker、不初始化 tracking、不购买订阅、不打开公开开关。

## 2026-07-16 第一期 1998–2026 历史赛事正式详情总账已收口

- 正式详情分母固定为 `8032`，最终为 `6534 complete + 1491 evidence gap + 7 not_due`；生产验收为 `6534 events / 70314 runners / 65227 results / 6534 winners`。日本、中国香港、法国 hard 范围完整；英国历史 hard 为 `708 complete + 45 evidence gap`；英国新正式范围为 `94 complete + 1 gap + 4 future`，美国新正式范围为 `195 complete + 1 future`。英国、美国历史 G2/G3 按已批准的 best-effort 政策收口，不把无可靠来源的目标伪造为完整。
- France 14 场补包 manifest 为 `7e8f29066bccae965ade8736e071189155cb8245e92309f07bf23bfa67f50eeb`，写入 `132 runners / 122 results / 14 winners`。写前备份 `/opt/umanewsbot/backups/db/pre-france-zone-turf-7e8f2906-20260716_2204.dump`，SHA-256 `ed7e189796d2d8d87c27874ecbab796db99829322e5cf9cfb388db9b362b60a9`；replay 与 verifier 均为 `errors=0`。
- UK 6 场补包 bundle 为 `fd3438beaeabbf15ed365069707cea982221a444716161d66a30e74bc2a0a081`，写入 `46 runners / 40 results / 6 winners`，出走状态为 `40 declared + 4 pulled_up + 2 withdrawn`。dry-run plan 为 `490400342fe30e4fe291691d7cc61801d42f025663cb25245d4d5793c122560e`；apply2 plan/state 为 `473495fbb70c22823d29471aa436d52a343596c23562043a42aff35c3dbdabbb` / `ca51bb347c4313a0bfeee645cc7fe9f33013da09713d2acbee02f69c0e688f0f`；replay plan/state 为 `5e1b5895d217b2f265cc9455b35679e566ebd7f922dedae3caf80bdc349070b1` / `cc5d9d149fbfe20a3796a9b6bf62e75e233448939f4b1ce6799ac9fffbade6ba`。
- UK 场地修正 manifest 为 `662be6d37e55fda7b3b2d620ddc61fe0ba2bc0291270d4bd7439ae8a4c0da903`，script SHA-256 为 `1ac34051d5c8a72294364b1f4d5b524c55d81e393c1188edcb12fbd0a508407c`；apply 与两次 verifier 均为 `4/4`。
- UK 6 场与 gap 裁决统一写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-uk-six-gap-659b46ca-20260716_230344.dump`，`189338143` bytes，SHA-256 `c5006b15bee22dd17d0d6fb7913f7c376a0799eeb37f3d6dc42b9199444c1410`，权限 `0600`，mtime `2026-07-16 23:04:32 +0800`，`pg_restore -l` 通过。
- gap/not_due resolution manifest 为 `d529126840a6d3c6ffb1abc0a426d3ac796d36f9df72a50dcc06b34e0af9c90f`；`1498` 条 resolution 已 apply，并通过两次独立 verify，生产存在 `1498` 条唯一 `OperationLog`。原因分布为 `1467 source_unavailable + 31 identity_review_required`；最终状态按到期日收敛为 `1491 gap + 7 not_due`。其中 target `53349` 的正式日期为 `2026-09-05`，target `53418` 为 `2026-07-26`。
- 最终 v5 产物位于 `runtime/race_event_crawl_runs/final-detail-coverage-ledger-v5-20260716`；manifest SHA-256 为 `692b089b0d18b08899571702cb57ff3dadbca144a2dce4c4e6b3d7c15e6584ea`，ledger SHA-256 为 `833995952fc444fd39c40934802cc7306cc7dd354c4f57db5bd725fc66a48fe9`，review 结论为 `approved`。global verifier 检查 `8032` 个目标，`errors=0`。
- 生产部署运行态：`prod` 与 web/worker/beat 统一为 image `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab`、revision `6b596befa0eea9ef0ba45acbb5384195829cc144`。即时回滚标签 `umanewsbot:rollback-pre-6b596bef-20260716_233842` 指向上一镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`；环境备份为 `/opt/umanewsbot/.env.backup.pre-6b596bef-20260716_233842`。本次无迁移；Django check、两个正式 HTTP 域名 `/healthz/` 200、worker ping 均通过，日志未发现 error。
- 收口运行态为 formal `published=0 / featured=0`，`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，无 historical runner、无 running batch。清理未使用的旧 `umanewsbot` tags 后仅保留当前镜像与即时 rollback，可用磁盘由 `2.6 GiB` 升至 `4.0 GiB`；仍低于 `5 GiB` crawl floor，后续服务器 crawl 为 no-go，重型抓取继续使用本地 Docker。
- 结论：第一期 `1998–2026` 正式详情总账已按批准政策全部达到“完整或证据化 gap/not_due”，生产数据写入完成；本结论不等于赛事已经公开，历史公开仍保持关闭。

## 2026-07-16 英国 Sporting Life 增量详情包已正式导入生产

- 第一阶段应到清单尚未全部写入。本轮在本地 Docker、全程无数据库连接下补抓英国 Sporting Life 已发现目标 `198` 场，最终为 `197 complete + 1 parse gap`，包含 `2027 runners / 1794 results / 197 winners`。唯一缺口为 target `57633`（2015 Finale Juvenile Hurdle），来源页没有可解析 runner rows，已保留在统一 gap/review ledger；该缺口没有被伪造为 complete。
- 解析器提交为 `2a7352c8abfbd3b22aca274a1eeb3fda07731eb8`，真实缓存 RED 后回归 `39/39`，独立代码审核结论为“未发现可修复问题”。结构化 casualty 现可保留 `NonRunner / UnseatedRider / PulledUp`；普通 `tailed off` 文案仍不会被武断映射为退赛。
- 六个 2023 英国目标的旧总账距离丢失英里位，已按 Sporting Life 详情页结构化距离生成独立 correction ledger；原值、新值、来源 URL 和 fixture SHA 全部绑定。v8 plan manifest 为 `9f3042caf4a9bc27dbc5d9e1130b4a72a1e0f380ca2a3ef24dabca1322b729b0`，correction ledger 为 `ab17e79d823dff6e79d27b69a751aa10c8d700787e104a646229106e8c003350`。
- 增量 source bundle 位于本地 `runtime/historical_plan_exports/detail-import-bundle-uk-sportinglife-v8`，已在生产隔离目录 `/opt/umanewsbot/runtime/historical_race_detail_import/detail-import-bundle-uk-sportinglife-v8` 逐字节复核。bundle manifest 为 `3c6a4d11106c2b490876d63f0719b71d6fde9d7c7bc9c8937736d26a0e28831c`，identity 为 `2392a69c7cf1b03812422cf11b3c5ed73a181e719ca6309d79283812c735cb50`；当前生产镜像在 `--network none` 下验证 `197` records、`197` source objects、`67302603` source bytes 全部通过。
- 用户按 commit `2a7352c8` 和 bundle manifest `3c6a4d11106c2b490876d63f0719b71d6fde9d7c7bc9c8937736d26a0e28831c` 明确授权。approval 于 `2026-07-16T09:33:54Z` 签署；historical approval SHA 为 `6a0240453cf19d681365a7add59ff2ea254fff5dfaee3ca6722495450ca87aec`，current-year-due approval SHA 为 `93bf1143460450015365f85fa7d2c3aae2a479180ccf69c953e9622d1fac06b1`。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-uk-sportinglife-v8-apply-700a2a96-3c6a4d11-20260716_093456.dump`，`175094189` bytes，SHA-256 `a942e2dad092bdf0af9e0546030a73c75dfeebb1c89ee888d704e8244d7f0d6c`，权限 `0600` 且 `pg_restore -l` 通过。`detail-dryrun-700a2a96-3c6a4d11` 对两个 chunk 全量通过，receipt 为 0；随后 `detail-apply2-700a2a96-3c6a4d11` 完成 2/2 receipts，`detail-replay-700a2a96-3c6a4d11` 逐目标检查 `194 + 3`，两块均 `error_count=0`。
- 最终数据库验收精确为 `197 events / 2027 runners / 1794 results / 197 first-place winners`，197 个 target 均为 `imported`，basic/runners/results 均为 `complete`。197 场全部保持 `draft + incomplete + is_featured=false`，公开 0。生产累计 historical imported target/event 为 `7182`，但这不表示一期总账已经全部完成。
- apply 首次尝试 `detail-apply-700a2a96-3c6a4d11` 因 dry-run 根 checkpoint 尚未归档而在业务步骤前 fail closed，错误为 `runtime/database checkpoint mismatch`，receipt 仍为 0。完成状态文件按 run 归档后使用新 run ID 从头执行，未删除 checkpoint、未续跑不明步骤；失败 run 保留为审计记录。
- 收口时 historical runner 容器为空，preflight 为 `migration_safe`；web/worker/beat 统一运行镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`、revision `700a2a961516464ecf93deb0f43a751718efaaca`。HTTP 内外 `/healthz/` 正常，常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史公开继续关闭。worker/beat 恢复后已开始正常新闻窗口，因此 Celery 队列不要求保持空闲；生产可用空间约 `5.1 GiB`。

## 2026-07-16 历史详情 source bundle 已正式导入生产并完成逐目标验收

- 本次按用户授权的审核基线 `943602458bd6975bff1a0bb6bb47ad8e3dde605796a10103461def91a723892a`、content `a353f2f8179432cb807601bf574039db578b265dda2bf3c9d5f9777e1c1b748f`、commit `700a2a961516464ecf93deb0f43a751718efaaca` 和 manifest `dfb86ee85b103688fe1521b07f44ee8f36669d25e85ff3ac2b580a66b38e14d9` 执行。正式 AMD64 镜像为 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`，两个独立构建 ID 一致；tree 为 `0708ce3ef34f64549dd8483c9d7400302052c79e`，source archive SHA-256 为 `20ff51d1f2d6220fba3b0a01615e5366f57605de6e579b6ab222bc70eef597d3`。镜像内聚焦回归 `30/30`、Django check 和迁移漂移检查通过，生产没有新增待应用迁移，`0032` 已处于 applied。
- 正式 bundle 固定 `4930 = 4652 complete + 278 evidence-backed gaps`，其中完整目标含 `51191 runners / 48413 results / 4652 winners`；地区分布为法国 `15`、香港 `19`、日本 `1586`、英国 `171`、美国 `2861`。截至 2024 年导入 `4351` 场，2026 当前到期范围导入 `301` 场；278 个 gap 保留在统一 gap/review ledger，不阻断本次完整目标写入，也不视为已经消失。
- 首次全量 dry-run 在第 13 个 chunk 发现 PostgreSQL 物理索引 `stable_raceevent_series_key_6e15e445` 的 tuple overlap 损坏，事务完整回滚且 receipt 为 0。先生成并校验修复前备份 `/opt/umanewsbot/backups/db/pre-raceevent-index-reindex-700a2a96-20260716_104953.dump`（`151565133` bytes，SHA-256 `43cbfb4faec810a133805f7622f306a1cf44f143891e1235924ff7e85bd48947`），再执行两次 `REINDEX INDEX CONCURRENTLY`，随后从头重跑 `detail-dryrun2-700a2a96-dfb86ee8`，20/20 chunks、4652 targets 全部通过。
- 正式 apply 前重新生成独立 custom-format 备份 `/opt/umanewsbot/backups/db/pre-detail-apply-700a2a96-dfb86ee8-20260716_110915.dump`（`151570907` bytes，SHA-256 `6c7d8f326c4c6a10f685a7be1a0625027cf6732729bcbc6904eba3aa45964b54`），`pg_restore -l` 通过且权限为 `0600`。`detail-apply-700a2a96-dfb86ee8` 完成 20/20 receipts，`detail-replay-700a2a96-dfb86ee8` 随后逐 receipt replay 20/20，最终 verifier 为 `error_count=0`、缺来源 `0`、缺日期 `0`、模块错误 `0`。
- 4652 场全部保持 `draft`、`published=0`、`is_featured=false`。其 basic/runners/results 历史模块已完整写入，但 `RaceEvent.data_quality_status` 继续为 `incomplete`，这是等待单独公开验收的产品门禁，不是导入失败；抽查草稿 URL 返回 404。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史公开继续关闭。
- 生产 web/worker/beat 已统一运行上述镜像，HTTP 首页和 `/healthz/` 为 200，Celery active/reserved、Redis queue/unacked、historical runner 均为空。本次切换显式绑定 service-specific image tags 并使用 `docker compose ... --no-build`；web 重建后 Nginx 曾保留旧 upstream IP 并短暂返回 502，重启 Nginx 后恢复。收口时生产可用磁盘约 `4.5 GiB`，低于既有重型历史 crawl 的 `5 GiB` 门槛，未启动新的生产 crawler。
- batch006 及本次 4652 场均已完成，不倒退、不重跑。历史总目标尚未全部完成：remaining artifact 仍为 `28126` targets（`8857 historical hard / 18173 historical best-effort / 1096 new formal`）；下一步继续按五地区和覆盖分层推进，少量歧义与 278 个现有 gap 留到最终统一审核。

## 2026-07-16 France runner v2 单目标本地 smoke 在 preflight 安全停止

- 本次仅使用本地 Docker，固定镜像 `sha256:e55b8b08bcd5848625a8c1d0fa5abd710783ed3be6fddaf245860ccbc9e55fa8`，OCI revision 为 `d6d6f58b2b5b90301d8fa633a650df28379c09e7`；未连接生产服务器或数据库。
- 已创建独立 run root `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/france` 和共享 host lock 根 `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/host-locks`。France `48498` descriptor 仍把 `run`、`host_lock` 和全部 outputs 不可变绑定到 plan root 下的 `smoke/run/smoke-france-48498`、`smoke/host-locks`，与本次批准路径不一致。
- `discover` 在 launcher 的宿主 preflight 以 `mount contract mismatch for run` fail closed，发生在 `docker run` 和真实网络请求之前。按失败即停规则未运行 `cache / parse / validate / package`；请求数、缓存字节和阶段产物均为 0，无 checkpoint、request log、package manifest 或残留容器。
- 后续不得通过软链接、改写 descriptor 或改用 plan root 可写目录绕过门禁。须先由计划生成侧提供绑定上述独立 run root/共享 host lock 的新不可变 descriptor，再从 `discover` 重新开始。

## 2026-07-16 日本 runner v2 单目标本地 smoke 在 preflight 安全停止

- 本次仅使用本地 Docker，目标为 `japan / 50556`，固定镜像 `sha256:e55b8b08bcd5848625a8c1d0fa5abd710783ed3be6fddaf245860ccbc9e55fa8`，OCI revision 为 `d6d6f58b2b5b90301d8fa633a650df28379c09e7`；未连接生产服务器或数据库。
- 已创建独立 run root `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/japan`，并复用同级共享 host lock 根。Japan `50556` descriptor 仍把 `run`、`host_lock` 和全部 outputs 不可变绑定到 plan root 下的 `smoke/run/smoke-japan-50556`、`smoke/host-locks`，与本次批准路径不一致。
- `discover` 在 launcher 的宿主 preflight 以 `mount contract mismatch for run` fail closed，退出码为 `2`，发生在 `docker run` 和真实网络请求之前。按失败即停规则未运行 `cache / parse / validate / package`；请求数、缓存字节和阶段产物均为 `0`，无 checkpoint、request log、package manifest 或残留容器。
- 后续须由计划生成侧提供绑定上述独立 run root/共享 host lock 的新不可变 descriptor，或经明确审批改用当前 descriptor 原路径，再从 `discover` 重新开始；不得手工修改 descriptor 绕过身份门禁。

## 2026-07-16 准实时赛事赛果 latest-main 复审通过，进入离线测试先行

- 独立 worktree `/Users/mentianlu/.codex/worktrees/97f5/umanews` 的初始 PLAN 基于 `9b617702`；离线 TDD 期间持续安全快进，当前 `HEAD == origin/main@283bacf2cdc5ff97423b50ff46cfda2a87120a2b`。本次先 stash 专项改动，再 `ff-only` 到最新主线并恢复；四份状态/决策/运维文档的顶部新增事实发生预期文本冲突，现已保留主线赛事身份/关联事实与本专项事实并清除冲突。代码仅在 `race_events.py` 的主线新增服务 re-export 与本专项追加实现处自动合并；没有读取或复用历史抓取 runtime 产物。
- 新 change 固化在 `docs/changes/realtime-race-results/`。第一批离线 TDD 已新增发布 mode resolver 与 5 项目标测试；首次原生代码 review 的 `terms_mode` 缺失 fail-closed 和状态记录两项 P2 均已修复，同一 reviewer 限定复审 `APPROVED`。5 项目标测试与 3 项相邻赛事回归共 `8/8` 通过。尚无模型、migration、队列、网络、生产或公开行为改动。
- 第二个离线 TDD 切片已对六态状态机纯函数取得真实 RED 并完成 GREEN：严格允许设计表中的 7 条边，拒绝跳级、倒退、未知状态和未批准自循环；完整准实时模块与 3 项相邻赛事回归共 `10/10` 通过，同一代码 reviewer 完整只读复审为 `NO ACTIONABLE FINDINGS / APPROVED`。审核 approved parent 为 `201ab2d8`，content manifest 为 `c515962d4e1c1f358a6f12112a50af7d4d5c9e16db0a64a671b92666dfe5c960`。尚未接入 revision、来源权限、持久化写入或 ProjectionControl。
- 第三个离线 TDD 切片已对 canonical 内容哈希取得真实 RED 并完成 GREEN：只接受严格 JSON object，mapping key 顺序无关，赛果数组顺序和事实变化会改变 SHA-256。第三轮 review 发现等价 JSON 数字会产生不同 hash 的 P2；已用新增 RED 修复 `1/1.0`、`0.0/-0.0` 归一化，并证明五种 approved phase 元数据均不进入内容 hash。完整准实时模块与 3 项相邻赛事回归共 `15/15` 通过，同一 reviewer 限定复审已关闭唯一 P2，结论 `NO ACTIONABLE FINDINGS / APPROVED`。hash 尚未接入 revision/CAS 持久化。
- 第四个离线 TDD 切片已新增 ProjectionControl 基础所有权行和 `0033` migration：现有赛事不自动建 control，显式行默认 `unmanaged`、generation 0、revision counters 1，一场一行且非法 owner 由数据库拒绝。完整 review 对模型/migration 无 finding，但发现既有 mode resolver 的 event allowlist fail-open P2；已按新增 RED 改为只有显式布尔 `True` 放行，同一 reviewer 限定复审确认唯一 P2 `CLOSED`。latest-main 上 SQLite 专项、相邻赛事和历史 chunk/receipt/import primitive 回归 `49/49`，Django check 与 migration drift 检查通过；尚未实现 revision pointer、owner transfer/CAS 或 importer 接入。
- reviewer 后续建议指出 `PositiveBigIntegerField` 仍允许显式 revision counter 0；已取得两个 subtest 的真实 RED，并在模型与未发布 `0033` 增加 racecard/result counter `>=1` 数据库约束。latest-main 组合回归现为 `50/50`，check/migration drift 继续通过，等待同一 reviewer 限定复审。
- 后续离线切片已完成 `0034` 至 `0038`：显式 LiveTracking、source/participant identity、append-only observation/revision/item/evidence、ProjectionControl 四个 revision pointer、共享 HostBudget；同时实现 owner transfer、独立 racecard/result revision allocator、全联网模式 source permission resolver、轮询窗口、短事务 claim、host reservation 和返回 checkpoint 的 owner/claim 双 CAS。reviewer 发现过期 claim 仍可提交 checkpoint 的 P1 后，已分别用真实 RED 覆盖过期 lease 与缺失 expiry：前者返回 `claim_expired`，后者返回 `claim_missing_expiry`，均零 mutation。修复后 latest-main 组合回归 `105/105`；PostgreSQL 并发验证仍待执行。
- 新一批离线控制面已按逐行为 RED -> GREEN 完成：batch due-selector、host outcome/circuit、默认关闭的每分钟 Celery selector、`poll_race_live_event_task -> race_live` 独立 route、The Racing API Free 合成 fixture contract 和 append-only observation recorder。poll task 当前明确返回 `runner_not_configured`，不会访问 DB/HTTP。reviewer 发现损坏 claim lease 可被回收、旧 host outcome 可覆盖新 circuit 后，已补真实 RED；现改为损坏 lease fail closed，并以 reservation version CAS 拒绝迟到 outcome。准实时模块 `85/85`，与 historical detail chunk/import receipt/import primitives 组合回归 `122/122`，Django check、migration drift 和 diff check 通过，等待同一 reviewer 限定复审。Compose config 因独立 worktree 无 `.env` fail closed，未读取主工作区 secret；专用 worker、真实 broker、HTTP runner、revision/pointer apply 与 PostgreSQL 并发层仍未实现。
- 独立 `race_live` worker 部署契约已按真实 RED -> GREEN 完成：普通 worker 显式只消费 `celery`，live worker 固定只消费 `race_live`，默认并发 1、prefetch 1、soft/hard time limit 45/60 秒；开发、标准生产和低成本生产 Compose 均已定义该服务，scheduler 仍默认关闭。准实时 `88/88`、与 historical detail chunk/import receipt/import primitives 组合 `125/125`，三份 Compose 配置解析通过；尚未启动真实 broker/worker，poll runner 仍为 `runner_not_configured`。
- 赛果 authority/conflict 与 observation -> revision/pointer apply 核心也已完成：supplemental 只能 provisional，official authority 必须绑定持久化且 approved 的 source identity，调用方不得提权；shadow 只更新内部 immutable revision/current pointer，切换公开时通过唯一 publication audit 单向晋级并原子重建 `RaceEventResult`。owner/claim/expiry、participant identity、replay、conflict freeze、LKG 和确认时间都在短事务门禁内。公开赛事页已区分 provisional/official/corrected/conflict/stale，且 `published_at=NULL` 的 shadow revision 不泄漏。SQLite 准实时 `103/103`、与 historical detail chunk/import receipt/import primitives 组合 `140/140`；PostgreSQL identity/apply/并发直接路径 `15/15`，`0040` 迁移往返通过。
- PostgreSQL 16 专项首次发现 nullable JOIN `FOR UPDATE` 与锁等待旧快照两层问题，现已改为只锁 control 且锁后独立读取 current revision；`skip_locked`、host reservation、同 claim 双 worker单 revision/replay 和 deferred link guards 共 `4/4`。新增 `0039` 以 deferred triggers 阻断 pointer/supersedes 跨 event、跨 kind、向前引用，并保护 revision identity；迁移正向/回退/再正向通过。临时 PG 容器仅用于本地测试，未连接生产。
- 完全离线的 TRA fixture poll runner 已端到端 GREEN：默认 disabled，只读绝对受控 root，限制 2 MiB、严格 identity/path/JSON contract，以实际文件 bytes SHA 记录 observation，执行 shadow revision 后双 CAS checkpoint；成功严格沿用有限轮询窗口并在 T+7d 后停止，失败 5 分钟重试。offline fixture 即使误设 public 也会在读取前拒绝，不得物化公开投影。准实时 `108/108`、与相邻历史组合 `145/145`；尚未连接真实 Redis broker 或 HTTP。
- 隔离真实 broker smoke 已完成：临时 PostgreSQL 16 + Redis 7 + 独立 `race_live` worker 下，selector 领取并投递 1 场，最终 `1 observation / 1 revision / success checkpoint`、claim 释放、shadow 当前结果 0；普通 `celery` queue 消息未被 live worker 消费。全部临时容器、网络、数据库、消息和 fixture 已清理；这不代表生产 broker/shadow 已启用，HTTP 仍未实现。
- Django admin 已增加 live control/tracking/source/participant/observation/revision/conflict/publication/host budget 只读观测面；所有事实与权限数据禁止直接编辑。唯一可写 action 为赛事级 kill switch，经行锁 + lock-version CAS 停用 tracking、清空 next poll/claim、递增 claim generation 使在途响应失效并写 OperationLog；真实 admin POST 已通过。manual correction 尚未开放。准实时 `113/113`、相邻历史组合 `150/150`。
- latest-main 专项与四组新增历史回归组合 `249/249`（1 skip）通过。完整 `stable` 实际运行 `1837` 项后为 `2 failures / 13 errors / 23 skipped`；在干净 `origin/main@c40a8c2b` 精确复跑同一 15 项得到完全相同结果，确认是主线日期漂移、缺未跟踪 `tmp` helper 和既有 historical runner fixture/import-path 问题，不是本专项引入。Django check、migration drift、三份 Compose config、worker 脚本语法与 diff check 通过。
- 最终 full review 的三项 finding 已按真实 RED 修复：TRA 保留 PU/F/UR/NR/DSQ/REF 客观状态；无官方名次的非完赛投影和页面显示状态而非内部顺序；生产 live worker 显式限制为默认 0.25 CPU/384M。新增 `0041` choices migration。准实时 `116/116`、latest-main 组合 `252/252`（1 skip）、SQLite 迁移至 `0041`、check/drift/Compose/diff 通过，等待同一完整-review会话限定复审。
- 设计复用现有 `RaceEvent`、runner/result 当前投影、赛事页面、Celery/Redis 和来源 parser 规范化片段；新增共享 ProjectionControl、稳定 participant、append-only racecard/result revision、六态状态机和独立 `race_live` queue/worker。历史 importer、候选、后台人工和 live apply 必须共用写入所有权仲裁，避免互相覆盖。
- The Racing API 当前官方展示 Free `£0/月`、Basic `£27.99/月`、North America add-on `£49.99/月`；Free 默认 1 req/s。官网对当日更新给出约 3 分钟、文档另述 Core 约 5 分钟且条款明确不保证，因此 plan 要求先以 Free 实测覆盖/字段/p50/p95，不先购买。
- 来源条款核对发现 Sporting Life 明确禁止 screen scraping、Racing Post 限个人非商业使用；HRN/Equibase及各地区官方页面也需要逐源许可审计。任何自动真实联网均要求对应许可门禁；未获许可的来源只可人工查漏或使用获准/合成的离线 fixture，不能以“只读 proof”绕过条款。
- 原方案与用户修正范围均已 `APPROVED`。最新主线已经把第一期 1998–2026 历史详情分母收口为 `8032 = 6534 complete + 1491 evidence gap + 7 not_due`，global verifier `errors=0`；生产 historical runner 为空、历史网络/功能开关关闭，因此“历史任务先完成”已满足，旧的 `28126 remaining` 不再作为来源 proof 前置条件。来源 proof 仍只允许只读网络且业务 DB 零写入；进入任何 shadow 前，仍须生成精确 event allowlist/ownership generation、确认无 active lease/checkpoint、绑定 source registry digest、共享 host/资源窗口和用户审核 SHA。当前继续禁止生产 live worker、tracking 初始化、业务写入、部署、采购和公开开关。

## 2026-07-15 Codex 项目工作流迁移已合并主线（无需生产镜像部署）

- Codex 原生工作流迁移已完成方案审核与代码审核，结论均为 `APPROVED`；用户在最新成功代码 review 后明确回复“确认上线”。
- 受审 feature commit 为 `55b6cebc14eef067c929b01ce3cea5515416c5ef`；PR 为 [#10](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/10)。变更已提交、推送并合并到远端 `main@96810fcc288f92b41971f4f825105732967798c2`。
- merge commit 的两个 parent 分别为原主线 `d6d6f58b...` 与受审 feature `55b6cebc...`；merge tree 与受审 feature tree 一致，实际进入 `main` 的内容未偏离审核范围。
- 发布前验证通过：fingerprint `24/24`、transition/index `10/10`、workflow contract tests `26/26`，workflow checker 与 `git diff --check` 均通过。
- 本次范围仅包括治理文档、Codex skills/agents/scripts 与历史 skill 归档；没有 Django 业务代码、runtime 配置、数据库 migration 或生产数据变化。
- 本次“上线”以仓库主线合并为验收口径：未构建或部署生产镜像，未重启、重建或迁移生产容器，也未直接修改生产。线上业务运行态不因本变更改变，因此无需生产部署动作。
- 原合并前记录中的“尚未发布”状态现已由上述 `main` 合并证据取代，不表示当前仍未发布。
- 完整发布证据与回滚口径见 `docs/changes/codex-native-workflow-migration/release_report.md`。

## 2026-07-15 batch006 本地详情冲刺进行中，生产写入暂停

- batch006 年度赛历 1061 场已全部记账：`1050 complete / 11 gap`，accounted rate `100%`、data complete rate `98.96%`。两个日本 gap 为东京大赏典需要 NAR/Oi 来源；九个美国 gap 为障碍赛、同名冲突或未举办判断，全部进入最终统一审核，不阻断其他分片。
- 日本详情已完成 `248/248`（`3704 runners / 3671 results`），美国 `241/241`（`2181 / 1885`），英国 `250/250`（`2570 / 2105`），香港 `61/61`（`660 / 645`），四地区详情均为零 parser gap。英国同名赛事先按距离筛选，香港同日赛事使用原始名与年度目录名共同匹配并按距离一对一解析；香港 61 场均有唯一官方 URL 和冠军。
- 法国详情在本地按地区内单 host 1 秒限速续跑；本检查点前 5 个分片完成 `61` 场、`530 runners / 402 results`，零跳过、零错误。重型 PDF/详情解析只在本地运行，年度源只缓存一次；剩余分片继续使用 checkpoint 跳过已完成输出。
- 多分片并发新增可选共享 host interval artifact：各 shard 保留独立请求额度，但共同文件锁保证跨容器请求启动至少间隔 1 秒；法国双 worker 实跑最近最小间隔 `1.006s`。正式 runner 显式清除此变量，避免继承宿主任意路径；当前共享限速只在共同挂载根内的本地抓取启用。
- 首次生产 France verify 在无网络、无赛事业务写入阶段触发高内存后，生产 SSH 持续在 banner exchange 超时。当前禁止在生产重跑重型解析、启动新 runner 或执行赛事 apply；只在可信主机恢复后先清理/核对旧 runner、服务镜像、数据库租约、事务、队列和 healthz，再执行轻量 verifier 与串行写入。
- 本轮 UK/HK 解析与共享 host 限速修复完成测试优先和零问题复审；请求/cache/runner 组合 `161/161`、来源/直连详情组合 `104/104`、最终完整 stable `1528/1528`（11 skip）、Python compile 和 diff check 通过。历史公开、常驻网络与常驻写入开关继续关闭。
- `main@f9e76b88` 已构建本地 AMD64 候选 `sha256:f10982238ad75f53620f42897085888870cfb827b8fea67bb60fb3baf12406c3`，tree `ec3f9fbdb60c80ea63bb09b9939d56ce3eb20c64`、source archive SHA-256 `f78dae1071c5a006527d91821cec6f424035ffc0d336a82540936aece94d831a`；镜像内 Django check、迁移无漂移和赛事专项 `104/104` 通过。该镜像未传生产、未 retag、未重启服务。
- 已生成正式详情包：日本 `248` 场 SHA-256 `936c6f9e25182c978121538c289175eb032d12bf6e01a75fb0a0d3842f762e28`、美国 `241` 场 `482fc83ebb1fd5aa28ffc25194749c13688eab6f43837cdfe5e0042b8ffd40c4`、香港 `61` 场 `c02d5d2f56c5fd04b3baf2da3fa69c3fee2d11b747d71c59f0342ed084336b31`，均 gap=0。英国 250 条 date fragment SHA-256 为 `aceaaba5a4170b0b2a6e3e21987a538b34ca7e5dd00bf2ff7a5af754b139a700`；按正式门禁须先 date apply、detail-source apply 并重导 target SHA 后再打包最终详情，不能绕过来源审批。

## 2026-07-15 batch006 年度赛历入口已部署，待生成正式分片

- `formalize-historical-batch-crawl-pipeline` 已部署生产：代码为 `main@ccfee75fdff6fab7238b19484ba0489c2848dd50`，web/worker/beat 统一运行可复现 AMD64 image `sha256:e86c2339a6e690e801df2426a5edb408cbedf4c7eddd8cfd08011ed659ef773d`，Git tree `0c8fb1d65eea121a51366584a84749c7d2e3d88f`，source archive SHA-256 `635fa8a01b5c4685c66650355938af4930d8bebc90a9ece144fd76a2f1fa0d19`。两个正式域名的 HTTP healthz 正常，Celery active/reserved 与 Redis queue 均为 0。
- 实跑 batch006 前补齐了正式年度赛历入口：tracked source catalog 展开、HTTPS/host allowlist、URL 去重、终态 partial ledger、缓存 path/size/SHA/source URL 复核、离线地区 parser、complete/gap 分母、typed recipe 与逐成员目录 checkpoint。请求与解析分 stage：crawl 仅联网不写库，verify 既不联网也不写库。
- runner 新增全局输出路径互斥与普通文件 symlink 恢复拒绝；target/source identity 禁止布尔、分数和空字符串宽松转换。全量 ledger 可服务地区×年份解析分片；共享 URL 的 target references 必须精确等于 catalog 来源 scope 的并集。
- batch006 固定身份仍为 1061 targets：manifest `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`、selection `b9a3ad6556cfd03e9a57874bec763f75ad4c45e7642751140cb063f1d0553637`、approval `a119e3bcfd3bc8940cf8b792e246e462b405c292b77f2996739b435c9185d835`。正式年度赛历按 11 个地区×届次年 scope 执行：FR `2023=120 / 2024=130`，HK `2016=35 / 2017=26`，JP `2022=88 / 2023=138 / 2024=24`，UK `2024=196 / 2025=54`，US `2024=83 / 2025=167`。
- 法国官方来源真实 smoke 已完成：2023 `120/120`、2024 `130/130`，均 `issues=0`。France Galop 平地 programme、障碍详细赛程及固定列分组汇总均可解析；汇总只补详细赛程缺失目标，同等质量时详细记录优先，避免摘要笔误覆盖逐场日期。
- 其他地区现有离线覆盖基线为：香港 `61/61`、日本 `248/250`、英国 `250/250`、美国 `241/250`。日本缺口为 2023/2024 东京大赏典的 Oi/NAR 日期来源；美国缺口集中在 NSA 障碍赛、2025 Remsen 同名冲突、Robert J. Frankel 未举办判断和 Tokyo City Cup 日期，继续记入统一 gap 审核，不中断其他 scope。
- 最新验证：完整 stable `1524/1524`（11 skip）、年度赛历/来源专项 `118/118`（1 skip）、runner `70/70`、1250-target 性能 `3/3`、OpenSpec `30/30`；Django check、迁移漂移、Python compile 和 diff 检查均通过。新增实现完成 4 轮 review，最终一轮无 actionable finding。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-main-ccfee75f-20260715_122039.dump`，`141448192` bytes，SHA-256 `898c9a4ab3a06847023d189aed830553cbe733bf4c8e92a4ed636dd8231fa55f`，`pg_restore -l` 通过；环境备份为 `.env.backup.pre-main-ccfee75f-20260715_122039`，旧镜像回滚标签为 `umanewsbot:rollback-pre-ccfee75f-20260715_122039`。
- 新镜像 runner provisioning、crawl 最小权限、apply 无公网出口及两步暂停/恢复 smoke 均通过；恢复时第一步没有重复执行，最终无 runner 容器、running run 或 live lock。生产可用磁盘 `7088280 KiB`，高于 5 GiB 门槛。batch006 正式网络抓取和赛事业务表写入均未启动，历史公开/常驻网络/常驻写入继续关闭；下一步按 11 个 scope 生成不可变 descriptor/shard/plan 后启动 crawl。

## 2026-07-15 historical runner 工具根补丁部署与强化 smoke 完成

- 最新 `main@c4087e6c1e66605feb44d3650039fab2e19567e7` 已部署到生产，web/worker/beat 统一运行 AMD64 image `sha256:5eb6471c8c1e96c90198e519c4d02f1b74316d6a13dbc93e9b63c0981ad22600`；Git tree 为 `95f7ba384c791e16b7f401dfca9adb744bbb4ed0`，source archive SHA-256 为 `5051285c4bc8b5daa1355eec5be433f95d7193e8302126e3bfb359309672aec7`。旧生产镜像保留为 `umanewsbot:rollback-pre-c4087e6c-20260715-0610`。
- 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-main-c4087e6c-20260715_060549.dump`，`141446379` bytes，SHA-256 `60331b0840a98e00370f2a5c10724d2e0e9ee370724ac572be8b0cd54781e341`，`pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.pre-main-c4087e6c-20260715_060549`。
- historical runner provisioning 已幂等通过。新镜像 crawl smoke 证明 control role 无赛事业务表写权限，apply 隔离容器可连接 PostgreSQL 但无公网出口；40 秒 step 在暂停请求后完整结束并进入 `paused`，恢复后未重复第一步且完成第二步。生产 artifact 子目录伪工具根 `/app/historical-runtime/batch-006` 被 `production runner must use the immutable image tool root` 拒绝，且拒绝发生在创建 `HistoricalBatchRun` 之前，残留 run 为 0。
- 收口时 `manage_historical_batch_runner preflight` 为 `migration_safe`，无 runner 容器、active historical run、TranslationRun started、NewsArticle translating、Celery active/reserved 或 Redis queue；web healthy、worker consumer 取消、beat 保持 `Created`。历史常驻 enabled/network 均为 false，多地区归属仍为 off，历史 published 为 0，生产可用磁盘 `7856596 KiB`（约 7.49 GiB），高于 5 GiB 门槛。
- batch006 selection 仍为 1061 场、五地区 `250/61/250/250/250`，正式网络抓取尚未启动。下一步是生成绑定 selection/manifest/image/tool SHA 的不可变审批与 runner plan，再按每个 crawl run 最多 250 次请求分片执行；不得复用 batch005 的 `tmp/` 临时脚本。

## 2026-07-15 7 月 13 日起新闻质量修复、全量重跑与生产回归完成

- “正文边界与博彩噪声”“实体识别与马名保护”“日文翻译与赛马固定格式”三类问题均已完成 OpenSpec、测试、实现、复审、部署和线上回归。最终代码 revision 为 `bdc0eeff78e111d7fa8a697cbb3557888f864fb8`，生产 web/worker/beat 统一运行 image `sha256:c975a4faf979a1f78cdb203b810d4f5726aca114175007fc01c176044f13841c`。
- 北京时间 2026-07-13 起冻结清单共 `357` 篇，其中 `343` 篇可处理、`14` 篇重复稿；可处理稿最终 `218 published / 105 pending_review / 20 ignored`。冻结清单 `343/343` 已有成功处理结论，剩余 0。用户点名的 19 篇全部为 translated + published，生产详情页均返回 HTTP 200。
- Sponichi 来源级修复覆盖 `81` 篇：`79` 篇赛马稿完成清洗、重译、实体与门禁重建，`2` 篇 BOATRACE 非赛马稿 `8264/8274` 明确 ignored；79 篇最终为 `47 published / 22 pending_review / 10 ignored`。本轮新发布 47 篇关闭 QQ 自动交付，新增 QQ delivery 为 0。
- 最终验收脚本覆盖全部 357 篇、19 篇目标稿和随机样本 `8109/8186/8263/8368/8451`，`issue_count=0`；浏览器复核目标 `8086/8212/8304/8317` 及上述 5 篇随机稿，未发现框架噪声、博彩噪声、内部占位符或错误公开内容。
- 最终源码完整 `stable 1423/1423` 通过（环境专项跳过 7），跨新闻边界、实体、日文、多地区归属和历史 runner 的组合测试 `272/272` 通过（跳过 1）；Django check、迁移漂移和 OpenSpec 全量校验均通过。未知马名重复占位继续 fail closed，重试提示只允许用“该马/其”修复省略主语，不降低发布门禁。
- 最新可恢复数据库备份为 `/opt/umanewsbot/backups/db/post-news-final-pre-unified-bdc0eeff-20260715_033227.dump`，`140310729` bytes，SHA-256 `3e93fd9dba4fb80d3b415a2f97fce1d02337054d6afeb14a725b859cf67a5a74`，`pg_restore -l` 通过。最终 Redis/Celery 队列、active、reserved、TranslationRun started、NewsArticle translating、历史 running/applying、idle-in-transaction 均为 0，`/healthz/` 正常。
- 历史常驻网络与写入开关仍为 false，多地区归属 mode 仍为 off。清理未引用镜像层后生产可用磁盘约 `3.0 GiB`，仍低于 historical runner 的 `5 GiB` 硬门槛，因此新闻任务已完成但 batch006 继续 no-go，等待独立磁盘治理。

## 2026-07-14 多地区归属 V3 首轮生产审计人工复核未通过

- 已用候选镜像对生产最近 72 小时执行新的 `all_articles` 只读审计：共 `596` 篇、全部范围完整，`27` 条主地区变化、`5` 条 `needs_review`、`0` 条锁定/缺失/漂移；端到端约 `29.36s`，不再重复执行发布门禁。159 条单审 Gold 经保守对账后有效 `156` 条，主地区准确率 `96.15%`、五运营地区相关 precision `100%`、recall `52%`，机器报告为 `qualified=true`。
- 人工逐条检查全部主地区变化和 `needs_review` 后，仍发现 7 类不可接受错标：普通英文单词马名压过美国赛事、法国赛果被冠军马来源压到英国、正文首段爱尔兰赛场被外籍马名压过、日本当前成就被未来凯旋门梦想改成法国、英国 Jockey Club 机构新闻被嵌套赛事词改成其他，以及英国赛场标题被正文中的法国历史背景压过。因此首轮结论明确为 no-go，生产 `MULTIREGION_ATTRIBUTION_MODE=off`、相关地区查询关闭，Shadow 尚未开始计时。
- 修正规则采用 precision 优先：ASCII 单词实体不再单独夺取主地区；明确赛事/赛场优先于参赛马来源；正文首段只有唯一且非歧义赛事证据时才补足标题；机构全名可屏蔽其内部完整词边界的伪赛事命中；日本稿的当前成就加“未来梦想”保持日本主地区、海外目标只作相关地区。7 个真实反例已固化为回归测试。
- 修复后专项 `117` 项通过（1 项 SQLite 环境跳过），完整 `stable 1404` 项通过（7 项环境专项跳过），真实 PostgreSQL 16 的 250 篇性能契约测试体约 `0.266s`；Django check、迁移无漂移、OpenSpec strict/all `29/29` 通过。下一门禁是提交并构建第二候选，再重跑同一 72 小时范围并人工检查全部变化；未通过前不得进入 Shadow。

## 2026-07-14 多地区归属 V3 审计性能与 Gold 漂移修复待部署

- 生产首次 72 小时 `all_articles` dry-run 已持久化 `597` 篇候选，但旧命令在归属推断后又逐篇执行发布门禁，运行超过 30 分钟后被终止，stdout 报告为空；run `#1` 与 manifest 仍在数据库。现已将全量归属审计和发布门禁复核拆开，`all_articles` 默认只生成归属报告，默认门禁补跑范围仍保持原行为。
- 新增从持久 run 直接导出审核报告的命令，不重复执行归属推断；支持原子写入新 JSON 文件并拒绝覆盖既有证据。文章缺失或指纹漂移会进入必审清单，漂移文章不再使用旧归属结果校验新正文；candidate fingerprint 或 manifest 漂移时拒绝导出/commit。
- 159 条单审 Gold 在当前生产正文上有 `21` 条输入 SHA 漂移。对照用户原审核快照后，`18` 条满足来源 URL、标题、正文语义/长度和当前推断结论全部稳定，可保守刷新 SHA；`8230` 标题变化、`8088` 正文异常缩短、`7898` 当前推断与人工相关地区结论不同，继续阻断。新增命令只输出对账工件，不修改数据库，重复身份或既有输出目录一律 fail closed。
- 相关地区 precision/recall 现在只计算日本、中国香港、英国、法国、美国五个实际运营频道；`other` 继续保留为审计证据，但不会因系统没有第六个频道而制造假阳性。低置信度主地区变化若与人工 Gold 主地区一致，不再误计为“无依据变化”。
- France Galop 英文页面真实日期形如 `Sunday, July 12, 2026 - 19:04`；旧 parser 缺少星期前缀格式，导致新稿被标记为时间不可信。适配器已补充长/短星期格式，来源 probe 同时输出 `published_at_verified` 与证据，部署后须以真实页面确认纠正。
- 专项 `109` 项通过（另 1 项 SQLite 环境跳过）；完整 `stable 1396` 项通过（7 项环境专项跳过）；一次性 PostgreSQL 16 上 250 篇性能契约通过，测试体 `0.219s`，满足 SQL/30 秒/256 MiB 三项门槛；OpenSpec strict/all `29/29` 通过。当前分支尚未提交或部署，生产归属 mode 与相关地区查询仍保持关闭，Shadow 尚未开始计时。

## 2026-07-14 historical runner 生产上线、batch006 selection 与资源门禁补丁

- 独立 historical runner 第一版已完成生产部署：web/worker/beat 统一运行 image `sha256:33055eb824e4166470d692206404bebbff4057df44647bd2b3029adb21c25385`、revision `8741de98c59430c040afa1ce1737e948ba14eac3`，迁移 `stable.0031_historical_batch_runner` 已应用。写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-main-8741de98-20260714_185105.dump`，`137354931` bytes，SHA-256 `f5126ea6f69dbfbc11dc40f0c85cf1dbf05a6e2c7c678e2ccf123ea46b10073e`，`pg_restore -l` 通过。
- 生产 provisioning 已创建 internal DB/egress 两张 runner 网络、最小权限 `historical_runner_control` 角色和 0600 secret 目录。`runner-smoke-20260714-1920` 已证明 crawl 业务表写入被 PostgreSQL 拒绝、apply 无公网出口、双锁冲突、40 秒 step 心跳、暂停/恢复不重复、checkpoint SHA、迁移 preflight 和普通 `--no-deps` web 更新不干扰 DB/Redis/runner 网络；smoke 容器与一次性 secret 已清理。
- batch006 selection 已在生产正式总账上生成于 `/opt/umanewsbot/runtime/historical_race_batches/2016-2025-batch-006-20260714`：共 `1061` 场，法国 `250`、香港 `61`、日本 `250`、英国 `250`、美国 `250`；与 batch002、有效 batch003、batch004、batch005 共 `1000` 个旧 target 交集为 0，香港已抓空并退出后续地区进度比较。manifest SHA-256 为 `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`，正式总账 SHA-256 为 `ac61298f242b2c649c403eae4741771a43cdb027befef20bc75e18fe34bcbad7`。
- 正式网络抓取尚未启动。生产 smoke 后发现直接 `python_tool` 子进程未继承编排层的请求预算、source-cache 上限和磁盘底线；生产 artifact 文件系统当时仅余约 `2.8 GiB`，低于批准的 `5 GiB`。本线程在任何 batch006 网络请求前主动停止，未产生真实请求账本、source cache 或赛事写入。
- 现已在同一 OpenSpec change 中补充资源门禁：宿主脚本与 Django 服务双重拒绝请求预算超出 `1..250`、cache 超出 `1..2 GiB`、磁盘底线低于 `5 GiB`；crawl 父进程固定 1 秒请求间隔，并把共享请求账本/cache manifest 路径绑定到当前 artifact。嵌套 AdapterRunner 保留父级路径，数值只允许收紧；请求账本和 cache manifest 的存在状态、大小与 SHA 进入顶层 checkpoint，首步前保存基线且任何失败收尾刷新身份，暂停或失败期间创建、删除、修改会 blocked；固定生产工具根只允许显式赛事工具，术语等无关联网脚本即使 SHA 匹配也会拒绝。新增用例均先证明旧实现放行。第七轮复审无 actionable finding，runner `64/64`、historical 组合 `200/200`；最终合入最新多地区归属主线后交叉专项 `208/208`（跳过 1）、完整 `stable 1417/1417` 通过（跳过 7）。完成生产磁盘治理、候选部署与强化 smoke 前，batch006 继续保持未启动，历史常驻开关与公开开关保持关闭。
- 最终组合提交 `84217c56a3c483d9ff08029729f16c11bd1f42ad` 的 Git tree 为 `61341c7e3256ec417d243a809254afd91acab6b2`，source archive SHA-256 为 `aee41ac51b5347d5a1c146074079fed49e1b23dc08518ddeef36405fe6d406af`。两个独立源码上下文的本地 AMD64 构建得到相同 image ID `sha256:2e8bd05f5c138a8dfd5d5012c5ecfc811422fef2ec3ae5cbe4ed2ed45b28b31e`，正式候选 tag 为 `umanewsbot:main-84217c56-amd64-20260714-2220`；镜像内 Django check、migration drift 和 runtime 专项 `239/239` 通过（跳过 1）。过渡候选 `82fa4a3f/sha256:01397d15...` 缺少最新归属反例修复，`sha256:119f59e3...` 的 revision 标签不是有效 Git 对象，两者均明确不得部署。镜像按设计不复制生产 Compose 静态文件，该契约测试只在完整源码树执行。当前仅待生产磁盘治理、窗口交接、候选部署和强化 smoke。

## 2026-07-14 batch006 扩容与独立 historical runner 本地实现

- OpenSpec change `scale-and-isolate-historical-race-batches` 已完成完整提案、两轮工程评审和测试优先实现。batch006 起标准单地区上限为 250；显式 1-249 仍合法，旧批次可继续显式传 50。selection、writer、validator、summary、manifest 和命令 JSON 使用同一 `approved_region_limit`，100 场地区领先与不可变排除 snapshot 语义不变。
- 新增 `HistoricalBatchRun`、`HistoricalBatchLock`、`HistoricalBatchRunEvent` 及迁移 `0031_historical_batch_runner`。runner 同时持有 PostgreSQL 租约和 artifact `fcntl` 文件锁，默认 30 秒心跳、180 秒租约；不同 owner 即使租约过期也不能普通启动，必须满足容器不存在、无历史数据库连接、checkpoint 一致并记录操作者/原因后才可接管。
- runner plan 只接受结构化 argv、批准命令和镜像内工具 SHA；禁止 shell。checkpoint 同时绑定 run、phase、固定镜像、plan、输入和输出 SHA，使用 `fsync + rename` 写文件后更新数据库；分叉、丢失文件或未确认的 apply step 均转 blocked。owner token 只从 artifact 外的 0600 文件读取，数据库和日志仅保留哈希或前缀。
- 原生 Docker runner 与普通 Compose project 分离：crawl 使用 egress + control-role DB 网络且不能写业务表；apply 只连 internal DB 网络且不能访问公网。容器强制 2 CPU、2 GiB、256 PID、只读根文件系统、drop all capabilities、日志轮转和 `/app/historical-runtime` 挂载，不覆盖镜像 `/app/runtime/tools`。
- 普通 deploy/rollback 已改为 preflight 后仅以 `--no-deps` 更新 web/worker/beat/nginx，不再 pull/start/recreate DB、Redis、runner 或 networks；首次 runner 建表必须显式使用 host-only initial-install 门禁，基础设施 bootstrap 另设独立确认脚本。
- 本地 runner 聚焦测试 52 项、runner+历史批次组合 118 项、加历史网络日志组合 122 项；合并最新主线后的交叉组合 194 项通过（跳过 1），完整 `stable` 1386 项通过（跳过 7 项环境专项）。真实 PostgreSQL 6 项并发/trigger 测试、Django check、migration drift、OpenSpec strict/all 和 shell/diff 校验通过。隔离 Docker smoke 已证明 20 连接唯一 owner、40 秒 step 心跳、暂停/恢复不重复、crawl 业务写入失败、apply 公网连接失败、2 CPU/2 GiB/256 PID 与日志轮转生效；provisioning 二次执行保持幂等。
- 五轮代码 review 已闭环：前四轮共修复无界子进程输出、失败诊断缺失、任意 checkpoint 路径、文件锁失败遗留 running 租约、runner 删除 RaceEvent、crawl prepare 误写业务 `TaskExecutionLog`、stale takeover 未在宿主核验旧容器七项问题；第五轮没有 actionable finding。进程流先进入容器 256 MiB `/tmp` tmpfs，结束后脱敏写 artifact；runner prepare 改由 append-only run event 审计；接管必须由宿主脚本实际确认旧容器不存在，并以只读挂载核对固定 `runner-state.json`。提交/镜像/生产迁移与普通部署不干扰演练尚未完成，因此 batch006 尚未生成，生产历史公开及常驻网络/写入开关继续关闭。

## 2026-07-14 2016-2025 标准批次五号 250 场正式导入

- batch005 五地区各 50 场、共 250 场已完成日期、详情来源、出马表和赛果正式导入；日期 artifact manifest SHA-256 为 `0bedb2ad10d71bc3c22f11b4c42b5ee70708a50c9359b6f661739baff242c861`，详情来源 manifest SHA-256 为 `c629b5f7e6485f81b7a0a5bcc7252947eddef1a85674d124c9853828a60fcaf7`，最终详情候选 SHA-256 为 `269c65e646b11be0a1edef70c8c088e5b4b9a2b0a69527ca0efc6242cb84d6e3`。
- 日期、详情来源和最终详情三个写阶段均为 250/250；最终逐 target 验收 `error_count=0`。本批新增法国 `414 runners / 327 results`、香港 `482 / 469`、日本 `714 / 710`、英国 `489 / 433`、美国 `484 / 425`，合计 `2583 runners / 2364 results`。
- 三个写入阶段均有独立 PostgreSQL custom-format 备份并通过 `pg_restore -l`：日期写前 `pre-batch005-date-20260714_052929.dump`，SHA-256 `34ca0038ff8795929384b287ea34a7615c2a057b1d49ab10d1eaf6a161c57d2f`；详情来源写前 `pre-batch005-detail-source-20260714_055621.dump`，SHA-256 `0fbf2eb9915ed9e7f52aca515353135527772ea2c4b981cb20241c2d474999b3`；最终详情写前 `pre-batch005-final-20260714_055856.dump`，SHA-256 `82908208d5a32f751c1b7c258c54e3ac66993798d27b66ff6d1405393a10ffa9`。
- 写后生产总账为 `1291 imported / 29626 pending`，共 `13507 runners / 12167 results`；1291 个历史赛事全部保持 draft，published 为 0。写入窗口结束后 worker consumer 与 beat 已恢复，常驻历史写入和网络开关继续为 false。
- batch006 不在旧的每地区 50 场规则下直接启动。按已批准后续要求，必须先完成“每地区最多 250 场”和独立 historical batch runner 的 OpenSpec、工程评审、测试优先实现、零问题代码复审、部署与验收；公开历史赛事开关继续关闭。
## 2026-07-14 多地区归属 V3 PostgreSQL 性能达标并调整单审资格口径

- 本地独立 worktree 使用临时 PostgreSQL 16 和当前真实校准快照完成 250 篇性能验收：250 篇文章、17,474 条有效地区术语、21,240 条 alias、38,806 个索引候选、17 个实际来源。首次真实基准暴露每篇文章懒加载一次 `NewsSource` 的 N+1，五轮均为 `254 SQL`；已改为 `AttributionBatchContext` 一次预加载批次来源，并让性能测试中的 250 篇文章绑定真实来源以防回归。
- 修复后五个独立应用进程的基准均为 `5 SQL`，耗时依次为 `1.657 / 1.764 / 1.764 / 2.135 / 1.674` 秒，RSS 增量约 `49 MiB`，满足 `<=30 SQL / <=30 秒 / <=256 MiB` 门槛。性能问题不再构成当前 no-go。
- 产品口径调整为：单人审核来源必须显式保留，但单审身份本身不再自动 no-go；首发覆盖门槛为有效样本至少 150 条、五个运营地区各至少 10 条、跨地区至少 20 条。满足覆盖及全部质量/性能门槛后只获得进入生产 shadow 的资格，只有 shadow 至少观察 24 小时且全部主地区变化和 `needs_review` 完成人工复核后，才可对新文章 enforce。
- Gold Set 不以首次达标封版；新增来源、规则版本、shadow 误判和运营争议案例必须持续追加到后续版本。相关地区采用“高 precision、允许低 recall”首发策略：precision 硬门槛保持 `>=95%`，recall 从 `>=90%` 调整为 `>=50%`。当前 159 条单审 Gold Set 的最少运营地区样本为法国 11 条、跨地区 24 条，主地区准确率 `98.11%`、相关地区 precision `100%`、recall `54.84%`、过度扩散 `0%`，覆盖与质量门槛均通过，可进入 shadow。
- 线上 recall 下降代表漏标，只告警并阻止继续扩大灰度，不单独触发自动关闭；precision 低于 95%、明显错标或过度扩散超过 1% 才要求回退。生产归属和相关地区查询继续保持关闭，本轮未连接生产数据库、未部署、未修改生产配置。
- Gold 生成器与评估器现统一读取 `MULTIREGION_ATTRIBUTION_GOLD_MIN_TOTAL/PER_REGION/CROSS_REGION`，避免自定义门槛时生成结果与资格报告不一致。V3 已合并 `origin/main@9d6dec34` 的新闻实体、日文翻译和内容边界修复；组合专项 `205` 项、完整 `stable` `1321 passed / 1 skipped`。合并后 159 条 Gold 指标完全不变，仍为 `qualified=true / no_go_reasons=[]`；Django check、迁移无漂移、Python 编译、两个生产 Compose、OpenSpec strict/all `28/28` 和 `git diff --check` 均通过。
- 上线前复核发现旧 `reprocess_multiregion_attribution_gates` 只扫描被英文术语门禁卡住的 `manual_review_required` 文章，不能满足“最近 72 小时全部主地区变化与全部 `needs_review`”的生产验收。现新增显式 `--scope all_articles`：覆盖近期全部有效文章并包含已发布稿，排除 duplicate/rejected/withdrawn/archived/ignored；不传 scope 时仍保持原门禁补跑语义。全量模式默认不截断，显式 `--limit` 时报告 `scope_complete=false`，不得作为 go/no-go 依据。
- 全量报告固定列出全部主地区变化、全部 `needs_review`、全部 `locked_skip`，并从其余文章按当前主地区为五个运营地区各做内容指纹确定性抽样；完整清单写入持久 run selectors，重复运行同一快照可复核。人工锁定文章在报告和 manifest 中均保留原主/相关地区，同时展示算法 proposed 结果。`scope/scope_complete/commit_policy` 已进入 manifest 绑定契约，截断 run 禁止提交，全量 commit 只写归属。最终定向 `41/41`、完整 `stable 1327 passed / 1 skipped`、Django/迁移/编译、两个 Compose 和 OpenSpec `28/28` 均通过；159 条 Gold 指标不变且 `qualified=true`。生产仍为旧镜像、mode=off、相关地区查询关闭，任务 `9.3` 尚未执行。
- 修复已提交并推送远端 main `7f0827ad941452524062d478940c85bdfddf4a59`，tree `173602cd408b970b5dd9160eee1e1aba1768ce44`，source archive SHA-256 `f0217003f9c2f614fb7f0576ff00c3086b508c70b1c213614d2470e6df08179a`。服务器独立上下文 `/opt/umanewsbot-builds/main-7f0827ad-20260714-1707` 的聚合 SHA-256 为 `746271a0d97235ac800f6b65cd26a2e1c894fc75148e233cb8efb611e7899641`；AMD64 候选 `umanewsbot:main-7f0827ad-amd64-20260714-1707` 两次构建 image ID 均为 `sha256:6ad16e368d7934777a689e537c70618a6321c3466d02f304116e2f61ae2af9a1`，镜像内 41 项归属/门禁专项、Django check 和迁移漂移通过。
- 候选尚未切换。`2026-07-14 17:12 CST` 生产仍为旧 image `sha256:d3f602de...d6d791` / revision `873845da`，`news-translate-20260713-r3` 正在按 186 篇清单执行受控翻译重试，观测时完成 7 篇，worker/beat 已停。该任务会修改 72 小时文章正文和指纹，因此本会话未 retag prod、未重启、未生成生产归属 run、未改开关；待 one-off 自然退出并确认运行账本/队列为空后，才可备份、切换并执行任务 `9.3`。

## 2026-07-14 生产 DB/Redis 意外重建事故已恢复

- 北京时间 `01:22`，历史任务线程为只读查看命令帮助误用了 `docker compose run --rm -T web`，Compose 意外重建 `umanewsbot-db-1` 与 `umanewsbot-redis-1`。PostgreSQL 日志确认数据库在 `01:22:26` 干净关闭、`01:22:28` 从原数据目录启动，没有重新初始化或恢复错误；`web / worker / beat` 当时没有被重建，生产应用镜像始终为 `sha256:87c435cfc50344d0ca94f46e44d4bea97ab11361f88f7c708b6457331aee78ec`。
- 重建瞬间中断了 1 条 netkeiba 抓取和 1 条文章自动化链路，并使 Redis 中尚未消费的来源任务丢失；后续自然窗口按最大回看机制重新调度。事故任务最终明确记为 `CrawlJob#17084 failed`，`TaskExecutionLog#108765/#108772/#108773/#108803 failed`，旧 `17:15` 生产窗口统一收口为 `coalesced_to_latest_crawl_window`，不再伪装为运行中。
- 恢复过程中暴露 `stable_newsarticle_public_slug_46694cb6` 和 `uq_article_source_article_id` 索引异常，并确认故障期间产生 4 组重复 identity、共 5 条冗余文章。权威旧记录保留为 `6809 / 8089 / 8101 / 7514`，重复记录 `8324 / 8328 / 8325 / 8327 / 8329` 的快照、翻译运行、自动化日志和窗口决策已迁回权威行后删除；每次合并均写入 `OperationLog(action_type=incident_duplicate_merge)`。
- 停止 beat、停止 worker 继续取新任务并排空 active 后，对 `stable_newsarticle` 全部 17 个索引执行 `REINDEX TABLE CONCURRENTLY`，随后执行 `VACUUM (ANALYZE, VERBOSE)`。最终为 `8312` 行、重复 identity `0`、无效/未就绪索引 `0/17`、dead row `0`；索引修复后文章 `8330` 正常自动发布，未再出现索引页或重复键错误。
- 最新停写备份为 `/opt/umanewsbot/backups/db/pre-newsarticle-dedup-reindex-20260714_020918.sql.gz`，大小 `156642923` bytes，`gzip -t` 通过，SHA-256 `f37ff4835fe13d4c2a016beac433940ef995677e690711dc68ca59f42b149a9e`。较早的索引修复前备份为 `pre-public-slug-reindex-20260714_013400.sql.gz`，大小 `156320990` bytes，SHA-256 `de864deeb53ce96e1b5509b6baffdddac1779aef711954b0783aa9a4c0a6e861`。
- `02:15` 自然窗口中 17 个生产来源全部 `succeeded`，五地区发布和 QQ 窗口全部 `succeeded`，美国发布 1 篇；公网域名、`www` 和公网 IP `/healthz/` 均返回 200。worker/beat 已恢复，DB/Redis/web 健康，历史任务继续冻结到本次协调线程明确解除。

## 2026-07-13 多地区归属单审校准集完成（历史评估已由 V3 复评取代）

- 用户完成 `multiregion_gold_set_review_20260713.xlsx` 的审稿人 1 标注；因没有第二位审核人，且法国/美国等高量地区只做部分抽样，本轮按显式 `provisional_single_review` 口径固化，不冒充正式双审 Gold Set。规则为：有期望主地区的行进入校准标签，明确 `exclude` 单独保留，主/相关地区均未选择的行视为未选中并忽略。
- 250 篇候选最终得到 `159` 条有效单审标签、`1` 条明确排除和 `90` 条未选中忽略。期望主地区为日本 `46`、中国香港 `50`、英国 `30`、法国 `11`、美国 `17`、其他 `5`；带期望相关地区的标签 `24` 条。`united_state` 已规范为 `united_states`，“所有地区”已展开为五个支持地区，原始填写值均保存在规范化审计中。
- 当日实现曾把 `provisional_single_review` 固定作为 no-go；该限制已由 2026-07-14 产品决策取代。现在单审来源继续保留且不得伪造第二审核人，但达到 150 总量、五地区各 10、跨地区 20 和全部质量/性能门槛后可进入 shadow；多人审核出现冲突时仍必须裁决。
- 对生产数据库执行纯只读评估，159 篇均存在，其中 `5` 篇输入 SHA 已漂移，实际分母 `154`。当前规则主地区准确率 `81.17%`；日本 `79.07%`、中国香港 `88.00%`、英国 `82.76%`、法国 `90.91%`、美国 `81.25%`、其他 `0%`。相关地区 precision `6.90%`、recall `6.67%`，主地区有效错配 `29` 条。主要误差是实体地区压过中心赛事，以及相关地区漏判/误扩散。
- 批处理还暴露正则重复编译问题：原始 159 篇运行超过 10 分钟后中止；为术语匹配正则增加有界缓存后约 `97` 秒完成，仍高于 250 篇 `30` 秒目标，因此性能同样 no-go。评估结束后生产无残留 one-off，未写数据库、未重启容器、未修改开关。
- 最终审核与逐篇结果工作簿为 `outputs/20260713-multiregion-gold-final/multiregion_gold_set_final_20260713.xlsx`，SHA-256 `e34726d5c8130dfd716dc3bbe10f67db3dc167f55ae36ae37a7843a99e048fdb`。校准标签 SHA-256 为 `bd94b3a40642328b93fa29f3e8aa9f1680161bb2ee3455d567d15ea377eb3681`。生产 `MULTIREGION_ATTRIBUTION_MODE` 和相关地区查询继续保持关闭。

## 2026-07-13 多地区归属 Gold Set 双人标注已启动

- OpenSpec change `fix-france-news-freshness-and-multiregion-attribution` 的任务 `5.1` 已进入真实数据阶段。新增只读命令 `prepare_multiregion_attribution_gold_review` 生成不可变快照、盲标 CSV、中文口径说明和文件哈希清单；新增 `finalize_multiregion_attribution_gold_review` 校验审核来源、输入漂移和多人冲突。该日原始双审及 `250/40/50` 口径已由 2026-07-14 的单审可用及 `150/10/20` 首发门槛取代。
- 第一版真实审核包为 `multiregion-gold-v1-20260713`，本地路径 `runtime/multiregion_gold_review/gold-v1-20260713/`，生产只读副本路径 `/opt/umanewsbot/runtime/multiregion_gold_review/gold-v1-20260713/`。manifest SHA-256 为 `1836a9d896ca5b6e09da6da7ed07a2fb3f66f0a02f387010fe4b56475bf5c1ea`。
- 审核包共 `250` 篇，按当前文章地区分层为日本/中国香港/英国/法国/美国各 `50` 篇，覆盖全部 `17` 个生产新闻来源；`250` 个 URL 和 `250` 个输入 SHA 均唯一。时间范围为日本 `2026-05-25–2026-07-13`、中国香港 `2026-06-23–2026-07-13`、英国/法国 `2026-06-26–2026-07-13`、美国 `2026-06-24–2026-07-12`。
- 抽样使用与待测归属算法独立的宽地区关键词，只用于优先纳入困难样本，不向审核表泄露算法答案；本包有 `139` 篇疑似跨地区候选。审核包包含第三方正文，已由 `.gitignore` 排除，最终仓库只保存 article ID、source URL、输入 SHA、人工期望地区、审核角色和理由。
- 该日尚未完成两次独立人工标注和冲突裁决，因此 OpenSpec `5.1` 当时未勾选；该状态已由 2026-07-14 的单审可用决策和 159 条 V3 复评取代。生产 `MULTIREGION_ATTRIBUTION_MODE=off`、相关地区查询与翻译自动重试继续关闭；生产 dry-run 与 Shadow 仍待执行。
- 本分支已在完成实现后快进合入 `origin/main@693db30e`。生产在本任务期间由并行历史任务切换到 `umanewsbot:main-df2732c3-amd64-20260713-1321`，image ID `sha256:27d5d51cbe2ae6d23cb99dc758da01addc2d5935504a950bbb8a2685bce2bf13`；本任务只读复核确认常驻容器健康、无 one-off 容器、归属相关安全开关仍关闭。
- 最新主线组合回归为 `1139 passed / 1 skipped`；Django check、迁移漂移、OpenSpec change strict、全仓 25 项 OpenSpec strict 和 `git diff --check` 均通过。macOS 全测须设置 `TMPDIR=/private/tmp`，否则未改动的历史 artifact 测试会因 `/var` 与 `/private/var` 别名产生 16 个伪错误。
## 2026-07-14 日文赛马翻译与固定格式已上线

- OpenSpec change `standardize-japanese-racing-translation` 已按提案、Full 工程评审、完整测试、apply、多轮 `/review -> 修复`、部署、生产回归和规格同步流程完成，并归档到 `openspec/changes/archive/2026-07-14-standardize-japanese-racing-translation/`。日文普通片假名词现在以非马名固定译法进入文章级实体与翻译链路；拍卖产驹、追切计时、赛后访谈和出马表骑手未定使用字段级确定性格式；未知完整马名继续保留原文。种子术语占位符按字段守恒，恢复时只消除明确的边界重复，不会把“拍卖会会场”这类合法单字相接误删。
- `社台/Shadai`、`ノーザンホースパーク/Northern Horse Park` 和 `セレクトセール` 已在生产术语库中各自保持唯一概念；目标分别为“社台”“北方马公园”“精选拍卖会”，日英别名完整。英文马名中文目标只在中文/繁中文章中反向匹配，不再把日文普通词 `出走` 识别成英文马名 `Movin Out`。
- 最终生产 revision 为 `873845dacb1cec0353ed9b9834417a1a00cc6311`，源码 archive SHA-256 为 `2c00bf5bee4e824d5bd3cb408af942b5a255dd88f30de1b24436cab289ec3e09`；web/worker/beat 均运行 AMD64 镜像 `sha256:d3f602de4459158bc372e45bb35f3730a7be21f284dfea32de5535681bd6d791`。本地完整 `stable 1295` 项通过（另 `1` 项按设计跳过），候选 PostgreSQL 的迁移/check/漂移和关联 `84` 项通过，最终 review 零问题。
- 写入前恢复点为 `.env.backup.pre-873845da-20260714_124940` 与 `backups/db/pre-873845da-20260714_124940.dump`；数据库备份 `134234023` bytes、SHA-256 `413718143809a09686ea18710a4cd8b8f9a9f7643fb6b769cee5daf23ca485a6`，已用 PostgreSQL 容器执行 `pg_restore -l` 验证。旧镜像回滚 tag 为 `umanewsbot:rollback-pre-873845da-20260714-1254`，image ID `sha256:b14844ee027a7902db2ed22c9b310e8240dd2d84f822d2785a28799271e3a1a2`。
- 目标文章 `8304/8299/8298/8291/8290/8288/8287/8283/8276/8219/8212` 均为 `published + translated`，保留原发布时间、人工字段和 QQ 次数；指定普通词残留、内部占位符和格式错误均为 `0`。`8304` 产驹、`8291` 追切、`8219` 访谈、`8212` 骑手未定及完整未知马名逐项通过。`8287` 使用已通过全部门禁的成功 run `8613`，仅确定性修复两处“类型类型”和一处“公开级级别”，并记录 `OperationLog`；后续失败 run `8622` 未覆盖公开稿。
- 随机样本 `8337/8366/8356/8307/8367` 均已发布、已翻译且无内部占位符；`8367` 的标签和 machine tags 均不含错误的“出走”。HTTP healthz、首页、后台和 11 篇详情均为 `200`；Redis queue、Celery active/reserved 为空，近 15 分钟无 fatal/traceback。候选数据库已删除，历史写入/网络开关保持 false，历史 published 为 `0`。

## 2026-07-14 新闻实体语境判定与完整马名保护已上线

- OpenSpec change `contextualize-news-entity-resolution` 已完成测试优先实现及 `18` 轮 `/review -> 修复`，最终一轮无问题。文章级解析结果统一供翻译、标签、发布校验、自动马匹关联与显式重处理消费；英文人物全名及篇内唯一姓氏回指会压制内部马名，英文普通词/高歧义词需要强马名语境，日文完整未知马名会先整体占位，不再被父马、冠名或短术语拆分。
- 最终生产 revision 为 `dc1e5ec584e47ea9d28998f76454d105836b3f0a`，源码 archive SHA-256 为 `f2eec61f6d2211a76e4456f6b9cbfc3e55a5b610829162b4a68b6039aae6ffe1`；web/worker/beat 均运行镜像 `sha256:5b06821610f0d2214cb24692e58beac4ffda731ddb84674a8855b2a1d4dbb470`。本地与候选环境最终目标测试 `51` 项、完整 `stable 1249` 项通过（另 `1` 项按设计跳过），Django check、迁移漂移、OpenSpec strict 和 diff check 均通过。
- 写入前有效恢复点为 `backups/db/pre-main-624dd5b9-20260714-071014.dump`，`133370327` bytes、SHA-256 `21cdce21f52ded3b48e7c083f2f536eb694130f71ad6a1e38e067620f817fa75`，`pg_restore -l` 通过；随机六篇重处理前另有 `pre-random-six-entity-reprocess-20260714-074604.dump`，SHA-256 `0f0876c492d80ab9d8af2bacfe3776e3de5c94642acc427523ddd25d0437cf91`。
- 目标文章 `8086/8212/8221/8283/8288/8290/8291/8309/8317/8318/8330` 已逐篇完成 dry-run、commit、重译和重新校验；`8317` 正文统一为岳品贤，`8309/8330/8318` 不再产生假马标签，`8086` 只保留真实马名多爵，指定日文完整马名不再拆分。11 篇均保持原 `published`、原发布时间和 QQ 次数，公开页全部为 `200`。
- 随机样本 `8390/8388/8386/8385/8383/8380` 在最终规则下重处理后 dry-run 无增删差异；最终 worker 自然处理的 `8393/8394` 也通过实体 dry-run 与发布校验。公网 HTTP healthz、首页、后台和目标详情均为 `200`；Celery queue/active/reserved 均为空，最近 15 分钟 web/worker/beat 无 error/traceback，历史写入/网络开关保持关闭且历史 published 为 `0`。

## 2026-07-14 国际新闻正文边界与博彩噪声修复已上线

- OpenSpec change `tighten-international-article-content-boundaries` 已完成提案、Full 工程评审、测试优先实现和多轮零问题 review。最终本地验证为正文边界目标测试 `27` 项、完整 `stable` `1198` 项通过（另 `1` 项按设计跳过），Django check、迁移漂移、OpenSpec strict 和 diff check 均通过。
- 国际来源正文现在只接受可信正文选择器；未命中时显式失败，不再回退整页。Sporting Life 会移除页面框架、社交组件、推荐区、责任博彩、博彩推广、独立跳转 URL 和 `BOOK NOW` 等 CTA，同时保留赔率及赛事标题、马主等专名中的博彩公司名称；TDN 会移除编辑注、纯跳转说明、完整赛果/活动链接、`Read Today's Paper` 和含 `click here` 的行动句。
- 历史修复命令只接受显式文章 ID、默认 dry-run，commit 后记录清理规则与 `OperationLog`；同步强制重译不会改变公开状态、原发布时间或触发 QQ。翻译完整性门禁新增非空行覆盖判断，避免“日期表完整但中文自然缩短”被误判截断，同时仍拦截尾部条目缺失。
- 最终生产 revision 为 `514af8a22aec18f01cf0193344ae3b7a45c4dbc4`，web/worker/beat 均运行镜像 `sha256:954673cc74049d4b882e492ec29b072aba01aeb1a3ae440cc85415209c8a2f8a`。源码 tree 为 `b62a80cc34b2b65c47f6dd7d541c455d04a0ef5c`，archive SHA-256 为 `507b95c9b3e3ab66b67e4813b6b4814d2e4bc3d6cb2aae6abc7ad357322ad039`，双构建 `/app` manifest SHA-256 为 `2ada2d84788d048fcfd86d589762c2b159256d1a884581ac819a614aacf92aea`。
- 最终切换前备份为 `.env.backup.pre-main-514af8a2-20260714-051127` 和 `backups/db/pre-main-514af8a2-20260714-051127.sql.gz`；数据库备份 `158552943` bytes、SHA-256 `9fc72efba29ee8d32c9709665809d259ca49e47a217c43626c99b084d99d4b0a`，`gzip -t` 通过，旧镜像回滚 tag 为 `umanewsbot:rollback-pre-514af8a2-20260714-051127`。
- 文章 `8086/8267/8316/8318` 均已按保存 HTML 离线修复并强制重译，继续保持 `published`、原 `published_to_web_at` 与 QQ delivery `0`；公开详情全部返回 `200`。生产随机抽检 `8306/8311/8326/8331/8336` 后又修复并重译存量旧解析结果，五篇保存正文与当前重解析逐字一致、解析状态均为 `ok`、噪声标记为 `0`；已发布样本 `8326` 保持原发布时间 `2026-07-13T17:47:04.152562Z` 且 QQ delivery `0`。
- 部署后 migrate 无待应用迁移，Django check、内外 `/healthz/`、首页、后台登录和目标公开页面均为 `200`，web/worker 日志无异常。beat 已恢复，Celery active/reserved 均为空；生产写入窗口随后由历史 batch005 完成使用并正常归还。

## 2026-07-14 2016-2025 标准批次四号 250 场正式导入

- batch004 五地区各 50 场、共 250 场已完成日期、直接详情来源、出马表和赛果正式导入；日期 artifact manifest 为 `30ff2c0fe14e4d6ce7d9ee7123d882d99838853e381627b552b9b0ac19dd2ea0`，详情来源 manifest 为 `cf5bfdc1cc8c6c82732d6485e1815f582a47d057010e4d1c0214ec3103fd46a8`，最终详情候选 SHA-256 为 `ddd1f8256cef0b17aabc33ea66f7a0638a2d6498c2d23342daff8835b10a5156`。
- 日期 apply、详情来源 apply 和最终详情 apply 均为 250/250。正式详情新增 `2563 runners / 2311 results`；500 个模块候选全部为 `applied`，逐场马号与名次唯一性、module 状态和 250 条导入日志一致。250 场保持 draft，published 0。
- 来源分布为 JRA 官方 50、HKJC 官方 50、NSA 官方 1、Sporting Life 50、ZEturf 50、Equibase 49。NSA `target_id=74171` 的官方 PDF 不提供马号，因而该场 8 条 runners 与 7 条 results 的 `horse_number` 为空；姓名、骑手和名次完整，作为非阻断来源格式例外进入最终统一审核。
- 226 个 target 的 `module_statuses.term_gaps` 记录了术语库暂缺中文映射；原文赛事数据已经完整导入，这些翻译缺口不改变 imported 状态，也不阻断后续批次，统一留到正式总账数据收集完成后的审核与术语补全。
- 详情来源写前流式备份 `pre-batch004-detail-source-apply-20260714_031200.sql.gz` 在进程尚未结束时曾被中途检查并报截断；进程完成后文件为 `128991200` bytes，`gzip -t` 通过，SHA-256 为 `dbe05660aaae9e1957c21b84d714c3340a81a3a59aedef4dcf5f99caae5509e5`，现为有效恢复点。最终详情写前另有更靠后的 PostgreSQL custom-format 备份 `/opt/umanewsbot/backups/db/pre-batch004-detail-import-20260714_0325.dump`，大小 `129830849` bytes，`pg_restore -l` 通过，SHA-256 为 `e50bd095bfa141ea0f05bf77fda68a508808dcddac4cbacb8fdb4ce3860e758a`。
- 写后生产累计为 `1041 imported / 29876 pending / 0 ready`，本批 250 场合计 `2563 runners / 2311 results`；全体历史 published 仍为 0。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，无 one-off，三个公网 healthz 均为 `ok`。
- batch005 生成必须等待包含 `main@614f810e` 已耗尽地区进度门禁的可复现 AMD64 镜像完成生产切换；历史线程不得自行重建或重启生产。

## 2026-07-13 2016-2025 标准批次三号 250 场正式导入

- batch003 五地区各 50 场已完成日期、带原单位距离、实际场地、详情来源、出马表和赛果正式导入，新增 `2638 runners / 2349 results`；写后累计为 `791 imported / 30126 pending / 0 ready`、`8361 runners / 7492 results`，全部 draft、published 0。
- 2025 Hampton Novices' Chase 按同届移师处理为 `2025-01-19 / Windsor / 3m53y`，3 匹出走、3 条赛果，冠军 `Jingko Blue`；Warwick 原定场次 `ABANDONED` 只保留为变更证据，不构成年度取消或缺口。
- 最终详情候选 SHA-256 为 `426af99cf541b43aa2e73e839989de40f2d2a15ab6298cda4cec4026cafe0a59`。日期、权威字段、详情来源和最终详情四个写阶段均有独立门禁与备份，逐 target 验收 error 0。

## 2026-07-14 已耗尽地区不再冻结历史标准批次

- 既有地区进度护栏会把五地区永久放在同一比较集合；当中国香港等低容量地区已经没有可选目标时，仍会以其较低 accounted 数阻止英国、美国等高容量地区继续推进，与 1998–2026 正式总账全量完成目标冲突。
- 标准批次现在只比较“本批选择后仍有未排除可选 pending due 目标”的地区。地区抓空后退出领先比较；仍未完成地区之间继续严格执行 100 个标准目标上限，101 拒绝、100 放行。
- selection snapshot 显式排除的待审目标继续保留在 `available/remaining pending`、总账分母和缺口账本中，但不把只有待审排除项的地区视为仍可抓。artifact summary 新增 `eligible_pending_by_region` 和 `progress_guard_regions`，明确记录放行依据。
- OpenSpec 增补已完成 Full 工程评审；新增回归先在旧实现上失败，修复后历史批次专项 `66` 项和完整 `stable 1171` 项通过（另 `1` 项按设计跳过），Django check、迁移漂移、OpenSpec strict、diff check 和最终代码 review 均通过。代码已合入 `main@614f810e`，尚未部署；生产历史写入/网络和公开开关不得因此开启。

## 2026-07-13 后续标准批次重复选样门禁已实现

- batch002 写后生成旧 batch003 时，4 个仍为 pending 的已交代 gap 再次进入选样：英国 Classic Handicap Chase、Dick Poole Fillies Stakes，以及美国 Brooklyn、Cougar II。该工件与 batch002 重叠 4 条，视为无效，不得审批或进入抓取。
- `build_historical_race_band_batch` 已增加可重复 `--exclude-selection-snapshot`。命令校验旧快照 schema、inventory SHA、内部 snapshot SHA、target 数量/唯一性和稳定身份，在地区 limit 前排除旧 target，并把输入原字节复制到新 artifact、以固定键写入 manifest 文件身份。
- 排除只影响本批选样：被排除 gap 继续保持 pending，仍计入 `available/remaining pending`，不计入 accounted/imported，也不修改 held/not_held/cancelled 口径。旧目标已导入导致当前 target SHA 改变时，只要 series/year/region/inventory 稳定，历史快照仍可作为排除证据。
- 42 项批次与日期发现聚焦测试、完整 `stable 1157` 项回归、Django check、迁移漂移、OpenSpec strict/all 和第二轮代码 review 均通过。batch002 真实 250 目标快照已通过新读取器；该门禁后续已经提交并用于 batch003/batch004，公开展示和常驻历史写入/网络开关保持关闭。

## 2026-07-13 2016–2025 标准批次二号 246 场正式导入

- 生产已使用可复现主线镜像 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0` 完成第二标准批次。日期 artifact manifest SHA-256 为 `9ed3b7138012b4ce1732cf1f071d13cb16678a97983ea63d94329fe84c902e68`，批准 246 场、保留 4 个显式 gap；日期 apply 246/246 成功，目标由 pending 变为 ready，并生成 246 个 finished/draft 年度赛事。
- 详情来源 artifact manifest SHA-256 为 `ae9d20aa62062e62a0bc8561e69b2cd06493b2d3eab50e175a82913d077b44d9`，来源分布为 JRA 50、Equibase 48、HKJC 50、Sporting Life 48、ZEturf 50。只读 check 246/246 通过，来源 apply 246/246 成功；来源写入后重新导出 event input 并生成最终详情候选，候选 SHA-256 为 `735ec0dacafd9c388adb678b93ab402e45f991cb0e143c89a6fe067e606fc459`，246 scopes / 0 gaps，生产 dry-run 全部通过。
- 三道写前备份均通过 `gzip -t`：日期 apply 前 `pre-band-2016-2025-batch002-date-apply-20260713_164248.sql.gz` 为 `150494499` bytes、SHA-256 `379f86de4408ff0a66dbdee200514a56a53a10404b579c49a3fb13462541b7c7`；详情来源 apply 前 `pre-band-2016-2025-batch002-detail-apply-20260713_165007.sql.gz` 为 `124141632` bytes、SHA-256 `0b0423aee6ffbe4094a71c3ff533e47538f1ccb8b3a918aa3d07863b76809540`；最终详情导入前 `pre-band-2016-2025-batch002-candidate-import-20260713_165304.sql.gz` 为 `124218014` bytes、SHA-256 `a22967b6e0574faab9ae865d908f69474234dfff862092025471cf7eff660545`。
- 正式详情导入 246/246 成功，新增日本 `730 runners / 722 results`、美国 `468 / 406`、香港 `463 / 453`、英国 `464 / 417`、法国 `424 / 328`，合计 `2549 runners / 2326 results`。写后逐场核对 candidate 数量、马号唯一性、名次唯一性、applied candidate 来源名/URL、target module 状态和 draft 可见性，error 0。
- 生产历史累计为 `541 imported / 30376 pending`、`5723 runners / 5143 results`，materialized events 为 541，published 为 0。本批 246 场仍全部 draft；4 个 gap 继续保持 pending，未把 `ABANDONED` 或 `not run` 自动改成产品总账结论。
- 常驻 `.env` 和运行中 web 均保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；web/worker/beat 镜像未变化，无遗留 one-off 容器，内外 HTTP healthz 正常，近 30 分钟日志错误扫描为空。历史前台展示继续关闭。

## 2026-07-13 2016–2025 标准批次二号详情证据门禁

- 第二标准批次 250 个目标已完成五地区详情来源发现。当前可直接进入日期工件的证据为 246 场：日本 50、美国 48、香港 50、英国 48、法国 50；246 个来源 URL 全局唯一，来源缓存逐文件大小和 SHA-256 可核验。详情解析合计日本/美国 `1198 runners / 1128 results`、香港 `463 / 453`、英国 `464 / 417`、法国 `424 / 328`。
- 4 个目标继续作为显式缺口保留：美国 Brooklyn Stakes 和 Cougar II Stakes 的 2025 届有 TOBA `not run` 证据，等待产品结论；英国 Classic Handicap Chase 和 Dick Poole Fillies Stakes 的 2025 结果页标记 `ABANDONED`，在正式取消证据修正总账前不得按 held 导入。
- 首次生产只读 artifact 构建为 `219 candidate / 31 gap`。除上述 4 个预期缺口外，15 个香港目标缺少赛季年度与实际自然年的跨年说明，12 个英国目标被 `2m4f`、`3m21/2f` 等紧凑英制距离写法误判。香港 provider 已显式写入 `actual_year` 和 `hong_kong_racing_season_spans_calendar_years`；英制解析器已按测试优先支持紧凑 mile/furlong/yard 组合和粘连分数，同时保留来源原文。
- 距离修复专项先失败后通过，完整 `stable` 回归为 `1149` 项通过、`1` 项按设计跳过；`git diff --check` 通过，最终代码复审无 actionable finding。当前尚未把本轮修复部署到生产，也未批准或提交二号批次日期 artifact；生产仍为历史 `295 imported / 30622 pending`、`3174 runners / 2817 results`、全部 draft、published 0，常驻历史写入和网络开关保持 false。

## 2026-07-13 2016–2025 标准批次二号应到与日美来源发现

- 由于 2016–2025 年代带仍有 pending 目标，按 OpenSpec 年代带门禁继续本年代，不提前跳到 2006–2015。生产总账生成第二个标准批次 250 场，五地区各 50；生成前各地区 accounted 均为 53，生成后领先差仍为 0。selection snapshot 内部 SHA-256 为 `fdd297a8c76cca529634128c11c59ea6ed4cf216b13e574a012d5fd35557629b`，manifest 文件 SHA-256 为 `b4db68f36e2ec378b7dffc9f8c8d2286d3cf4d4138499f2eb4fef86c8d3152f8`，审批文件 SHA-256 为 `b2650665588758c9e43cae3f80db30fe7c0f8287657cea468f728b9baf1fd6c2`。
- 批次审核为 250 个唯一 target、250 个唯一地区/年份/系列组合，核心身份字段无空值，同地区同年无重名；全部继承自已批准总账。年份分布为法国/日本/英国/美国各 50 场 2025，香港为 2024 年 9 场、2023 年 31 场、2022 年 10 场。
- 复用已缓存 JRA 与 TOBA 2025 年表做零网络离线发现。修复 JRA 五个障碍/赞助名称别名、TOBA 核心限定词串场和同 URL 双 target 后，得到日本 50、美国 48 个候选，共 98 个全局唯一 URL；候选 SHA-256 为 `bff176ca9b55ca11a8a5200c1f27a02e3f14e160877dac79e1092d5409f0560e`。
- TOBA 权威年表将美国 `Brooklyn Stakes`（target 74077，BAQ）和 `Cougar II Stakes`（target 74108，DMR）明确标为 `not run`。工具只输出 `source_reports_not_run` 审核证据，不自动改总账；两条由产品审核决定是否从 `held` 改为 `not_held`，其余 248 场可继续独立推进。
- 技术修复按测试优先完成，109 项历史专项与完整 `stable` 1141 项通过，1 项按设计跳过；OpenSpec strict、编译和 diff 检查通过，修复后重新 review 无剩余可修问题。历史公开展示和常驻网络/写入开关继续关闭，尚未对本批执行生产网络抓取或数据库写入。

## 2026-07-13 2016–2025 标准批次法港英 150 场正式导入

- 法国、香港、英国各 50 场的基础字段先经独立权威字段 artifact 校正。evidence manifest SHA-256 为 `d6f6e29a7243b2d709ef117a85fb315d2067b60870e6d72145dc81d0ab6a2857`，候选 SHA-256 为 `59acc224101cccf1a4b98dfc2e64173bbbf81406027b8ecd269871e643cf50ac`；生产 dry-run 精确得到 150 个 scope、164 个字段，其中距离 150、场地 8、surface 6，人工锁跳过 0。
- 字段写入前备份 `backups/db/pre-fr-hk-uk-field-corrections-20260713_134732.sql.gz` 为 `148521701` bytes，SHA-256 `30dc58d2d7f7eb099dfebf7ebf059e13f28aee13b5b0bd69b41bbe5cdd6c94ce`，`gzip -t` 通过。原子 apply 后 150 个 target SHA 全部改变，164 个值和字段 provenance 逐项一致，150 条目标日志和 1 条批次日志齐全；常驻历史写入/网络开关仍为 false。
- 旧详情候选 `38e05d7786fcfa5adf91eee19dc08d3eb86c55f8cc5a29a86bead32b6f771950` 已在生产因 `historical target changed after candidate approval` 被明确拒绝。重新导出并打包的新候选 SHA-256 为 `a8fc8fbf94c5a90e0d62be6f8727c38cbbcd14577c1894d8869d9974b33368da`，150 场、0 gap、150 个全局唯一详情 URL，正式 dry-run 全部通过。
- 详情写入前第二份备份 `backups/db/pre-fr-hk-uk-detail-import-20260713_135954.sql.gz` 为 `148554120` bytes，SHA-256 `610c540758ac0665342d219841ee91592bc36f5f0641ed2f263eec507250f4db`，`gzip -t` 通过。正式 apply 150/150 成功：法国 `449 runners / 330 results`，香港 `515 / 506`，英国 `570 / 458`；合计新增 `1534 runners / 1294 results / 300 applied candidates` 和 150 条导入日志。
- 写后验收 error 0：每场 runners/results 与候选完全一致，马号和存储名次无重复，candidate source name/URL/cache identity 均匹配批准证据，target 全部 imported、module 状态完整。生产历史累计为 `295 imported / 30622 pending`、2026 年前 `295` 场且全部 draft，历史 runners/results 为 `3174 / 2817`，published 为 0。
- 150 个详情 source cache 共 `38383091` bytes，生产逐文件大小和 SHA-256 `150/150` 通过。数据库约 `850877463` bytes；Django check、内外 healthz、容器和 web/worker/beat 日志均正常。历史公开展示继续关闭，本批未改变新闻或公开页面开关。
- 写入后的 14:00 CST 自然窗口验收通过：17 个抓取窗口、5 个发布窗口、5 个 QQ 推送窗口均 succeeded；抓取处理 470 条、产生 5 条新稿、失败 0。发布与 QQ 均为门禁解释明确的正常零产出，分别是 `hard_gate_blocked` / `no_ready_candidates` 和 `already_sent` / `no_eligible_articles`，失败文章与失败投递均为 0；随后内外 healthz 正常，web/worker/beat 近 20 分钟错误扫描为 0。

## 2026-07-13 权威字段门禁固化与可复现镜像切换

- 权威字段批次门禁源码、测试、OpenSpec 与运行文档已提交为 `df2732c3b8ae47619728c52f54a95204f5d6b574`，历史分支和远端 `main` 同步快进；提交前完整 `stable` 回归 `1136/1136` 通过，1 项按设计跳过，最终代码 review 无待修问题。
- 生产从干净 detached worktree 构建 `umanewsbot:main-df2732c3-amd64-20260713-1321`，两次构建 image ID 均为 `sha256:27d5d51cbe2ae6d23cb99dc758da01addc2d5935504a950bbb8a2685bce2bf13`；架构 `amd64`，revision `df2732c3...6b574`，Git tree `d2ce464b80ec595f82dc19a531c982429bb639af`，已提交源码归档 SHA-256 `441eb2acb5c061aae5d22671e82ddccfafb2cb08af62711b030c0031354d8d5d`。
- 切换前停止 beat 并等待 worker active/reserved 清空；外部导入、术语重处理、多地区归属 live lock 均为 0，无 one-off 容器。`.env` 备份为 `.env.backup.main-df2732c3-20260713_132757`；数据库备份 `backups/db/pre-main-df2732c3-20260713_132757.sql.gz` 为 `148455898` bytes，`gzip -t` 通过，SHA-256 `87cc176658cd2e57fa72c703bc1446e1e1930147a875d82cfccab7470d964776`。旧镜像回滚 tag 为 `pre-main-df2732c3-20260713-1327`。
- 新镜像连接生产数据库执行 migrate 无待迁移，Django check、迁移漂移和新命令 help 均通过；随后重建 `web / worker / beat`。三容器统一使用 `sha256:27d5d51c...bf13`，web healthy，`stable.0029`、64 个模型、历史新命令和静态资源正常。
- 安全状态保持不变：历史回填/网络常驻开关 false，多地区归属 mode off，相关地区查询、翻译自动重试和失败邮件 false；生产仍为 `145 imported + 150 ready`、2026 年前赛事 `295`、历史 published `0`。本轮没有执行权威字段或详情生产写入。
- 内外 `/healthz/`、五地区首页筛选、赛事页、马匹页和后台均返回 200。切换后的 `13:30` 自然窗口中 5 个到期来源全部抓取 succeeded，五地区 publish/QQ 窗口全部 succeeded，日本正常发布文章 `8238`；web/worker/beat 日志无 traceback/error/constraint 异常。

## 2026-07-13 历史源码固化与可复现生产镜像切换

- 历史赛事全部保留能力已提交并推送，分支与远端 `main` 均已快进到 `304ebdb67562e655929d263a3af98b8f17905752`。源码完整 `stable` 回归为 `1128 passed / 1 skipped`，OpenSpec strict、Django check、迁移漂移与 diff check 通过。
- 生产最终已切换到从干净已提交 `main` 两次一致构建的 AMD64 镜像 `umanewsbot:main-304ebdb6-amd64-20260713-1230`，image ID 为 `sha256:e7ab7af0061d7362ad0582224baffc79eda07bd6d8f6467bfa573f760853877d`，Git tree 为 `5dfef5c7d219e63cd0b156071c89508cb42543ce`，context SHA-256 为 `a77a271cde3d0d06e25f9075036de5fc99415e832f2da052c84bf40bf956a7b5`。旧组合镜像已保留为回滚 tag `pre-main-304ebdb6-20260713-1240`。
- 切换前数据库备份为 `backups/db/pre-main-304ebdb6-20260713_123828.sql.gz`，大小 `148091210` bytes，SHA-256 为 `f61038e6a9e015f0eb0d59288029903911ebd55ed1acf600eabfb15a4c6ee126`，`gzip -t` 通过；`.env` 备份为 `.env.backup.main-304ebdb6-20260713_123828`。生产遗留的未跟踪旧版 `package_historical_race_detail_candidates.py` 已按原 SHA 保存在 `runtime/deploy/pre-main-304ebdb6-20260713_1239/`，由正式跟踪的新版接管路径。
- 切换按单一生产协调流程执行：停 beat，等待唯一术语发现任务自然结束，确认 Celery active/reserved、外部导入、归属与术语重处理锁均为 0；新镜像 migrate 无待迁移，Django check 和 `makemigrations --check --dry-run` 通过后重建 `web / worker / beat`。
- 上线验收：三个应用容器均使用 `sha256:e7ab7af0...877d`，`stable.0027–0029` 均已应用，64 models 加载正常，历史日期/批次/详情管理命令可用。归属、相关地区查询、翻译自动重试、失败邮件和历史网络/公开开关均继续安全关闭。历史 target 为法国/香港/英国各 `50 ready`，历史公开数为 0。内外 healthz、首页、五地区筛选、赛事页、马匹页与后台跳转均通过，最近日志无异常，新容器后的自然生产窗口无失败。“运行镜像不可复现”风险至此已解除。
- 新镜像后的北京时间 `12:45` 自然窗口已收口：当轮到期的 8 个抓取窗口全部 succeeded，五地区发布和 QQ 窗口全部 succeeded。netkeiba 新着顺读取 `116`、新增 `4`，文章 `8225–8228` 均已翻译并进入 `publish_ready`，未再出现 schema 约束错误。

## 2026-07-13 组合镜像恢复后三窗口只读验收

- 本次以北京时间 `11:15 / 11:30 / 11:45` 三个生产窗口为验收对象，并追加观察 `12:00` 窗口。该次验收时 `web / worker / beat` 统一使用临时 AMD64 组合镜像 `sha256:383a36c1...c7b4`，容器健康，最近 90 分钟日志未发现 traceback/error/critical/exception，也没有超过 30 分钟的 ProductionWindow 卡死。该镜像已由上述可复现主线镜像替代。
- 抓取主链路已恢复，但尚不能记为“完全正常”。`11:15` 为 `8 succeeded + 9 coalesced`，`11:30` 为 `9 succeeded + 8 coalesced`，`11:45` 的 17 个已启用且生产批准来源全部 succeeded。追加观察时，`12:00` 为 `10 succeeded + 6 coalesced`，同一批 6 个来源已在 `12:15` 成功抓取，证明合并不只是重建后追赶，也是当前调度算法的常态。来源以 `last_crawl_at` 滚动到期、beat 每 5 分钟检查，因此实际间隔约为 15–20 分钟，单个 15 分钟 bucket 不保证固定出现全部 17 条来源记录。
- 三窗口的抓取结果为日本新增 `9`，其他四地区来源均成功返回列表，但候选全为已入库重复稿，所以无新稿；不是来源失效或抓取报错。发布窗口全部 succeeded：`11:15` 日本发布 3 篇，`11:30` 日本发布 2 篇，`11:45` 因硬门禁/翻译等待发布 0 篇；其他地区均为 `no_ready_candidates`。QQ 窗口无失败，本时段实际成功交付 1 条，其余均有 `no_eligible_articles / already_sent` 明确原因。
- 尚存三类问题：文章 `8208` 为可重试 timeout，但生产 `TRANSLATION_AUTO_RETRY_ENABLED=false` 且到期后未自动重试；新稿 `8211 / 8215` 因 `Translation response appears incomplete` 被分类为 `unknown` 并停在 `translation_failed`，同样不会自愈。JRA 来源每轮还会跳过 `060302.pdf` 一条解析异常，来源整体仍成功。数据库另有 28 条历史 `CrawlJob(status=started)` 脏记录，最新一条为当日 `07:20`，它们没有对应运行任务、不阻断当前窗口，但会干扰运营观测。
- 结论：镜像/schema 不兼容造成的新闻写入故障已解除，抓取、发布、QQ 和 HTTP 主链路正在运行；但需先处理翻译失败自愈口径、JRA 固定 PDF 跳过和历史卡死记录，并明确是接受滚动 15–20 分钟口径还是改为对齐的严格 15 分钟调度，才能宣称“完全正常”。

## 历史状态记录

`2026-07-13` change `fix-france-news-freshness-and-multiregion-attribution` 已完成当时版本的本地实现与三轮 review/返修。TDN 法国入口、France Galop 时间证据、翻译恢复、多地区归属运行账本和灰度控制均已实现。该段原记录的“双审 250/40/50”Gold 门槛已由 2026-07-14 决策取代：现有 159 条单审 Gold Set 达到 `150/10/20` 首发覆盖和全部质量门槛，可进入 shadow，但生产 dry-run、至少 24 小时 shadow、全量变化复核、仅新文章 enforce 和相关地区查询灰度仍未完成，不得直接开启相关地区查询或归档 change。

`2026-07-13` OpenSpec change `fix-france-news-freshness-and-multiregion-attribution` 已完成两轮完整工程评审并进入 `reviewed` 阶段，共收敛 11 个架构、测试、性能和一致性问题。方案锁定：TDN 改用日期倒序 posts 查询；France Galop 保存 verified 详情时间且 fallback 不覆盖；瞬时翻译错误最多 3 次退避重试且默认不开自动调度；归属使用 `off|shadow|enforce` 单一模式，相关地区查询独立灰度；归属 dry-run/commit 使用持久 run、独立可续租锁、manifest、断点续跑和幂等保护。该日原评审口径要求双审、`250/40/50` 覆盖和 related recall `>=90%`，已由 `2026-07-14` 决策修订为单审可用、`150/10/20` 首发覆盖且 recall 首发线 `>=50%`；precision、准确率、扩散和性能门槛不变。灰度顺序仍为代码部署且 mode=off、shadow、仅新文章 enforce、网页/测试群相关查询、近期 72 小时回填、正式群。

`2026-07-12` 法国新闻新鲜度与低产出专项只读排查已完成，本次未修改代码、配置或文章状态。线上三个法国来源都在按有效 15 分钟频率成功轮询，但存在四个独立阻断：一是 `tdn_france` / `tdn_france_broad` 使用 WordPress `/wp/v2/search`，该接口按相关度返回固定历史结果而非按日期倒序，来源 `#21` 每轮因此正确过滤 `80` 条旧文却漏掉最新稿；实测改用 `/wp/v2/posts?search=...&orderby=date&order=desc&after=...`，`2026-07-09` 以来 11 组法国宽关键词可得到 `12` 篇去重候选，其中包含 `2026-07-11` Grand Prix de Paris 调时和 `2026-07-09` France Galop 预算稿。二是 `FranceGalopEnglishNewsAdapter` 列表阶段用 `timezone.now()` 作为发布时间，详情页未解析页面真实时间，重复抓取还会覆盖 `NewsArticle.published_at`；线上 `7871/7699/7031` 的官方真实日期分别为 `2026-07-11 / 2026-07-10 / 2026-07-05`，但数据库时间被刷新为最近轮询时间。三是最新 France Galop 稿 `7871/7699` 已抓入库，却分别因翻译供应商 `503/429` 停在 `translation_failed`，当前没有周期性失败翻译重试，`translation_retry_count=0`。四是生产 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，全球 TDN 最新流中的法国稿仍按来源默认记为美国，例如 `7872` Grand Prix de Paris 调时稿已入库但主地区为美国。推荐改造为：TDN 直接使用按日期倒序且带 `after` 的 posts 搜索；France Galop 解析正文官方时间并禁止 fallback 时间覆盖可信发布时间；对 `429/503` 增加有上限和退避的自动翻译重试；完成多地区归属复核后开启相关地区查询，使全球来源法国稿同时进入法国池。3 天新鲜度门禁应保留，不应通过提高上限掩盖入口排序和时间可信度问题。

`2026-07-12` 已对英文术语门禁重处理结果执行受控发布。按香港 run `#7`、英国 `#8`、美国 `#10`、法国 `#11` 的 manifest 锁定提交后，共恢复 `24` 篇候选；自然发布窗口在北京时间 `18:30` 发布 `18` 篇、`18:45` 发布 `6` 篇，QQ 因 `high_value_only` 策略均返回 `no_eligible_articles`，没有产生交付。发布后复核发现法国 `NewsSource#21 / CrawlJob#9408` 属于 `fix-tdn-france-search-date-freshness` 上线前的受污染库存：其中本次公开的 `7250/7256/7259/7261/7268` 官方真实日期分别为 `2026-06-23 / 2022-03-08 / 2020-04-27 / 2020-04-27 / 2017-03-29`，均不满足抓取时 3 天新鲜度要求。已在新备份 `backups/db/pre-term-gate-stale-cleanup-20260712_185347.sql.gz`（约 `100M`，gzip 校验通过，SHA-256 `a16f85f74d2d1d9de44debbf54f1bf096cff2ad2ce0a17f448ba259e6738a118`）后，将 `CrawlJob#9408` 全部 `20` 篇标记为 `withdrawn`、清空公开时间并写入批次清理原因，防止剩余待审核旧文再次被补跑复活。最终合格公开文章为香港 `7`、英国 `3`、美国 `9`，合计 `19` 篇；5 个旧文详情已从公网撤回，QQ 误推送为 `0`。生产仍保持 `ENGLISH_TERM_CONTEXT_MODE=shadow`，本次仅在锁定 commit 命令中临时使用 `enforce`，未改变常驻服务模式。

`2026-07-12` OpenSpec change `fix-english-term-context-gates-and-reprocess-performance` 已部署生产并进入 `shadow` 灰度，生产 HEAD 为 `f221c7df`。新增迁移 `stable.0028_term_gate_reprocess_runs`、只读运行后台、`off|shadow|enforce` 单一模式和带 run ID/manifest 的受控重处理；当前 `web/worker/beat` 均为 `shadow`，旧门禁继续决定自然流入文章状态。部署前备份为 `.env.backup.english-term-context-20260712_171023` 和 `backups/db/pre-english-term-context-20260712_171023.sql.gz`（109M，`gzip -t` 通过，SHA-256 `8f1cb6d3380db6c92671348d60a1c1d1633939bc637a38bcc2bdc796116486e1`）。生产 100 篇美国候选最终基准 run `#6`：7.53 秒、SQL 19 条、RSS 增量 36,503,552 bytes，术语索引 1 次，赛事实体/英文 alias/额外马名术语/重复语料预取 `2/1/0/1`，全部达标；100 篇中 20 篇可恢复、80 篇仍被真实专名或其他门禁阻断。四地区小批 dry-run 为香港 `12/16` 可恢复、英国 `3/20`、法国 `6/13`、美国 `9/20`；随后仅对已审核的 run `#7/#8/#10/#11` 执行 manifest 锁定 commit，实际恢复 `24` 篇并按上段记录完成发布与旧库存清理。抽检发现并修复 NFKC 前文字符膨胀导致审计 span 偏移，法国复验 run `#11` 已准确记录 `Exactly -> exactly`。本地最终专项 `81` 项、完整 `stable` `870` 项通过；Django、迁移、OpenSpec 和 diff 检查通过。内外 `/healthz/`、首页、新闻详情和重处理后台登录跳转已通过真实浏览器/接口验收。至少观察 24 小时并完成普通词、单词型真实马名和 uncertain 抽检前，不得切全局 `enforce`，不得继续提交其他历史 run，也暂不归档 change。

`2026-07-12` P0 马资料补全基础能力已部署生产提交 `ce676998`。本地分支先变基到最新 `origin/main=31cc82c`，P0 迁移因主干已有 `0023/0024/0026` 顺延为 `stable.0027_p0_horse_profile_completion`；最新主干上术语解析/旧马匹页/P0 定向测试 `104` 项通过，补齐临时环境 `pdfplumber` 后完整 `stable` `813` 项全部通过，Django check、迁移一致性、OpenSpec strict/all 和 `git diff --check` 通过。生产部署前 `HEAD=31cc82c`，容器、内外 `/healthz/`、公网 `/horses/` 正常，外部导入 started/锁和 Celery active/reserved 均为空，未发现历史回填进程；备份 `.env.backup.p0-horse-profile-20260712_162039` 与 `backups/db/pre-p0-horse-profile-20260712_162039.sql.gz`（109MB，`gzip -t` 通过）。生产已显式保持 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，并新增批次上限 `10`、强制来源 URL、在役履历新鲜度 `1` 天。部署后 `0027` 已应用，`manage.py check`、内外健康页、马匹页和 Django Admin 跳转通过，`web/worker/beat` 日志无 traceback；既有 `HorseRaceRecord=21`，全部回填幂等键、空键 `0`。P0 来源 dry-run 为 `term_candidates=21596`、`major_race_candidates=992`，实际重点赛事证据含 runner `5096`、result `4572`；为遵守“五地区各 10 匹先人工跑通”，本次未执行 `--sync-sources --commit`，生产 `HorseP0Source/HorseIdentityConflict/HorseProfileCompletionRun` 仍为 `0`，也未启用网络补全或自动首次发布。

项目当前已经完成正式域名 HTTP 接入修复，`umafans.run` 与 `www.umafans.run` 已可访问。  
“自动化内容运营 + AI 编辑改写 MVP”已完成代码侧与生产侧上线，当前处于上线后观察与质量抽检阶段。

`2026-07-13` 五地区历史赛事第一批验收已全部完成生产详情写入：selection snapshot 中 `45/45` 个目标均为 `imported`，对应 `45` 个历史 `RaceEvent`、`468 runners / 429 results`，全部保持 `draft`，历史公开数为 `0`。法国和英国2000年样本已使用按地区隔离的 IrishRacing 正式备用详情源补齐；美国2000/2012六场使用 Equibase 官方单场 standard PDF 补齐，共新增 `58 runners / 58 results`，逐场胜马和1号马核验通过。美国详情候选固定 SHA-256 为 `94b62febe849b9a0562e5ab641d87671ae3468a202355b5336a7f4405e8abe75`。

美国补源的证据链已收紧为 target 批准记录 → date/source cache manifest 的大小与 SHA-256 → 单场 PDF 的 URL、大小与 SHA-256 → PDF 页眉日期/赛场/场次复核；`1a` 等联合投注编号作为独立实际出走保留。日期 apply 前备份为 `backups/db/pre-equibase-us-date-apply-20260713_083026.sql.gz`（`120405132` bytes，SHA-256 `65da811725111da6c556d077118571da0d9bf5bed628d15c27ea7021052ad2e5`）；详情 apply 前备份为 `backups/db/pre-equibase-us-detail-apply-20260713_083319.sql.gz`（`120406520` bytes，SHA-256 `ad547a575ac03de17d8314821b3111b30ef5151231f2c4d33e5fe263c99d09c1`），两份均通过 `gzip -t`。生产镜像为 `umanewsbot:equibase-20260713`，回滚镜像为 `umanewsbot:pre-equibase-20260713`；数据库约 `796 MB`，内外 healthz、Django check 和近10分钟日志正常。`.env` 继续保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，历史线上展示暂不开放。

`2026-07-13` 高相似名称审核已完成：`15` 对确认合并为名称变体，`Prince of Wales's` 与 `Princess of Wales's` 确认保持为不同赛事。最终身份总账为 `runtime/historical_race_inventory/tjcis-inventory-1998-2026-v12-final-20260713/`，保留 `30,917` 个年度目标和 `2,334` 条正式赛事线；高相似名称合并没有删除任何年度目标。最终工作簿为 `outputs/race_identity_review_20260712/TJCIS_1998-2026_赛事系列身份审核最终结论版.xlsx`，结构化校验、SHA-256、公式和视觉检查均通过。至此1998–2026同名簇与高相似名称身份审核全部完成，生产数据库仍未写入，历史公开开关继续关闭。

`2026-07-13` 已完成 TJCIS 1998–2026 的 `25` 个同名赛事簇逐项人工审核，并生成审核后身份决策与总账 v11。`102` 个临时 Series Key 已归入 `58` 条正式赛事线；审核后年度目标由 `30,919` 行变为 `30,917` 行，仅消除两组经确认的重复年度表达：Bristol Novices' Hurdle 的 2001 届（实际于 `2002-01-11` 在 Huntingdon 举办）和 Louisville Stakes 2008 改场记录。京都雌马锦标 `2005–2009` 已由 `not_held` 修正为 `held`；Keeneland First Lady 2000 年年度显示名修为 `Galaxy Stakes`；NYRA Matron 2018 场地修为 turf。正式产物为 `runtime/historical_race_inventory/tjcis-inventory-1998-2026-v11-approved-20260713/`，审核工作簿为 `outputs/race_identity_review_20260712/TJCIS_1998-2026_赛事系列身份审核结论版.xlsx`。逐届证据合并后为 `685` 届，可靠冠军 `473` 届、1号马 `164` 届。结构化校验、SHA-256 清单和工作簿视觉检查均通过。本次未写生产数据库、未部署，历史公开开关继续关闭。

同名簇身份边界已经审核完成，Ascot 约 3m 金杯线中文主名已确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。`16` 对高相似名称也已完成审核，其中 `15` 对合并为名称变体，Prince/Princess of Wales's 保持独立。1998–2026 身份冲突审核现已清零。

同日补充确定五地区赛事详情的来源优先级：日本以 JRA 为官方主源，netkeiba 补历史出马表/赛果，JBIS 补血统与赛事沿革；中国香港以 HKJC Race Card / Results 为绝对主源；英国以 Racing Post Full Result 采实际出走和赛果，Sky Sports Racecard 补赛前声明出马表，BHA 仅用于 2014 年后官方校验；法国以 France Galop 为主、PMU 补充；美国以 Equibase historical charts 为主，BRISnet chart archive、DRF 和 BloodHorse 交叉校验，美国障碍赛另以 NSA 为重要来源。`declared runners`、`actual runners`、`non-runners` 和 `results` 必须分别记录及保留各自来源，不能用完赛结果中的实际出走马冒充赛前出马表。

`2026-07-12` 已把 TJCIS 1998–2026 身份审核表扩展为逐届证据版，产物为 `outputs/race_identity_review_20260712/TJCIS_1998-2026_赛事系列身份审核.xlsx`。该文件是人工审核前的原始证据快照，范围含 `25` 个同名簇、`102` 个临时 series key 和 `687` 个原始年度行；经生产库、JRA、TOBA、Wikipedia 历届冠军表和 Racing Post 单届赛果交叉补证，审前快照取得冠军 `474` 行、1号马 `164` 行。其同名簇结论和京都雌马冲突已由 `2026-07-13` 结论版及 v11 总账取代，原文件仅作审计留存。距离继续保留 TJCIS 原文，不允许跨地区直接比较裸数字；正式标准化前必须同时保存原值、原单位和统一换算值。

同日生产库只读覆盖复核：`RaceEvent=992`，其中 `finished=503 / scheduled=484 / cancelled=5`；有出马表的赛事 `505/992`（约 `50.9%`），有赛果的赛事 `503/992`（约 `50.7%`）。所有 `503` 场已完赛赛事均同时有出马表和赛果，因此按已完赛赛事为分母时两项覆盖均为 `100%`。现有模型没有独立的逐模块 `is_complete` 数据库字段，上述百分比是“存在正式模块数据”的运行态口径；全赛事约一半无赛果主要因为尚未开赛，而不是完赛后漏抓。

`2026-07-11` 已在生产库生成赛事编排第一批五地区应到清单，run 为 `runtime/race_event_crawl_runs/first-acceptance-race-event-crawl-20260711/`。本批每地区 1 场、共 5 场，分别为日本德比、富卫保险女皇杯、BETFRED DERBY、PRIX DE DIANE LONGINES、KENTUCKY DERBY PRESENTED BY WOODFORD RESERVE；三模块目标均为 `runners / results / history_winners`，5 行 `preflight_status` 全部为 `ready`。审批文件仍为 `pending`，plan 中 `allow_network=false`，本次没有访问外部网站、没有生成候选、没有写赛事详情。人工审核入口为 `review/expected_targets_review.csv`；只有用户确认赛事名称、年份、地区和 slug 后才允许填写审批并创建可触网的新 plan。

用户已确认第一批范围与中英文名。网络版 run `first-acceptance-race-event-crawl-network-20260711` 已生成，并与原审批清单逐字段对比一致；进入 prepare 前发现生产镜像未包含 adapter 所需的 `runtime/tools/*.py`。首次镜像补包后，真实 prepare 进一步暴露 Django 工作目录 `/app/server` 与 AdapterRunner 仓库根 `/app` 对相对 runtime 路径的解释不一致，`jra_detail` 在零网络请求时失败。最终镜像约定统一为 `/app/runtime`，并由 `/app/server/runtime` 符号链接到同一目录；运行计划、审批和失败 state 保持不变，修复后使用 resume 重试。

第一批网络抓取 v2 已完成 prepare 和覆盖审计，但审计状态为 `blocked`，未进入 dry-run 或写库：香港、英国、法国三场完整；JRA 详情脚本按筛选后序号误取全年首个结果页，把日本德比错配为中山金杯；美国 HRN 只有参赛名单，TOBA 在线页返回 403，缺正式赛果和历届冠军。JRA 已改为按赛事原名/别名唯一匹配结果页，编排测试 `55` 项通过。v3 保持已批准五场赛事不变，新增 `us_equibase_results`，计划以 HRN 参赛名单、Equibase 官方赛果 PDF、TOBA 已验证年度页组合完成美国三模块；五地区覆盖审计全部通过前不得进入 dry-run。

v3 首次 prepare 在请求预算 `60/60` 时由 HRN 空候选连带阻断 Equibase；补入此前留存的同源 HRN 日期页和 Churchill Downs 赛场页后，resume 已得到 24 匹参赛马且未新增请求。随后发现生产镜像缺少 Equibase PDF 脚本所需的 `pdfplumber`，当前补充 `pdfplumber==0.11.9` 并重建镜像；该阶段仍未运行 dry-run 或写库。

补齐依赖后 v3 prepare 的 11 个 adapter 已全部成功；Equibase 产出 Kentucky Derby 正式赛果 18 条、冠军 `Golden Tempo`。首次 coverage 仍为 `blocked`、完整地区 `3/5`：法国 Wikipedia 历史 adapter 因预算耗尽留下空候选；美国审计把 HRN 的空 `results` 与 Equibase 非空 `results` 误判为重复。当前审计改为只让非空模块参与重复、完整度和来源策略；只有空模块而无替代来源时仍报告 `empty_<module>`。回归测试增至 `56` 项通过，法国将使用留存的同源搜索响应和页面恢复后重新审计。

法国缓存按 canonical query 别名恢复后，coverage 已通过：`complete_count=5`、应到/实到均为 `5`、blocker 为 `0`，候选 SHA-256 为 `4043a5ee7a4c3cd09d9d2d15ae4bfec7ce32440f68b0836f3a4ec56d8b00bee7`。首轮 dry-run 通过，统计 11 条 adapter record、16 个模块、`runners=75 / results=64 / history_winners=47`；继续检查发现组合文件仍保留 HRN 空 `results`，虽会被 Equibase 后写覆盖，但与批准 apply scope 不一致。当前在 aggregate 阶段剔除显式空模块和全空记录，测试增至 `57` 项通过；修复部署后须重新生成候选身份、coverage 和 dry-run，尚未正式写库。

空模块修复后候选 SHA-256 为 `795e3629821dd843526a88bb445e2a65383c647a958578151d2bcbd99a56245a`，coverage `5/5`、blocker `0`，dry-run 为 11 条 record、15 个有效模块、`runners=75 / results=64 / history_winners=47`。字段级只读 diff 随后发现 JRA 2026 历史冠军候选会把现有练马师 `杉山 晴紀` 和完赛时间 `2:22.7` 覆盖为空，因此未放行 apply。当前 coverage 增加关键字段非空数量退化门禁，`jra_history_winners` 显式依赖同批 `jra_detail` 补齐当年冠军详情；25 年真实缓存 smoke 已确认 2026 `ロブチェン` 保留上述字段，编排测试 `65` 项通过。部署后需再次更新所有证据身份，仍未写库。

最终 resume 已通过：生产运行 `ad31a6d`，coverage `5/5`、blocker `0`，dry-run 为 11 条 record、15 个有效模块、`runners=75 / results=64 / history_winners=47`，最终候选 SHA-256 为 `2dd40a141219f7fd39799b7f586efb862f2332e8e037e4091f46c88bee48eac5`，请求账本保持 `60`。JRA 当届冠军字段已完整保留。字段级业务 review 只剩三类真实变化：英国历史增加 2020 `Serpentine` 并补 2021 `Adayar` 完赛时间；法国 `EVOLUTIONIST` 练马师从 `Burke Kr.` 规范为 `K R Burke`；法国 2026 冠军从大写/缩写人名规范为 `Diamond Necklace / Ryan Moore / Aidan O'Brien` 并补 `2:03:78`。其余核心字段与现有数据一致。当前停在 apply-check 前，等待用户确认这三类覆盖变化和法国/美国 mixed-source 策略，尚未正式写库。

用户已确认上述覆盖变化和 mixed-source 策略，第一批于 `2026-07-12` 正式写入生产。apply-check 的 8 个实际 scope 全部匹配，法国/美国 strategy SHA 已确认，blocker 为 `0`；写入命令按候选 SHA 锁定并在整批事务中完成，`candidates=15 / applied=15`。五场写后合计为 `runners=75 / results=64 / history_winners=47`，历史冠军较写前增加 1 条，RaceEventDataCandidate 从 27 增至 42；最新 15 条均为 `applied`。JRA `ロブチェン / 杉山 晴紀 / 2:22.7`、英国 2020/2021 补充、法国规范化和美国 Equibase 冠军均验收通过。写前备份为 `/opt/umanewsbot/backups/db/pre-first-race-crawl-apply-20260712_000116.sql.gz`，`105M`，gzip 与 SHA-256 校验通过；本地/公网 healthz 和 `/races/` 均返回 `200`，外部导入与锁仍为 `0`。

`2026-07-11` 发布提交 `38974f1` 已部署生产。赛事信息编排管理命令、adapter、五地区第一验收 fixture 和写入证据门禁已在线可用；本次只部署工具，没有启动真实赛事网络抓取，也没有写入赛事数据。多地区新闻归属代码与迁移 `stable.0023_multiregion_news_attribution` 同批上线，但生产 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`，旧文章、地区查询、发布窗口和 QQ 继续使用原有主地区逻辑。生产五地区临时开启式 dry-run 发现归属结果仍需产品复核：法国样本 `article_id=7031` 从法国推断为英国主地区，日本样本中也出现主地区改为中国香港，并有样本一次关联三至四个地区；因此未启用归属功能、未执行 commit。验收 artifact 位于生产 `runtime/deployment_acceptance/multiregion-20260711_0352-enabled-dry-run/`。部署前备份为 `.env.backup.multiregion-orchestration-20260711_034313` 和 `backups/db/pre-multiregion-orchestration-20260711_034313.sql.gz`（约 `101M`，`gzip -t` 通过）。部署后六个容器正常，Django check、`/healthz/`、首页、法英地区页和后台登录 smoke 通过，web/worker 近 15 分钟无 error。

`2026-07-11` 赛事编排第四轮技术返修已实现：coverage 新增 `actual_apply_scopes`，apply-check 对账真实地区/来源/模块组合并逐组合要求确认；全绿后生成按 SHA-256 命名的 approved candidate，最终 importer 通过 `--expected-sha256` 从同一批原始字节复核后才解析写库；自定义 adapter 缺少非空 command/modules/outputs 或 provenance 时在 plan 阶段失败，prepare 不再静默跳过；coverage 行级 blocker 与 warning 已拆分，`existing_data_diff` 单独存在时标记 `complete_with_warnings` 且仍计入完整覆盖，候选更不完整时继续 blocked。独立赛事编排专项测试 `41` 项、包含并行马匹主页功能在内的完整 `stable` 测试 `581` 项均通过，Django check 和迁移漂移检查通过；当前未执行真实抓取、未写生产数据。

`2026-07-10` `classify-english-term-gate-context` 已部署生产。该变更在英文来源 `validate_rewrite()` 生成 `core_term_missing` 前加入上下文语义判定：地区过滤仍优先；本批已审核普通英文词种子和 `MULTIREGION_TERM_GATE_COMMON_ENGLISH_TERMS` 按“普通词概率更高”处理，默认降级为 `english_term_common_word_downgraded` warning；只有 `wins / returns / runs / targets / entered` 等强动作上下文才把普通词种子保守维持为 blocker。`Classic` 这类同时属于普通词和赛事 marker 的 horse term 会先走普通词上下文判断，`Contact and live updates from York` / `Live stable updates` 等弱赛马上下文不会硬挡。重校验命令 `reprocess_term_gate_blocked_articles` 已改为有界候选、批量预加载术语/alias，并输出文章级英文分类明细、真实专名阻断明细和地区 summary；`--commit` 只恢复完整门禁通过文章到可发布候选，不直接公开发布。上线前本地已通过目标测试、`manage.py check`、`openspec validate classify-english-term-gate-context --strict` 和 `git diff --check`。生产部署前已把服务器独有的移动端马匹导航修复提交合并回主线，最终上线提交为 `43898ff`；备份 `.env.backup.english-term-context-20260710_030705` 和 `backups/db/pre-english-term-context-20260710_030705.sql.gz` 均已生成且数据库备份通过 `gzip -t`。部署后 `web / worker / beat / db / redis / nginx` 正常，生产 `manage.py check`、本地 `/healthz/`、公网 `/healthz/`、首页和后台登录入口 smoke 均通过。

生产完整只读 dry-run 已完成，产物目录为 `runtime/multiregion_candidate_audit/reprocess_full_dryrun_20260710_030944/`，本次未执行 `--commit`、未恢复候选、未公开发布。四地区旧 `core_term_missing` 候选合计 `146` 篇，其中 dry-run 后完整门禁通过、可恢复为发布候选的为 `37` 篇：香港 `3/17`、英国 `5/37`、美国 `22/79`、法国 `7/13`；仍阻断 `109` 篇。普通词降级命中合计 `142` 次，仍保留真实专名 blocker 合计 `549` 次。OpenSpec change 已归档到 `openspec/changes/archive/2026-07-10-classify-english-term-gate-context/`，正式规格已同步到 `openspec/specs/automation-publish-gates/spec.md`。下一步如要实际恢复文章，应先人工抽检 dry-run JSON，确认无真实马名、赛事名或人物名被误降级，再按地区小批执行 `--commit`。
`2026-07-10` 已做一次只读数据续抓盘点，本次未执行生产抓取、未写库、未部署。当前已经批量处理过的数据主线包括：新闻源抓取与多地区新闻源探测、术语种子与候选池审计、2026 五地区重要赛事基础表、部分赛事详情出走表/赛果、HKJC / Sporting Life / Geny / HRN 外部赛马数据库 proof / dry-run，以及已发布文章术语回填。后续继续抓取建议优先放在结构化赛事数据，而不是盲目扩大新闻抓取：第一优先补英国 / 法国赛事详情和五地区历届冠军；第二优先恢复 HKJC 长窗口 dry-run 并按审计门禁判断是否进入 commit；第三优先按 runbook 开始英国、法国、美国最近 60 天外部赛马数据库完整 dry-run。新闻侧继续常态观察来源健康和门禁原因即可。

`2026-07-10` 已完成英法赛事详情候选的只读覆盖校验，并生成离线审计产物 `runtime/race_event_detail_imports/2026/coverage-audit-20260710/`。英国基础赛事共 `202` 场（Flat `138`、Jump `64`），CSV 状态已完赛 `123` 场；现有 Sporting Life 详情候选规范合并后 `122` 场，所有候选 slug 均能回到基础赛事，规范候选内无重复 slug、无 source URL 一对多映射。英国缺口为 `uk-bha-jump-2026-0206-016 / Jane Seymour Nov. Hurdle`，另有 `2026-07-09` 至 `2026-07-10` 已到日期但 CSV 仍为 `scheduled` 的 Flat 赛事 `5` 场，后续应刷新 Sporting Life 结果页后再补。法国基础赛事共 `173` 场，CSV 状态已完赛 `74` 场；ZEturf 候选原始记录 `80` 条，存在 `6` 个重复 slug，规范合并后 `74` 场，已覆盖全部已完赛法国赛事且候选均回到基础赛事，规范候选内无 source URL 一对多映射。法国重复中 `fr-france-galop-2026-0705-044` 曾有一条误配到 `Prix des Côteaux de Saint-Cloud` 的候选，规范包已保留匹配 `Grand Prix de Saint-Cloud` 的 `R1C5` 版本。规范候选包为 `uk_canonical_detail_candidates_20260710.jsonl` 与 `france_canonical_detail_candidates_20260710.jsonl`；本地 `import_race_event_detail_candidates --dry-run` 因本地 sqlite 未加载生产 `RaceEvent` 行而无法执行，生产 dry-run 前仍需在生产库上重新校验。

`2026-07-10` 生产复核发现英法赛事详情实际上已完成正式导入：生产 `RaceEventRunner=5096`、`RaceEventResult=4572`、`RaceEventHistoryWinner=5731`、`RaceEventDataCandidate=2913`，其中英国已应用 `sporting_life` 116 组和 `sporting_life_gap` 6 组，法国已应用 `zeturf` 候选；英国 `Jane Seymour Nov. Hurdle` 当前生产状态为 `cancelled`，不是需补赛果的 finished 缺口。复核同时发现 `fr-france-galop-2026-0705-044 / GRAND PRIX DE SAINT-CLOUD` 的出走表和赛果已被正确 R1C5 覆盖，但 `RaceEventHistoryWinner` 中 `2026` 年冠军仍残留早先误配 R1C4 的 `ZELMAN`。已在生产生成单场修复 JSONL `grand_prix_saint_cloud_history_repair_20260710.jsonl`，dry-run 通过 `events=1 modules=1 items={"history_winners": 7}`；写入前备份 `backups/db/pre-race-detail-gpsc-history-repair-20260710_025949.sql.gz`（约 `96M`）且 `gzip -t` 通过；正式 apply 成功 `events=1 candidates=1 applied=1`，新增 applied candidate `2914`，该赛事 2026 历史冠军已修为 `CALANDAGAN`，公网 `/races/2026/fr-france-galop-2026-0705-044/` 可见 `CALANDAGAN`，本地/Host `/healthz/` 均返回 `ok`。本次没有重复导入整批英法 runners/results。

`2026-07-10` 已为后续长期赛事历史回填创建并完成 OpenSpec change `orchestrate-race-event-data-crawls` 的 planning artifacts：`proposal.md`、`design.md`、`tasks.md`，以及 `race-event-data-crawl-orchestration` 新规格和 `race-event-pages` / `real-global-racing-data-ingestion` delta specs；已执行 `/plan-eng-review` 并将 change 标记为 `profile=feature`、`phase=reviewed`，review 轮次为 `1`，修正了 adapter 非统一脚本契约、深历史目标 `RaceEvent` 行预检 / draft seed 清单、五地区第一验收 fixture 覆盖三项计划风险。随后已新增 `server/stable/test_race_event_crawl_orchestration.py` 目标测试，并实现 `stable.services.race_event_crawl_orchestration` 与 `orchestrate_race_event_crawl` 管理命令，支持 `plan`、`prepare`、`audit`、`dry-run`、`apply-check`、`resume` 阶段。多轮返修后编排工具已处理：plan 自复制、adapter 相对路径和网络授权、分模块候选聚合、活跃锁判断、真实 resume、人工归因保护，以及正式门禁证据绑定。当前 adapter 会从 manifest 向标准候选和 summary 注入 provenance，并记录必需输出 SHA-256；coverage 会阻断缺失/冲突 source authority，记录候选身份和混合来源策略；结构化 `dry_run.json` 与 apply-check 强制核对同一候选哈希，不能用另一份 JSONL 或空壳日志绕过；resume 只在输入和必需输出哈希都一致时跳过，并可恢复 audit、dry-run 和 apply-check；所有阶段成功/失败都会写入同一 state。新闻入库同时补充保护：来源提升不得覆盖 `attribution_locked=true` 的人工主地区。默认 adapter registry 已覆盖 JRA/NAR/HKJC/UK Sporting Life/France ZEturf/US HRN/Equibase 的 runners/results 路径，以及 JRA/NAR/HKJC/UK Sporting Life/France Wikipedia/US TOBA 的 history_winners 路径；第一验收 plan fixture 位于 `server/stable/fixtures/race_event_crawl/first_acceptance_plan.json`，source authority 矩阵位于 `server/stable/fixtures/race_event_crawl/source_authority_matrix.json`。本轮验证为赛事编排专项测试 `29` 项、完整 `stable` 测试 `545` 项、Django check、迁移漂移检查、Python 编译、OpenSpec 严格/全量校验和 `git diff --check` 全部通过。该 change 目前仍未运行真实抓取、未写生产数据。已锁定的第一版边界：只服务 `RaceEvent*` 产品层，不写 `External*`；日本、香港、英国、法国、美国五地区都要参与第一验收小批；第一阶段不含 Listed；`runners`、`results`、`history_winners` 三模块同历史深度推进；历史 series 必须显式 mapping；长周期运行默认手动分批 / 一次性容器，不做 Celery Beat 或无人值守 apply。

`2026-07-10` 第三轮赛事编排审查返修已实现并完成本地验证：run 在网络请求前根据 plan 独立生成绑定 plan SHA-256 的 `expected_targets.json` 与运营 review CSV，清单包含赛事中英文名、年份、地区、slug 和预检状态；coverage 以该清单为固定分母，空候选、缺少应到目标、出现计划外候选或 series 不一致均 fail closed。prepare 会把全部 adapter 的标准候选汇总为 `combined_candidates.jsonl`，audit / dry-run 默认复用该文件；plan 的 batch/rate limit 已从“仅记录配置”改为真实执行，全部默认网络 adapter 共享 run 级 `request_budget.json`，累计达到上限或预算证据损坏时停止请求。第一验收会逐地区检查三模块 adapter 覆盖，apply-check 会验证真实备份文件、gzip 通过和 `diff_review.status=approved`。英文门禁同时修复 ignored alias 连带豁免同记录其他可信专名的问题。目标回归 `40` 项、完整 `stable` 回归 `555` 项、Django check、迁移漂移、Python 编译、两个 change 严格校验、全量 OpenSpec `19` 项和 diff 检查全部通过。当前仍未进行真实网络抓取、生产写入或部署；第一批真实抓取前需由用户审核应到清单，技术性证据由工程侧负责。

`2026-07-08` 本地已修复 2026 赛事历届冠军 / 缺口详情候选生成工具的 apply 前安全问题：`prepare_jra_history_winner_candidates.py`、`prepare_hkjc_history_winner_candidates.py`、`prepare_nar_history_winner_candidates.py`、`prepare_uk_sportinglife_history_winner_candidates.py`、`prepare_us_toba_history_winner_candidates.py` 和 `prepare_france_wikipedia_history_winner_candidates.py` 在年份、马季、previous-winners 链路或 Wikipedia 赛事页出现中途错误时，默认跳过相关赛事并记录 `partial_*` skipped，不再生成半截 `history_winners` 候选后在正式 apply 中替换掉已有完整数据；如确需人工接受部分历史，可显式使用 `--allow-partial-history` 并在 metadata 中保留 diagnostics。`prepare_uk_sportinglife_gap_candidates.py` 现在会在 Sporting Life 详情解析出空出走表或空赛果时写入 `skipped`，不再生成可 apply 的空 runners/results 候选，避免覆盖已有赛事详情。`.gitignore` 已补充 `runtime/race_event_history_imports/` 与 `runtime/term_review/`，防止历史冠军 HTML/cache、review CSV/JSON、术语 snapshot 等运行产物被误提交；可复用脚本仍保留在 `runtime/tools/`。

`2026-07-10` 已按用户抽检结论处理候选池 raw 分类结果：`raw_classified_term_candidates_candidate_pool_20260701_20260707.csv` 中 `is_likely_term=yes` 的 `369` 条全部为 `existing_termbase_residual` 且均有 `existing_term_id`；进一步生产只读核对显示对应 `350` 个唯一 `TermEntry` 当前全部存在且 active，因此无需新增术语库记录。`is_likely_term=no` 的 `89` 条已确认为非术语；本地代码新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS` 默认配置，并在发布校验中将命中该配置的 source term 记为 `non_term_gate_ignored` / `info`，不参与 `core_term_missing` / `background_term_missing` 阻断。该列表覆盖本次 raw no 类中的 HTML/布局片段、源站/导航/产品噪声、普通赛马词、片段/普通词等；`review` 类暂不处理，尤其暂无翻译的马名不批量创建中文译名。本地验证已通过目标测试、`manage.py check` 和 settings 默认值读取；本次未写生产术语库、未部署生产、未回填文章字段。

`2026-07-07` OpenSpec change `fix-tdn-france-search-date-freshness` 已完成实现并部署生产，用于修复法国 `tdn_france_broad` 抓入历史旧文的问题。根因是 TDN WordPress search API 返回相关性历史结果且 search item 不带发布时间；修复后 `TDNFranceKeywordAdapter` / `TDNFranceBroadKeywordAdapter` 会用 search item 的 `id` 或 `_links.self` 二次读取 post API 的真实 `date_gmt/date`，缺失真实日期的条目会跳过，超过 3 天新鲜度窗口的历史旧文也会跳过，且 listing 阶段跳过会写入 `CrawlJob` / `NewsSource.last_crawl_message`，不再兜底为当前时间。本地验证已通过目标测试、`DB_ENGINE=sqlite python manage.py check`、完整 `stable` 测试 `493` 项、`openspec validate fix-tdn-france-search-date-freshness --strict`、`openspec validate --all` 和 `git diff --check`。生产服务器 `/opt/umanewsbot` 已通过 bundle 从 `96fde81` 快进到 `ad587ce` 并重建 `web / worker / beat`；部署前数据库备份为 `backups/db/pre-tdn-france-freshness-20260707_223913.sql.gz` 且 `gzip -t` 通过，外部导入运行数和锁均为 `0`。已将误发布的历史旧文 `7255/7263/7264/7265/7271` 标记为 `withdrawn`、清空 `published_to_web_at` 并写入清理原因，公网 `/news/<id>/` 均返回 `404`。`NewsSource#21 TDN 法国宽关键词英文新闻` 已重新启用：`enabled=true`、`production_approved=true`、`manual_pause_reason=""`。线上只读探测当前为 HTTP `200` 但 `empty_sample`，真实抓取 `CrawlJob#9445` 成功，`new_count=0`、`seen_count=0`、`skipped_count=80`，首条原因 `stale_published_at`，无新增文章，确认 2020/2022 等历史旧文已被过滤而非入库。

`2026-07-07` 已在 worktree `/Users/mentianlu/.codex/worktrees/race-detail-page/umanews` 本地实现 OpenSpec change `horse-profile-page-mvp`。新增 `HorseProfile`、`HorseProfileDataCandidate`、`HorseRaceRecord`、`HorseRaceLink`、`ArticleHorseLink` 和 `HorseFollow`，迁移为 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more`；P0 马由 `generate_horse_profiles` 从 active horse `TermEntry` 生成草稿，默认不前台可见，管理员可在 `/admin/horse-profiles/` 审核、补资料、维护参赛履历/新闻关联并手动发布，空壳也允许强制发布。公开入口新增 `/horses/`、`/horses/<id>/`、`/horses/follows/`，URL 只使用唯一 ID；新闻详情页展示已发布马匹 tag，首页新增“我的关注”模块，匿名关注只在 cookie 中保存签名 token，数据库只存 `token_hash`，可包含关注马的子孙代新闻。外部补全采用“本地 ExternalHorse/ExternalHorseAlias 缓存 + dry-run artifact + 人工审核后 commit”的门禁，`complete_horse_profiles` 会输出全局/按地区完整二代成功率、未补全占比、逐马失败原因和 source URL；commit 必须指定 `--artifact --confirm-reviewed-artifact`。KeibaScraper 调研结果：`new-village/KeibaScraper` 当前为 Apache-2.0、PyPI 3.1.5（2026-05-13 发布）、项目说明提示请求会给 netkeiba 带来负载，因此只作为受控 `external_horse_data` 导入链路的数据源，不让公开页或审核页直接访问第三方。本地验证已通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.HorseProfilePageMvpTests --noinput`（8 项）和完整 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（498 项）。

`2026-07-08` 已完成 `horse-profile-page-mvp` 本地审查修复：`complete_horse_profiles --dry-run` 不再默认截断为 100 条，未传 `--limit` 时覆盖所有地区全部 P0 马；马名和术语匹配统一对拉丁字母大小写不敏感；关注列表、首页关注模块和关注流只返回仍为 `published` 的马匹及其公开子孙代，后台下线或隐藏后不会继续在前台关注面泄露；补全 artifact commit 会在写库前生成 before/after diff，保留真实审计差异。补充回归测试后，本地验证通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.TermResolverTests stable.tests.HorseProfilePageMvpTests --noinput`（31 项）和完整 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（503 项）。

`2026-07-08` 二次审查后继续收紧 `horse-profile-page-mvp`：后台资料保存表单不再携带 `review_status`，发布/下线只能走专门状态动作以保留 `published_at/published_by/hidden_at/hidden_by` 和状态变更日志；补全 summary 的 `regions` 也输出按地区 `complete_ratio` / `not_complete_ratio`；`scan_article_horse_links_task` 在显式 `article_id` 或 `profile_id` 已不存在时直接返回 skipped，不再退化为默认范围扫描。补充回归测试后，本地验证通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.HorseProfilePageMvpTests stable.tests.TermResolverTests --noinput`（33 项）和完整 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（505 项）。

`2026-07-08` `horse-profile-page-mvp` 已部署生产提交 `2b28755`。部署前生产 `HEAD=01c0b9b`，容器健康，`manage.py check`、本地 `/healthz/`、公网 `/healthz/` 通过，`ExternalDataImportRun(status="started")=0` 且外部导入锁为空；备份 `.env` 为 `.env.backup.horse-profile-page-mvp-20260708_040446`，数据库备份为 `backups/db/pre-horse-profile-page-mvp-20260708_040503.sql.gz`（约 `85M`）并通过 `gzip -t`。已在生产 `.env` 显式设置保守默认：`HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`、`HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`、`HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`。部署后 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more` 已应用，`web / worker / beat / db / redis / nginx` 正常，生产 `manage.py check` 通过，本地和公网 `/healthz/`、公网 `/horses/` 均返回 `200`。已执行 `generate_horse_profiles`，生成 `21596` 个 `HorseProfile`，全部为 `draft`，`published=0`；草稿样例 `/horses/1/` 返回 `404`，未登录 `/admin/horse-profiles/` 返回 `302`。历史新闻马匹关联 dry-run `--limit 500` 为 `created=0 updated=0 candidate=0`。全地区补全 dry-run 已输出到生产宿主机 `runtime/horse_profile_completion/dry-run-20260708_041343/`，覆盖 `21596` 匹 P0 马：完整二代 `0`、未补全 `21596`、未补全占比 `1.0`；原因分布为 `no_external_match=15293`、`source_unavailable=6301`、`profile_only=2`，按地区 `france/hong_kong/japan/other/united_kingdom/united_states` 的未补全占比均为 `1.0`。本次未应用补全 artifact，后续需先人工审核 `horse_profile_completion_review.csv` 后再 commit。

`2026-07-08` OpenSpec change `horse-profile-page-mvp` 已归档到 `openspec/changes/archive/2026-07-08-horse-profile-page-mvp/`。归档前已将 delta spec 同步到正式规格：新增 `openspec/specs/horse-profile-pages/spec.md` 与 `openspec/specs/horse-profile-data-completion/spec.md`，并把首页关注模块、关注管理入口和新闻详情马匹 tag 要求合并到 `openspec/specs/public-home-info-feed/spec.md`。归档后 `openspec validate --all` 通过 `19` 项。

`2026-07-10` 已将马匹详情页 MVP 最后一轮前台体验修复和两匹样本马资料上线到 UmaNews 生产服务器 `root@47.239.167.86:/opt/umanewsbot`，最终生产 `HEAD=65988b0`。本次只使用 UmaNews 服务器，未使用其他项目服务器。部署前备份 `.env.backup.horse-public-polish-20260710_010639` / `backups/db/pre-horse-public-polish-20260710_010639.sql.gz`，样本写入前备份 `backups/db/pre-horse-sample-profiles-20260710_011038.sql.gz`，移动样式修复前备份 `.env.backup.horse-mobile-polish-20260710_011811` / `backups/db/pre-horse-mobile-polish-20260710_011811.sql.gz`，均已 `gzip -t`。已发布 `春秋分` `/horses/13113/` 与 `北十字星` `/horses/3873/`，来源为用户指定 netkeiba 页面 `https://db.netkeiba.com/horse/2019105219/` 与 `https://db.netkeiba.com/horse/2022105102/`；两匹马均为 `published`、`complete_pedigree_2gen`，参赛履历分别为 `10` / `11` 条，相关新闻人工关联各 `5` 篇。浏览器验收覆盖：详情页二代血统、主胜鞍、参赛履历、相关新闻、新闻详情马匹 tag 点击、匿名关注/取消关注、关注页新闻流、`croix` / `EQUINOX` 大小写搜索、移动端一级导航和地区筛选布局；测试关注已清理，最终 `HorseFollow` 样本计数为 `0`。生产 `manage.py check`、本地和公网 `/healthz/` 均通过。

`2026-07-10` 已为 P0 马资料补全专项新建独立 worktree `/Users/mentianlu/.codex/worktrees/p0-horse-info-completion/umanews`，分支 `codex/p0-horse-info-completion`，并从 `origin/main` 快进对齐旧线程最终提交 `d78fab0`（其中生产运行代码为 `65988b0`，`d78fab0` 为文档验收记录）。已创建并经 `/grill-me` 需求追问重写 OpenSpec change `complete-p0-horse-profile-data`：新版 P0 马范围为“当前 active 且有中文译名的 horse `TermEntry` + 日本/中国香港/英国/法国/美国全部历史与未来重点赛事参赛马”，重点赛事等级严格限定为 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ`；暂无中文译名的 P0 马允许进入补全、ready 和人工发布，翻译命中时必须保留原文而不做空中文替换。首批验收口径已改为五大地区各 10 匹完整资料马，完整资料硬门槛包含身份/P0 来源证据、基础事实字段、二代血统、完整赛事履历、主胜鞍、来源 URL、赛马生涯/同步状态和人工审核记录，`intro`、相关新闻和站内相关赛事链接不作为硬门槛。已重新执行 `plan-eng-review`（Full mode，session 2，2 个问题已修复），补充了退役/在役履历同步状态与 `docs/decisions.md` 回写任务；`.openspec.yaml` 当前 `phase=reviewed`。已通过 `openspec validate complete-p0-horse-profile-data --strict`；本 change 尚未进入代码实现或生产执行。原“下一步运行 openspec apply skill”的交接已被 `2026-07-15` 新流程取代：在安全检查点读取现存规格，补齐/更新测试用例，对未实现行为取得真实 RED 后交给 subagent 实现，再由同一需求既有代码 reviewer 会话复审。

`2026-07-10` 已按测试先行方式为 `complete-p0-horse-profile-data` 在 `server/stable/tests.py` 新增 RED 用例。覆盖暂无中文译名马名术语的识别/原文保留/校验阻断、五大地区重点赛事参赛马进入 P0 queue、非重点等级排除、完整资料硬门槛、在役马履历同步窗口、人工审核 artifact 幂等入库、完整后仍需人工首次发布、公开页不得触发 P0 同步/补全，以及无中文译名公开页使用原文并提示中文译名待补。本轮未实现产品代码，故未勾选 OpenSpec tasks；新增测试预期在实现前失败。当前本地仅完成 `python3 -m py_compile server/stable/tests.py` 与 `git diff --check`；Django 定向测试因当前可用 Python 环境缺少 `django` 依赖未能运行。

`2026-07-10` 已开始实现 `complete-p0-horse-profile-data` 的核心应用骨架。新增迁移 `stable.0027_p0_horse_profile_completion`：`TermEntry.translation_status` 支持无中文译名 horse term，`HorseProfile` 增加完整资料状态、赛马生涯状态、履历同步时间、完整资料审核人与自动化预留字段，新增 `HorseP0Source` 和 `HorseProfileCompletionRun`，并为 `HorseRaceRecord` 增加幂等键与 run 关联。新增 `stable.services.p0_horse_profiles`，实现本地新版 P0 来源同步、五地区重点赛事等级过滤、P0 队列预览、完整资料评估、已审核 artifact 幂等写入和人工 ready 标记；公开页仍不触网。术语解析/应用/发布校验已区分“有中文译名可替换”和“暂无中文译名需保留原文”，后台术语表单/CSV、马匹后台筛选、详情质量提示和前台无译名展示已更新；新增 `p0_horse_profiles` 管理命令。已在 `/tmp/umanews-p0-venv` 临时环境完成验证：`DB_ENGINE=sqlite manage.py check` 通过，`makemigrations --check --dry-run` 无变化，新增目标测试 `10` 项通过，旧 `HorseProfilePageMvpTests` `15` 项通过，`openspec validate complete-p0-horse-profile-data --strict`、`openspec validate --all`（20 项）和 `git diff --check` 均通过。当前尚未完成五地区真实 adapter 扩展、完整 dry-run artifact 写出、每地区 10 匹样本 dry-run、生产 commit 或人工公开验收。

`2026-07-10` P0 核心骨架完成第二轮审查返修。马匹自动身份合并改为依赖“来源命名空间 + 外部 horse ID”强身份键，名字和地区只用于候选检索；同名马强身份键不同可建立独立资料，既有同名资料缺强身份键时保留歧义并停止自动合并。P0 来源同步支持地区作用域，普通 `--sync-sources --commit` 只新增/刷新来源，只有显式 `--full-reconcile` 才撤销全地区失效来源；queue 支持重复 `--profile-id`。完整资料评估默认按 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1` 检查在役马履历，并以每模块最新审核结论为准，新冲突会撤销 `complete_profile_full`；退役马同步日期不得早于最新赛绩。已修复赛绩来源门禁不可达、待译马名被中文 alias 误放行、术语待译状态在控制台/API 缺失等问题。专项与旧马匹页回归共 `83` 项通过；完整 `stable` 从仓库根目录以 eager 模式运行 `538` 项，仅剩 `3` 个随当前日期漂移的既有 TDN France fixture 失败。尚未执行真实 adapter 扩展、五地区各 10 匹 dry-run、生产 commit 或公开验收。

`2026-07-10` 已根据代码审查和用户确认返修 P0 核心门禁。马匹地区不再参与身份唯一匹配，跨地区重点赛事复用全局唯一正式马名/alias，赛事地区只写 P0 来源且不覆盖 `HorseProfile.racing_region`；歧义身份不直接写主表。暂无中文译名 horse term 的原文保护跨地区生效，已有中文译名的歧义英文术语继续使用既有地区门禁。P0 全量同步会把本轮失效的术语/重点赛事来源标记为 `revoked` 并保留历史。完整资料现在阻止 `racing_career_status=unknown`，要求退役/在役履历同步标记、每条赛绩来源名与 URL、审核人/时间及基础资料/血统/赛事履历/主胜鞍四模块 applied 记录。artifact commit 改为顶层、行级、模块级三层审核，并区分旧赛绩接管、新增、修正和未变化；迁移为唯一旧赛绩回填幂等键，已有重复旧赛绩组转冲突且不会新增第三条，修正保存 before/after。目标与兼容测试 `20` 项、旧马匹页 `15` 项、`manage.py check`、迁移一致性、OpenSpec strict/all 和 `git diff --check` 通过。完整 `stable` 回归共 `526` 项，除 `3` 个使用 `2026-07-07` 固定发布时间、在当前日期已越过三天窗口的 TDN France 时效测试外均通过；这三个失败与本次 P0 改动无关，尚未在本专项修改。

`2026-07-11` 第三轮 P0 审查返修确立两层身份原则：来源命名空间内 external horse ID 直接定位来源身份；跨来源归并数据库已有马必须完整唯一命中经术语库多语种归一的“马名 + 父名 + 母名 + 出生年份”，`racing_region` 不参与唯一性。术语识别支持外文主名、中文译名和多语言 alias；同一原名对应多个 active horse term 时保留原文、禁止任选中文译名。队列按 `HorseProfile.racing_region` 每匹马只出现一次，人工来源和重点赛事证据优先；冲突审计覆盖旧 applied 结论，通用完整度刷新不再错误降级有效的 `complete_profile_full`。身份冲突的最终持久化与处理方案以紧随其后的第四轮记录为准。

`2026-07-11` 第四轮审查返修进一步修复五个身份与审核边界：同一赛事参赛记录改为优先按马号、其次按来源 external ID 分组，同名不同马号不再提前折叠；完整对账遇到参赛记录仍存在但 source URL 暂缺时保留既有 P0 来源，不误标 `revoked`；通用候选应用服务端只接受 `pending`，冲突/忽略/已应用记录不能通过直接 POST 变成 applied；人工 `complete_profile_full` 审核必须显式提供整匹马资料 URL，不能借用单场赛果 URL 给基础资料和血统背书。身份歧义采用专用 `HorseIdentityConflict`，支持无 profile 冲突、多个候选术语/资料页、赛事/马号/父母/出生年份/来源证据、pending/resolved/ignored、解决资料页、处理人和处理时间；`resolved` 必须选择最终资料页，下一次同步会按人工结论建立 P0 来源。每天 `09:20` 通知链接 Django Admin 待处理筛选。定向术语/P0/旧马匹页回归 `79` 项全部通过；完整 `stable` 回归 `556` 项仅有此前已知的 `3` 个固定日期 TDN France 时效 fixture 失败，本轮新增测试全部通过。`manage.py check`、迁移一致性、OpenSpec strict/all 和 `git diff --check` 均通过；尚未执行真实 adapter 扩展、五地区各 10 匹 dry-run、生产 commit 或公开验收。

`2026-07-11` 第五轮审查返修把同场参赛身份和赛绩幂等写入升级为长期结构。`HorseP0Source` 新增持久化 `participant_key`：同场优先按马号，其次按来源 external horse ID，最后仅在赛事内马名唯一时按规范化马名识别；runner/result 先按马号、外部 ID、唯一马名分阶段配对，字段不对称时不会把同一匹马拆成两条。同场同名但不同马号即使没有外部 ID 也建立不同来源与资料页，重复同步不增生；身份纠正时旧来源标记 `revoked`，新绑定另建 active 行，保留追加式审计。赛绩写入抽到共享 `horse_race_records.upsert_race_record()`，P0 artifact 与通用人工候选均强制生成幂等键、接管唯一旧记录、拒绝重复旧记录歧义，并要求 `source_name/source_url`。定向旧马匹页/P0 回归 `59` 项全部通过；完整 `stable` 回归 `560` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。`manage.py check`、迁移一致性和代码语法检查通过；真实五地区样本与生产步骤仍未执行。

`2026-07-12` 第六轮审查返修关闭三个剩余身份/赛绩入口缺口。参赛者从“只有 external ID”补到马号时，P0 同步会通过既有 `race_result`、`race_runner` 或来源 identity 找到旧 active 来源并迁移 `participant_key`，普通增量同步不会留下 identity/number 两条 active 记录；若新身份指向另一资料页则撤销旧绑定。runner/result 两边均有非空且不同马号时，即使 external ID 相同也禁止自动配对，保存 `HorseIdentityConflict.evidence_payload.pairing_conflict` 后停止写 P0 来源。后台手工新增与编辑赛绩也统一调用 `upsert_race_record()`：新增重复记录不增生，编辑自然键后重新生成幂等键，命中另一记录时拒绝覆盖，来源 URL 在表单与服务两层必填。定向旧马匹页/P0 回归 `63` 项通过；完整 `stable` 回归 `564` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败，本轮新增测试全部通过。并发相同赛绩写入仍按用户决定不在本轮处理。

`2026-07-12` 第七轮审查返修补齐同类型参赛记录、来源证据和新鲜度口径。P0 participant 构建完成后会按同一来源 identity 汇总全部 runner/result；同一 identity 对应多个非空马号时，不论是 runner-result、两条 runner 或两条 result，均合并为一条 `HorseIdentityConflict`，证据保存全部马号与记录 ID，且不生成 active P0 来源。后台编辑既有赛绩时只更新表单事实字段和幂等键，保留 importer 原有 `source_refs/raw_payload`，before/after diff 写入操作日志；只有手工新建才初始化 manual console 证据。新增 `active_record_freshness_cutoff()` 统一完整度与后台“在役待刷新”筛选，默认 1 天时昨天仍为新鲜、前天才待刷新。定向旧马匹页/P0 回归 `67` 项通过；完整 `stable` 回归 `568` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败，本轮新增测试全部通过。

`2026-07-12` 第八轮审查返修完善马号冲突解决与 external-ID 赛绩稳定性。`HorseIdentityConflict` 新增 `resolved_horse_number`：含 `pairing_conflict` 的记录只有同时选择最终资料页和证据内候选马号才允许 resolved，后续同步只绑定该马号对应的 runner/result；选中记录缺可复核 URL 时仍不写 active 来源。冲突 evidence 现在保存全部成员的马号、名称、runner/result ID 和 source URL；任意成员有 URL 时用于冲突复核，全部无 URL 时冲突仍落库并计入缺 URL。fingerprint 只使用稳定身份字段，后补 URL 不会生成重复冲突。后台编辑 imported 赛绩时从既有 `raw_payload/source_refs` 继承 external race/result ID，并沿用原 source namespace 生成幂等键，编辑名称后 importer 重跑仍只保留一条记录。定向旧马匹页/P0 回归 `69` 项通过；完整 `stable` 回归 `570` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败，本轮新增测试全部通过。

`2026-07-12` 第九轮审查返修补齐三个数据完整性边界。`stable.0027` 的旧赛绩幂等键回填同时读取 `raw_payload` 与 `source_refs` 中的 external race/result ID，避免迁移后 importer 以另一种键重复建档；同一赛事内共享任一来源身份键的参赛记录先按连通组整体归并，交叉身份键不再覆盖或丢失冲突成员；马号冲突 resolved 前要求所选成员或赛事具备来源 URL，若 URL 后续消失或绕过表单写入，下一次同步会清除无效解决结论、恢复 pending 并记录 `resolution_failure`，继续进入每日管理员通知。术语解析/旧马匹页/P0 定向回归 `96` 项通过；完整 `stable` 回归 `573` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败。尚未部署或执行五地区样本补全。

`2026-07-12` 第十轮审查返修修复三处持续运行风险。人工 `HorseP0Source` 改为按 `profile + source_type=manual` 独立 upsert，并增加条件唯一约束，多匹马依次审核不再互相撤销来源；马号冲突的所选成员无法在本轮证据中定位时，与缺 URL 使用同一恢复函数，清空无效人工结论、恢复 pending 并记录 `resolved_member_missing`；旧空键赛绩在自然字段匹配前优先扫描 `raw_payload/source_refs` external identity，同一来源 external ID 命中多条时直接报告歧义，禁止 importer 新增第三条。术语解析/旧马匹页/P0 定向回归 `99` 项通过；完整 `stable` 回归 `576` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败。尚未部署。

`2026-07-12` 按用户要求继续执行“审查 -> 修复 -> 复验”循环，直至第五轮纯审查无可操作发现。旧赛绩迁移与运行期现在从 `record.source_name` 或 `raw_payload/source_refs` 的 `source/source_name/provider/adapter` 推导有效来源命名空间，来源身份统一去空格并 `casefold()`，external ID 统一字符串化并去首尾空格；来源名只存在证据中的旧记录可被唯一接管，同 external identity 多条旧记录在 importer 和后台编辑路径都会阻断写入。P0 队列不再按完整度字符串排序，而使用明确资料缺口等级；同等级再综合人工标记、待处理候选、近 30 天已发布新闻、重点赛事证据、非空外部身份和术语优先级，并把在役过期、退役同步落后和未知生涯状态的 full profile 放入刷新层。OpenSpec `3.4` 在排序信号补齐后保持完成，尚无五地区 adapter/artifact 完整测试的 `6.2` 已恢复未完成。最终术语解析/旧马匹页/P0 定向回归 `104` 项通过；完整 `stable` 回归 `581` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败；Django check、迁移一致性、OpenSpec strict/all 和 `git diff --check` 通过。尚未提交或部署。

`2026-07-08` 已完成马匹详情页 MVP 线上浏览器验收。本次先尝试 Codex 内置浏览器访问生产页，但两次打开 `http://umafans.run/horses/` 超时；随后使用系统 Chrome headless 生成真实桌面/移动截图与 CDP 布局指标，截图保存在本地 `/tmp/umanews-horse-acceptance/`。公网复核显示 `http://umafans.run/healthz/`、`/horses/`、`/horses/follows/` 均返回 `200`，草稿样例 `/horses/1/` 返回 `404`，未登录 `/admin/horse-profiles/` 返回 `302` 到登录页，符合“P0 马默认草稿、后台审核后才公开”的策略。Chrome 验收确认桌面 `/horses/`、移动 `/horses/`、移动首页和移动草稿 404 页没有页面级横向溢出，导航 DOM 中包含“马匹”和“我的关注”；`/horses/?q=test&region=japan` 保留搜索词并正确激活日本筛选。已发现两个体验问题：`/horses/` 空状态文案仍显示“目前还没有已发布文章。”，语义应改为马匹资料；移动端顶部导航和地区筛选依赖横向滑动，功能可用但“马匹 / 我的关注”和最右侧“美国”不够显眼。因生产当前 `published=0`，未发布任何马匹详情，故无法在不改生产数据的前提下完整验收已发布详情页、关注按钮 POST、新闻详情马匹 tag 和关注新闻流；staff 后台列表/详情也因没有登录态仅验收到未登录跳转。UmaNews 生产 SSH 只以 `root@47.239.167.86` 为准，不使用其他项目服务器。

`2026-07-07` OpenSpec change `hkjc-ja-alias-article-backfill` 已完成实现并部署生产。新增 `stable.services.term_maintenance`、`merge_hkjc_ja_aliases` 和 `backfill_article_terms`，用于处理 HKJC 日本马日语 alias 概念合并，以及已发布文章中文字段的术语精确回填。概念合并默认 dry-run 输出 `merge_plan.json` / review CSV / summary，正式写入必须使用已审核 `--plan-file`；apply 会重新校验 active owner 占用，只合并同类型、同中文目标、active 日语主术语的安全项，并将冗余日语主术语停用，notes 中记录 `hkjc_ja_alias_merged_into_term_id=<target>`。这也是术语库中一部分 inactive 术语的合理来源：它们不是删除，而是被更完整的正式概念吸收后的历史主术语。文章回填默认只扫描已发布文章，输出完整 before/after JSON 与人工 review CSV；正式写入必须使用已审核 `--diff-file`，或显式提供 term/article/date/source/limit 过滤范围，且默认跳过 `manually_edited_fields` 中的发布字段，不重新翻译、不调用 AI 改写、不改变发布、审核、workflow 或 QQ 推送状态。本地验证已通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（最终 `473` 项）、`openspec validate hkjc-ja-alias-article-backfill --strict` 和 `git diff --check`。生产服务器 `/opt/umanewsbot` 已部署到 `a65c1ed`；部署前备份 `.env` 为 `.env.backup.hkjc-ja-alias-backfill-20260707_184118`，数据库备份为 `backups/db/pre-hkjc-ja-alias-backfill-20260707_184118.sql.gz` 且 `gzip -t` 通过。生产 HKJC alias dry-run 为 `candidate=112 skipped=0`，正式 apply 写入 `112` 条日语 alias 并停用 `112` 条冗余日语主术语；post-apply smoke 为 `candidate=0 scanned=0`。文章回填 dry-run 扫描 `713` 篇日文已发布文章，命中 `7` 篇，计划更新 `29` 个字段、跳过 `2` 个人工字段；正式 apply 为 `updated=29 skipped=2 stale=0`。artifact 已复制到生产宿主机 `runtime/term_backfills/hkjc-ja-article-backfill-20260707_192910/`、`runtime/term_backfills/hkjc-ja-article-backfill-apply-20260707_192931/`、`runtime/term_backfills/hkjc-ja-alias-merge-postapply-smoke-20260707_192810/`。抽检确认 `Kalamatianos / カラマティアノス -> 欢快舞步` 为日本地区 active term `6443` 的 active EN/JA alias，`/news/7117/` 返回 `200` 且页面包含 `欢快舞步`；生产 `manage.py check`、本地和公网 `/healthz/` 均通过。

`2026-07-07` 本地已实现并准备上线 OpenSpec change `expand-france-news-sources`。该变更为法国新增 `tdn_france_broad` 英文补充来源：使用 TDN 公开 WordPress 搜索 API 聚合 `French racing`、`ParisLongchamp`、`Deauville`、`Chantilly` 等关键词，`canonical_source_site=tdn`，通过 URL / source_article_id 复用既有 TDN 去重，默认 `enabled=false`、`production_approved=false`，需灰度启用后才进入生产抓取。真实只读探测显示 `tdn_france_broad` accepted：HTTP `200`、列表 `20` 条、详情样本 `2` 条、最大正文长度 `12735`、重复数 `0`；`at_the_races_france` 当前仍因 HTTP `403 / Client Challenge` 标记为 deferred/access_limited，不生产批准。探测命令已输出 `status/deferred_reason/http_status/final_url/parse_quality/duplicate_ratio/query_errors/sample_errors`，并支持多关键词来源在部分关键词失败时记录 `query_errors`、单篇详情样本失败时记录 `detail_error_count` 后继续采样后续文章；国际新闻来源生产抓取已改为“单篇详情解析失败则跳过并继续处理其他文章，全部详情都失败才将来源标记为 failed”，避免一篇坏详情拖垮整轮来源或把全失败伪装成无新稿。来源同步新增 `MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES=ja,en,zh-hant` 保护，法语源即使误配置 production approved 也会降级为未批准并写 `source_language_not_supported`；法国审计摘要可区分成功无新增、解析失败来源 ID、门禁 blocker 和示例文章。

`2026-07-07` 本地已实现并准备上线 OpenSpec change `fix-english-term-gate-region-filter`。该变更针对香港、英国、美国等英文新闻被 `core_term_missing` 大量误挡的问题：英文发布校验第一版只检查文章同地区术语和 `racing_region=""` 全局术语；`class/content/link/agent/oaks/america/numbers` 等配置化高歧义英文词会降级为 warning，不再默认生成硬 blocker；未配置的短词 / 全大写词只有在非核心命中时才会派生降级，真正同地区 / 全局高可信核心马名、赛事名等缺失仍会阻断自动发布。新增 `reprocess_term_gate_blocked_articles` 管理命令，可对最近发布候选回看窗口内、因术语 blocker 进入人工审核的文章执行 dry-run 或 commit 重校验，commit 只会重新进入 `publish_ready` 候选并写 `ranked_revived_at`，不会直接公开发布文章。生产审计摘要已增加 `articles.gate_issues`，用于区分真实 blocker、高歧义降级和地区排除。上线后需只读验证香港、英国、美国最近窗口的 `core_term_missing` blocker、`publish_ready` 和公开数量。

`2026-07-07` OpenSpec changes `expand-france-news-sources` 与 `fix-english-term-gate-region-filter` 已部署生产。生产因 GitHub HTTPS 连接超时，改用本地 `git bundle` 将提交 `bfc3445` 传入 `/opt/umanewsbot` 并 fast-forward 部署；部署前数据库备份为 `backups/db/pre-france-source-term-gate-20260707_200124.sql.gz`，已执行 `gzip -t`。部署后 `web / worker / beat / db / redis / nginx` 正常，`manage.py check` 通过，本地与公网 `/healthz/` 均返回 `200`。`tdn_france_broad` 生产只读探测 accepted：HTTP `200`、列表 `20` 条、详情样本 `5` 条、详情错误 `0`、重复 `0`；已在生产启用 `NewsSource#21`，设置 `enabled=true`、`production_approved=true`、`effective_crawl_interval_minutes=15`，并把 `tdn_france:access` 与 canonical 入库后的 `tdn:access` 加入 `MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES`。真实人工抓取验证因中途补生产配置重启被打断，已入库法国新来源文章 `7250-7253` 共 `4` 篇；中断的人工 `CrawlJob#9330` 已标记为 failed 并记录 `success_count=4`，错误说明为部署配置重启中断，不代表来源失败。4 篇均已补翻译并重新跑自动化，当前均为 `manual_review_required / pending_review`：其中 `7250-7252` 因真实 `core_term_missing` blocker 转人工，`7253` 因总分 `69` 转人工。最终审计文件位于生产容器 `runtime/multiregion_audit/post-france-source-term-gate-final-20260707_202851.json`：法国来源总数 `4`、启用 `3`、生产批准 `3`、paused/backoff 均为 `0`，今日法国新入库 `4`、公开 `0`，公开为 0 的原因是正常门禁转人工而非抓取或来源白名单失败。英文门禁重处理 dry-run：香港、美国、法国最近 3 小时无可释放 `core_term_missing` 候选；英国有 `1` 篇候选但仍被真实核心术语缺失阻断，未执行 commit。

`2026-07-07 21:00` 线上回归复核：生产仓库 `HEAD=dcb9b90`，容器运行正常，`manage.py check`、本地/公网 `/healthz/`、首页和 `/admin/login/` 均通过；生产开关 `MULTIREGION_PRODUCTION_WINDOWS_*`、`NEWS_SOURCE_POLL_ENABLED` 均为开启，`tdn:access` 与 `tdn_france:access` 均在自动发布来源白名单中。法国新来源 `tdn_france_broad` 再次只读探测 accepted，HTTP `200`、列表 `20`、详情样本 `2`、详情错误 `0`，重复率 `0.5` 是因为自然抓取已写入同批文章。自然窗口已派发 `CrawlJob#9355`，截至复核时仍为 `started`，但已通过 `source_config=21` 入库 `10` 篇法国文章，其中 `9` 篇已翻译、`1` 篇翻译中；Celery active 显示该 crawl task 正在 worker 内运行，worker 日志持续出现 SiliconFlow `200 OK`，因此判断为“单轮处理耗时偏长但仍在推进”，不是来源不可用。最近 90 分钟五地区发布/QQ 窗口均为 succeeded，0 结果均有 `no_ready_candidates / no_eligible_articles / already_sent` 等原因；英文门禁 dry-run 复核为香港/美国无候选、英国 `7242` 仍真实 blocker、法国 `7250/7251/7252` 仍真实 blocker，无可释放误挡文章。

`2026-07-07` 发现法国新来源 `tdn_france_broad` 抓入历史旧文并有旧文自动发布。根因是 TDN `/wp-json/wp/v2/search?search=French%20racing` 返回按相关性排序的历史搜索结果，search item 只有 `id/title/url`，没有 `date/date_gmt`；当前 adapter 复用 `TDNAdapter._api_datetime()`，在缺少日期时兜底为 `timezone.now()`，而详情页解析也未纠正为真实发布时间，导致 2020/2022/2023/2024 旧文被写成 `2026-07-07T14:05:04Z` 并进入发布窗口。已立即暂停生产 `NewsSource#21`：`enabled=false`、`production_approved=false`，`manual_pause_reason=paused 2026-07-07: TDN search endpoint returned historical articles without dates; old articles were stamped as current`。已确认公开受影响旧文包括：`7255` 实际 `2022-03-21`，`7263` 实际 `2020-04-07`，`7264` 实际 `2020-03-16`，`7265` 实际 `2020-03-13`，`7271` 实际 `2024-11-08`。后续修复应改为从 search item 的 `_links.self` / post `id` 二次读取 `/wp-json/wp/v2/posts/<id>` 的真实 `date_gmt`，并在 adapter 或生产抓取层丢弃超过允许新鲜度窗口的文章；修复前不要重新启用该来源。

`2026-07-04` OpenSpec change `race-event-page-mvp` 已按已确认 Stitch 原型完成赛事日历 / 年度赛事详情页 MVP，并已部署生产。新增 `RaceEvent` 产品层模型、别名、出马表、赛果、历史冠军、候选资料和 `ArticleRaceLink`；公开入口为 `/races/` 与 `/races/<year>/<slug>/`，文章详情页会展示已确认关联赛事；业务后台新增 `/admin/race-events/`，支持赛事列表筛选、详情维护、候选资料应用、手动关联/移除新闻和人工移除保护。管理命令新增 `import_race_events`、`fetch_race_event_candidates` 和 `research_live_race_fields`，样例 CSV 位于 `server/stable/data/race_events_seed_sample.csv`。本地 code review 后已修复后台赛事列表筛选翻页丢参问题，并补充回归测试。生产服务器 `/opt/umanewsbot` 已部署提交 `f3c4c46`，迁移 `stable.0020_raceevent_articleracelink_raceeventalias_and_more` 已应用；已正式导入 5 条 P0/P1 赛事种子和 10 条别名，当前 `ArticleRaceLink=0`，后续新闻关联仍需自动匹配或人工维护。第一版不建设马匹数据库、完整赛果库、复杂赛事聚类或赛中实时进度。

`2026-07-04` 本次赛事日历 / HKJC overseas 术语种子上线前，本地验证已通过 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable --noinput`（442 项）、`openspec validate --all`（17 项）和 `git diff --check`。生产部署前确认没有正在运行的外部数据导入和导入锁；备份 `.env` 为 `.env.backup.race-calendar-hkjc-overseas-20260704_182412`，数据库有效备份为 `backups/db/rds_horse_news_race_calendar_manual_20260704_182458.sql.gz` 并通过 `gzip -t`。部署后 `manage.py check` 通过，`showmigrations stable` 显示 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`，`web / worker / beat / db / redis / nginx` 均运行，`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/` 和 `/admin/login/` 均返回 `200`，未登录 `/admin/race-events/` 返回 `302` 到登录链路。生产容器内 HKJC overseas fixture smoke 生成 `candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`，输出目录为 `runtime/termbase_seed/hkjc-overseas-deploy-smoke-20260704_183048`；本次未把 HKJC overseas 候选导入正式术语库。

`2026-07-06` 已按“赛事日历正式填充前先线上验收、再给示例审核”的节奏完成第一步。生产 `/opt/umanewsbot` 当前 `HEAD=c996621`，`web` healthy，`worker / beat / db / redis / nginx` 正常；公网 `umafans.run/healthz/`、`/races/` 与 `/admin/login/` 均返回 `200`，`manage.py check` 通过，`stable.0020_raceevent_articleracelink_raceeventalias_and_more` 已应用。生产当前赛事模块计数为 `RaceEvent=5`、`RaceEventAlias=10`、`RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventDataCandidate=0`、`ArticleRaceLink=0`，五地区各 1 条样例赛事，`ExternalDataImportRun(status="started")=0` 且导入锁为空。已从 JAIRS/JRA 官方英文页抓取 `2025 Japan Cup` 赛后样例审核包，路径为 `runtime/race_event_review_samples/japan-cup-2025-20260706/`，包含 `race_events_sample.csv`、`race_event_candidate_payload.json`、`source_official.html` 和 `README.md`；该样例为日本 G1、非 listed、非地区重赏，解析出基础资料 1 组、出走表 17 匹、正式完赛赛果 16 条。`import_race_events --dry-run` 对该 CSV 通过，候选 JSON 通过 JSON 校验。本次未写生产库；示例中 `visibility_status=draft`，且术语库/官方中文未命中 `Japan Cup` 与 `Tokyo Racecourse` 时按约定保留原文，等待人工审核补全。

`2026-07-06` 赛事日历正式填充已开始写生产库。按用户要求优先使用本地语言官方源：日本批次改用 JRA 日文重赏一覧 `https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`，生成并导入 `runtime/race_event_imports/2026/japan-jra-central-graded-20260706/race_events_japan_jra_2026.csv`；范围为 2026 年 JRA 中央 G1/G2/G3/J-G1/J-G2/J-G3，不含 Listed/Open 和地方交流重赏，生产导入结果为 `created=139 updated=1 aliases=413`，其中 `宝塚記念` 更新原样例 `takarazuka-kinen`，当前 `japan/year=2026` 共 `140` 场，状态分布 `finished=74`、`scheduled=66`。香港批次使用 HKJC 繁中官方源 `https://racing.hkjc.com/zh-hk/international-racing/g2-g3-races/index` 与 `https://campaigns.hkjc.com/racing-event-hub/ch/`，并用 HKJC 本地赛果页补马场、距离和场地，生成并导入 `runtime/race_event_imports/2026/hong-kong-hkjc-pattern-20260706/race_events_hong_kong_hkjc_2026.csv`；范围为 HKJC 当前公开 2025/26 马季内日期落在 2026 年的香港 G1/G2/G3，共 `19` 场，已过滤非单场赛事卡片 `沙田煞科日`，不猜测尚未由 HKJC 公开 2026/27 日期的 2026 年末香港国际赛。香港导入结果为 `created=19 updated=0 aliases=74`；生产当前 `RaceEvent=163`、`RaceEventAlias=497`、香港 2026 共 `20` 条，其中 `19` 条为本批 HKJC 官方源，另 `1` 条为既有香港杯样例。日本与香港详情页均已通过公网 Host 验收；香港默认重点日历页因只显示当前前后 30 天且过滤 P2，需用 `tab=all` 或 `direction=past` 查看本批历史赛事。

`2026-07-06` 继续补齐 2026 目标地区重要赛事并写入生产。日本地方/交流ダートグレード使用 NAR 官方 `https://www.keiba.go.jp/dirtgraderace/2026/racelist/index.html` 与官方 PDF `https://www.keiba.go.jp/pdf/uploads/20251110_01_01.pdf`，导入地方竞马场 JpnⅠ/JpnⅡ/JpnⅢ 与大井东京大赏典 GⅠ 共 `46` 场，结果 `created=46 updated=0 aliases=105`；其中 `22` 场官方给出发走时刻，`24` 场日期确定但时刻待定，前台详情页已验证帝王赏显示 `20:05`、东京大赏典显示“待定”。为支持美国 all-weather/synthetic 赛事，已新增 `RaceEventSurface.SYNTHETIC=synthetic/复合赛道` 并部署生产 `9dc9b4d`，迁移 `stable.0021_alter_raceevent_surface` 已应用。美国使用 TOBA 官方 `https://toba.org/graded-stakes/2026-races/`，导入 2026 American Graded Stakes 表内 Grade 1/2/3 共 `411` 条，结果 `created=411 updated=0 aliases=1550`；其中 `370` 条有日期并公开展示，`41` 条空日期或 `not run` 作为 draft 底表记录保留，Listed `200` 条与其他非分级黑体 `12` 条已排除，Jeff Ruby Steaks 已验证显示“复合赛道”。英国当前可靠导入 BHA Jump 官方 `British_Jump_Pattern_Listed_2526.pdf` 中 2026 年 1-4 月 Grade 1/2 共 `64` 场，结果 `created=64 updated=0 aliases=192`；英国 Flat 官方 2026 PDF 正文页文字层为空，仍需 OCR 或另一官方结构化源；Jump 2026 年 10-12 月需等待 2026/27 官方书或其他官方源。法国使用 France Galop 官方 `groupes_listed_plat_2026_v7.pdf` 与 `groupes_listed_obstacles_2026_v4.pdf`，按逐赛条件页导入 Groupe I/II/III 共 `173` 条，结果 `created=173 updated=0 aliases=519`，其中 Flat `113`、障碍 `60`，Listed 已排除；Prix Ganay 与 Grand Steeple-Chase de Paris 详情页已验证。生产当前 `RaceEvent=857`、`RaceEventAlias=2863`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `65`、法国 `174`。剩余缺口主要是香港 2026 年末 HKJC 尚未公开赛期、英国 Flat 2026 官方 PDF 需要 OCR/结构化替代源、英国 Jump 2026 年 10-12 月官方赛季书未确认。

`2026-07-06` 已继续补上英国 Flat Group 赛事。BHA 官方 `British_Flat_Pattern_Listed_2026.pdf` 正文页无可用文本层，本次使用 macOS Vision OCR 识别官方详情页，生成 `runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/race_events_united_kingdom_bha_flat_2026.csv`；范围为英国 2026 Flat `Group 1/2/3`，排除 Listed，共 `138` 场，等级分布 `G1=33`、`G2=42`、`G3=63`，其中 `59` 场按当前日期归为 `finished`、`79` 场为 `scheduled`，复合赛道 `6` 场、草地 `132` 场。距离字段来自 OCR，已对明显残缺值做清理并保留 `data_quality_status=partial`；赛事名、日期、场地和等级来自官方详情页。生产导入前备份为 `backups/db/pre-race-events-uk-bha-flat-2026-20260706_222151.sql.gz`，约 `74M`，`gzip -t` 通过；生产 dry-run 通过后正式导入 `created=138 updated=0 aliases=414`。导入后生产 `RaceEvent=995`、`RaceEventAlias=3277`，2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`；英国 Flat 页面验收 `/races/2026/uk-bha-flat-2026-0704-058/` 显示 `CORAL-ECLIPSE`，复合赛道样例 `/races/2026/uk-bha-flat-2026-0905-102/` 显示 `UNIBET SEPTEMBER STAKES` 与“复合赛道”。当前剩余缺口收敛为：HKJC 尚未公开 2026/27 马季年末香港本地 G1/G2/G3 日期明细；英国 Jump 2026 年 10-12 月需等待 2026/27 官方书或其他官方结构化来源。

`2026-07-06` 已开始正式填充 2026 赛事详情表，第一批完成 JRA 中央重赏已完赛场次的出走表和赛果。官方来源继续使用 JRA 日文重赏列表和各赛事结果页，产物位于 `runtime/race_event_detail_imports/2026/japan-jra-details-20260706/`，包括 `jra_detail_candidates_2026.jsonl`、`jra_detail_review_2026.csv`、`summary.json` 与页面缓存；生成结果为 `74` 场、`1112` 条出走表、`1106` 条数字名次赛果，另有 `取消=2`、`除外=2`、`中止=2` 保留在出走表状态中。生产写入前备份为 `backups/db/pre-race-event-details-jra-2026-20260706_224953.sql.gz`，约 `75M` 且 `gzip -t` 通过；生产 dry-run 确认 `events=74`、`runners=1112`、`results=1106` 后正式应用 `148` 个候选模块。第一次 apply 因 JRA 同着导致 `finish_position` 唯一约束冲突而中止，已将失败留下的 `1` 条旧 pending 候选标记为 `failed`；修正后用唯一排序位写入 `finish_position`，并在 `source_refs.official_finish_position` 保留 JRA 官方名次。导入后生产 `RaceEventRunner=1112`、`RaceEventResult=1106`、`RaceEventDataCandidate=192`、`AppliedCandidates=191`、`FailedCandidates=1`；宝塚記念详情页显示 `メイショウタバル`、出走表和赛果，安田記念同着马 `ワールズエンド` 与 `ガイアフォース` 前台均显示官方第 `2` 名。为让同着展示立即正确，已将 `views.py` 和两个公开模板热补丁复制进 `web` 容器并重启，同步本地代码已保留但尚未通过 git 镜像部署固化；后续正式部署或容器重建前必须先提交/部署该展示修复，避免热补丁丢失。

`2026-07-06` 已继续补齐日本 NAR/地方交流重赏当前官方可用详情。NAR 使用 `keiba.go.jp` ダートグレード特设页的 `racecard.html` 自动发现 `KeibaWeb/TodayRaceInfo/DebaTable`，已完赛赛事再跳转 `RaceMarkTable`；产物位于 `runtime/race_event_detail_imports/2026/japan-nar-details-20260706/`，包括 `nar_detail_candidates_2026.jsonl`、`nar_detail_review_2026.csv`、`summary.json` 与页面缓存。生成结果为 `21` 场、`256` 条出走表、`242` 条数字名次赛果；其中 `20` 场已完赛写入出走表和赛果，`2026-07-08` スパーキングレディーカップ已公布出走表但未有赛果，仅写入赛前出走表；后续 `25` 场仍停留在 `introduction.html` 且官方未公布出走表，记录为 `racecard_not_published`。生产写入前备份为 `backups/db/pre-race-event-details-nar-2026-20260706_232856.sql.gz`，约 `75M` 且 `gzip -t` 通过；dry-run 确认 `events=21`、`runners=256`、`results=242` 后正式应用 `41` 个候选模块。导入后生产详情表为 `RaceEventRunner=1368`、`RaceEventResult=1348`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=233`、`AppliedCandidates=232`、`FailedCandidates=1`，全部详情行当前仍为日本地区。页面验收：`/races/2026/nar-dirt-2026-0701-20/` 显示帝王賞冠军 `ミッキーファイト`、出走表、赛果和 `2:02.8`；`/races/2026/nar-dirt-2026-0708-21/` 显示スパーキングレディーカップ出走表和 `レクランスリール / アピーリングルック`，未显示赛果区块。当前按用户指定顺序，日本 JRA/NAR 中“官方已公布的出走表/赛果”已补完；JRA 未来 66 场和 NAR 未来 25 场需等官方出走表或赛果发布后刷新。

`2026-07-06/07` 已继续补香港与美国 2026 已完赛重赏详情。香港使用 HKJC 繁中官方 `resultsall` 日汇总页定位 RaceNo，再进入单场 `localresults` 完整赛果页；产物位于 `runtime/race_event_detail_imports/2026/hong-kong-hkjc-details-20260706/`。生成并导入 HKJC 已公开 2026 本地 G1/G2/G3 `19` 场、`182` 条出走表、`181` 条数字名次赛果；`WV` 保留为 `withdrawn` 出走状态但不写赛果，马名/骑师/练马师展示字段已从繁中转简体，原始繁中保存在 `source_refs`。生产写入前备份为 `backups/db/pre-race-event-details-hk-2026-20260706_234317.sql.gz`，约 `75M` 且 `gzip -t` 通过；dry-run 通过后正式应用 `38` 个候选模块。页面验收：`/races/2026/hkjc-2026-0125-05/` 显示董事杯冠军 `浪漫勇士`、完整出走表和赛果，`祝愿 / 阳光勇士` 同为官方第 `4` 名且时间 `1:33.18`；`/races/2026/hkjc-2026-0621-19/` 显示精英碟出走表中 `非惟侥幸` 为取消出走，赛果只保留 `11` 条已确认名次。

美国使用 TOBA 官方分级赛表确定 2026 已完赛范围，并以 TOBA `chart_url` 中的官方 RaceNo 辅助匹配 Horse Racing Nation track-day 页面；Equibase chart HTML/PDF 当前仍返回防护页，因此 HRN 仅作为可访问公开结果源。产物位于 `runtime/race_event_detail_imports/2026/united-states-hrn-details-20260706/`。生成并导入美国 TOBA Grade 1/2/3 已完赛 `195` 场、`1710` 条出走表、`1448` 条可确认赛果；马名展示字段已剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。HRN 对 Kentucky Derby / Kentucky Oaks 等少量大赛页当前只公开出走表、不公开 payout/also-rans 结果块，本批不从 TOBA winner 字段猜完整名次，因此这些赛事可显示出走表但暂无赛果。首次 apply 因 HRN HTML 重复渲染同一出走马导致唯一马号冲突中止，已将旧 pending 候选标记为 failed，并在生成器中按 `horse_number + horse_name + horse_url` 去重后重跑成功。生产写入前备份为 `backups/db/pre-race-event-details-us-hrn-2026-20260707_000230.sql.gz`，约 `75M` 且 `gzip -t` 通过；最终正式应用 `390` 个候选模块。导入后生产详情表为 `RaceEventRunner=3260`、`RaceEventResult=2977`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=992`、`AppliedCandidates=990`、`FailedCandidates=2`、`PendingCandidates=0`；其中美国详情为 `1710` 条出走表和 `1448` 条赛果。页面验收：`/races/2026/us-toba-2026-0108-001/` 显示 Robert J. Frankel S. 冠军 `Paradise Lake`、出走表和赛果；`/races/2026/us-toba-2026-0502-119/` 显示 Kentucky Derby 出走表但因 HRN 未公开结果块暂不显示赛果。当前顺序进度为日本、香港、美国已完成当前可用详情，下一步继续英国、法国，再处理历届冠军。

`2026-06-27` 全球赛马数据库接入当前处于能力确认完成状态：香港 HKJC 已有生产真实 dry-run 批次证据，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 已完成少量真实 proof，证明四地公开入口、parser/importer、马匹详情链路、低频限量抓取和 proof-only 离线审计可用。用户已将本目标完成口径调整为“先保证所有地区的数据爬取能力真实可用”，不再要求本目标内完成最近 2 个月完整大量爬取或生产真实网络 commit。当前主工作树已同步外部缓存底座、HKJC、UK/France/US importer、fixtures、OpenSpec 归档和 proof JSON，用于后续恢复；这些同步内容仍是未提交工作树差异。交接索引见 `docs/global_racing_database_handoff.md`。

同步后本地验证已覆盖 Django check、外部缓存底座、HKJC、UK/France/US importer、global racing isolation、proof-only 离线审计测试、OpenSpec 全量校验和 `git diff --check`；离线 commit 候选审计已加严为要求 plan-only 具备请求证据和成功响应，非 plan 批次具备请求证据、成功响应和非空 `races/entries/results/horses` coverage；四地 importer 的生产写库门禁已加严为只有 `completion.is_complete=true` 的严格布尔完成证明、completion 内部无受限停止或马匹详情缺口、completion 内含可解析 `unique_horses_found` / `horse_profiles_fetched` 计数、且 payload 具备非空 `races/entries/results/horses` coverage 时才允许 commit。HKJC、UK、France Geny、US 的 plan-only 命令均要求显式 `--allow-network`，避免误把最近 60 天拆批计划当成本地无网络操作；新增 `render_global_racing_batch_command` 只读命令，可从 plan JSON 渲染指定批次或全部批次的精确 dry-run/commit 命令，并可根据 `--output-dir` 给出稳定 `suggested_output_path` 和可直接执行的 `tee_command_line`，减少手工复制 `race_ids`、`race_urls` 或 `partants_urls` 以及覆盖批次 JSON 的风险，离线审计会忽略这类命令清单 artifact。详见 `docs/global_racing_database_handoff.md`。当前同步范围清单见 `docs/global_racing_sync_manifest.md`。

`2026-07-03` 生产只读核对多地区术语库与外部马名索引：服务器 `/opt/umanewsbot` 当前 `HEAD=4323d32`，`web/worker/beat/db/redis/nginx` 均在运行。正式术语库 `TermEntry=2054`，全部为 `source_language=ja`，其中 `horse=1884`、`race=153`、`fixed_phrase=15`、`jockey=2`，`TermAlias=2057` 也全部为日文；正式术语的 `racing_region` 仍为空，尚未形成香港、英国、法国、美国分地区正式术语内容。术语候选池 `TermCandidate=3519`、证据 `13725`，当前同样全部为日文候选。外部马名索引 `ExternalHorseAlias=12425`，其中日本 `netkeiba/ja=12421`；香港 HKJC 只有小样本 `en=2`、`zh-hant=2`。外部缓存表中日本仍是主体：`ExternalHorse=12405`、`ExternalRace=4099`、`ExternalRaceEntry=60838`、`ExternalRaceResult=56882`；香港仅有 sample commit 级别的 `ExternalHorse=2`、`ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`；英国、法国、美国当前生产 `External*` 表无写入。结论：多地区新闻源与语言/地区处理链路已上线，但正式术语内容和外部马名识别数据厚度仍明显以日本为主，英法美仍停在 proof/代码能力而非生产数据沉淀。

`2026-07-04` OpenSpec change `prepare-termbase-seed-data` 已完成实现、验证和归档，归档目录为 `openspec/changes/archive/2026-07-03-prepare-termbase-seed-data`，正式规格已同步到 `openspec/specs/termbase-seed-data-preparation/spec.md`，并在 `openspec/specs/termbase-and-race-priority/spec.md` 追加“术语种子候选兼容正式术语导入”要求。本地首版已实现 `prepare_termbase_seed_data` 管理命令与 `stable.services.termbase_seed` 服务层，可从 HKJC/WP Stud fixture 或低频触网入口生成 `seed_candidates.csv`、`seed_conflicts.csv` 和 `summary.json`；内置 fixture smoke 生成 `10` 条候选与 `1` 条冲突，香港候选优先、日本候选最后，中文目标译名经 OpenCC 简体化。该能力边界是从 HKJC 体系和 WP Stud 准备第一批人工审核 CSV：`seed_candidates.csv` 严格兼容现有 `import_terms` 字段，`seed_conflicts.csv` 记录译名冲突；第一版不直接写生产 `TermEntry`、不触发翻译、发布或 QQ 推送。审查后已明确首版不做 HKJC `racecards` PDF/排位表全量抽取，必须先做 HKJC/WP Stud source discovery，默认输出到 `runtime/termbase_seed/<timestamp>/`，并要求网络失败摘要、繁简转换依赖落地和后台术语导入模板同步更新。代码审查修复已将命令内置 dry-run 预检调整为与 `import_terms` 默认一致的 `upsert`，并确保触网达到 `max_requests` 后停止所有后续来源。`2026-07-06` 本地 review 返修进一步修复 `SeedNetworkClient` 的 GET/POST 重试计数：失败重试尝试也会立即写入 request 明细并计入 `--max-requests`，避免超出请求预算，原始 timeout 错误保留在 `summary.requests`；同时为 HKJC/QIDS 马匹候选引入 `source:type:id` 全局实体 key，避免英文同名马误合并，IRE/CAN 等未建模地区保持 `other`，候选证据合并时每条最多保留 `10` 个 evidence sample。上线前本地验证已通过：`TermbaseSeedDataPreparationTests` 6 项、`stable` 全量 354 项、fixture smoke、`openspec validate --all` 和 `git diff --check`；本次 review 返修后追加验证 `TermbaseSeedDataPreparationTests` 21 项、`manage.py check`、`openspec validate --all` 和 `git diff --check` 通过。返修提交 `4b6e840` 已部署生产，部署前备份 `.env.backup.harden-hkjc-termbase-20260706_043557` 与 `backups/db/pre-harden-hkjc-termbase-20260706_043557.sql.gz`（约 `71M`，`gzip -t` 通过）；部署后 `/healthz/`、`manage.py check`、`/`、`/races/`、`/admin/login/` 和公网 `umafans.run/healthz/` 均通过。生产 fixture smoke 输出 `candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`，QIDS 同英文名加拿大马 smoke 已确认不会误合并。本次未导入正式术语，生产计数保持 `TermEntry=15321`、`TermAlias=15537`。

`2026-07-04` 术语种子数据准备已部署生产。服务器 `/opt/umanewsbot` 从 `4323d32` 快进到 `e81733f`，部署前备份 `.env` 为 `.env.backup.termbase-seed-20260704_012005`；因新增 `opencc-python-reimplemented==0.1.7`，本次重建并重启 `web / worker / beat`。部署后迁移显示 `No migrations to apply`，`manage.py check` 通过，生产容器内 fixture smoke 输出 `candidate_count=10`、`conflict_count=1`、`incomplete=false`、`dry_run_error_count=0`，首条候选为 `BEAUTY GENERATION`，末条为 `ディープインパクト`；本地和公网 `/healthz/` 均返回 `200`。本次未导入正式术语，不修改 `TermEntry`、`TermAlias`、`TermCandidate` 或外部马名索引。

`2026-07-04` 已正式导入第一批人工认可格式的术语种子候选。导入文件为生产生成并回传审核的 `imports/termbase-seed-fixture-review-20260704_024950/seed_candidates.csv`；导入前数据库备份为 `backups/db/pre-termbase-seed-import-20260704_030722.sql.gz`，`gzip -t` 校验通过。`import_terms --dry-run` 显示总计 `10` 条、 新增 `8` 条、更新 `2` 条、错误 `0` 条；正式导入结果为新增 `8` 条、更新 `2` 条、跳过 `0` 条。生产正式术语从 `TermEntry=2054` 增至 `2062`，`TermAlias=2057` 增至 `2068`；新增英文术语 `8` 条，日文术语仍为 `2054` 条，其中 `グランアレグリア` 与 `ディープインパクト` 是既有日文术语更新。新增英文术语包括 `BEAUTY GENERATION -> 美丽传承`、`KA YING RISING -> 嘉应高升`、`ROMANTIC WARRIOR -> 浪漫勇士`、`Hong Kong Cup -> 香港杯`、`Zac Purton -> 潘顿`、`John Size -> 蔡约翰`、`Sha Tin -> 沙田马场`、`Declared Starter -> 宣布出赛马匹`。本批首次导入时地区证据只保留在 `notes`，随后已用模型合法地区值执行补写 upsert：备份 `backups/db/pre-termbase-seed-region-upsert-20260704_031950.sql.gz`，短码 `hk/jp` dry-run 因地区不合法被阻断且未写库，改用 `hong_kong/japan` 后 dry-run 为 `10` 条更新、`0` 错误，正式 upsert 为 `10` 条更新、`0` 跳过。补写后地区分布为 `en/hong_kong=8`、`ja/japan=2`、既有旧日文术语空地区 `2052`；公网 `/healthz/` 返回 `200`。

`2026-07-04` WP Stud 第一批全量审核候选已正式导入。已从可直接访问的 WP Stud 页面缓存并转换编码，输出 `runtime/termbase_seed/wpstud-full-review-20260704/seed_candidates.csv`、`seed_candidates_with_region.csv`、`seed_conflicts.csv` 与 `summary.json`；候选共 `210` 条，冲突 `0` 条，全部为 `term_type=horse`、`source_language=ja`、`source_tier=community`、`requires_review=true`，中文译名已转为简体。带地区版本统一设置 `racing_region=hong_kong`，用于描述香港或海外来港赛马候选；生产导入文件为 `/opt/umanewsbot/imports/wpstud-full-review-20260704/seed_candidates_with_region.csv`。本轮与 HKJC 500 条批次共用导入前备份 `backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，`gzip -t` 校验通过；WP Stud 生产 `import_terms --dry-run` 为总计 `210` 条、新增 `210` 条、更新 `0` 条、错误 `0` 条，正式导入为新增 `210`、更新 `0`、跳过 `0`。HKJC 真实页面此前可访问但通用解析器拿不到候选；本地已补 HKJC 专用抽取路径，从 `selecthorse` 发现字母页、从字母页拿 `horseid + 英文名`，再抓繁中马匹详情页对齐中文名，并新增 `--limit-horses` 控制小批马匹数。本轮进一步新增 `--hkjc-letter`，用于按 A-Z 字母拆批抓取，避免无 checkpoint 的全量请求长时间运行。

`2026-07-04` 已开始 HKJC 正式术语候选抓取第一批。为避免后续再手工补地区，生成器已将 `racing_region` 加入 `seed_candidates.csv` 表头，并把 HKJC 候选输出为模型合法值 `hong_kong`。本地低频命令 `--source hkjc --allow-network --limit-pages 1 --limit-horses 100 --max-requests 130 --request-interval-seconds 2 --timeout-seconds 25` 输出到 `runtime/termbase_seed/hkjc-formal-review-20260704_100horses/`，结果为候选 `100` 条、冲突 `0` 条、请求 `103` 次且全部 `200`、`incomplete=false`；全部候选为 `term_type=horse`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`，样例包括 `A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`。临时 SQLite 迁移库已对该 CSV 执行 `import_terms --dry-run`，结果为总计 `100` 条、新增 `100` 条、更新 `0` 条、错误 `0` 条；本批尚未导入生产正式术语库，也尚未部署 HKJC 抽取代码到生产。

`2026-07-04` HKJC 当前本地马官方译名已按 A-Z 字母拆批补齐并导入生产正式术语库。此前 `500` 匹审核包输出目录为 `runtime/termbase_seed/hkjc-formal-review-20260704_500horses/`，结果候选 `500` 条、冲突 `0`、请求 `509` 次全部 `200`、`incomplete=false`，并在生产 dry-run 后正式导入，导入前备份为 `backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`；该批正式导入新增 `500`、更新 `0`。随后发现无 checkpoint 全量命令运行过久，改为新增 `--hkjc-letter` 并按字母拆批：`I` 批候选 `28` 条，备份 `backups/db/pre-hkjc-letter-I-term-import-20260704_185212.sql.gz` 后导入新增 `28`；`J` 批候选 `23` 条，备份 `backups/db/pre-hkjc-letter-J-term-import-20260704_185400.sql.gz` 后导入新增 `23`；`K-Z` 合并候选 `701` 条，生产 dry-run 为新增 `699`、更新 `2`、错误 `0`，备份 `backups/db/pre-hkjc-letters-K-Z-term-import-20260704_191425.sql.gz` 后正式导入；`A-H` 复跑合并候选 `505` 条，生产 dry-run 为新增 `5`、更新 `500`、错误 `0`，备份 `backups/db/pre-hkjc-letters-A-H-term-import-20260704_192843.sql.gz` 后正式导入。导入后生产 `TermEntry=3527`、`TermAlias=3743`，`source_language=en/racing_region=hong_kong` 合计 `1263` 条，其中 HKJC 当前本地马英文术语 `1258` 条；`source_language=ja/racing_region=hong_kong` 的 WP Stud 社区马名术语 `210` 条。公网 `/healthz/` 返回 `200`。当前完成的是 HKJC 当前本地马名单补齐，不等同于“香港赛事/骑手回溯到 2024-01-01”；赛事和骑手仍需从 HKJC Race Card/赛果链路另行抽取。

`2026-07-04` 已继续 HKJC 本地赛果回溯术语导入，用于补齐香港赛果中的历史马名、骑师名和赛事名。生成器新增 `--hkjc-local-results-start-date`、`--hkjc-local-results-end-date`、`--hkjc-local-results-skip-races` 与 `--hkjc-skip-horse-details`，并对 HKJC 赛日首页只直接展示第 1 场、链接从第 2 场开始的结构做了补抓；抓取时会同时请求 `en-us` 与 `zh-hk` 赛果页，对齐输出 `horse / jockey / race` 候选，中文目标译名转为简体。已正式导入 `2024-01` 至 `2024-07`、`2024-09` 至 `2025-07`、`2025-09` 至 `2026-07-04`；`2024-08` 与 `2025-08` 已逐日扫描且候选 `0`、失败 `0`，无需导入。`2024-07` 输出 `647` 条候选（`horse=575`、`race=49`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202407-term-import-20260704_211425.sql.gz` 后导入新增 `74`、更新 `573`；`2024-09` 输出 `626` 条候选（`horse=549`、`race=54`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202409-term-import-20260704_213327.sql.gz` 后导入新增 `62`、更新 `564`；`2024-10` 输出 `834` 条候选（`horse=735`、`race=75`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-202410-term-import-20260704_214522.sql.gz` 后导入新增 `104`、更新 `730`；`2024-11` 输出 `850` 条候选（`horse=757`、`race=69`、`jockey=24`），`2024-11-13 HV Race 7-9` 为 HKJC 双语空壳赛果页，已记录为 `skipped_races/local_result_not_available` 且不导入空数据，备份 `backups/db/pre-hkjc-local-results-202411-term-import-20260704_221006.sql.gz` 后导入新增 `97`、更新 `753`；`2024-12` 输出 `957` 条候选（`horse=832`、`race=78`、`jockey=47`），备份 `backups/db/pre-hkjc-local-results-202412-term-import-20260704_222551.sql.gz` 后导入新增 `135`、更新 `822`；`2025-01` 输出 `913` 条候选（`horse=804`、`race=78`、`jockey=31`），备份 `backups/db/pre-hkjc-local-results-202501-term-import-20260704_224151.sql.gz` 后导入新增 `73`、更新 `840`；`2025-02` 输出 `794` 条候选（`horse=703`、`race=60`、`jockey=31`），备份 `backups/db/pre-hkjc-local-results-202502-term-import-20260704_225443.sql.gz` 后导入新增 `38`、更新 `756`；`2025-03` 输出 `914` 条候选（`horse=803`、`race=78`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202503-term-import-20260704_231134.sql.gz` 后导入新增 `30`、更新 `884`；`2025-04` 输出 `893` 条候选（`horse=782`、`race=78`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202504-term-import-20260704_232559.sql.gz` 后导入新增 `58`、更新 `835`；`2025-05` 输出 `920` 条候选（`horse=816`、`race=79`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202505-term-import-20260704_234206.sql.gz` 后导入新增 `38`、更新 `882`；`2025-06` 输出 `826` 条候选（`horse=741`、`race=63`、`jockey=22`），备份 `backups/db/pre-hkjc-local-results-202506-term-import-20260704_235659.sql.gz` 后导入新增 `44`、更新 `782`；`2025-07` 输出 `675` 条候选（`horse=603`、`race=49`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202507-term-import-20260705_000915.sql.gz` 后导入新增 `19`、更新 `656`；`2025-09` 输出 `632` 条候选（`horse=560`、`race=49`、`jockey=23`），`2025-09-21 ST Race 9-10` 为 HKJC 双语空壳赛果页，已记录为 `skipped_races/local_result_not_available` 且不导入空数据，备份 `backups/db/pre-hkjc-local-results-202509-term-import-20260705_002604.sql.gz` 后导入新增 `17`、更新 `615`；`2025-10` 输出 `882` 条候选（`horse=786`、`race=73`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202510-term-import-20260705_004245.sql.gz` 后导入新增 `41`、更新 `841`；`2025-11` 输出 `933` 条候选（`horse=826`、`race=81`、`jockey=26`），备份 `backups/db/pre-hkjc-local-results-202511-term-import-20260705_010022.sql.gz` 后导入新增 `45`、更新 `888`；`2025-12` 输出 `912` 条候选（`horse=803`、`race=68`、`jockey=41`），备份 `backups/db/pre-hkjc-local-results-202512-term-import-20260705_011812.sql.gz` 后导入新增 `42`、更新 `870`；`2026-01` 输出 `978` 条候选（`horse=875`、`race=78`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202601-term-import-20260705_013522.sql.gz` 后导入新增 `28`、更新 `950`；`2026-02` 输出 `930` 条候选（`horse=836`、`race=69`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202602-term-import-20260705_015108.sql.gz` 后导入新增 `18`、更新 `912`；`2026-03` 输出 `944` 条候选（`horse=838`、`race=81`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202603-term-import-20260705_020814.sql.gz` 后导入新增 `18`、更新 `926`；`2026-04` 输出 `975` 条候选（`horse=859`、`race=83`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202604-term-import-20260705_022703.sql.gz` 后导入新增 `41`、更新 `934`；`2026-05` 输出 `979` 条候选（`horse=873`、`race=80`、`jockey=26`），备份 `backups/db/pre-hkjc-local-results-202605-term-import-20260705_024451.sql.gz` 后导入新增 `33`、更新 `946`；`2026-06` 输出 `844` 条候选（`horse=757`、`race=63`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-202606-term-import-20260705_025830.sql.gz` 后导入新增 `20`、更新 `824`；`2026-07-01` 至 `2026-07-04` 输出 `310` 条候选（`horse=265`、`race=21`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-20260701-20260704-term-import-20260705_030505.sql.gz` 后导入新增 `5`、更新 `305`。以上新增批次生产 dry-run 均为错误 `0`，正式导入均为跳过 `0`。导入后生产 `TermEntry=5948`、`TermAlias=6164`，`source_language=en/racing_region=hong_kong` 合计中 `horse=2479`、`jockey=70`、`race=1132`，另保留既有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`；`http://127.0.0.1/healthz/` 返回 `200`。当前 HKJC 香港本地赛果已回溯到 `2026-07-04`；仍需另行补 HKJC overseas 与 WP Stud 赛事/骑手缺口。

`2026-07-04` 已创建并完成 plan-eng-review 的 OpenSpec change `prepare-hkjc-overseas-termbase-seeds`，用于把 HKJC overseas simulcast Race Card 扩展为海外马名、骑师和赛事名的官方中文术语种子来源。该 change 已完成 `proposal.md`、`design.md`、`tasks.md` 与 `termbase-seed-data-preparation` delta spec，并通过 `openspec validate prepare-hkjc-overseas-termbase-seeds --strict`；当前本地已完成代码侧实现，新增 `prepare_termbase_seed_data --source hkjc_overseas`、`--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`、`--limit-meetings`、`--limit-races`，输出继续不写正式术语库、不写 `ExternalHorse`，并新增 `source_evidence.json` 记录 Race Card 参数、中英页面 URL、原始繁体、地区映射、horse profile 证据、跳过和失败原因。review 约束已落地：渲染 fallback 默认不引入生产浏览器硬依赖；若无可用渲染器或渲染后缓存，会记录 `render_fallback_unavailable` 并标记 `incomplete=true`。本地 fixture smoke 输出 `runtime/termbase_seed/hkjc-overseas-fixture-smoke-migrated/`，候选 `9` 条、冲突 `0`、`incomplete=false`、`dry_run_error_count=0`，并通过 `import_terms --dry-run`。后续 review 修复已明确术语种子冲突输出规则：同一实体如出现多个中文译名，`seed_candidates.csv` 只保留一个正式 `target_zh`，其他译名进入 `aliases_zh`，同时 `seed_conflicts.csv` 保留冲突证据。用户确认后已执行 HKJC overseas 低上限 live dry-run：命令使用 `--source hkjc_overseas --allow-network --limit-meetings 1 --limit-races 1 --max-requests 6 --request-interval-seconds 3 --timeout-seconds 15`，输出目录为 `runtime/termbase_seed/hkjc-overseas-live-smoke-20260704_174924/`；结果为候选 `0` 条、冲突 `0`、跳过 `0`、请求 `1` 次且入口页 `https://racing.hkjc.com/en-us/overseas/` 返回 `200`，但直接 HTML 未暴露 Race Card 链接，因此记录 `render_fallback_unavailable: no race card links in direct HTML`，`incomplete=true`，`dry_run_error_count=0`。这证明当前实现不会把 HKJC Next.js shell 误当作空数据成功；要批量取得海外 Race Card 正式候选，还需要后续补浏览器渲染缓存或解析 HKJC 前端 API。本能力尚未部署生产，live dry-run 也未写正式术语库。

`2026-07-05` HKJC overseas 术语批量回溯已通过本地 QIDS GraphQL 抽取和生产 `import_terms` 正式导入完成，覆盖 `2024-01-01` 至 `2026-07-04`。生成器新增 `--hkjc-overseas-start-date` 与 `--hkjc-overseas-end-date`，会从 HKJC overseas results 发现转播赛日，再通过 HKJC QIDS `raceMeetingProfile` 对齐海外 Race Card 的英文/繁中 `horse / jockey / race`；该本地代码尚未部署生产，但生成产物已用于生产导入。月度产物合并目录为 `runtime/termbase_seed/hkjc-overseas-qids-merged-20240101-20260704/`，原始行 `11633` 条、候选 `7691` 条、冲突 `3` 条，候选结构为 `horse=6481`、`jockey=847`、`race=363`。生产导入文件为 `/opt/umanewsbot/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`；导入前备份为 `backups/db/pre-hkjc-overseas-qids-term-import-20260705_040238.sql.gz` 并通过 `gzip -t`；生产 dry-run 为总计 `7691`、新增 `7688`、更新 `3`、错误 `0`，正式导入为新增 `7482`、更新 `209`、跳过 `0`。因当前正式术语 upsert 身份是 `term_type + source_language + source_ja`，不是按地区拆分，同名国际骑师会被后导入地区覆盖；已用 `runtime/termbase_seed/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv` 对 HKJC 本地赛果骑师做地区恢复，备份 `backups/db/pre-hkjc-local-jockey-region-restore-20260705_040950.sql.gz`，dry-run 和正式导入均为 `69` 条更新、`0` 错误/跳过。恢复后 HKJC 本地赛果覆盖仍为 `en/hong_kong horse=2479, jockey=69, race=1132`，海外 HKJC 官方来源计数为 `7483`。

`2026-07-05` WP Stud 当前发现的马名、赛事、骑师和马场社区术语已补齐到正式术语库，但不覆盖 HKJC 官方主译名。此前 WP Stud 马名批次已导入 `210` 条 `source_language=ja/racing_region=hong_kong` 社区马名；本次继续抓取 WP Stud `Translation/Race` 下 `21` 个赛事页面、`Translation/jockey.htm` 和 `Translation/racecourse/RaceCourse.htm`，输出目录为 `runtime/termbase_seed/wpstud-race-jockey-racecourse-review-20260705/`，完整候选 `2095` 条、冲突 `17` 条、`incomplete=false`，其中 `race=1392`、`jockey=276`、`racecourse=427`。生产完整 dry-run 显示会新增 `1891`、更新 `204`、错误 `0`；其中 `204` 条更新主要命中 HKJC overseas/HKJC 官方术语，因此已过滤为 `seed_candidates_new_only.csv` 仅导入新增项，并把 `seed_candidates_skipped_existing.csv` 留作人工审核清单。过滤后生产 dry-run 为总计 `1891`、新增 `1891`、更新 `0`、错误 `0`；备份 `backups/db/pre-wpstud-race-jockey-racecourse-term-import-20260705_072047.sql.gz` 通过 `gzip -t`；正式导入新增 `1891`、更新 `0`、跳过 `0`。导入后生产 `TermEntry=15321`、`TermAlias=15537`，`http://127.0.0.1/healthz/` 返回 `200`。本轮后 `source_language=en` 分布已包含香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，其中 HKJC 官方仍保持最高优先级，WP Stud 作为社区候选和佐证使用。

`2026-07-06/07` 已完成 HKJC / WP Stud 术语库清洗、WP Stud HorseList 全量马名补齐和生产正式导入。返修代码让 HKJC overseas 与美国详情来源中的马名去除尾部国别后缀，例如 `A Bit Of Spirit (IRE)` 清洗为 `A Bit Of Spirit`；带年份或替代名称的复合赛事名会拆成独立术语，例如 `International Stakes` 与 `Benson & Hedges Gold Cup Stakes`；WP Stud `HorseList.html` 已作为默认来源，解析日文马名、英文别名和简体中文译名。最终审核产物位于 `runtime/termbase_seed/final-reviewed-import-20260706/`，`seed_candidates_final.csv` 共 `11257` 行，输入覆盖 HKJC `7691`、WP Stud race/jockey/racecourse `1891` 和 WP Stud HorseList `1866`；清洗统计包括去除马名国别后缀 `6481` 次、拆分年份赛事标记 `59` 次、去重 `254` 行，并生成 HKJC 日本地区英文马名日文 alias `907` 行，其中马名 `883` 行已全部找到日文名。生产服务器 `/opt/umanewsbot` 导入时 `HEAD=b1ddb54`，导入前 `TermEntry=15321`、`TermAlias=15537`，备份 `backups/db/pre-final-termbase-review-20260706_234427.sql.gz` 约 `75M` 且 `gzip -t` 通过；正式脚本先清理既有脏 active 术语，再执行 `import_terms`，结果为新增 `1169`、更新 `10088`、错误/跳过 `0`。导入后生产 `TermEntry=16558`、`TermAlias=19293`、active `TermEntry=16428`，active 马名国别后缀术语 `0`、active 赛事年份标记术语 `0`，`ExternalDataImportRun(status="started")=0` 且导入锁为空，`manage.py check`、`127.0.0.1/healthz/` 与 Host `umafans.run` 健康检查均通过。抽检确认 `A Bit Of Spirit (IRE)` 已无 active 词条而 `A Bit Of Spirit -> 点燃斗志` 有效，`International Stakes -> 国际锦标` 与 `Benson & Hedges Gold Cup Stakes -> 宾臣暨赫捷仕金杯` 已拆分，`A Shin Resume / Dragon / Dynamic / Sophia` 等 HKJC 日本马英文词条已挂日文 alias。另有 `26` 个 HKJC 日本马日文 alias 因生产已有同日文 `TermAlias` 或日文主词而未直接挂到英文词条，其中大多数中文目标一致；`Raijin / ライジン` 和 `Scintillation / シンチレーション` 存在既有译名占用，导入脚本按“不强行合并冲突概念”跳过，保留 HKJC 英文主译名。

`2026-07-05` OpenSpec change `prepare-hkjc-overseas-termbase-seeds` 已完成正式规格同步并归档，归档目录为 `openspec/changes/archive/2026-07-05-prepare-hkjc-overseas-termbase-seeds/`。归档前已将 delta spec 合并到 `openspec/specs/termbase-seed-data-preparation/spec.md`：正式规格现在包含 `hkjc_overseas` 来源、Race Card 自动发现与精确参数、马名/骑师/赛事名候选、简体中文目标、官方来源元数据、结构化证据、地区映射以及包含 `racing_region` 的导入兼容表头。归档前 `openspec validate prepare-hkjc-overseas-termbase-seeds --strict && openspec validate --all` 通过，归档后 `openspec validate --all` 通过 `17` 项。
仓库已于 `2026-06-06` 加入 OpenSpec + Codex 协作支持，用于在较大功能、跨模块改动、架构调整和生产高风险变更前先对齐规格，再进入实现。

OpenSpec change `add-term-candidate-discovery` 已完成实现、自动化测试、本地隔离环境浏览器验收，并归档为 `2026-06-06-add-term-candidate-discovery`；正式能力规格已同步到 `openspec/specs/term-candidate-discovery/spec.md`。

`2026-06-30` OpenSpec change `operate-multiregion-news-production` 已完成实现、代码审查返修、生产部署和归档。新增多地区新闻生产只读审计命令 `audit_multiregion_news_production`、通用 enabled 新闻来源轮询任务 `crawl_enabled_news_sources_task`、地区/来源自动发布 allowlist 与地区上限策略、后台 `/admin/regions/` 地区生产概览、来源管理地区筛选、QQ 国际新闻地区标签、地区查询索引和运行手册。返修后，地区生产概览的自动发布、人工发布和公开数量按今日窗口统计，待翻译、翻译失败和待审核保留为当前积压；审计中的来源抓取状态改为按 `NewsSource.last_crawl_status` 当前来源状态聚合，不再累计历史 `CrawlJob` 次数；正式术语 `TermEntry` 增加可选适用地区，空值表示全局通用，术语列表/表单/API/CSV 导入和多地区审计均支持地区口径；自动发布批次在地区每日/每轮上限跳过大量国际候选时，会在主扫描未填满后执行有限的日本候选兜底扫描，避免拖慢符合既有策略的日本文章。生产服务器 `/opt/umanewsbot` 已从 `7b6e51b` 快进到 `62a0f9a` 并执行 `bash ./deploy_lowcost.sh`，部署前备份 `.env` 为 `.env.backup.multiregion-news-20260630_185150`；迁移 `stable.0014_multiregion_news_indexes` 与 `stable.0015_termentry_racing_region` 已应用，`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、首页和后台登录入口均通过。随后已按用户要求开启多地区新闻生产开关，备份 `.env` 为 `.env.backup.enable-all-multiregion-20260630_203647`；当前 `NEWS_SOURCE_POLL_ENABLED=true`、轮询间隔 `30` 分钟、每轮最多 `12` 个来源，覆盖 `japan / hong_kong / united_kingdom / france / united_states` 五个地区；非日本自动发布 allowlist 已开启 `hong_kong / united_kingdom / france / united_states` 四个地区和当前已启用的国际来源，并设置首日护栏上限 `hong_kong:5 / united_kingdom:5 / france:3 / united_states:3`。开关生效后手动执行通用轮询 smoke，已选中并派发 `12` 个 due 来源，固定调度的 netkeiba/JRA 被正确跳过；worker 并发为 `2`，当前先处理 Sponichi 两个任务，其余任务在队列中等待消化。正式 QQ 群仍需显式配置 `PushTarget.allowed_regions` 才接收国际新闻。外部赛马数据库 `External*` importer 不进入新闻常态调度，不自动生成公开新闻或 QQ 推送。归档目录为 `openspec/changes/archive/2026-06-30-operate-multiregion-news-production/`，正式规格已同步到 `openspec/specs/multiregion-news-production/spec.md` 及相关能力规格。

`2026-07-02` OpenSpec change `increase-multiregion-news-volume` 已整体上线到生产。生产 `/opt/umanewsbot` 当前运行 `9e97e8c`，与 `origin/main` 一致；部署前数据库备份为 `backups/db/pre-multiregion-volume-20260702_040811.sql.gz`，`.env` 备份为 `.env.backup.multiregion-volume-20260702_040811`，启用前另备份 `.env.backup.enable-multiregion-volume-20260702_041242`。迁移 `stable.0017_majorraceevent_productionwindow_quotaledger_and_more` 与 `stable.0018_alter_notificationlog_type` 已应用，`web / worker / beat` 运行健康，本地和公网 `/healthz/` 均返回 `200`。本次上线开启 `MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true`、抓取/发布/QQ 三条窗口开关均为 `true`，覆盖 `japan / hong_kong / united_kingdom / france / united_states`；当前 16 个启用新闻源已标记 `production_approved=true`，日常抓取默认 15 分钟，重要赛事窗口默认 5 分钟。上线过程中发现并修复抓取窗口把 Celery `AsyncResult` 写入 JSON payload 导致窗口失败的问题，修复提交为 `9e97e8c`，窗口现在保存 `dispatch_result.task_id`。生产 smoke：20:15 抓取窗口派发 15 个 due 来源，最终 14 个成功、1 个 `Sponichi 新闻ランキング` 因上游 `502 Bad Gateway` 失败且写入明确原因；20:15 发布窗口香港自动发布 1 篇、美国自动发布 3 篇，20:30 发布窗口美国继续发布 1 篇，其他地区为 `no_ready_candidates`；20:15 QQ 窗口美国发送 2 条 delivery，20:30 QQ 窗口美国为 `already_sent`，其他地区为 `no_eligible_articles`。公开首页和地区页浏览器验收通过，首页可见 20:15 窗口新发布的香港/美国文章。ops 摘要通知已配置到 `UmaFans测试群(1026525240)`，`production_summary_task` 已产生 `NotificationLog #13051`，状态 `sent`。因当前为后半夜新闻低峰，用户确认跳过实际 4 个自然窗口等待，改为次日继续观察来源失败、候选质量、0 原因和 QQ 限流情况。

`2026-07-01` 已将 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send` 全部归档，正式规格同步到 `openspec/specs/external-horse-data-import/`、`openspec/specs/international-racing-coverage/` 及相关能力规格；`openspec list` 为空，`openspec validate --all` 12 项通过。本次同时补齐 `ExternalDataSource` 对 `sporting_life / france_galop / geny_france / horse_racing_nation` 的 choices 和迁移 `stable.0016`，避免英法美外部数据导入 source 值与模型枚举不一致。生产服务器 `/opt/umanewsbot` 已从 `538a1a9` 快进到 `8c83708` 并执行 `bash ./deploy_lowcost.sh`，部署前数据库备份为 `backups/db/pre-archive-all-20260701_153301.sql.gz` 且 `gzip -t` 通过；部署后 `web / worker / beat` 已重建，迁移 `stable.0016_alter_externaldataimporterror_source_and_more` 已应用，`manage.py check`、本地和公网 `/healthz/`、首页、后台登录入口和 `/admin/regions/` 均通过。浏览器验收确认首页地区 tab 正常，香港/英国地区页可渲染已发布国际新闻，地区生产页可显示五地区来源与 QQ 状态。生产开关仍为 `NEWS_SOURCE_POLL_ENABLED=true`、轮询间隔 `30` 分钟、每轮最多 `12` 个来源、覆盖五地区，`QQ_PUSH_ENABLED=true` 且 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。来源状态复核显示五地区 enabled 来源多数最近抓取为 `success`；当前仅 `Sponichi 新闻ランキング` 因上游 `502 Bad Gateway` 处于失败状态，属于来源站响应异常，不影响本次部署成立。

`2026-06-07` 已将术语候选发现部署到生产：服务器从 `7123e4e` 拉到 `e2e3e07`，应用迁移 `0006` 新建候选与证据表，`.env` 补入术语发现开关并保持 `TERM_DISCOVERY_ENABLED=false`（灰度，先关后开）。本次部署同时核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 仍在生效。

仓库已明确长期语言约定：Codex 新增或维护的协作文档、OpenSpec 产物与代理说明默认使用中文；仅保留必要的代码标识符、命令和工具机器语法。

`2026-06-19` 已创建公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`。该 change 作为后续前台 Web + 移动 H5 首页子任务的指导规范，目标是把当前 MVP 公开首页从“大说明 + 大卡片网格”升级为成熟资讯流：移动端轻头条 + 高密度新闻列表，桌面端门户式主内容 + 侧栏。`2026-06-21` 已完成 plan-eng-review 与 `/opsx:apply` 本地实现；实施过程按严格 TDD 执行发布过滤、头条选择、普通流去重、热门代理、公开静态资源和详情页结构测试，并已通过本地 Django 测试、OpenSpec 校验和桌面/移动浏览器验收。`2026-06-22` 已将 delta spec 同步为正式规格 `openspec/specs/public-home-info-feed/spec.md`，并归档为 `openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`；同日 PR #1 已合并并部署到生产，服务器运行 `e834f58`，公开首页已切换到 `stable/public.css` 和新资讯流模板。`2026-06-23` PR #2 已合并并部署生产，服务器运行 `04e2ee9`，移动 H5 首屏密度 follow-up 已上线。

`2026-06-24` 已完成自动发布门禁优化 OpenSpec change：`refine-automation-publish-gates` 的实现、PR 合并与生产上线。代码已将自动发布门禁拆为 `blocker / warning / info`：`blocker` 阻断自动发布，`warning` 初期不阻断但记录并对高价值文章邮件告警，`info` 仅用于诊断；同时支持基准翻译稿自动发布、高价值来源评分放行、非马名普通词过滤、关键术语分层校验和重复内容拦截。生产服务器当前运行 PR #4 squash merge 后的提交 `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用。

`2026-06-25` 已将本轮三个运营改造 change 合并到 `main` 并部署生产：抓取新鲜度与来源健康、后台原文选区快速加入术语库、新增术语后一次性应用到当前稿。服务器 `/opt/umanewsbot` 已从 `268100d` 更新到 `7f54f13`，`web / worker / beat` 已重建，`manage.py check`、`/healthz/` 和首页 HTTP 验证通过。相关 OpenSpec change 已归档并同步正式规格；其中抓取返修的 `fix-crawl-health-running-and-schedule-stagger` 是 change1 的后续规格，随 change1 一并归档。

`2026-06-25` 已将榜单重点新闻 QQ 推送与公开文章 ID URL 改造通过 PR #8 合并并部署生产。服务器 `/opt/umanewsbot` 已更新到 `00e4bd4`，部署前 `.env` 备份为 `.env.backup.qq-ranked-idurl-20260625_191826`；生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、`http://umafans.run/`、`/news/<article_id>/` 公开详情和旧 slug 到 ID URL 的 `302` 跳转均已验证通过。本次不补推历史公开新闻，后续只等待自然榜单新闻触发测试群推送。

`2026-06-26` 已将国际赛马资讯扩展 OpenSpec change：`expand-international-racing-coverage` 合并到 `main` 并部署生产，服务器 `/opt/umanewsbot` 已从 `2f0c35c` 更新到 `5865e58`，部署前 `.env` 备份为 `.env.backup.international-coverage-20260626_103923`。本次部署应用迁移 `stable.0011`、`0012`、`0013`，`web / worker / beat` 已重建，`manage.py check`、`http://127.0.0.1/healthz/` 和首页 HTTP 验证通过。部署前发现生产 netkeiba 外部马名导入脚本仍在连续运行，已等待当前批次完成并释放 `ExternalDataImportLock` 后再部署；外层脚本 `/opt/umanewsbot/imports/run_horse_import_202504_to_202406_20260626_083946.sh` 已停止，最近两批 `1958 / 1959` 均停在 `paused`，避免部署与导入写库重叠。国际来源已同步并灰度启用第一版清单：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing latest/access`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation latest/access`；生产探测中 `BHA official` 返回 `403`，已暂时停用，`At The Races`、`Paulick Report` 和 `BloodHorse` 仍保留为候选但不启用。测试 QQ 群 `1026525240` 已配置允许 `japan / hong_kong / united_kingdom / france / united_states` 五个地区。首轮手动触发 12 个新增来源抓取任务后，`Sponichi latest` 已完成并入库 `13` 篇新稿、`7` 篇重复稿，`Sponichi access` 与 `HKJC Racing News` 已开始执行，其他国际来源仍在 worker 队列中等待；后续重点观察 `CrawlJob`、翻译结果、自动发布门禁和 QQ 群推送。

`2026-06-26` 已创建新的本地 Codex 工作树 `/Users/mentianlu/.codex/worktrees/openspec-ready-20260626/umanews`，基线为 `origin/main` 的 `4d09d25`。该工作树已带入 `.codex/skills/openspec-*`、`.codex/skills/plan-eng-review`、`.codex/skills/tdd`、`.codex/skills/workflow-spine` 和 `.agents/skills` 镜像，并补齐 `gate-templates.md` 引用副本；已通过 `openspec list`、`openspec validate --all`、`openspec validate expand-international-racing-coverage --strict`、`openspec validate add-netkeiba-horse-data-import --strict`、`openspec status --change expand-international-racing-coverage --json` 和 skill 文件一致性检查。该记录仅描述本地协作工作树准备状态，不代表新的产品或生产部署变更。

`2026-06-26` 已新增并完成计划审查 OpenSpec change `start-hkjc-data-import-and-global-spikes`，用于启动香港 HKJC 外部赛马数据受控导入，并为英国 `Sporting Life + BHA`、美国 `Equibase`、法国 `France Galop` 产出结构化数据库 spike。该 change 明确不续跑日本 netkeiba 外部数据导入，日本导入由其他线程继续；本轮也不实现前台比赛页、赛果页或马匹页。已创建 `proposal.md`、`design.md`、`specs/global-racing-data-import-readiness/spec.md` 和 `tasks.md`，并通过 `/plan-eng-review`；审查后补齐 HKJC 生产 commit 前的隔离库验证、数据库备份、用户显式确认、`HKJC_IMPORT_*` 环境配置入口，以及英法美 spike 前后正式表计数保持不变的验收要求。当前 `.openspec.yaml` 为 `phase: reviewed`，已通过 `openspec validate start-hkjc-data-import-and-global-spikes --strict`、`openspec validate --all` 和 `git diff --check`。随后按 TDD 红灯阶段新增 `openspec/changes/start-hkjc-data-import-and-global-spikes/test_cases.md` 和自动化测试；本轮实现已将 4 个红灯转绿：补齐 `HKJC_IMPORT_*` settings 和 `.env.example`，新增 HKJC `--allow-network` dry-run 请求边界输出，新增英法美只读 spike runner 和正式表 before/after 计数检查。HKJC 最小样本 fixture 已保存到 `server/stable/fixtures/hkjc/`，本地隔离 SQLite `/tmp/umanews-hkjc-apply.sqlite3` 已完成赛日、单场、单马 dry-run/commit，结果写入 `docs/hkjc_data_import_samples.md`；隔离库最终统计为 3 个 import run、1 场比赛、2 个 entries、2 条 results、2 匹马、4 条别名。英法美 read-only spike 已执行 6 次公开页面 GET，请求证据、字段覆盖矩阵和准入判断已写入 `docs/global_racing_data_source_spikes.md`；三地当前均为 `needs_more_spike`，且正式表 before/after 计数保持不变。验证通过：`manage.py check`、HKJC/spike 目标测试 12 项、完整 `stable` 测试 246 项。

`2026-06-26` 已将 `start-hkjc-data-import-and-global-spikes` 实现提交 `b0361cf` 推送到 `main` 并部署生产。服务器 `/opt/umanewsbot` 已从 `4d09d25` 快进到 `b0361cf`，部署前 `.env` 备份为 `.env.backup.hkjc-global-spikes-20260626_164045`。部署前确认生产无运行中 `ExternalDataImportLock`，无 `ExternalDataImportRun(status="started")`；`bash ./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建，`web` healthy。生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`；HKJC 样本命令以 dry-run 方式读取容器内 `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`，返回 `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}` 且 `would_write_formal_tables=false`。部署当时未执行 HKJC commit，也未启用英法美正式导入。

`2026-06-26` 已归档 `start-hkjc-data-import-and-global-spikes`，归档目录为 `openspec/changes/archive/2026-06-26-start-hkjc-data-import-and-global-spikes/`；delta spec 已同步为正式规格 `openspec/specs/global-racing-data-import-readiness/spec.md`。归档后 `openspec validate --all` 通过，`global-racing-data-import-readiness` 正式规格包含 6 个 requirement。归档提交 `db0f3cc` 已推送到 `main` 并在生产 `/opt/umanewsbot` 快进；该提交只移动 OpenSpec/文档，不重建容器，生产服务代码仍为已部署验证过的 `b0361cf` 镜像内容，线上 `/healthz/` 和首页保持 `200`。

`2026-06-26` 已按用户确认启动 HKJC 生产样本导入，但范围仅限仓库 fixture `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`，不是 HKJC 真实网络持续抓取。执行前已在生产服务器创建数据库备份 `backups/db/pre-hkjc-sample-20260626_180646.sql.gz` 并通过 `gzip -t` 校验；预检查显示无运行中 HKJC 导入、无 started run，`web` healthy。生产 dry-run 再次返回 `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}` 且不写正式表；随后执行 `--commit` 成功，`run_id=1960`、`success_count=7`、`failure_count=0`、`skipped_count=0`。提交后生产 HKJC 外部表统计为 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`，马名索引 `STELLAR EXPRESS` 命中 `HKH_STELLAR_EXPRESS`；`ExternalDataImportLock` 仅保留未占用的来源占位记录，未发现仍在运行的 HKJC 导入进程，`http://umafans.run/healthz/` 返回 `200`。真实 HKJC 网络入口仍未确认，不能把这次样本导入理解为已开启自动抓取。

`2026-06-26` 已新建 OpenSpec change `connect-real-global-racing-databases`，目标是按 `香港 -> 英国 -> 法国 -> 美国` 顺序接入真实赛马数据库，抓取每个地区最近 2 个月赛事和涉及马匹详情后停止，不创建公开比赛页或持续调度。香港阶段已定位 HKJC 官方真实 HTML 入口：赛日列表 `localresults`、单场结果 `localresults?racedate=YYYY/MM/DD&Racecourse=HV|ST&RaceNo=N`、马匹详情 `horse?horseid=...`。本地 TDD 已新增 HKJC HTML parser、race link 聚合、recent-days/date-range、马匹详情补抓、限速、请求上限和 `completion` 完成度测试，`HKJCExternalDataImportTests` 21 项通过；真实 HKJC 单场 dry-run `HK20260624HV01` 请求 1 次官方页面并解析 `1` 场、`12` entries、`12` results、`12` unique horses，未写库。随后在隔离 SQLite `/tmp/umanews-hkjc-real-single.sqlite3` 执行同一真实单场 `--commit --allow-network`，成功写入 `ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorseAlias=12`，`run_id=1`、`success_count=25`、`failure_count=0`。同日又完成 HKJC `--recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1` 真实小范围链路：dry-run 请求赛日列表、赛日页、单场结果和马匹详情共 `4` 次，解析 `1` 场、`12` entries、`12` results、`12` unique horses，并返回 `completion.is_complete=false`、`stop_reason=limit_horses_reached`、`meetings_found=28`，明确这是样本而非全量；隔离 SQLite `/tmp/umanews-hkjc-real-range.sqlite3` commit 后写入 `ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorse=1`、`ExternalHorseAlias=12`，重复执行后正式对象计数不增长。当前仍未部署生产，也未执行生产最近两个月全量 dry-run/commit；下一步需要生产部署前锁检查、备份、用户确认后再低频运行 HKJC 最近两个月范围。

`2026-06-26` 已为 `connect-real-global-racing-databases` 追加英法美只读 spike 复核，共执行 `18` 次公开页面 GET，不写任何 `External*` 表。英国 `Sporting Life` racecards、fast-results 和 horse profile 均返回 `200`，fast-results 暴露具体 racecard 与 horse profile 链接；`BHA` horses/fixtures 返回 `200`，暴露 horses feed、search 和 fixtures/racecards 相关入口，因此英国当前优先级最高，建议后续以 Sporting Life 为正式导入主候选、BHA 为官方补字段候选。美国 `Equibase` entries、chart/PDF index 和具体 horse profile 均返回 `200`，但 chart/PDF 解析成本和访问限制仍需 fixture spike。法国 `France Galop` 官方页面和 app 说明页返回 `200` 并有 race card/results/calendar 浅层信号，但尚未定位稳定结构化查询参数，仍为 `needs_more_spike`。证据已写入 `docs/global_racing_data_source_spikes.md`。

`2026-06-26` 已为 HKJC 增加 `--plan-only`、`--skip-races` 和 `--race-ids` 批次能力，并用真实页面完成本地 plan-only 预检：最近 60 天 HKJC 下拉目标日期页 `28` 个，过滤 overseas simulcast 的 `S*` racecourse 后，本地香港 `HV/ST` 比赛为 `144` 场；按 `limit-races=20` 可拆为 `8` 批。`--skip-races 20 --limit-races 1 --limit-horses 0` 真实 smoke 成功从第 21 场 `HK20260613ST04` 开始，证明日期范围后续批次不会重复第一批；随后 `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 真实 smoke 只请求 `race/race/horse` 3 个页面，解析 `2` 场、`26` entries、`26` results 和 `26` 匹唯一马，证明可按 plan-only 输出的 race_id 清单执行精确批次。本能力只用于生产全量前规划和拆批；尚未执行生产最近 2 个月全量 dry-run 或 commit。

`2026-06-26` 已将 `connect-real-global-racing-databases` 当前 HKJC 真实网络实现部署到生产，部署前数据库备份为 `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz` 并通过 `gzip -t` 校验。生产 `65d41eb` 部署后 `manage.py check`、本地和公网 `/healthz/`、HKJC 精确 race-id 小样本 dry-run 均通过；生产 plan-only 仍显示最近 60 天本地香港 `HV/ST` 比赛 `144` 场、拆为 `8` 批。随后第 1 批 full dry-run 在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout 中断；该次未使用 `--commit`，未写正式表，中断后生产 HKJC 锁为空、`started_runs=0`、HKJC 表计数仍为上次 fixture 样本 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`。已按 TDD 追加 transient timeout retry 并部署到生产 `04c0444`，单请求最多 `3` 次并记录失败尝试；目前已将前 6 个 plan-only 批次拆成 24 个 5 场小批次完成 full dry-run，累计覆盖 `120` 场、`1522` entries、`1522` results、`1522` 个 horse profile 请求，所有小批次均 `completion.is_complete=true`，未写正式表。3c 首次执行时遇到一次执行容器 `137` 中断，输出文件为 `0` 字节；复查服务、锁和表计数均安全，随后改用一次性 `docker compose run --rm --no-deps web ...` 容器重跑 3c/3d 并完成；5a 出现 `2` 次 transient retry 记录但最终完成。当前停在生产 commit 前确认点，并可继续第 7 批 dry-run。

`2026-06-27` 全球赛马数据库目标已调整并完成“能力真实可用”确认：香港 HKJC 已有生产真实 dry-run 批次证据，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 已完成少量真实 proof，证明四地公开入口、parser/importer、马匹详情链路、低频限量抓取和 proof-only 离线审计可用。本次上线包从 `origin/main` 干净基线单独整理，只包含全球赛马数据库 importer、fixtures、审计工具、批次命令渲染器、OpenSpec 规格/归档、proof 证据和相关文档；刻意排除当前本地大工作树中的 QQ 推送、前台信息流、compose 端口等旁支差异。本目标不再要求本轮完成最近 60 天完整大量爬取或生产 `--commit`；后续完整爬取需另按 `docs/global_racing_next_run_checklist.md` 与 `docs/global_racing_full_crawl_runbook.md` 新开执行窗口。代码提交 `93b7007` 已推送并部署到生产；部署后 `manage.py check` 通过，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`，UK / France / US 导入命令与 batch 渲染命令可用，proof-only 审计通过，`ExternalDataImportRun(status="started")=0` 且 HKJC/netkeiba 锁为空。

`2026-06-30` 已按用户要求开始尝试香港 HKJC 慢速真实 dry-run，但仍未执行生产 `--commit`，也未写正式表。生产服务器 `/opt/umanewsbot` 当前代码为 `7b6e51b`；执行前确认 `docker compose -f docker-compose.prod.lowcost.yml ps` 中 `web/db/redis` healthy、`worker/beat/nginx` 运行，`ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`。最新 `--recent-days 60 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 160 --allow-network` 输出为 `runtime/global_racing_import/hkjc-20260630/hkjc-plan-20260630.json`，显示 `meetings=29`、`races=146`、`estimated_requests_without_horses=176`，拆为 `8` 批；该结果已不同于历史 `144` 场，因此不能把旧的 `120/144` 停点直接当作有效续跑点。随后以 `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`、`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=100` 执行精确 `race_ids=HK20260627ST02,HK20260627ST03` 小批 dry-run，输出 `runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json`：`dry_run=true`、`would_write_formal_tables=false`、`coverage_stats={"races":2,"entries":28,"results":28,"horses":28}`、`completion.is_complete=true`、`stop_reason=complete`、`horse_profiles_fetched=28`、`requests_len=30` 且全部 `status_code=200`。执行后复查 `ExternalDataImportRun(status="started")=0`、HKJC/netkeiba 锁为空，无 `umanewsbot-web-run-*` 临时容器残留，`http://umafans.run/healthz/` 和 `http://127.0.0.1/healthz/` 均返回 `200`。下一步如果继续香港，应按最新 `146` 场 plan 重新切批，从第 1 批剩余 race_ids 或重新渲染批次命令继续，而不是沿用旧 `skip-races=120`。

`2026-06-30` 用户要求继续香港 HKJC 慢速抓取到 `2024-07`。当前仍按 dry-run 执行，不写正式表、不加 `--commit`。生产已运行 `--start-date 2024-07-01 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 600 --allow-network`，输出 `runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json`：计划共 `1496` 场、`75` 个 20 场批次，请求日志 `254` 条，其中 `253` 条 HTTP `200`；最后一个 plan 批次覆盖 `2024-09-11` 与 `2024-09-08`，说明 `2024-07-01` 至 `2024-09` 之间没有更早的 HKJC 本地 `HV/ST` 赛日进入该计划。此前已在生产 `runtime/global_racing_import/hkjc-20260701-to-202407/run_hkjc_slow_dryrun_to_202407.sh` 启动后台慢速 dry-run worker，按每 `5` 场一个 mini-batch、`HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`、`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=140`、批次间暂停 `60` 秒执行；`races=3-7/1496` 与 `races=8-12/1496` 已通过校验。为部署 `operate-multiregion-news-production`，已按运行手册先暂停该 dry-run worker 和临时 `umanewsbot-web-run-*` 容器，状态文件 `hkjc-slow-dryrun.state=92`；暂停后 `ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`，未写正式表。后续若继续该长窗口 dry-run，应从 `hkjc-slow-dryrun.state=92` 对应进度恢复或重新渲染剩余批次，避免与生产部署、重建容器或 `git pull` 重叠。

## 已完成内容

- 域名购买与解析
- 正式域名 `umafans.run` / `www.umafans.run` 接入
- 本轮线上问题已修复，正式域名已可访问
- 公网服务器上 `Django + PostgreSQL + Celery + Redis + Docker Compose + Nginx` 主链路已运行
- 基础抓取、翻译、后台、前台链路已具备可继续迭代的基础
- 自动化运营 MVP 代码侧已完成：
  - 翻译成功后可进入自动评分分流
  - 支持 `auto / manual / ignored` 三类分流
  - 支持基准翻译稿与 AI 改写稿双层保存
  - 支持一致性校验、批量自动发布、自动化日志与通知日志
  - 后台候选池、详情页、编辑台、日志页已展示自动化状态与决策留痕
  - 前台展示优先级已调整为人工稿优先，其次改写稿，最后基准翻译稿
- Codex 原生工作流已完成仓库级规则配置：
  - `AGENTS.md` 与 `docs/codex_workflow.md` 定义探索、持久 spec/design、测试先行、subagent 实现、独立 `/review` 和发布授权门禁
  - 新任务持久产物写入 `docs/changes/<slug>/`；`.codex/skills/plan-eng-review` 仅在缺少通用原生方案审核能力时作为 fallback
  - `.codex/agents/` 提供 `application / integration / operations` 实现代理，以及 `reviewer / security-scanner` 只读审核代理
  - `openspec/config.yaml` 与既有 OpenSpec artifacts 只作 legacy 兼容；相关 skills、workflow-spine、CLI phase 和 journal 不再是新流程入口或门禁
- 专有术语候选发现与待标注池已完成：
  - 支持马名、比赛名、骑手名和马主名发现
  - 支持候选去重、证据聚合、工作人员审核和安全写入正式术语
  - 已完成 69 项测试与本地浏览器功能验收
  - 生产默认关闭，等待灰度启用

## 当前进行中的 OpenSpec change

- `start-hkjc-data-import-and-global-spikes`：已完成实现、生产部署、验证和归档；生产服务镜像来自 `b0361cf`。已在生产执行一次 HKJC fixture 样本 commit（`run_id=1960`），但未启用 HKJC 真实网络持续抓取，也未启用英法美正式导入。
- `connect-real-global-racing-databases`：本轮已按用户调整后的“能力真实可用”口径完成并归档；香港 HKJC 生产真实 dry-run 证据成立，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 少量真实 proof 成立，四地 importer、低频限量抓取、proof-only 审计和后续完整抓取门禁已可用。最近 60 天完整大量爬取和任何生产 `--commit` 不属于本轮完成口径，后续需要新执行窗口。

## 本轮问题简述

本轮线上问题并不是单一故障，而是多层运行态与仓库预期不一致叠加导致：

- 早期曾出现 DNS 解析未生效或本地查询返回 `NXDOMAIN`
- 服务器曾运行旧版 `nginx` 配置，仍保留 `80 -> 443` 跳转逻辑
- 服务器 `.env` 曾保留旧版 IP + HTTPS 强制配置
- 服务器运行中的 commit 一度与仓库当前预期不一致
- 最终通过对齐服务器代码版本、运行态配置、域名配置，完成正式域名 HTTP 接入修复

## 当前线上状态

- 线上域名已通
- 正式域名 `umafans.run` / `www.umafans.run` 可访问
- 自动化运营 MVP 已上线
- 公开首页资讯流升级已上线生产：`/` 使用公开站点专用 `public.css`、头条、普通新闻流和原站热度模块；移动 H5 已展示头条 + 高密度左文右图列表；移动端首屏密度 follow-up 已上线，390px 视口首屏可见 4 条普通新闻卡
- 自动化能力通过 `.env` 中 `AUTOMATION_ENABLED` 控制，当前已进入灰度运行与质量观察阶段
- 已核实线上 `AUTOMATION_ENABLED=true`、`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true`，当前按“基准翻译稿自动发布 + 高价值 warning 邮件告警”灰度运行
- 术语候选发现代码已部署到生产（`e2e3e07`，迁移 `0006` 已应用），`TERM_DISCOVERY_ENABLED=false` 默认关闭，等待单篇抽检后灰度开启
- `2026-06-24` 已完成 QQ Bot / OneBot 生产运行态配置：独立 NapCat 容器 `umanewsbot-onebot-1` 已启动，OneBot HTTP 仅绑定服务器 `127.0.0.1:3000` 并通过 Docker 网络别名 `onebot` 给应用访问，测试群 `1026525240` 已写入 `PushTarget`，OneBot 直连与 Django `BotPusher` 均已成功发送测试消息。
- `2026-06-25` 生产服务器运行 `7f54f13`：netkeiba 新着顺 / 访问量榜 / 注目数榜调度已加载为每小时 `00/16/26` 分，后台已具备来源健康摘要；候选详情页和文章编辑台已具备原文选区快速加入术语库，以及新增术语后 15 秒一次性浮层“应用到当前稿”。

## 下一步优先级

1. 继续观察公开首页资讯流生产运行，重点确认 `/`、`/news/<article_id>/`、旧非纯数字 `/news/<slug>/` 跳转、图片、`public.css`、移动 H5 首屏密度和自动发布内容长期表现
2. 生产迁移已于 `2026-06-07` 完成；下一步在生产做单篇手动重新发现并抽检术语候选质量，确认后灰度启用 `TERM_DISCOVERY_ENABLED`
3. 观察自动化发布质量与 `AutomationLog`
4. 补充翻译 warning 可视化和术语库补全流程
5. 继续观察 QQ Bot 测试群灰度推送，必要时通过 `QQ_PUSH_ENABLED=false` 暂停自动发送
6. 继续观察 netkeiba `00/16/26` 分错峰抓取在连续小时内生成 `CrawlJob`，并抽检后台来源健康摘要
7. 对 `expand-international-racing-coverage` 做一次上线前整体 review；后续进入 PR / 部署前，需要重点确认迁移窗口、国际新闻源灰度启用顺序、HKJC payload 小样本和生产外部导入锁状态
8. HTTPS / 证书接入
9. 部署稳定化与监控 / 备份 / 回滚完善
10. 继续低批量观察 `refine-automation-publish-gates` 上线后的 warning 邮件、重复内容阻断、候选池门禁展示和自动发布结果

## 2026-06-25 榜单重点新闻 QQ 推送规划

- 已形成协调总纲：`docs/ranked_news_push_plan.md`。该文档只作为本轮计划说明，不作为 OpenSpec 长期能力规格。
- 本轮拆为三个 OpenSpec 子 change：`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls`。
- 推送策略方向：`QQ_PUSH_SCOPE` 继续表示“全推 / 重点推”，重点推送的判定方式由后续配置承载；本期统一实现 `ranked` 榜单策略，即只推 `netkeiba:access` 与 `netkeiba:attention` 新闻。
- QQ 推送 blocker 判断必须复用现有 `NewsArticle.gate_blockers` / `gate_issues.severity=blocker` 结构化门禁结果，不在 QQ 服务里重新实现一套发布门禁。
- 归档状态：`add-qqbot-auto-push` 已先归档为正式 `qqbot-auto-push` 规格，随后本轮三个子 change 已归档到 `openspec/changes/archive/2026-06-25-*` 并同步正式规格。后续仍建议维护者定期清理其他已完成的 active change。
- `elevate-ranked-netkeiba-sources` 已完成并部署生产：`upsert_article_from_draft()` 会将同一 netkeiba 文章从 `latest` 提升为首次命中的 `access` 或 `attention`，二者之间不互相覆盖，`latest` 也不会覆盖榜单来源；每次命中仍创建 `NewsSnapshot`。入库结果新增 `source_elevated` 稳定信号，且仍兼容旧的 `article, created = ...` 解包方式。
- `push-ranked-news-to-qq` 已完成并部署生产：新增 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`high_value_only` 下只推 `netkeiba:access` / `netkeiba:attention` 且无 blocker 的公开文章；已公开文章被榜单来源提升时会触发 QQ 自动推送编排，并继续依靠 `QQPushDelivery(article, target)` 唯一约束去重。QQ delivery 真正发送前也会复检推送资格，若文章后来出现 blocker 或不再符合范围，会标记为 `skipped/not_eligible`，不会继续发群消息。
- `use-article-id-public-urls` 已完成并部署生产：`NewsArticle.public_path` 改为 `/news/<article_id>/`，公开详情页可通过文章 ID 访问，非纯数字旧 slug URL 会跳转到 ID URL；首页、热门列表、后台前台查看入口和 QQ 自动推送消息均继续通过 `article.public_path` 使用 ID URL。
- 本地已通过完整 `stable` 测试、三个子 change 的严格校验、`openspec validate --all` 和 `git diff --check`；生产已通过容器重建、Django check、外部健康检查、首页检查、ID URL 与旧 slug 跳转 smoke test。

## 当前已知风险与待确认项

- 公开首页资讯流升级已部署生产；后续仍需观察真实访问、图片加载和自动发布内容在首页的长期表现
- 当前正式域名阶段仍以 HTTP 为主，HTTPS 证书尚未接入完成
- 需要把 HTTP 阶段的临时安全配置，在 HTTPS 切换时重新收紧
- 需要继续确认抓取调度、翻译调度、发布链路在正式域名环境下的长期稳定性
- 自动化发布涉及内容安全，生产首轮建议低频、低批量、保守开关启用
- AI 改写真实效果依赖模型配置与术语库质量，需继续通过后台人工抽检
- 邮件通知首版已实现；短信 / 微信通知当前只保留日志与配置位；QQ / OneBot 真实发送网关已在生产配置并通过测试消息，自动推送代码已部署并进入测试群灰度
- 需要补足更标准的部署基线、回滚与备份演练
- QQ Bot 自动推送已在生产开启测试群灰度；如出现 QQ 客户端发送异常，优先通过 `QQ_PUSH_ENABLED=false` 停止自动推送并保留 OneBot 网关排查。

## 2026-06-23 QQ 群自动推送 OpenSpec change

### 当前实现

- 新增 OpenSpec change：`add-qqbot-auto-push`。
- 新增自动 QQ 推送交付模型，以“文章 x QQ 群”为唯一粒度记录状态、尝试次数、最大尝试次数、错误类型、错误信息、OneBot 响应、消息 ID、最后尝试时间和成功时间。
- 自动推送默认关闭：`QQ_PUSH_ENABLED=false`。
- 自动推送默认范围：`QQ_PUSH_SCOPE=high_value_only`，首版高价值口径为 `score_total >= AUTO_REVIEW_THRESHOLD`；也支持 `all_public`。
- 发布入口已接入自动推送入队：人工发布、`publish_article()` helper 和自动发布成功后都会在开关开启时异步进入 QQ 推送编排。
- 推送前检查 `SITE_URL + article.public_path` 是否可访问；URL 不可访问和 OneBot 发送失败分别记录为 `url_unavailable` 与 `send_failed`。
- 自动交付在领取一次发送尝试前会先检查 OneBot `/get_status`，若网关离线、登录态失效或状态检查失败，则记录 `send_failed` 错误摘要并保持可恢复重试状态，不调用 `/send_group_msg`，也不增加 `attempt_count`。
- 自动交付会先原子领取尝试再执行 URL 检查和 OneBot 发送，避免重复任务并发消耗重试次数。
- OneBot HTTP 200 但 JSON 返回业务失败时按 `send_failed` 记录，不会误标记为成功。
- `sending` 状态超过 `QQ_PUSH_SENDING_STALE_SECONDS`（默认 600 秒）后允许后续任务重新领取，避免 worker 异常后长期卡住。
- 自动发送按目标群最近一次尝试时间做最小间隔保护，`QQ_PUSH_MIN_INTERVAL_SECONDS` 默认 60 秒，避免批量发布或补推时压垮 QQ / NapCat 发送通道。
- 自动推送只读取 `PushTarget.is_active=true` 的群；`is_default` 保留给后台手动推送默认目标。
- Django Admin 新增自动交付记录查看入口，并在文章详情中展示交付内联记录。

### 当前启用策略

- 生产已配置 NapCatQQ / OneBot v11 网关、测试群和 access token。
- 生产 `.env` 已设置 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，当前只等待自然榜单新闻触发测试群推送。
- 生产已部署迁移 `stable.0010_qqpushdelivery`，并设置 `QQ_PUSH_ENABLED=true` 进入测试群灰度。
- OneBot API 不得公网裸露；优先 Docker 内网 `http://onebot:3000`，临时映射只能绑定 `127.0.0.1`。

### 验收记录

- OneBot 直连和 Django 应用侧短消息均已成功发送到测试群 `1026525240`。
- 生产批量补推 126 篇公开文章时，交付记录成功创建并进入有限重试；NapCat / QQ 客户端随后返回 `网络连接异常`，系统正确记录为 `send_failed` 且未误标为成功。
- 已补充 `QQ_PUSH_MIN_INTERVAL_SECONDS` 节流保护，后续自动任务按目标群最小间隔重排，降低 QQ 风控和客户端异常风险。
- 2026-06-25 重新扫码登录 NapCat 后，Django `BotPusher` 短消息发送成功，`qq_auto_push_article_task -> qq_push_delivery_task -> OneBot` 自动任务链路已用真实公开文章验证成功，`QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=all_public` 在生产 worker 生效。
- 2026-06-25 存量补推按 65 秒间隔运行并成功发送 79 条交付记录；按当前验收判断，不再要求继续补推全部历史公开新闻，剩余历史 `retrying/send_failed` 记录保留用于后台排查，不影响后续新发布文章自动推送。
- 2026-06-25 榜单重点推送部署后，生产 worker 已确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 生效；本次不补推历史公开新闻，后续只等待自然榜单新闻推送。
- 2026-06-26 QQ 推送中断排查确认根因是 NapCat 快速登录态失效，日志出现“登录态已失效，请重新登录 / 你的用户身份已失效”。处理过程为：先把生产 `.env` 临时切到 `QQ_PUSH_ENABLED=false` 并重启 `worker / beat` 暂停自动推送；用户重新扫码登录后，OneBot `/get_status` 返回 `online=true`，`/get_login_info` 返回 QQ `1577955464`，群列表包含 `1026525240`，Django 应用侧测试消息发送成功；随后恢复 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 并重启 `worker / beat`。本次不补推全部已发表新闻，后续只等待自然榜单新闻触发。
- 2026-06-26 已将 OneBot 离线防护部署生产，服务器 `/opt/umanewsbot` 从 `849004c` 更新到 `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`。部署后 `web` healthy，迁移显示 `No migrations to apply`，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `http://umafans.run/healthz/` 均返回 `200`；worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`BotPusher().is_online()` 返回 `(True, '')`，测试群 `1026525240` 发送部署验证消息成功，返回 `message_id=1364343902`。

## 2026-06-24 自动发布门禁优化本地实现

- OpenSpec change：`refine-automation-publish-gates`，当前 `tasks.md` 已完成本地实现和验证。
- 新增配置：
  - `AUTO_REWRITE_ENABLED=false`：默认跳过 AI 改写前置。
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`：默认使用基准翻译稿作为自动发布内容源。
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`：访问量榜和注目数榜评分阶段放行。
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`：高价值 warning 初期告警收件人示例。
- 新增数据字段：
  - `NewsArticle.gate_issues` 保存结构化门禁 issue。
  - `WorkflowStatus.DUPLICATE` 描述高度重复内容。
  - `duplicate_of / duplicate_score / duplicate_reason` 保存重复检测解释。
  - `automation_warning_email_signature / automation_warning_email_sent_at` 用于 warning 邮件 24 小时去重。
- 迁移 `0009_automation_publish_gates` 会导入首批非马名普通词固定译法，包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、`ラジオ`、`ダート`、`マイル`、`スプリント`、`クラス`、`チャンス`、`キャリア`、`イメージ`、`デビュー`、`ゲート`。
- 后台候选列表、候选详情、自动化日志和 Django Admin 已展示 blocker / warning / info、重复检测结果和相似文章信息。
- `2026-06-24` review 返修：
  - 重新校验通过且当前不再重复的文章，会清理旧 `duplicate_of / duplicate_score / duplicate_reason`，并把旧 `duplicate` / `pending_review` 状态恢复为可进入自动发布批次的候选状态，避免显示 `publish_ready` 但被批发布排除。
  - 候选列表与候选详情中的相似文章现在链接到后台候选详情 `/admin/candidates/<id>/`。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AutomationFlowTests stable.tests.ConsoleFlowTests --noinput`：通过，23 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，106 项。
  - `openspec validate refine-automation-publish-gates --strict`：通过。

### 生产上线结果

- PR：GitHub PR #4 `[codex] refine automation publish gates` 已 squash merge。
- 生产提交：服务器 `/opt/umanewsbot` 已从 `71ab966` 更新到 `42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 已设置生产灰度配置：
  - `AUTO_REWRITE_ENABLED=false`
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`
  - `HIGH_VALUE_WARNING_SCORE_THRESHOLD=90`
  - `AUTO_DUPLICATE_LOOKBACK_DAYS=7`
  - `AUTO_DUPLICATE_HIGH_THRESHOLD=0.86`
  - `AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72`
  - `AUTOMATION_WARNING_EMAIL_ENABLED=true`
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`
  - `AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24`
- 容器：`web` healthy，`db / redis` healthy，`worker / beat` up。
- 迁移：`stable.0009_automation_publish_gates` 已应用；运行时确认 `WorkflowStatus.DUPLICATE=True`，首批 `non_horse_common_word` 普通词种子数量为 `14`。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/` 返回 `200`。
- 部署注意：重启初期日志曾出现一次 `automation_warning_email_sent_at` 字段已存在异常，判断为容器启动自动迁移与手工迁移并发撞车；后续日志显示 `No migrations to apply`，`showmigrations stable` 显示 `0009` 已应用，服务健康检查持续返回 `200`。

## 2026-06-24 抓取新鲜度与 JRA 日期解析本地实现

- OpenSpec change：`fix-crawl-freshness-and-jra-date-parse`，当前已完成本地实现并于 `2026-06-25` 部署生产。
- 修复范围：
  - JRA 官方新闻日期解析兼容 `2026年5月31日`、`5月31日`、零填充和非零填充日期。
  - JRA 无年份日期优先使用列表月份或 URL 年份；缺少上下文时使用当前东京年份，若推断日期晚于当前东京日期超过 7 天则回退上一年。
  - JRA 列表中单条日期异常会跳过该条并继续处理同一列表中其他新闻；整体结构或网络失败仍会记录为 JRA 抓取失败。
  - netkeiba 访问量榜和注目数榜从每天 `00:00/12:00`、`00:05/12:05` 调整为小时级抓取，并在 review 返修后避开新着顺和周日重赏高频补抓：新着顺每小时 `00` 分，访问量榜每小时 `16` 分，注目数榜每小时 `26` 分。
  - 内置来源定义同步更新访问量榜 / 注目数榜 `crawl_interval_minutes=60` 和来源备注，避免后台展示、异常检测与实际调度不一致。
  - 后台工作台和来源列表新增来源健康摘要，区分“运行中”“运行超时”“成功”“成功无新增”“失败”“长时间未运行”，并展示最近新增数、重复数或错误摘要；超过 60 分钟仍未完成的运行中记录会显示为疑似卡住，停用来源不参与“长时间未运行”判定。
  - JRA 单篇详情结构异常被跳过时，跳过摘要会同时写入本轮 `CrawlJob.error_message` 和 `NewsSource.last_crawl_message`，便于事后按 job 追溯。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.ConsoleFlowTests stable.tests.CrawlAutoTranslateTests --noinput`：通过，25 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，118 项。
  - `openspec validate fix-crawl-health-running-and-schedule-stagger --strict`：通过。
  - `openspec validate --all`：通过，7 项。
- 生产部署：
  - 服务器 `/opt/umanewsbot` 已于 `2026-06-25` 更新到 `7f54f13`，部署前 `.env` 备份为 `.env.backup.three-changes-20260625_003714`。
  - `web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`。
  - 运行态确认 `crawl-netkeiba-latest-hourly / access / attention` 分钟分别为 `0 / 16 / 26`，内置来源定义中三者 `crawl_interval_minutes=60`。
  - 后续仍需等待自然调度，确认访问量榜 / 注目数榜在连续小时内按 `16 / 26` 分生成新 `CrawlJob`。

## 2026-06-23 前台发布判定代码阅读结论

- 公开前台首页 `/` 与详情页 `/news/<article_id>/` 只展示 `workflow_status=published` 且 `published_to_web_at` 非空的 `NewsArticle`；旧的非纯数字 `/news/<slug>/` 兼容入口会跳转到对应 ID URL。
- 抓取入库的新稿默认是 `workflow_status=pending_translation`，不会因为来自 `netkeiba` 新着、访问榜、注目榜或 `JRA` 官方新闻而直接进入前台。
- 翻译成功后文章进入 `pending_edit`；若 `AUTOMATION_ENABLED=true`，会触发自动化评分、改写与校验链路。
- 自动化评分为 `auto` 的文章也不会立刻公开；必须完成改写、通过一致性校验成为 `automation_status=publish_ready`，再由批量自动发布任务写入 `workflow_status=published` 与 `published_to_web_at` 后才进入前台。
- 自动化硬规则会把重复稿、正文过短或为空、疑似乱码/结构损坏、疑似广告或导航短页直接置为 `ignored`，默认不进入前台。
- 长采访或引语较多、翻译未成功、缺少基准中文翻译等会转为 `manual` / `pending_review`，需要人工审核后发布。
- 人工发布通过运营后台文章编辑页完成时会写入 `workflow_status=published`、`published_to_web_at`、`published_by_mode=manual`；无封面时需要二次确认。Django Admin 或后台 API 若只改 `workflow_status` 而不补 `published_to_web_at`，仍不会被公开前台接收。

## 2026-06-23 外部赛马数据导入 OpenSpec 提案

- 已创建 OpenSpec change：`add-netkeiba-horse-data-import`。
- 提案目标：使用 `keibascraper` / netkeiba 作为低频离线导入来源，先抓取近两年比赛、出走、赛果、赔率、马匹血统和马匹履历数据，保存结构化字段与原始 payload，并派生本地马名索引。
- 关键约束：导入默认关闭，不加入自动全量调度；生产必须人工显式执行、强制限速、随机抖动、小批量、可暂停、可恢复；导入失败不得影响新闻抓取、翻译、自动化发布或公开前台。
- 当前状态：仅完成 proposal、design、delta spec 和 tasks，尚未实现代码，尚未执行真实爬取。

## 2026-06-19 公开首页资讯流升级 OpenSpec 主 change

### 已归档产物

- 正式规格：`openspec/specs/public-home-info-feed/spec.md`
- 归档目录：`openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`
- 归档内保留 proposal、design、delta spec、tasks 和 `.openspec.yaml`

### 主范围

- Web 端：首页升级为轻导航、主头条、普通新闻流和右侧热门/重点辅助模块。
- 移动 H5：首页升级为轻顶部、轻量头条和高密度左文右图新闻列表。
- 数据层优先复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，不新增数据库模型。
- 公开站点样式从后台 `console.css` 中解耦，后续实现应新增公开站点专用样式入口。
- 文章详情页与首页共享公开站点视觉体系，并保持已有有效稿件字段优先级。
- 后续实施采用严格 TDD：发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源必须逐行为执行 RED -> GREEN -> REFACTOR，禁止一次性批量写完全部测试后再实现。
- 热门代理必须在有限候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。

### 明确非目标

- 不做原生 App、个性化推荐、无限滚动、站内浏览量、站内评论或用户系统。
- 不在本轮新增手工置顶、推荐位、专题、搜索频道或赛事日历模型。
- 不改抓取、翻译、AI 改写、自动发布、QQ 推送或 Docker Compose 主架构。

### 本地实现结果

- 公开首页 `/` 已升级为公开站点专用模板和 `stable/public.css`，不再以后台 `console.css` 作为主要样式入口。
- 首页数据层复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，提供 `headline_article`、`feed_articles`、`latest_articles` 和 `hot_articles`。
- 头条选择按近期范围、赛事优先级、自动评分、封面和发布时间排序；低量内容回退到近 7 天或最新已发布文章。
- 热门代理在有限已发布候选集内批量读取上游访问/注目快照，无快照时按自动评分和发布时间回退；页面只标注“原站热度/原站排行”，不包装为本站评论或浏览量。
- 移动 H5 首页采用轻头条 + 左文右图高密度列表，普通卡片在 390px 视口验收中稳定为约 128px 高，缺图卡不破坏列表布局。
- 详情页复用公开站点 base，继续展示有效标题、摘要、正文、来源、原文链接和发布时间，并完成窄屏阅读排版验收。
- 本轮未新增数据库模型、迁移、生产配置或部署运行手册步骤。

### 校验结果

- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过。
- `openspec validate --all`：归档前通过；归档并同步正式 spec 后再次通过。
- `/plan-eng-review upgrade-public-home-info-feed`：通过。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，88 项。
- 本地开发服务器浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；无横向溢出，图片加载正常，移动普通卡高度受控，桌面主列与右侧热门模块不重叠。

### 生产部署结果（2026-06-22）

- GitHub PR #1 从 draft 转为 ready 后合并到 `main`，merge commit 为 `e834f58`，包含实现提交 `1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`；部署前备份 `.env` 为 `.env.backup.20260622_140844`。
- 生产使用低成本 compose 执行 `./deploy_lowcost.sh`：重建 `web/worker/beat`，`migrate` 显示 `No migrations to apply`，`collectstatic` 成功处理 `stable/public.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`。
- 首页 HTML 已引用 `/static/stable/public.2eec24723b45.css`，页面包含 `home-page`、`headline-card`、`news-card` 和“原站热度”；不再引用后台 `console.css`。
- 浏览器生产验收通过：桌面端显示轻导航、头条和热门模块；390px 移动端普通新闻卡约 `128px` 高，首屏头条后可见 3 条普通新闻，无横向溢出；新闻详情页可打开，标题、封面和公开详情结构正常，控制台无错误。

### 移动端首屏密度 follow-up（2026-06-22）

- 在不改变首页数据层、公开 URL、模板结构或普通新闻卡尺寸的前提下，后续小幅收紧移动端首页视觉密度。
- 调整范围仅限 `server/stable/static/stable/public.css` 的 `max-width: 599px` 移动端规则：
  - 顶部和页面内边距略收紧。
  - 移动端头条图片从 `16 / 9` 改为 `16 / 7`。
  - 移动端头条摘要隐藏，仅保留来源时间和两行标题。
  - 普通新闻卡继续保持约 `128px` 高和右侧缩略图结构。
- 本地临时 SQLite + 浏览器验收结果：390px 视口下头条高度约 `250px`，第一张普通新闻卡提前到 `top=381`，首屏可见 4 条普通新闻卡，无横向溢出，控制台无错误。
- 生产部署结果（2026-06-23）：GitHub PR #2 合并到 `main`，merge commit 为 `04e2ee9`；服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`，部署前备份 `.env` 为 `.env.backup.20260623_120201`。
- 生产 `./deploy_lowcost.sh` 执行成功：`migrate` 显示 `No migrations to apply`，`collectstatic` 后首页引用 `/static/stable/public.9aaf4b105424.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`；首页包含 `home-page`、`headline-card`、`news-card` 和“原站热度”，不再引用 `console.css`。
- 浏览器生产验收：390px 移动端头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通卡约 `128px` 高，首屏可见 4 条普通新闻卡，无横向溢出；详情页公开结构、封面和标题正常，控制台无错误。

## 2026-06-07 术语候选发现生产部署纪要

### 部署内容

- 服务器 `/opt/umanewsbot`：`git pull origin main` 从 `7123e4e` 快进到 `e2e3e07`
- 迁移 `0006`（纯新增 `TermCandidate` / `TermCandidateEvidence` 两表）已应用；`web` 启动脚本会自动迁移，显式 `migrate` 显示 `No migrations to apply`
- `.env` 追加并保持关闭：`TERM_DISCOVERY_ENABLED=false` / `TERM_DISCOVERY_PROVIDER=rules` / `TERM_DISCOVERY_MIN_CONFIDENCE=60`
- 用低成本 compose `docker-compose.prod.lowcost.yml` 重建 `web/worker/beat`，`db/redis/nginx` 未动

### 迁移前备份（可回滚）

- `.env.backup.20260607_033207`
- 数据库快照 `backups/pre-0006-20260607_033207.sql`（74M，`horse_news` 库，含 `PostgreSQL database dump complete` 标记）

### 上线后验证

- 容器 `web/db` healthy、`worker/beat` up；`manage.py check` 0 issues
- 候选/证据模型可查、计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`
- `worker` 近 200 行日志无报错；核对 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 未变更

### 回滚方式

- 停用功能：将 `TERM_DISCOVERY_ENABLED=false`（当前即为关闭），重启 `web` 与 `worker` 即可，无需回滚迁移或删除候选数据
- 整体回退：用上面的 `.env` 备份与数据库快照还原

## 最近一次翻译稳定性修复

- 现象：部分文章翻译失败，错误为 `Translation response changed unknown horse names`
- 原因：未知马名校验过于严格；模型没有原样保留疑似未收录马名时，系统会让整篇翻译失败
- 修复：
  - 翻译 prompt 中对未知马名使用 `__UMA_KEEP_n__` 占位符保护
  - 模型返回后将占位符还原为原始日文马名
  - 若模型仍未保留未知马名，不再让整篇失败，而是写入 metadata warning 后接受译文
- 验证：
  - 新增未知马名占位符还原测试
  - 新增未知马名仍缺失但不阻断翻译的测试
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 通过，45 项

## 自动化内容运营 MVP 开发纪要

### 本轮新增能力

- `NewsArticle` 增加自动化字段：分流模式、风险等级、自动化状态、评分、决策原因、基准翻译稿、改写稿、自动发布时间与错误信息
- 新增 `AutomationLog`，记录评分、改写、校验、发布、通知各阶段过程
- 新增 `NotificationLog`，记录邮件 / 短信 / QQ / 微信通知状态；MVP 真实发送只启用邮件
- 新增自动化服务：
  - `stable.services.automation`
  - `stable.services.rewriting`
  - `stable.services.validation`
  - `stable.services.notifications`
- 新增 Celery 任务：
  - `process_article_automation_task`
  - `score_article_task`
  - `rewrite_article_task`
  - `validate_rewrite_task`
  - `auto_publish_batch_task`
  - `send_notification_task`
  - `detect_automation_anomalies_task`
  - 新增 Celery Beat 调度：
    - 每 15 分钟批量自动发布
    - 每 30 分钟检测自动化异常
  - 自动发布批量规则已调整为：
    - 常规时段每批最多 4 篇
    - 每周日北京时间 13:00-16:00 每批最多 10 篇
    - 调度频率仍为每 15 分钟一次

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，40 项测试

### 生产启用前注意

- 必须先部署代码并执行迁移 `python manage.py migrate`
- 初次部署建议 `AUTOMATION_ENABLED=false`
- 确认后台可看到自动化字段和日志后，再切换 `AUTOMATION_ENABLED=true`
- 当前自动发布策略为常规每批 4 篇、周日 13:00-16:00 每批 10 篇，并定期人工抽检自动发布稿

## 专有术语候选发现与待标注池

### 当前实现

- 新增 `TermCandidate` 与 `TermCandidateEvidence`，分别保存待审核术语和按文章聚合的来源证据。
- 首版支持马名、比赛名、骑手名和马主名四类实体。
- 新文章入库后可旁路触发发现任务；发现失败不会阻断抓取、翻译、改写或发布。
- 候选会与正式 `TermEntry.source_ja`、日文别名及已有候选去重；停用正式术语也参与去重。
- 后台新增“术语候选”列表、详情、单篇重新发现、接受、修改后接受、合并、拒绝、忽略和保守批量拒绝/忽略。
- 规则或 AI 发现结果不会直接写入正式术语库，只有工作人员明确接受后才创建 `TermEntry`。

### 当前启用策略

- `TERM_DISCOVERY_ENABLED=false`：默认关闭。`2026-06-07` 已在生产应用迁移并部署代码，当前处于“先关后开”灰度阶段，待单篇抽检后再开启。
- `TERM_DISCOVERY_PROVIDER=rules`：首版使用保守规则发现器。
- `TERM_DISCOVERY_MIN_CONFIDENCE=60`：低于阈值的发现结果不进入候选池。

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，69 项。
- `openspec validate --all`：通过。
- 两种生产 Compose 配置基于 `.env.example` 检查通过。
- 已使用独立 SQLite 数据库部署本地验收环境，并通过浏览器完成筛选、单篇重跑、接受、合并、拒绝、忽略、批量操作、操作日志和别名搜索验收。

## 最近一次关键修复纪要

### 现象

- 域名已经解析到服务器 IP
- HTTP 请求被 `301` 跳转到 HTTPS
- HTTPS 请求返回 `400 Bad Request`
- 浏览器无法正常打开正式域名页面

### 排查过程

- 先确认 DNS 是否已经真正打通，排除“域名未解析”的假象
- 再比对仓库当前代码与服务器实际 `HEAD`
- 检查服务器 `.env` 中的 `ALLOWED_HOSTS`、`SITE_URL`、`SECURE_SSL_REDIRECT` 等关键项
- 进入 `nginx` 容器读取真实 `/etc/nginx/conf.d/default.conf`
- 检查 `web` 容器运行态环境变量与日志
- 最终确认线上实际行为与仓库当前预期不一致

### 确认的真实根因

- 服务器并未运行到本地最新域名接入修复版本
- 服务器仍在使用旧版 `nginx` 配置，保留 `80 -> 443` 跳转与启用中的 HTTPS server block
- 服务器 `.env` 仍使用旧版 IP + HTTPS 强制配置
- `ALLOWED_HOSTS` 未包含正式域名，导致域名下请求被 Django 拒绝

### 修复动作

- 备份服务器 `.env`
- 清理或暂存本地未提交运行态差异
- 将服务器代码同步到正确版本
- 更新 `.env`，切换为正式域名 + HTTP 阶段配置
- 重建并启动 `web / worker / beat / db / redis / nginx`
- 进入容器核对真实 `nginx` 配置与环境变量，确保运行态与仓库一致

### 修复后验证结果

- `nginx` 容器加载了新版 `default.conf`
- `80 -> 443` 强制跳转已移除
- 正式域名 `umafans.run` / `www.umafans.run` 页面可打开
- 线上服务恢复到与当前仓库预期一致的状态

### 后续如何避免再次发生

- 每次部署前先确认服务器 `HEAD`，不要只看本地仓库
- 每次域名或安全策略变更时，同时核对：
  - 仓库代码
  - 服务器 `.env`
  - `nginx` 容器内真实配置
  - `web` 容器内真实环境变量
- 不把聊天记录当唯一记忆来源，关键修复过程必须落文档
- 生产问题处理时，坚持“先核对运行态，再给结论”

## 2026-06-23 外部赛马数据导入实现状态

### 本地已实现

- 新增 OpenSpec change：`add-netkeiba-horse-data-import`。
- 新增 `keibascraper==3.1.5` 依赖，并通过管理命令提供 import 冒烟检查入口。
- 新增外部赛马数据表：比赛、出走表、赛果、赔率、马匹、马匹履历、马名索引、导入运行、导入错误和单来源导入锁。
- 新增 `stable.services.external_horse_data`：
  - 包装 `keibascraper.race_list()` 与 `keibascraper.load()`。
  - 项目侧强制执行网络开关、请求间隔、随机抖动。
  - 保存结构化字段与 `raw_payload`。
  - 对比赛、出走、赛果、赔率、马匹、履历做幂等 upsert。
  - 从出走表、赛果、可信单马参数派生 `ExternalHorseAlias`。
  - 单马导入仅在存在可信马名时创建马名索引，避免凭空写入错误马名。
  - 记录覆盖率统计：比赛数、出走数、赛果数、赔率数、马匹数、履历数、唯一马 ID、唯一日文马名、缺失马 ID/马名记录数。
- 新增管理命令 `import_external_horse_data`：
  - 支持默认近两年、指定年月、指定 `race_id`、指定 `horse_id`、`--horse-name`、`--dry-run`。
  - 支持 `--max-races`、`--max-horses`、`--fetch-odds`、`--no-fetch-horse-detail`。
  - 支持 `--lookup-name` 查询本地马名索引。
  - 支持 `--stats-run-id` 查看导入运行统计。
  - 支持 `--check-dependency` 检查 `keibascraper` 是否可 import。
- 新增 Celery 任务 `import_external_horse_data_task`，但未加入默认 Celery Beat 全量调度。

### 当前默认策略

- `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`。
- `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 代码已可部署迁移，但生产不会自动发起 netkeiba 请求。
- 外部数据导入当前不参与新闻抓取、翻译、AI 改写、自动发布或公开前台。

### 本地验证

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ExternalHorseDataImportTests`：通过，8 项。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，96 项。

### 生产执行提醒

- 生产首次真实导入前必须备份数据库。
- 先执行 dry-run 或单月小批量。
- 首次真实请求建议使用 8-10 秒间隔、小批量、低峰时段，不抓赔率。
- 同一来源通过导入锁避免多 worker 并发放大请求。
- 如发现异常，优先关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED` / `EXTERNAL_HORSE_DATA_ALLOW_NETWORK` 并停止任务；新表不参与主新闻链路。

### 生产首轮小批量导入结果

- 生产部署提交：`58a6e82`。
- 部署前 `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- 服务器迁移：`stable.0008_externaldataimportrun_externaldataimportlock_and_more` 已应用。
- 容器内依赖检查：`keibascraper import ok`。
- dry-run：`2026-05` 单月、小批量、最多 10 场，预计 20 个请求。
- 真实导入命令：`2026-05`、`--max-races 10`、`--max-horses 30`、不抓赔率、不补马匹详情、请求间隔 10 秒 + 2 秒抖动。
- 运行结果：`run_id=1`，`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=326`。
- 写入统计：`race_count=10`、`entry_count=151`、`result_count=143`、`horse_count=143`、`unique_horse_id_count=143`、`unique_horse_name_count=143`、`missing_horse_id_or_name_count=16`。
- 样本马名索引已写入，如 `ヴォルスター`、`ファイツオン`、`サトノエピック`。

### 后续继续导入注意

- `2026-06-24` 已补充按月续跑逻辑：再次导入同一月份时会先跳过已落库的 `ExternalRace.race_id`，只处理下一批未导入 race。
- 不建议直接一次性跑近两年全量；应继续按月、小批量、低速运行，并观察失败率和覆盖率。

### 生产第二批续跑结果

- 续跑部署提交：`a61d789`。
- 第二批真实导入：`run_id=2`，同为 `2026-05`，最多 10 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 续跑确认：`parameters.already_imported_race_count=10`，说明第二批已跳过首批落库 race。
- 运行结果：`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=316`。
- 累计写入统计：`race_count=20`、`entry_count=292`、`result_count=274`、`horse_count=274`、`unique_horse_id_count=274`、`unique_horse_name_count=274`、`missing_horse_id_or_name_count=36`。

### 生产第三批续跑结果

- 第三批真实导入：`run_id=3`，仍为 `2026-05`，最多 30 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 运行结果：`status=paused`，`success_count=30`，`failure_count=0`，`skipped_count=286`。
- 累计写入统计：`race_count=50`、`entry_count=742`、`result_count=695`、`horse_count=695`、`unique_horse_id_count=695`、`unique_horse_name_count=695`、`missing_horse_id_or_name_count=94`。
- 服务器健康检查：`/healthz/` 返回 `200`。

### 生产长循环导入中断记录

- `2026-06-24` 按用户确认启动长循环：从 `2026-05` 到 `2025-06`，每批 25 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 成功完成批次：`run_id=4` 到 `run_id=8`，均为 `2026-05`，每批 25 场，均 `failure_count=0`。
- 中断批次：`run_id=9`，`2026-05`，已成功 7 场后执行进程以退出码 `137` 中断；当时 `web/db` 容器发生重启，但 `OOMKilled=false`。
- 已人工收尾：将 `run_id=9` 标记为 `partial`，写入 `finished_at` 和 coverage，释放 `ExternalDataImportLock`。
- 中断后累计写入：`race_count=182`、`entry_count=2692`、`result_count=2518`、`horse_count=2401`、`unique_horse_id_count=2401`、`unique_horse_name_count=2401`、`missing_horse_id_or_name_count=348`。
- 当前服务状态：`web/db/redis/nginx/worker/beat` 运行，`/healthz/` 返回 `200`。按“报错退出则停止”约定，未继续启动后续导入。

## 后台原文选区快速加入术语库

- OpenSpec change：`add-selection-term-quick-add`。
- 本地分支：`codex/add-selection-term-quick-add`。
- 实现时间：`2026-06-24`。
- 状态：已于 `2026-06-25` 合并到 `main` 并部署生产，OpenSpec 已归档为 `openspec/changes/archive/2026-06-24-add-selection-term-quick-add/`。

### 已实现能力

- 候选详情页和文章编辑台的原文标题、原文正文已标记为可选区来源。
- 两个页面都新增“快速加入术语库”入口；管理员可点击“使用当前选区”填入日文原词，也可手工粘贴作为无 JavaScript fallback。
- 快速表单字段包含日文原词、术语类型、中文译词；术语类型默认 `horse`（马名），但可改为赛事、骑手、调教师、马主、牧场、赛马场、机构、固定译法或其他。
- 后端新增文章上下文 POST 入口 `console-article-quick-term-create`，路径为 `/admin/articles/<article_id>/quick-term/`。
- 创建正式术语时复用 `validate_term_payload()`，继续执行正式术语库的类型、重复、比赛等级、启用状态和优先级校验。
- 快速创建默认写入：`is_active=true`、`priority=0`、`race_grade=""`、`aliases_ja=[]`、`aliases_zh=[]`，并在 `notes` 记录来源文章 ID 和标题。
- 创建成功后留在当前页面并显示成功消息，同时写入 `OperationLog`。
- 创建失败时不写入 `TermEntry`，通过 messages 展示错误；重复术语提示已有术语 ID，并提供已有术语编辑页链接。

### 明确边界

- 快速加入术语库只写入 `TermEntry` 和操作日志。
- 不触发 `translate_article_task`，不触发自动化处理，不修改当前文章的 `title_zh`、`body_zh`、`base_translation_zh` 或 `rewrite_body_zh`。
- “新增术语后自动重新应用术语/重翻译联动”仍属于后续 change，不在本次实现中。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。

### 验证结果

- `DB_ENGINE=sqlite python manage.py check` 已通过（本地使用 Codex bundled Python 执行）。
- `DB_ENGINE=sqlite python manage.py test stable.tests.ConsoleFlowTests --verbosity=2` 已通过；本轮按 OpenSpec 场景补齐非法术语类型、换行误选整段、文章不存在、非联动状态保持和原文选区脚本限制等测试。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --verbosity=2` 已通过，126 个测试全部通过。
- `openspec validate add-selection-term-quick-add --strict` 已通过。
- 本地浏览器验收使用临时 SQLite 后台：
  - 候选详情页可创建术语并返回当前候选页。
  - 候选详情页重复创建同类型同日文原词时显示失败提示和已有术语编辑链接。
  - 编辑台快速术语入口已验证不会提交外层文章编辑表单；提交成功后返回编辑台。
  - 无选区点击“使用当前选区”不会乱填，提示需在原文标题或正文中选择短词。

## 后台快速术语创建后的当前稿联动提案

- OpenSpec change：`reapply-terms-after-quick-add`。
- 创建时间：`2026-06-24`。
- 当前状态：本地实现和验证已完成；review 后的浮层交互和多标签页 session pending 返修已于 `2026-06-25` 完成，并已随 `7f54f13` 部署生产。OpenSpec 已归档为 `openspec/changes/archive/2026-06-24-reapply-terms-after-quick-add/`。
- 目标：在候选详情页或文章编辑台快速创建正式术语后，为当前文章提供明确的后续动作：
  - 一次性“应用该术语到当前稿”：只把刚创建的指定术语应用到当前文章整篇已有中文字段，不调用翻译模型，不重扫整个正式术语库。
  - 页面级“重新翻译”：复用现有 `translate_article_task`，异步重新走翻译链路；不属于术语成功浮层，若页面已有按钮则不新增。
- 关键边界：
  - 不做全站批量重翻译或批量重应用。
  - 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口。
  - 不自动发布文章，不改变前台发布过滤规则。
  - 默认保护 `manually_edited_fields` 中的人工标题、正文、摘要和推送摘要，不在无确认时覆盖人工稿。
  - 术语应用必须记录文章、用户、来源术语、更新字段和跳过字段；页面级重新翻译继续记录文章、用户和任务触发结果。
- 实现范围：
  - 新增指定术语应用服务函数，只替换刚创建术语的日文原词和日文别名。
  - 新增后台 POST 入口 `/admin/articles/<article_id>/apply-created-term/`。
  - quick-create 成功后通过 session 多 pending 字典提供一次性后续动作上下文；候选详情页和编辑台只消费匹配当前文章与页面上下文的 pending follow-up。
  - `candidate_retranslate` 改为安全返回，并继续作为页面级重新翻译入口记录任务触发结果；术语成功浮层不提供重翻译入口。
  - 候选详情页和编辑台已改为页面上方浮层：`术语【日文名（中文名）】已添加，点击此处立即应用到文章中`；浮层只承载当前术语应用，不承载重新翻译。
  - 旧的术语表单内嵌“刚创建术语”面板和 `retranslate-created-term-*` follow-up 表单/按钮已删除；重新翻译仅保留页面级既有入口。
  - 浮层点击“点击此处”立即应用，不再二次确认；点击关闭 icon、应用成功、当前页面新术语浮层出现、关闭页面或 15 秒超时后消失。
  - 浮层不阻塞选区、滚动、编辑和其他不离开当前页面的点击行为。
  - session follow-up 已从全局单槽改为多 pending 结构，避免多标签页之间互相覆盖；渲染不匹配文章或上下文时不会消费其他 pending follow-up。
  - 后端不额外增加一次性 token 限制；当前后台仅单人可信使用，手工构造接口请求被视为可接受风险。
- TDD 测试：
  - `2026-06-25` 已先在 `server/stable/tests.py` 补充完整测试约束，覆盖浮层文案、关闭/15 秒 DOM 合同、旧内嵌面板不存在、`retranslate-created-term-*` 不存在、多 pending、不匹配页面不消费 pending、同页新术语替换旧浮层，以及应用术语不派发翻译任务。
  - 红灯阶段结果：未实现新交互前，`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ConsoleFlowTests --noinput` 为 31 项中 5 项失败，失败集中在旧内嵌面板和单槽 session。
- 本轮验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.ConsoleFlowTests --noinput`：通过，31 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，135 项。
  - `openspec validate reapply-terms-after-quick-add --strict`：通过。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。
- 规格校验：`openspec validate reapply-terms-after-quick-add --strict` 已通过。

## 2026-06-25 外部马名索引接入识别链路本地实现

- OpenSpec change：`use-external-horse-alias-for-name-recognition`。
- 创建时间：`2026-06-25`。
- 当前状态：本地实现、验证、OpenSpec 归档和生产部署已完成；归档目录为 `openspec/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`。
- 背景：近两年外部赛马数据已导入 `ExternalHorseAlias`，当前未知马名识别仍主要依赖片假名 token + 上下文打分，无法真正判断没见过的片假名词是不是普通词，容易把 `タイトル` 等普通词误判为马名，也可能漏掉 `マヤノライジン` 等真实马名。
- 核心边界：
  - `TermEntry` 继续表示有中文译名或固定译法的正式术语，参与翻译术语表、译后替换和正式术语校验。
  - `ExternalHorseAlias` 只表示本地外部马名索引，用来确认“这是马名”，不代表已有中文译名，不批量写入 `TermEntry`。
  - 新闻处理链路只查询本地数据库，不在翻译、校验或候选发现阶段实时访问 netkeiba / keibascraper。
- 已实现能力：
  - `server/stable/services/terms.py` 新增结构化马名识别结果，区分 `formal_term`、`external_alias` 和 `heuristic`，并保留旧字符串列表接口兼容既有调用。
  - 识别链路会先提取候选片假名 token，做 NFKC 标准化，再批量查询本地 `ExternalHorseAlias.normalized_name__in`；同一日文名多次出现时按文章出现顺序和长词优先去重。
  - 正式 `TermEntry(term_type=horse)` 优先于外部马名索引；已存在正式中文译名的马名继续走正式术语提示和替换，不再作为未知马名保护。
  - 翻译阶段对外部已知但无中文译名的马名做占位符保护，译后还原为日文原名，不自动替换为中文；翻译 metadata 会记录 `recognized_horse_names` 和 `external_horse_names`。
  - 发布校验阶段把外部已知马名未保留记录为独立 `external_horse_not_preserved` warning，payload 包含日文名、全部外部 horse ID、主展示 ID、来源、置信度和冲突标记；只命中外部索引的马名不触发核心术语或背景术语缺失。
  - 术语候选发现阶段把新闻中出现、外部索引命中但无正式中文译名的马名均作为 `external_horse_alias` 高置信候选来源，包括正文背景段落中的马名；已有正式马名术语或日文别名时不重复建候选。
  - 若片假名文本同时命中普通词过滤表和外部马名索引，必须依赖强马名上下文消歧，不能仅因数据库存在同名马就识别为马名。
  - 同一日文马名对应多个外部 horse ID 时，识别结果和校验 payload 保留全部 ID，不静默只取第一条。
- `2026-06-25` review 返修：
  - `limit` 只限制需要原样保留的外部已知马名和启发式疑似马名，不再让已有中文译名的正式马名占用保护名额。
  - `extract_unknown_horse_names()`、翻译阶段和发布校验阶段均改为先取完整结构化识别结果，再对 `needs_preserve=True` 的名单截断。
  - 新增回归测试覆盖“前面出现多个正式马名，后面出现外部已知但无中文译名马名”时，翻译保护和发布校验仍能命中后者。
- 已创建规格：
  - `external-horse-name-recognition`：新增本地外部马名索引识别能力。
  - `termbase-and-race-priority`：修改翻译链路正式术语命中，并新增外部已知马名保留校验。
  - `term-candidate-discovery`：修改候选发现，使外部马名索引成为高置信来源且不绕过正式术语审核。
- 已同步正式规格：
  - `openspec/specs/external-horse-name-recognition/spec.md`
  - `openspec/specs/termbase-and-race-priority/spec.md`
  - `openspec/specs/term-candidate-discovery/spec.md`
- 验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests --noinput`：review 返修后通过，39 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：review 返修后通过，147 项。
  - `openspec validate use-external-horse-alias-for-name-recognition --strict`：通过。
  - `openspec validate --all`：归档前后均通过。
- 生产部署结果：
  - GitHub PR #6 `[codex] Use external horse aliases for name recognition` 已 squash merge 到 `main`，merge commit 为 `35b0866`。
  - 服务器 `/opt/umanewsbot` 已从 `817e1c8` 快进到 `35b0866`，部署前 `.env` 备份为 `.env.backup.external-horse-alias-20260625_182936`。
  - `./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`collectstatic` 完成，`web` 容器 healthy，`worker / beat` 已重启。
  - 生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `http://umafans.run/` 均返回 `200`。
  - 生产只读 smoke test：`ExternalHorseAlias` 数量为 `11521`；`recognize_horse_names("ロブチェンが出走", ...)` 返回 `ロブチェン`，来源为 `external_alias`，外部 horse ID 为 `2023107089`。
- 长文样本抽检：
  - 抽检方式：从生产只读导出 5 篇长文、2054 条启用正式术语和 11521 条 `ExternalHorseAlias`，写入本地临时 SQLite 后用当前未部署代码跑识别、候选发现和发布校验；未改生产数据。
  - 样本结果：netkeiba 长文中外部索引可命中多匹真实马名，例如 `ロブチェン`、`パントルナイーフ`、`ミクニインスパイア`、`ドリームコア` 等，并在译文未保留时产生独立 `external_horse_not_preserved` warning。
  - 观察到的后续优化点：JRA 活动公告类长文（例如 `JRA宮崎育成牧場けいばフェスタ`）仍会通过启发式把 `フェスタ`、`ウインズ`、`イベント`、`ポニー`、`オリジナル` 等普通片假名词列为疑似未知马名；外部马名索引能降低真实马名漏报，但不能完全替代后续普通词过滤和启发式收紧。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 外部马名索引识别链路生产部署`。

## 2026-06-25 国际赛马资讯扩展本地实现

- OpenSpec change：`expand-international-racing-coverage`。
- 当前状态：本地代码、迁移、测试、文档和 review 返修已完成；尚未部署生产，生产仍以已上线的日本新闻源和既有 QQ 推送配置为准。
- 已落地能力：
  - `NewsSource`、`NewsArticle`、外部数据缓存、`TermEntry`、`TermCandidate` 和 `PushTarget` 已增加地区、原文语言、来源类型或群级推送配置字段；现有数据默认回填为 `japan / ja`。
  - 内置来源同步已增加一期国际新闻源最终清单：`Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`BHA`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`。新来源默认 `enabled=false`，需要人工启用或测试抓取；2026-06-26 review 返修后，内置来源同步只更新来源定义，不再覆盖工作人员手动调整的 `enabled` 状态。
  - 已补充排序型入口策略：类似 netkeiba 访问量榜/注目榜的来源，只有在公开 HTML/API 能稳定慢速抓取时才作为独立榜单源接入。本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓，均作为独立排序/榜单来源加入并保留原站 rank；2026-06-26 review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，普通 list 仍会记录 `NewsSnapshot`；旧候选 `At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险不进入第一版默认清单。
  - 公开首页新增 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，`/?region=<region>` 过滤头条、信息流和热门列表；地区页翻页会保留当前 `region` 查询参数，不会翻页后跳回综合流；文章详情展示地区、来源和原文语言。
  - 术语库 UI 和服务语义已从“日文原词/日文别名”扩展为“原文/原文别名/原文语言”，并新增 `TermAlias` 作为多语言原文别名表；`TermEntry` 表示正式术语概念和标准中文译名，旧 `source_ja / aliases_ja` 物理字段继续兼容并回填为 `ja` 别名。
  - 翻译、改写、发布校验、候选发现、自动标签和自动化评分会按文章 `source_language` 选择对应 `TermAlias`；日文片假名未知马名启发式只应用于 `ja`，英文和繁中不套日文规则，但会按同语言 `ExternalHorseAlias` 做保守外部马名匹配；英文候选可合并到日文正式术语概念并保存为英文别名。2026-06-26 review 返修后，术语匹配和自动化 P0 马匹命中会按本次候选术语批量加载 `TermAlias`，避免每条术语各查一次别名；英文/繁中外部马名识别会先从文章文本生成候选片段收窄数据库查询，并使用原文中实际出现的大小写/写法作为保护文本；翻译保护、发布校验和候选发现也统一使用真实匹配文本，英文正式术语按大小写不敏感方式命中并记录原文真实写法；最终 review 返修后，自动化 P0 马匹命中、发布校验的核心/背景术语判定、以及“新增术语后应用到当前稿”均复用同一套语言感知匹配，避免 `EQUINOX` 这类大写英文漏判或漏替换。本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，跨语言别名 upsert 仍只维护该语言别名、不覆盖概念主原文；后台/API 启停术语时会同步所有语言 `TermAlias` 的启用状态；AI 改写 prompt 的术语表也使用本次文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名。本次返修明确术语导入 upsert 的目标解析：主原文命中同一术语时才更新；如果只是原文别名命中已有其它术语，预览和提交都会拒绝该行，避免把两个正式概念误合并。
  - 自动化评分已补充英文和繁体中文赛马关键词表，英文 `preview / entries / draw / withdrawn / injury / results / stewards` 等信号会参与分类、高关注命中和重点赛事 fallback，不再只依赖日文关键词。
  - QQ 自动推送保留 `QQ_PUSH_ENABLED` 总开关；每个 `PushTarget` 可配置 `allowed_regions`、`push_scope`、`importance_strategy`。总开关管“能不能推”，群配置管“推什么给谁”；文章地区缺失时返回 `region_missing` 并不自动推送。2026-06-26 review 返修后，`importance_strategy=ranked` 不再只认 netkeiba，也会把 `Sponichi / Sky Sports Racing / Horse Racing Nation` 的排序/榜单稿视为重点新闻；已有群迁移会把空 `allowed_regions` 回填为 `["japan"]`，运行时空地区或非法地区配置也按旧行为仅允许日本，避免旧群或误配置群突然收到全球新闻。
  - HKJC 外部数据新增 `import_hkjc_external_data` 管理命令和 `HKJCExternalDataImporter`，支持 `--race-date`、`--race-id`、`--horse-id`、`--payload-file`、`--commit`、`--lookup-name`、`--stats-run-id`，默认 dry-run；提交只写 External* 缓存表和 `ExternalHorseAlias`，不生成前台赛果页。commit 模式在真实网络抓取实现前必须提供 `--payload-file`，并参考 netkeiba 外部导入使用单来源互斥锁，已有 `STARTED` 导入时拒绝并发写入；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入。2026-06-26 review 返修后，`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹，避免 entries/results 里的大量马绕过批量上限。
  - 公开详情 URL 继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID；国际新闻源的 `source_article_id` 只作为来源内幂等去重键，使用完整 URL 派生的 `slug-short_hash`，避免同 slug 不同路径碰撞。
  - 国际新闻原始 HTML 只写入 `original_content_html`；`translation_metadata` 和 `NewsSnapshot.snapshot_metadata` 只保留轻量抓取/翻译元信息，不再重复保存整页 HTML；TDN 等列表 API 提供真实发布时间的来源，在详情页缺少日期节点时会回退使用列表时间；`TDN France keyword` 与美国 `TDN` 来自同一站点，入库时使用 `TDN` canonical source site 和同一 `source_article_id` 去重，`NewsSnapshot` 仍记录实际发现来源，法国关键词来源会优先保留法国地区归类。
  - 欧美数据库源 spike 结论已写入 `docs/global_racing_data_source_spikes.md`；本轮 spike 不加入 Celery Beat、生产命令队列或正式导入队列，不写正式外部数据表。
- 本轮新增迁移：
  - `server/stable/migrations/0011_remove_termcandidate_uq_term_candidate_type_normalized_and_more.py`
  - `server/stable/migrations/0012_termalias.py`
  - `server/stable/migrations/0013_alter_newsarticle_source_site_and_more.py`
- 本轮新增/调整的关键入口：
  - 新闻来源同步：`server/stable/services/sources.py`
  - 国际新闻适配器：`server/stable/adapters/international.py`
  - 国际新闻真实探测命令：`server/stable/management/commands/probe_international_news_sources.py`
  - QQ 群级推送判断：`server/stable/services/qq_auto_push.py`
  - HKJC 数据导入：`server/stable/services/external_hkjc_data.py`
  - HKJC 管理命令：`server/stable/management/commands/import_hkjc_external_data.py`
  - 公开首页地区 tab：`server/stable/views.py`、`server/stable/templates/stable/public/feed.html`
- 已完成的本地验证：
  - `openspec/changes/expand-international-racing-coverage/test_cases.md`：已新增完整测试用例矩阵，按 OpenSpec `proposal/design/spec` 拆分，不依据实现代码倒推；覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.InternationalSourceMetadataTests stable.tests.HKJCExternalDataImportTests stable.tests.AutomationFlowTests --noinput`：通过，35 项。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.InternationalSourceMetadataTests stable.tests.QQAutoPushTests --verbosity 2`：通过，26 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：最终源清单返修前通过，201 项；返修后通过，209 项；2026-06-26 上线前 review 返修后通过，210 项；第二轮 review 返修后通过，214 项，新增覆盖人工来源启用保留、国际榜单来源提升、普通 list 不覆盖榜单主来源、QQ ranked 识别国际榜单稿；本次 review 补丁后通过，217 项，新增覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别、术语导入 upsert 命中跨语言别名时保留正式概念主原文；术语批量别名和 HKJC 上限口径返修后通过，219 项；本轮全球范围适配 review 返修后通过，224 项，新增覆盖英文外部马名真实写法保护、非日文外部别名候选查询、旧 QQ 群空地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮 review 返修后通过，227 项，新增覆盖翻译保护使用英文外部马名真实写法、发布校验不误报已保留真实写法、英文正式术语大小写不敏感匹配与替换；最终 review 补丁后通过，231 项，新增覆盖英文 P0 马匹自动化评分大小写不敏感命中、英文核心术语缺失大小写不敏感阻断、新增英文术语应用当前稿大小写不敏感替换、QQ 群非法地区配置回退日本旧行为；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步 `TermAlias`、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选。
  - `openspec validate expand-international-racing-coverage --strict`：通过。
  - `openspec validate --all`：通过，9 项。
  - `git diff --check`：通过。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py makemigrations --check --dry-run`：通过，无额外迁移。
- 国际新闻源 dry-run 探测：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py probe_international_news_sources --limit 2 --json`：已执行，不写库。
  - 默认第一版矩阵成功解析两篇真实样本：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest`。
  - 榜单/排序入口结论：`Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓并保留原站 rank；`HKJC Racing News`、`SCMP Racing`、`BHA`、`France Galop English News`、`TDN` 当前不按热门榜处理。
  - 旧候选源处理：`At The Races` 当前 403，`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险；三者仍保留适配器供后续单独探测，但不进入第一版默认清单。
- 生产注意事项：
  - 本变更含数据库迁移，部署前必须确认没有正在运行的外部数据导入。
  - 国际新闻源默认关闭；生产启用前应先完成一次整体 review，再按地区逐个灰度启用，并用后台“测试抓取”或命令行小样本复验页面结构。
  - HKJC 正式网络导入仍应小批量、低频、单来源互斥，并从 `--payload-file --dry-run` 或单场小样本开始；如样本超过 `max_races / max_horses`，应先拆分 payload，而不是依赖程序截断。

## 2026-07-10 多地区新闻归属与英文门禁实现

- OpenSpec change：`support-multiregion-news-attribution-and-english-gates`，当前已完成本地实现，待线上前执行生产 dry-run 抽样。
- 数据模型：保留 `NewsArticle.racing_region` 作为主地区，新增 `NewsArticleRelatedRegion` 独立表记录关联地区，并增加 `attribution_source / attribution_summary / attribution_locked` 归属元数据；新增迁移 `0023_multiregion_news_attribution.py`。
- 归属口径：新采集文章和自动化打分前会运行 `stable.services.news_attribution.apply_article_attribution()`；顺序为赛事/赛场信号优先，其次马、骑手、练马师、马主等核心对象，再回退来源地区。法国来源涉及海外赛事时进入法国池和比赛地区池；爱尔兰内容暂归英国并写入 `ireland` 标签。人工归属是否锁定由编辑页显式开关决定，锁定后自动重算不覆盖。
- 英文门禁：`validate_rewrite()` 的英文术语地区筛选已改为使用“主地区 + 关联地区”集合，避免英国赛事/法国来源等跨地区文章被 `term_region_excluded` 误排除。
- 内容类别：文章类别扩展为 `news / preview / result_brief / official_notice / racecard_update / tips / feature / sales_breeding / other`，并保留旧值兼容历史文章。QQ 默认只放行新闻、赛前展望、赛果简报、特写和旧兼容类别；普通 `tips`、拍卖/育马、普通官方通知不自动群推。
- 查询口径：公开首页地区 tab、QQ 窗口、运营汇总可按主地区或关联地区可见；发布窗口可看见关联地区候选，但未发布文章仍只由主地区窗口负责发布，关联地区不消耗发布配额。
- 运营入口：站内文章编辑页新增主地区、关联地区、内容类型、锁定归属字段；Django Admin 增加 `NewsArticleRelatedRegion` inline；文章列表和详情页地区标签显示所有可见地区。
- 重算命令：新增 `reprocess_multiregion_attribution_gates`，支持 `--dry-run / --commit / --region / --hours / --limit / --json`。commit 只重新写归属、重跑门禁并把通过文章恢复为候选，不直接发布。
- 配置：新增 `MULTIREGION_ATTRIBUTION_ENABLED`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED`、`MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`，已写入 `.env.example`。
- 本地验证：`DB_ENGINE=sqlite .venv/bin/python server/manage.py check` 通过；新增/相关测试 86 项通过；`makemigrations --check --dry-run` 通过；两个生产 compose config 使用临时 `.env` 渲染通过；`openspec validate support-multiregion-news-attribution-and-english-gates --strict` 通过。
- `2026-07-10` 未提交改动复审后补齐 `stable.0023_multiregion_news_attribution` 迁移，并将新内容类别贯通到赛事新闻关联和 AI 改写提示：`preview / tips` 按赛前关联，`result_brief` 按赛后关联，所有新类别均有明确改写指令；保留旧类别兼容。SQLite 测试库已实际应用迁移，新增回归测试锁定新类别映射；完整 `stable` 测试 `522` 项通过。本次未部署、未执行生产迁移。
- `2026-07-10` 未提交改动代码审查返修已完成：自动归属将明确赛事/赛场与国家、对象、机构上下文分层，赛事地优先不再受固定地区顺序干扰；多个模糊上下文并存时保守回退主来源；来源 URL/备注不参与归属。重复来源入库始终使用文章最终主来源配置，避免 TDN 法国稿被普通 TDN 重抓改回美国。`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 现在同时约束 QQ 即时推送；后台锁定复选框可正常取消；重处理 dry-run 对锁定文章使用与 commit 相同的有效地区并输出 `attribution_locked / attribution_applied / inferred_regions`；QQ 默认白名单移除 `other`。新增反例测试后相关测试组 `123` 项通过，完整 `stable` 回归 `529` 项通过；生产 dry-run 与部署仍未执行。
- `2026-07-10` 第二轮代码审查返修已完成：文章编辑页通过隐藏哨兵区分旧请求与新版空多选，运营可以把全部关联地区清空；`NewsArticleRelatedRegion` 使用标准字段级 `ValidationError`，Django Admin 选择与主地区相同的关联地区时显示中文错误而不是 500；重处理命令的 `--limit` 改为按有效门禁候选计数，并输出 `scanned_count / candidate_count / has_more_candidates`；公开卡片以主地区开头，详情页和 QQ 明确区分“主地区/关联地区”，单地区回退时 QQ 不显示关联地区。目标测试 `19` 项、相关测试组 `129` 项、完整 `stable` 回归 `534` 项通过；Django check、迁移漂移、OpenSpec 严格校验和 `git diff --check` 均通过。本次仍未执行生产 dry-run 或部署。
- `2026-07-10` 第三轮审查按确认范围只修复公开展示回退：`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 时，首页卡片和文章详情也只显示主地区，关联地区数据保留。按当前决策不收紧 `other` 关联地区的后台保存规则。目标测试 `20` 项、完整 `stable` 回归 `540` 项通过；Django check、迁移漂移、OpenSpec 严格校验和 `git diff --check` 均通过。生产 dry-run 与部署仍未执行。
- `2026-07-11` 已将分支快进合并最新 `origin/main`；多地区新闻迁移顺延为 `0023_multiregion_news_attribution` 并依赖主干 horse profile `0022`。赛事历史抓取编排第五轮审查补齐基础证据链；第六轮定向返修进一步让批量候选保存/apply 整批事务回滚、把完整 adapter 输入写入批准快照并在 `RaceEvent` 漂移时阻断、只从完整 approved 记录读取混合来源策略 SHA。按用户决定，不强制所有 importer apply 提供 `--expected-sha256`，暂不增加请求预算并发锁。OpenSpec change `orchestrate-race-event-data-crawls` 已同步正式规格并归档到 `openspec/changes/archive/2026-07-11-orchestrate-race-event-data-crawls/`。目标测试 `67` 项、完整 `stable` 回归 `589` 项通过；Django check、迁移漂移、两个 change 严格校验、OpenSpec 全量 `21` 项和 `git diff --check` 均通过。本轮生产部署进行中，尚未运行赛事网络抓取或写入。
- `2026-07-11` 上线等待空闲窗口时发现生产 worker 在归属开关关闭后仍执行完整术语扫描，两个 crawl worker 长时间高 CPU。已修正 `apply_article_attribution()`：开关关闭或人工归属锁定且未 force 时直接返回当前归属，仅对历史空内容类别做轻量分类，不调用 `infer_article_attribution()`。目标测试 `30` 项、完整 `stable` 回归 `591` 项通过；生产开关继续关闭，五地区产品抽样仍未通过，本修复待随本轮部署上线。
- `2026-07-11` 已完成赛事历史抓取编排与多地区归属基础代码上线，生产代码提交为 `6e2cc92`。部署前备份 `.env.backup.orchestration-hotfix-20260711_093556` 和 `backups/db/pre-orchestration-hotfix-20260711_093556.sql.gz`，数据库备份约 `102M` 且 `gzip -t` 通过。`stable.0023_multiregion_news_attribution` 已应用，无新增待执行迁移。
- 上述归属短路热修复已在生产验证：当 `MULTIREGION_ATTRIBUTION_ENABLED=false` 时，真实文章调用 `apply_article_attribution(save=False)` 不会调用 `infer_article_attribution()`，返回 `attribution_disabled`。worker 从部署前两个进程持续高 CPU 恢复到约 `0.04%`，旧抓取积压已消化，Celery reserved 为空，日志未见 traceback/error。
- 生产 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 继续保持关闭；此前五地区 dry-run 的产品归属口径仍未通过，因此 `support-multiregion-news-attribution-and-english-gates` 保持 active，任务 `9.6` 继续待办，未执行历史归属 commit。
- 生产回归通过：六个容器正常，Django check 通过；本机与公网 `/healthz/`、首页、法国/英国地区页、赛事日历和后台登录页均正常。已通过应用内浏览器真实打开首页、法国频道、英国频道、赛事日历和后台登录页，页面标题、地区导航和文章列表正常渲染。
- `2026-07-11` 经用户确认，`support-multiregion-news-attribution-and-english-gates` 已同步六组 delta spec 后归档至 `openspec/changes/archive/2026-07-11-support-multiregion-news-attribution-and-english-gates/`，当前无 active OpenSpec change。正式规格新增 `multiregion-news-attribution`，并同步英文门禁、国际内容分类、发布窗口、公开地区 tab 和 QQ 多地区规则；OpenSpec 全量 `21` 项通过。归档时保留任务 `9.6` 未完成警告：五地区生产 dry-run 的产品归属口径仍未通过，生产两个多地区开关继续关闭。

## 2026-07-01 多地区新闻增量窗口实现与生产验证

- OpenSpec change：`increase-multiregion-news-volume`，已完成实现、归档、部署生产，并开启抓取 / 发布 / QQ 三条生产窗口。
- 已新增窗口运行模型：`ProductionWindow`、`WindowCandidateDecision`、`WindowTargetDecision`、`QuotaLedger`、`MajorRaceEvent`；`NewsSource` 增加生产批准、有效抓取间隔、backoff、人工暂停、错误分类、连续成功/失败和重要赛事升频字段。
- 已实现日常/重要赛事窗口服务：日常 15 分钟、重要赛事 5 分钟、最多 3 小时回看；重要赛事按地区当地时间录入，开跑前 3 小时到开跑后 1 小时升频，无开跑时间时按当地日期级窗口处理。
- 已实现新抓取窗口：只选择 `enabled=true`、`production_approved=true`、未暂停、未 backoff 的来源；连续失败 3 次自动降频，403/429/验证码类错误使用更保守 backoff，连续成功 3 次恢复默认 15 分钟。
- 已实现新发布窗口：每地区每窗口最多 5 篇；硬门禁不绕过；按内容指纹去重后评分排序；若没有高分稿但存在 45 分以上可发布稿，按保底发 1 篇并标记 `region_minimum_fill` 与 `disable_auto_qq`。
- 已实现新 QQ 窗口：只推高价值/榜单稿；每地区每窗口最多 3 篇；保底文章不自动 QQ；群小时和全站小时配额写入 `QuotaLedger`；0 推送原因写入 `WindowTargetDecision` 和窗口 payload。
- `2026-07-02` review 返修后，抓取和 QQ 补跑都只对最近一个缺失窗口执行真实动作，较早缺失窗口会记录为 `coalesced_to_latest_*_window` 的 `SKIPPED` 窗口，避免停机恢复后集中补抓或集中补推；已有 `SKIPPED/FAILED` QQ delivery 若重新进入发送，也必须先重新占用群小时和全站小时配额，`PENDING/RETRYING/SENDING/SENT` 或已达到最大尝试次数的 delivery 仍不会重复占配额。本轮进一步修正窗口真实状态口径：抓取窗口只在真实抓取任务完成后写 `SUCCEEDED/FAILED`，来源存在 lease 未过期的运行中抓取窗口时不再重复派发；HTTP 403/429 等状态码会进入来源错误分类；QQ 窗口在占配额和创建 delivery 前先检查 OneBot 在线状态，离线时直接在窗口记录 `onebot_offline` 并不派发消息。
- 已扩展 `audit_multiregion_news_production`：输出生产批准来源数、暂停/backoff 来源数、最近窗口结果、0 原因和配额打满记录；新增 `production_summary_task` 每日生成同一份摘要。
- 新窗口 Beat 已接入；生产显式开启后进入五地区常态窗口，不依赖旧 `auto_publish_batch_task` 提高频率。
- 新增管理入口：
  - `MajorRaceEvent`、`ProductionWindow`、`QuotaLedger` 已注册 Django Admin。
  - `NewsSourceAdmin` 显示生产批准、有效间隔、backoff、失败连续次数和错误分类。
  - `import_major_race_events --csv <path>` 支持重要赛事 CSV upsert，主键口径为 `normalized_name + year + racing_region + race_grade`。
- 已完成本地验证：
  - `DB_ENGINE=sqlite manage.py check`：通过。
  - `DB_ENGINE=sqlite manage.py makemigrations --check --dry-run`：通过。
  - 模型/窗口/来源/发布/QQ/重要赛事导入相关目标测试通过。
  - `2026-07-02` review 返修后，窗口相关目标测试 26 项通过，完整 `stable` 测试 399 项通过；`DB_ENGINE=sqlite manage.py check`、`openspec validate increase-multiregion-news-volume --strict`、`openspec validate --all` 和 `git diff --check` 均通过。
  - 临时 SQLite 迁移后 `audit_multiregion_news_production` 可输出有效 JSON。
- 生产运行验证：
  - `2026-07-02` 已部署到生产 `a122130`，容器 `web / worker / beat` 正常，`http://umafans.run/healthz/`、首页和抽检 `/news/<article_id>/` 均返回 `200`，Celery `active/reserved` 为空。
  - 生产配置确认：`MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true`，抓取 / 发布 / QQ 子开关均为 `true`；允许地区为日本、中国香港、英国、法国、美国；日常窗口 `15` 分钟，重要赛事窗口 `5` 分钟；发布每地区每窗口 `1-5` 篇，QQ 每地区每窗口最多 `3` 篇；当前没有地区处于重要赛事升频窗口。
  - `2026-07-02 04:18-10:18` 最近 6 小时窗口复核：发布窗口和 QQ 窗口各地区均产生 `24` 个日常窗口；抓取窗口统计为 `260` 个 `succeeded/completed`，`109` 个 `skipped/coalesced_to_latest_crawl_window`，符合恢复补跑只抓最近窗口的设计。
  - 最近 6 小时发布窗口中，美国 `04:30` 发布 `1` 篇，日本 `04:45` 发布 `2` 篇、`05:30` 发布 `4` 篇、`06:30 / 08:15 / 09:45` 各发布 `1` 篇；所有非零窗口均未超过每地区每窗口 `5` 篇，其余窗口均有 `no_ready_candidates` 原因。该时段 `published_to_web_at` 另包含香港 `1` 篇和美国 `3` 篇上线初始批次 / 旧自动发布文章，不属于本次新窗口发布。
  - 最近 6 小时 QQ 实际发送 `6` 条，目标均为 `UmaFans测试群(1026525240)`；美国 `3` 条，日本 `3` 条，未超过每地区每窗口 `3` 条。0 推送窗口记录为 `no_eligible_articles` 或 `already_sent`。
  - 来源复核显示 16 个生产批准来源最近抓取均为 `success`；`TDN France Galop 关键词英文新闻` 和 `TDN 美国新闻` 虽有已过期 `backoff_until` 残留，但最新 `10:00` 抓取窗口均为 `succeeded/completed`，当前不影响抓取。
  - Ops 通知开关已开启，最近 6 小时产生 `ops_summary` QQ 通知 `2` 条并发送成功；邮件 / 短信 / 微信渠道按 MVP 预留逻辑记录为 `skipped` 或未配置。
  - `2026-07-02 11:07` 继续复核最新 4 个发布窗口（`10:15 / 10:30 / 10:45 / 11:00`）：五地区均未发布新文章。日本有 `18` 条候选决策，全部为 `hard_gate_blocked`，主要来自翻译失败、人工审核要求和核心术语缺失；香港、英国、法国、美国没有进入发布候选的文章。最近 3 小时抓取显示非日本来源均成功运行但新增为 `0`、只命中重复旧稿；`TDN France Galop 关键词英文新闻`、`TDN 美国新闻` 曾在 `08:25-09:05` 超时或 `525`，`10:10` 已恢复成功且失败 streak 为 `0`。因此最新窗口 0 发布的主因是“日本候选被门禁/审核拦住，非日本暂无新稿”，不是生产调度或整体抓取失效。
  - `2026-07-02 15:10` 复核最近 2 小时自然窗口（`13:15` 至 `15:00`）：发布窗口和 QQ 窗口五地区均按 15 分钟节奏生成且状态为 `succeeded`，本时段网页发布 `0` 篇、QQ delivery `0` 条；发布 0 原因为 `no_ready_candidates`，QQ 0 原因为 `no_eligible_articles`。抓取窗口整体正常，最近 2 小时新入库 `8` 篇：日本 `5`、香港 `1`、英国 `2`、法国/美国 `0`；这些新稿当前为翻译失败或 `manual_review_required / pending_review`，未达到自动发布状态。16 个生产批准来源中 14 个最新成功，`TDN France Galop 关键词英文新闻` 与 `TDN 美国新闻` 在 `15:02` 出现 read timeout，`failure_streak=1`，属于同一上游站短时超时，不是整体抓取失效。候选决策当前能记录 `hard_gate_blocked`，但 payload 未展开具体 blocker 明细，后续可作为可观测性改进。
  - `2026-07-03 00:13` 复核今日窗口：因刚过零点，今日目前只有 `00:00` 一个自然窗口。五地区抓取 / 发布 / QQ 窗口均为 `succeeded`；抓取新入库 `1` 篇美国 TDN 新闻，其余来源均为重复旧稿；网页发布 `0` 篇，发布 0 原因为 `no_ready_candidates`；QQ delivery `0` 条，日本 / 美国为 `already_sent`，香港 / 英国 / 法国为 `no_eligible_articles`。16 个生产批准来源最新状态均为 `success`，前一日 TDN 超时已恢复。
  - `2026-07-03` 复核 `2026-07-02` 全日窗口：因多地区生产窗口于 `04:00` 后开始有账本，昨日实际覆盖 `04:00-23:45` 共 `80` 个 15 分钟窗口起点。发布窗口五地区各 `80` 个且全部 `succeeded`，窗口发布日本 `37` 篇、香港 `1` 篇、美国 `10` 篇，英国 / 法国为 `0`，无 failed/partial；0 发布主因仍为 `no_ready_candidates`，未发布候选多为 `hard_gate_blocked`。QQ 窗口五地区各 `80` 个且全部 `succeeded`，窗口派发日本 `3` 条、美国 `5` 条，均无 failed delivery；昨日所有 QQPushDelivery 记录按地区为日本 `15` 条、美国 `9` 条，状态均为 `sent`。抓取窗口无 `failed`，按窗口 payload 统计新增：日本 `79`、香港 `5`、英国 `11`、法国 `1`、美国 `28`，其中日本有 `7` 次榜单唤醒；`coalesced_to_latest_crawl_window` 为恢复/延迟时只补最近窗口的预期跳过。16 个生产批准来源在 `2026-07-03 00:13` 最新状态均为 `success`。
  - `2026-07-03` 地区归属错配只读审计：当时 `NewsArticle.racing_region` 与 `source_config.racing_region` 完全一致，`6598` 篇文章中 `0` 篇偏离“按新闻源地区”的现有逻辑。严格按有地区字段的实体（`ExternalHorseAlias` / 非空 `TermEntry.racing_region`）推断时，可覆盖 `462` 篇文章，且全部为日本文章；按用户提出的“第一种单地区逻辑”和“第二种多地区逻辑”均未发现结构化错配。但该结果只能作为下限：审计当时生产 `TermEntry` 的马/赛事/骑手地区全部为空（马 `1884`、赛事 `153`、骑手 `2`），`MajorRaceEvent` 为空，外部马名/赛事正式缓存只有日本和极少香港，没有英法美实体地区，因此系统无法可靠判断英文新闻中提到的日本 / 英国 / 法国 / 美国马、骑手或赛事。`2026-07-04` 后仅首批 `10` 条术语补写了地区，仍不足以支撑可信实体地区识别。补充关键词粗扫发现 `1213` 篇疑似跨地区提及，其中 `2026-06-30` 以后 `231` 篇、`2026-07-02` `60` 篇，但噪声较高，只能作为后续补实体地区识别的线索。

## 2026-07-02 榜单唤醒未发布文章实现

- OpenSpec change：`revive-ranked-news-for-publish`，当前已完成实现、归档和生产部署。生产服务器 `/opt/umanewsbot` 已部署到 `a774672`，部署前备份 `.env` 为 `.env.backup.ranked-revival-20260702_145529`，数据库备份为 `backups/db/pre-ranked-revival-20260702_145529.sql.gz`。
- 用户确认的产品规则：榜单二次命中不是直接发布按钮，而是“这篇文章值得重新认真看一次”的强信号。未发布文章从普通来源升级为榜单来源时，应允许低分忽略、价值不足转人工、待翻译或翻译失败文章被唤醒；翻译失败或待翻译文章需要自动重试翻译；翻译成功后重新评分，高价值来源信号参与自动发布判断。
- 边界：榜单唤醒不得绕过翻译成功、自动评分、发布校验、发布窗口配额和 QQ 限流；人工拒绝、撤回、已发布、高度重复 blocker、正文缺失、核心术语缺失等硬门禁仍不自动复活。
- 规格影响：修改 `automation-publish-gates` 和 `multiregion-news-production`，新增榜单唤醒、翻译重试、重新评分、按唤醒时间进入发布候选池以及窗口决策留痕要求。
- 代码实现：新增 `NewsArticle.ranked_revived_at` nullable/indexed 字段和迁移 `0019_newsarticle_ranked_revived_at.py`；新增 `revive_article_after_ranked_source_elevation()` 服务，记录 `decision_reason.ranked_revival`，区分 `translation_retry / rescore / blocked / already_retrying_translation`；netkeiba 榜单和国际榜单抓取在 `source_elevated=true` 时对未发布文章执行榜单唤醒，已发布文章继续沿用现有 QQ 补推；发布窗口候选查询支持 `first_seen_at` 或 `ranked_revived_at` 最近 3 小时，并在 `WindowCandidateDecision.payload` 写入榜单唤醒来源和时间。
- 测试进展：已按 TDD RED-GREEN 补充并跑通 `server/stable/tests.py` 中的榜单唤醒测试，覆盖 nullable/indexed `ranked_revived_at` 字段契约、低分 ignored 复活、价值不足人工状态复活、翻译失败/待翻译重试、人工终态/duplicate/blocker 不复活、重复榜单命中幂等、发布窗口按 `ranked_revived_at` 回看、以及 netkeiba/国际榜单抓取对未发布文章走唤醒而非 QQ 直推。
- 验证：`DB_ENGINE=sqlite manage.py check` 通过；`DB_ENGINE=sqlite manage.py makemigrations --check --dry-run` 通过；`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true manage.py test stable --noinput` 通过，418 项；归档前 `openspec validate revive-ranked-news-for-publish --strict` 通过，归档后 `openspec validate --all` 通过，14 项；`git diff --check` 通过。
- 上线结果：迁移 `stable.0019_newsarticle_ranked_revived_at` 已应用；`manage.py check` 通过；生产模型确认 `ranked_revived_at null=True db_index=True`，榜单唤醒服务可 import；`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页和后台登录入口均返回 `200`；`web / worker / beat` 已重建并运行，Celery `active/reserved` 为空，近 80 行 `web / worker / beat` 日志未见 traceback/error。
- 上线后观察：继续观察发布窗口候选决策中的 `ranked_revival` payload、翻译重试数量、重新评分结果和 QQ 是否仍只推已发布/合格文章。回滚代码后 `ranked_revived_at` 字段可保留不用；如需彻底清理，后续单独做清理迁移。

## 2026-07-11 国际新闻门禁与产量生产验收

- 验收窗口：截至 `2026-07-11 17:18 CST` 的最近 24 小时。抓取/发布窗口调度正常，所有启用来源最新状态均为 `success`；但业务验收未通过。
- 门禁：最近 24 小时英文新稿 `50` 篇，公开 `15` 篇，`25` 篇仍有 `core_term_missing` blocker，共 `136` 条。`America`、`Oaks` 已按普通词/高歧义词降级，且没有 `term_semantic_classification=common_word` 的 blocker；但 `something`、`versatile`、`brilliant`、`incredible`、`reputation`、`threat`、`title`、`too soon`、`yet` 等普通词因术语库被错误标为 `horse`，仍走 `horse_term_without_common_seed -> proper_noun` 并阻断发布。因此门禁优化有效但不完整。
- `reprocess_term_gate_blocked_articles --dry-run` 存在严重性能问题：生产上 `limit=5` 仍长时间占用单核，多个并发验收进程一度使 web 容器 CPU 达约 `185%`；已终止本次启动的全部进程，web CPU 恢复约 `0.08%`，健康检查正常。修复前不得在生产批量运行该命令。
- 来源与产量：当前生产批准并启用来源为日本 `6`、香港 `2`、英国 `3`、法国 `3`、美国 `3`。法国新增宽关键词 TDN 来源已启用，但最近 24 小时新增 `0`，主要命中 `stale_published_at` 后跳过；At The Races 法国源仍未批准。香港、英国、美国没有完成后续讨论的新一轮扩源。
- 最近 24 小时按主地区统计：日本新增/公开 `114/21`，香港 `3/0`，英国 `12/2`，法国 `1/0`，美国 `34/13`。香港 3 篇为待审核 `2`、翻译失败 `1`；法国 1 篇翻译失败；英国 12 篇中待审核 `6`、翻译失败 `2`、忽略 `2`、公开 `2`；美国 34 篇中待审核 `17`、翻译失败 `4`、公开 `13`。
- 最近 8 个发布窗口：日本发布 `5` 篇、英国 `1` 篇，香港/法国/美国均为 `0`，0 原因均为 `no_ready_candidates`。结论是美国总体产出已可用、英国抓取量达到最低规模但发布转化偏低，香港和法国仍明显不足，尚未达到各地区常态丰富产出的目标。
- 验收期间并行赛事 adapter 部署重建了 web/worker/beat，17:15 抓取窗口短暂留下运行中记录，随后从 `11` 条降至 `1` 条，Celery 抓取队列清空且健康检查恢复。该暂态由并行部署造成，不作为新闻调度持续故障结论。
## 2026-07-12 赛事公开页中文术语与出马表排序修复

- 公开赛事详情页和赛事日历赛果将马名、骑师名批量关联 active `TermEntry / TermAlias`；精确命中时展示正式中文译名，候选优先级为赛事同地区、全局、其他地区，未命中保留来源原文。
- 出马表不再使用抓取来源行序直接展示。当前日本、香港、英国、法国、美国均优先按马号自然升序，缺马号时回退闸位，再回退来源 `sort_order`；支持 `1A / 2 / 10` 等编号。
- 修复只改变公开展示，不覆盖 `RaceEventRunner / RaceEventResult / RaceEventHistoryWinner` 中的来源原文，也不改变赛果名次顺序。
- 本地目标测试 `23` 项、完整 `stable` 回归 `612` 项、Django check、迁移漂移检查、OpenSpec 严格校验和 `git diff --check` 均通过。
- 已部署生产提交 `d071952`，无新增迁移。生产 `web / worker / beat` 重建正常，内外 healthz、赛事日历和日本德比详情均返回 `200`，近 5 分钟服务日志无 traceback/error。
- 线上首批术语覆盖抽检：香港赛果已是中文原文；英国马名 `13/13`、骑师 `9/13` 命中；美国马名 `2/18`、骑师 `11/18` 命中；法国马名 `1/7`、骑师 `0/7` 命中；日本德比马名 `1/18`、骑师 `0/18` 命中。日本德比当前冠军 `ロブチェン` 和骑师 `松山 弘平` 尚无 active 正式术语，页面按规则保留原文，后续需补词库而不是改展示逻辑。
- 部署前 `.env` 备份为 `.env.backup.race-display-20260712_002533`；数据库备份为 `backups/db/pre-race-display-20260712_002533.sql.gz`，约 `105M`，gzip 校验通过，SHA-256 为 `99994e84d3154dd9d4c1503b96688cd24bf7e00d9ad13aca02a965a69d64a8c0`。
## 2026-07-12 五地区赛事追溯至 1984 年目标启动

- 新长期目标已锁定：日本、中国香港、英国、法国、美国赛事采用相同历史深度，统一追溯至 1984 年，并沿用应到清单、跨来源关联、去重补漏、五地区抽样、覆盖审计、dry-run、备份、分批写入和写后核验门禁。
- 生产只读基线：`RaceEvent=995`，全部为 2026 年；日本 `186`、香港 `20`、英国 `203`、法国 `174`、美国 `412`。按现有系列机械乘以 1984–2026 的 43 年，理论上限约 `42,785` 个年度对象，但该数字尚未扣除创办年、停办/取消和历史等级范围变化。
- 当前前置缺口：编排器支持年份范围，但要求每个年份先存在正式 `RaceEvent`；日本、香港部分 `series_key` 带 2026 日期，美国另有两个同年重复系列键，不能直接复制当前赛历生成历史年度对象。
- 已创建 OpenSpec change `backfill-race-events-to-1984`，完成 proposal、design、4 份 delta spec 和 tasks；`/grill-me` 共锁定 22 个产品决策。两轮 `/plan-eng-review` 已收敛，最终 verdict 为 APPROVED，审查记录见 `engineering_review.md`。当前只获准进入“编写完整测试用例”阶段，尚未实现代码、触网、创建历史赛事或写生产数据。
- `/grill-me` Q1 已确认选择 A：历史范围为当前五地区全部 graded/pattern 系列，包括日本 JRA/NAR 分级赛、香港分级赛、英国/法国 Pattern Race 和美国 Graded Stakes；明确排除普通赛、让赛和未胜利赛。
- `/grill-me` Q2 已确认选择 A：入选赛事系列按完整系列史收录，从 `max(1984, 实际创办年)` 开始；赛事升级为分级赛之前的届次也纳入，并保存当年真实等级。
- `/grill-me` Q3 已确认选择 A：纳入 1984–当前年度任一年曾属于 graded/pattern 体系、但后来停办、降级退出或不在 2026 当前目录中的历史独有系列。完整目录必须逐年发现，不能只从现役 2026 系列向前复制。
- `/grill-me` Q4 已确认选择 A：已排期后取消的年度赛事创建 `RaceEvent(status=cancelled)`；当年根本未举办的系列只在应到清单记录 `not_held`、原因和证据，不创建虚假赛事，且不作为漏抓。
- `/grill-me` Q5 已确认选择 A：历史年份只有可信完整赛果而无独立 racecard 时，可从完整赛果派生出马表并标记 `derived_from_results`；仅复制有证据字段，赔率、闸位等未知值保持为空。
- `/grill-me` Q6 已确认选择 A：年度冠军以该年正式赛果为唯一主事实，历届冠军按稳定系列动态汇总；只有缺完整赛果而有可信冠军证据的年份才用 `RaceEventHistoryWinner` 补位，禁止向每届复制整张冠军表。
- `/grill-me` Q7 已确认选择 A：稳定赛事系列身份按权威沿革认定；冠名、名称、场地、距离和等级变化不自动切断系列，合并/拆分/替代必须人工确认并记录前身后继，名称相似只生成待审候选。
- `/grill-me` Q8 已确认选择 A：字段级来源权威顺序为当年主办方/监管机构官方结果、官方历史档案/年鉴、高可信专业数据库、参考来源；低级来源只补空，同级或更高级冲突阻断相应写入范围并人工审核。
- `/grill-me` Q9 已确认选择 A；工程审查将不可执行的停办系列近年锚点澄清为：每地区 3 个代表系列、约 9 个真实 held/cancelled 年度目标，地区整体覆盖 1980 年代、2000 年前后和近年，约 45 场，并覆盖长寿、改名/迁场、历史独有或停办系列。
- `/grill-me` Q10 已确认选择 A：覆盖完整目标可按批准 scope 先写入；`source_unavailable / identity_review_required` 持续挂在总缺口账本且不计完成，不冻结其他完整目标，也不得用空记录占位。
- `/grill-me` Q11 已确认选择 A：永久不可得必须完成官方/监管档案与至少一个独立可信来源的双来源核查，保留完整证据并人工批准；超时、403、限流和页面改版只算暂时不可用。
- `/grill-me` Q12 已确认选择 A：当前年度未来赛事或官方确认宽限期内赛事标记 `not_due`，进入总清单但不计缺失；到期后再转为应到，历史完成率与滚动当前赛季分开统计。
- `/grill-me` Q13 已确认选择 A：批准批次中身份完整且出马表/赛果达到年度可得标准的历史赛事可自动公开；身份待审、来源冲突或资料不足保持 draft，已确认取消赛事可带说明公开。
- `/grill-me` Q14 已确认选择 A：后续更权威/更完整来源通过新候选 diff 和批准批次修正机器字段，人工锁字段不覆盖；旧值、来源快照、批次、原因和回滚证据必须保留。
- `/grill-me` Q15 已确认选择 A：马名/骑师名缺中文术语不阻止结构化历史赛事写入和公开，页面保留原文并生成术语缺口；术语补齐后动态显示中文，禁止自动音译直接写正式词库。
- `/grill-me` Q16 已确认选择 A：首批后全量按 `2016–2025 → 2006–2015 → 1996–2005 → 1984–1995` 从新到旧推进；标准批次每地区最多 50 个目标，任何地区不得比最慢地区领先超过 100 个同年代带标准目标。
- `/grill-me` Q17 已确认选择 A：最终以 `accounted_rate=100%` 收口，同时独立报告 `data_complete_rate`；全部目标必须写入、确认 not_held/not_due，或经双来源批准 permanently_unavailable，永久缺档不得伪装成数据完整。
- `/grill-me` Q18 已确认选择 A：历史参赛记录不自动批量创建 HorseProfile，只关联现有正式术语/马匹资料；未识别人马进入候选和术语缺口，避免同名误合并与空壳资料。
- `/grill-me` Q19 已确认选择 B：不新增公开赛事系列页；历史数据继续落在年度 RaceEvent 详情页，稳定系列仅用于后台身份、历届冠军汇总和年度关联。
- `/grill-me` Q20 已确认选择 A：赛事日历增加年份筛选和赛事名称搜索，结果进入现有年度详情页；不新增系列页，也不要求按短窗口连续翻到 1984 年。
- `/grill-me` Q21 已确认选择 A：哈希锁定 artifact 是审批与 apply 唯一凭证；后台增加按地区/年代/系列/状态/冲突查看的汇总入口，但不得绕过 artifact 直接批量写入。
- `/grill-me` Q22 已确认选择 A：质量达标且 published 的历史年度赛事允许搜索引擎收录并进入分片 sitemap；draft、身份冲突、资料不足和 not_held 不收录。
- 本轮 `/grill-me` 当时已完成关键产品分支确认，后续也已完成旧 OpenSpec design、delta specs 和 tasks 编写；这是一条历史进度记录，不是现行下一步。`2026-07-15` 起剩余工作按本文件顶部的新流程迁移。
- `backfill-race-events-to-1984` 已完成两轮 Full `/plan-eng-review`，最终 APPROVED；随后已创建 `test_cases.md`，共 160 个唯一测试用例，覆盖范围、系列/迁移、年度状态机、来源权威、artifact、五地区 adapter、批次、导入、公开页面、运维和非目标回归。OpenSpec change strict、全量 22 项和 `git diff --check` 均通过。历史上曾按旧流程进入 apply 阶段；该交接已由 `2026-07-15` 新流程取代，后续从安全检查点读取现存规格并只对未实现行为补真实 RED，再由 subagent 实现并复用同一需求既有 reviewer 会话审核。此处不伪造既往 RED，也不重做已完成生产动作。

## 2026-07-12 历史赛事回填 apply 第一阶段

- `backfill-race-events-to-1984` 的旧 apply 阶段当时仅完成本地模型、迁移和只读 inventory 基础能力；尚未部署、触网、提交历史总账或创建历史年度赛事。后续执行以 `2026-07-15` 新流程为准，不再把旧命令作为可执行下一步。
- 新增稳定系列、历史名称、系列关系和年度应到总账模型；`RaceEvent.race_series` 为 nullable，旧 `series_key` 和公开 slug 保持兼容。赛果新增独立 `official_finish_position`，迁移会优先读取旧 `source_refs` 官方名次并回退存储顺序，历史冠军唯一约束已支持并列冠军。
- 新增离线 `build_historical_race_inventory`：默认只生成 series/target/conflict/gap/summary/manifest/approval artifact；commit 必须开启功能开关并验证批准人、时间、manifest SHA 和全部文件 SHA，且 commit 阶段不重新生成输入、不触网。
- 已实现字段级来源权威合并、同级冲突阻断、人工锁保护、系列关系防环、名称模糊匹配只进待审、双状态转换、永久缺档独立双来源校验和 accounted/data-complete 分开统计。
- 历史总账 Django admin 为只读入口，支持地区、年份、系列、expectation/resolution 状态和名称筛选；无新增、编辑、删除或直接 apply 动作。
- 新增默认关闭配置：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，并设置请求、source cache 和最小剩余磁盘预算。历史 prepare 必须同时通过功能开关、网络开关、plan 显式授权和预算校验。
- 当前相关模型、service、command、后台、旧赛事页面和旧编排回归共 `122` 项通过；空 SQLite 正向迁移、反向回滚、再迁移、Django check 和迁移漂移检查通过。完整实现、全量回归、代码 review 和生产验收仍未完成。
- 后续 apply 与生产准备已推进到 `65/82` 项，代码与自动化测试任务已全部完成：除总账切批、历史 importer、公开搜索和分片 sitemap 外，已新增五地区统一离线目录 adapter、`parse_historical_race_catalog` 标准候选命令、共享 source cache/请求预算锁、历史网络运行日志，以及 sitemap/年份缓存和查询索引。五地区三年代测试摘录只验证解析契约，不代表生产目录已收齐。
- 本轮专项测试覆盖目录、模型、artifact、批次、日志、缓存和编排，完整 `stable` 回归最终为 `743/743`；Django check、迁移无漂移、OpenSpec strict/all `23/23`、三套 Compose 配置、实际 Docker 镜像构建及容器内 `/app/runtime` 路径检查均通过。
- 已完成多轮 `/review -> 修复 -> 重新 review`：修复目录年份/香港赛季与 provenance、稳定 key 冲突、批准人和人工锁、artifact/cache 路径边界、apply-check cache 保护、已导入/永久缺档状态漂移、共享 Redis cache 降级，以及受保护 cache 不可覆盖和大文件分块校验。最终一轮 review 无 actionable finding，代码门禁 clean；工具已部署并完成 2026 mapping，但尚未创建历史总账、抓取 1984–2025 详情或公开历史赛事。
- 生产部署和 2026 mapping 已完成，当前进度 `65/82`。剩余 `17` 项全部是生产操作：逐年官方 source cache/总账、首批五地区验收、分年代带抓取落库和最终审计。1984 起官方年鉴 cache 尚未收齐，不能把测试 fixture 当作生产总账分母。

## 2026-07-12 历史赛事工具生产部署与 2026 系列 mapping

- 生产已从 `dc6e434` 快进部署至 `c3b66a6`。迁移 `stable.0024_historical_race_inventory` 与 `stable.0026_historical_race_query_indexes` 已应用，三个历史查询索引均存在；Django check、内外 `/healthz/`、赛事日历和抽检详情页通过。
- 部署前备份为 `.env.backup.historical-race-backfill-20260712_044501` 与 `backups/db/pre-historical-race-backfill-20260712_044501.sql.gz`；mapping 写入前备份为 `backups/db/pre-2026-race-series-mapping-20260712_051047.sql.gz`。两份数据库备份均通过 `gzip -t` 和 SHA-256 校验。
- 2026 初始 mapping 对 `995` 场赛事识别出日本/香港日期型 key、美国两组重复 key 和英国名称相似冲突。美国两个无日期空壳的别名、历届冠军和候选均与正式赛事重复，已在事务断言后删除；英国 Gold Cup 重复记录的出马表、赛果、冠军、候选和 BHA 官方来源已合并到既有 `/races/2026/gold-cup/` 主记录。
- 最终批准 artifact 为 `runtime/historical_race_inventory/mapping-2026-approved-20260712_051808/`：`event_count=992`、`approved=992`、`review_required=0`、`conflict=0`。日本 JRA key 使用 JRA 官方英文重赏表/赛程，NAR 使用 `keiba.go.jp` 官方详情 URL，香港使用 HKJC 官方英文赛果术语；override 审核证据位于 `mapping-overrides-2026/`。
- 受控 commit 新建 `992` 个 `RaceSeries` 并绑定全部 `992` 场 2026 `RaceEvent`；幂等复跑返回 `series_created=0 / events_bound=0`。地区计数为日本 `186`、香港 `20`、英国 `202`、法国 `174`、美国 `410`，未绑定赛事为 `0`。
- 常驻生产配置最终确认 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`、`RACE_EVENT_CACHE_URL=redis://redis:6379/2`。当前 `HistoricalRaceEventTarget=0`、1984–2025 `RaceEvent=0`、公开历史赛事 `0`，尚未开始逐年目录抓取或历史详情落库。
- 下一步是任务 8.3：按五地区逐年采集 1984–当前官方 catalog source cache，生成只读年度总账；测试 fixture 不得充当生产完整目录。
- 用户已授权：准备任务、完整测试和 clean review 全部完成后，可自主执行生产部署、抓取与分批落库，无需逐批再次确认；最终必须恢复关闭历史功能/网络开关，历史年度赛事保持 draft，不提前公开。

## 2026-07-12 TJCIS 1998–2026 历史目录解析准备

- 新增 `prepare_tjcis_ics_catalog.py`，从 TJCIS 官方索引发现 1998–2026 International Cataloguing Standards 整本 PDF，统一解析日本、香港、英国、法国、美国平地及目标地区障碍分级赛。
- 真实网络必须同时具备 CLI `--allow-network` 和两个历史开关，并复用共享 request budget/source cache。`--resume` 只复用 manifest、大小和 SHA 一致的缓存；全缓存重放可在网络开关关闭时执行。
- 解析只接受 G1/G2/G3，支持老版点阵列、跨页名称、香港 Part I/II 赛季、Part IV 障碍页、AWT 和同名异场防覆盖。平地章节与年鉴自报 Graded/Group 总数强制对账。
- 真实 2016 整书烟测已用于锁定版式；后续全书生产验收发现 1998 年鉴正文等级标记与页尾 G1/G2/G3 汇总互相矛盾，因此 1998 不再视为通过，必须进入来源交叉核对。
- 新增/相关测试 `67` 项通过；完整 stable 发现 `724` 项，从错误 cwd 运行时仅有 2 个旧测试因相对 fixture 路径报错，从仓库根目录复跑均通过。`py_compile`、`git diff --check` 和最终 clean review 通过。
- 任务 `8.3` 仍未勾选：下一步部署后生成 1998–2026 source cache/部分候选总账，再补齐 1984–1997。完整总账、身份审核和批准完成前不得宣称全量完成。

## 2026-07-12 TJCIS 生产 source cache 与部分总账结果

- 生产机到 `tjcis.com:443` 连续 TLS/连接超时，2 次请求均未收到字节；改由本机同一正式工具在共享预算/source-cache 门禁下抓取，再将原始字节、manifest 和 SHA 完整同步生产，生产离线复验。
- 已缓存 1998–2026 共 `29` 本官方 PDF，加 2 个官方索引，总请求 `31/40`，原始 cache `82,494,754` bytes。生产逐文件大小/SHA 校验 `31/31` 通过；source summary SHA-256 为 `1a7aba7afac63b768fdcf8f994a9725a2471bddb6900c3313e4c1c7b537c7505`。
- 严格年度验收最终仅通过 `2016 / 2020 / 2021`；其余 `25` 年存在正文/页尾数量不一致、章节缺失、同名身份冲突或地区数量异常。1984–1997 仍完全缺少 TJCIS 在线整本覆盖。
- 标准候选 v3：`runtime/historical_race_inventory/tjcis-candidates-2016-2021-v3-20260712/`，共 `3,252` 行，日本 `404`、香港 `97`、英国 `894`、法国 `485`、美国 `1,372`，索引/附录/Listed 粘连质量扫描为 `0`；manifest SHA-256 `48b02ef77c02ef81e959331e5c927ddff412514c15caa8a0a6afbd23e67af1ac`。
- 部分 inventory v3：`runtime/historical_race_inventory/tjcis-inventory-partial-2016-2021-v3-20260712/`，`target_count=3,252`、`series_count=1,313`、`conflict_count=82`、`accounted_count=2`；冲突主要为历史标点/空格/命名差异，manifest SHA-256 `f422c8fc82a616d49c634e96e263745d8b0250026be7af939f9f1a06bc9ba955`。
- v3 仅是只读部分总账证据，未批准、未 commit。生产保持 `HistoricalRaceEventTarget=0`、1984–2025 `RaceEvent=0`、公开历史赛事 `0`；两个历史开关均为 `false`，公网 healthz 为 `200`。
- 因完整年度总账尚未形成，未启动赛事详情全量抓取。下一步按错误族修复/交叉核对 25 个年度，再做系列身份审核；只有 1984–当前总账完整且批准后才能进入详情批次。

## 2026-07-12 TJCIS 1998–2026 年度目录第二轮修复

- 已修复旧版国家码、带空格年龄、等级紧贴奖金、空页眉误拼、障碍赛距离缺失、重复声明翻倍，以及同名赛事候选 key 不稳定等问题。
- 专项解析器测试 `36` 项、目录相关组合测试 `49` 项通过，`git diff --check` 通过；复审未发现新的 actionable finding。
- 29 本 PDF 全量离线回放后，直接通过年份由 `3` 个增至 `11` 个：`2005 / 2007 / 2009 / 2012–2016 / 2020–2022`。2015 美国章节从错误的 `212` 条恢复为 `468` 条；2022 同名英国障碍赛已保留为不同审核候选。
- 全地区审计确认共有 `22` 个年份、`31` 个地区/项目组合存在“正文显式 G1/G2/G3 行与页脚声明小计不一致”。完整记录位于 `diagnostics/declared_count_reconciliation.json/csv`；不得删除、隐藏或用总数机械补造赛事。
- 已生成 1998–2026 共 29 份只读页文本诊断缓存，供相邻年和地区官方目录交叉核验；诊断缓存不能替代原始 PDF 和 SHA 证据。
- 生产仍为 `HistoricalRaceEventTarget=0`、pre-2026 `RaceEvent=0`、历史公开数 `0`；两个历史开关保持 `false`。下一步先完成 31 项来源冲突核验并生成完整身份审核包。
## 2026-07-13 法国新鲜度与多地区归属代码安全关闭上线

- 生产源码已从 `c998eb3f` 快进到 `badc10e028aa3c1f6f2984bbfad8c1e202101cdc`，基于最新代码重建 `umanewsbot:prod`，并成功应用 `stable.0029_france_freshness_translation_attribution`。`web / worker / beat / db / redis / nginx` 均正常运行，最近部署日志未发现 traceback、error、critical 或 exception。
- 部署前已保存 `.env.backup.france-multiregion-20260713_041004`；有效数据库备份为 `backups/db/pre-france-multiregion-20260713_041111.sql.gz`，大小约 114 MiB，SHA256 为 `a92e95fd8b10ceb7cd3721d4984d8f8d699b23edf6686615e289a12e6aa0c898`，`gzip -t` 通过。首次中断文件已明确改名为 `.incomplete`，不得用于恢复。
- 本次只部署代码，不启用新行为。`web / worker / beat` 实际设置均为 `MULTIREGION_ATTRIBUTION_MODE=off`、归属写入关闭、相关地区查询关闭、灰度阶段 `off`、gold 版本 `pending-review`、翻译自动重试关闭。新归属运行表可正常查询，当前 run/lock 均为 0。
- 邮件告警接收地址已配置为 `754652181@qq.com`，但生产尚无 SMTP/EMAIL_HOST 凭据，因此 `TRANSLATION_FAILURE_EMAIL_ENABLED=false`。在完成 SMTP 配置和测试邮件前，不得宣称邮件通知可用或开启该开关。
- 运行验收：服务器内部 `http://127.0.0.1/healthz/` 与公网 `http://umafans.run/healthz/` 返回 200；浏览器真实打开首页、法国频道和 `/news/8093/` 详情页均正常，详情页含 8 个正文段落且无前端错误。HTTPS 仍未接入证书，Nginx 443 TLS server 块原本即为注释状态，本次不将 HTTPS 计为已完成能力。
- 法国只读 probe 未写文章：France Galop / TDN France / TDN France Broad 分别得到 `20 / 4 / 12` 条列表候选，三个来源均为 accepted，抽取的 6 篇详情全部成功；最新样本时间覆盖 2026-07-10 至 2026-07-12，未再返回 2020/2022 历史稿。生产法国来源 13/14/21 仍为 enabled、production approved、最近抓取 success。
- 该日 OpenSpec 进度为 `59/68`，其双审 Gold 待办已由后续单审资格决策取代。当前 OpenSpec 为 `63/71`：159 条 Gold 已通过本地覆盖与质量门槛，生产 gold/dry-run、人工复核、时间修复与翻译小批处理、shadow/enforce 灰度、网页/测试群/正式群扩展和窗口数量验收仍未完成，因此 change 保持 `implementing`，不得归档。
## 2026-07-13 历史赛事第一批生产详情写入

- 第一批 selection snapshot 固定为五地区各 9 场、共 45 场，绑定 inventory manifest `ac61298f242b2c649c403eae4741771a43cdb027befef20bc75e18fe34bcbad7`。日期发现审核后形成 `36 ready / 9 pending gap`：日本、香港、法国各 9 场有日期；英国 6 场有日期、2000 年 3 场缺口；美国 3 场有日期、2000/2012 年 6 场缺口。
- 日期 apply 已创建 36 个 draft `RaceEvent`。详情抓取完成香港 9 场、日本 9 场、英国 6 场、美国 3 场；法国 9 场因尚无达到完整出马表与赛果要求的解析链路，继续作为显式详情 gap，不用空候选占位。
- 完整详情候选为 27 场，SHA-256 `c999be2b2b0790837f8a6f5888e7068e775c783a57c6f8e7f3298e41e9b67a04`。生产 dry-run 通过后，新建详情写入前备份 `backups/db/pre-historical-detail-first-acceptance-20260713_055500.sql.gz`，大小约 139 MB，`gzip -t` 通过，SHA-256 `5f0f9d94406d55954b078339f2a3796556f6ffc98b47c43d6bf2d14bbccde9ff`。
- 正式 apply 成功：27 个目标全部转为 `imported`，写入 `RaceEventRunner=297`、`RaceEventResult=287`、`RaceEventDataCandidate=54`，候选状态全部为 `applied`，并生成 27 条 `historical_target_imported` 操作日志。逐目标核验与候选条数完全一致。
- 第一批最终状态为 `27 imported / 9 ready / 9 pending`：法国 9 场保持 ready 等待详情；英国 2000 年 3 场、美国 2000/2012 年 6 场保持 pending 等待日期来源。36 个已建赛事全部为 draft，published 为 0。
- 详情 source cache 在生产保留 38 个文件、约 5.4 MB，manifest 所列 18 个源文件大小和 SHA-256 全部通过。当前数据库约 832,322,583 bytes；本批核心新增 638 行，另有 27 条操作日志，相关表容量无扩大批次 blocker。
- 常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；内外 `/healthz/` 均为 `ok`，容器正常，`web / worker / beat` 最近 20 分钟无 traceback/error。历史公开展示仍关闭，未执行前台发布验收。

## 2026-07-13 法国第一批详情补源进展

- 已从 ZEturf 精确定位并受控缓存法国 2012/2025 六场详情页；请求预算上限 50，实际仅抓取 R1/C1–C6 范围，缓存 manifest 保留逐文件大小、SHA-256 和来源 URL。2000 年页面在 ZEturf 已过期，仍保持缺口。
- 真实缓存首次回放暴露 2012 旧页面使用 `span.horse-name`、骑师/练马师节点结构变化，以及 2025 `Criterium de Saint-Cloud` 被误配到同日 `Criterium International`。已按 TDD 修复，法国 adapter 网络层同时改为统一 HTTPS host/重定向安全校验。
- 离线重跑结果为 `6/6` 唯一命中、`runners=70`、`results=41`、`skipped=0`、`errors=0`；runners 保留非出走状态，2012 旧页马名、骑师和练马师均可解析。
- 这六场尚未写生产：现有 target 批准的是 France Galop 日期/历史页，ZEturf 直接详情 URL 仍需通过独立、哈希锁定的来源补充 artifact 写回 target，之后才能由详情 packager 接受。禁止手工改 `source_refs` 或绕过 URL 绑定。
- 新增目标测试和完整 `stable` 回归均通过，完整测试现为 826 项；重新代码复审无 actionable finding。

## 2026-07-13 2016–2025 标准批次一号日美写入

- 首个年代带标准批次已批准 250 场，五地区各 50；selection snapshot 文件 SHA-256 为 `0724d55c904eb4072c8dfe741648a9678a71b447bc07fe59705ffa412a5be036`，approval SHA-256 为 `a046e17e2b5388ce7508eb644bcbf9437ec5af7d2ca7aa0523eccac84dd80a88`。
- 日本 50 场使用 JRA 官方年度表和单场赛果；美国 48 场由 TOBA 年表定位 Equibase Yearbook 单场结果，2 场障碍赛使用 NSA 官方结果。日期 artifact 中日美 `100 ready`，法港英 `150 gap`。
- 日期写入前备份 `pre-band-2016-2025-jra-us-date-apply-20260713_011232.sql.gz`，大小 `117378172`，SHA-256 `d93a26469dee057a70164eb7dc4f7f6a459fcf3c85f846b1713c0555213d6847`；100 场均已 materialize。
- 详情来源 artifact `c91872542a03db6519d29148c442ca9d38adc9cc52db6c247806eb5773ba9aec` 批准 98 场。日本 50 场和美国平地 48 场最终全部 imported，共 `1157 runners / 1080 results`；两场 NSA 障碍赛仍为 ready 详情缺口。
- Equibase 退赛现使用稳定 `SCR-n`；存储名次连续唯一并以 `official_finish_position` 保留并列。dry-run 会提前拒绝重复马号和重复存储名次，完整 `stable` 回归 `865/865` 通过。
- 一次 ARM64 镜像误部署使 web unhealthy，未迁移且未写详情数据，已立即回滚；后续改在生产机原生构建并核验 AMD64。当前 healthz 正常，常驻两个历史开关和公开开关仍关闭。

## 2026-07-13 NSA 两场补齐与生产兼容阻断

- 美国两场障碍赛已由 NSA 官方结果 PDF 补齐：A.P. Smithwick Memorial 为 `8 runners / 8 results`，Beverly R. Steinman Memorial 为 `7 runners / 6 results`；后者保留 faller CARLOUN 为 runner，不伪造完赛名次。候选 SHA-256 为 `478e263ee1b2e07ca6ef3cba23c683549393400b263ae250eef9b15fa0c3a1ff`。
- 写入前备份为 `backups/db/pre-band-2016-2025-nsa-import-20260713_015750.sql.gz`，大小 `117926527` bytes，SHA-256 `9a34f879a98e0fd8bda27b426b81f009bf6fcef0ce882b031589fe7c8867f3bc`。dry-run 与正式 apply 均通过；至此标准批次日美 100 场全部 imported，共 `1172 runners / 1094 results`，常驻历史功能、网络和公开展示开关继续关闭。
- 随后发现生产 `umanewsbot:prod` 被历史分支旧底座镜像覆盖：镜像含历史能力，但缺少 `origin/main@badc10e0` 的法国新鲜度、翻译恢复、多地区归属代码及 `stable.0027–0029` 对应写路径。数据库已经应用 `0029`，netkeiba 新增触发 `attribution_rule_version` 非空约束错误；收到 P0 后已立即停止新的历史写入、生产构建和容器重启，恢复动作由生产协调线程接管。
- 当前历史 worktree 已合入 `origin/main@1a70b22e`，保留全部历史能力并通过 Django check、迁移无漂移、323 项组合测试、完整 `stable 1093/1093`（1 skip）、OpenSpec strict `25/25` 和 `git diff --check`。生产镜像替换继续由生产协调线程统一执行。
- 生产协调已短时切回 `umanewsbot:pre-irishracing-20260713`（`sha256:982fac66…`），恢复后成功新增并翻译 9 篇 netkeiba 文章，新增 NULL 约束异常为 0。独立 staging 已构建兼容镜像 `umanewsbot:merged-main-historical-amd64-20260713-1008`，完整 ID `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`，内容 commit `0068715fceb0f629b5bfcb0c0b760427dfc6edc5`，构建树 SHA-256 `e51e6992e57649445aeff2aa7f2a0c925f3c5c742771fceac13053459beceec6`。该镜像尚未 retag 为 prod、未重启容器，等待生产协调线程最终切换。

## 2026-07-13 兼容镜像切换与法港英 150 场详情证据

- 生产 `web / worker / beat` 已由协调线程正式切换到兼容镜像 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`；`stable.0027–0029`、Django check、64 个模型、新闻新开关关闭、历史命令、五地区页面/后台/healthz 和日志均通过。回滚镜像为 `pre-merged-main-historical-20260713-1015`。历史线程不得再次重建或重启生产容器。
- 2016–2025 标准批次剩余法国、香港、英国各 50 场已完成日期定位与详情抓取：法国 `449 runners / 330 results`，香港 `515 / 506`，英国修正 Aintree Bowl 误配后为 `570 / 458`；三地区均 `50/50` 无跳过、无错误。
- 详情来源按目标一一对应，三地区分别 50 个唯一 URL、全局 `150/150` 唯一。统一日期发现证据包包含 150 条 provider 记录、150 条成功请求账本和 150 个逐文件大小/SHA-256 验证的缓存文件，共 `38,383,091` bytes，绑定 inventory manifest `ac61298f242b2c649c403eae4741771a43cdb027befef20bc75e18fe34bcbad7`。
- Aintree Bowl 现绑定 Sporting Life race ID `850965`，Aintree Hurdle 保持 `850966`；详情 URL 去重以移除 fragment 后的规范 URL 为准。生产只读 artifact 首次构建另发现 47 场英国距离证据缺显式单位或为紧凑分数写法，现已按 `<5 mile / >=5 furlong` 和 mile/furlong/yard 规则规范化，并修复 `71/2f` 的距离消歧误读。专项 57 项及完整 `stable 1128` 项通过，Django check、迁移漂移、OpenSpec strict 和 diff 检查通过，最终复审无剩余可修复问题。
- 日期 artifact v2 已批准并受控提交，manifest SHA-256 为 `e5ede9033485f59faac8d27c5371bd4749c17235119f4eea173cca07cc389b03`；写入前备份 `pre-band-2016-2025-fr-hk-uk-date-apply-20260713_122142.sql.gz` 为 `121,994,037` bytes，SHA-256 `dae5869d58eb7e854d359f333e979b52647da75db667db930ff53d1cce5f521f`，`gzip -t` 通过。
- 150 个目标现均为 `ready` 并 materialize 为 150 个 draft `RaceEvent`；生产历史累计为 `145 imported + 150 ready`、2026 年前赛事 `295`，详情仍为 `1,640 runners / 1,523 results`，证明本次只写日期与赛事壳，未提前导入详情。用户要求先完成源码 Git 固化，后续详情打包、coverage、dry-run、第二次备份和正式导入现已暂停。历史公开展示开关继续关闭。

## 2026-07-13 线上验收发现旧底座镜像覆盖并完成组合镜像恢复

- `10:00` 左右验收发现生产仓库 HEAD 虽为 `1a70b22e`，运行镜像却已被历史赛事任务从旧代码底座重建为 `deadheat-fix-amd64-20260713`。该镜像仅加载 57 个模型，不认识 `stable.0027-0029` 和新增设置；数据库已经应用 `0029`，因此 netkeiba 新稿插入触发 `attribution_rule_version` 非空约束失败。问题属于应用镜像与数据库 schema 不匹配，不是来源失效。
- 已在 Celery/one-off 为空时短时切回 `pre-irishracing-20260713`，恢复后 netkeiba 完整抓取成功：新增 `3`、重复 `117`；本次恢复后共新增 9 篇，9 篇均完成翻译，`attribution_rule_version IS NULL=0`。由验收同步探测中断产生的 `CrawlJob 16266` 已显式标记失败并注明原因，未遗留伪运行状态。
- 历史赛事 worktree 已合入 `origin/main@1a70b22e`，组合源码通过专项 `323` 项、完整 `stable 1093` 项（1 skip）、Django/迁移/OpenSpec/diff 检查。生产最终切换到 AMD64 组合镜像 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`，镜像 tag 为 `umanewsbot:merged-main-historical-amd64-20260713-1008`；内容 commit 标签 `0068715fceb0f629b5bfcb0c0b760427dfc6edc5`，构建上下文树 SHA256 `e51e6992e57649445aeff2aa7f2a0c925f3c5c742771fceac13053459beceec6`。
- 最终运行验收：`web/worker/beat` 使用上述同一镜像，`stable.0029` 已应用，Django check 通过；归属、相关地区查询、翻译自动重试与失败邮件继续关闭。五地区页、后台登录入口和 HTTP `/healthz/` 全部返回 200，最近日志无 traceback/error/not-null constraint。
- 组合镜像包含历史任务尚未全部提交到 `main` 的实现，虽然已绑定内容 commit、上下文树 SHA 和回滚镜像，但仍不是最终可复现发布。历史任务完成当前批次后必须提交并推送全部生产代码；后续生产重建必须先合入最新 `origin/main`，禁止从旧分支或旧上下文直接覆盖 `umanewsbot:prod`。

## 2026-07-14 多地区归属 V3 单审校准优化

- 用户确认不再补充 Gold Set 或第二审核人；法国、美国未选地区的空白行继续忽略。现有审核包固定为 `159` 条单审标签、`1` 条明确排除、`90` 条未选择，始终标记 `provisional_single_review`，不得用于归属 commit 或生产启用资格。
- 为避免继续扫描生产数据库，已用审核包冻结文章和一次性术语快照建立本地 SQLite 校准库。旧规则在相同 `159` 条分母上的基线为主地区 `81.76%`、相关 precision `6.67%`、recall `6.45%`；生产此前 154 条结果只因 5 篇输入 SHA 漂移，不再作为算法同分母对比。
- `multiregion-v3` 增加按语言 token/bigram 的 `AttributionTermIndex`，17,474 条术语、38,806 个候选下，159 篇纯推断约 `0.8` 秒，完整 Docker 评估约 `2–4` 秒；候选命中后仍调用原边界匹配器。主地区达到 `98.11%`，日本/香港/英国/美国 `100%`、法国 `90.91%`、other `60%`；相关 precision `100%`、recall `54.84%`，无依据变化 `1.89%`、过度扩散 `0%`。
- V3 规则按标题叙事中心、明确赛事、导语唯一上下文、来源 fallback 分层；普通单词马名、短日文马名、同名单词赛事和正文背景不得单独改区。`other` 现在可作为主/相关归属证据持久化，但不新增生产频道、发布配额或 QQ 窗口。文章没有提供的历史参赛地区不为提高 recall 自动补齐。
- enforce 遇到 `needs_review` 时只写 `review_candidate` 审计，不修改主地区或关联表。归属/相关地区生产开关继续保持关闭，本轮没有部署、生产归属写入、镜像构建或容器重启。
- 归属与 Gold 审核目标测试 `82` 项通过（其中 1 项 PostgreSQL 专用性能测试在 SQLite 环境按设计跳过）；从仓库根目录、内存 Celery backend 运行最终完整 `stable` 回归为 `1156 passed / 1 skipped`。Django check、迁移无漂移、Python compileall、OpenSpec strict/all `25/25` 均通过。PostgreSQL 250 篇基准、生产 72 小时 dry-run 和灰度仍待后续验证。

## 2026-07-13 法港英详情导入前字段门禁与 Git 固化

- 生产只读导出的法港英 150 个 ready 目标与审核证据对比后确认：日期 apply 已物化赛事日期和来源，但 `distance_text` 仍沿用原始 TJCIS 裸数字，未保留法国/香港的米制 `m` 和英国的 `mile/furlong/yard` 单位；另有 8 个权威场地名和 6 个法国 surface 差异需要在详情导入前校正。
- 已新增 `import_historical_race_event_field_candidates` 管理命令和整批服务。候选 JSONL 同时绑定整文件 SHA、target SHA、inventory artifact SHA、字段证据 SHA 和逐来源快照；仅允许基础字段白名单，dry-run 输出逐字段 before/after，apply 保护人工锁并同时锁定 target/RaceEvent，任一目标漂移或后段失败都会整批回滚。
- 基础字段 apply 会改变 target SHA，旧详情候选因此自动失效；正确顺序固定为字段 dry-run/备份/apply、重新导出 event input、重新打包详情、coverage、详情 dry-run/第二次备份/apply。禁止手工修改生产 `RaceEvent` 或复用旧候选绕过身份校验。
- 本轮目标/相邻测试 `34/89` 项通过；在临时 Redis 和 macOS 真实临时目录下完整 `stable` 回归 `1136/1136` 通过，1 项按设计跳过。Django check、迁移无漂移、OpenSpec strict 和 `git diff --check` 均通过；两轮代码复审最终无待修问题。
- 当前生产仍运行 `main@304ebdb6` 对应可复现 AMD64 镜像，历史公开数据保持关闭。本轮字段门禁尚未部署，也未执行字段或详情生产写入；先完成源码提交、推送和合入最新 `main`，再由最新主线构建并受控替换生产镜像。

## 2026-07-13 历史来源匹配器主线固化与可复现镜像切换

- 历史赛事全部必须保留的源码已提交并合入 `main@58786b91fba9c44054a6102055766824677bcbcb`。该版本新增 JRA 当前赛事别名、TOBA 核心限定词全词匹配、同一结果 URL 跨目标复用阻断，以及 TOBA `not run` 证据解析；完整 `stable` 回归为 `1141 passed / 1 skipped`，迁移无漂移，OpenSpec strict/all `25/25`，最终代码复审无 actionable finding。
- 在生产独立上下文 `/opt/umanewsbot-builds/main-58786b91-20260713-1435` 两次构建得到相同 AMD64 image ID `sha256:c6a3670fdc42db9c0b8ded5772630ac1b0511b98a521ea7f4a9cbe7e25864691`。镜像标签绑定 Git tree `5d8b7ccf775f6be7051c88e8f440b034ad02f4df` 和 source archive SHA-256 `184f05c39d3df5dd0bb1f410bdccda418ed3052964edea99b07faf22723fa07e`，已替换生产 `web / worker / beat`。
- 切换前数据库备份为 `backups/db/pre-main-58786b91-20260713_143748.sql.gz`，大小 `149,960,820` bytes，SHA-256 `9f29cd1a28b41761591a1966c68125c611a36290953cf0d845cdcead05891f27`，`gzip -t` 通过；旧镜像保留为 `pre-main-58786b91-20260713-1439`。
- 部署后 `stable.0029_france_freshness_translation_attribution` 已应用、64 个模型可加载，五地区页面、赛事页、马匹页、后台、内外 healthz 和近期日志均通过。生产历史总账 `30,917` 个目标，历史赛事 `295` 场、`3,174 runners / 2,817 results`，全部仍为 `draft`，published 为 `0`；常驻历史写入与网络开关均为 `false`。
- 切换后的 `14:45` 自然窗口完整通过：`17` 个 crawl、`5` 个 publish、`5` 个 QQ 窗口全部 succeeded；抓取共 seen `472`、new `3`，新增文章 `attribution_rule_version IS NULL=0`，web/worker/beat 近期错误日志均为 `0`。
- `2016–2025` 第二标准批次已固定五地区各 50 场。日美离线来源发现得到 JRA 50 条、Equibase 48 条，共 98 个唯一 URL；Brooklyn 与 Cougar II 的 2025 届由 TOBA 标记为 `not run`，继续等待产品口径审核，其余 248 个目标不受阻塞。

## 2026-07-13 紧凑英制距离修复生产切换

- 紧凑英制距离修复已进入 `main@d8b65fe7d63e913cf826d02a74cdebaec60351ce`，并由生产机独立构建为 AMD64 镜像 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`。镜像标签绑定 Git tree `fda256535ae3b9f435cf8c7b069ff26d04503d99` 和 source archive SHA-256 `2b085d0226580295f9a844fbc92df48405cd9bb3b467786230fac8941fa60520`。
- 切换前确认外部导入、外部锁、Celery active/reserved 和 one-off 写入均为空；停止 beat、排空并停止 worker 后才 retag。生产 `web / worker / beat` 现统一运行上述镜像，旧镜像 `sha256:c6a3670f...64691` 已保留为 `rollback-pre-d8b65fe7-20260713_163805`。
- `.env` 备份为 `.env.backup.main-d8b65fe7-20260713_163805`。数据库备份为 `backups/db/pre-main-d8b65fe7-20260713_163805.sql.gz`，大小 `124,020,905` bytes，SHA-256 `33f5ef3520e833a8cf343ca87831a7620c9cb80ba095e74c5cadb716d55ccfa2`，`gzip -t` 通过。
- 部署没有新增迁移；Django check、静态资源收集、内外 healthz、首页、赛事页、worker ping 和近期错误日志均通过。生产纯函数 smoke 已确认 `2m4f` 解析为 2 mile + 4 furlong，`3m21/2f` 解析为 3 mile + 2.5 furlong，且保留来源原文。
- 常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，多地区归属与相关地区查询也继续关闭。本次只切换代码，没有执行历史赛事写入。
- 使用新镜像连接生产库只读重建 batch002 日期 artifact，结果精确为 `246 candidate / 4 gap`：法国/香港/日本各 50，英国/美国各 48；4 个 gap 仍是两场英国 `ABANDONED` 和两场美国 TOBA `not run`。manifest SHA-256 为 `9ed3b7138012b4ce1732cf1f071d13cb16678a97983ea63d94329fe84c902e68`，尚未审批、备份或 commit。

## 2026-07-13 第三标准批次只读证据完成

- batch003 selection 固定为五地区各 50 场、共 250 场，与 batch002 零重叠；本轮没有执行生产写入。
- 首次离线快照曾为 `249 candidate / 1 gap`、`2,635 runners / 2,346 results`，候选 SHA-256 `31c8cf61191d937c766f98b50a656ec98e92f774b59e5d0635fd54090ee2ad1a`；该快照遗漏 Hampton 移师后的实际赛果，已隔离并被上方 batch003 正式结果取代，不得审批或恢复。
- `target_id=60693` 的 Warwick 页面只证明原定场次 `ABANDONED`；用户提供 Windsor 正式结果后已按正常举办收口，不能再作为 gap 或 cancelled 候选。
- 修复了 ZEturf 发现页把实际缓存 URL 重写成另一目标 slug 的身份错误，并把 NAR `keiba.go.jp` 与法国 Zone-Turf 同步登记到日期校验、补充来源审批和最终详情打包三层。年度日历的 `flat/jumps` 只证明竞赛类型，不再用它覆盖已审核的 `surface`；Hoppings Stakes 保持 Newcastle synthetic。
- 专项 73 项、完整 `stable 1161/1161`（1 skip）、Django check、迁移无漂移、OpenSpec strict `25/25` 和 `git diff --check` 全部通过；代码复审无剩余可修复问题。
- 生产仍运行 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`。先前候选镜像 `sha256:9cd0b966...45bc1` 不包含本轮来源修复，已视为过期；必须从最新 main 重建可复现 AMD64 镜像后，才允许连接生产库生成日期/来源 artifact、dry-run 和后续受控写入。历史公开展示继续关闭。

## 2026-07-13 batch003 来源门禁镜像生产切换

- batch003 来源门禁修复已合入 `main@3939992c7d3753779fc34de81c595f5a34d7ed2b`，生产现运行 AMD64 镜像 `sha256:87c435cfc50344d0ca94f46e44d4bea97ab11361f88f7c708b6457331aee78ec`。镜像标签绑定 Git tree `0464a1aae6f587e3ba021421ac84b44a3d9379dd` 和 source archive SHA-256 `a787391c84a4ba3bb22c2ab638f1e36453d3ff8869bb95aeb5001b1dd448bb21`。
- 切换前发现两条正常新闻抓取任务正在执行，因此先停止 beat 并等待任务自然完成；确认 Celery active/reserved、外部导入、外部锁和 one-off 历史写入均为空后才继续。生产 `web / worker / beat` 已统一切换到新镜像。
- `.env` 备份为 `.env.backup.main-3939992c-20260713_185140`。数据库备份为 `backups/db/pre-main-3939992c-20260713_185140.sql.gz`，大小 `125,782,755` bytes，SHA-256 `21903cf8d9494ef6053414a34c2e2f6ab01406b9ffebcf56ff3fd10eedfc0967`，`gzip -t` 通过；旧镜像回滚标签为 `umanewsbot:rollback-pre-3939992c-20260713_185140`。
- 无待应用迁移；Django check、静态资源、worker ping、内外 healthz、首页、赛事页和近期错误日志均通过。常驻历史写入/网络、历史公开、多地区归属及相关地区查询开关继续关闭。
- 该镜像切换步骤本身没有执行 batch003 写入；随后历史线程已按独立 approval、备份和门禁完成上方 250/250 正式导入。旧的 `249 candidate / 1 Hampton gap` 预期已经作废。
