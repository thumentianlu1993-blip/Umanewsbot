# Lifecycle shadow 观察加固规格

## 1. 背景与根因

阶段 A 已在生产以 `RACE_EVENT_LIFECYCLE_ENABLED=true`、
`RACE_EVENT_LIFECYCLE_MODE=shadow` 纳管 16 场赛事。生产曾出现两个独立问题：

1. 隔离 release 的 Beat 为 `true/shadow`，但旧 `/opt/umanewsbot` Compose 重建了
   `web/worker`，使其变为 `false/off`。scanner 看似正常调度，worker 却按关闭态静默退出，
   直到人工同时核对三个容器才发现配置漂移。
2. 成功创建 proposal 的 `shadow_proposed` 没有按成功结果记录，导致
   `consecutive_failures` 增加，错误地把正常 shadow 观察显示成连续失败。

本 change 只加固 shadow 观察与部署合同，不改变赛事生命周期状态机。

## 2. 目标

- 成功新建 shadow proposal 时更新 `last_success_at` 并把
  `consecutive_failures` 归零，不产生虚假失败。
- 幂等命中既有 proposal 时仍视为成功处理，不增加或保留过时的连续失败。
- scanner 派发时携带自身观察到的 lifecycle 运行配置；worker 实际配置不一致时以明确、
  可检索的结构化错误暴露，而不是仅返回普通关闭态结果。
- 提供只读的宿主机全量容器 census，精确核对 `web/worker/beat` 的运行状态、Compose
  project/working directory、不可变 image ID、release commit 和 lifecycle flags。
- 提供共享锁保护的专用 lifecycle mode 切换入口，使 active release 与 canonical state
  两份 `.env` 的切换可恢复，并固定 Beat 最后启动。
- 用自动化合同保证仓库内通过 Compose wrapper 发起的 one-off `run` 必须带
  `--no-deps`；生产 one-off 继续受共享部署锁约束。
- 在不启用 enforce、不启动 race-live、不改公开状态的前提下，完成关闭态部署和第二轮
  真实 shadow 观察准备。

## 3. 非目标

- 不新增或修改 `RaceEvent.status` 枚举、transition 去重键或状态推进时间规则。
- 不新增 migration、模型、Beat 频率、Celery queue、provider、赛果抓取或新闻门禁。
- 不自动纳管更多赛事，不修改现有 16 场 control/manifest。
- 不处理 `default=2` 或 `race_live=7543` 的既有积压，不启动 race-live worker。
- 不把 shadow proposal 公开，不在本 change 中启用 enforce。
- 不试图阻止拥有 Docker 权限的操作者直接绕过仓库脚本执行原生 Docker 命令；该边界由
  运维授权和 runbook 管理，但任何这种绕过都不属于受支持路径。

## 4. 功能要求

### 4.1 Shadow 成功语义

- 创建 proposal 成功后：
  - `last_attempt_at=now`；
  - `last_success_at=now`；
  - `last_result_code=shadow_proposed`；
  - `last_error=""`；
  - `consecutive_failures=0`；
  - claim 正常释放；
  - `RaceEvent.status` 不变。
- proposal dedupe 命中后按幂等成功记录，`last_result_code=proposal_duplicate`，失败计数归零，
  不新增 transition。
- `decision_error` 等真实错误仍增加失败计数并按现有指数退避，不得因本 change 被弱化。

### 4.2 配置漂移可观测性

- scanner 向单赛事 task 传递期望的 `enabled=true` 与全局 mode。
- worker 在任何 lifecycle 数据写入前比较期望值和自身实际 settings。
- 不一致时：
  - task 返回 `processed=false` 和固定 reason `lifecycle_runtime_config_mismatch`；
  - 记录包含 event ID、期望 enabled/mode、实际 enabled/mode 的 error 日志；
  - 不修改 event、control 或 transition；
  - 不调用 lifecycle decision/apply；
  - 既有 claim 由 TTL 自然释放，避免在关闭态写 control。
- 一致且为关闭态时继续保持原有零写关闭语义。

### 4.3 宿主机只读一致性检查

新增只读脚本，生产模式下以下输入全部必填：

- allowlisted `COMPOSE_FILE`；
- `EXPECTED_LIFECYCLE_ENABLED=true|false`；
- `EXPECTED_LIFECYCLE_MODE=off|shadow|enforce`；
- `EXPECTED_COMPOSE_PROJECT`；
- `EXPECTED_RELEASE_DIR`；
- `EXPECTED_IMAGE_ID`；
- `EXPECTED_RELEASE_COMMIT`（40 位小写 OID）。
- `EXPECTED_BEAT_STATE=running|stopped`。

脚本先使用宿主级 `docker ps` 按 Compose service/project/one-off labels 对所有运行容器做
census，而不是只查询当前 wrapper/project。随后对 `web/worker/beat` 逐一 fail closed：

- web/worker 必须各有一个 running 容器；`EXPECTED_BEAT_STATE=running` 时 Beat 同样必须精确
  一个 running 容器；`stopped` 时宿主不得存在 running Beat，且 expected project 的停止容器
  只用于身份检查，不要求其旧环境已更新；
- 每个 service 必须只有一个非 one-off 常驻实例；任何 project 下存在第二个同类常驻实例或
  运行中的同类 one-off 均失败；
- project label 必须等于 `EXPECTED_COMPOSE_PROJECT`；
- 三者 image ID 必须等于 `EXPECTED_IMAGE_ID`；image 的
  `org.opencontainers.image.revision` 必须等于 `EXPECTED_RELEASE_COMMIT`；
- 三者 `com.docker.compose.project.working_dir` 必须等于 `EXPECTED_RELEASE_DIR`；
- running 服务的 lifecycle enabled/mode 必须与期望值精确一致；缺失、重复、未知值均失败。

脚本不得启动、停止、重建容器或写数据库。

### 4.4 专用 mode 切换入口

- 新增 `deploy/switch_lifecycle_mode.sh`，唯一支持的生产切换为 `false/off` 与
  `true/shadow`；本 change 不允许 `enforce`。
- 必须显式传入并 allowlist 校验：canonical env `/opt/umanewsbot/.env`、active release env、
  Compose file/project、release directory、image ID、release commit 和目标 mode。
- 使用新增共享锁 action `lifecycle-mode-switch`；锁竞争在任何 Compose 或文件写入前失败。
- 两份 env 必须是非 symlink、当前用户拥有、mode `0600` 的 regular file；每个 lifecycle key
  必须精确出现一次。不得打印其他环境值。
- 固定顺序：取得锁 → 停 Beat → 创建同目录 mode-600 备份和临时文件 → 分别原子替换并逐文件
  复核 → 强制重建 web/worker → 在 Beat 停止形态核验 runtime → 强制重建并启动 Beat → 全量
  一致性核验。
- 切往 `true/shadow` 前，两份文件和 running web/worker/Beat 必须已精确为 `false/off`。任一步
  失败时不得保留或恢复成 shadow：先停 Beat，把两份文件收敛为原 `false/off`，再强制重建
  web/worker 并以 Beat-stopped census 验证。
- 切往 `false/off` 失败时不得把原 `true/shadow` 备份写回生效配置；恢复器继续把两份文件和
  web/worker 收敛到 `false/off`，Beat 保持停止。
- 若上述安全收敛自身失败，必须尽力停止 worker 和 Beat、保留部署锁、备份和证据并非零退出，
  由人工接管；不得启动 Beat 或宣称回滚完成。
- 成功后保留带时间戳的两份备份，释放锁；切换入口不运行 scanner、不修改 control/event。

### 4.5 One-off Compose 合同

- `deploy/docker/compose-wrapper.sh ... run` 缺少 `--no-deps` 时必须在调用 Docker Compose
  前失败。
- wrapper 只接受当前仓库需要的 canonical grammar：识别 allowlisted Compose global options 后，
  `run` 必须以精确 `run --rm --no-deps` 开头，再解析 allowlisted、可带值的 run options，最后
  得到唯一 service。`--no-deps` 出现在 service 后的 command argv 不算。
- 在子命令前出现的任何 `-` token必须命中 global allowlist；未知 option、缺值、歧义 `--`
  一律 fail closed。只有 canonical global grammar 内识别出的非 `run` 子命令才原样传递。
- `-f FILE`、`--file FILE`、`--file=FILE` 和 Release B 的多个 `-e VALUE` 必须支持；未知或
  歧义的 option 在 `run` 路径 fail closed。非 `run` 命令保持原样。
- 现有 release task 与 P0 closed admission 的生产 one-off 继续在共享部署锁内运行。
- 仓库测试扫描受支持的部署 shell 入口，防止新增不带 `--no-deps` 的 wrapper one-off。
- `exec/config/ps` 等非 `run` Compose 命令在 canonical global grammar 内行为不变。

## 5. 验收标准

- 目标自动化测试真实 RED 后转 GREEN。
- 既有 lifecycle、enrollment、单一 migration owner、P0 deployment contract 回归通过。
- `sh -n`、Django check、migration drift、Compose config 和 `git diff --check` 通过。
- 关闭态部署后 `web/worker/beat=false/off`，scanner 零 claim/dispatch。
- 经独立授权恢复 `true/shadow` 后，一致性检查通过；无需手工 scanner，至少覆盖日本和英国
  的 2–4 场，在 T 与 T+30 观察到预期 proposal。
- 整个 shadow 观察中 `applied=0`、公开状态不变、active claim 最终为 0、成功 proposal 的
  `consecutive_failures=0`。

## 6. 发布门禁

实现完成并通过独立代码 review 后仍须取得当前 fingerprint 的发布授权。发布分开为：

1. `false/off` 代码部署与运行态一致性验收；
2. 单独授权恢复现有 16 场 `true/shadow`；
3. 观察通过后再为小范围 enforce 建立独立 change 和授权。
