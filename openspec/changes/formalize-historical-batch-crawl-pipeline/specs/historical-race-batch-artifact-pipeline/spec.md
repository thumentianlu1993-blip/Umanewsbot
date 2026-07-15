## ADDED Requirements

### Requirement: 正式批次计划绑定已批准 selection 与固定镜像
系统 MUST 从结构化 stage descriptor 和受支持工具的 typed recipe 生成 historical runner plan，并同时绑定 selection、approval、manifest、image ID、revision、工具 SHA、实际输入目标集合、输入输出身份和请求预算。手工 argv 或无法证明这些身份的 plan 不得作为生产正式批次入口。

#### Scenario: 生成完整分片计划
- **WHEN** approved selection、artifact SHA、固定镜像和全部 shards 均通过校验
- **THEN** 系统生成确定排序的 runner plans，并使同一 stage 的 approved target 在所有 shard 中恰好出现一次

#### Scenario: selection 或 approval 漂移
- **WHEN** descriptor 声明的 selection、approval 或 manifest SHA 与磁盘文件不一致
- **THEN** 系统在创建 runner run 前拒绝生成计划，且不留下部分 plan

#### Scenario: shard 声明与工具输入目标不一致
- **WHEN** shard 声明 50 个 target，但 recipe 实际读取的 events CSV 或 selection subset 多一个、少一个或含跨地区 target
- **THEN** builder 拒绝该 shard，不生成 argv 或 plan

### Requirement: 分片同时遵守目标与请求预算
系统 MUST 要求单个 shard 的 target 数量不超过 250、请求预算位于 1 到 250，target 只能属于声明地区和批准 scope。请求预算不得用 target 数量推断后静默放大。

#### Scenario: 合法多分片覆盖 batch006
- **WHEN** 1061 个目标按地区和请求预算拆为多个合法 shard
- **THEN** 系统接受全部 shard，并报告总目标、各地区目标、各 shard 请求预算及零重叠零遗漏

#### Scenario: shard 超限或跨地区
- **WHEN** shard 包含 251 个目标、请求预算 251、重复 target 或与声明地区不一致的 target
- **THEN** 系统 fail closed，指出 shard 与具体违规目标，不生成正式 plan

#### Scenario: plan 预算与 runner env 不一致
- **WHEN** plan 的 `resource_limits` 与 runner settings 派生的请求、cache、磁盘或间隔限制不相等
- **THEN** runner 在创建/恢复 run 和取得双锁前拒绝执行

#### Scenario: 多个 shard 请求账本隔离
- **WHEN** 同一 stage 生成多个合法 shard
- **THEN** 每个 shard 使用独立 artifact 挂载根、请求账本、source-cache manifest 和 checkpoint，父 stage manifest 记录各 shard identity

### Requirement: 日期与详情碎片确定性合并
系统 MUST 以 approved selection 为分母合并重复输入的日期 provider rows、详情 candidates 和 gap fragments。不同输入顺序 MUST 产生相同的 canonical 输出与 SHA；同 target 冲突不得按最后写入获胜。

#### Scenario: 多地区碎片完整且无冲突
- **WHEN** 多个地区/年份碎片合计覆盖 scope 且 target SHA、inventory SHA 和模块完整性一致
- **THEN** 系统输出确定排序的 complete artifact、gap ledger 和 summary，并记录每个输入文件身份

#### Scenario: 同 target 有冲突证据
- **WHEN** 两个碎片为同一 target 提供不同日期、来源 URL、runner 或 result 内容
- **THEN** 系统将该 target 记为 conflict gap，保留双方身份，不静默覆盖

#### Scenario: 多文件发布中途失败
- **WHEN** builder 或 merger 在写完部分临时文件后发生异常
- **THEN** 最终输出目录仍不存在，既有输入不变，重跑不会读取半套 artifact

### Requirement: 每个目标必须完整或显式留缺口
系统 MUST 对 stage scope 中每个 approved target 给出且只给出一种结论：complete 或有证据身份的显式 gap。两集合不得相交；完全没有输入证据的 target 不得自动转为 gap。summary MUST 同时报告 accounted_rate 与 data_complete_rate，且不得以 gap 提高数据完整率。

#### Scenario: 少量来源暂不可得
- **WHEN** 5 个目标没有可信来源而其余目标形成完整候选
- **THEN** 系统继续输出其余 complete targets，将 5 个目标写入 gap ledger，并满足 `complete + gap = scope`

#### Scenario: 目标从 complete 和 gap 同时缺失
- **WHEN** 任一 scope target 未出现在 complete 或 gap
- **THEN** 整个合并失败，禁止进入 apply

#### Scenario: 无证据目标被自动包装为 gap
- **WHEN** 输入中没有某 target 的 candidate、失败记录或来源身份
- **THEN** merger 视为遗漏并失败，不生成通用 gap 代替证据

### Requirement: 人工补证必须可审计且防漂移
系统 MUST 仅接受结构化人工 evidence fragment，并绑定 target ID、target SHA、预期旧值、新值、来源 URL、理由、审核者和时间。工具代码不得写死生产 target ID。

#### Scenario: 预期旧值仍匹配
- **WHEN** 人工补证的 target SHA 和预期旧值与当前 selection/碎片一致
- **THEN** 系统应用覆盖并在输出 provenance 中保留完整补证身份

#### Scenario: target 或旧值已变化
- **WHEN** target SHA 或预期旧值与当前输入不一致
- **THEN** 系统拒绝覆盖并将该目标列入冲突，不修改候选

### Requirement: 写后阶段验收逐 target 可重复
系统 MUST 提供 tracked 管理命令验收 date、detail-source 和 final 阶段，逐 target 核对数据库身份、来源 provenance、模块完整性、applied candidate 和 draft 可见性，并输出机器可读报告。生产 PostgreSQL 验收 MUST 在数据库只读事务中运行。

#### Scenario: final 阶段全部一致
- **WHEN** complete candidates 已通过备份和 approval 门禁正式 apply
- **THEN** verifier 报告每地区 events/runners/results、error_count=0、published=0，且 complete targets 状态为 imported

#### Scenario: 某场模块数量或来源不一致
- **WHEN** 数据库 runners/results 数量或 applied source 与批准候选不一致
- **THEN** verifier 返回非零退出码并列出 target ID，不把该 stage 标记完成

#### Scenario: verifier 发生意外写入
- **WHEN** verifier 的实现或后续改动尝试执行 INSERT、UPDATE 或 DELETE
- **THEN** PostgreSQL 只读事务拒绝写入，命令失败且业务数据不变

### Requirement: 最大标准批次在固定资源内完成编排
系统 MUST 在 1250 targets 的标准批次上有界完成 plan、merge 和数据库验收，避免按 target 逐条查询或把全部原始 source body 常驻内存。

#### Scenario: 1250 target 性能契约
- **WHEN** fixture 包含 1250 targets、10 shards 和每 target 20 条 runner/result
- **THEN** 纯 artifact 编排在 30 秒和 256 MiB 额外 RSS 内完成，数据库 verifier 查询数不超过 20

### Requirement: 年度赛历来源请求必须由冻结 catalog 展开
系统 MUST 从 approved selection 和版本化 source catalog 生成逐 target 来源请求。catalog MUST 显式绑定来源 ID、地区、届次年份、adapter、HTTPS URL、parser 与来源级别；任一 target 没有来源映射或来源跨 scope 时不得生成请求 artifact。

#### Scenario: 多份年度目录覆盖同一地区年份
- **WHEN** 英国某届同时需要平地和障碍年度目录，且 catalog 两份来源都合法
- **THEN** 系统为该 scope 的每个 target 绑定两份来源，并使 cache 对共享 URL 只请求一次而保留全部 target references

#### Scenario: 同一 URL 跨届次年共享
- **WHEN** 一个正式目录 URL 同时覆盖相邻两个届次年，request/ledger 使用全量 selection 与 catalog，而 parser 按地区+年份分片
- **THEN** cache 只请求一次，ledger target references 精确等于两届来源 scope 的并集；每个 parser shard 仍只消费自己的 target scope

#### Scenario: catalog 漏掉 target 或引用错误年份
- **WHEN** 任一 target 没有匹配 source，或 source 的地区/届次年与 target 不一致
- **THEN** 请求生成器 fail closed，不用空 URL 或人工默认值补齐

### Requirement: 赛历缓存允许显式、完整记账的部分失败
日期 source cache MUST 默认因任一请求失败返回非零；仅在操作者显式启用 partial 且全部唯一请求均已形成 succeeded/failed 终态账本时，才可继续下一阶段。失败请求 MUST 保留 URL、错误、受影响 target references 和请求身份，不得计入成功或数据完整率。

#### Scenario: 一个年度 PDF 暂时不可得
- **WHEN** 其余请求成功、该 PDF 请求失败且正式 recipe 显式允许 partial
- **THEN** cache 完整写出 ledger/summary 并成功结束 stage，后续 parser 将受影响 target 转为 evidence-backed gap

#### Scenario: 未显式允许 partial
- **WHEN** 任一请求失败且 recipe 未声明 partial
- **THEN** cache 返回非零，runner 停在该 step 的安全边界

### Requirement: 缓存年度赛历必须离线解析为完整输入或证据缺口
系统 MUST 使用 tracked runner 工具离线读取 selection、source catalog、request ledger、source-cache manifest 和缓存目录，复核每个缓存文件 path/size/SHA/source URL，再按显式 parser 生成可选直接 provider rows、地区 events CSV、gap ledger、summary 与 manifest。每个 scope target MUST 恰好属于 calendar-complete 或 gap；calendar-complete 必须有可信 local_date，但只有来源给出唯一直接赛果 URL 时才允许生成 provider row。

#### Scenario: BHA 与 France Galop PDF 正常解析
- **WHEN** 缓存身份一致、PDF 可提取文本且赛事唯一匹配
- **THEN** 系统保留英国原始英制距离、法国公制距离和 source provenance，生成带 local_date 的 events CSV

#### Scenario: 法国障碍汇总表仅作补充
- **WHEN** 固定列分组汇总表可补齐详细赛程缺少的场地赛事，但同一目标的汇总日期与同质量详细赛程不同
- **THEN** 系统使用布局保留解析补齐缺失目标，并让逐场详细赛程优先；汇总日期不得覆盖详细记录

#### Scenario: HKJC 跨年赛季目录
- **WHEN** HKJC 赛季来源包含上一自然年下半年和本自然年上半年
- **THEN** 系统按 edition year 绑定目标并保留实际 local_date，不把跨年赛事改到错误届次

#### Scenario: 缓存 SHA 漂移
- **WHEN** manifest/ledger 声明的缓存文件与磁盘 size 或 SHA 不一致
- **THEN** 解析器 fail closed，不生成 complete 或通用 gap

#### Scenario: 来源已记账失败或匹配多义
- **WHEN** cache ledger 为 failed，或解析后一个 target 无唯一匹配
- **THEN** 解析器为该 target 生成带 catalog、ledger 和 source identity 的 gap，并继续其他 target

#### Scenario: 年度目录只有日期而没有赛果 URL
- **WHEN** BHA、France Galop 或 HKJC 年度目录唯一定位了赛事日期，但页面不是该场具体赛果
- **THEN** 系统生成 event row 且不生成该 target 的 provider row；后续详情 preparer 必须找到真实赛果 URL 后才能进入 date fragment merger
