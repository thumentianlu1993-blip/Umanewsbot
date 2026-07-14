## ADDED Requirements

### Requirement: 历史批次必须运行在独立且固定版本的 runner 中
系统 SHALL 提供独立 historical batch runner 容器执行长周期历史阶段。runner MUST 使用不可变镜像 identity 和显式 runtime artifact 挂载，不得加入 Celery Beat 或普通 web/worker/beat 生命周期。

#### Scenario: 使用可变镜像或缺少版本标签
- **WHEN** 启动参数只提供 `latest`、无法解析的 tag，或镜像缺少 revision identity
- **THEN** runner MUST 拒绝启动
- **AND** 系统 MUST 不创建活动租约

#### Scenario: 普通应用部署执行
- **WHEN** 运维人员部署或回滚 web、worker 或 beat
- **THEN** 普通部署 MUST 不创建、停止、删除或重建 runner
- **AND** 普通部署 MUST 不处理 DB、Redis、runner 网络或 runtime artifact

#### Scenario: 普通部署缺少基础设施
- **WHEN** 普通 deploy 发现 DB、Redis 或所需网络不存在或不健康
- **THEN** 普通 deploy MUST fail closed
- **AND** 系统 MUST 要求另行执行显式 infrastructure bootstrap，不得隐式创建基础设施

#### Scenario: runner 加入周期调度
- **WHEN** 配置试图把历史 plan 注册到 Celery Beat 或无人值守循环
- **THEN** 系统 MUST 拒绝该配置
- **AND** 每个 runner run MUST 由显式批次 plan 启动

### Requirement: runner 必须同时持有数据库租约与应用文件锁
runner MUST 在执行任何 stage 前同时取得唯一数据库租约和 runtime 文件锁，并在运行期间续租。任一锁不可得、失效或身份分叉时 MUST 停止进入下一个 step。

#### Scenario: 第二个 runner 并发启动
- **WHEN** 已有未过期租约和文件锁的 runner 正在运行
- **THEN** 第二个 runner MUST 在执行命令前失败
- **AND** 系统 MUST 展示当前 owner、run id、phase 和 lease expiry

#### Scenario: 心跳正常续租
- **WHEN** runner 正在执行长 step 且未收到暂停请求
- **THEN** 系统 MUST 周期更新数据库 heartbeat 和 lease expiry
- **AND** 状态命令 MUST 报告可计算的 heartbeat age

#### Scenario: 仅有一类锁可用
- **WHEN** 数据库租约可取得但文件锁不可得，或文件锁可得但数据库租约不可取得
- **THEN** runner MUST fail closed
- **AND** 系统 MUST 不执行 crawl、verify 或 apply 命令

### Requirement: runner 必须保存可验证且可恢复的 checkpoint
系统 MUST 在每个 step 成功后保存数据库 checkpoint 和原子 runtime state，绑定 plan、镜像、输入、输出和命令身份。resume 只能跳过重新验证完全一致的已完成 step。

#### Scenario: 容器在已完成 step 后中断
- **WHEN** 新 runner 使用同一 run 和合法恢复凭据启动
- **THEN** 系统 MUST 重新校验已完成 step 的输入与输出 SHA
- **AND** 校验通过时 SHALL 从下一个未完成 step 继续

#### Scenario: artifact 在中断后变化
- **WHEN** 已完成 step 的输入、输出、plan SHA 或镜像 revision 与 checkpoint 不一致
- **THEN** 系统 MUST 将恢复标记为 blocked
- **AND** 系统 MUST 不自动重抓、重写或跳过该 step

#### Scenario: 数据库与文件状态分叉
- **WHEN** 数据库 checkpoint 和 runtime state 不指向同一 run、phase 或 completed step
- **THEN** 系统 MUST 阻止 resume
- **AND** 系统 MUST 输出两份状态的差异供审核

### Requirement: runner plan 必须使用结构化命令和 allowlist
runner MUST 只执行版本化 plan 中的结构化 argv，使用 `shell=false`，并按 phase 限定管理命令和已跟踪工具 allowlist。任意 shell 文本、越界路径或未知命令 MUST 被拒绝。

#### Scenario: plan 包含 shell 语法
- **WHEN** step 包含 `sh -c`、管道、重定向、命令替换或字符串命令
- **THEN** runner MUST 在启动 step 前拒绝 plan
- **AND** 系统 MUST 不创建该 step 的成功 checkpoint

#### Scenario: Python 工具越出批准目录
- **WHEN** `python_tool` 解析后的真实路径不位于 `/app/runtime/tools`
- **THEN** runner MUST 拒绝执行
- **AND** 系统 MUST 记录路径边界错误

#### Scenario: artifact 挂载遮住镜像工具
- **WHEN** 启动配置把宿主目录挂载到 `/app/runtime`，或实际工具 SHA 与镜像内 tool manifest 不一致
- **THEN** runner MUST 拒绝启动或执行该工具
- **AND** artifact MUST 只挂载到独立 `/app/historical-runtime` 路径

#### Scenario: apply 命令缺少批准哈希
- **WHEN** apply phase 的写入命令没有 approval 或 expected SHA 参数
- **THEN** runner MUST 阻止该 step
- **AND** 系统 MUST 不以 runner 锁替代 importer 自身门禁

### Requirement: crawl 与 apply 必须具有互斥的权限集合
系统 MUST 将 crawl 限定为 `network=true / write=false`，将 apply 限定为 `network=false / write=true`。两种 phase MUST 使用不同网络拓扑和数据库凭据，任何 run 都不得同时获得公网出口与业务表写权限。

#### Scenario: crawl 尝试写业务表
- **WHEN** crawl phase 的代码尝试创建或修改历史 target、RaceEvent、runner、result 或 candidate 业务记录
- **THEN** PostgreSQL 权限 MUST 拒绝写入
- **AND** runner MUST 将 step 标记为 failed

#### Scenario: apply 尝试访问公网
- **WHEN** apply phase 的代码尝试连接外部 HTTP、DNS 或其他公网服务
- **THEN** 容器网络 MUST 阻止请求
- **AND** runner MUST 不通过临时打开网络来重试

#### Scenario: phase 开关组合非法
- **WHEN** plan、环境或命令同时声明 network 和 write 为 true，或与当前 phase 不一致
- **THEN** runner MUST 在取得业务权限前失败
- **AND** 系统 MUST 记录非法权限组合

### Requirement: runner 必须实施资源和日志边界
runner MUST 配置 CPU、内存、PID 和日志轮转上限，并把完整日志保存到批次 runtime 目录。数据库只保存有界摘要，任何凭据或敏感环境变量不得进入 artifact 或日志。

#### Scenario: 缺少资源限制
- **WHEN** 启动命令没有 CPU、内存、PID 或日志轮转限制
- **THEN** runner 启动脚本 MUST 拒绝创建容器
- **AND** 系统 MUST 列出缺失限制

#### Scenario: 日志包含敏感值
- **WHEN** argv、stdout、stderr 或异常文本包含配置的敏感值
- **THEN** runner MUST 在写入数据库和 artifact 前脱敏
- **AND** 状态接口 MUST 不返回原值

#### Scenario: owner token 位于 artifact 目录
- **WHEN** 启动配置试图把 owner token 原文保存到批次 artifact、数据库或普通日志
- **THEN** runner MUST 拒绝启动或写入
- **AND** token 原文 MUST 只从独立 `0600` secret 文件只读加载

### Requirement: 数据库迁移必须等待 runner 安全暂停
普通部署在执行 migrate 前 MUST 请求 runner 暂停，并确认不存在 applying 状态、未过期可写租约或未完成数据库事务。未满足门禁时部署 MUST 停止。

#### Scenario: 首次上线控制表尚不存在
- **WHEN** 首次部署本能力且 runner 控制表尚未创建
- **THEN** 部署 MUST 通过 host-only 门禁确认 runner 容器、网络、secret 和同名表均不存在后才可迁移
- **AND** 任一 runner 痕迹存在时 MUST 拒绝首次上线 bypass

#### Scenario: crawl 正在运行
- **WHEN** 部署请求暂停且 runner 正在 crawl step
- **THEN** runner SHALL 在当前安全 step 边界进入 paused
- **AND** 部署 MUST 等待 paused 心跳后才可迁移

#### Scenario: apply 正在事务中
- **WHEN** 部署请求暂停且 runner 正在 apply 事务
- **THEN** runner MUST 等待事务提交或回滚后再进入 paused
- **AND** 部署 MUST 不强杀 runner 或并行执行迁移

#### Scenario: 暂停超时
- **WHEN** runner 未在规定时间内确认安全暂停
- **THEN** 部署 MUST 失败并保留现有服务
- **AND** 系统 MUST 不通过删除容器或租约绕过门禁

### Requirement: 失联接管必须 fail closed 且可审计
系统 MUST 仅在租约已过期、旧容器不存在、无活动历史事务且 checkpoint 可验证时允许 stale takeover。接管 MUST 记录操作者、原因、旧 owner 和新 owner。

#### Scenario: 租约过期但容器仍存在
- **WHEN** heartbeat 已过期但旧 runner 容器仍存在或状态未知
- **THEN** 系统 MUST 拒绝接管
- **AND** 运维人员 MUST 先查明旧进程状态

#### Scenario: 满足全部接管条件
- **WHEN** 租约已过期、容器不存在、无活动事务且 checkpoint 一致
- **THEN** 授权运维人员 MAY 创建新 owner 并恢复同一 run
- **AND** 系统 MUST 保存完整 takeover 审计记录

#### Scenario: 子进程仍在执行
- **WHEN** runner 父进程收到停止信号但已启动的 step 子进程仍存在
- **THEN** runner MUST 先终止并等待整个子进程组
- **AND** 系统 MUST 不在子进程退出前释放数据库租约或文件锁

### Requirement: runner 不得改变历史公开状态
runner 的 crawl、verify、apply、pause、resume 和 takeover 操作 MUST 不开启历史公开功能，也不得把 draft RaceEvent 自动改为 published。

#### Scenario: 批次成功完成
- **WHEN** runner 完成所有批准的 apply step
- **THEN** 历史赛事 MUST 继续保持 draft，除非另有独立公开审批 artifact
- **AND** 常驻历史网络与写入开关 MUST 继续为 false
