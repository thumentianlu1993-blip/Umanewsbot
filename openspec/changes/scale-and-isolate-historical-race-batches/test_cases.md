# scale-and-isolate-historical-race-batches 测试用例

本文档依据已通过两轮 Full 工程评审的 proposal、design、delta specs 和 tasks 编写。当前阶段只锁定测试，不实现业务代码、不创建生产 runner、不触网、不写生产数据。

测试类型：

- `A`：SQLite 可执行的 Django 单元/集成测试。
- `P`：真实 PostgreSQL 并发、角色或事务测试。
- `S`：management command smoke。
- `H`：shell/部署脚本静态或隔离主机测试。
- `D`：Docker 网络、容器资源和生命周期测试。
- `O`：生产部署、权限、恢复和 batch006 验收。
- `C`：文档、OpenSpec、迁移和非目标边界检查。

## 0. 推荐测试落点与固定 fixture

实际测试模块：

- `server/stable/test_historical_race_batches.py`：250 上限、artifact 和地区护栏。
- `server/stable/test_historical_batch_runner_change.py`：run/lock/event 模型、租约、文件锁、plan、step、checkpoint、管理命令和部署脚本契约。
- `server/stable/test_historical_batch_runner_postgres.py`：真实 PostgreSQL 并发、角色、事务和 `application_name`。

固定 fixture：

- 五地区各 300 个 pending target，另含 imported、ready、not-held、not-due、permanent unavailable 和带 event 的 target。
- 一个地区仅余 80 个可抓目标、一个地区仅余 exclusion gap、一个地区已经抓空。
- 合法 crawl/apply/verify runner plan，各包含两个成功 step 和一个可注入失败 step。
- 合法 tool manifest、被篡改工具、越界 symlink、可写 artifact、只读 image tools。
- 活动、过期、暂停、分叉和接管后的 run/lock/event 记录。
- PostgreSQL `historical_runner_control`、完整 apply role 和无权限 role。

## 1. Requirement 覆盖关系

| 能力 | 主要测试 |
| --- | --- |
| batch006 单地区 250 与旧 50 兼容 | TC-BATCH-001 至 018 |
| runner 模型、迁移和审计 | TC-MODEL-001 至 015 |
| 双锁、租约、心跳和接管 | TC-LOCK-001 至 020 |
| 结构化 plan、allowlist 和工具身份 | TC-PLAN-001 至 019 |
| step、checkpoint、暂停和恢复 | TC-STATE-001 至 021 |
| crawl/apply 权限、网络隔离与资源预算 | TC-PERM-001 至 026 |
| Docker 与普通部署隔离 | TC-OPS-001 至 024 |
| 日志、状态、安全和公开边界 | TC-OBS-001 至 014 |
| 生产部署与 batch006 验收 | TC-PROD-001 至 019 |

## 2. batch006 地区上限与 artifact

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-BATCH-001 | 五地区各 300 个可抓 target | 不传 `--region-limit` 生成 batch006 | 每地区选择 250，target_count=1250 | A/S |
| TC-BATCH-002 | 同上 | 显式 `--region-limit 50` | 每地区 50；旧小批可重放 | A/S |
| TC-BATCH-003 | 同上 | 显式 1 和 249 | 分别按实际上限选择，均合法 | A |
| TC-BATCH-004 | 同上 | 显式 0、-1、251 | 写 artifact 前失败，目录不存在 | A/S |
| TC-BATCH-005 | 手工传入某地区 251 个 target | 写 artifact | fail closed，不静默截断 | A |
| TC-BATCH-006 | 选择按 250、writer 参数 50 | 写 artifact | 报批准上限/地区计数不一致 | A |
| TC-BATCH-007 | 选择按 50、writer 参数 250 | 写 artifact | 实际 count 合法，summary 明确 approved=250、selected=50 | A |
| TC-BATCH-008 | 合法 250 批次 | 检查 summary/manifest/命令 JSON | 三处均记录 `approved_region_limit=250` | A/S |
| TC-BATCH-009 | 合法显式 80 批次 | 检查三类产物 | 三处记录 80，不伪报 250 | A |
| TC-BATCH-010 | 某地区 prospective 领先仍未完成地区 101 | 生成批次 | 拒绝，保持 target 状态不变 | A |
| TC-BATCH-011 | prospective 领先恰为 100 | 生成批次 | 不因领先护栏拒绝 | A |
| TC-BATCH-012 | 低容量地区选择后抓空 | 生成批次 | 退出比较，其他地区可继续到 250 | A |
| TC-BATCH-013 | 地区只剩 exclusion gap | 生成批次 | 不冻结其他地区；gap 仍在 pending 分母 | A |
| TC-BATCH-014 | 只剩一个地区有可抓 target | 生成批次 | 无比较对象，不因领先护栏拒绝 | A |
| TC-BATCH-015 | 传入 batch002-batch005 exclusion snapshots | 生成 batch006 | limit 前去重排除，selection 与旧目标交集为 0 | A/S |
| TC-BATCH-016 | exclusion snapshot SHA/总账/身份漂移 | 生成批次 | fail closed，不写可审批 artifact | A |
| TC-BATCH-017 | 地区可抓量小于批准上限 | 生成批次 | 只选实际数量，remaining/eligible/accounted 数学一致 | A |
| TC-BATCH-018 | 旧 batch005 artifact 无新字段 | 读取/审计旧 artifact | 旧 artifact 保持不可变；新 reader 兼容或给出明确 legacy 口径 | A/C |

## 3. Runner 模型、迁移和审计事件

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-MODEL-001 | 空库 | 应用迁移 | 创建 Run/Lock/RunEvent 三表、约束与索引 | A/P |
| TC-MODEL-002 | 既有 30917 target 与 RaceEvent | 应用迁移 | 既有表行数、状态和 visibility 不变 | A/P |
| TC-MODEL-003 | 同 batch id/phase 已有 run | 创建不同 run id | 按设计允许历史记录并存，活动互斥交给 lock | A |
| TC-MODEL-004 | run id 已存在 | 重复创建 | 唯一约束拒绝 | A |
| TC-MODEL-005 | lock key 已存在 | 创建第二 lock 行 | 唯一约束拒绝 | A |
| TC-MODEL-006 | lock 指向 run | 删除 run | lock 按设计清空/保护，不出现悬挂 FK | A |
| TC-MODEL-007 | 合法状态流 | planned→running→paused→running→completed | 全部允许并记录事件 | A |
| TC-MODEL-008 | completed run | 尝试直接回 running | 服务拒绝非法状态转换 | A |
| TC-MODEL-009 | crawl run 声明 write=true | full_clean/服务创建 | 拒绝非法 phase 权限 | A |
| TC-MODEL-010 | apply run 声明 network=true | full_clean/服务创建 | 拒绝非法 phase 权限 | A |
| TC-MODEL-011 | owner token 原文 | 保存 lock | 数据库只存 64 位 SHA，不含原文 | A |
| TC-MODEL-012 | run 有 100 个事件 | 查询状态 | 使用索引/related 查询，无 N+1 | A |
| TC-MODEL-013 | event detail 超过规定大小 | 追加事件 | 拒绝或截断到有界脱敏摘要 | A |
| TC-MODEL-014 | SQLite 与 PostgreSQL | 迁移、回滚到前一 migration、再前进 | 两端均可执行；旧业务数据不变 | A/P |
| TC-MODEL-015 | 迁移完成 | `makemigrations --check --dry-run` | 无漂移 | C |

## 4. 数据库租约、文件锁、心跳和接管

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-LOCK-001 | 无活动锁 | 获取全局租约 | run 成为 owner，heartbeat/expiry 写入 | A/P |
| TC-LOCK-002 | 同 owner/token | 重复获取 | 幂等续租，不创建第二 owner | A/P |
| TC-LOCK-003 | 未过期 owner A | owner B 获取 | 失败并返回 owner 前缀/run/phase/expiry | A/P |
| TC-LOCK-004 | PostgreSQL 20 个并发事务 | 同时获取 | 恰有 1 成功，19 明确冲突 | P |
| TC-LOCK-005 | DB 租约成功、文件锁被占 | 启动 runner | 释放新租约并失败，零 step 执行 | A/P |
| TC-LOCK-006 | 文件锁成功、DB 租约被占 | 启动 runner | 释放文件锁并失败，零 step 执行 | A/P |
| TC-LOCK-007 | 两个不同 artifact 根目录 | 同时启动 | 全局 DB 锁仍阻止第二个 | P |
| TC-LOCK-008 | 同一 artifact 根目录、不同 DB | 同时启动 | 文件锁阻止第二个 | A |
| TC-LOCK-009 | active run | 连续三次 heartbeat | owner/token 不变，expiry 单调后移 | A/P |
| TC-LOCK-010 | fake clock 90 秒、每 30 秒 heartbeat | 检查 age | 最大 age 不超过 90 秒 | A |
| TC-LOCK-011 | heartbeat DB 暂时失败 | 进入下一 step | 不进入；状态明确 degraded/failed | A/P |
| TC-LOCK-012 | owner token 不匹配 | heartbeat/release | 拒绝，不影响真实 owner | A/P |
| TC-LOCK-013 | 租约过期但旧容器存在 | takeover | 拒绝 | A/S |
| TC-LOCK-014 | 租约过期、容器不存在、pg 活动仍在 | takeover | 拒绝并列出 application_name/pid | P/S |
| TC-LOCK-015 | 租约过期、无容器/事务、state 一致 | takeover | 成功，新 owner 和原因写事件 | P/S |
| TC-LOCK-016 | checkpoint 分叉 | takeover | 拒绝，即使租约过期 | A/P |
| TC-LOCK-017 | takeover 未给操作者或原因 | 执行命令 | 参数校验失败 | A/S |
| TC-LOCK-018 | 父进程收到 TERM、子进程仍运行 | 停止 | 先终止并 wait 整个进程组，再释放锁 | A/D |
| TC-LOCK-019 | 子进程忽略 TERM | 停止并超过 grace | 按设计 KILL 后 wait，记录失败，不提前释放 | A/D |
| TC-LOCK-020 | 正常完成 | 释放双锁 | lease 清空、文件锁释放、completed 事件存在 | A/P |

## 5. Runner plan、allowlist 与工具身份

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-PLAN-001 | 合法 schema/version | 注册 plan + expected SHA | 成功，数据库保存相同 SHA | A/S |
| TC-PLAN-002 | plan 改一个字节 | 启动 | expected SHA 不符，租约前失败 | A/S |
| TC-PLAN-003 | 缺 batch id/phase/image/steps | 校验 | 列出缺失字段 | A |
| TC-PLAN-004 | step command 为字符串 | 校验 | 拒绝，必须 argv 数组 | A |
| TC-PLAN-005 | argv 含 `sh -c` | 校验 | 拒绝 | A |
| TC-PLAN-006 | argv 含管道/重定向/命令替换语义 | 校验 | 拒绝或按普通参数安全传递，绝不经 shell 解释 | A |
| TC-PLAN-007 | 未知 management command | 校验 | allowlist 拒绝 | A |
| TC-PLAN-008 | crawl plan 含 importer apply | 校验 | phase allowlist 拒绝 | A |
| TC-PLAN-009 | apply 写命令缺 approval | 校验 | 拒绝 | A |
| TC-PLAN-010 | apply 写命令缺 expected SHA | 校验 | 拒绝 | A |
| TC-PLAN-011 | python tool 位于镜像 `/app/runtime/tools` | 校验/执行 | 路径和 tool manifest SHA 均匹配才允许 | A |
| TC-PLAN-012 | tool 是指向外部的 symlink | 校验 | realpath 越界，拒绝 | A |
| TC-PLAN-013 | 宿主挂载覆盖 `/app/runtime` | 启动脚本检查 | 拒绝创建容器 | H/D |
| TC-PLAN-014 | artifact 挂到 `/app/historical-runtime` | 启动 | 允许；image tools 保持只读可见 | D |
| TC-PLAN-015 | tool 内容与 manifest 不符 | 执行 | 拒绝并记录 tool SHA 差异 | A/D |
| TC-PLAN-016 | 输入路径越出批准 batch root | 校验 | 拒绝 path traversal/symlink escape | A |
| TC-PLAN-017 | 输出路径越出批准 batch root | 校验 | 拒绝，未创建外部文件 | A |
| TC-PLAN-018 | 重复 step id 或循环依赖 | 校验 | 拒绝并指出 step | A |
| TC-PLAN-019 | 生产工具根中的非赛事/不消费预算脚本 | 校验匹配 SHA 的 crawl plan | 显式白名单拒绝，不能借镜像内任意工具绕过预算 | A |
| TC-PLAN-020 | 生产 artifact plan 把 `tool_root` 指向 artifact 内目录 | 校验匹配 SHA 的 crawl plan | 在 step 校验前拒绝，生产只能使用镜像内不可变工具根 | A |
| TC-PLAN-021 | plan 工具根与运行 settings 不一致 | 通过正式 stage 命令启动 | 在创建 `HistoricalBatchRun` 前拒绝，不留下无效控制记录 | A |

## 6. Step、checkpoint、暂停和恢复

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-STATE-001 | 两个合法 step | 执行 | 按顺序运行，每步写 event/checkpoint | A/S |
| TC-STATE-002 | step1 退出非零 | 执行 | step2 不运行，run failed，日志路径可见 | A/S |
| TC-STATE-003 | step 输出缺失 | 命令退出 0 | 仍判失败，不写成功 checkpoint | A |
| TC-STATE-004 | step 输出 SHA 与声明不符 | 验证 | 失败并记录差异 | A |
| TC-STATE-005 | state 写临时文件后掉电 | 恢复 | 原 state 保持完整，不读取半文件 | A |
| TC-STATE-006 | fsync 失败 | 写 checkpoint | 不更新 DB completed step，run failed | A |
| TC-STATE-007 | 文件 state 成功、DB 更新失败 | 恢复 | 检出分叉并 blocked | A/P |
| TC-STATE-008 | DB 更新成功、文件 rename 失败 | 恢复 | 检出分叉并 blocked | A/P |
| TC-STATE-009 | step1 已完成且输出未变 | resume | 跳过 step1，只运行 step2 | A/S |
| TC-STATE-010 | step1 输出缺失 | resume | blocked，不自动重做 | A/S |
| TC-STATE-011 | step1 输出改一个字节 | resume | blocked，报告旧/新 SHA | A/S |
| TC-STATE-012 | image revision 变化 | resume | blocked，要求新 run/审核 | A/S |
| TC-STATE-013 | plan SHA 变化 | resume | blocked | A/S |
| TC-STATE-014 | owner token 文件 mode 0644 | 启动/resume | 拒绝；要求 0600 | H/S |
| TC-STATE-015 | token 被放入 artifact | 启动检查 | 拒绝，artifact 中不出现原文 | A/H |
| TC-STATE-016 | crawl step 期间请求 pause | step 安全结束 | 转 paused，后续 step 不运行 | A/S |
| TC-STATE-017 | apply 事务期间请求 pause | 等待事务 | 事务 commit/rollback 后 paused，不中途杀 | P/S |
| TC-STATE-018 | paused run | 合法 resume | 重验双锁/state 后继续 | A/S |
| TC-STATE-019 | completed run | resume | 幂等返回 completed，不重复 step | A/S |
| TC-STATE-020 | 未 checkpoint 的 apply step 进程丢失 | resume | blocked，要求 importer/DB 核验，不盲目跳过或重写 | P/S |
| TC-STATE-021 | 首个 crawl step 写入请求账本后失败 | 删除账本并 resume | 失败收尾 checkpoint 保留已消费身份；删除后 blocked，不重置额度 | A/S |

## 7. Crawl/Apply 数据库角色与网络隔离

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-PERM-001 | control role | CRUD Run/Lock/Event | 仅必要操作成功 | P |
| TC-PERM-002 | control role | SELECT/INSERT HistoricalRaceEventTarget | 权限拒绝 | P |
| TC-PERM-003 | control role | INSERT/UPDATE RaceEvent | 权限拒绝 | P |
| TC-PERM-004 | control role | INSERT runner/result/candidate | 权限拒绝 | P |
| TC-PERM-005 | control role | 访问其他新闻/术语表 | 权限拒绝 | P |
| TC-PERM-006 | crawl container | 访问外部 fixture HTTP | 成功并有请求预算 | D |
| TC-PERM-007 | crawl container | 连接 control DB alias | 成功，只能写控制表 | D/P |
| TC-PERM-008 | crawl container | 尝试使用业务写 ORM | PostgreSQL 拒绝，step failed | D/P |
| TC-PERM-009 | apply internal network | 连接生产 DB alias | 成功 | D/P |
| TC-PERM-010 | apply internal network | curl 公网 IP/域名 | 均失败 | D |
| TC-PERM-011 | apply env | 检查环境变量名 | 不含翻译/OSS/OneBot/SMTP/API keys | D/H |
| TC-PERM-012 | crawl env | 检查环境变量名 | 不含 full apply DB credential 或外部无关密钥 | D/H |
| TC-PERM-013 | phase 同时 network/write true | 启动 | 容器创建前失败 | A/H |
| TC-PERM-014 | crawl write=true 或 apply network=true | 启动 | fail closed | A/H |
| TC-PERM-015 | DB 容器连接 default+internal networks | 检查 | 不被重建，原网络不变，internal alias=db | D |
| TC-PERM-016 | crawl 同时连 egress+internal control 网络 | 尝试通过 DB 转发到 default | Docker 不路由，无法访问 default 其他服务 | D |
| TC-PERM-017 | 宿主预置无限/超限 `RACE_EVENT_CRAWL_*` | 执行 crawl `python_tool` 环境探针 | 子进程只看到 settings 批准值，不能继承无限/超限值 | A |
| TC-PERM-018 | 同一 crawl run 含多个网络 step | 检查子进程环境 | 全部共享 artifact 根目录中的同一请求账本和 cache manifest | A |
| TC-PERM-019 | 容器内 artifact 可用空间低于批准底线 | 执行 crawl runner | 取得租约和执行 step 前失败，零网络请求 | A |
| TC-PERM-020 | verify/apply runner | 执行普通 step | 不注入 crawl 网络环境，不改变既有 phase 权限 | A |
| TC-PERM-021 | 绕过宿主脚本直接使用异常 crawl settings | 执行 Django runner 服务 | 数值边界校验失败，零 step、零租约 | A |
| TC-PERM-022 | checkpoint 后请求账本/cache manifest 被修改或删除 | resume | checkpoint 漂移，run blocked，不执行后续 step | A |
| TC-PERM-023 | checkpoint 记录资源文件不存在，暂停期间被外部创建 | resume | 存在状态漂移，run blocked，不接受伪造账本 | A |
| TC-PERM-024 | 固定请求账本或 cache manifest 是 symlink/目录 | 启动 crawl | 租约和 step 前失败，不读取 artifact 外文件 | A |
| TC-PERM-025 | 升级前非终态 crawl checkpoint 缺少资源身份 | resume | blocked；旧 completed run 仍可幂等读取 | A |
| TC-PERM-026 | runner management step 嵌套 AdapterRunner | 子 policy 放宽值并指定自己的 run 目录 | 保留父账本/cache 路径，数值只收紧不放宽 | A |

## 8. Docker 生命周期与普通部署隔离

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-OPS-001 | image 只有可变 tag | runner start | 拒绝 | H |
| TC-OPS-002 | full image ID + matching revision | runner start | 允许 | H/D |
| TC-OPS-003 | image ID 与 revision 不匹配 | runner start | 拒绝 | H/D |
| TC-OPS-004 | 缺 CPU/memory/PID/log 限制 | runner start | 拒绝并列出缺项 | H |
| TC-OPS-005 | 合法启动 | inspect container | NanoCpus<=2、Memory<=2GiB、PidsLimit=256、日志轮转存在 | D |
| TC-OPS-006 | runner 已在执行 | 终端/SSH 断开 | detached runner 继续，heartbeat 更新 | D |
| TC-OPS-007 | provisioning 首次执行 | 检查 Docker | 只创建两个 runner 网络并 connect 既有 DB | H/D |
| TC-OPS-008 | provisioning 重跑 | 检查 IDs | 幂等，DB/container/network ID 不变 | H/D |
| TC-OPS-009 | DB 或 Redis 不存在 | 普通 deploy | fail closed，不自动 bootstrap | H |
| TC-OPS-010 | 显式 infrastructure bootstrap | 首次环境执行 | 创建所需基础设施；必须单独确认 | H/D |
| TC-OPS-011 | 普通 deploy | 静态扫描 argv | 只针对应用服务且使用 `--no-deps` | H |
| TC-OPS-012 | 普通 deploy 前后 runner 活跃 | 执行应用更新演练 | runner container ID/started_at/lock 不变 | D/O |
| TC-OPS-013 | 普通 deploy 前后 | 检查 DB/Redis/network IDs | 全部不变 | D/O |
| TC-OPS-014 | rollback 演练 | 检查 | 同样不处理 runner/DB/Redis/network | H/D |
| TC-OPS-015 | 首次 migration、无任何 runner 痕迹 | host-only preflight | 允许建表 | H/O |
| TC-OPS-016 | 首次 migration 发现容器/网络/secret/同名表任一 | preflight | 拒绝 bypass | H/O |
| TC-OPS-017 | 后续 migration、runner crawl 活跃 | preflight | 请求 pause，等待 paused 后放行 | D/O |
| TC-OPS-018 | 后续 migration、runner apply 活跃 | preflight | 等事务完成和 paused；期间不 migrate | P/D |
| TC-OPS-019 | pause 超时 | deploy | 整体停止，现有服务保持运行 | H/D |
| TC-OPS-020 | shell 文件 | `sh -n`/ShellCheck 契约 | 语法通过，无 `docker compose down`、volume/network 删除或 DB/Redis recreate | H/C |
| TC-OPS-021 | crawl env 请求预算为 0、251 或非整数 | 启动脚本校验 | 创建容器前失败；1 和 250 合法 | H/S |
| TC-OPS-022 | crawl env cache 为 0、超过 2 GiB 或非整数 | 启动脚本校验 | 创建容器前失败；1 和 2 GiB 合法 | H/S |
| TC-OPS-023 | crawl env 磁盘底线小于 5 GiB 或非整数 | 启动脚本校验 | 创建容器前失败；5 GiB 及以上合法 | H/S |
| TC-OPS-024 | artifact 文件系统实时可用空间低于 env 底线 | 启动 crawl | `docker create` 前失败，容器不存在 | H/S |

## 9. 可观测性、日志、安全和公开边界

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-OBS-001 | active run | `status --json` | 含 run/batch/phase/state/image/plan/current step/heartbeat/lease/pause/error | A/S |
| TC-OBS-002 | 无 run | status | 稳定空状态和零退出码 | A/S |
| TC-OBS-003 | heartbeat 过期 | status | 明确 stale/degraded，不显示 healthy | A/S |
| TC-OBS-004 | DB/file checkpoint 分叉 | status | 明确 blocked 与差异 | A/S |
| TC-OBS-005 | stdout 20 KiB | 完成 step | DB 摘要<=8 KiB，完整日志在文件 | A |
| TC-OBS-006 | stderr 20 KiB | step 失败 | 同上，错误尾部可读 | A |
| TC-OBS-007 | 日志含 DB/API/token 值 | 保存/查询 | 全部脱敏，原值全文搜索为 0 | A/H |
| TC-OBS-008 | owner token | status/event/artifact/log | 只出现短前缀/hash，无原文 | A/H |
| TC-OBS-009 | takeover | 查询 RunEvent | 操作者、原因、旧/新 owner、时间完整 | A |
| TC-OBS-010 | pause/resume/failure/completion | 查询 RunEvent | 每类事件 append-only 且顺序稳定 | A |
| TC-OBS-011 | runner crawl 完成 | 查询历史 RaceEvent | visibility 未变化，published 增量 0 | A/P |
| TC-OBS-012 | runner apply 完成 | 查询批次目标 | 只按批准 importer 更新，全部 draft | A/P |
| TC-OBS-013 | 常驻 web/worker/beat | 检查环境 | 历史 enabled/network 继续 false | O |
| TC-OBS-014 | 运行结束 | 检查 Celery/Beat | 无新增周期任务、无历史 Celery 队列 | A/O |

## 10. 生产部署、隔离 smoke 与 batch006 门禁

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-PROD-001 | 最新 main 干净 tree | 双构建 AMD64 镜像 | image ID、revision、tree、source SHA 可复现 | O |
| TC-PROD-002 | 部署前 | 生成 DB/env 备份 | 文件完整、SHA 记录、restore list/gzip 校验通过 | O |
| TC-PROD-003 | 旧生产无 runner 表 | 执行首次 host-only preflight+migrate | 新表创建，旧业务计数不变 | O |
| TC-PROD-004 | migration 后未启动 runner | Django check/迁移漂移 | 全通过，控制表为空 | O |
| TC-PROD-005 | provisioning | 检查网络/角色/secret 权限 | 两网络正确、role 最小、文件 0600 | O |
| TC-PROD-006 | crawl smoke plan | detached 运行 | 双锁/心跳/status/log/checkpoint 全通过，业务表零写入 | O |
| TC-PROD-007 | crawl smoke | 故意写 RaceEvent | 权限拒绝且 run failed 可见 | O |
| TC-PROD-008 | apply smoke | 故意访问公网 | 网络拒绝，DB 仍可连接 | O |
| TC-PROD-009 | 两个 smoke runner | 并发启动 | 只有一个取得租约 | O |
| TC-PROD-010 | 中断 smoke 后 | resume | 已完成 step 不重复，后续继续 | O |
| TC-PROD-011 | active crawl smoke | 执行普通应用部署演练 | runner/container/DB/Redis/networks 不变 | O |
| TC-PROD-012 | active apply transaction | 请求部署 | migrate 被阻断直到安全暂停 | O |
| TC-PROD-013 | stale run + 旧容器存在 | takeover | 拒绝 | O |
| TC-PROD-014 | stale run + 无容器但 pg activity 存在 | takeover | 拒绝 | O |
| TC-PROD-015 | 满足接管四条件 | takeover/resume | 成功且审计完整 | O |
| TC-PROD-016 | batch006 正式总账与全部 exclusion snapshots | 生成 selection | 每地区<=250、无重复/重叠、summary 数学与护栏正确 | O |
| TC-PROD-017 | batch006 selection 通过审核 | 启动 crawl runner | 仅网络阶段，write=false，公开开关不变 | O |
| TC-PROD-018 | runner 部署验收结束 | 检查公网/新闻链路 | healthz、web/worker/beat、自然新闻窗口正常；历史 published=0 | O |
| TC-PROD-019 | 生产 artifact 文件系统 | 启动 batch006 crawl 前检查 | 可用空间至少 5 GiB，预算账本/cache manifest 路径和三项硬上限可见 | O |

## 11. 必跑验证矩阵

1. 先在旧实现上运行新增自动化测试，证明 250 上限和 runner 用例按预期失败。
2. 实现后运行 runner/历史批次聚焦测试。
3. 运行完整 `stable` 回归、Django check 和 migration drift。
4. 使用真实 PostgreSQL 执行 20 并发租约、最小权限 role、事务暂停和 `application_name` 测试。
5. 使用隔离 Docker 网络执行 crawl/apply 越权 smoke、资源 inspect 和普通部署不干扰演练。
6. 运行 `sh -n`、脚本契约扫描、`git diff --check`、本 change strict 和全量 OpenSpec validate。
7. 代码实现后执行 `/review -> 修复 -> 重新 review`，直到某轮没有 actionable finding。
8. 生产部署后先完成 TC-PROD-001 至 015，再允许生成 batch006；TC-PROD-016 至 018 通过前不得开始正式批次写入。
