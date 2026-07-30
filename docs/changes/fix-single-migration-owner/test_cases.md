# 单一迁移执行者修复测试用例

## 1. 测试先行与真实 RED

只有用户明确授权实现后才能创建或修改测试。测试 subagent 首先只写测试并运行；有效 RED 必须
由当前重复入口或缺失的新控制能力直接导致，不能来自 fixture、shell 语法、路径、权限或 Docker
环境错误。

首轮建议命令：

```bash
.venv/bin/python manage.py test stable.test_single_migration_owner -v 2
```

预期真实 RED：

- migration 单一所有者测试发现 `start-web.sh` 与 deploy/rollback 共五类入口；
- `start-web.sh` 禁止 migration/collectstatic 测试失败；
- 共享 release wrapper、健康等待和部署锁尚不存在；
- 真实编排 harness 观察到 `up web` 后的第二次 `exec migrate`；
- migration 失败时的 fail-closed 编排尚未满足。

记录：

```text
RED: UTC 时间 / commit / 命令 / exit / 失败用例 / 目标能力缺口
GREEN: UTC 时间 / commit / 命令 / exit / passed/skipped
```

## 2. 聚焦测试矩阵

### T01 唯一 migration 所有者

- 扫描非文档、非 migration 文件；
- 精确断言 `manage.py migrate --noinput` 只在
  `deploy/docker/run-release-tasks.sh` 出现一次；
- 禁止使用变体空格、`call_command("migrate")` 或 wrapper 藏第二入口。

当前预期：RED。

### T02 唯一 collectstatic 所有者

- `collectstatic --noinput` 只在同一 release-task 脚本出现；
- deploy/rollback/start-web 不直接执行。

当前预期：RED。

### T03 web 入口纯应用启动

- `start-web.sh` 包含 `wait_for_services.py`；
- 可选 `seed_admin` 保持；
- 最终 `exec gunicorn`；
- 不含 migrate/collectstatic/release wrapper。

当前预期：RED。

### T04 release task 固定顺序

用 fake `python` 记录参数并执行容器内脚本：

- wait -> migrate -> collectstatic 顺序准确；
- migrate 返回非零时 collectstatic 不执行；
- collectstatic 返回非零时脚本非零；
- 不执行 Gunicorn、Celery、外部网络命令。

### T05 宿主 wrapper 的 Compose 合同

- 缺 `COMPOSE_FILE` 非零；
- 非 allowlist Compose 文件非零；
- 标准和 lowcost 文件均调用一次
  `run --rm --no-deps web /app/deploy/docker/run-release-tasks.sh`；
- 不调用 `exec web ... migrate`；
- 缺失或错误 deployment lock owner token 时零 Compose call；
- fake Compose 返回非零时原样失败。

### T06 部署锁互斥

- 第一个进程获取锁后，第二个 deploy/rollback/手工 release 入口立即非零；
- 正常退出、INT、TERM 释放；
- 模拟遗留锁时 fail closed，测试不得自动删除；
- 锁元数据不含环境变量或 secret。
- 竞争失败者不安装 trap，退出后赢家锁仍存在；
- 非 owner 不能调用 release 或释放锁，原始 token 不写日志。
- 手工 release 在 web/worker/beat/race_live_worker 任一 running、restarting 或状态未知时零
  Compose `run`；四者全部非运行才允许 one-shot，完成后不启动任何服务。

### T07 web 健康等待成功

fake Compose/Docker 状态序列：

```text
absent -> true starting -> true healthy
```

断言成功、轮询有界、只检查 web、日志脱敏。

### T08 web 健康等待失败

分别覆盖：

- `false none`；
- `true unhealthy`；
- inspect 非零；
- 一直 `true starting` 到 timeout；
- container ID 在重建中变化。

断言非零且最后状态可诊断，不启动下游。

### T09 标准部署真实 shell 编排

在临时目录复制必要脚本，使用 fake Git/Compose/Docker/health helper 运行真实
`deploy/deploy.sh`，断言：

1. preflight 在有状态动作前；
2. build 完成；
3. beat stop -> drain -> worker stop -> running race-live stop -> web stop；
4. release wrapper 恰好一次；
5. web start -> healthy；
6. worker/beat/nginx 最后启动，race-live 只按原始运行态恢复；
7. 全程没有 `exec web migrate`。

### T10 低成本部署真实 shell 编排

与 T09 相同，但精确使用 `docker-compose.prod.lowcost.yml`。

### T11 两条 rollback 真实编排

- 目标 ref 为空或不可解析时零停服、零 release；
- 含 `release_contract_v1` 的目标在 checkout/build 后复用相同 orchestration；
- 不含 contract 的 pre-fix target 在 checkout/停服前非零拒绝；
- 标准/lowcost 分别使用正确 Compose 文件；
- migration 入口仍只有 release wrapper 一次；
- 文档警示 forward migrate 不等于数据库回退。

### T12 pre-contract rollback bridge

- 使用冻结 old image tag，不 checkout old ref；
- 不调用 one-shot release 或旧 rollback；
- 停止/排空服务后只启动一个旧 web；
- web healthy 后才恢复下游；
- schema 被标记不兼容时在 image 切换/启动前停止；
- race_live_worker 只在回滚前为 running 时恢复。

### T13 race_live_worker 状态保持

分别模拟 running、created/stopped、absent：

- running：drain 后 stop，web healthy 后恢复一次；
- running worker 的 container hostname 必须出现在 ping/active/reserved/active-confirm 完整快照；
  缺普通或 race-live 任一 expected node 时 drain 失败且不停 web；
- created/stopped/absent：release 前不启动，release 后仍不启动；
- release/health/downstream 失败时不恢复；
- 状态探测失败 fail closed；
- migration 时普通 worker、race_live_worker 和 web 都已停止。

### T14 各失败点 fail closed

参数化让以下步骤分别失败：

- historical preflight；
- drain；
- stop web；
- release task；
- web start；
- web healthy。

断言失败点后的命令均不执行。特别是 release/healthy 失败时
`up worker beat nginx` 和 race-live 恢复调用数均为 0。

### T15 `--no-deps` 和基础设施边界

- release one-shot、web、worker、beat、nginx 都保留正确 `--no-deps`；
- deploy/rollback 不调用 `compose down`；
- 不创建/删除 db、redis、volume 或 network；
- 现有 historical runner preflight 和 Celery drain 未被绕过。

### T16 shell 与 Compose 静态验证

```bash
sh -n deploy/*.sh deploy/docker/*.sh
./deploy/docker/compose-wrapper.sh -f docker-compose.prod.yml config
./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml config
```

若隔离 worktree 没有 `.env`，Compose config 必须使用经审核的无敏感测试 env/临时空 env；
不能把缺 `.env` 误报为产品失败。

### T17 相邻历史 runner 回归

至少运行现有：

```bash
.venv/bin/python manage.py test \
  stable.test_historical_batch_runner_change \
  stable.test_historical_race_detail_runner_v2_contract -v 2
```

确保普通 deploy 仍使用 preflight、drain 和 `--no-deps`，不 bootstrap 基础设施。

### T18 historical initial-install 语义不冒充 greenfield bootstrap

- 真实 shell harness 证明无既有 web 时，普通 deploy 的 historical preflight 在任何迁移前
  fail closed；
- 文档与 help 不宣称 `HISTORICAL_RUNNER_INITIAL_INSTALL` 可安装全新站点；
- 既有健康 web/db/redis 下的 historical runner initial-install 路径保持原合同。

### T19 Django 与 migration 漂移

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
git diff --check
```

本 change 不应生成任何 `server/stable/migrations/*.py`。

## 3. 本地 Compose 集成测试

静态和 fake harness GREEN 后，在非生产、本地隔离 Compose 环境验证：

1. 起 DB/Redis；
2. release wrapper 执行一次；
3. 再执行一次得到 no-op migration，均成功；
4. 启动 web 并达到 healthy；
5. 验证 migration 日志只来自 one-shot，不来自 web；
6. 构造一个测试专用失败 migration 或 mock 命令，证明 web/worker/beat 不启动；
7. 并发发起两个顶层入口，只有持锁编排能进入；内部 wrapper 直接调用被拒绝。

不得为了测试连接生产数据库或复用生产 `.env`。

## 4. 生产前验证矩阵

生产授权前只读核对：

- 精确 review fingerprint、commit、镜像 revision；
- 旧脚本与新脚本路径/权限；
- DB backup 可恢复性；
- 当前 migration plan；
- lifecycle/race-live/result-review 等开关保持原值；
- Celery active/reserved/queues 和 historical runner 安全；
- 可用磁盘、容器健康、数据库锁。

发布后验证：

- release log 中 migration owner 只有 one-shot container；
- web 日志没有 `Applying ... migrations`；
- web healthy 后才有 worker/beat/race-live 启动时间，race-live 状态与部署前一致；
- Django check、showmigrations、内外 healthz、Celery ping 正常；
- 无 `DuplicateTable`、migration race、502 残留或队列重复消费。
