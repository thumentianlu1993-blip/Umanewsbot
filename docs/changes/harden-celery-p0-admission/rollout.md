# Celery 赛事实时任务 P0 投递止血 rollout

## 当前阶段

初始实现 commit `611c6aab` 已经 PR `#46` 合并为 `main@7cd144ab`。生产已成功完成
`prepare`，但 `start-beat` 在真正执行 `up beat` 前因 Django auto-import banner 污染
machine queue snapshot stdout 而 fail closed。当前阶段为
`部分部署停在安全检查点 -> stdout final fix 已 GREEN -> 待同一 reviewer 限定复审和重新授权`；
这不是发布成功。方案 reviewer 第三轮限定复审结论为 `APPROVED`，其冻结范围为：

- P0 只做关闭态 Beat 生产者止血，不迁移 monitor/delivery 队列；
- `expires=55` 只作为 Celery 最佳努力元数据；
- 关闭态发布入口固定为 `prepare` / `start-beat` 两阶段；
- migration 零计划双重门禁和 Beat 三状态失败语义纳入自动化合同；
- 方案审核时生产状态仍未知；该历史方案结论不替代后续真实生产预检、发布授权或运行态证据。

实现事实：

- `server/app/settings.py` 已增加纯 builder；两个关闭 flag 分别不注册 selector/monitor，
  开启 entry 保持 selector→`celery`、monitor→`race_live` 和 `expires=55`；
- 未修改 `server/stable/tasks.py`、现有 task route、模型、migration、Compose、worker
  shell 或 `.env.example`；
- 新增 `deploy/deploy_race_live_p0_closed.sh prepare|start-beat`，覆盖生产根 test/fake
  覆盖拒绝、三状态边界、资源/OOM/磁盘、两次零 migration plan、候选 schedule 和失败后
  Beat 保持停止/旧 web 与普通 worker 恢复；
- 普通 worker stop 非零但已经停止时会进入失败恢复并恢复普通 worker；Beat 保持停止；
- Compose 状态显式拒绝把 `restarting/paused/unknown` 解释为 stopped；
- 普通 worker 运行态从 PID 1 参数证明 queue 选项唯一且精确为 `--queues=celery`；
- start-beat 在启动前保存队列/task 基线，启动后连续执行五轮健康、镜像、状态、队列计数和
  Beat 日志后验；任一异常立即停止并复核 Beat。
- P0 脚本不再 pull nginx，不改变当前本地 nginx image；仍以该 image
  `--force-recreate nginx` 并执行 healthz 检查。
- 当前本地 final fix 只把 machine snapshot 改为 `manage.py shell --no-imports -c`，
  parser 继续严格拒绝 banner、多余行和畸形输出。

验证边界：

- stdout final fix 后当前候选已由主代理复跑四组聚焦，结果为
  `64/64 / 57.693s / exit 0`，其中部署合同
  `33/33 / 56.236s / exit 0`；Django check 为 exit `0`，
  `makemigrations --check --dry-run` 为 `No changes detected`，`sh -n` 与
  `git diff --check` 均为 exit `0`；
- 完整 stable 候选为
  `3830 tests / 216.643s / 26 failures / 148 errors / 72 skipped / exit 1`；
  同 HEAD 干净基线为
  `3790 tests / 167.124s / 26 failures / 148 errors / 72 skipped / exit 1`；
- 原始唯一 headings 均 `174`，SHA-256 均为
  `a214e6a1ac4ff5cdfe0c0f2a0670525d3ed30bf41a191b18cbcaa85d9acd7040`；规范化方法均
  `153`，SHA-256 均为
  `077c2f0634b1a3221394f4b605e986d2393d8778e1068215a10b72fcb0ec1ae2`；
  两种口径候选 only/基线 only 均为 `0`，因此本 scope 新增失败标识为 `0`，但完整 suite
  仍非全绿。完整方法清单见 `full_stable_failure_baseline.txt`。

当前只允许回到代码 reviewer 的同一会话，限定复审 stdout final fix 和直接触及路径。复审
必须按 `docs/codex_workflow.md` 对完整 uncommitted scope 执行原生只读审核和前后
fingerprint 核对。聚焦 `64/64` 和静态检查通过不等于 review 通过。

当前未允许：

- 把 finding 修复、部署合同通过或基线同集表述为代码 review 通过；
- 未经复审和新授权直接 commit、push、PR/merge 或继续部署；
- 清理/迁移队列、启动 worker、启用 flag、执行 migration 或生产写入；
- 热补丁生产脚本、手工启动 Beat，或使用此前授权代替变化后版本的新发布授权。

截至本次回写，生产 HEAD 为 `7cd144ab`，web/worker 运行初始候选 image
`sha256:17562c52...acea7`；Beat exited、race-live worker `Created`，flags 仍为
`false/false/disabled`。`race_live=6574` 为未处理 monitor 积压。final fix 尚未进入生产，
五轮后验尚未开始。

## 2026-07-30 部分部署证据

- 预检：Compose `5.1.2`；首次 active/reserved/scheduled `0/0/0`、`celery=0`；
  `race_live` 从 `6055` 增到 prepare 前 `6574`，全部是 monitor。
- 资源门禁先以 `MemAvailable=867284 KiB / SwapFree=0 KiB` NO-GO。用户额外授权后创建并
  启用 `/swapfile-umanews-p0-20260730`（`2 GiB`、`0600`、不写 fstab），空闲 worker
  优雅重启，OneBot 最终 running。
- 生产仓库 `4221affa -> 7cd144ab`；既有 `12` 个 deploy 脚本 mode-only dirty 保留。
- `prepare`：drain active `2→0`；rollback tag
  `umanewsbot:rollback-race-live-p0-20260730T030255Z` 指向旧 image
  `sha256:7d730634...8774`；候选 `sha256:17562c52...acea7`；migration `0/0`，
  settings closed，web/worker/nginx 与内外 healthz `200`。
- `start-beat`：启动前 queue snapshot stdout 出现
  `105 objects imported automatically (use -v 2 for details).`，严格 parser
  fail closed；Beat 没有启动，五轮未执行，后验队列仍为 `6574`。
- 完整证据和后续门禁见 `release_report.md`。

## 基线

- 建立时间：2026-07-29；
- 基线：`origin/main@78719a467a2eceb57572b484a906cb78761badf8`；
- worktree：
  `/Users/mentianlu/Code/umanews/.worktrees/harden-celery-p0-admission`；
- 分支：`codex/harden-celery-p0-admission`；
- 建立时 HEAD 与 `origin/main` 一致，工作树干净。

## 当前证据边界

- 基线 `origin/main@78719a467a2eceb57572b484a906cb78761badf8`：Beat 无条件注册两个
  race-live 周期任务；monitor 和 delivery 使用 `race_live`；普通 worker 默认消费
  `celery`，专用 worker 只消费 `race_live`。
- 当前生产初始候选：Beat 按两个开关独立注册 entry，关闭态两项均不存在；开启态队列拓扑
  不变并带最佳努力 `expires=55`。生产已通过 prepare，但未通过 start-beat 五轮。
- 当前本地 final fix：仅为 machine queue snapshot 增加 `--no-imports`；尚未 review、
  commit、merge 或部署。
- 当前生产：HEAD `7cd144ab`、flags `false/false/disabled`、Beat exited、
  race-live worker `Created`、`race_live=6574`。继续动作前仍须重新只读核对，不能把本次
  快照冒充未来运行态。

## 并行工作与脏工作区

主工作区 `/Users/mentianlu/Code/umanews` 基于较旧 HEAD，包含大量用户及其他任务的 tracked
和 untracked 改动，尤其包括状态文档、settings、tasks 和测试。该工作区不得用于本任务实现，
不得复制整文件覆盖本 worktree。

本 worktree 基于最新 `origin/main`，只允许本 change 的窄改。若 main 在实现期间推进：

1. 到安全检查点；
2. 重新读取新 main 的 `AGENTS.md` 和工作流；
3. 只读比较相关 settings/task/tests；
4. 必要时更新方案并回到同一方案 reviewer 复审；
5. 不在未评审状态下直接 merge/rebase 后继续实现。

## 生效边界

P0 只改变 race-live 周期消息的生产者条件和分钟 entry 的最佳努力过期元数据，并增加关闭态
专用部署入口。monitor、delivery、poll 的队列拓扑不变。不启用任务，不改变赛事状态、
claim、赛果、发布、新闻或 QQ 行为。

旧队列消息不会自动迁移或删除。代码部署、积压处理、启用 monitor、启用 selector、启动
race-live worker 是不同状态变更，必须分开。

## 实施门禁

1. 五份 artifacts 完整；
2. 方案 reviewer 首审并输出 findings/结论；
3. 若 REVISE，在同一 reviewer 会话修订和限定复审；
4. reviewer `VERDICT: APPROVED`；
5. 主代理向用户提交已审摘要；
6. 用户针对当前版本明确授权实现；
7. 测试 subagent 逐行为取得真实 RED；
8. 实现 subagent 完成 GREEN/REFACTOR；
9. 主代理统一验证；
10. 未参与实现的代码 reviewer subagent 执行原生只读 review；
11. actionable findings 清零并冻结 fingerprint；
12. 用户在最新成功 review 后另行授权发布。

## 发布前只读核对

- 生产 HEAD、镜像和 Compose 文件；
- 解析后的 scheduler/monitor/runner/publication flags；
- Beat 实际 schedule；
- 普通 worker 和 race-live worker 的命令、队列和状态；
- Celery active/reserved/scheduled；
- Redis `celery`、`race_live` 长度、最老消息时间和 task 名称构成；
- 候选 image 的 Django migration graph 待应用数量；
- 磁盘、内存、容器健康、本地/公网 healthz；
- 是否存在其他部署、迁移、历史 runner 或维护窗口。

任一证据不可用或与方案假设不一致即停止。

## 关闭态发布

本 change 的首次生产验收只允许关闭态：

- scheduler=false；
- monitor=false；
- runner=disabled；
- publication/allowlist 不扩大；
- race-live worker 保持停止；
- 不清理历史队列。

发布唯一入口：

```bash
./deploy/deploy_race_live_p0_closed.sh prepare
./deploy/deploy_race_live_p0_closed.sh start-beat
```

`prepare` 必须在停 Beat、验证停止、drain 并停普通 worker 后才构建。候选 image 必须在
web 启动前两次通过“待应用 migration 数为 0”的只读断言；非零或不可读均不得启动候选
web，P0 脚本不得直接执行 migrate。之后只启动候选 web/普通 worker/nginx，验证候选关闭态
schedule 后正常退出且 Beat 仍停止。`start-beat` 必须再次验证关闭态、候选 schedule、
web/worker 健康和 race-live worker 停止后，才单独启动 Beat。禁止原样运行
`deploy_lowcost.sh`。

量化 no-go：

- `MemAvailable < 1536 MiB`；
- 或 `SwapFree < 1024 MiB` 且 `MemAvailable < 2048 MiB`；
- 仓库或 Docker 数据目录任一可用空间 `< 6 GiB`；
- 最近 15 分钟有新 OOM kill；
- 当前 image、flags、drain、候选 schedule 或健康状态不可核实。

失败状态必须按阶段报告：

- `PRE_STOP_PREFLIGHT` 失败：不调用 stop/build/up，Beat 保持进入命令前的实际状态，回执
  明确写 running/stopped/unknown 和“未被本命令改变”；
- 验证 `stop beat` 成功后：进入 `BEAT_STOPPED`，后续任一失败都再次验证 Beat 未运行；
- 候选准备完成：进入 `CANDIDATE_READY`，Beat 仍停止，只能由独立 `start-beat` 改变。

部署后只验证 schedule 不再发布目标消息、普通站点健康和按 task 名称计数不再增长。启用
monitor/selector、启动 worker 或处理积压均不属于首次发布。

## 回滚与失败边界

- 无迁移、无业务数据写入，不需要数据库恢复；
- 候选 migration graph 必须为零待应用；否则在 web 启动前停止并回到独立迁移规划；
- 回滚代码前先停 Beat，因为旧代码会恢复无条件投递；
- `prepare` 在构建前记录旧 `umanewsbot:prod` image ID 并建立本窗口 rollback tag；
- 候选 web/worker 不健康时用该 tag 恢复 web/普通 worker；
- 回滚后不重新启动 Beat，除非有替代止血或恢复本 P0；
- 保持所有 race-live flags 关闭和 worker 停止；
- 现有队列不删除、不重放、不解释为成功；
- healthz 恢复不等于队列、任务或告警恢复；
- 发布失败按 evidence-only 规则记录失败与实际回滚，不得标记为成功。

## 后续 change

- P1：monitor/alert 独立运行所需的 durable dispatch admission、单轮硬上限、broker 发布失败
  CAS 释放、租约恢复，以及 race-live 队列高水位背压；
- P2：生产 `dispatch_task()` Broker 故障时 fail closed；
- P3：新闻翻译/AI 编辑原子领取和版本 CAS；
- 独立 operations：积压 manifest、备份、精确处理与 worker 恢复。

这些后续工作不得在 P0 reviewer finding 修复中顺手加入。
