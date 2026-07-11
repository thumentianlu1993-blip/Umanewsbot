## ADDED Requirements

### Requirement: 历史范围必须覆盖五地区全部 graded/pattern 赛事
系统 SHALL 建立日本 JRA/NAR 分级赛、中国香港分级赛、英国/法国 Pattern Race、美国 Graded Stakes 的历史系列目录。目录 MUST 覆盖 1984 年至当前年度任一年进入相应分级体系的现役和历史独有系列，并 MUST 排除普通赛、让赛和未胜利赛。

#### Scenario: 历史停办系列不在当前目录
- **WHEN** 某赛事在 1984–2010 年曾属于地区分级体系但已停办
- **THEN** 系统 MUST 将该赛事建立为历史系列
- **AND** 系统 MUST NOT 因其未出现在当前年度目录而忽略历史届次

#### Scenario: 普通赛事未进入分级体系
- **WHEN** 某年度赛事从未属于目标 graded/pattern 体系且不是入选系列的前分级届次
- **THEN** 系统 MUST NOT 将其纳入历史系列目录

### Requirement: 入选系列必须保存完整系列届次
系统 SHALL 从 `max(1984, 实际创办年)` 开始保存入选系列的真实年度届次。系列成为分级赛之前的届次 MUST 纳入，并保存当年真实名称、等级、马场、距离和举办状态，不得把当前字段倒灌到历史年份。

#### Scenario: 系列晚于 1984 年创办
- **WHEN** 某系列于 1995 年创办并于 2005 年升级为 G3
- **THEN** 系统 SHALL 从 1995 年开始生成年度应到目标
- **AND** 1995–2004 年 SHALL 保存当年真实等级而不是 G3

#### Scenario: 系列早于 1984 年创办
- **WHEN** 某系列在 1984 年前已经持续举办
- **THEN** 本项目的年度应到目标 SHALL 从 1984 年开始

#### Scenario: 系列后来降级退出分级目录
- **WHEN** 某系列曾进入分级体系、后来降级但仍连续举办
- **THEN** 系统 SHALL 继续收录降级后的真实届次直到停办或当前年度
- **AND** 各年 SHALL 保存真实等级

### Requirement: 稳定系列身份必须以权威沿革为准
系统 MUST 使用稳定系列实体关联年度赛事，并保存历史名称有效期、别名和来源。冠名、名称、马场、距离或等级变化 MAY 属于同一系列；合并、拆分、替代、前身和后继关系 MUST 显式审核，不得仅凭模糊名称自动合并。

#### Scenario: 赞助冠名变化
- **WHEN** 权威来源确认两个不同冠名属于同一赛事沿革
- **THEN** 系统 SHALL 将年度赛事绑定到同一稳定系列
- **AND** 系统 SHALL 保存各名称的有效年份和来源

#### Scenario: 名称相似但沿革不确定
- **WHEN** 两项赛事名称相似但没有权威沿革证据
- **THEN** 系统 MUST 生成 `identity_review_required` 候选
- **AND** 系统 MUST NOT 自动合并

#### Scenario: 系列合并或拆分
- **WHEN** 权威来源说明赛事发生合并、拆分或由另一赛事替代
- **THEN** 系统 SHALL 保存显式前身/后继关系和人工批准
- **AND** 系统 MUST NOT 把关系两端静默改成同一系列

#### Scenario: 系列关系形成循环
- **WHEN** 新的前身/后继关系会形成 self relation、重复关系或关系环
- **THEN** 系统 MUST 拒绝保存
- **AND** 系统 SHALL 输出冲突路径

### Requirement: 年度应到总账必须是完整分母
系统 SHALL 为每个已批准稳定系列和目标年份维护唯一年度目标。客观举办事实 MUST 使用 `expectation_status=held/cancelled/not_due/not_held`，处理结果 MUST 使用 `resolution_status=pending/ready/source_unavailable/identity_review_required/permanently_unavailable/imported`，并记录模块状态、证据和关联年度赛事。总账 MUST 从逐年赛历与已批准系列 timeline 生成，不得从实际抓到的候选反推。

#### Scenario: 实际候选缺少年度目标
- **WHEN** 某年度目标存在于总账但详情抓取没有返回候选
- **THEN** 该目标 MUST 保留在分母中
- **AND** 系统 MUST 将其记录为缺口而不是删除

#### Scenario: 当前目录机械外推历史
- **WHEN** 系统只有 2026 年赛事目录而缺少历史年度证据
- **THEN** 系统 MUST NOT 复制 2026 字段创建 1984–2025 目标
- **AND** 对应年份 MUST 保持待发现或身份待审状态

#### Scenario: 非法状态组合
- **WHEN** not-held 目标关联 RaceEvent、not-due 目标标记 imported，或 permanently-unavailable 缺少批准证据
- **THEN** 模型和写入服务 MUST 拒绝状态转换

### Requirement: 系列 timeline 必须补足前分级和后降级届次
系统 MUST 在逐年分级目录识别入选系列后，使用权威沿革、年度结果索引或年鉴生成系列 timeline，以发现创办年起的前分级届次、降级后连续届次、取消和 not-held 年份。仅扫描 graded/pattern 年度目录不得被视为完整系列历史。

#### Scenario: 前分级届次不在年度分级目录
- **WHEN** 某系列 1995 年创办、2005 年升格且 1995–2004 不在分级目录
- **THEN** timeline discovery MUST 识别 1995–2004 年届次
- **AND** 系统 MUST 将其加入年度总账

#### Scenario: timeline 缺少来源证据
- **WHEN** 某系列只能推测早期创办年而没有逐年沿革或结果证据
- **THEN** 相关年份 MUST 保持 identity review
- **AND** 系统 MUST NOT 自动创建年度赛事

### Requirement: 取消赛事与未举办年份必须分开
系统 SHALL 区分已排期后取消和该年根本未举办。已排期后取消 MUST 创建状态为 `cancelled` 的年度 `RaceEvent`；`not_held` MUST 只存在于年度总账并包含原因与证据，不得创建虚假赛事。

#### Scenario: 已排期后取消
- **WHEN** 权威来源证明某届已经排期但后来取消
- **THEN** 系统 SHALL 创建该年度取消赛事
- **AND** 取消原因和来源 SHALL 可审计

#### Scenario: 系列暂停一年
- **WHEN** 权威年度目录证明系列当年没有举办且没有排期取消事件
- **THEN** 系统 SHALL 将年度目标标记为 `not_held`
- **AND** 系统 MUST NOT 创建 `RaceEvent`

### Requirement: 当前年度未到期目标不得污染历史完成率
系统 SHALL 根据年度赛事日期和地区确认宽限期标记 `not_due`。未来赛事或仍在确认宽限期的赛事 SHALL 进入总账但不得计为缺失；到期后 MUST 转为应到目标。

#### Scenario: 当前年度赛事尚未举行
- **WHEN** 年度赛事日期晚于当前日期
- **THEN** 系统 SHALL 标记 `not_due`
- **AND** 历史缺失率 SHALL 不包含该目标

#### Scenario: 赛事已超过确认宽限期
- **WHEN** 赛事已经结束且超过地区结果确认宽限期
- **THEN** 系统 MUST 将其转为详情应到目标

### Requirement: 多来源必须执行字段级权威规则
系统 SHALL 按当年主办方/监管机构官方结果、官方历史档案/年鉴、高可信专业数据库、参考来源的顺序合并字段。低权威来源 MUST 只补空；同级或更高权威来源冲突 MUST 阻断受影响写入范围并进入人工审核。

#### Scenario: 低权威来源与官方结果冲突
- **WHEN** 官方结果和参考来源对冠军字段给出不同值
- **THEN** 系统 SHALL 保留官方值
- **AND** 系统 SHALL 记录冲突但 MUST NOT 让参考来源覆盖

#### Scenario: 两个官方来源冲突
- **WHEN** 两个同级官方档案对同一字段冲突
- **THEN** 系统 MUST 阻断该年度目标应用
- **AND** 系统 SHALL 输出字段、来源和原值供人工审核

### Requirement: 永久不可得必须有双来源证据
系统 MUST 在核查官方/监管机构档案和至少一个独立可信来源，保存查询范围、URL、时间、响应或档案目录证据，并排除限流、改版和身份错配后，才允许人工批准 `permanently_unavailable`。

#### Scenario: 来源暂时返回 403
- **WHEN** 单个来源返回 403、超时或限流
- **THEN** 系统 MUST 记录暂时 `source_unavailable`
- **AND** 系统 MUST NOT 自动标记永久不可得

#### Scenario: 双来源核查完成
- **WHEN** 官方档案和独立可信来源均无对应资料且证据完整
- **THEN** 运营人员 MAY 批准 `permanently_unavailable`
- **AND** 批准人、时间和证据身份 MUST 保存

### Requirement: Inventory artifact 必须绑定审批身份
系统 SHALL 为系列候选、冲突、年度目标、缺口、摘要和 source cache 清单生成确定性 artifact manifest。commit MUST 读取已批准 manifest 中的同一字节，且不得在 commit 阶段重新触网。

#### Scenario: 审批后年度目标文件变化
- **WHEN** `annual_targets.jsonl` 或 manifest 中任一文件 SHA-256 在审批后变化
- **THEN** commit MUST 在任何数据库写入前失败
- **AND** 系统 SHALL 要求重新审核

#### Scenario: 后台尝试绕过 artifact 批量写入
- **WHEN** 运营人员从后台查看总账或冲突
- **THEN** 后台 SHALL 提供筛选和详情
- **AND** 后台 MUST NOT 提供绕过已批准 artifact 的批量 apply

### Requirement: 历史网络与缓存必须默认关闭并受预算约束
系统 MUST 提供默认关闭的历史回填功能与网络总开关。真实网络 prepare 只有在全局功能开关、全局网络开关、plan 网络授权和应到审批全部通过时才能执行。run MUST 共享请求预算、缓存字节上限和最小剩余磁盘门槛，任一超限 MUST fail closed。

#### Scenario: plan 允许网络但全局开关关闭
- **WHEN** plan 声明 `allow_network=true` 但任一全局开关为 false
- **THEN** 系统 MUST NOT 发起网络请求

#### Scenario: 全局功能开关关闭时只读审计
- **WHEN** 功能和网络开关关闭，但操作者执行离线 cache 解析、plan 或 dry-run
- **THEN** 系统 MAY 执行只读阶段
- **AND** commit、publication 和网络请求 MUST 保持禁止

#### Scenario: source cache 超过预算
- **WHEN** 下一次响应写入会超过 `max_source_cache_bytes` 或低于 `min_free_disk_bytes`
- **THEN** adapter MUST 在写入前停止
- **AND** run state SHALL 记录预算 blocker

#### Scenario: 已批准 cache 被清理
- **WHEN** source cache 已进入批准 manifest 且批次仍在可回滚期
- **THEN** 清理流程 MUST 保留对应文件

### Requirement: 最终验收必须同时报告 accounted 和 data complete
系统 SHALL 计算全局及按地区、年代、系列拆分的 `accounted_rate` 和 `data_complete_rate`。目标闭环要求所有年度目标已导入、确认 `not_held/not_due`，或经双来源人工批准 `permanently_unavailable`，使 `accounted_rate=100%`；永久缺档 MUST 单独披露且不得计为数据完整。

#### Scenario: 所有目标有结论但存在永久缺档
- **WHEN** 所有年度目标均有允许的终态且部分目标永久不可得
- **THEN** `accounted_rate` SHALL 为 100%
- **AND** `data_complete_rate` MUST 低于 100% 并列出永久缺档

#### Scenario: 暂时不可用仍存在
- **WHEN** 任一 due 目标仍为 `source_unavailable` 或 `identity_review_required`
- **THEN** `accounted_rate` MUST 低于 100%
- **AND** 系统 MUST NOT 宣称全目标闭环
