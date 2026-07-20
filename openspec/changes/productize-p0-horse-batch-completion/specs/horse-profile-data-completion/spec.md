## ADDED Requirements

### Requirement: 补全批次必须支持来自队列的任意批次选择

系统 SHALL 从 P0 补全队列选择滚动批次，支持按地区、profile id 和每地区上限的任意组合，默认每地区 100 匹、单批五地区合计不超过 500 匹。批次选择 MUST NOT 要求固定行数或固定地区构成的审核 CSV 作为唯一合法输入。

#### Scenario: 按地区和上限选批

- **WHEN** 操作者以 `--regions japan --limit-per-region 100` 选择批次
- **THEN** 系统 SHALL 从队列输出该地区不超过 100 匹候选
- **AND** 默认 SHALL 排除 `complete_profile_full` 和处于进行中批次的 profile
- **AND** 每行 SHALL 保留队列排序原因供人工审核批次构成

#### Scenario: 无界抓取被拒绝

- **WHEN** 抓取命令未指定地区或 profile id 且未显式给出每地区上限
- **THEN** 系统 SHALL fail closed 并拒绝执行网络抓取

#### Scenario: 批次 manifest 记录身份快照

- **WHEN** 系统生成批次 manifest
- **THEN** manifest SHALL 包含批次 SHA-256、逐匹 profile id、四字段身份快照、P0 来源摘要、地区分布和 adapter 配置指纹
- **AND** manifest 初始状态 SHALL 为 `pending`

### Requirement: 批次触网前必须完成人工批准绑定

系统 SHALL 要求批次 manifest 经人工批准后任何网络 prepare 才能执行。prepare MUST 校验显式传入的批准 SHA-256 与 manifest 文件字节 SHA-256 一致，且 manifest schema、reviewer、approved_at 字段完整，否则 fail closed。

#### Scenario: 未批准批次不得触网

- **WHEN** 操作者对状态为 `pending` 的批次 manifest 执行网络 prepare
- **THEN** 系统 SHALL fail closed 且不发出任何网络请求

#### Scenario: 批准 SHA 漂移被拒绝

- **WHEN** 显式传入的批准 SHA-256 与 manifest 文件实际字节 SHA-256 不一致
- **THEN** 系统 SHALL fail closed 并记录漂移原因

### Requirement: 每批复审产物必须为面向抽样的单独文件

系统 SHALL 为每个待审核批次在可配置本地复审目录输出一个独立复审文件，包含按地区分组的逐匹摘要（身份、硬字段完整度、血统状态、履历计数、异常标记、来源 URL）和异常/低置信抽样清单。复审文件 SHALL 服务于人工抽样、重点字段核对和 AI 辅助复审；机器可读 JSONL artifact MUST 保持为唯一 commit 凭证。

#### Scenario: 每批一个复审文件

- **WHEN** 批次抓取完成并通过 artifact 校验
- **THEN** 系统 SHALL 在复审目录输出以批次 ID 命名的单独复审文件
- **AND** 文件 SHALL 包含按地区分组的逐匹摘要行和异常/低置信抽样页

#### Scenario: 复审文件不替代 commit 凭证

- **WHEN** 操作者仅提供复审文件而未提供经批准的 manifest
- **THEN** 系统 SHALL NOT 执行 commit

### Requirement: 抓取批次必须可中断恢复

系统 SHALL 为每个批次 run 维护原子写入的 checkpoint 状态，逐候选记录输入指纹、必需输出 SHA-256、状态和失败原因。中断后 resume MUST 按决策矩阵精确续跑：输入指纹一致且上次成功且输出校验通过的候选 skipped，上次失败或中断的候选重试，输入变化的候选重跑，输出缺失或漂移的候选重跑并记录原因码。每次 resume SHALL 追加 resume 审计历史。

#### Scenario: 中断后 resume 跳过已完成候选

- **WHEN** 批次 prepare 在部分候选完成后中断，操作者执行 resume
- **THEN** 输入指纹未变且输出校验通过的已完成候选 SHALL 标记 `skipped_unchanged` 且不发出网络请求
- **AND** 失败或未完成候选 SHALL 按 `retry_failed` 重跑

#### Scenario: 候选输出漂移触发重跑

- **WHEN** resume 发现某候选必需输出的 SHA-256 与 checkpoint 记录不一致
- **THEN** 系统 SHALL 重跑该候选并记录输出漂移原因码
- **AND** 下游 review/apply 阶段状态 SHALL 作废并需重跑

### Requirement: 请求预算必须持久化并按地区独立

系统 SHALL 使用跨进程安全的持久预算账本记录抓取请求，每地区独立账本，host 级限速证据跨 run 共享。预算超限、账本损坏或锁失败 SHALL fail closed。run 级请求上限 MUST 有界，默认值由批次逐候选预算导出。

#### Scenario: 预算超限停止请求

- **WHEN** 某地区账本计数达到 run 级上限
- **THEN** 该地区后续网络请求 SHALL 被拒绝并记录 `request_budget_exceeded`
- **AND** 已完成的候选和 checkpoint SHALL 保留，可 resume

#### Scenario: host 限速跨 run 生效

- **WHEN** 两个顺序执行的批次访问同一来源主机
- **THEN** 第二个批次 SHALL 继承该主机的最近请求时间并按限速等待

### Requirement: 瞬时来源失败必须有限重试且计入预算

系统 SHALL 对 timeout、连接错误、HTTP 429 和 5xx 执行有界指数退避重试，每次尝试 MUST 计入请求预算。HTTP 403、登录墙、重定向超限、解析失败和缓存身份错配 MUST NOT 重试。超过重试上限的失败 SHALL 写为该候选的 blocked payload，不中断同批其他候选。

#### Scenario: 429 退避重试后成功

- **WHEN** 来源对某候选请求返回 429，且重试预算与次数均未耗尽
- **THEN** 系统 SHALL 按退避等待后重试，Retry-After SHALL 作为退避下限
- **AND** 成功后的候选正常进入 payload 生成

#### Scenario: 重试记账口径

- **WHEN** 系统重试同一 URL
- **THEN** 重试尝试 SHALL NOT 消耗 per-candidate 地区常量（该常量只计首次访问的不同 URL）
- **AND** 重试尝试 SHALL 计入地区持久账本与 run 级请求上限

#### Scenario: 永久失败不重试

- **WHEN** 来源返回 403 或登录墙
- **THEN** 系统 SHALL 立即将该候选标记为 blocked，记录失败原因，继续处理同批其他候选

### Requirement: 滚动批次必须经确定性转换与批准回写进入既有提交链

系统 SHALL 将批次 crawl artifact 通过确定性转换器生成每地区 research v3 JSON：同一输入字节 MUST 产生同一输出字节，转换器 MUST NOT 推断补值。操作者批准后，系统 SHALL 按地区生成 mapping decisions（逐马 bind/create、同名候选显式拒绝、四模块 module_reviews、数据库快照）、US authority manifest（批内含美国马时）和 release manifest，并复用既有 prepare/dry-run/commit 链提交。未通过复审的马 SHALL 整匹排除并记录到 blocker/替补池。

#### Scenario: 转换器确定性

- **WHEN** 对同一批次 crawl artifact 两次执行转换
- **THEN** 两次输出的 research v3 字节和 SHA-256 SHALL 完全一致
- **AND** 转换器无法确定的字段 SHALL 保持缺失并出现在复审文件异常页

#### Scenario: 未通过复审的马整匹排除

- **WHEN** 操作者批准批次时将某匹马标记为不通过
- **THEN** 该马所有模块 SHALL 一起排除，不进入 mapping decisions
- **AND** 系统 SHALL 把该马记录到 blocker/替补池并保留原因

### Requirement: 滚动批次提交必须绑定逐批人工批准

系统 SHALL 只允许消费经人工批准的滚动批次 artifact：apply 入口 MUST 校验显式传入的批准 manifest SHA-256 与文件字节一致、manifest schema 合法、reviewer 与 approved_at 必填、四模块对批内全部马匹均有批准记录，且 manifest SHA 在批次 append-only 批准台账中存在对应条目。AI 生成或未审核内容 MUST NOT 被标记为人工已审核。

#### Scenario: 模块批准覆盖不全被拒绝

- **WHEN** 批准 manifest 缺少批内任一马匹的任一必需模块批准
- **THEN** 系统 SHALL fail closed 且不执行 commit

#### Scenario: 台账无对应条目被拒绝

- **WHEN** release manifest SHA-256 在批次批准台账中不存在对应条目
- **THEN** 系统 SHALL fail closed 且不执行 commit

#### Scenario: 首批白名单仅限首批复验

- **WHEN** 新滚动批次尝试使用首批硬编码可信 release manifest SHA 作为批准通道
- **THEN** 系统 SHALL 拒绝并要求该批次自己的批准 manifest

### Requirement: 批次提交必须以每地区独立 commit artifact 执行

系统 SHALL 为批次内每个地区生成独立 commit artifact，各自携带 expected_actions、summary、SHA-256、release manifest 绑定和补全 run 记录，并按“prepare → dry-run → commit”逐地区串行提交。全局同一时间 SHALL 只允许一个批次处于 prepared-uncommitted 状态。重跑 commit MUST 使用同一 artifact 字节；内容修复 MUST 另起新批次。

#### Scenario: 地区独立提交互不阻塞

- **WHEN** 批次中一个地区的 commit 因任一行异常回滚
- **THEN** 该地区 artifact 的全部写入 SHALL 回滚并标记该地区 failed
- **AND** 同批其他地区的 commit SHALL 可正常继续，已提交地区数据保持不变

#### Scenario: 修复内容必须另起批次

- **WHEN** 操作者修改批次内容后尝试以原批次身份重新 commit
- **THEN** 系统 SHALL 检测到 artifact SHA 变化并拒绝，要求另起新批次

### Requirement: 批次提交后必须自动幂等复验

系统 SHALL 在 commit 成功后自动以同一 artifact 重跑 dry-run 模拟，断言 planned creates、updates、audits 全为 0。复验摘要 SHALL 写入补全 run 记录和 checkpoint 状态；复验失败 SHALL 报警并留给人工处理，系统 MUST NOT 自动修补。

#### Scenario: 重复提交计划写入为零

- **WHEN** 对已成功 commit 的批次再次执行完整链路
- **THEN** dry-run SHALL 报告全部记录 already applied、planned write 为 0
- **AND** 复验时间和计数 SHALL 写入 run 记录

### Requirement: 批次执行必须有界且内存安全

系统 SHALL 以有界批次为唯一执行形态：候选 payload 逐匹流式写入 staging，批次循环 MUST NOT 在内存累积整批 payload；commit 输入 SHALL 按地区切片为独立 artifact（不超过 100 匹），apply 侧单次解析峰值 MUST 保持有界。

#### Scenario: 无界抓取被拒绝

- **WHEN** 抓取命令未指定地区或 profile id 且未显式给出每地区上限
- **THEN** 系统 SHALL fail closed 并拒绝执行网络抓取

#### Scenario: 地区切片控制 apply 内存峰值

- **WHEN** 系统执行 commit 或 dry-run
- **THEN** 单次解析的 commit artifact SHALL 为地区切片而非整批聚合
- **AND** 整批聚合 artifact MUST NOT 作为 commit 输入
