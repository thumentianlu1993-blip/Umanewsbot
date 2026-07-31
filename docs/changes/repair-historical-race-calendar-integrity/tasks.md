# 历史赛事赛历完整性修复任务

> 方案审核和用户实现授权均已取得；Release A 早期实现快照曾通过第二轮限定代码审查，但随后
> 的 P1/P2 加固、PostgreSQL 专项和文档增量使原 fingerprint 失效，当前必须重新 review。
> 勾选项不表示发布或生产数据授权。

## 0. Pre-declared hypotheses

- [ ] 0.1 (application) 赛事日历每页数据库候选最多 41 个主 event，聚焦 view query count
  `PASS <= 12 / BLOCKER > 12`，实现前先记录旧基线
- [ ] 0.2 (application) PostgreSQL explain 不得出现全年结果在 Python materialize；单页查询
  `PASS p95 <= 300ms / BLOCKER > 1000ms`（本地固定 50k event 数据集）
- [ ] 0.3 (operations) Release A/B/C schema migration 单次排他锁等待
  `PASS <= 5s / BLOCKER > 15s`，单次 migration wall time
  `PASS <= 60s / BLOCKER > 180s`
  - [x] Release A 真实 PostgreSQL：`pg_locks` wait 约 `0.024s`，fresh migrate `7.96s`，
    forward `0.346s`，reverse `0.463–0.475s`；B/C 尚不存在，故总项保持未勾选
- [ ] 0.4 (integration) 全库 prepare 使用流式/分页读取，50k event fixture
  `PASS peak RSS <= 512MiB、artifact <= 256MiB / BLOCKER 超任一上限`
- [ ] 0.5 (integration) 单次 apply action `PASS <= 500 event、事务 <= 120s、锁等待 <= 5s /
  BLOCKER 超任一上限`；超限必须重新分 scope、更新设计并复审

## 1. RED：年份与模型

- [x] 1.1 (application) 新增 `RaceEvent.edition_year`、自然年一致性、target/event 届次关联的模型和
  service RED
- [ ] 1.2 (application) 新增 series/edition 唯一约束与 Release A/B/C 独立 migration plan 测试，
  包括真实 PostgreSQL
- [x] 1.3 (application) 新增普通香港马季、香港/非香港合法延期和未分类 mismatch fixture
- [x] 1.4 (application) 新增 target supersession 状态/条件唯一和
  `HistoricalRaceCalendarRepairReceipt` exactly-once 模型 RED

## 2. RED：公开筛选与路由

- [x] 2.1 (application) 新增历史重点 G1/G2 等级族及当前/未来运营口径回归 RED
- [x] 2.2 (application) 新增 year/q 超过 40 条的前后 keyset 分页、同日边界、筛选守恒和篡改游标 RED
- [ ] 2.3 (application) 新增统一 public-path registry、301、canonical sitemap、串行/并发冲突 RED
  （registry/301/sitemap 与串行唯一冲突已有覆盖；真实并发冲突尚未验证）

## 3. RED：无马号采集

- [x] 3.1 (integration) 新增马号占位符、多匹缺号、合法字母数字马号和真实冲突 RED
- [ ] 3.2 (integration) 固化 A. P. Smithwick Hurdle 及三个已知跨栏错误的脱敏离线 fixture
- [x] 3.3 (integration) 新增 fresh output root 合同与旧 checkpoint 无迁移拒绝 RED

## 4. RED：香港审核与修复

- [ ] 4.1 (integration) 新增全地区 census/香港强制 action、连续链 duplicate、依赖哈希和零写入 RED
- [ ] 4.2 (integration) 新增 manifest/approval/actor/precondition 漂移、target 重编号与 duplicate
  canonicalization RED
- [x] 4.3 (integration) 新增 maintenance admission、并发 writer、crash point、
  `HistoricalRaceCalendarRepairReceipt` 和 rollback RED
- [ ] 4.4 (integration) 新增独立 verifier 的全库自然年/届次/registry/依赖守恒 RED

## 5. GREEN：年份双语义

- [x] 5.1 (application) 新增 Release A `edition_year` nullable/public-path registry migration、
  target supersession、`HistoricalRaceCalendarRepairReceipt`、回填和兼容索引；B/C migration
  尚不存在
- [x] 5.2 (integration) 实现集中式年份 helper，接入 historical materialize/date discovery/
  inventory/import/detail 链
- [x] 5.3 (integration) 以 `RaceEvent`/target/public-path 集中 writer admission 覆盖当前赛事
  初始化、reconciliation、crawl、P0/race-live 及历史写路径；已知 bulk identity 写显式拒绝
- [x] 5.4 (application) 更新模型关联合同、管理命令和兼容序列化字段
- [ ] 5.5 (application) 全库 census 通过后单独创建/审核 Release B 约束切换 migration
- [ ] 5.6 (application) data verifier 通过后单独创建/审核 Release C non-null/自然年 check migration

## 6. GREEN：前台

- [x] 6.1 (application) 实现历史年份 key=G1/G2、当前/未来/无年份沿用运营重点
- [x] 6.2 (application) 实现版本化签名复合游标、筛选 fingerprint 和 year/q 双向分页
- [ ] 6.3 (application) 消除搜索 join 重复，保持每页固定查询上限并按需要补索引
- [x] 6.4 (application) 新增统一 `RaceEventPublicPath` registry、详情解析/301 和 canonical-only sitemap
- [ ] 6.5 (application) 更新模板分页入口、年份/筛选保留和合法延期届次辅助显示

## 7. GREEN：collector

- [x] 7.1 (integration) 实现马号占位符归一化并在 identity/dedupe/checkpoint/output 前统一使用
- [x] 7.2 (integration) 实现真实马号、profile/source ID、规范化马名的分层身份与 ambiguity gap
- [x] 7.3 (integration) 锁定 fresh output root，明确拒绝全部旧 checkpoint，不提供迁移路径
- [x] 7.4 (integration) 增加缺号 fallback 和真实冲突可观测计数

## 8. GREEN：全库 census 与香港数据治理工具

- [x] 8.1 (integration) 实现全地区只读 census、全香港 action/依赖图和人工分类 artifact service
- [x] 8.2 (application) 实现 prepare/apply/rollback/verifier 管理命令的参数、actor 和输出门禁
- [x] 8.3 (integration) 复用 identity review approval 模式，实现 manifest/approval/precondition、
  maintenance、锁序、duplicate 固定终态和 repair receipt
- [x] 8.4 (integration) 实现幂等 apply、精确 rollback、crash recovery 和未知状态 fail closed
  （覆盖 ledger 落盘后/receipt 前中断、精确重试恢复、篡改拒绝）
- [x] 8.5 (integration) 实现独立只读 verifier 与机器/人工报告

## 9. REFACTOR 与验证

- [x] 9.1 (application) 运行模型、历史批次、前台、路由、sitemap、系列、P0 和 race-live 聚焦套件
- [x] 9.2 (integration) 运行年度 collector 全部离线 unittest，并从 fresh checkpoint 验证三个跨栏 fixture
- [x] 9.3a (application) 运行真实 PostgreSQL Release A migration/约束/shared-exclusive 并发
  专项两轮 `5/5`，并删除临时容器/tmpfs
- [ ] 9.3b (application) 运行真实 PostgreSQL 全服务 prepare/apply/rollback；当前尚未执行
- [ ] 9.4 (application) 运行 `manage.py check`、迁移漂移检查与完整 `stable` 回归
- [ ] 9.5 (operations) 验证两份 Compose config、部署前备份/恢复命令和 runbook 一致性
- [ ] 9.6 (operations) 精确同步旧 `backfill-race-events-to-1984` 年份/重点合同，废弃
  `hong_kong_racing_season_spans_calendar_years` 并更新 deploy runbook
- [x] 9.7 (operations) 更新 `current_state`、`project_status`、`decisions` 和本 change review handoff

## 10. 方案与代码审核门禁

- [x] 10.1 (application) 当前五文档经独立方案 reviewer 三轮审核，关闭全部 actionable findings
- [x] 10.2 (application) 主线程汇报最终范围、RED、数据边界、风险/回滚，等待用户明确实现授权
- [ ] 10.3 (application) 实现完成后由未参与实现的独立 reviewer 执行受指纹保护的原生只读 review
  （URL 中央 validator P1 已获限定复审 APPROVED；本次 evidence-only 文档写回使 content 过期，
  须复用同一 reviewer 完成 evidence 复审后才能勾选总项）
- [ ] 10.4 (operations) 最新成功 review 后另行等待用户发布授权；不得复用实现授权

## 11. 生产阶段（不由代码部署自动触发）

- [ ] 11.1 (operations) Release A 关闭态部署，只含 nullable schema/兼容代码，保存 migration leaf
- [ ] 11.2 (integration) 经独立生产只读授权生成全库 census/香港 action artifact
- [ ] 11.3 (application) 人工审核 artifact，冲突清零并冻结精确 SHA
- [ ] 11.4 (operations) census 通过后单独 review/授权/部署 Release B 系列约束切换
- [ ] 11.5 (operations) 取得精确生产写入授权，进入 maintenance 并创建/验证 PostgreSQL 备份
- [ ] 11.6 (integration) 执行批准 action、独立 verifier 与公网抽检
- [ ] 11.7 (operations) verifier 通过后单独 review/授权/部署 Release C 最终约束
- [ ] 11.8 (operations) evidence-only 收尾并复用同一代码 reviewer 会话审核事实文档

## 12. 当前本地证据边界

- 最新主线程 Django `205/205`，collector 离线套件 `101/101`；URL + detail 子聚焦
  `166/166`、gate 子聚焦 `68/68`。
- Django check、`makemigrations --check --dry-run`、migration graph/漂移检查和
  `git diff --check` 通过。
- 完整 `stable`：`3989 tests / 25 failures / 54 errors / 72 skipped`。失败包含测试子进程
  缺少 `python` PATH、Redis 不可达、时效测试、旧 CSV 门禁和 migration-owner guard；
  该结果不能表述为全绿，亦不替代未执行的 50k 性能验证。
- 真实 PostgreSQL Release A 专项连续两轮 `5/5`；migration、约束、shared/exclusive lock
  并发、gate 重查/exit 已覆盖。此前 review fingerprint 不含最终 P1/P2、PostgreSQL 专项和
  文档增量，现已失效，必须复用同一 reviewer 重审。未 commit/push/PR/部署，未运行生产
  census/apply。

## 13. 首次代码审核 fixes（第二轮限定复审已关闭）

- [x] F1：`RaceEvent.save/create/update_or_create` 统一调用年份合同；身份字段
  `QuerySet.update/bulk_update` 拒绝，旧坏行非身份更新保持 Release A 兼容。
- [x] F2：`RaceEvent.save` 与 canonical registry 在同一事务 reserve/sync；rename 旋转 legacy，
  canonical/legacy 冲突整笔回滚；bulk create 逐条走同一 writer。
- [x] F3：`0067` 增加实时 maintenance gate 审计模型；PostgreSQL 使用 advisory
  shared/exclusive transaction lock，SQLite 覆盖确定性 admission；apply/rollback 要求
  exact active gate，repair bypass 仅绑定已验证 manifest/action scope。
- [x] F4：无 receipt 的 orphan ledger 仅在 schema/manifest/action scope 匹配且数据库仍为
  exact pre-state 时清理并重建；篡改、漂移或未知状态 fail closed。
- [x] 新增 RED 后确认缺失模型导入失败；GREEN 聚焦 51/51，通过 Django check、
  migration drift、fresh 0066→0067→latest 和 0067→0066。
- [x] 独立 reviewer 第二轮限定复审以上四项，`VERDICT: APPROVED`。

## 14. 第一次复审 follow-up（第二轮限定复审已关闭）

- [x] P1：移除误加在 `RaceReferenceReceipt` 上、会覆盖不可变保护的第二个 `delete`；
  calendar admission 只放在实际 scoped model。
- [x] P2：`RaceEvent.save(update_fields=...)` 按实际落库字段计算 identity/path 变化；
  未包含的内存 year/slug 不触发校验或 registry 迁移。
- [x] P2：`RaceEventPublicPath` 与 `HistoricalRaceEventTarget` instance delete 均接入 live gate。
- [x] P2：dependency snapshot key 加入 reverse accessor 和 FK field identity，同 model 多 FK
  不再互相覆盖。
- [x] 新增 RED 确认上述三类行为失败；GREEN review/integrity/tooling/year/frontend `115/115`。
- [x] 同一 reviewer 第二轮限定复审关闭 `1 P1 + 3 P2`；本次事实文档写回仍需再次限定复审。

## 15. 第二轮限定复审证据

- 原生命令：`codex review`，read-only，exit `0`；结论 `VERDICT: APPROVED`。
- pre/post fingerprint：
  `88c53c265cd0de5748438648f637e0975e75389ee8b636ab1c3848f68d033eb3`。
- approved parent：`43b81fd3288a1e7b997ffad78d03565327e3d990`。
- approved content：
  `1a31d68e51d8aa4ce28249c4feb2f3fa82517d9277818da063214972fda9646f`。
- approved content 仅标识本次文档写回前的实现快照；本节写入后须复用同一 reviewer 再审
  文档增量。发布授权尚未请求或取得。

## 16. 最终全量扫描 follow-up（待复审）

- [x] P1：`RaceEventPublicPath.event` 在 model 与既有 `0067` 同步改为 `CASCADE`；普通
  RaceEvent 删除原子清理 canonical/legacy，active gate 仍拒绝并保留 event/path。
- [x] P2：orphan ledger 先做 controlled path 和 symlink 校验，再以 `O_NOFOLLOW` regular-file
  descriptor 单次读取；digest 与 JSON 解析复用同一 bytes，移除 `Path.read_bytes()`。
- [x] RED 覆盖 PROTECT 阻止 event 删除、root 外/内 symlink orphan 被跟随；GREEN
  review/integrity/tooling/year/frontend path 聚焦 `116/116`。
- [x] fresh SQLite `0066→0067→0066`、check、migration drift、diff check 通过；无 `0068`。
- [ ] 本次实现与事实文档等待同一 reviewer 再审，不得表述为已通过。

## 17. 真实 PostgreSQL Release A 验收

- [x] 新增 `test_historical_calendar_release_a_postgres.py`，隔离 PostgreSQL 连续两轮
  `5/5`。
- [x] fresh migrate `7.96s`；`0066→0067` `0.346s`；`0067→0066`
  `0.463–0.475s`。
- [x] shared/exclusive advisory lock 以实际 `pg_locks` wait（约 `0.024s`）同步；验证锁后
  active gate 拒绝、gate exit 恢复、无 deadlock/陈旧提交。
- [x] PostgreSQL 验证路径冲突回滚、event/path `CASCADE`、receipt manifest unique 和单
  active gate 条件唯一。
- [x] 临时容器 `umanews-histcal-pg-accept-20260731-a1` 与 tmpfs 已删除，未改变其他容器。
- [ ] 50k 数据集性能、Release B/C 和生产 prepare/apply/rollback 未运行。

## 18. descriptor 与 public cache follow-up（待复审）

- [x] current-year descriptor 显式区分 public year/edition year；slug、query、identity 仅使用
  public year，跨届次记录仍强制 descriptor。
- [x] apply/rollback 通过 `transaction.on_commit` 失效 public cache；失败事务不清缓存。
- [x] existing receipt 幂等重入不注册 cache invalidation。
- [x] descriptor `13/13`、cache `10/10`，主线程合并 Django `224/224`、collector
  `101/101`；check、migration drift、diff check 通过。
- [ ] 旧 fingerprint 不覆盖该增量，必须复用同一 reviewer 复审。

## 19. 最新复审路径安全 P2（实现关闭，待复审）

- [x] `_controlled_path` 在任何 resolve 前对 absolute raw path 逐组件 `lstat`，拒绝父目录或
  leaf symlink；resolve/relative-to 后再复核 resolved components。
- [x] controlled reads 以 root dirfd 为锚逐层 `O_NOFOLLOW` 打开父目录与 leaf，缩小检查到打开
  之间的父组件替换窗口；digest/JSON 复用同一 descriptor bytes。
- [x] manifest、approval、maintenance evidence 的受控 root 内 symlink alias 均新增 RED；
  root 外既有覆盖和 direct canonical regular file 保持 GREEN。
- [x] integrity/tooling/review fixes + descriptor/cache/public path 聚焦 `98/98`；check、
  migration drift、diff check 通过，无 migration 变化。
- [ ] 等待 reviewer 复审本次实现与事实文档增量。

## 20. 最新复审历史写入总门 P1（实现关闭，待复审）

- [x] apply/rollback 写入口集中检查 `HISTORICAL_RACE_BACKFILL_ENABLED`，配置缺省或 false
  均在 artifact/receipt/rollback ledger 处理前 fail closed。
- [x] existing receipt 重入在总门关闭时不运行 verifier 更新；true 时保留 exactly-once 行为。
- [x] rollback 作为业务恢复写入受同一总门保护；prepare/verify 继续为只读入口。
- [x] 新增 3 项真实 RED 后取得 GREEN；integrity/tooling/review-fixes 聚焦 `55/55`，加入
  descriptor 回归后 `68/68`；check、migration drift、diff check 通过。
- [ ] 等待同一 reviewer 对本次 P1、测试及事实文档做限定复审。

## 21. 写总门禁、authority URL 与 detail edition 综合 follow-up（待复审）

- [x] apply/rollback 和 existing receipt 重入均要求
  `HISTORICAL_RACE_BACKFILL_ENABLED=true`；prepare/verify 只读不受写开关影响。
- [x] 跨届次 `authority_url` 严格校验有效 HTTPS、受控 host、无 credentials/fragment，并保留
  合法 query。
- [x] detail `edition_year` 仅字段缺失时回退；显式值须为非 bool `int` 且 `1..9999`。
- [x] 最新主线程 `205/205`、URL + detail `166/166`、gate `68/68`；PG `5/5` 两轮、
  collector `101/101` 保留，check、migration drift、diff check 通过。
- [ ] detail clean RED 未保存：初次失败被陈旧 SHA fixture 遮蔽，不能追溯冒充完成。
- [ ] 旧 fingerprint 不覆盖该增量，必须复用同一 reviewer 复审。

## 22. URL 中央 validator 限定复审与后续 P2

- [x] 同一 reviewer 限定复审 `APPROVED`，确认 `URL central validator P1 CLOSED`；原生命令
  read-only、exit `0`。
- [x] pre/post fingerprint：
  `91fed97e63acacbb28ee8fed717edc049d1812f0dead8465c5a6f139bd110a39`；approved parent：
  `43b81fd3288a1e7b997ffad78d03565327e3d990`；approved content：
  `b3353358647cd7b842a5a16326deee25ecc09485f37f7cd6974ed32b53868d2e`。
- [x] URL `76/76`、主线程 `205/205`、真实 PostgreSQL `5/5` 两轮、collector `101/101`。
- [ ] 本次 evidence-only 文档写回使 approved content 过期，待同一 reviewer evidence 复审。
- [ ] non-blocking P2：apply/rollback 与 maintenance exit 理论锁顺序反转；PG `5/5` 未复现，
  但未运行专项并发 exit 测试，不能标记关闭。
