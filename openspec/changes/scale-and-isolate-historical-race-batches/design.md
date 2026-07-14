## Context

生产正式总账包含 30917 个 1998-2026 年度目标；batch001-batch005 已导入 1291 场，仍有 29626 个 pending。当前标准批次由 `build_historical_race_band_batch` 选择目标，`STANDARD_REGION_BATCH_LIMIT=50` 同时约束选择、artifact 写入和后续验证；每批再通过若干人工执行的 `docker run --rm` 完成抓取、日期、来源、重打包和最终导入。

这种方式已经证明数据门禁有效，但长任务依赖当前终端和人工协调新闻 worker/beat。普通部署脚本还会对主 Compose project 执行 `up -d --remove-orphans`，若把 runner 直接追加到同一 project，会造成普通部署误停 runner；若继续给一次性容器完整 `.env` 和共享网络，则无法从权限层保证抓取阶段不写业务表、落库阶段不访问公网。

本变更服务于历史赛事运维人员和生产协调人员。它不改变正式总账身份、来源权威、待审 gap、详情 importer 或前台公开规则。

## Goals / Non-Goals

**Goals:**

- batch006 起支持单地区最多 250 场，并让选择、验证和 artifact 明确记录同一个批准上限。
- 用独立 runner 容器执行长周期历史阶段，容器或会话中断后能从已验证 checkpoint 恢复。
- 同时提供数据库租约和 runtime 文件锁，阻止两个 runner 或旧进程并发处理同一生产账本。
- 从网络、数据库角色和应用门禁三层隔离 crawl 与 apply 权限。
- 使普通 web/worker/beat 部署与 runner 生命周期解耦，并为迁移提供可证明的安全暂停门禁。
- 保持所有历史赛事为 draft，继续累计非阻断歧义，直到 1998+ 总账全部收集后统一审核。

**Non-Goals:**

- 不把历史批次加入 Celery Beat，不建设无人值守无限循环。
- 不在本变更中修改赛事身份、来源优先级、100 场地区领先护栏或永久不可得审批规则。
- 不自动批准 selection、详情来源、字段候选或最终导入候选。
- 不让 runner 管理或重建生产 DB、Redis、Nginx、web、worker、beat 或共享网络。
- 不开启历史赛事前台展示、常驻网络开关或常驻写入开关。

## Decisions

### 1. 标准批次上限改为单一显式参数，batch006 默认 250

将标准最大值改为 `250`，管理命令默认值引用服务常量，不再重复裸数字。`write_band_batch_artifact` 必须接收实际 `approved_region_limit`，重新执行相同校验，并把它写入 selection summary、manifest 和命令结果。显式传入 `--region-limit 50` 仍合法，用于重放旧规则或小批验证；旧 batch001-batch005 artifact 不重写。

100 场地区领先护栏继续生效，只比较本批后仍有未排除可抓目标的地区。选择器不会为了凑满 250 静默跨年代带、复用旧 gap 或降低应到分母。

替代方案是只修改命令默认值；这会让 artifact 二次校验仍使用旧常量或无法证明实际口径，因此拒绝。

### 2. runner 使用 Django 控制账本加 runtime 文件锁

新增 `HistoricalBatchRun`、单例式 `HistoricalBatchLock` 和 append-only `HistoricalBatchRunEvent`：run 保存 batch id、phase、固定镜像 identity、plan/manifest SHA、artifact 根目录、状态、checkpoint、心跳、暂停请求和错误；lock 使用唯一 key、owner token hash、lease expiry 和 heartbeat；event 保存 step、暂停、恢复、失败、接管等有界审计事件。获取/续租/释放均在 `transaction.atomic()` 中通过 `select_for_update()` 完成。

同一 runner 还必须在 artifact 根目录持有 `fcntl.flock` 文件锁。数据库租约阻止跨主机并发，文件锁阻止同一 runtime 挂载上的重复进程；两者任一不可得都 fail closed。默认每 30 秒心跳，租约 180 秒；参数可在测试中缩短，但生产不能通过环境变量无限延长。

替代方案是只使用 PostgreSQL advisory lock。它依赖单条长连接，连接重置时缺少可审计租约和失联恢复信息；只用文件锁又不能覆盖其他主机，因此采用双锁。

### 3. runner plan 只允许结构化 argv 和批准命令

新增 `run_historical_batch_stage` 管理命令读取版本化 runner plan。每个 step 使用参数数组并以 `subprocess` 的 `shell=False` 执行，禁止 `sh -c`、重定向和任意 shell 文本。plan 必须声明 phase、batch id、输入文件身份、期望输出、命令类型和固定镜像 identity。

命令类型限定为：

- `management`：仓库中显式 allowlist 的历史管理命令；
- `python_tool`：解析后仍位于镜像内只读 `/app/runtime/tools` 的已跟踪工具；
- `verify`：只读校验脚本或管理命令。

apply phase 的 allowlist 只包含既有受控写入命令，且每个命令必须带 approval/expected SHA。runner 不替代原有 importer 门禁。

宿主 artifact 不再挂载到 `/app/runtime`，而是只把批准批次目录挂到 `/app/historical-runtime`。这样宿主文件不能遮住镜像内 `/app/runtime/tools`；启动时还必须用镜像内生成的 tool manifest 校验实际脚本 SHA。runner plan 本身位于可写 artifact 挂载，因此注册 run 时必须额外提供并保存 expected plan SHA，后续只按该 SHA 读取。

替代方案是让 plan 保存整段 shell；这会扩大命令注入和误操作面，也无法可靠分析权限，因此拒绝。

### 4. checkpoint 绑定输入、输出和镜像，恢复不重做已确认步骤

每个 step 完成后，runner 记录 argv 指纹、开始/结束时间、退出码、最多 8 KiB 且已脱敏的 stdout/stderr 摘要、输入 SHA 和输出文件身份；完整日志只写批次目录。runtime `runner-state.json` 使用同目录临时文件、flush、`fsync` 和原子 rename，再更新数据库 checkpoint。恢复时两份状态必须指向同一 run、phase、镜像和 plan SHA，且所有已完成输出重新计算 SHA 后一致，才可跳过。

任何输入漂移、输出丢失、镜像 revision 变化或数据库/runtime checkpoint 分叉都会将 run 标记为 blocked，要求新 run 或显式审核恢复，不自动重抓或重写。owner token 原文只保存在 artifact 目录之外的 `/opt/umanewsbot/runtime/historical_runner_secrets/<run_id>.token`，权限 `0600`，并以 Docker secret 风格只读挂载到 `/run/secrets/historical-owner-token`；数据库和 artifact 只保存 SHA-256，状态和日志只显示短前缀。失败 step 可以在租约失效后由同一 run/token 恢复；已经开始但未提交 checkpoint 的 apply step 必须先依赖 importer 的事务幂等和生产核验，不能盲目跳过。

runner 为每个数据库连接设置 `application_name=umanews-historical-runner:<run_id>:<phase>`。父进程收到退出信号时先终止并等待整个子进程组，再更新失败/暂停状态和释放租约，禁止在子命令仍运行时提前释放锁。

### 5. crawl 与 apply 使用不同网络和数据库角色

runner 由专用原生 Docker 启动脚本创建，不复用普通 `.env`：

- crawl：连接专用 egress 网络和 runner DB 控制网络，使用只能读写 `HistoricalBatchRun/HistoricalBatchLock/HistoricalBatchRunEvent` 的 PostgreSQL 角色；应用设置为 `network=true / write=false`，该角色没有 RaceEvent、target、candidate 等业务表写权限。
- apply：只连接 `internal=true` 的 runner DB 网络，使用受控写入凭据；应用设置为 `network=false / write=true`，容器没有公网出口。

runner DB 网络只在一次性 provisioning 中创建，并把现有 DB 容器以 `db` alias 连接进去；不重建 DB，也不修改普通共享网络。crawl egress 网络不承载生产 DB alias。control role 只获得 runner 三张控制表及其序列的必要权限；apply 凭据继续使用既有 importer 所需权限，但只出现在 internal-only 容器。crawl/apply 都使用显式环境变量 allowlist，apply 环境不得携带翻译、OSS、OneBot 等外部 API 密钥。凭据文件必须位于服务器、权限 `0600`，不得写入仓库、artifact、日志或镜像。

替代方案是同一网络和同一 `.env` 仅靠布尔开关；这无法抵抗误命令或代码缺陷，因此不足以满足权限隔离。

### 6. runner 不属于普通 Compose project

新增 `deploy/historical_runner.sh` 和 provisioning/preflight 脚本，使用 `docker create/start/stop/network connect` 管理固定名称容器；镜像必须以完整 image ID 或不可变 digest 解析，并同时匹配 OCI revision label。脚本拒绝 `latest`、可变 tag、缺少 revision、把宿主目录挂到 `/app/runtime`、未将批准批次目录挂到 `/app/historical-runtime` 或资源限制缺失。

默认资源上限为 2 CPU、2 GiB memory、256 PIDs，并设置日志轮转。普通 `deploy.sh`、`deploy_lowcost.sh` 和 rollback 脚本改为只使用 `--no-deps` 更新 web/worker/beat/nginx，并在迁移前增加 runner preflight；它们不得 pull、start、stop、remove 或 recreate runner、DB、Redis 或任何网络。初次部署所需的 DB/Redis/network 建立移到名称明确、必须单独确认的 infrastructure bootstrap 脚本，不能由普通 deploy/rollback 隐式调用。runner 不属于普通 Compose project。

### 7. 迁移前必须请求暂停并等待安全状态

runner 在每次 step 前后和心跳循环中检查 `pause_requested_at`。crawl 可在当前外部请求/工具 step 结束后进入 paused；apply 只在当前数据库事务结束后进入 paused，绝不在事务中途强停。部署 preflight 在 migrate 前要求：没有 `applying` run、没有未过期可写租约、所有 pause 请求已经得到 `paused_at` 响应。

若超时，部署必须停止，不能杀 runner 后继续 migrate。只有租约过期、容器确实不存在、通过带 `application_name` 的 `pg_stat_activity` 证明没有活动历史连接/事务且 checkpoint 可验证时，运维人员才可执行带原因和审计记录的 stale takeover；生产 preflight 使用具备只读活动查询权限的运维连接，不把该权限授予 crawl control role。

### 8. 状态和日志同时面向机器与运维人员

runner 提供 `status --json`，至少显示 run id、batch id、phase、state、image identity、plan SHA、当前 step、checkpoint、heartbeat age、lease expiry、pause 状态和最近错误。stdout/stderr 保存到本批 runtime 目录并限制摘要进入数据库；敏感值统一脱敏。健康检查不会把“容器在运行”当成成功，心跳过期、锁分叉或 checkpoint 漂移均为失败。

## Risks / Trade-offs

- [250 场会增加单批抓取时间和 artifact 体积] -> 保留共享请求预算、资源限制和逐 step checkpoint；选择/抓取/写入仍可按地区或阶段拆分，不要求单容器完成所有网络来源。
- [租约在网络抖动时可能误判过期] -> 180 秒租约配 30 秒心跳，接管还需要容器不存在、无活动事务和 checkpoint 三重验证。
- [专用 PostgreSQL 角色和网络增加运维复杂度] -> provisioning 脚本幂等创建/校验，不持有销毁 DB/Redis 的命令；部署手册记录回收与审计步骤。
- [apply 容器不能访问公网会暴露既有命令的隐式网络依赖] -> apply 前在隔离网络做 dry-run；任何隐式请求都应失败并改为 crawl 阶段缓存 artifact，而不是放宽网络。
- [文件锁依赖共享 runtime 挂载] -> 数据库租约仍提供跨主机保护；runtime 未挂载或不可写时 runner 直接拒绝启动。
- [普通部署仍可能由人工直接执行危险 Docker 命令] -> 脚本 preflight 和运行手册明确禁止；runner 状态、网络和容器 identity 纳入部署验收。

## Migration Plan

1. 先提交模型、迁移、runner 服务/命令、批次上限、脚本、测试和 OpenSpec；从最新 main 构建可复现 AMD64 镜像。
2. 首次上线因 runner 表尚不存在，先执行一次性 host-only 初始门禁：确认没有 runner 容器、runner 网络、runner secrets 或同名数据库表；满足后才应用迁移。该 bypass 只能用于首次建表，任一 runner 痕迹存在即失败。后续部署全部使用数据库 preflight；迁移后确认新表为空、历史开关和 published 计数不变。
3. 幂等创建 runner 内部 DB 网络和 egress 网络，把现有 DB 容器连接到内部网络；创建最小权限 control role 和 0600 凭据文件。不得重建 DB/Redis/共享网络。
4. 用固定镜像启动 read-only smoke run：空/测试 plan、双锁、心跳、状态、暂停、恢复、资源和日志轮转全部通过，不写赛事数据。
5. 在隔离环境验证 crawl phase 无业务表写权限，apply phase 无公网出口；故意执行越权操作必须失败。
6. 演练普通 web/worker/beat 部署 preflight，证明 `--no-deps` 应用更新不处理 runner/DB/Redis/network；另行验证 infrastructure bootstrap 不会被普通部署调用，并演练迁移暂停与 stale takeover 门禁。
7. 生成 batch006 的每地区最多 250 场 selection artifact，审核 summary/manifest 口径后再进入实际抓取和分阶段落库。

回滚代码时先暂停且停止 runner，再回滚应用镜像。新表只保存控制账本，可保留；只有确认迁移本身损坏时才恢复部署前数据库备份。已生成 artifact 保留审计，禁止为了回滚删除 source cache 或改写总账状态。

## Open Questions

无。资源默认值、租约参数、网络拓扑和角色边界先按本设计实施；生产验收若证明资源不足，只能在保留硬上限和审计记录的前提下通过独立配置变更调整。
