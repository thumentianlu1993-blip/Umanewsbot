# TRA profile/career production apply 独立审查 handoff

日期：2026-08-30（Asia/Shanghai）
状态：待非实现者只读审查；本文件不是 release、部署或 production apply 授权
当前副作用：0 TRA 请求、0 生产数据库写入、0 生产服务/配置变化

## 1. 审查结论必须回答的问题

1. 是否存在能绕过 rolling plan/region ordinal、唯一 active claim、completed receipt 或 failed exact resume 的
   canonical profile/career 写入口？
2. 业务行、before/after receipt、OperationLog、batch completed 与 late task-log failure 是否确实同事务？
3. completed replay 是否在任何文件 checkpoint 或返回成功前重验 live after-state，并保持零业务写？
4. reverse 是否默认关闭、完整绑定 receipt/batch/state SHA、拒绝 after-state 漂移，并在删除 created row 可能影响
   未捕获关联时失败关闭？模型/admin 是否阻止 receipt 原地修改或删除？
5. maintenance proof 是否真正绑定 artifact/package/candidate/release、apply plan/source batch/ordinal、revision/image、
   DB/migration 和 deployment lock，且能阻断 active import/completion/apply/赛事 claim、同步开关、busy/partial
   Celery 与相关 Redis 队列？
6. inner wrapper 是否只消费外层已有原 token，永不 acquire/release、stop/start 或消费 `race_live`？输入路径、SHA、
   shell 环境值和 candidate image identity 是否 fail-closed？
7. production apply 是否严格 database-only，没有自动页面发布、QQ、邮件、赛事写入或网络副作用？

任一问题无法由代码与测试直接证明，应给出 finding，不得以运行手册意图替代实现证据。

## 2. 承重实现文件

- `server/stable/models.py`、`server/stable/migrations/0080_horse_profile_production_apply_ledger.py`：apply batch、不可变
  apply/reverse receipt 与数据库约束；
- `server/stable/services/p0_horse_production_ledger.py`：claim/ordinal/resume/replay、exact snapshot/receipt、verify/reverse；
- `server/stable/services/p0_horse_production_preflight.py`：5 分钟 proof、DB/settings/Celery/Redis 即时复核；
- `runtime/research/capture_p0_horse_production_host_preflight.py`：deployment lock、candidate image、web/worker health 与
  Beat/race worker 关闭态证据；
- `deploy/run_p0_horse_production_apply_locked.sh`：只消费外层锁的 lowcost inner runner；
- `server/stable/services/p0_horse_production_apply.py`：低层 canonical 写入与 receipt 同事务；
- `server/stable/services/p0_horse_completion_commit.py`：rolling dry-run/commit/replay/checkpoint 与 database-only policy；
- `server/stable/management/commands/p0_horse_completion_batch.py`：proof-before-claim、claim、失败终态与 resume；
- `server/stable/management/commands/apply_reviewed_p0_horse_completion.py`：生产门禁开启时拒绝 direct commit；
- `server/stable/management/commands/manage_p0_horse_production_receipt.py`：exact verify 与默认关闭 reverse；
- `server/stable/admin.py`、`server/app/settings.py`：只读观察面与默认门禁。

## 3. 承重测试

- `server/stable/test_p0_horse_production_ledger.py`：13 项，覆盖 ordinal/resume/replay、receipt/reverse、状态/身份 SHA
  漂移、uncaptured relation、不可变模型与管理命令；
- `server/stable/test_p0_horse_production_ledger_postgres.py`：真实 PostgreSQL 同 plan/region/ordinal 并发唯一 claim；
- `server/stable/test_p0_horse_production_apply.py`：late task-log error 下业务行与 receipt 同事务 rollback；
- `server/stable/test_p0_horse_production_apply_postgres.py`：serializable/advisory/table lock、非协作 writer、timeout、
  并发身份与整批 rollback；
- `server/stable/test_p0_horse_production_preflight.py`：13 项，覆盖全部 writer counts、10 flags、race-live flags、
  queue/Celery、服务拓扑、stale/binding/input/lock drift；
- `runtime/research/test_capture_p0_horse_production_host_preflight.py` 与
  `runtime/research/test_run_p0_horse_production_apply_locked.py`：host/inner wrapper 9 项。

当前已执行：

```text
Django 受影响组合                    288/288
host evidence + locked wrapper         9/9
isolated PostgreSQL 16                  9/9
makemigrations --check --dry-run        PASS
manage.py check                         PASS
py_compile / sh -n / git diff --check   PASS
```

PostgreSQL 临时容器由本任务创建、`--rm` 删除；没有复用或修改其他任务的 DB 容器。

## 4. 特别检查的失败场景

- 已 completed 但 receipt 缺失必须视为损坏，不得伪装成 failed resume；
- before/after 内嵌 `state_sha256` 必须在 receipt 创建事务内重算；
- apply 成功但 task log 之后抛错，receipt、OperationLog、completion run 与业务行全部回滚，claim 由调用方标 failed；
- completed receipt after-state 漂移，claim replay、rolling replay、verify 与 reverse 均失败；
- created profile/term 在 apply 后新增 external identity、name variant、article/race/follow/participant 等未捕获关联，
  reverse 不得 cascade 删除或 SET_NULL；
- active claim 即使 lease/业务上下文看似过期仍阻断，不允许按时间猜终态；
- proof 生成后 race-live 长度、Celery worker 集合、DB count 或 settings 任一变化都失败；`race_live>0` 本身允许，
  但绝不消费；
- web/worker 缺失、多实例、错误 image、web unhealthy，或 Beat/race worker 仍运行时，host evidence 不得生成；
- shell 环境值不得经 `eval` 二次解析。

## 5. 明确不在本轮“代码完成”结论中的事项

- 没有独立 reviewer verdict；
- 没有最终 commit、image、migration leaf 或 G2 artifact SHA；
- 没有 commit/push/PR/merge/deploy；
- 没有生产 custom-format backup、fresh maintenance proof、dry-run、canonical apply、receipt verifier 或页面抽检；
- 没有赛事阶段重开或容量通过证据；英国/美国 TRA 样本继续暂停；
- reverse 门禁保持默认 false，未在生产执行；
- 39 条 winner seed extension 仍缺非实现者 exact-SHA decision，本 handoff 不审核或批准它们。

独立审查必须基于最终 diff 或最终 commit 重新运行承重测试；本 handoff 的通过计数不能迁移为未来 release 证据。
