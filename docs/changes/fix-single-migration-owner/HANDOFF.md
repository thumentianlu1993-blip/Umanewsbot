# `fix-single-migration-owner` 实现交接

## 0. 给接手会话的第一句话

你要实现的是 Umanews 部署入口的“单一迁移执行者”修复，不是赛事生命周期业务功能。请只在最新、
干净、隔离的 `codex/` worktree 中工作，严格测试先行；不要使用 旧规格流程，不要连接生产，不要
commit、push、创建 PR 或部署，除非用户针对当前 fingerprint 另行授权。

## 1. 当前基线

- 仓库：`/Users/mentianlu/Code/umanews`
- 规划 worktree：
  `/Users/mentianlu/Code/umanews/.worktrees/fix-single-migration-owner`
- 规划分支：`codex/fix-single-migration-owner`
- 规划 parent：`origin/main@7385f59ab87bcce5193f3313ecca6809b165ad89`
- 工作流：Codex 原生，禁止 旧规格流程 skills/CLI/change
- 当前成果：spec/design/test/tasks/rollout/handoff，仅文档
- 方案 reviewer：`/root/single_migration_plan_review`，三轮限定复审后
  `VERDICT: APPROVED`；首轮 4 项 P1、第二轮 2 项直接 P1 均已关闭，无开放 P0/P1

开始前必须重新：

```bash
git fetch origin main
git status --short --branch
git rev-parse HEAD origin/main
```

如果 `origin/main` 已前进，不要直接在过期设计基线上实现。先从最新 main 建新隔离 worktree，
重读根 `AGENTS.md`、`docs/codex_workflow.md`、session bootstrap 要求的状态文档，重新核对下列
入口是否变化，再把本目录文档迁移/修订到新基线。

## 2. 已确认根因

当前 main 中：

- `deploy/docker/start-web.sh` 第 6 行执行 `migrate`，第 7 行执行 `collectstatic`；
- `deploy/deploy.sh` 第 24 行先 `up web`，第 25/26 行再次 migrate/collectstatic；
- `deploy/deploy_lowcost.sh` 同样重复；
- `deploy/rollback.sh`、`deploy/rollback_lowcost.sh` 也在 `up web` 后再次 migrate。

`compose up -d web` 不等待 `start-web.sh` 完成，所以随后 `exec web migrate` 可能与容器主进程
并发执行同一 migration。真实生产预检曾因此把 additive migration 判断为 `DuplicateTable`
风险并安全停止。

## 3. 锁定的实现方向

采用“显式一次性 release task”为唯一 owner：

```text
deploy/rollback entry
  -> host deployment lock
  -> existing preflight/build/drain
  -> freeze race_live_worker state
  -> stop worker + running race_live_worker + web
  -> deploy/run_release_tasks.sh
       -> compose run --rm --no-deps web
          /app/deploy/docker/run-release-tasks.sh
             -> wait_for_services
             -> migrate --noinput
             -> collectstatic --noinput
  -> start web
  -> bounded wait for web healthy
  -> start worker/beat/nginx
  -> restore race_live_worker only if it was running
```

`start-web.sh` 删除 migrate/collectstatic，只保留依赖等待、可选 seed_admin 和 Gunicorn。

不要采用“仅删 deploy 中 migrate、继续由 web 自动迁移”的最小改法。它在 web restart/未来
replica 下仍没有独立 release owner，且难以审计失败边界。

## 4. 预期文件边界

允许新增/修改：

- `server/stable/test_single_migration_owner.py`（先写）
- `deploy/docker/run-release-tasks.sh`（新增，唯一 migration 命令）
- `deploy/run_release_tasks.sh`（新增宿主 wrapper）
- `deploy/wait_for_compose_service_healthy.sh`（新增）
- `deploy/deployment_lock.sh`（新增）
- `deploy/run_application_release.sh`（新增共享编排）
- `deploy/wait_for_celery_drain.sh`（扩展 expected worker node 完整性核对）
- `deploy/manual_release.sh`（新增受锁保护的手工入口）
- `deploy/rollback_pre_single_owner.sh`（新增首次发布兼容桥）
- `deploy/release_contract_v1`（新增目标 ref 能力 marker）
- `deploy/docker/start-web.sh`
- `deploy/deploy.sh`
- `deploy/deploy_lowcost.sh`
- `deploy/rollback.sh`
- `deploy/rollback_lowcost.sh`
- `docs/deploy_production.md`
- `docs/rollback_guide.md`
- `docs/deploy_runbook.md`
- `docs/current_state.md`
- `docs/project_status.md`
- `docs/decisions.md`（若实现改变已锁定决策）
- 本 change 目录文档

默认不应修改：

- `server/stable/models.py`
- `server/stable/tasks.py`
- 任何 `server/stable/migrations/*.py`
- Celery/Beat 配置
- 两份 Compose service 定义（除非测试证明一次性 wrapper 无法复用现有 service；这种偏离必须
  先停下并更新设计、重新方案审核）
- lifecycle/race-live/result-review 代码和开关

## 5. 测试先行执行顺序

### 5.1 测试 subagent

由测试 subagent 只负责 `server/stable/test_single_migration_owner.py`。明确告诉它：

- 不独占仓库，不得回退他人修改；
- 不实现产品脚本；
- 不 commit/push/PR/部署/生产访问；
- 使用 fake executable/temp directory 运行真实 shell 路径；
- RED 必须来自重复 owner/缺失 helper。

至少实现 `test_cases.md` 的 T01–T19。先运行：

```bash
.venv/bin/python manage.py test stable.test_single_migration_owner -v 2
```

保存真实 RED 后才委派 operations 实现。

### 5.2 实现 subagent

operations subagent 只拥有 `deploy/` 脚本和部署文档，不修改测试。要求：

- POSIX `sh`，`set -eu`；
- 固定 Compose allowlist；
- 不用 `eval`；
- 不输出 secret；
- migration 命令只出现一次；
- 所有失败非零；
- 锁和健康等待有界且 fail closed；
- release wrapper 必须验证当前 lock owner token；竞争失败者不能释放赢家锁；
- manual release 仅在 web/worker/beat/race-live 全部可验证为非运行时允许，否则零
  Compose `run`，且成功后也不启动服务；
- migration 前停止 race_live_worker，之后只恢复原始 running 状态；
- 通用 rollback 在停服前拒绝 pre-contract target；首次发布回退只走冻结 image 兼容桥；
- 不绕过 historical preflight、Celery drain、`--no-deps`。

主线程负责整合和处理测试/实现边界冲突。

## 6. 主线程验证

按顺序运行并记录：

```bash
.venv/bin/python manage.py test stable.test_single_migration_owner -v 2
.venv/bin/python manage.py test \
  stable.test_historical_batch_runner_change \
  stable.test_historical_race_detail_runner_v2_contract -v 2
sh -n deploy/*.sh deploy/docker/*.sh
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
git diff --check
```

再运行：

```bash
rg -n "manage\\.py migrate --noinput|manage\\.py collectstatic --noinput" \
  . --glob '!docs/**' --glob '!旧规格流程/**' --glob '!.git/**'
```

预期只命中 `deploy/docker/run-release-tasks.sh` 各一次。

Compose config 需要 `.env` 时，只能使用隔离的非敏感测试 env；不得读取或复制生产 `.env`。
然后在临时本地 Compose 验证正常、重放、失败三条路径。若 Docker 不可用，必须明确标为未验证，
不能猜测通过。

## 7. 独立代码 review

验证 GREEN 后：

1. 冻结 `git diff --binary` SHA-256、变更文件列表、HEAD/parent；
2. 启动未参与实现的独立 reviewer；
3. reviewer 只读检查全部新增/修改文件，并重点攻击：
   - 两个部署是否还能并发；
   - migration 是否还有隐藏第二入口；
   - release task 失败是否会启动服务；
   - web healthy 是否是硬门禁；
   - rollback 是否误称会反向迁移或支持任意 pre-fix ref；
   - race_live_worker 是否跨 migration 运行或被意外启用；
   - 直接 manual release 是否绕过锁、失败竞争者是否能释放赢家锁；
   - historical runner initial-install 是否被误称为 greenfield bootstrap；
   - fake harness 是否真的跑了脚本；
4. 有 finding 时先补 RED、修复，并复用同一 reviewer 会话复审；

## 8. 生产与授权边界

没有用户针对当前版本的明确授权，禁止：

- commit、push、PR、合并；
- 读取生产凭据；
- 创建生产备份；
- 修改生产 Git/镜像/容器；
- 执行 migrate/collectstatic；
- 停止或启动服务；
- 写任何业务数据。

即使代码 review 通过，也只说明候选可进入发布审批。发布时必须重新核对生产 HEAD、Compose
版本、migration plan、备份、队列、锁、磁盘、health 和所有业务开关。

## 9. 完成定义

实现完成但未发布时，应交付：

- 真实 RED/GREEN；
- 所有验证命令与计数；
- 唯一 migration owner 的 `rg` 证据；
- 本地 Compose 证据或明确未验证项；
- 独立 reviewer session、结论和精确 fingerprint；
- 文件清单和风险；
- 当前没有生产动作的声明；
- 下一步仅为用户选择 commit/push/Draft PR 或继续修复。

详细规范以同目录 `spec.md`、`design.md`、`test_cases.md`、`tasks.md`、`rollout.md` 为准。
