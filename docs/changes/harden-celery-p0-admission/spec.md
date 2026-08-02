# Celery 赛事实时任务 P0 关闭态投递止血规格

## 背景与根因

`race_live` 使用独立 Celery 队列和独立 worker。仓库当前同时存在以下行为：

1. `CELERY_BEAT_SCHEDULE` 无条件注册每分钟一次的
   `select_due_race_live_events_task` 和 `monitor_race_live_sla_task`；
2. `RACE_LIVE_SCHEDULER_ENABLED`、`RACE_LIVE_MONITOR_ENABLED` 只在任务开始执行后检查；
3. `monitor_race_live_sla_task` 被路由到 `race_live`；
4. monitor 产生的 `deliver_race_live_alert_task` 也显式投递到 `race_live`；
5. 普通 worker 默认只消费 `celery`，独立 worker 只消费 `race_live`。

因此，Beat 运行而 `race_live_worker` 停止时，即使 monitor 开关关闭，Beat 仍会每分钟向
无人消费的 `race_live` 队列增加一条消息。task body 返回 `disabled` 只能保护将来的消费，
不能阻止生产者持续入队。此前恢复后的只读快照曾观察到约 `5782` 条
`monitor_race_live_sla_task`；该数字只作为事故证据，实施或发布前必须重新只读核对，不能
当作当前实时状态。

## P0 目标

- 两个开关关闭时，从 Beat 生产者侧停止投递对应周期任务；
- 两个开关互相独立，开启配置仍保留既有队列拓扑；
- 为开启态的分钟唤醒消息附加 Celery 最佳努力过期元数据；
- 保留 task body 内部开关复核，形成生产者和消费者双层防护；
- 提供一条关闭态专用、Beat 分阶段启动、资源不足即停止的生产发布入口；
- 不处理现有积压，不启动 `race_live_worker`，不改变赛事业务数据。

## P0 范围

- race-live 两个 Beat entry 的条件注册；
- selector/monitor Beat entry 的既有队列和 `expires=55` 元数据；
- 四种开关组合、原有路由不漂移和部署顺序的自动化合同；
- `deploy/deploy_race_live_p0_closed.sh` 关闭态两阶段发布入口；
- 本 change 的 durable artifacts、项目状态、决策和运行手册。

## 非目标

- 把 monitor 或 alert delivery 迁移到普通 `celery` 队列；
- 解决 monitor 连续 tick 对同一 incident 的重复 broker 投递；
- 自动终止、revoke 或 kill 已有 Celery task/worker；
- 清理、迁移、消费或重写 Redis 中的历史队列消息；
- 启动、重建或修改生产 `race_live_worker`；
- 比赛 selector 的队列高水位背压或 worker heartbeat；
- `poll_race_live_event_task` 的 claim/generation/token 语义；
- 通用 `dispatch_task()` 同步降级策略；
- 新闻翻译、AI 编辑、发布、QQ 推送去重；
- 新模型、数据库迁移、Redis 锁或通用 singleton 框架；
- 启用 race-live scheduler、monitor、runner 或公开发布能力。

monitor/delivery 的独立运行和 durable dispatch admission 属于 P1。P1 必须在 broker 发布前
按 incident 原子领取、定义发布失败 CAS 释放/租约恢复、单轮硬上限，并覆盖并发 tick、
broker 失败、租约到期和外部发送去重。P0 不通过简单换队列绕过该设计。

## 行为要求

### 关闭时不注册周期任务

- `RACE_LIVE_SCHEDULER_ENABLED=false` 时，
  `CELERY_BEAT_SCHEDULE` 不包含 `select-due-race-live-events`；
- `RACE_LIVE_MONITOR_ENABLED=false` 时，
  `CELERY_BEAT_SCHEDULE` 不包含 `monitor-race-live-sla`；
- 两个开关互相独立；
- task 内部现有 `disabled` 返回继续保留，防止旧消息或配置漂移执行。

环境开关在 Beat 进程启动时读取。改变开关后必须重启或重建 Beat 才能刷新 schedule，
不得声称只编辑 `.env` 就已经生效。

### 队列拓扑保持不变

- selector Beat entry 继续进入普通 `celery`；
- `poll_race_live_event_task` 继续进入 `race_live`；
- `monitor_race_live_sla_task` 继续进入 `race_live`；
- `deliver_race_live_alert_task` 继续由 monitor 显式投递到 `race_live`；
- 普通 worker 默认只消费 `celery`，race-live worker 只消费 `race_live`。

P0 的首次发布必须保持 scheduler/monitor 关闭，因此不会触发上述开启态链路。若需要启用
monitor、迁移其队列或让告警脱离 race-live worker，必须先完成 P1 的 durable admission
方案和独立审核。

### 周期消息过期元数据

- selector 和 monitor 的 Beat entry 使用固定 `expires=55` 秒；
- selector 的 `options.queue=celery`；
- monitor 的 `options.queue=race_live`；
- alert delivery 和 poll 不在 P0 新增 55 秒 expiration。

本规格只承诺设置 Celery 的最佳努力过期元数据，不承诺 Redis 立即删除消息，也不承诺
任何已经被 worker 预取或保留的消息在 task body 开始时绝对不会执行。绝对执行时新鲜度
门禁若有业务需要，必须另立 change、增加 task body admission 和延迟执行行为测试。

### 关闭态专用发布入口

本 change 实现唯一入口 `deploy/deploy_race_live_p0_closed.sh`，分成两个显式阶段：

1. `prepare`：只允许三个值精确为
   `RACE_LIVE_SCHEDULER_ENABLED=false`、
   `RACE_LIVE_MONITOR_ENABLED=false`、
   `RACE_LIVE_RUNNER_MODE=disabled`；先停 Beat、排空并停普通 worker，再执行受控构建，
   用候选镜像只读确认待应用 migration 为零，再启动候选 web/普通 worker/nginx；停止 Beat
   之后的验证失败必须保持 Beat 停止；
2. `start-beat`：重新解析候选容器 flags 和 schedule，确认两个 entry 均不存在后，单独启动
   Beat；启动前还必须确认普通 worker 的 PID 1 参数只出现一个且精确为
   `--queues=celery`。启动后连续执行五轮关闭态后验，任一轮异常立即停止并复核 Beat；
   启动前断言失败均不得启动。

禁止原样运行 `deploy/deploy_lowcost.sh` 发布本 P0，因为它在停 Beat/worker 前构建，并把
worker、Beat、nginx 同时启动，无法建立候选 schedule 的验证点。

`prepare` 的量化 no-go 条件为：

- `/proc/meminfo` 的 `MemAvailable` 小于 `2048 MiB` 且 `SwapFree` 小于 `1024 MiB`；
- 或 `MemAvailable` 小于 `1536 MiB`，无论 swap 状态；
- Docker 数据目录或仓库所在文件系统任一可用空间小于 `6 GiB`；
- 最近 15 分钟内发现新的 OOM kill；
- 无法确认当前镜像 ID、关闭态 flags、Celery drain 或容器健康。

资源门禁在停 worker 后、构建前再次执行。候选构建仍在生产主机进行，但 Beat 和普通 worker
已停止；镜像只在构建成功后替换 `umanewsbot:prod`，构建失败时 Beat 保持停止并按 rollout
恢复旧镜像/普通 worker。P0 不引入未配置的镜像仓库，也不猜测预构建镜像已经可用。

`prepare` 使用显式状态机：

- `PRE_STOP_PREFLIGHT`：只读检查 flags、现有 image、磁盘、OOM 和当前 Beat 状态。此阶段
  失败不得改变服务，回执必须报告“Beat 保持进入命令前的实际状态”，不能声称已经停止；
- `BEAT_STOPPED`：执行并验证 `stop beat` 后进入。此后 drain、资源复核、构建、候选校验或
  恢复任一步失败，均必须再次验证 Beat 未运行；
- `CANDIDATE_READY`：候选 web/普通 worker/nginx 健康，但 Beat 仍停止；只有独立
  `start-beat` 阶段可改变该状态。

Compose 服务状态必须按显式状态解析。`restarting`、`paused`、`unknown` 或无法得到唯一
`State` 字段时一律不得当作 stopped；普通 worker 的 stop 命令即使非零，只要复核证明它
已经进入明确停止态，也必须先记录“worker 已停止”，再进入失败恢复并只恢复普通 worker，
Beat 继续停止，避免留下部分停服状态。

候选镜像必须在启动 web 前通过 Django migration graph 的只读检查，待应用 migration 数量
必须精确为 `0`。查询失败或数量非零时在启动候选 web 前退出。仓库现有
`start-web.sh` 会调用 `migrate --noinput`，因此零待应用断言必须在紧邻启动前再次通过，
使该启动调用只能是 schema no-op；P0 专用脚本本身不得另行执行实际 migrate。若 main 漂移
使此断言不再成立，回到方案审核和数据库备份/回滚规划，不得借 P0 应用其他 change 的迁移。

## 兼容与失败边界

- 关闭态部署后不产生新的 selector/monitor 周期消息；
- 已经在队列中的旧消息不会自动搬迁、消费或删除；
- 旧 monitor 消息未来若被消费，仍会先检查 monitor 开关；
- 开启态的 monitor/delivery 仍依赖停止中的 race-live worker，因此 P0 后不得启用；
- Celery `expires=55` 只提供最佳努力 broker/worker 过期提示；
- Celery Broker 不可用时的同步降级属于后续 P2，本 change 不修改；
- 无法确认生产路由、任务类型构成、active/reserved、flags 或资源时 fail closed。

## 验收标准

- 默认关闭配置下两个 race-live Beat entry 均不存在；
- 单独开启任一开关时只出现对应 entry；
- 两个 entry 均为每分钟一次、`expires=55`；
- selector entry 为 `queue=celery`，monitor entry 为 `queue=race_live`；
- monitor/delivery/poll 的既有 `race_live` 路由和显式派发不变化；
- task 级 disabled 防护与已有 alert lease/CAS 测试保持通过；
- 部署合同证明 `prepare` 先停 Beat/worker 再构建、不会启动 Beat，`start-beat` 必须在候选
  关闭态 schedule 验证后才单独启动；
- 普通 worker stop 命令非零但进程已停止时，失败恢复会恢复普通 worker；Beat 不恢复；
- `restarting`、`paused`、`unknown` 等模糊状态不会被误判为 stopped；
- 普通 worker PID 1 只允许唯一且精确的 `--queues=celery`，逗号多队列、前缀近似、
  重复 queue 参数或分离式多队列参数均阻断；
- `start-beat` 启动后必须连续完成五轮后验，每轮复核 Beat/web/普通 worker、
  `race_live_worker`、候选 image、目标 task 队列计数和 Beat 日志；任一异常立即停止并复核
  Beat；
- 待应用 migration 为零；migration 状态非零或不可读时不启动候选 web，也不调用脚本级
  实际 migrate；
- 停 Beat 前的只读 preflight 失败时不改变原 Beat 状态并准确报告；停 Beat 成功后的任何
  失败都非零退出并验证 Beat 仍停止；
- 无模型或迁移变化；
- 方案/实现阶段未进行生产连接、部署、队列清理、worker 启动或业务数据写入。
