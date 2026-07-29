# Celery 赛事实时任务 P0 关闭态投递止血任务

## 测试

- [x] (integration) 测试 subagent 新增纯 schedule 构造合同，取得“关闭态仍注册”的真实
  RED。
- [x] (integration) 测试 subagent 新增四种开关组合、每分钟 schedule 和其他 entry 不漂移
  合同，分别保存 RED。
- [x] (integration) 测试 subagent 新增 selector
  `queue=celery/expires=55`、monitor `queue=race_live/expires=55` 合同，取得真实 RED。
- [x] (integration) 测试 subagent 冻结 monitor/delivery/poll 的既有 race-live 路由和显式
  派发，确认这些回归测试在实现前已通过。
- [x] (operations) 测试 subagent 新增
  `stable.test_race_live_p0_deployment_contract`，先取得专用脚本不存在的真实 RED。
- [x] (operations) 测试 subagent 使用 fake command 逐项取得关闭态 no-go、资源 no-go、
  pre-stop 不改变 Beat 状态、stop/drain/build 顺序、post-stop 失败验证 Beat 停止、prepare
  不启动 Beat、候选验证失败不启动 Beat、start-beat 条件启动和失败 trap 不启动 Beat 的
  真实 RED。
- [x] (operations) 测试 subagent 取得“待应用 migration 非零”和“migration 状态不可读”
  都在候选 web 启动前失败的 RED，并断言脚本本身不调用实际 migrate。
- [x] (integration) 每个 RED 单独保存命令、退出状态、失败断言和“目标能力缺失”原因。

## 实现

- [x] (integration) 实现 race-live Beat entry 纯构造函数，按两个开关独立返回 entry。
- [x] (integration) 把纯构造结果合并进现有 `CELERY_BEAT_SCHEDULE`，不改其他 schedule。
- [x] (integration) selector 设置 `queue=celery/expires=55`，monitor 设置
  `queue=race_live/expires=55`。
- [x] (integration) 不修改 `server/stable/tasks.py`，保留 monitor/delivery/poll 既有
  race-live 路由、task body 关闭态和 enabled-regions 防御。
- [x] (operations) 实现 `deploy/deploy_race_live_p0_closed.sh prepare`：精确关闭态门禁、
  OOM/磁盘/内存/swap 量化门禁、先停 Beat、drain/停 worker、rollback image tag、受控构建、
  migration graph 零待应用双重断言、只启动候选 web/普通 worker/nginx、候选 schedule
  验证，退出时 Beat 保持停止。
- [x] (operations) prepare 使用 `PRE_STOP_PREFLIGHT -> BEAT_STOPPED -> CANDIDATE_READY`
  状态机；pre-stop 失败不改变原服务并准确报告，post-stop 失败验证 Beat 未运行。
- [x] (operations) P0 脚本不直接执行 `migrate --noinput`；只有零待应用断言通过后才启动
  候选 web，使现有 `start-web.sh` 的 migrate 调用只能是 schema no-op。
- [x] (operations) 实现 `deploy/deploy_race_live_p0_closed.sh start-beat`：重新验证关闭态、
  候选 schedule、web/worker 健康和 race-live worker 停止后，才单独启动 Beat。
- [x] (operations) 失败恢复仅允许恢复旧 web/普通 worker，任何失败路径不自动启动 Beat。
- [x] (operations) 修复首次 review 的普通 worker 部分停止边界：stop 非零但最终已停止时，
  先记录 worker 已停并进入失败恢复，恢复普通 worker且保持 Beat 停止。
- [x] (operations) 使用显式 Compose 状态分类，拒绝把
  `restarting/paused/unknown` 当作普通 worker 或 race-live worker 已停止。
- [x] (operations) 从普通 worker PID 1 参数验证唯一精确
  `--queues=celery`，拒绝近似、多队列和重复 queue 参数。
- [x] (operations) start-beat 启动后连续执行五轮关闭态后验；任一轮健康、镜像、状态、
  队列/task 计数或 Beat 日志异常都立即停止并复核 Beat。
- [x] (operations) 按同一 reviewer 新增 P1 的真实 RED/GREEN 最小修复 P0 脚本：取消
  nginx pull，不改变当前本地 nginx image；仍以该 image `--force-recreate nginx` 并
  验证 healthz。

## 验证

- [x] (integration) 逐个 RED 转 GREEN，并执行局部 REFACTOR。
- [x] (integration) 在新增 P1 修复后的当前候选上复跑
  `stable.test_race_live_sla_monitor`、`RaceLiveCeleryIsolationTests`、
  `RaceLiveWorkerDeploymentContractTests` 和
  `stable.test_race_live_p0_deployment_contract`；主代理实跑
  `63/63 / 54.863s / exit 0`。
- [x] (operations) 新增 P1 修复后的部署合同为 `32/32`；测试使用 fake command，未真实
  调用 Docker/Redis/网络；该集合已包含在主代理当前候选 `63/63` 中。
- [x] (integration) 运行完整 `stable` 并与同 HEAD 干净基线比较。候选为
  `3830 tests / 216.643s / 26 failures / 148 errors / 72 skipped / exit 1`；基线
  `HEAD=78719a467a2eceb57572b484a906cb78761badf8`，结果为
  `3790 tests / 167.124s / 26 failures / 148 errors / 72 skipped / exit 1`。原始唯一
  headings 均 `174`、规范化失败方法均 `153`，两种口径的双向差集均为 `0`。此项表示
  “已运行且与基线同失败集”，不是全绿。
- [x] (application) 运行 Django check 和迁移漂移检查。
- [x] (operations) 运行 `git diff --check`，确认无 model、migration、Compose、worker shell
  或 `.env.example` 变化。
- [x] (operations) 回写 `docs/current_state.md`、`docs/decisions.md`、
  `docs/deploy_runbook.md` 和 `docs/project_status.md` 的本地实现事实与未部署边界。
- [x] (operations) 新增 `full_stable_failure_baseline.txt`，逐行保存 `153` 个规范化失败方法；
  原始巨大 subtest repr 只记录 `174` 条计数和
  `a214e6a1ac4ff5cdfe0c0f2a0670525d3ed30bf41a191b18cbcaa85d9acd7040`，不复制正文。

新增 P1 修复后的当前候选聚焦为 `63/63 / 54.863s / exit 0`，其中部署合同 `32/32`。
Django check 为 exit `0`；`makemigrations --check --dry-run` 为
`No changes detected`；`sh -n` 与 `git diff --check` 均为 exit `0`；脚本静态核对确认无
nginx pull、仍有 nginx recreate/healthz。以上均不代表代码 review 通过。

## Review

- [x] (integration) 未参与实现的 reviewer subagent 在首次代码审核中执行
  `codex review -c 'sandbox_mode="read-only"' --uncommitted`。
- [x] (operations) 首次 code review 提出的五项 finding 已完成实现与合同补强：普通 worker
  部分停止恢复、模糊状态拒绝、PID 1 唯一精确 queue、start-beat 五轮持续后验与异常停
  Beat、完整 suite 同 HEAD 基线对照。
- [x] (integration) 同一 reviewer 限定复审 session
  `019faecf-f5fe-7900-be8d-95998bcb6b42` 已关闭原五项 finding，但因 `pull nginx`
  改变可变镜像且没有 nginx 镜像级回滚新增 P1，verdict 为 `REVISE`。
- [x] (operations) 新增 P1 已按真实 RED/GREEN 修复并复跑聚焦与静态门禁。
- [ ] (integration) 回到同一 reviewer session 再次限定复审新增 P1 修复和直接触及路径。
- [ ] (operations) 复审时按工作流保存审核前后完整 fingerprint、内层只读启动头、命令退出
  状态和 findings。
- [ ] (operations) 最新成功 review 后冻结 scope、approved parent 和
  `content_manifest_sha256`，停止等待发布授权。

## 发布

- [ ] (operations) 仅在最新成功 review 后取得用户针对当前 fingerprint 的明确发布授权。
- [ ] (operations) 授权后、staging 前重算 fingerprint，并通过 index transition。
- [ ] (operations) 经授权后完成 commit、push、PR/merge；不得把实现授权当发布授权。
- [ ] (operations) 部署前重新只读核对生产 SHA、flags、worker 队列、active/reserved、
  队列长度、task 构成、待应用 migration 数和 OOM/资源状态。
- [ ] (operations) 首次发布唯一使用
  `./deploy/deploy_race_live_p0_closed.sh prepare`；不得原样运行 `deploy_lowcost.sh`。
- [ ] (operations) 保存 prepare 成功且 Beat 仍停止的候选证据后，才运行
  `./deploy/deploy_race_live_p0_closed.sh start-beat`。
- [ ] (operations) 启动 Beat 后观察至少 5 分钟，确认不再新增两个目标周期 task。
- [ ] (operations) 不启用 scheduler/monitor/runner，不启动 race-live worker，不处理历史
  积压；这些操作另行规划和授权。
- [ ] (operations) 按 evidence-only 规则回写真实发布结果，并复用同一代码 reviewer 会话
  审核证据 patch。
