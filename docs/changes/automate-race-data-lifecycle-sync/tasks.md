# 赛事时间、出马表与赛果自动同步任务清单

## 0. 目标与授权口径

- [x] (operations) 从 `origin/main@2833558a` 建立 clean worktree，保留用户主 checkout 的历史 dirty。
- [x] (application) 将产品目标锁定为：未来赛事时间自动补齐、状态自动推进、出马表至少每日两次、
  T+3 起自动获取赛果并持续更正。
- [x] (integration) 将来源优先级锁定为 `licensed_api > official_operator > trusted_publisher`；三类均为
  无需逐场人工确认的正式来源，前台不显示来源或内部阶段标签。
- [x] (operations) 按用户明确授权覆盖旧的多 PR、固定 7 天 shadow、逐地区/逐赛事人工批准门禁；
  dry-run 通过后只再请求一次最终生产确认，启用过程仍按开关分步并自动止损。

## R0：统一控制面、纳管与队列隔离

- [x] (application) 新增 `data_sync` projection owner、enrollment、provider checkpoint、claim/generation/
  attempt token/plan SHA CAS、future standing policy 和每小时自动发现。
- [x] (integration) 实现 selector、动态 checkpoint、provider/region/date 共享请求计划与身份发现公平轮转。
- [x] (operations) 新增只消费 `race_sync_v2` 的专用 worker；发布、恢复和回滚控制面完整纳入该服务，
  遗留 `race_live` 队列不清理、不迁移、不消费。
- [x] (integration) transport 前原子预留 provider/region/day 请求与字节预算，并验证 artifact root、
  high/low water、hold 和最小剩余磁盘。
- [x] (integration) 投影事务内再次锁定并验证 exact claim、enrollment/owner generation、plan、checkpoint
  version 与 claim expiry；网络期间过期或被接管的 worker 只能留下 immutable observation，不能写 canonical。

## R1：赛事时间与状态

- [x] (application) 解析并校验 aware `race_datetime`、IANA timezone、local date/time，禁止缺时间时猜默认值。
- [x] (application) 按来源优先级与 manual lock 仲裁，时间变更追加 field decision 并使旧 generation 失效。
- [x] (application) lifecycle 自动执行 `scheduled -> running`（T）和 `scheduled/running -> finished`
  （T+30）；postponed 等待新时间，cancelled 不误推进。
- [x] (integration) 完整赛果投影可在同一事务补齐 `finished` transition，且不会把 `finished` 误当成已有赛果。

## R2：出马表

- [x] (application) 实现 immutable racecard observation/revision、participant identity、runner 兼容投影、
  补出/退赛/换骑师/改档和缺行不等于删除。
- [x] (integration) 动态 cadence 在远期不超过 12 小时，临近赛事逐步缩短到 6 小时、1 小时和 10 分钟，
  满足每天至少两次。
- [x] (integration) 未关联 `HorseProfile` 不阻塞出马表或赛果，manual lock 与身份冲突继续 fail closed。

## R3：赛果与更正

- [x] (integration) The Racing API 是联网主链；主 API result not-found 后先尝试已有 HKJC/France Galop
  官方导入事实，再尝试 Sporting Life/ZEturf/HRN immutable receipt。
- [x] (application) 从 T+3 起按动态检查点抓取，T+30 后继续补偿；成功赛果保留 7 天自动更正观察。
- [x] (application) 终态、完整 roster、稳定身份和合同有效后自动创建不可变 revision 并投影；partial、
  schema drift、身份多解或 manual lock 不公开。
- [x] (application) `reported_finish_position` 保留并列名次，内部 `finish_position` 保持唯一稳定排序；更正
  新增 superseding revision，不覆盖历史证据。
- [x] (application) 前台统一显示“赛果”，不暴露 provider、source class 或 provisional/official/corrected 标签。

## R4：配置、观测、回滚与文档

- [x] (operations) migration 0074/0075、普通/生产/low-cost Compose、Beat route、worker 启动脚本和
  `.env.example` 已同步；全部新开关默认 false、容量默认 0。
- [x] (operations) 新增 `audit_race_data_sync` 和 standing-policy renderer；审计固定 `would_write=false`，
  输出 route drift、coverage、checkpoint、capacity 和 ledger。
- [x] (operations) 一级止损为关闭总开关、future discovery、network、lifecycle、各 apply/public；保留
  observation/revision/transition，不清空队列、不批量反向状态。
- [x] (operations) 更新 current state、decisions、deploy runbook、overview、project status、spec/design/
  rollout/test cases 和实现报告，删除与用户目标冲突的旧门禁描述。

## 验证与 PR

- [x] (application) claim 投影硬化覆盖 claim 被替换、过期、data-kind 越权以及旧 worker 终态/释放；
  局部组合 125/125，最终完整聚焦 SQLite 202/202。
- [x] (integration) 隔离 PostgreSQL 16 专项最终 24/24，覆盖行锁、并发幂等、约束、migration，以及
  superseded claim 在真实数据库上零 canonical 投影。
- [x] (operations) Django check、migration drift、compileall、Compose 解析、secret 扫描和 `git diff --check` 通过。
- [x] (operations) 全新 SQLite 全配置审计为 `ready`、`route_drift=[]`、`would_write=false`，审计前后数据库
  SHA-256 相同。
- [x] (operations) claim 硬化后重跑 684 项扩展相邻套件；相对 `origin/main` 的规范化失败/错误集合
  `current-only=0`，并消除基线 3 项既有失败。
- [x] (integration) claim 投影硬化后完整聚焦 SQLite 202/202、隔离 PostgreSQL 16 专项 24/24。
- [x] (operations) 实现已提交、推送并创建 PR #108；PR 当前 OPEN/MERGEABLE，生产未改动。

## 最终生产发布

- [ ] (operations) 取得用户对 PR #108 合并及生产部署的最终确认。
- [ ] (operations) 合并后绑定精确 revision/tree/archive/image，建立隔离 release；不得在 1,710 项 dirty 的
  `/opt/umanewsbot` checkout 直接 pull、checkout 或清理。
- [ ] (operations) 创建 PostgreSQL custom-format 备份，记录权限/大小/SHA 并通过 `pg_restore --list`。
- [ ] (operations) 所有新开关关闭应用 0074/0075，验证 web/worker/Beat 同 image/revision、healthz、迁移和
  flag-off 三零；磁盘低于 8 GiB 时停止。
- [ ] (operations) 写入冻结容量与 allowlist，按 future discovery -> network/time/racecard -> lifecycle ->
  result apply/public -> correction 顺序启用，每一步核对 run、claim、请求、revision、公开页和错误率。
- [ ] (operations) 验证 `race_sync_v2_worker` 正常消费新队列、旧 `race_live=7543` 不变，并记录 release evidence。
