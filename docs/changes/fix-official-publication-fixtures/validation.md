# 正式发布与暂定赛果恢复测试收口

## 根因和最小修改

两个命令测试类创建固定 2026-08-01 到期的权限或策略。9 月运行时，正式授权被
`valid-until` 检查拒绝，范围提升则因 CAS 检查包含有效期而拒绝；原成功和幂等断言
尚未到达。夹具现在通过 `enterContext` 固定对应 7 月时钟并自动恢复，保留真实
到期判断。新增回归把时钟推进到到期边界，分别验证 dry-run 和 apply 都拒绝，
不产生授权、策略变更或操作日志。

暂定赛果恢复夹具创建两条已发布 revision，却只给暂定版本创建审计。现在为原有
正式版本补齐匹配时间的审计；新增用例核对两个审计并调用数据库约束检查，不关闭
约束。原有恢复、CAS 漂移、显式审计和策略恢复断言保留。

`restore_last_provisional_result` 已分别锁定 revision、observation 和 source，
但 revision 查询还重复以 nullable `primary_observation` 外连接加锁，导致
PostgreSQL 拒绝执行。应用仅删除这一处多余的 `select_related`；后续两类记录的
显式加锁、控制权/claim/CAS/恢复目标验证和原子事务全部保留。

范围为一个应用查询、一份测试及本验证记录。没有迁移或新的配置、权限、功能开关
与生产数据动作；部署代码 rollback 的禁用策略保持原状。

## 实际验证

- 基线为 `f62a6edadbe6173c6a5b3ec58ad957916588a15f`，独立工作树
  `codex/fix-official-publication-fixtures`，不依赖尚未合并的 PR #192。
- 修复前整个相关模块在离线 SQLite 下真实 RED：28 项、0.285 秒，3 项因到期
  报错，25 项通过。输入与文件摘要见本机
  `runtime/fix-official-publication-fixtures/regression-evidence.json`。
- 已保存的 Linux/PG16 `22ab56b8` CI 同时证明该模块的缺失审计和 nullable
  `FOR UPDATE` 错误；其中部分记录属于同一测试，不能相加为独立修复数。
  原始摘录在 `runtime/closeout-m2-test-ops/next-publication-fixture-diagnostics.json`。
- 最小修复及 3 项新回归后，同一完整模块为 31 项、0.326 秒全部通过，无跳过；
  Django check 通过。测试禁用外部网络和生产配置。
- SQLite 不验证 PostgreSQL 行锁及其延迟触发器。真实 PG 完整恢复路径与审计
  约束须由固定新候选 CI 验证；不据本机结果预报全量修复数量或宣称 PG 通过。
- 静态解析和 `git diff --check` 通过；工作流合同检查仍命中主线既有 5 处旧
  文档引用，4 项合同测试有 1 项因此报错。该独立问题已由 PR #186 修复；本分支
  保留原检查器及失败，不通过放宽规则处理。
- 验证与审核证据保存在 `runtime/fix-official-publication-fixtures/`。交付沿用根
  [AGENTS.md](../../../AGENTS.md)，本地验证不代表合并或生产操作授权。
