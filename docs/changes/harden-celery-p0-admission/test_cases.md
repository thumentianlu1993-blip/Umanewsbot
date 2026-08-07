# Celery 赛事实时任务 P0 关闭态投递止血测试用例

## 自动化测试矩阵

### 周期任务条件注册

1. scheduler=false、monitor=false：两个 race-live Beat entry 均不存在。
2. scheduler=true、monitor=false：只存在 selector。
3. scheduler=false、monitor=true：只存在 monitor。
4. scheduler=true、monitor=true：两个 entry 都存在。
5. 两个 entry 均为每分钟一次。
6. selector 的 `options` 为 `{"queue": "celery", "expires": 55}`。
7. monitor 的 `options` 为 `{"queue": "race_live", "expires": 55}`。
8. 其他现有 Beat entry 不因 race-live 构造函数改变。

### 路由不漂移

9. `poll_race_live_event_task` 路由保持 `race_live`。
10. `monitor_race_live_sla_task` 路由保持 `race_live`。
11. monitor stage 出 incident 后，delivery 的 `apply_async` 仍显式使用
    `queue="race_live"`。
12. 普通 worker 脚本默认消费 `celery`，race-live worker 只消费 `race_live`。

这组测试是回归保护，不是目标 RED。它防止 P0 把缺少 broker 入队前 admission 的告警副本
扩散到核心队列。

### 防御性回归

13. scheduler task 内部在开关关闭时仍返回 disabled，且不 claim。
14. monitor task 内部在开关关闭时仍返回 disabled，且不 stage incident。
15. monitor 开启但 enabled regions 为空时仍不 stage/deliver。
16. 现有 alert incident 唯一键、delivery lease、旧 token 不可完成和失败重试测试保持通过。
17. selector 产生 poll 时仍显式进入 `race_live`。

### 部署合同

18. `deploy_race_live_p0_closed.sh prepare` 在任一关闭态值不满足时，在 Docker build/up 前
    非零退出。
19. 内存、swap、仓库磁盘、Docker 数据目录或最近 OOM 任一触发 no-go 时，prepare 非零退出。
20. pre-stop flags/资源检查失败时不调用 stop/build/up，Beat 保持进入命令前的实际状态，
    回执不得声称已停止。
21. prepare 调用顺序满足：stop Beat -> 验证 Beat 已停 -> drain worker -> stop worker ->
    二次资源门禁 -> build。
22. stop Beat 成功后的任一失败路径都会查询最终状态并断言 Beat 未运行。
23. 候选 Django migration graph 待应用数量非零时，在启动候选 web 前失败。
24. migration graph 不可读/查询退出非零时，在启动候选 web 前失败。
25. migration 零断言在候选 web 启动前执行两次，脚本本身不调用
    `manage.py migrate --noinput`。
26. prepare 只启动 web/普通 worker/nginx，不启动 Beat 或 race-live worker。
27. 候选 settings/schedule 验证失败时，Beat 保持停止。
28. `start-beat` 必须重新通过关闭态、候选 schedule、web/worker 健康和 race-live worker
    停止四组断言后，才单独启动 Beat。
29. prepare/start-beat 失败路径均不得通过 trap 隐式启动 Beat。
30. 测试使用 fake command 目录和临时输入，不真实连接 Docker、Redis、生产数据库或网络。
31. 普通 worker stop 命令非零但最终状态已经停止时，prepare 非零退出、恢复普通 worker，
    Beat 仍停止且不进入 build。
32. 普通 worker 或 race-live worker 为 `restarting/paused/unknown` 时不得解释为 stopped；
    prepare/start-beat 均 fail closed。
33. start-beat 只接受普通 worker PID 1 唯一精确 `--queues=celery`；逗号多队列、
    `celery2`、重复 queue 参数和分离式多队列值均阻断且不启动 Beat。
34. start-beat 成功必须连续完成五轮后验，每轮复核服务状态、候选 image、health、worker
    queue、两个队列长度、selector/monitor 计数和 Beat 日志。
35. 五轮内 web health 失败、目标 task 计数增长、Beat 日志出现目标 entry/task，或
    race-live worker 转为 restarting 时，命令非零退出并立即停止、复核 Beat。
36. prepare 不执行 `pull nginx`，不改变可变 nginx image；仍使用当前本地 image
    `--force-recreate nginx` 并执行 healthz 检查。
37. start-beat 的 machine queue snapshot 必须使用
    `manage.py shell --no-imports -c`；Django auto-import banner 不得污染 stdout。
    parser 继续严格拒绝畸形或多余输出，并在任何 `up beat` 前 fail closed。

### 静态与配置回归

38. 没有模型或迁移变化。
39. settings 可以在默认关闭环境正常导入。
40. Django system check 通过。
41. 专用脚本通过 `sh -n`；文档和脚本固定使用同一入口和阶段名。

## RED 取得方式

不得一次写完所有测试后只保存一张总红灯。

### RED 1：关闭态仍注册

新增纯构造合同并让默认
`RACE_LIVE_SCHEDULER_ENABLED=false/RACE_LIVE_MONITOR_ENABLED=false` 断言
`CELERY_BEAT_SCHEDULE` 不含两个 entry。

当前代码无条件注册，因此应明确失败为对应 key 仍存在，不能来自 import、fixture 或语法
错误。

### RED 2：缺少独立开关构造

分别调用目标纯函数覆盖 `false/false`、`true/false`、`false/true`、`true/true`。

当前函数不存在，因此失败应为缺少目标 API。RED 记录后才能增加实现；测试不得通过自行复制
settings 字典绕过目标能力。

### RED 3：分钟 entry 没有最佳努力过期元数据

对两个启用 entry 分别断言：

```python
selector["options"] == {"queue": "celery", "expires": 55}
monitor["options"] == {"queue": "race_live", "expires": 55}
```

当前 entry 没有 `options`，测试应以目标元数据缺失失败。本 RED 不声称或测试 worker 延迟
执行时的绝对新鲜度。

### RED 4：关闭态专用发布入口不存在

新增部署合同测试，先断言
`deploy/deploy_race_live_p0_closed.sh` 存在并支持 `prepare`、`start-beat`。当前文件不存在，
因此第一个失败应为精确入口缺失。

### RED 5：部署顺序和 fail-closed 合同

在入口骨架存在后，用 fake `docker`/compose/system command 记录调用，逐项取得：

- pre-stop 关闭态/资源失败仍进入 stop/build/up，或错误声称 Beat 已停；
- stop Beat 后失败未验证最终 Beat 状态；
- prepare 未按 stop Beat -> 验证停止 -> drain/stop worker -> build 排序；
- migration plan 非零仍启动 web；
- migration 状态不可读仍启动 web；
- 零 migration 只检查一次，或脚本直接调用 `migrate --noinput`；
- prepare 启动 Beat；
- start-beat 未验证候选 schedule 就启动 Beat；
- 失败 trap 重新启动 Beat；
- 普通 worker stop 已经造成停止但命令非零时，没有恢复普通 worker；
- 把 `restarting/paused/unknown` 当作 worker 已停止；
- 只检查启动脚本默认值而不检查运行中普通 worker PID 1 的唯一精确 queue；
- start-beat 启动后没有完成五轮持续后验，或后验异常未立即停止 Beat；

对应的真实 RED。测试必须按一个行为一个断言推进，不能用只读取脚本文本的脆弱子串匹配替代
控制流验证。

### RED 6：Django auto-import banner 污染 machine stdout

生产 `start-beat` 在真正执行 `up beat` 前取得 queue snapshot 时，Django shell 输出
`105 objects imported automatically (use -v 2 for details).`，严格 parser 因多余 stdout
正确 fail closed。合同测试先复现该 banner，并断言 Beat 未启动；GREEN 只允许为 machine
snapshot 增加 `shell --no-imports -c`。不得删除严格格式断言、跳过首行或容忍任意前缀。

## GREEN 与验证命令

实现后至少运行：

```bash
cd server
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  ../.venv/bin/python manage.py test \
  stable.test_race_live_sla_monitor.RaceLiveSlaMonitorTaskContractTests

DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  ../.venv/bin/python manage.py test \
  stable.test_realtime_race_results.RaceLiveCeleryIsolationTests \
  stable.test_realtime_race_results.RaceLiveWorkerDeploymentContractTests \
  stable.test_race_live_p0_deployment_contract

DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  ../.venv/bin/python manage.py check

DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
  ../.venv/bin/python manage.py makemigrations --check --dry-run

sh -n deploy/deploy_race_live_p0_closed.sh
git diff --check
```

完整 `stable` 回归在聚焦 GREEN 后执行。所有自动化测试禁止真实网络、SMTP、Redis、Docker
和生产数据库。若仓库精确类名在实现前因 main 漂移，先更新方案并回到同一 reviewer 复审，
不得用“以实现时为准”替代冻结命令。

## 部分部署后 stdout 修复与当前验证

首次代码 review 提出的五项 actionable finding 已分别补入上述部署合同：普通 worker
部分停止恢复、模糊 Compose 状态拒绝、PID 1 唯一精确 queue、start-beat 五轮持续后验与
异常停 Beat、完整 stable 同 HEAD 干净基线对照。同一 reviewer 限定复审 session
`019faecf-f5fe-7900-be8d-95998bcb6b42` 已确认原五项全部关闭，但新增 P1：`pull nginx`
改变可变镜像且没有 nginx 镜像级回滚，verdict 为 `REVISE`。该 P1 已按真实 RED/GREEN
补充上述第 36 项合同并最小修复：取消 nginx pull，保留当前本地 image 的
force-recreate 与 healthz。

初始实现 commit `611c6aab` 已经 PR `#46` 合并为 `main@7cd144ab`。生产
`prepare` 成功；`start-beat` 因上述 banner 在 `up beat` 前 fail closed，Beat 保持
exited。当前本地 final fix 已由主代理复跑：

```text
stable.test_race_live_sla_monitor
stable.test_realtime_race_results.RaceLiveCeleryIsolationTests
stable.test_realtime_race_results.RaceLiveWorkerDeploymentContractTests
stable.test_race_live_p0_deployment_contract
```

结果为 `64/64 / 57.693s / exit 0`，其中部署合同为
`33/33 / 56.236s / exit 0`。Django check 为 exit `0`；
`makemigrations --check --dry-run` 输出 `No changes detected`；`sh -n` 与
`git diff --check` 均为 exit `0`。这些是当前候选验证证据，不能冒充限定复审通过或新的

完整 `stable` 对照结果：

- 候选未提交工作树：`3830 tests / 216.643s / 26 failures / 148 errors /
  72 skipped / exit 1`；
- 干净基线 worktree：
  `HEAD=78719a467a2eceb57572b484a906cb78761badf8`，
  `3790 tests / 167.124s / 26 failures / 148 errors / 72 skipped / exit 1`；
- 原始唯一 failure/error headings 均为 `174`，候选 only 与基线 only 均为 `0`，
  两边 SHA-256 均为
  `a214e6a1ac4ff5cdfe0c0f2a0670525d3ed30bf41a191b18cbcaa85d9acd7040`；
- 规范化失败方法均为 `153`，候选 only 与基线 only 均为 `0`，两边 SHA-256 均为
  `077c2f0634b1a3221394f4b605e986d2393d8778e1068215a10b72fcb0ec1ae2`。

这证明本 scope 新增失败方法标识为 `0`，不代表完整 suite 全绿。完整规范化列表见
`full_stable_failure_baseline.txt`；原始 headings 中的巨大 subtest repr 不复制进仓库，
只保存其计数、差集与 hash。


- 只使用 `deploy_race_live_p0_closed.sh prepare`，不得原样运行 `deploy_lowcost.sh`；
- 从候选容器解析 settings，确认三个关闭态值和两个 schedule key；
- 从候选 migration graph 取得待应用数量 `0`；非零或不可读即 no-go；
- 核对普通 worker 实际命令只消费 `celery`，`race_live_worker` 仍停止；
- prepare 成功后先保存证据并确认 Beat 仍停止，再运行 `start-beat`；
- 保存发布前后两个队列长度和目标 task 名称计数；
- 连续至少 5 个分钟边界，关闭态不得新增 selector/monitor；
- healthz、首页、赛事入口和普通 Celery ping 正常；
- 不消费、不删除、不迁移现有 `race_live` 历史消息。
