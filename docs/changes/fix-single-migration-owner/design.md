# 单一迁移执行者修复设计

## 1. 当前真实调用链

### 1.1 普通部署

```text
deploy.sh
-> deploy/deploy.sh
-> historical_runner_preflight
-> build web
-> stop beat
-> wait_for_celery_drain
-> stop worker
-> compose up web
   -> start-web.sh
      -> wait_for_services
      -> migrate                 # 执行者 A
      -> collectstatic           # 执行者 A
      -> gunicorn
-> compose exec web migrate      # 执行者 B，可能与 A 并发
-> compose exec web collectstatic
-> start worker/beat/nginx
```

低成本部署同构，仅 Compose 文件不同。两个 rollback 脚本也在 `up web` 后再次 `exec migrate`。

### 1.2 为什么会影响主流程

这不是单纯多跑一次无害命令。`up -d web` 返回只代表容器已创建，不代表
`start-web.sh` 的 migration 已完成；下一条 `exec web migrate` 可以与容器主进程并发。两个
MigrationExecutor 可能同时判断某 migration 未应用，并竞争执行同一 DDL。失败后：

- web 可能无法进入 Gunicorn，Nginx 出现 502；
- deploy 脚本可能在中间状态退出，beat/worker 保持停止；
- 某些 migration 已完成、另一些未完成，形成部分升级；
- 操作者容易把一次后续重试成功误认为原流程安全；
- 所有带 migration 的后续赛事、新闻或治理 change 都受影响。

## 2. 方案比较

### 2.1 方案 A：保留 web 启动时迁移，只删除 deploy/rollback 的显式命令

优点是改动最少，手工 `compose up web` 仍可自动迁移。缺点是迁移仍绑定常驻进程：

- web 重启会重复尝试迁移；
- 未来扩容多个 web replica 时再次出现多个 owner；
- 部署脚本难以把“迁移完成”和“应用 healthy”分开审计；
- release task 失败混在 web restart policy 中，失败原因和恢复边界不清楚。

不采用。

### 2.2 方案 B：部署脚本各自执行 migrate，移除 web 自动迁移

可消除当前竞争，但四个脚本仍各自拥有 release 逻辑，后续容易漂移；既有环境手工恢复也没有
统一入口。不采用。

### 2.3 方案 C：共享一次性 release task，web 只运行应用

新增唯一容器内 release-task 脚本和一个宿主 wrapper。四条 deploy/rollback 路径都只调用
wrapper；`start-web.sh` 不再迁移。release task 用 Compose `run --rm --no-deps web` 运行，
复用同一候选镜像、env、network、数据库连接和 static volume。

这是推荐方案。它把 schema/static 准备与应用启动分开，能被测试、审计和失败隔离，也不会因
web restart 或未来 replica 扩容再次产生并发 migration。

## 3. 文件级设计

### 3.1 新增 `deploy/docker/run-release-tasks.sh`

唯一允许出现迁移命令的非文档文件：

```sh
#!/bin/sh
set -eu

cd /app/server
python /app/deploy/docker/wait_for_services.py
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

不创建管理员、不启动 Gunicorn、不连接外部 API、不启动 Celery。`set -eu` 保证 migrate 失败
后 collectstatic 不运行，collectstatic 失败时整体非零。

### 3.2 新增 `deploy/run_release_tasks.sh`

宿主唯一 wrapper：

- 必须由环境变量提供精确 `COMPOSE_FILE`；
- 必须提供当前 deployment lock 的高熵 owner token，并与锁内 token hash/owner metadata 核对；
- 只接受仓库内两份生产 Compose 文件；
- 调用
  `compose run --rm --no-deps web /app/deploy/docker/run-release-tasks.sh`；
- 不允许调用 `exec web`；
- 输出开始/完成阶段，不打印 `.env`、数据库 URL 或凭据。

Compose `run` 覆盖 web service 的 `command`，因此不会进入 `start-web.sh`；`--no-deps`
避免重建数据库/Redis；web service 的 volumes 使 `collectstatic` 写入既有 `static_data`。

### 3.3 修改 `deploy/docker/start-web.sh`

删除 `migrate` 和 `collectstatic`。保留：

```text
wait_for_services
-> 可选 seed_admin
-> exec gunicorn
```

`seed_admin` 不是 schema owner，本 change 不改变其既有语义。未来是否移出常驻入口属于独立
hardening change。

### 3.4 新增 `deploy/wait_for_compose_service_healthy.sh`

接口：

```text
COMPOSE_FILE=<allowlisted path>
SERVICE_NAME=web
SERVICE_HEALTH_TIMEOUT_SECONDS=300
./deploy/wait_for_compose_service_healthy.sh
```

循环读取：

1. `compose ps -q "$SERVICE_NAME"` 得到当前 container ID；
2. `docker inspect` 得到 `running health-status`；
3. `true healthy` 返回成功；
4. `false *` 或显式 `unhealthy` 立即失败；
5. absent、starting、restarting 在 deadline 前每 2 秒重试；
6. 超时失败。

脚本只支持 `web`，避免被当作任意 service 执行器。container ID 输出最多前 12 位。

### 3.5 新增 `deploy/deployment_lock.sh`

提供 `acquire`/`verify`/`release`，由 deploy、rollback 和手工 release 顶层入口在最外层调用。
默认锁目录建议：
`/tmp/umanews-deployment.lock`。锁元数据只包含：

- 当前 PID；
- `deploy|rollback|manual-release|pre-contract-rollback`；
- Compose 文件；
- UTC 开始时间。
- 随机 owner token 的 SHA-256；原始 token 只存在于持有者进程环境，不写 stdout。

`mkdir` 原子成功才算获得锁。已有目录一律失败，不自动按 PID 或时间清理；人工确认没有部署/回滚
进程后才可删除遗留目录。只有 acquire 成功者才安装 trap；verify 要求 token 与锁 generation
匹配，release 还必须由保存 acquisition identity 的顶层持有者调用。竞争失败者直接退出，不能
注册会删除公共锁目录的 trap。持有者在正常退出及
`HUP/INT/TERM` 时释放；`KILL` 遗留锁是刻意的 fail-closed 选择。

### 3.6 修改四条 deploy/rollback 脚本

共同编排通过一个小型共享函数脚本实现，避免四份流程继续漂移。建议新增
`deploy/run_application_release.sh`，只接受：

- 精确 Compose 文件；
- `deploy|rollback` 动作；
- 由调用者已完成的 build/checkout 前置条件。

它每次尝试都读取普通 worker 与 `race_live_worker` 的当前 container hostname/运行态，用于
决定停止与 drain expected nodes；probe 失败一律 fail closed。首次尝试同时把
`race_live_worker` 的恢复意图写入 `${DEPLOYMENT_LOCK_DIR}.race-live-state`，六字段绑定：
state（running|not-running）、node、compose_file、action（deploy|rollback|
pre-contract-rollback）、head（`git rev-parse HEAD`）与 frozen_at_utc，写完 `chmod 600`。
读取方（编排、兼容桥与 `resume_stopped_release.sh`，共享 `deploy/race_live_state.sh`）
必须先校验：regular 且非 symlink、属当前用户、group/other 无任何权限、state 合法、
compose_file 与 head 绑定当前尝试、action 匹配（编排/桥要求==自身动作，resume 接受三者）。
该文件只决定恢复意图——重试仍重新 probe 当前运行态来决定停止与 drain（即使文件存在，
probe 失败也 fail closed）；编排/桥对任何校验失败在任何 stop 前 fail closed，resume 则
告警并跳过 race-live 恢复、核心服务照恢复。整个编排或兼容桥成功完成后删除该文件，失败
则保留供下一次重试复用；不可信的遗留文件只能人工核对后删除。
扩展 `wait_for_celery_drain.sh` 接受本次冻结的 expected node 集合；
`ping/active/reserved/active_confirm` 必须完整包含且不得遗漏任一原本 running worker，随后才执行：

```text
stop beat
-> wait_for_celery_drain（必须看到普通与 race-live worker 的完整空闲快照）
-> stop worker
-> race_live_worker 原本 running 时 stop race_live_worker
-> stop web
-> run_release_tasks
-> up -d --no-deps web
-> wait web healthy
-> up -d --no-deps worker beat nginx
-> race_live_worker 原本 running 时 up -d --no-deps race_live_worker
-> ps
```

标准/低成本 deploy 继续负责 `.env`、historical preflight、pull/build；rollback 继续负责目标
ref 校验、fetch/checkout/build。两类入口都在执行任何有状态步骤前获取同一部署锁。

为了避免迁移期间旧 web 或 race-live worker 使用新 schema，二者必须在 release task 前停止。
原先 absent/created/stopped 的 race-live worker 不恢复，防止部署改变功能启用状态。Nginx 可以保持
运行并短暂返回 502；这是现有非零停机架构可接受的已知行为，health 通过后重启 nginx 以刷新
upstream。

### 3.7 受保护的手工 release

`deploy/run_release_tasks.sh` 不是用户可直接绕过锁调用的公开命令。新增顶层
`deploy/manual_release.sh`：

1. 获取同一 deployment lock；
2. 核对既有 DB/Redis 和目标镜像；
3. 精确检查 web、worker、beat、race_live_worker 均不存在 running container；
4. 任一应用 service 为 running、状态无法读取或处于 restarting 时，在任何 Compose `run` 前
   fail closed；
5. 只有四类应用服务全部非运行时，才在锁内调用受保护 wrapper；
6. 完成后仍保持应用服务停止，不承担启动或恢复；服务恢复必须另走受审的 deploy/rollback
   orchestration。

wrapper 缺 owner token、token 不匹配或 lock metadata 漂移均在任何 Compose call 前退出。
测试和 runbook 不指导操作者直接调用内部 wrapper。手工入口不能替代普通部署，也不能在旧应用
仍访问数据库时应用 migration。

## 4. 状态与失败矩阵

| 失败点 | 数据库 | 服务状态 | 自动行为 | 人工恢复 |
|---|---|---|---|---|
| preflight/build | 未开始迁移 | 旧服务保持 | 立即退出 | 修复前置条件后重跑 |
| Celery drain 超时 | 未开始迁移 | beat 停、worker 仍在 | 不停 web、不迁移 | 查积压，安全后重跑 |
| release task 的 wait | 未迁移 | beat/worker/race-live/web 停 | 不启动下游 | 修 DB/Redis |
| migrate 失败 | 可能单 migration 回滚或部分序列完成 | 应用服务停 | 不 collectstatic、不启动下游 | 查 migration plan/DB；必要时恢复备份 |
| collectstatic 失败 | migration 已完成 | 应用服务停 | 不启动下游 | 修静态卷/磁盘后只重跑同一 release task |
| web unhealthy/timeout | migration、static 已完成 | web 失败，下游停 | 不启动 worker/beat/nginx/race-live | 查 web 日志；修复或按兼容性回滚镜像 |
| 下游启动失败 | migration、web 已完成 | 部分服务可用 | 脚本非零 | 按 `ps/logs` 恢复缺失服务 |

禁止在失败时自动恢复数据库或猜测旧镜像兼容。任何数据库恢复都必须使用本次部署前已创建并验证的
备份，并另行获得生产写入授权。

## 5. 回滚设计

### 5.1 post-contract 通用 rollback

代码 rollback 的步骤与 deploy 共享同一 release orchestration，但在进入 release task 前必须：

1. 核对目标 ref、目标镜像和当前 DB migration plan；
2. 判定当前 schema 是否与目标代码兼容；
3. 若不兼容，停止并选择：
   - 显式、已审核的反向 migration；或
   - 恢复部署前备份。

共享 release task 的 `migrate` 只会把目标代码已知 migration 推到其 forward head，不代表撤销
数据库中较新的 migration。交接和 runbook 必须醒目标记这一点。

通用 rollback 在任何停服/checkout 前使用 `git cat-file` 核对目标 ref 含
`deploy/release_contract_v1` 和全部 v1 helper；缺失则 fail closed。含 marker 的目标保证
checkout 后宿主 helper 和目标 image 内 release script 都存在。

### 5.2 首次发布的 pre-contract rollback bridge

本 change 首次生产发布的前一版本必然没有上述 helper。为此新增并单独测试
`deploy/rollback_pre_single_owner.sh`：

- 新控制面 checkout 保持不变，不 checkout 旧 ref；
- 必须提供部署前冻结的旧 image immutable tag/ID；
- 使用同一 deployment lock，停止并排空全部 Celery worker，停止 web；
- 若 schema 不兼容，先停在数据库恢复授权门禁；本脚本不自行恢复数据库；
- 把冻结旧 image 恢复为 Compose 使用的 image tag；
- 不运行新 one-shot、不调用旧 rollback 脚本；
- 启动旧 web；旧 image 的 `start-web.sh` 自身执行一次 migration/collectstatic；
- 等旧 web healthy 后恢复 worker/beat/nginx，并只按原始状态恢复 race_live_worker。

这条桥只用于回退到 pre-contract image，并明确接受旧 image 的 web-entrypoint owner；因为没有
第二个 `exec migrate`，运行时仍只有一个 migration process。通用 rollback 不得声称直接支持
任意旧 git ref。

## 6. 安全与兼容性

- 所有 shell 参数使用固定值或双引号；Compose 文件必须 allowlist。
- 不接受用户输入命令片段，不使用 `eval`。
- 不输出 `.env`、容器完整环境或 secret。
- release one-shot 不挂载 race reference/race-live publication 写目录之外的新增卷。
- 不改变 Compose service、healthcheck、queue、feature flag 或 restart policy。
- 生产只有单主机 Compose；锁是 host-local。未来多主机部署必须改用分布式 release lock。
- 迁移仍需遵循 Django 自身 atomic 属性；本 change 不承诺所有历史 migration 可逆。
- 已批准的例外（re-baseline，用户批准）：main 引入的 `deploy/deploy_race_live_p0_closed.sh`
  （race-live P0 closed-admission 一次性脚本）允许保留自己的 `collectstatic --noinput`，
  前提是不含 migrate、`verify_migration_plan_zero` 恰好两次、collectstatic 在 `up web`
  之前单进程执行；它不持有任何 migration 命令，不违反本设计的单一 migration owner 不变量。

## 7. 查询、性能和停机

本 change 不新增业务查询。release task 只执行一次 migration plan 和一次 collectstatic。
健康检查每 2 秒执行一次 Compose `ps` 和 Docker inspect，默认最多 300 秒；不会轮询数据库业务表。

停机从 `stop web` 开始，到新 web healthy 且 nginx 重启完成结束。预计无 migration 时主要由
collectstatic、Gunicorn 启动和 health interval 决定。发布前应在本地 Compose 测量实际时间；
若现有 30 秒 health interval 导致不可接受的停机，另行评审调整 healthcheck，不在本 change
隐式修改。

## 8. 设计不变量

1. 仓库中 migration 命令单点拥有。
2. 一个 release orchestration 只启动一个 migration process；pre-contract bridge 只启动旧 web
   的一个 migration process。
3. deploy、rollback 和手工 release 并发时只有一个获得锁，失败者不能释放赢家锁。
4. migration 失败后没有新应用服务启动。
5. worker/beat/race-live 只在 web healthy 后启动；race-live 仅恢复原本运行态。
6. 所有失败均显式非零，不用后续成功掩盖前一步失败。
7. 本 change 不产生 Django migration，也不写赛事/新闻业务数据。
