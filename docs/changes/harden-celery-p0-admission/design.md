# Celery 赛事实时任务 P0 关闭态投递止血设计

## 当前数据流

```text
Celery Beat（无条件每分钟发布）
  ├─ select_due_race_live_events_task -> celery -> claim event
  │    └─ poll_race_live_event_task -> race_live
  └─ monitor_race_live_sla_task -> race_live
       └─ deliver_race_live_alert_task -> race_live
```

开关检查发生在 task body 内。`race_live_worker` 停止时，monitor 无法执行开关检查；Beat 仍
持续增加消息。监控链路与被监控的网络抓取链路共用同一停摆队列，也形成观测盲区。

第一轮方案把 monitor 和 delivery 一起迁到普通 `celery`。复审前代码追踪发现：
`stage_race_live_sla_alerts()` 会在每个 monitor tick 返回所有未终态 incident，而真正的
`next_attempt_at`、delivery lease 和 token 检查发生在 delivery task 出队后。直接换队列会
让同一 incident 在慢 worker 或 SMTP 故障时每分钟重复进入核心队列，因此 P0 放弃该迁移。

## P0 目标数据流

```text
Beat 启动时按开关构造 schedule
  ├─ scheduler 关闭：不注册 selector
  ├─ monitor 关闭：不注册 monitor
  ├─ selector 开启：celery，expires=55（最佳努力元数据）
  │    └─ 有效 claim 后 poll -> race_live
  └─ monitor 开启：race_live，expires=55（最佳努力元数据）
       └─ incident delivery -> race_live
```

P0 的首次生产状态只允许两个开关都关闭，所以目标不是让开启态 monitor 立即可用，而是先
停止错误生产者。开启态独立监控需要 P1 的 durable dispatch admission。

## 配置构造

在 `server/app/settings.py` 提供一个不访问环境和数据库的纯构造函数，例如：

```python
def build_race_live_beat_schedule(
    *,
    scheduler_enabled: bool,
    monitor_enabled: bool,
) -> dict:
    ...
```

函数只返回 race-live 两个 schedule entry：

- selector：`task=stable.tasks.select_due_race_live_events_task`，
  `options={"queue": "celery", "expires": 55}`；
- monitor：`task=stable.tasks.monitor_race_live_sla_task`，
  `options={"queue": "race_live", "expires": 55}`；
- 各自只有开关为真时存在；
- 均使用 `crontab(minute="*")`。

全局 `CELERY_BEAT_SCHEDULE` 保留现有其他 entry，再
`update(build_race_live_beat_schedule(...))`。不重新组织整个 settings，不改变其他 Beat
任务顺序、时间或路由。

使用纯函数是为了让测试覆盖四种开关组合，无需重载 Django settings 或依赖测试进程环境。

## Task 路由

P0 不改 `server/stable/tasks.py`，也不改现有路由：

```text
selector Beat entry            -> celery
poll_race_live_event_task      -> race_live
monitor_race_live_sla_task     -> race_live
deliver_race_live_alert_task   -> race_live（task body 显式指定）
```

现有普通 worker 启动脚本默认
`--queues="${CELERY_WORKER_QUEUES:-celery}"`；race-live worker 固定
`--queues="race_live"`。测试冻结这一现状，防止 P0 意外把重复告警扩散到核心队列。

## 最佳努力过期语义

分钟级唤醒任务的业务含义是“检查当前这一分钟是否有工作”。P0 为启用 entry 设置
`expires=55`，仅表达 Celery broker/worker 可以丢弃过期消息的元数据。

明确限制：

- 不声称 worker 延迟开始时有 task body 新鲜度 admission；
- 不声称被预取或保留的消息绝不会执行；
- Celery/Redis 可在消费者收到前仍保留过期消息，`LLEN` 不一定立刻下降；
- worker 丢弃过期消息不代表物理清理；
- alert delivery 不继承 55 秒过期，否则会破坏持久 incident 的重试语义；
- poll 有数据库 claim TTL/generation，本次不改。

因此自动化测试只验证 schedule 元数据和关闭态根因，不把 `expires` 当绝对执行合同。

## 并发、幂等与 P1 边界

P0 不新增锁、模型或 migration：

- selector 仍由 `claim_due_race_event_live_tracking()` 的
  `select_for_update(skip_locked)` 和 active claim 约束；
- poll 仍在网络前检查 owner generation、claim generation、attempt token 和 expiry；
- SLA incident 仍以 `dedupe_key` 唯一；
- alert delivery 仍以 delivery lease/token/CAS 防重复完成。

这些机制不能阻止同一 incident 在 delivery 消费前重复进入 broker。P1 必须增加 broker
发布前 admission，至少锁定：

1. incident 级 durable dispatch token/lease 或 outbox；
2. 单轮硬上限；
3. broker 发布失败后的 token CAS 释放；
4. 租约超时和 retry 到期后的恢复；
5. 旧 token task 不得产生外部发送；
6. 连续/并发 monitor tick 不得为同一 incident 增加有效投递。

完成 P1 前，生产 `RACE_LIVE_MONITOR_ENABLED` 必须保持 false。

## 性能与容量

- 关闭态：两个 Beat entry 的发布量从每分钟各一条降为零；
- 开启态路由、查询上限和 worker 并发均不变化；
- settings 只构造最多两个小字典，不增加 ORM 或 Redis 调用；
- 生产验收观察至少 5 个完整分钟，要求关闭态两个目标 task 的新入队计数为 0；
- 队列总长度可能因其他生产者变化，所以必须同时按 task 名称取样，不能只看 `LLEN`。

## 预计文件

- `server/app/settings.py`
- `server/stable/test_race_live_sla_monitor.py`
- `server/stable/test_realtime_race_results.py`
- `server/stable/test_race_live_p0_deployment_contract.py`
- `deploy/deploy_race_live_p0_closed.sh`
- `docs/changes/harden-celery-p0-admission/*`
- `docs/current_state.md`
- `docs/decisions.md`
- `docs/deploy_runbook.md`
- `docs/project_status.md`

不预计修改 `server/stable/tasks.py`、`.env.example`、Compose、worker shell、模型或迁移。

## 关闭态两阶段发布设计

部署需要最新 review 后的独立授权。唯一入口是：

```bash
./deploy/deploy_race_live_p0_closed.sh prepare
./deploy/deploy_race_live_p0_closed.sh start-beat
```

不得原样运行 `deploy/deploy_lowcost.sh`。

### `prepare`

按固定顺序执行：

1. 读取 `.env`，只打印脱敏后的布尔判定；精确要求 scheduler=false、monitor=false、
   runner mode=disabled；
2. 只读保存生产 HEAD、当前 `umanewsbot:prod` image ID、Compose 状态、worker 命令、
   active/reserved/scheduled 和两个队列按 task 名的构成；
3. 验证最近 15 分钟无新 OOM kill，仓库和 Docker 数据目录各有至少 `6 GiB`；
4. 停止 Beat；
5. 查询 Compose 状态并验证 Beat 已停止；只有此断言成功才进入 `BEAT_STOPPED`；
6. 运行既有 `wait_for_celery_drain.sh`，成功后停止普通 worker；无论 stop 命令退出状态
   如何，都先复核服务状态。若 stop 非零但 worker 已进入明确停止态，先记录
   `WORKER_STOPPED` 再失败退出，使 trap 恢复普通 worker；若为
   `restarting/paused/unknown` 等模糊状态则 fail closed，不继续构建；
7. 再次验证资源：
   - `MemAvailable >= 1536 MiB`；
   - 且当 `SwapFree < 1024 MiB` 时，要求 `MemAvailable >= 2048 MiB`；
8. 为当前 `umanewsbot:prod` 建立只用于本次窗口的精确 rollback image tag；
9. 运行历史 runner preflight，不执行 nginx pull、不改变当前本地 nginx image，并受控
   构建 `web`；
10. 用候选 image 的一次性、`--no-deps` 命令执行 Django check，并通过
    `MigrationExecutor.migration_plan(graph.leaf_nodes())` 只读取得待应用 migration 数；
11. 要求 migration 数精确为 `0`；查询错误或非零立即退出，不启动候选 web；
12. 在同一个候选 image 中解析三个关闭态值和 `CELERY_BEAT_SCHEDULE`，要求两个 entry 均
    不存在；
13. 紧邻启动前再次执行零待应用 migration 断言，防止步骤 10 之后状态漂移；
14. 通过资源门禁后执行候选 image 的 `collectstatic --noinput`；
15. 启动候选 `web`。仓库 `start-web.sh` 内的 `migrate --noinput` 已由步骤 13 证明为
    schema no-op；P0 脚本不得另外执行 migrate；
16. 只启动普通 worker和 nginx；nginx 使用当前本地 image
    `--force-recreate nginx`。验证 web healthz，并从普通 worker PID 1 的
    `/proc/1/cmdline` 证明 queue 参数只出现一次且精确为 `--queues=celery`；
17. 正常退出进入 `CANDIDATE_READY`，Beat 和 `race_live_worker` 均继续停止。

状态机和失败语义：

- 步骤 1～3 为 `PRE_STOP_PREFLIGHT`，只读失败时不得执行 `stop/build/up`，服务保持进入命令
  前的实际状态；回执记录“Beat 原状态为 running/stopped/unknown，未被本命令改变”；
- 步骤 5 成功后为 `BEAT_STOPPED`，步骤 6～16 任一步失败都非零退出并再次验证 Beat 未运行；
- 失败 trap 只做证据和状态检查，不启动 Beat；
- Compose 服务状态使用唯一 `State` 字段显式分类；
  `restarting/paused/unknown` 不属于停止终态，不得继续 prepare 或 start-beat；
- 普通 worker 已停止但 stop 命令非零时，失败 trap 必须恢复普通 worker，不能因退出码
  处理顺序遗漏部分停服恢复；
- 若新 web/worker 不健康，使用 rollback image tag 恢复 web/普通 worker，仍保持 Beat
  停止；
- migration plan 非零或不可读时不执行候选 web `up`，也不存在脚本级
  `migrate --noinput` 调用。
- P0 不 pull 可变 nginx image。现有 rollback tag 只覆盖应用 image，若在本窗口改变 nginx
  image 就没有对称的镜像级恢复；因此 nginx 只允许使用进入窗口时已有的本地 image 做
  force-recreate 和 healthz 验证。

### `start-beat`

按固定顺序执行：

1. 再次验证三项关闭态值；
2. 再次从候选 image 启动的一次性容器解析 schedule，确认两个 entry 不存在；
3. 确认 web/普通 worker 健康、race-live worker 处于明确停止态，并确认普通 worker
   PID 1 只有一个且精确的 `--queues=celery` 参数；
4. 使用 `manage.py shell --no-imports -c` 取得启动前两个队列长度及 selector/monitor
   task 计数；stdout 必须只包含 machine snapshot。parser 保持严格，任何 banner、多余行或
   畸形输出都在启动 Beat 前 fail closed；
5. 单独 `up -d --no-deps beat`；
6. 验证 Beat 使用与 web/worker 相同 image ID；
7. 连续五轮执行后验；每轮使用同一无 auto-import 的 machine snapshot 路径，并
   复核 Beat/web/普通 worker 为 running、race-live worker 仍明确停止、三者使用候选 image、
   普通 worker PID 1 queue 仍精确、healthz/ping 正常、目标 task 计数未超过启动前基线，
   且本窗口 Beat 日志不含两个关闭态 entry/task 名称。

若第 1～4 步任一失败，不执行启动 Beat 的命令。五轮内任一健康、镜像、状态、队列计数或
日志验证失败，立即停止并复核 Beat，保留已完成轮次证据，不清队列、不启动 race-live worker。

## 部署合同测试

新增自动化合同不得真实执行 Docker 或修改服务。通过隔离的 fake command 目录和临时状态
输入验证脚本控制流：

- 开关或资源 no-go 时，在任何 `build/up` 前非零退出；
- pre-stop 失败不调用 `stop beat`，并报告 Beat 原状态未被改变；
- `prepare` 的调用序列中 `stop beat` 早于 drain/stop worker 和 build；
- 普通 worker stop 非零但已经停止时，失败恢复会重新启动普通 worker，Beat 保持停止；
- `restarting/paused/unknown` 等模糊 Compose 状态不能作为 worker 或 race-live worker
  的停止证据；
- stop Beat 后的失败路径会验证 Beat 最终未运行；
- `prepare` 不出现启动 Beat；
- 待应用 migration 非零或状态不可读时不启动候选 web，且脚本不调用实际 migrate；
- migration 零断言在候选 web 启动前执行两次；
- 候选 schedule 验证失败时不出现启动 Beat；
- `start-beat` 只有在关闭态、schedule、web/worker/race-live 三组断言都成功后才出现
  `up -d --no-deps beat`；
- start-beat 只接受普通 worker PID 1 唯一精确 `--queues=celery`；
- start-beat 成功返回前必须完成五轮持续后验；第 3 轮健康失败、目标 task 计数增长、
  Beat 日志出现目标 entry/task 或 race-live worker 转为 restarting 时都会立即停止 Beat；
- queue snapshot 必须调用 `manage.py shell --no-imports -c`；Django auto-import banner
  不得进入 stdout，畸形或多余输出不得通过放宽 parser 绕过；
- 失败恢复只允许恢复 web/普通 worker，始终保持 Beat 停止。

测试固定脚本入口和命令序列，避免文档顺序与实际脚本漂移。

## 回滚

无 schema 和业务数据变更。旧代码会重新无条件注册两个 entry，因此安全回滚为：

1. 先停止 Beat；
2. 确认三个关闭态值仍满足；
3. 使用本次 `prepare` 记录的 rollback image tag 恢复 web/普通 worker；
4. 验证 healthz 和普通 worker；
5. Beat 保持停止，直到恢复 P0 候选或采用替代生产者止血；
6. `race_live_worker` 保持停止；
7. 不清队列、不恢复数据库、不启用比赛网络任务。
