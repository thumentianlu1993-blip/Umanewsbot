## ADDED Requirements

### Requirement: 编排工具必须以 RaceEvent 产品层为目标
系统 SHALL 提供赛事信息编排工具，目标限定为 `RaceEvent` 产品层及其出走表、赛果、历届冠军和候选资料，不得写入 `ExternalRace*` 外部缓存表。

#### Scenario: 编排目标为 RaceEvent
- **WHEN** 运维人员执行赛事信息编排计划
- **THEN** 系统 MUST 将 `target_layer` 识别为 `race_event`
- **AND** 系统 MUST 只生成或导入 `RaceEventDataCandidate` 可消费的候选资料

#### Scenario: 不写入 External 表
- **WHEN** 编排工具完成 prepare、audit 或 dry-run 阶段
- **THEN** 系统 MUST 不创建或修改 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 或 `ExternalHorseAlias`

### Requirement: 第一版必须覆盖三类赛事详情模块
系统 SHALL 在第一版编排范围内同时支持 `runners`、`results` 和 `history_winners` 三个模块，并对同一目标范围采用相同历史深度。

#### Scenario: plan 缺少任一目标模块
- **WHEN** plan 声明要执行第一版历史回填但缺少 `runners`、`results` 或 `history_winners`
- **THEN** 系统 MUST 拒绝将该 plan 标记为完整历史回填计划
- **AND** 系统 MUST 在错误或审计结果中列出缺失模块

#### Scenario: 三模块历史范围不一致
- **WHEN** 同一地区、来源和赛事系列的 `runners`、`results`、`history_winners` 声明不同历史起点或年份范围
- **THEN** 系统 MUST 将该批次标记为 invalid 或 incomplete
- **AND** 系统 MUST 不允许该批次进入 apply 候选

### Requirement: 编排计划必须可审计和可恢复
系统 SHALL 要求每次赛事信息编排从 plan 文件开始，并为每个运行生成可恢复的运行目录和 state artifact。

#### Scenario: 创建运行目录
- **WHEN** 运维人员以有效 plan 启动编排
- **THEN** 系统 SHALL 创建包含 plan 副本、state、命令记录、候选产物和审计产物的运行目录
- **AND** 运行目录名称 MUST 能区分地区、来源、模块范围和时间或 run id

#### Scenario: 从 state 恢复
- **WHEN** 某批次在 prepare 或 audit 阶段失败后重新执行 resume
- **THEN** 系统 SHALL 读取 state 并跳过已成功且输入未变化的阶段
- **AND** 系统 SHALL 保留上次失败摘要和本次恢复记录

#### Scenario: 缺少 plan 时拒绝运行
- **WHEN** 运维人员试图直接执行 prepare、audit 或 apply-check 而没有提供 plan 或 run state
- **THEN** 系统 MUST 拒绝运行
- **AND** 系统 MUST 返回需要 plan 或可恢复 state 的错误

### Requirement: 编排工具必须封装现有候选生成脚本
系统 SHALL 通过 adapter 调用现有 `runtime/tools` 候选生成脚本，并校验输出 JSONL、review CSV、summary 和 source cache。

#### Scenario: adapter 调用成功
- **WHEN** plan 指定的地区和来源已有对应 adapter
- **THEN** 系统 SHALL 执行该 adapter 的候选生成命令
- **AND** 系统 SHALL 记录实际命令、退出码、输出摘要和产物路径

#### Scenario: 产物缺失
- **WHEN** adapter 退出成功但缺少候选 JSONL、review CSV 或 summary 中的必需产物
- **THEN** 系统 MUST 将该阶段标记为 failed
- **AND** 系统 MUST 不进入 coverage audit

#### Scenario: 未授权网络访问
- **WHEN** plan 或命令未显式允许网络访问
- **THEN** adapter MUST 不发起外部请求
- **AND** 若候选生成需要网络，系统 MUST 失败并提示需要显式授权或提供 source cache

### Requirement: Adapter manifest 必须表达非统一脚本契约
系统 MUST 通过 adapter manifest 显式描述每个现有 `runtime/tools` 脚本的参数、依赖和输出，不得假设所有脚本共享同一个命令行接口或文件命名规则。

#### Scenario: 脚本使用特殊输入参数
- **WHEN** 某 adapter 目标脚本需要 `--review-csv`、`--source-html`、`--runner-jsonl`、`--pdf-dir` 或其他非通用输入
- **THEN** manifest MUST 声明该输入的来源、是否必需和在 run 目录中的归档位置
- **AND** adapter MUST 在缺失必需输入时失败并输出可复核错误

#### Scenario: 脚本输出固定年份或非标准文件名
- **WHEN** 某脚本生成固定年份文件名或来源特有文件名
- **THEN** adapter MUST 将产物复制、索引或记录为 run 目录中的标准候选、review、summary artifact
- **AND** 系统 MUST 保留原始产物路径以便追溯

#### Scenario: 脚本产物依赖前序模块
- **WHEN** 某模块候选生成依赖同批次的 runners、PDF cache 或人工 review CSV
- **THEN** manifest MUST 声明依赖关系
- **AND** 编排工具 MUST 在依赖产物缺失或未通过审计时阻止该 adapter 执行

### Requirement: 目标 RaceEvent 行必须在详情 dry-run 前预检
系统 MUST 在详情候选 dry-run 前确认目标年份的 `RaceEvent` 行存在或产出人工补建清单。缺少目标赛事行时，不得把详情候选伪装为可导入。

#### Scenario: 目标 RaceEvent 已存在
- **WHEN** plan 中的地区、赛事系列、年份和 slug 能匹配已存在的 `RaceEvent`
- **THEN** 系统 SHALL 将该年份标记为可进入详情候选审计
- **AND** coverage audit SHALL 记录目标赛事行的 id、slug、year 和 mapping 来源

#### Scenario: 深历史目标赛事行缺失
- **WHEN** plan 目标年份没有对应 `RaceEvent`
- **THEN** 系统 MUST 输出 draft RaceEvent seed review artifact
- **AND** 系统 MUST 将该年份标记为 missing_race_event blocker
- **AND** 系统 MUST 不允许该年份进入详情候选 dry-run 或 apply-check

#### Scenario: 补建清单未人工确认
- **WHEN** 缺失目标赛事行的 seed artifact 尚未人工确认或导入
- **THEN** 系统 MUST 保持该年份 blocked
- **AND** 系统 MUST 不自动公开新建赛事页

### Requirement: 覆盖审计必须区分完整、缺口和 blocker
系统 SHALL 对目标赛事系列、年份范围、候选 JSONL、现有正式数据和 source metadata 执行覆盖审计，输出机器可读 JSON 与人工 review CSV。

#### Scenario: 三模块完整覆盖
- **WHEN** 某赛事年份在目标范围内同时存在有效 `runners`、`results` 和 `history_winners` 候选
- **THEN** coverage audit SHALL 将该赛事年份标记为 `complete`

#### Scenario: 部分模块缺失
- **WHEN** 某赛事年份缺少 `runners`、`results` 或 `history_winners` 任一模块
- **THEN** coverage audit MUST 将该赛事年份标记为 incomplete
- **AND** coverage audit MUST 列出缺失模块
- **AND** 系统 MUST 不得把该赛事年份计入完整覆盖

#### Scenario: 重复候选
- **WHEN** 同一赛事年份和模块存在多个未合并候选，且来源或内容无法唯一确定
- **THEN** coverage audit MUST 输出 `duplicate_candidate` blocker
- **AND** 系统 MUST 不允许该模块进入 apply 候选

#### Scenario: source URL 一对多污染
- **WHEN** 同一个 source URL 被映射到多个不同赛事系列或年度赛事
- **THEN** coverage audit MUST 输出 `source_conflict` blocker
- **AND** 系统 MUST 要求人工复核后才能继续

### Requirement: 历史系列匹配必须依赖显式 mapping
系统 MUST 使用显式 `series_key` 或已审核 mapping 绑定历史赛事系列。名称模糊匹配只可生成待审候选，不得直接应用到正式赛事详情数据。

#### Scenario: 已审核 mapping 匹配
- **WHEN** 历史来源赛事名命中已审核的 series mapping
- **THEN** 系统 SHALL 将候选绑定到该 `series_key`
- **AND** coverage audit SHALL 记录 mapping 来源和审核状态

#### Scenario: 模糊匹配但未审核
- **WHEN** 历史来源赛事名只通过模糊匹配命中某个赛事系列
- **THEN** 系统 MUST 将该记录标记为 `needs_series_review`
- **AND** 系统 MUST 不允许该记录进入正式 apply 候选

#### Scenario: 多个系列候选
- **WHEN** 同一来源记录可能匹配多个赛事系列
- **THEN** 系统 MUST 标记为 `ambiguous_series`
- **AND** 系统 MUST 不写入 `RaceEventRunner`、`RaceEventResult` 或 `RaceEventHistoryWinner`

### Requirement: 来源权威等级必须贯穿候选与审计
系统 SHALL 对每个来源记录显式保存来源权威等级，并在候选、summary、coverage audit 和 apply-check 中展示该等级。

#### Scenario: 官方源候选
- **WHEN** 候选来自 JRA、NAR、HKJC 或其他官方来源
- **THEN** 系统 SHALL 标记来源权威等级为 official 或等价值

#### Scenario: 第三方源候选
- **WHEN** 候选来自 Sporting Life、ZEturf、Geny、HRN、TOBA、Wikipedia 或其他第三方来源
- **THEN** 系统 SHALL 标记来源权威等级为第三方或参考来源等级
- **AND** 系统 MUST 不得把该候选伪装为官方来源

#### Scenario: 混合来源模块
- **WHEN** 同一赛事系列的不同模块来自不同来源
- **THEN** coverage audit SHALL 分模块展示来源和权威等级
- **AND** apply-check MUST 要求人工确认该混合来源策略

#### Scenario: 来源等级缺失或与 adapter 声明冲突
- **WHEN** 候选缺少 `source_authority`、使用未知等级，或候选来源信息与 adapter manifest 冲突
- **THEN** adapter 或 coverage audit MUST 阻止该候选继续
- **AND** 系统 MUST 输出可复核的 provenance blocker

### Requirement: 已有正式数据覆盖必须进入 diff/review
系统 MUST 在候选 apply 前比较现有正式数据和新候选。已有正式数据不得被无条件覆盖。

#### Scenario: 已有模块数据
- **WHEN** 目标赛事已经存在 `runners`、`results` 或 `history_winners`
- **THEN** 系统 MUST 输出现有数据与候选数据的 diff/review 摘要
- **AND** 系统 MUST 记录现有来源、新来源、行数变化和年份覆盖变化

#### Scenario: 人工锁冲突
- **WHEN** 目标赛事或模块存在人工锁定标记
- **THEN** 系统 MUST 将该模块标记为 `manual_lock_conflict`
- **AND** 系统 MUST 不允许自动覆盖

#### Scenario: 候选更不完整
- **WHEN** 新候选的行数、年份覆盖或关键字段完整性低于现有正式数据
- **THEN** 系统 MUST 阻止该候选进入 apply 候选
- **AND** 系统 MUST 在 review artifact 中记录原因

### Requirement: apply-check 必须生成显式写入门禁清单
系统 SHALL 在正式 apply 前生成 apply-check artifact，确认 coverage、dry-run、人工确认、生产健康、导入锁和备份证据。

#### Scenario: 首批人工确认缺失
- **WHEN** 某地区、来源和模块组合首次准备 apply
- **THEN** apply-check MUST 要求人工确认记录
- **AND** 缺少人工确认时 MUST 阻止 apply

#### Scenario: 后续同组合批次
- **WHEN** 某地区、来源和模块组合已有首批确认且本批次门禁全绿
- **THEN** apply-check MAY 生成显式 apply 命令
- **AND** 系统 MUST 不得无人值守自动执行 apply

#### Scenario: 生产安全证据缺失
- **WHEN** apply-check 缺少健康检查、外部导入锁为空证明、数据库备份或 dry-run 结果
- **THEN** 系统 MUST 阻止 apply
- **AND** 系统 MUST 列出缺失证据

#### Scenario: 门禁证据指向不同候选文件
- **WHEN** coverage audit、dry-run artifact 和准备 apply 的候选 JSONL 的 SHA-256 不一致
- **THEN** apply-check MUST 输出候选证据不匹配 blocker
- **AND** 系统 MUST 不生成 apply 命令

#### Scenario: Dry-run artifact 未证明通过
- **WHEN** dry-run artifact 不是合法结构化结果、状态不是 `passed` 或缺少候选 SHA-256
- **THEN** apply-check MUST 将 dry-run 视为无效
- **AND** 系统 MUST 不生成 apply 命令

#### Scenario: 混合来源策略未确认
- **WHEN** coverage audit 显示同一赛事的不同模块使用不同来源或权威等级
- **THEN** apply-check MUST 要求人工确认记录与实际来源组合完全匹配
- **AND** 缺少匹配确认时 MUST 阻止 apply

### Requirement: 所有阶段必须写入可恢复运行状态
系统 SHALL 将 plan、prepare、audit、dry-run 和 apply-check 的成功、失败及 artifact 写入同一个 run state，并在恢复前校验已完成 adapter 的必需输出。

#### Scenario: 已成功 adapter 的输出丢失或变化
- **WHEN** resume 发现输入未变化，但上次成功 adapter 的必需输出缺失或 SHA-256 不一致
- **THEN** 系统 MUST 重新执行该 adapter
- **AND** 系统 MUST 记录输出缺失或变化的恢复原因

#### Scenario: Dry-run 或 apply-check 完成
- **WHEN** dry-run 或 apply-check 成功或失败
- **THEN** 系统 MUST 更新 state 中的当前阶段、completed stages、artifact 和错误摘要
- **AND** resume MUST 能使用已保存输入恢复该阶段

### Requirement: 长周期抓取必须手动分批执行
系统 MUST 将长周期历史赛事抓取设计为手动分批或一次性容器执行，不得加入 Celery Beat 或常驻后台自动调度。

#### Scenario: 生成批次命令
- **WHEN** plan 被拆分为多个批次
- **THEN** 系统 SHALL 为每个批次输出可复制执行的显式命令
- **AND** 命令 SHALL 包含 batch id、run 目录和阶段参数

#### Scenario: 不创建周期任务
- **WHEN** 编排工具创建或执行历史抓取计划
- **THEN** 系统 MUST 不创建 Celery Beat 周期任务
- **AND** 系统 MUST 不将该计划加入无人值守后台循环

### Requirement: 第一验收批次必须覆盖五个目标地区
系统 SHALL 要求第一验收批次覆盖日本、香港、英国、法国、美国五个目标地区，每个地区选择少数核心赛事系列并跑通三模块主流程。

#### Scenario: 验收批次缺少地区
- **WHEN** 第一验收计划缺少日本、香港、英国、法国或美国任一地区
- **THEN** 系统 MUST 将该验收计划标记为 incomplete
- **AND** 系统 MUST 列出缺失地区

#### Scenario: 每地区少数赛事系列
- **WHEN** 第一验收计划为某地区选择目标
- **THEN** 系统 SHALL 使用明确赛事系列清单
- **AND** 系统 SHALL 不以整年窗口替代系列清单作为第一验收目标

#### Scenario: 每地区三模块验收
- **WHEN** 第一验收批次完成
- **THEN** 每个目标地区 MUST 至少产出 `runners`、`results`、`history_winners` 的候选、coverage audit 和 dry-run 证据

### Requirement: 抓取前必须生成独立且不可静默缩减的应到清单
系统 MUST 在任何网络请求前仅根据已校验 plan 和正式 `RaceEvent` 生成应到目标快照。coverage audit MUST 以该快照为分母，不得从实际候选反推应到范围。

#### Scenario: 实际候选为空或缺少计划目标
- **WHEN** 实际候选为空，或缺少应到清单中的任一赛事年份
- **THEN** coverage audit MUST 生成 `missing_event_candidate` blocker
- **AND** 系统 MUST NOT 因没有候选记录可遍历而将覆盖率判为通过

#### Scenario: 候选超出应到清单
- **WHEN** 实际候选包含应到清单之外的年份或 slug
- **THEN** coverage audit MUST 生成 `unexpected_candidate` blocker
- **AND** 系统 MUST 阻止该候选进入 apply-check

#### Scenario: 应到清单无法可信生成
- **WHEN** plan 为空、目标重复、目标 `RaceEvent` 缺失，或恢复运行时 plan 哈希与应到快照不一致
- **THEN** 系统 MUST fail closed 并停止进入真实网络抓取
- **AND** 系统 SHALL 输出含赛事中英文名、年份、地区、slug 和预检状态的人工 review CSV

### Requirement: Prepare 必须产出单一汇总候选文件
系统 SHALL 在所有 adapter 完成后，将其已归一化且已注入 provenance 的候选合并为一个确定性 JSONL artifact，并将该 artifact 记录到 run state。

#### Scenario: 后续阶段未显式指定候选路径
- **WHEN** audit 或 dry-run 未传入单独候选 JSONL
- **THEN** 系统 SHALL 默认使用当前 run state 中的汇总候选文件
- **AND** coverage、dry-run 和 apply-check MUST 继续以其 SHA-256 绑定同一份候选

### Requirement: Plan 批量与限流配置必须在执行时生效
系统 MUST 校验正整数批量上限和请求上限，并让同一 run 的所有网络 adapter 共享累计请求预算与最小请求间隔。adapter 不得各自重新获得完整请求额度。

#### Scenario: 多个 adapter 连续执行
- **WHEN** 同一 run 依次执行多个需要网络的 adapter
- **THEN** 每次外部请求 MUST 先消耗同一个持久化请求预算
- **AND** 累计请求达到上限后，后续 adapter MUST 停止而非重置计数

#### Scenario: 请求预算证据损坏
- **WHEN** 已存在的请求预算 artifact 无法解析或内容非法
- **THEN** 网络 adapter MUST fail closed
- **AND** 系统 MUST NOT 通过重建空预算继续请求

### Requirement: 第一验收必须验证地区与模块的真实 adapter 覆盖
系统 MUST 在第一验收计划校验中确认每个地区声明的目标模块都至少有一个同地区 adapter 可执行，不得只检查全局模块集合。

#### Scenario: 某地区缺少模块 adapter
- **WHEN** 五地区和三模块名称均出现在计划中，但某地区没有覆盖其中一个模块的 adapter manifest
- **THEN** 第一验收计划 MUST 标记为 incomplete
- **AND** 系统 MUST 列出具体地区和缺失模块

### Requirement: Apply-check 必须验证真实备份与人工批准证据
系统 MUST 要求备份路径对应可读取文件且 gzip 校验通过，并要求 diff review 明确记录 `status=approved`。

#### Scenario: 备份文件不存在或 diff 未批准
- **WHEN** 备份路径不存在、gzip 证据未通过，或 diff review 缺少 approved 状态
- **THEN** apply-check MUST 生成 blocker
- **AND** 系统 MUST NOT 生成正式 apply 命令

### Requirement: Apply 范围必须与候选实际组合完全一致
系统 MUST 从 coverage 中的候选来源和模块推导实际 apply 组合，不得仅信任人工填写的 apply scope。

#### Scenario: 候选含有未确认的地区或来源组合
- **WHEN** 候选包含多个地区、来源或模块组合，但人工确认未覆盖其中任一组合
- **THEN** apply-check MUST 输出 `apply_scope_mismatch` 或对应确认缺失 blocker
- **AND** 系统 MUST NOT 生成会导入整份候选的 apply 命令

### Requirement: 正式 Importer 必须复核批准候选哈希
系统 MUST 在 apply-check 全绿后生成批准候选副本，并在 importer 真正写库前再次验证预期 SHA-256。

#### Scenario: 候选在 apply-check 后被修改
- **WHEN** importer 收到的候选字节哈希与 `--expected-sha256` 不一致
- **THEN** importer MUST 在任何数据库写入前失败
- **AND** 系统 MUST 不创建 `RaceEventDataCandidate` 或修改正式赛事详情

### Requirement: Adapter 配置必须严格校验
系统 MUST 拒绝无法执行的 adapter 配置，不得在 prepare 中静默跳过。

#### Scenario: 自定义 adapter 缺少命令或必需输出
- **WHEN** adapter 字典缺少非空 command、modules、outputs 或完整 provenance
- **THEN** plan 校验 MUST 失败并指出缺失字段
- **AND** prepare MUST 不得将该 adapter 计为已完成

### Requirement: Coverage Warning 不得伪装成 Blocker
系统 MUST 分别记录行级 blocker 与 warning，并只让 blocker 影响完整覆盖计数和写入门禁。

#### Scenario: 已有数据仅需要 diff review
- **WHEN** 候选三模块完整且不低于已有正式数据，但存在 `existing_data_diff` warning
- **THEN** coverage 行状态 SHALL 为 `complete_with_warnings`
- **AND** 该目标 SHALL 计入 `complete_count`

#### Scenario: 候选比已有数据更不完整
- **WHEN** 候选行数或关键覆盖低于已有正式数据
- **THEN** coverage 行状态 MUST 为 `blocked`
- **AND** `candidate_less_complete` MUST 阻止 apply

### Requirement: 真实网络抓取必须使用已审批应到清单生成的地区输入
系统 MUST 为应到清单生成绑定文件身份的固定审批 artifact，并从已审批清单按地区生成 adapter 输入，不得让共享或历史 CSV 决定本次抓取范围。

#### Scenario: 应到清单未审批或审批已过期
- **WHEN** 网络 adapter 即将执行，但审批不是 `approved`、缺少批准人/时间，或审批 SHA-256 与当前应到清单不一致
- **THEN** prepare MUST fail closed
- **AND** 系统 MUST NOT 发起真实网络请求

#### Scenario: 地区输入由计划目标生成
- **WHEN** 应到清单审批通过并进入 prepare
- **THEN** 系统 MUST 为每个地区生成只包含该地区应到赛事的 `events_csv`
- **AND** adapter MUST 使用该 run 内输入而不是工作区共享旧文件

### Requirement: Coverage 必须拒绝形式完整但内容无效的候选
系统 MUST 只接受显式批准的 series mapping，并要求每个模块包含非空 items 和可追溯 source URL。

#### Scenario: Mapping 状态拼写错误或未批准
- **WHEN** mapping 状态不是精确的 `approved`
- **THEN** coverage MUST 输出 `series_needs_review` 或 `ambiguous_series`
- **AND** 该目标 MUST NOT 计入 complete count

#### Scenario: 模块为空或来源 URL 缺失
- **WHEN** 模块键存在但 `items=[]`，或候选没有非空 `source_url`
- **THEN** coverage MUST 输出对应 `empty_<module>` 或 `source_url_missing` blocker
- **AND** 系统 MUST NOT 生成可写入结论

### Requirement: Apply-check 必须重新验证应到身份、备份内容和批准元数据
系统 MUST 在生成 apply 命令前重新计算当前应到清单身份、完整读取 gzip 备份，并验证范围确认含 approved 状态、批准人和批准时间。

#### Scenario: Coverage 来自另一份应到清单
- **WHEN** coverage 记录的应到 SHA-256 与当前 run 的应到清单不一致
- **THEN** apply-check MUST 输出 `expected_targets_evidence_mismatch`
- **AND** 系统 MUST NOT 生成 apply 命令

#### Scenario: 备份只是伪装成 gzip 或确认缺少批准证据
- **WHEN** 备份无法完整解压，或确认缺少 approved 状态、批准人、批准时间任一字段
- **THEN** apply-check MUST 生成 blocker
- **AND** 系统 MUST NOT 生成 apply 命令

### Requirement: 批量正式写入必须保持原子性
系统 MUST 在同一数据库事务内保存并应用一批赛事候选，不得在命令失败后留下已提交的前半批数据。

#### Scenario: 后续模块应用失败
- **WHEN** 本批前序模块已经处理，但后续模块在转换或写库时抛出异常
- **THEN** 系统 MUST 回滚本批创建的全部候选和正式赛事数据
- **AND** 操作者重新执行前 MUST 看到数据库仍处于批次开始前状态

### Requirement: 应到批准必须绑定 adapter 的完整输入
系统 MUST 将 adapter 所需的完整赛事字段保存在应到快照中，并只从批准快照生成地区 CSV。

#### Scenario: 审批后赛事抓取字段变化
- **WHEN** 应到清单获批后，当前 `RaceEvent` 的名称、别名、日期、系列、赛场或 `source_refs` 与快照不一致
- **THEN** prepare MUST 阻止执行
- **AND** 系统 MUST 要求重新生成并审批应到清单

### Requirement: 混合来源策略只接受完整批准记录
系统 MUST 只从通过统一批准校验的 confirmation 读取混合来源策略 SHA。

#### Scenario: Pending 记录包含正确策略 SHA
- **WHEN** confirmation 的策略 SHA 正确但状态不是 `approved`，或缺少批准人/时间
- **THEN** apply-check MUST 输出 `mixed_source_confirmation_missing`
- **AND** 系统 MUST NOT 将该记录与其他范围确认拼接后放行
