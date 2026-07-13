## ADDED Requirements

### Requirement: P0 范围必须包含正式马名术语和重点赛事参赛马
系统 SHALL 将 P0 马定义为两个来源集合的并集：active 且有中文译名的 horse `TermEntry`，以及日本、中国香港、英国、法国、美国重点赛事参赛马。重点赛事等级 MUST 严格限定为 `G1/G2/G3/JG1/JG2/JG3/JPN1/JPN2/JPN3`。

#### Scenario: 从正式术语生成 P0 来源
- **WHEN** 系统同步 P0 范围
- **THEN** active 且有中文译名的 horse `TermEntry` SHALL 产生 `term_active_with_zh` P0 来源
- **AND** 系统 SHALL 为缺失资料页的来源创建或关联 `HorseProfile`

#### Scenario: 从重点赛事参赛证据生成 P0 来源
- **WHEN** 系统发现五大地区重点赛事的出赛或赛果记录
- **THEN** 每匹参赛马 SHALL 产生 `major_race_participant` P0 来源
- **AND** 来源 SHALL 记录赛事、等级、地区、参赛或赛果证据、source URL 和同步时间

#### Scenario: 非重点等级不进入新版 P0
- **WHEN** 赛事等级为 Listed、Open、`LOCAL_GRADE` 或其它非指定等级
- **THEN** 该赛事的参赛马 SHALL NOT 仅因该赛事进入 P0 范围

### Requirement: P0 来源必须可审计且可撤销
系统 SHALL 使用结构化 P0 来源记录表达马匹为何属于 P0。P0 来源 MUST 可追踪来源类型、证据、状态和撤销原因，不得只依赖 `source_refs` 或自由文本 notes。

#### Scenario: P0 来源保留历史
- **WHEN** 某匹马曾因正式术语或重点赛事参赛进入 P0
- **THEN** 系统 SHALL 保留该 P0 来源记录
- **AND** 后续纠错 MUST 标记来源 inactive 或 revoked，而不是静默删除历史证据

#### Scenario: P0 来源驱动队列
- **WHEN** 操作者生成 P0 补全队列
- **THEN** 队列 SHALL 只包含存在 active P0 来源的马匹
- **AND** 每行 SHALL 展示至少一个 P0 来源和排序原因

### Requirement: P0 范围必须支持持续同步
系统 SHALL 在重点赛事、出赛表、赛果或外部缓存导入后刷新 P0 范围。同步 MUST 能创建缺失 `HorseProfile`、记录 P0 来源，并将新增或需刷新的马加入补全队列。

#### Scenario: 未来重点赛事进入系统
- **WHEN** 新的重点赛事出赛表或赛果被导入
- **THEN** 系统 SHALL 为参赛马刷新 P0 来源
- **AND** 新增 P0 马 SHALL 进入资料补全队列

#### Scenario: 队列生成不写资料字段
- **WHEN** 操作者只生成或预览补全队列
- **THEN** 系统 MUST 不修改 `HorseProfile`、`HorseRaceRecord` 或 `HorseProfileDataCandidate` 的资料字段

### Requirement: 马匹身份必须使用来源内 ID 与数据库四元组两层证据
系统 SHALL 将来源命名空间内的 external horse ID 作为该来源直接证据。不同来源之间自动归并数据库已有马时，系统 MUST 使用经术语库归一的多语种马名、父名、母名和出生年份，且四项必须完整并唯一命中。`racing_region` MUST NOT 参与身份唯一性。

#### Scenario: 来源内 external horse ID 唯一命中
- **WHEN** 同一来源命名空间的 external horse ID 唯一命中既有马匹
- **THEN** 系统 SHALL 复用该 `HorseProfile`

#### Scenario: 跨来源四元组唯一命中
- **WHEN** 新来源 ID 未直接命中，但多语种马名、父名、母名和出生年份完整且唯一命中数据库已有马
- **THEN** 系统 SHALL 将新来源身份追加到该马的来源证据
- **AND** 不得因参赛地区不同创建重复马匹

#### Scenario: 身份证据仍有歧义
- **WHEN** 四元组字段不全、命中多匹，或跨来源只有同名和不同 external horse ID
- **THEN** 系统 SHALL 创建专用 `HorseIdentityConflict` 且不得写入马匹主表
- **AND** 冲突 SHALL 能在尚无 `HorseProfile` 时关联候选术语、赛事、马号、原始身份字段和来源证据
- **AND** 全量对账 MUST 保留仍在输入中但身份待处理的既有来源

#### Scenario: 同一赛事存在同名参赛马
- **WHEN** 同一赛事中两个参赛记录马名相同但马号或来源身份不同
- **THEN** 系统 SHALL 将其作为两个独立参赛者处理
- **AND** 不得在身份判定前按马名折叠

#### Scenario: 未处理歧义定期通知管理员
- **WHEN** 系统存在 `status=pending` 的 `HorseIdentityConflict`
- **THEN** 定时任务 SHALL 通过运营通知通道汇总冲突数量和后台处理 URL

#### Scenario: 人工解决结论用于后续同步
- **WHEN** 管理员将身份冲突标记为 `resolved` 并选择最终 `HorseProfile`
- **THEN** 下一次 P0 同步 SHALL 使用该人工结论建立参赛来源和来源身份
- **AND** `resolved` 状态缺少最终 `HorseProfile` 时系统 MUST 拒绝保存

### Requirement: 完整资料状态必须高于完整二代血统
系统 SHALL 支持完整资料状态，用于区分仅二代血统完整与整匹马资料完整。完整资料 MUST 至少包含身份/P0 来源证据、基础事实字段、二代血统、完整赛事履历、主胜鞍、来源 URL、赛马生涯状态或等价同步标记和人工审核记录。

#### Scenario: 完整资料硬字段齐备
- **WHEN** 马匹具备国家/地区、性别、毛色、出生日期、马主、练马师、生产牧场、二代血统、完整赛事履历、主胜鞍和来源 URL
- **AND** 必需模块均已人工审核通过
- **THEN** 系统 MAY 将该马标记为完整资料状态

#### Scenario: 简介不阻塞完整资料
- **WHEN** 马匹缺少 `intro` 但其它完整资料硬字段齐备
- **THEN** 系统 SHALL NOT 仅因 `intro` 缺失阻塞完整资料状态

#### Scenario: 相关新闻不阻塞完整资料
- **WHEN** 马匹没有站内相关新闻或相关赛事链接
- **THEN** 系统 SHALL NOT 仅因站内关联缺失阻塞完整资料状态
- **AND** 若站内已有可匹配数据，系统 SHOULD 建立候选或确认链接

#### Scenario: 在役马记录同步时间
- **WHEN** 马匹仍在役且赛事履历已补全到最近同步点
- **THEN** 系统 SHALL 记录 `records_synced_through` 或等价同步时间
- **AND** 未来新增出赛或赛果后 SHALL 能将该马重新标记为需要刷新

#### Scenario: 退役马完整生涯履历
- **WHEN** 马匹为退役状态
- **THEN** 完整资料状态 SHALL 表示履历覆盖来源最终记录中的完整生涯

### Requirement: 首批验收必须覆盖五地区各十匹完整资料马
系统 SHALL 支持从新版 P0 范围中为日本、中国香港、英国、法国、美国各完成 10 匹完整资料马的补全验收。首批样本 MAY 包含暂无中文译名但有重点赛事 P0 来源的马。

#### Scenario: 五地区首批样本完成
- **WHEN** 首批 P0 补全验收完成
- **THEN** summary SHALL 显示五个地区各至少 10 匹马达到完整资料状态
- **AND** 每匹完整样本 SHALL 有人工审核记录和可追溯来源 URL

#### Scenario: 样本失败不得降级通过
- **WHEN** 某地区样本因无匹配、字段缺失、来源失败或冲突无法补齐完整资料
- **THEN** 该样本 SHALL 记录失败原因和证据
- **AND** 该样本 MUST NOT 计入该地区 10 匹完整资料验收数

### Requirement: 补全批次必须记录运行状态和 artifact
系统 SHALL 为每次 P0 补全 dry-run 和 commit 记录批次运行状态。记录 MUST 包含范围、参数、来源、状态、artifact 路径、统计摘要、失败原因分布和操作时间。

#### Scenario: dry-run 创建批次记录
- **WHEN** 操作者执行 P0 补全 dry-run
- **THEN** 系统 SHALL 创建或更新补全批次记录
- **AND** 记录 SHALL 指向 JSONL 原始候选、CSV 审核表、summary 和 source evidence manifest

#### Scenario: commit 关联原始 artifact
- **WHEN** 操作者提交已审核 artifact
- **THEN** commit 记录 SHALL 保存原始 dry-run artifact 路径或等价标识
- **AND** 输出实际写入、候选、跳过、冲突、人工锁定跳过和失败统计

#### Scenario: 中断批次可复核
- **WHEN** 补全批次因异常、中断或限流停止
- **THEN** 系统 SHALL 保留已处理计数、最后处理目标、错误摘要和可读状态
- **AND** 不得把中断批次标记为完整成功

### Requirement: 来源 adapter 必须生成候选 payload 而非直接覆盖主表
系统 SHALL 将来源 adapter 的输出统一为可审核候选 payload。adapter MUST 输出基础资料、二代血统、完整赛事履历、主胜鞍、别名、来源证据、raw payload、置信度和失败原因中的可用部分，不得直接修改公开主表。

#### Scenario: 生成基础资料候选
- **WHEN** 来源 adapter 找到马匹基础资料
- **THEN** dry-run artifact SHALL 包含国家/地区、性别、毛色、出生日期、马主、练马师、生产牧场、来源 URL 和抓取时间

#### Scenario: 生成完整二代血统候选
- **WHEN** 来源 adapter 找到父、母、父父、父母、母父、母母六项血统
- **THEN** dry-run artifact SHALL 包含 `pedigree_payload` 六项文本、来源 URL、抓取时间和 raw payload 摘要

#### Scenario: 生成完整赛事履历候选
- **WHEN** 来源 adapter 找到马匹参赛、赛果或胜利记录
- **THEN** dry-run artifact SHALL 包含可写入 `HorseRaceRecord` 的完整候选列表
- **AND** 每条候选 SHALL 包含比赛名、日期或年份、级别、马场、距离或场地、名次或状态、来源名称和来源 URL

#### Scenario: 低置信或冲突只进入候选
- **WHEN** 来源结果存在同名歧义、跨地区冲突、外部 ID 冲突或置信度不足
- **THEN** 系统 SHALL 标记 `ambiguous_match` 或等价失败原因
- **AND** 不得在 dry-run 或 commit 中直接覆盖 `HorseProfile`

### Requirement: 已审核模块才能写入主表或候选表
系统 MUST 只允许已审核 artifact 被 commit。commit MUST 逐行、逐模块检查审核状态、置信度、人工锁定字段、现有资料冲突和幂等键。

#### Scenario: 未审核模块不写入
- **WHEN** artifact row 的模块未标记为审核通过或缺少确认字段
- **THEN** commit SHALL 跳过该模块
- **AND** summary SHALL 记录未审核跳过数量

#### Scenario: 高可信唯一命中写入未锁定字段
- **WHEN** artifact row 已审核通过、唯一高可信且字段未被人工锁定
- **THEN** commit SHALL 写入对应 `HorseProfile` 字段并更新完整资料状态
- **AND** 写入来源引用和可审计候选记录

#### Scenario: 参赛履历幂等写入
- **WHEN** artifact row 包含已审核参赛履历候选
- **THEN** commit SHALL 使用外部 race/result id 或马匹、来源、日期、比赛名、马场、source URL 组合做幂等 upsert
- **AND** 重复 commit 同一 artifact 不得创建重复 `HorseRaceRecord`

#### Scenario: 人工补录保留 URL 和审核人
- **WHEN** 操作者通过人工补录补齐资料字段
- **THEN** 系统 SHALL 记录来源 URL、录入人、审核人和字段组
- **AND** 不得将人工补录伪装为 adapter 自动抓取结果

### Requirement: 补全专项报告必须给出下一批执行建议
系统 SHALL 在每次 P0 补全 dry-run 和 commit 后输出专项报告。报告 MUST 包含全局和按地区统计、完整资料样本数、候选覆盖、完整赛事履历覆盖、失败原因、样例证据和下一批建议。

#### Scenario: 输出批次质量摘要
- **WHEN** P0 补全 dry-run 完成
- **THEN** summary SHALL 包含处理总数、按地区完整资料候选数、基础资料候选数、完整二代候选数、完整赛事履历候选数、别名候选数、未命中数、歧义数、来源不可用数和限流数

#### Scenario: 输出可人工复核样例
- **WHEN** summary 包含失败或冲突原因
- **THEN** artifact SHALL 为每类原因提供可复核样例、source evidence 和候选字段摘要

#### Scenario: 给出下一批建议
- **WHEN** 批次完成
- **THEN** 系统 SHALL 基于成功率、失败原因和队列剩余项输出下一批建议
- **AND** 建议 SHALL 区分可扩大、需修 adapter、需人工处理和暂不处理
