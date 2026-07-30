# 单一迁移执行者修复规格

## 1. 状态与授权边界

- 任务 slug：`fix-single-migration-owner`
- 设计基线：`origin/main@7385f59ab87bcce5193f3313ecca6809b165ad89`
- 当前基线：`origin/main@6d073dc07cb29201bbc922255923820c872a0467`（2026-07-30 原地 re-baseline，
  分三跳：`7385f59` -> `7cd144ab`（main 增量 65 文件，含 race-calendar 日期窗口、race-news
  质量、harden-celery-p0-admission 等）-> `be1c89bf`（PR #47 fix-p0-queue-snapshot-output）
  -> `6d073dc0`（PR #48，纯文档增量，无代码变化））
- 隔离分支：`codex/fix-single-migration-owner`
- 当前阶段：实现已完成（含四轮代码审核 findings 修复）并迁移至新基线，聚焦合同测试 97/97
- 当前授权：实现与测试已完成；等待针对复审后新冻结指纹的发布授权
- 方案审核：同一 reviewer 三轮，最终 `APPROVED`；开放 P0/P1 为 0
- 代码审核：第 1 轮 REVISE（7 项 findings 已修复关闭）、第 2 轮 APPROVED、
  第 3 轮 Codex 原生 REVISE（P1-1/P1-2/P2-3/P2-4/P2-5/P3-6/P3-7 已修复）、
  第 4 轮复审 REVISE（P1 重试语义/P2 helper 扩 9 路径与 OID 格式/P3 文档残留已修复）
- 下一门禁：同一 reviewer 在新基线上做第 5 轮复审，通过后冻结新指纹并等待用户发布授权

本 change 禁止使用 OpenSpec skills、OpenSpec CLI 或创建 OpenSpec change。发布前仍不授权
commit、push、PR、部署、迁移、生产服务器访问、数据库写入或服务重启。

## 2. 当前问题

当前 web 容器启动入口和部署/回滚脚本都执行数据库迁移：

| 入口 | 当前行为 |
|---|---|
| `deploy/docker/start-web.sh` | web 启动时执行 `migrate` 和 `collectstatic` |
| `deploy/deploy.sh` | 启动 web 后再次执行 `migrate` 和 `collectstatic` |
| `deploy/deploy_lowcost.sh` | 启动 web 后再次执行 `migrate` 和 `collectstatic` |
| `deploy/rollback.sh` | 启动 web 后再次执行 `migrate` |
| `deploy/rollback_lowcost.sh` | 启动 web 后再次执行 `migrate` |

`docker compose up -d web` 会立即启动 `start-web.sh`。随后部署脚本又通过 `exec web` 调用
`migrate`，因此两个进程可能并发读取同一迁移计划并执行同一 DDL。数据库迁移的幂等预期只适用于
一个执行序列的重复调用，不能保证两个并发进程安全；additive migration 也可能因竞争创建同一表、
索引或约束而出现 `DuplicateTable` 等错误。

问题同时存在于标准、低成本部署和回滚路径，不是赛事生命周期代码本身的问题。赛事生命周期
B0.1 曾因此在生产预检中 fail closed；后续其他版本虽成功应用过迁移，也不能证明当前入口安全。

## 3. 目标

1. 数据库迁移只有一个代码所有者和一个受控执行进程。
2. 标准部署、低成本部署、标准回滚和低成本回滚复用同一 release-task 入口。
3. web 常驻入口不执行迁移或静态文件收集。
4. release task 失败时立即停止，不启动新 web、worker、beat 或 nginx。
5. web 未达到 `healthy` 前，不启动 worker、beat 或 nginx。
6. 同一主机上的部署、回滚和手工 release 会话不能并发进入 release task。
7. 保留现有 historical runner preflight、Celery 排空、`--no-deps` 和关闭态开关语义。
8. 既有生产环境的普通部署、回滚和手工恢复都有明确、可审计的命令顺序。
9. 不新增 Django migration，不改变业务模型、Celery 调度或赛事/新闻数据。

## 4. 非目标

- 不修改赛事生命周期、赛果同步、新闻门禁或来源代码。
- 不启用 lifecycle、race-live、定时赛果审核或任何外部数据源。
- 不设计通用蓝绿/零停机部署；本 change 接受当前部署方式已有的短暂停机。
- 不自动反向迁移数据库；数据库回滚仍必须按迁移兼容性和备份策略人工决定。
- 不自动清理无法确认来源的部署锁。
- 不引入 Kubernetes、CI/CD 平台或新的数据库 migration framework。
- 不顺带处理 race-live 或新闻正文积压。
- 不修复全新站点的 greenfield bootstrap。当前
  `HISTORICAL_RUNNER_INITIAL_INSTALL=true` 是 historical runner 首次纳管预检，不是无 web
  环境的站点初装入口。

## 5. 规范要求

### 5.1 单一所有者

数据库迁移的唯一代码入口必须是新增的容器内 release-task 脚本。仓库非文档文件中：

- `python manage.py migrate --noinput` 只能出现在该脚本；
- `start-web.sh`、四条 deploy/rollback 脚本不得直接包含迁移命令；
- 四条 deploy/rollback 脚本只能调用共享的宿主 release-task wrapper；
- wrapper 必须用一次性容器执行，不能对正在启动的 web 容器执行 `exec`。
- wrapper 是受保护的内部入口；没有当前 deployment lock owner token 时必须拒绝执行。

已批准的 collectstatic 例外（re-baseline 时用户批准）：`deploy/deploy_race_live_p0_closed.sh`
（race-live P0 closed-admission 一次性脚本）是除 `deploy/docker/run-release-tasks.sh` 外
唯一允许出现 `collectstatic --noinput` 的文件。该例外成立前提：此脚本不含任何 migrate
命令、`verify_migration_plan_zero` 恰好执行两次、collectstatic 在 `up web` 之前以单进程
执行；它是显式登记的例外而非隐蔽的第二 collectstatic 所有者，T01/T02 合同断言已按该
批准同步修订。

### 5.2 release task 顺序

一次 release task 必须在同一一次性容器内按固定顺序执行：

```text
wait_for_services
-> migrate --noinput
-> collectstatic --noinput
-> exit 0
```

任何一步非零退出时后续步骤不得执行，调用部署/回滚脚本必须非零退出。

### 5.3 服务顺序

部署和回滚必须遵循：

```text
旧环境只读预检
-> 停 beat
-> 等全部 Celery worker 排空
-> 记录 race_live_worker 原始运行态
-> 停普通 worker 和正在运行的 race_live_worker
-> 停 web
-> 单次 release task
-> 启动 web
-> 有界等待 web healthy
-> 启动 worker/beat/nginx
-> 仅在原先运行时恢复 race_live_worker
-> 状态核验
```

迁移期间旧 web 不得继续提供与新 schema 可能不兼容的业务写入。release task 或 web 健康检查
失败时，worker/beat/nginx/race_live_worker 的启动命令不得执行。原先 absent、created 或
stopped 的 race_live_worker 不得被部署顺带启用。

### 5.4 并发部署

deploy、rollback 和手工 release 必须共享同一个主机级排他锁：

- 获取锁失败即 fail closed；
- 锁覆盖 preflight、构建、停服、release task、健康等待和服务恢复；
- 正常退出和可捕获信号时释放；
- 获取成功后生成高熵 owner token；只有精确 token 匹配者才能调用 release task 或释放锁；
- 竞争失败者不得安装 release trap，也不得删除赢家持有的锁；
- 锁中保存 token hash、PID、动作和开始时间；原始 token 不写日志；
- 遗留锁不得按时间自动删除，必须先确认没有部署/回滚进程再人工清理。

### 5.5 健康等待

共享健康等待脚本必须：

- 通过 Compose 获取目标 service 的当前 container ID；
- 通过 Docker inspect 读取 `running/health`；
- 只有精确 `true healthy` 才返回 0；
- absent、restarting、unhealthy、inspect error 均继续有限重试或立即失败；
- 默认超时覆盖现有 web healthcheck 的 `start_period + retries`，建议 300 秒；
- 超时非零退出，输出非敏感的 service、container ID 前缀和最后状态；
- 不依赖公网 DNS、Nginx 或服务器本地时区。

### 5.6 既有环境的手工恢复

移除 web 自动迁移后，既有环境的 `docker compose up web` 不再隐式准备 schema。手工恢复必须
使用能自行获取同一锁的顶层命令。该命令只有在 web、worker、beat、race_live_worker 全部
非运行且状态可验证时，才允许在锁内调用受保护 release wrapper；任一应用服务运行时零
Compose `run`。手工 release 完成后服务保持停止，恢复服务必须另走受审 deploy/rollback 编排。

全新站点 bootstrap 不在本 change 范围。现有 `historical_runner_preflight.sh
--initial-install` 在分支判断前要求健康 web/db/redis，它仅表示 historical runner 首次纳管，
不能写成 greenfield 安装能力。禁止用“临时把 migrate 加回 start-web”作为恢复方式。

### 5.7 回滚

- 回滚脚本复用同一 release-task wrapper，不拥有第二份迁移命令。
- 通用 rollback 只接受含 `release_contract_v1` marker 和必需 helper 的目标 ref；不满足时必须
  在停服前拒绝。
- 本 change 首次发布回退到 pre-contract 版本时使用独立兼容桥：保留新控制面 checkout，在
  同一锁内恢复部署前冻结的旧 image，不运行新 one-shot，也不执行旧 rollback 脚本；旧 image
  的单个 web 主进程是唯一 migration owner。是否先恢复数据库由 schema 兼容性决定。
- 代码回退不等于数据库回退；若目标代码与当前 schema 向后兼容，可在现有 schema 上启动。
- 若 migration 不兼容或需要反向数据变化，必须停在 release 前，由人工选择显式反向 migration
  或恢复已校验备份。
- release task 失败后不得自动猜测安全并启动旧/新服务。

## 6. 验收标准

1. 当前重复入口合同测试先真实 RED，原因是五个脚本中存在多份迁移命令。
2. 修复后仓库非文档范围只有一个 `migrate --noinput` 所有者。
3. 标准/低成本 deploy 和 post-contract rollback 的真实 shell harness 均证明 release task 只
   调用一次；pre-contract target 在通用 rollback 中零停服拒绝，兼容桥单独验证。
4. migration、collectstatic 或 web healthy 失败时，下游服务零启动。
5. deploy/rollback/直接手工 release 任意两个并发入口只有一个获得部署锁，失败者不能释放赢家锁。
6. `start-web.sh` 仍先等待依赖，再启动 Gunicorn，但不做 release task。
7. 两份 Compose config 可解析，shell syntax、Django check、迁移漂移和相关回归通过。
8. 文档给出备份、停机、失败恢复、既有环境手工恢复和两类回滚的准确步骤，不虚构
   greenfield bootstrap。
