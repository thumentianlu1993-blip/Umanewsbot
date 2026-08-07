# 历史赛历 Release B 测试用例

## 0. 预声明假设与门槛

- H1：Release B migration 在 50k event / 50k target 的 PostgreSQL fixture 上，正向与反向各
  `< 5s`；超时为 blocker。
- H2：v2 prepare 在 50k event / 500 mismatch / 100 series fixture 上 `< 30s`，查询数不随
  mismatch event 数线性乘以 relation 数；超时或明显 N+1 为 blocker。
- H3：所有失败 fixture 的业务表写入数为 `0`；任一部分写为 blocker。
- H4：真实 PostgreSQL apply/maintenance 并发无 deadlock，等待方取锁后重查 gate 并 fail
  closed；deadlock 或陈旧提交为 blocker。

## 1. Migration RED/GREEN

1. 旧 schema 下，同一 series/public year 的不同 edition event 被拒；新增测试先取得 RED。
2. GREEN 后，同一 series/public year、不同 non-null edition 可共存；相同 series/edition 被拒。
3. `edition_year=NULL` 在 Release B 继续允许，Release C 约束不存在。
4. superseded target 与 active target 可共享 series/year；两个 active target 冲突。
5. `0070→0071→0070` SQLite 往返保持模型状态与约束名一致。
6. 真实 PostgreSQL 连续两轮验证正反 migration、约束、执行时间和 migration leaf。
7. forward preflight 在候选 image 构建后、停服务/DDL 前，由受控 candidate one-shot 执行并绑定
   candidate commit/image、`0070` leaf 与目标 DB identity；不得从旧 web 容器调用。冲突、identity
   漂移或查询异常时 `run_application_release.sh` 零调用，旧 web/worker/beat/race-live 状态不变。
8. 创建 B-only 合法的“同 series/public year、不同 edition”event 或重复 superseded target 后，
   reverse preflight 必须 fail closed；恢复旧约束兼容数据后才允许 `0071→0070`。
9. 生产 `django_migrations` 中出现候选 migration graph 不认识的 `stable.*` applied node 时，
   preflight 必须在机器可读结果中列出该 node、`migration_graph_known=false`、`ok=false`；deploy 与
   rollback 均不得进入 release orchestration 或停服务。

## 2. Series planner RED/GREEN

1. 香港单一错位链：多个 event 的 public/edition year 与 target association 一次生成完整 ledger。
2. 真实 duplicate boundary + 后续 chain：只 tombstone 经审核 duplicate，后续各 event 保留。
3. 两个同日 event 计数相同但 runner/result 核心字段不同：block，不按计数判断等价。
4. 同一自然年两届：保留不同 edition；缺显式消歧 slug 时 block。
5. 英国跨年届次：public year 改为 local year，edition/target year 保留。
6. target 链首尾：边界 target 重挂正确，最新未导入 target 恢复为无 event 的审核状态。
7. scope 外 path 占用、canonical link chain/cycle、重复 survivor、未知 series：block。
8. 无 race_series mismatch：event-level manual/block，不猜系列。
9. 脱敏、固定 SHA 的生产形态 fixture 必须把 81 个 mismatch 恰好归入 14 个互斥 series action；
   覆盖 12 个 duplicate boundary、英国跨年例外及链内非 mismatch event，集合守恒且 event 不重复。
10. superseded target 跨 series、跨 edition、指向 superseded、形成二层 chain 或 cycle：全部 block；
    同 series/edition 的单层 active survivor 才通过。

## 3. Reviewed overlay 与 artifact

1. prepare 为 read-only；SQLite query wrapper 和 PostgreSQL repeatable-read 均拒绝写 SQL。
2. v1 manifest 传给 v2 apply：schema mismatch 拒绝。
3. overlay 缺 event/target/path/dependency policy、SHA 不符或 action scope 漂移：拒绝。
4. artifact root 已存在、symlink、TOCTOU、路径越界或非 regular file：沿用 Release A fail closed。
5. 相同输入两次 fresh prepare 的语义内容和 action scope 稳定。

## 4. FK ledger

1. 五类生产非零 relation 使用 `retain_on_tombstone` 时 count/SHA 完全不变。
2. duplicate 的 runner/result 外键不自动重挂，不触发 unique 冲突或删除。
3. 新增测试模型 relation 或 manifest 漏 relation 时 apply block。
4. `repoint/dedupe_exact` 没有逐行 mapping 时 block；首版不暗中实现删除。
5. scope 内任一 relation 行在 prepare 后漂移，锁后 precondition 拒绝。
6. managed target/path、managed canonical link、immutable reverse dependency 三组互斥且并集完整；
   新建 canonical link 不改变 retain SHA。
7. canonical link 的 source/canonical 两向既有行漂移、并发插入、链、环和重复 active source 均阻断，
   rollback 精确恢复其 before state。

## 5. Apply、verifier、rollback

1. 写总开关关闭、无 live gate、gate identity 不同、actor/approval/action scope 不同：零写入。
2. duplicate boundary + chain + path owner rotation 在一个事务完成；中途故障整批回滚。
3. canonical product link 建立，duplicate draft/series null/tombstone；公开 queryset 只剩 canonical。
4. target association、resolution 与 edition identity 完整守恒。
5. 两个 event 同一 public year 的路径均可解析且 slug 唯一。
6. verifier 捕获 natural-year mismatch、series/edition duplicate、active target duplicate、path owner
   错误、retain SHA 漂移和临时 key 残留。
7. exact apply 重入只验证同一 receipt；manifest 不同不得复用。
8. rollback exact post-state 成功；任一 post-state 漂移拒绝且不部分恢复。
9. reviewed overlay 的带时区 `superseded_at` 与 ORM datetime 必须先规范化为同一 UTC 微秒表示再
   比较；合法 supersession 可通过 post-state verifier 并完成 exact rollback。

## 6. 并发与 PostgreSQL

1. apply 持有全局/series 锁时普通 event/target/path writer 等待，取锁后因 active gate 被拒。
2. maintenance exit 与 apply 同时运行不发生锁顺序反转；只能有一个确定赢家。
3. 两个 apply 使用相同 manifest 时 exactly-once；不同 manifest 互斥且无死锁。
4. path 轮转过程中约束立即生效，事务外不可观察临时 owner。
5. event 自身 `(year, slug)` 的轮转使用 manifest 固定临时 key，任一中间写不触发即时唯一冲突，
   事务完成后临时 key 为零。
6. `(race_series, edition_year)` 两行或多行链式交换先用 manifest-bound 临时 identity 将 scope 内
   event 解除 series/edition 唯一键，再写最终审核状态；真实 PostgreSQL 上 apply/verifier/
   rollback 全链路通过，事务外不可观察临时 identity。

## 7. 回归

- Release A 年份 helper、public path、历史重点、分页、collector 缺号测试保持 GREEN。
- race calendar/detail/sitemap、canonical product link、historical materialize/detail/import、P0 source、
  race-live、result recovery 聚焦回归。
- `DB_ENGINE=sqlite python3 manage.py check`。
- `python3 manage.py makemigrations --check --dry-run`。
- migration graph/owner、两份 Compose config、workflow contract 与 `git diff --check`。
- 完整 `stable` 运行并与冻结主线失败集合比较；不得把既有失败表述为全绿。

## 8. 发布验收（后续独立授权）

- Release B image 只含 `0071` 与兼容代码，无 Release C leaf。
- migration plan 为零、Django check 正常、web/worker/beat 镜像一致、healthz 200。
- 生产仍为 `9867 events / 81 mismatch / 0 receipt / 0 active gate`，flags false。
- 不运行 v2 census/apply；后续只读 v2 census 与生产 apply 分别授权。
