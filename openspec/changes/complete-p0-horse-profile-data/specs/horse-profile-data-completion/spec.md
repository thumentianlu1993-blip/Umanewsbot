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

#### Scenario: 写入前只读提取参赛马候选

- **WHEN** 操作者从已导入的重点赛事提取 P0 参赛马候选
- **THEN** 系统 SHALL 输出完整参赛观察、按稳定身份归并的候选池、每地区人工样本、summary 和 SHA-256 manifest
- **AND** 只有马名而没有来源内 external horse ID 或完整血统身份的跨赛事观察 SHALL 保持独立并标记待身份补强
- **AND** 共享任一强身份键的观察 SHALL 归入同一候选，后续非空血统 SHALL 回填，连接多个既有 profile 或出现矛盾血统 SHALL 标记身份冲突
- **AND** 拥有不同强身份的同名马 SHALL 保持为不同候选并可分别进入地区样本
- **AND** 提取过程 SHALL NOT 创建或修改 `TermEntry`、`HorseProfile`、`HorseP0Source` 或 `HorseIdentityConflict`

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

### Requirement: 首批五十匹正式提交必须绑定独立生产映射与数据库快照
系统 MUST 使用独立、版本化、commit-compatible 的 reviewed artifact 提交首批 50 匹。artifact
MUST 精确绑定冻结 v3、美国组合来源 authority manifest、独立 profile mapping decisions 的字节
SHA，并逐匹保存四字段身份、deterministic identity key、模块批准和数据库 resolution snapshot。

正式 dry-run 与 commit 还 MUST 消费独立
`p0_horse_production_release_manifest.v1`。manifest MUST 绑定精确 v3、authority、mapping、
production snapshot、final artifact SHA、项目负责人批准元数据和 executor reviewer ID，且
manifest 自身精确字节 SHA MUST 位于仓库 trusted allowlist。allowlist 为空时系统 MUST 保持
prepare-only。

#### Scenario: prepare 消费全部显式 mapping decisions
- **WHEN** 操作者执行正式 artifact prepare
- **THEN** mapping decisions MUST 对全部 50 匹逐行给出 `bind_existing(profile_id)` 或 `create_new`
- **AND** 仅名称命中、缺 profile ID、缺 production snapshot SHA 或缺 v3 SHA 绑定 MUST 阻断
- **AND** `Stradivarius` 等多 profile 命中 MUST 显式保存选中 ID、全部 rejected ID 和理由
- **AND** mapping reviewer MUST 是 active staff/superuser，且项目负责人 release approver 与
  active superuser DB executor MUST 作为不同角色记录

#### Scenario: candidate artifact 不能自签生产 release
- **WHEN** 操作者完成 prepare 或自行制作 release manifest
- **THEN** candidate artifact SHALL 保持 `candidate_pending_independent_release`
- **AND** release manifest 精确 SHA 未进入仓库 trusted allowlist 时 dry-run 与 commit MUST 阻断
- **AND** release manifest 任一输入 SHA、production snapshot、final artifact 或 executor 绑定
  不一致 MUST 阻断

#### Scenario: JSON 输入按冻结字节单次读取
- **WHEN** prepare、dry-run 或 commit 消费 JSON 文件
- **THEN** 每个文件 MUST 只读取一次普通文件字节，并以同一字节计算 SHA 和解析 JSON
- **AND** symlink 或非普通文件 MUST 拒绝
- **AND** commit MUST 使用已加载的内存 payload，不得重新打开 artifact 或其输入

#### Scenario: create resolution 不得绕过强身份
- **WHEN** mapping decision 选择 `create_new`
- **THEN** 当前数据库 MUST 不存在名称、父、母、出生年四字段完整一致的 profile
- **AND** commit SHALL 创建 pending horse `TermEntry` 与 `HorseProfile`
- **AND** 已有唯一可复用且未绑定 profile 的 `term_type=HORSE` 正式 term/alias SHOULD 复用
- **AND** 同名非 horse term MUST 完全忽略

#### Scenario: dry-run 执行真实逐行模拟且零写入
- **WHEN** 操作者为精确 artifact SHA 执行 `--dry-run`
- **THEN** 系统 MUST 重新验证三份输入 SHA、reviewer、identity、profile snapshot、模块 payload、
  URL、记录唯一性和 expected action
- **AND** 输出 SHALL 包含 profile create/update、record create/update/existing、P0 source 和
  module audit 数量
- **AND** 数据库写入数 MUST 为零
- **AND** 输出 SHALL 报告 commit 将使用的 table lock，但 dry-run MUST NOT 取得阻塞式 table lock

#### Scenario: commit 在单事务中 fail closed
- **WHEN** 操作者提供精确 artifact SHA 与 `--confirm-reviewed-artifact`
- **THEN** 系统 MUST 在单事务中锁定 reviewer、已有 profile 和 deterministic identity create scope
- **AND** PostgreSQL MUST 在任何 mapping snapshot 重扫和业务创建前，以
  `SHARE ROW EXCLUSIVE` 锁定 `TermEntry`、`TermAlias`、`HorseProfile`
- **AND** table lock 取得后 MUST 重扫全部 50 匹四字段身份和 mapping snapshot
- **AND** 任一 identity、snapshot、manual lock、记录或来源漂移 MUST 使整批回滚
- **AND** 重跑同一 artifact MUST 不重复创建 profile、term、P0 source、candidate 或 race record
- **AND** 普通履历 event/result 可为空，系统 MUST NOT 为本批创建 `RaceEvent`
- **AND** completion run 只 SHALL 关联本 artifact upsert 明确认领的 record ID（包括 unchanged），
  不得接管其它 `completion_run IS NULL` 的旧履历

#### Scenario: 非协作马档案或术语写入不能穿透提交快照
- **WHEN** 其它连接未使用本批 advisory lock 并尝试写入马档案、术语或 alias
- **THEN** 该写入 MUST 在本批 commit table lock 释放前等待或按数据库超时失败
- **AND** 普通读取 SHOULD 继续可用
- **AND** 运行手册 MUST 要求 commit 前停止相关自动任务或确认无并发写入

#### Scenario: 提交事务覆盖深层业务写入和审计日志
- **WHEN** 第一行已真实创建 profile、term、race records、P0 source、module candidates 和
  completion run 后，后续行失败
- **THEN** 全部业务写入 MUST 回滚
- **AND** `TaskExecutionLog` 创建后发生异常时，日志与全部业务写入也 MUST 在同一事务回滚

#### Scenario: 美国组合来源保持窄批准语义
- **WHEN** formal artifact 写入美国 10 匹的已审核履历
- **THEN** 系统 SHALL 继承冻结 v3 的 `source_records_verified` 状态
- **AND** P0 source 审计 MUST 明确该状态不表示 Equibase 官方逐场履历

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

### Requirement: P0 马完整生涯必须独立于赛事产品覆盖
系统 SHALL 按马匹来源采集 P0 马的全部生涯实际出赛，不得从重点赛事或正式 `RaceEvent` 总账反推完整履历。新马、未胜利、普通条件、让磅、表列及各级分级赛均属于 `HorseRaceRecord` 范围。

#### Scenario: 普通比赛没有正式赛事详情
- **WHEN** 来源确认 P0 马参加了一场普通比赛，但系统没有可确认的 `RaceEvent`
- **THEN** 系统 SHALL 保存一条 `event=NULL` 的 `HorseRaceRecord` 和比赛快照、结果及来源证据
- **AND** 系统 MUST NOT 为满足履历展示强行创建 `RaceEvent`

#### Scenario: 后续确认普通比赛身份
- **WHEN** 未关联履历后来获得唯一可靠的 `RaceEvent` / `RaceEventResult` 身份
- **THEN** 系统 SHALL 在原履历上回填关联
- **AND** 不得生成第二条参赛事实或丢失原始来源证据

### Requirement: 生涯完整度必须与资料和血统完整度分离
系统 SHALL 为马匹独立记录 `career_history_status` 或等价状态。状态 MUST 以来源总实际出赛数、已采集实际出赛数、缺口数、关联/未关联赛事数、海外出赛数、逐场核心字段和最后核验时间为依据，不得用二代血统状态、重点胜利数或 `records_synced_through` 单独代替。

#### Scenario: 来源总数与实际出赛一致
- **WHEN** 可靠来源给出生涯实际出赛总数
- **AND** 系统中去重后的实际出赛数与之相等、没有未解释缺口或待确认出赛记录
- **THEN** 系统 MAY 将生涯履历标记为完整

#### Scenario: 官方明确尚无出赛
- **WHEN** 可靠来源明确给出生涯实际出赛总数为零
- **AND** 逐场记录列表为空且总数证据完整
- **THEN** cache SHALL 接受该数量对齐快照
- **AND** 总数大于零时空逐场列表仍 MUST 被拒绝

#### Scenario: 来源总数未知或计数不一致
- **WHEN** 来源总数未知、采集数少于或多于来源总数，或存在待确认出赛状态
- **THEN** 系统 MUST NOT 将生涯履历标记为完整
- **AND** SHALL 保存可审核的阻断原因和缺口计数

#### Scenario: 来源总数缺少可审核出处
- **WHEN** 来源给出总实际出赛数，但来源名、来源 URL 或带时区核验时间任一缺失
- **THEN** 系统 MUST NOT 将生涯履历标记为完整
- **AND** 数量差异仍 SHALL 按真实采集数计算，不得为了表达证据缺失而伪造赛事缺口

### Requirement: 官方总数完整度必须与逐场权威性分离
系统 SHALL 分别记录官方或主来源实际出赛总数与逐场记录权威性。总数与已采集实际出赛数相等，只能证明数量对齐；若逐场记录来自非官方备用来源，系统 MUST 保持“数量已对齐、逐场官方性待确认”状态，不得标记为逐场官方履历完整。

#### Scenario: 官方总数与备用来源逐场行数相等
- **WHEN** Equibase 或等价权威来源给出实际出赛总数
- **AND** 已采集逐场记录来自 HRN 或其它非官方备用来源且实际出赛数与官方总数相等
- **THEN** 系统 SHALL 保存官方总数、总数来源、来源 URL、核验时间、已采集实际出赛数和 `gap_count=0`
- **AND** 逐场权威性 SHALL 保持 `count_aligned_records_unverified` 或等价状态
- **AND** 系统 MUST NOT 将数量相等解释为逐场官方结果已确认
- **AND** 只有独立批准且精确绑定冻结输入、记录唯一性和允许来源组成的窄批次审核 MAY 在新研究派生物中标记“组合来源逐场完整”
- **AND** 该窄例外 MUST NOT 被表述为 Equibase 官方逐场履历或用于放宽其它 HRN 输入

#### Scenario: 官方来源访问受许可或反自动化限制
- **WHEN** 官方逐场页面受许可条款或反自动化保护限制
- **THEN** 生产 adapter MUST NOT 使用浏览器绕过或规避访问限制
- **AND** 系统 SHALL 保留 `source_blocked` 或等价状态，并允许后续授权数据或人工 Full Charts/Lifetime PP 核验

#### Scenario: HRN 备用履历命中同名马
- **WHEN** 系统使用 HRN 直接 slug、搜索结果、缓存或离线研究结果补充美国马逐场履历
- **THEN** HRN 页面马名、父名、母名、出生年份 MUST 与已核验候选四项全部存在且一致
- **AND** 任一字段缺失或冲突时系统 SHALL fail closed，不得导入逐场履历

#### Scenario: 新增逐场权威状态处理旧完整履历
- **WHEN** 数据迁移为既有马匹新增默认未知的逐场权威状态
- **AND** 既有 `career_history_status` 为 `complete`
- **THEN** 系统 SHALL 将未达到 `source_records_verified` 的旧记录降为 `needs_review`
- **AND** 系统 MUST NOT 在重新核验前继续展示完整生涯
- **AND** 原 `complete_profile_full` 或等价聚合完整状态 SHALL 同步撤销

#### Scenario: 冻结批次组合逐场来源经人工审核
- **WHEN** pending-only prepare 之外独立冻结的 approved 审核 manifest 精确匹配可信 v2 输入字节 SHA、美国 10 匹四字段身份、Equibase 官方总数证据、逐场记录全集与稳定摘要
- **AND** 调用方显式提供的 approved manifest SHA 与代码信任锚和文件实际字节 SHA 完全一致
- **AND** Fort George 的逐场来源精确为 HRN 6 条、Sporting Life 6 条、Racing Post 1 条，其余 9 匹全部来自 HRN
- **AND** 每匹 source-bound ID、稳定记录键和同场规范键均唯一
- **AND** 10 匹均无 missing、excess、unknown 或 conflict
- **THEN** 系统 MAY 仅在新生成的 v3 派生产物中将这 10 匹标记为 `source_records_verified`
- **AND** 本批严格完整数 MAY 从 40 提升至 50
- **AND** 系统 MUST NOT 全局放宽 `count_aligned_records_unverified` 或改变其它输入的既有行为

#### Scenario: 组合来源审核任一绑定漂移
- **WHEN** 审核 manifest 缺失
- **OR** 输入 SHA、四字段身份、官方总数、记录内容、稳定摘要、来源 URL 或来源组成任一与当前输入不一致
- **OR** 出现未批准来源、missing、excess、unknown 或 conflict
- **THEN** 系统 SHALL fail closed，不生成通过审核的 v3
- **AND** 美国记录 SHALL 保持 partial，不得仅因数量对齐提升为完整
- **AND** 冻结 v1/v2 字节和数据库 SHALL 保持不变

#### Scenario: 组合来源审核生成只读验收链
- **WHEN** 冻结批次组合来源审核全部通过
- **THEN** 系统 SHALL 生成绑定审核 manifest 与 v3 SHA 的 research module-review artifact
- **AND** 输入缺少真实 production profile ID、reviewer ID 或 commit-compatible 模块批准时，系统 SHALL 生成显式声明零数据库写入且 `commit_artifact_compatible=false` 的 production readiness report
- **AND** readiness SHALL 标记 `assessment_type=static_schema_compatibility_check` 和 `safe_simulation_performed=false`
- **AND** 系统 MAY 保留 `load_completion_artifact` 对 v3 schema 不兼容的真实拒绝结论，但 MUST NOT 记录未实际调用的 apply simulation 路径或零动作 summary
- **AND** 正式生产写入仍 SHALL 由后续独立授权和 commit 流程执行

#### Scenario: 缓存复放必须由来源身份绑定请求马
- **WHEN** 系统复放任一地区的马匹来源缓存
- **THEN** 缓存自身的原始马名或 alias MUST 命中请求马名
- **AND** 系统 MUST NOT 用请求马名回填缓存缺失的 `identity.horse_name`

#### Scenario: 候选与资料来自不同 provider
- **WHEN** 候选 external horse ID 与资料 payload external horse ID 属于不同 provider
- **THEN** 候选马名、父名、母名和出生年份 MUST 全部存在并与资料 payload 一致
- **AND** 只有同名或 alias 时系统 SHALL fail closed，不能把不同 provider 的 ID 当作互证

#### Scenario: 同 provider 直接身份缺少或冲突
- **WHEN** 候选与资料声称属于同一 provider
- **THEN** 双方 external horse ID MUST 同时存在且一致，才可跳过四字段匹配
- **AND** 显式来源 namespace 与 `external:<provider>:...` key 冲突时系统 SHALL 拒绝

#### Scenario: 自动补充来源只有同名证据
- **WHEN** 系统准备把自动补充来源并入主来源 payload
- **AND** 双方不是同 provider 下 external horse ID 完整且精确一致
- **THEN** 主来源与补充来源 SHALL 各自具备马名、父名、母名和出生年份，且四字段全部一致
- **AND** 任一侧身份不完整或字段冲突时系统 SHALL fail closed，不得只凭同名补字段

#### Scenario: 父母实体搜索只有一个同名结果
- **WHEN** 父母实体搜索只返回一个名称相同的候选，但没有预期 external ID，也没有已知父名
  与候选完整来源身份的交叉匹配
- **THEN** 系统 SHALL 将该查询保留为待人工身份复核
- **AND** 系统 MUST NOT 仅因搜索结果唯一而自动写入祖父母字段

#### Scenario: 父母实体 external ID 近似但不相同
- **WHEN** 预期 external ID 与候选 ID 只在大小写或标点删除后相同，例如 `AB-12` 与 `ab12`
- **THEN** 系统 SHALL 视为不同 provider-bound 身份
- **AND** 只有去首尾空格后的原值精确一致 MAY 通过

#### Scenario: 历史 name-only 血统证据经人工复核
- **WHEN** 项目负责人已审核历史血统字段，但旧证据方法只有同名唯一结果
- **THEN** 升级 manifest SHALL 逐行绑定原输入 SHA、目标马强身份、父母实体 external ID、
  字段值、审核人、审核时间和审核会话
- **AND** 任一行漂移、缺失或多余时系统 SHALL 拒绝生成新版审核产物
- **AND** 旧 JSON/Excel MUST 保持原字节供审计追溯

#### Scenario: provider 名大小写不同但 external ID 冲突
- **WHEN** 候选与资料的 provider namespace 经规范化后相同
- **AND** 双方 external horse ID 原值不同
- **THEN** 系统 SHALL 拒绝直接身份绑定
- **AND** 系统 MUST NOT 以 provider 大小写差异绕过 ID 冲突

#### Scenario: 官方总数来源 URL 非法
- **WHEN** 官方或主来源总数证据的 URL 含空格主机、非法端口或其它不符合 HTTP(S) URL 语法的值
- **THEN** 数据库生涯 evaluator 和整匹马 evaluator SHALL 将该证据视为无效
- **AND** 该证据 MUST NOT 使生涯或整匹马资料进入完整状态

#### Scenario: 新候选只提供部分总数证据
- **WHEN** 新审核候选提供总出赛数，但来源名、严格有效来源 URL 或带时区核验时间任一缺失
- **THEN** apply SHALL 将总数、来源名、来源 URL 和核验时间作为无效整组处理
- **AND** 系统 MUST NOT 借用数据库旧字段与新总数拼成完整证据

#### Scenario: 官方总数与备用来源总数不一致
- **WHEN** 生涯同时保存经核验官方总数和备用来源总数
- **AND** 已采集实际出赛数只与备用来源总数相等
- **THEN** 研究摘要 SHALL 优先使用官方总数计算缺口
- **AND** 系统 MUST NOT 因备用来源数相等而报告官方数量已对齐

#### Scenario: 地区候选转换器离线重放
- **WHEN** 系统从已授权地区缓存重新构建研究候选
- **THEN** 转换器 SHALL 只从候选 payload 的逐场记录重新计算来源总数、实际出赛、未出赛、异常结果、海外出赛、缺少和多采数量
- **AND** 转换器 MUST NOT 依赖调用方未传入的临时变量或旧 summary
- **AND** 日本首批 10 匹缓存 SHALL 能逐匹完成离线重放

#### Scenario: 数据库或导出层绕过 cache 入口
- **WHEN** 管理员、服务或离线生成器直接评估生涯完整度
- **THEN** 数据库生涯 evaluator、整匹马 evaluator、研究 JSON 和工作簿 SHALL 各自复核总数证据和逐场权威状态
- **AND** 只有 `source_records_verified` MAY 输出完整，未知、受阻或非法状态 MUST 保持部分或受阻

#### Scenario: 来源请求发生重定向
- **WHEN** 地区来源返回 HTTP 重定向
- **THEN** transport SHALL 禁止自动跟随，并在下一次请求前重新校验 HTTPS 主机、凭据和端口
- **AND** 只有地区实现登记的目标主机 MAY 被访问，每一跳 SHALL 消耗同一单马请求预算

#### Scenario: 忽略新建议不撤销已应用证据
- **WHEN** 某模块已有 `APPLIED` 审核证据
- **AND** 后续新候选被标记为 `IGNORED`
- **THEN** 系统 SHALL 保留新候选的忽略审计记录
- **AND** 模块完整度 SHALL 继续使用最近一条非 ignored 的有效审核状态
- **AND** 从未应用或最近非 ignored 状态为 pending/conflict 时仍 SHALL 保持阻断

### Requirement: 父母实体来源身份与 v2 审核产物必须全局一致且可追溯
系统 SHALL 为父母实体使用版本化、全局一致的来源身份。每个 v2 `source_identity` MUST
包含 `horse_name`、`sire_name`、`dam_name`、`birth_year`、provider namespace、
provider-bound external horse ID 和严格来源 URL。provider namespace MAY 规范化，但 external
horse ID MUST 在搜索候选、出生年证据、逐行 manifest、v2 JSON 和工作簿中按不透明原值一致。

#### Scenario: 父母实体来源身份缺少出生年或父母名
- **WHEN** 父母实体候选缺少马名、父名、母名或出生年份中的任一字段
- **THEN** 系统 SHALL 将该候选保留为待人工身份复核
- **AND** 系统 MUST NOT 生成可进入 v2 的完整 `source_identity`

#### Scenario: 同 provider 的 external ID 在证据层发生漂移
- **WHEN** provider namespace 经规范化后相同
- **AND** 搜索候选、出生年证据、逐行 manifest 或 v2 输出中的 external horse ID 原值不同
- **THEN** 系统 SHALL fail closed
- **AND** 系统 MUST NOT 通过大小写折叠、标点删除或其它近似规则合并这些身份

#### Scenario: 自动 Netkeiba 父母候选 URL 不精确
- **WHEN** 自动父母候选声称来自 Netkeiba English
- **THEN** 来源 URL MUST 精确匹配 `https://en.netkeiba.com/db/horse/<id>/`
- **AND** URL 含凭据、显式端口、query 或 fragment 时系统 SHALL 拒绝该候选
- **AND** 路径中的 `<id>` MUST 与 provider-bound external horse ID 精确一致

#### Scenario: Kentucky Wood 的 Balko 同名纠错
- **WHEN** 系统升级 Kentucky Wood 的父系来源身份到 v2
- **THEN** Netkeiba `000a02bd3f` SHALL 作为 1925 年同名 Balko 保留在 v1 审计中且不得进入 v2
- **AND** v2 SHALL 使用 Racing Post `595446` 的 2001 年 Balko
- **AND** v2 SHALL 记录其父 Pistolet Bleu、母 Ella Royale、旧身份、新身份和纠错原因

#### Scenario: 父母出生年使用独立审核 artifact
- **WHEN** parent identity manifest 使用人工复核的父母出生年
- **THEN** 出生年 SHALL 来自独立 approved artifact，并保留其 `reviewed_by`、审核引用和 SHA-256
- **AND** 当前 `codex_manual_source_review` 证据 MUST NOT 被表述为项目负责人逐字段审核
- **AND** parent identity manifest SHALL 绑定该独立证据而不是复制或改写其审核归属

#### Scenario: 工作簿 builder 使用 v2 默认值
- **WHEN** 操作者不提供工作簿路径覆盖
- **THEN** builder SHALL 默认读取 v2 JSON
- **AND** 默认输出 SHALL 使用 `-v2.xlsx`，预览目录 SHALL 使用 `previews-v2`

#### Scenario: 环境变量覆盖配置但不能覆盖冻结 v1
- **WHEN** 环境变量和配置文件同时提供工作簿输入、输出或预览路径
- **THEN** 环境变量 SHALL 优先
- **AND** 输出指向冻结 v1 workbook 或 v1 previews 目录时 builder SHALL 拒绝运行
- **AND** v2 生成 MUST NOT 修改冻结 v1 JSON、workbook 或 previews 字节

### Requirement: 来源字段证据必须分为直接值、标准原始值和归一化值
系统 SHALL 为可能经过地区转换或语义映射的逐场字段分别保存直接原始值、当地权威来源的标准原始值和内部归一化值。每层 MUST 独立保存状态、来源名称、来源 URL、采集或核验时间和转换规则；缺少权威证据时不得从展示层值猜测标准值。

#### Scenario: 法国比赛由英国来源转换展示
- **WHEN** Sporting Life 将法国赛事的米制距离显示为英里/化朗，或将本地赛事分类显示为 Class/Grade
- **THEN** 系统 SHALL 将该值只保存为直接原始值
- **AND** 在 France Galop 或 IFCE SIRE 未提供标准原始值前，标准值 SHALL 保持未采集，归一化状态 SHALL 保持阻断
- **AND** 系统 MUST NOT 将 Class 与 Groupe 一一映射，也不得由舍入后的英制距离反推官方米制值

#### Scenario: 法国 N/A 获得权威结果补证
- **WHEN** Sporting Life 的直接结果为 `N/A`
- **AND** France Galop 或 IFCE SIRE 提供正式名次、`arr`、`tbé`、`t.j` 或其它权威结果
- **THEN** 系统 SHALL 保留 `N/A` 作为直接原始值，同时保存法国标准原始结果及内部归一化状态
- **AND** 该记录是否实际出赛 SHALL 按权威结果语义确定

### Requirement: 异常结果必须采用实际出赛计数语义
系统 SHALL 区分报名/退赛与实际出赛。`scratched` 和 `withdrawn` MUST NOT 计入生涯实际出赛数；`did_not_finish` 和 `disqualified` MUST 计入实际出赛数；来源无法确认是否实际出赛时 MUST 保持待确认。

#### Scenario: 退赛不计入实际出赛
- **WHEN** 一条履历状态为 `scratched` 或 `withdrawn`
- **THEN** 该记录 SHALL 保留在履历中
- **AND** `collected_start_count` MUST NOT 增加

#### Scenario: 未完赛仍计入实际出赛
- **WHEN** 一条履历状态为 `did_not_finish` 或 `disqualified`
- **THEN** `collected_start_count` SHALL 计入该记录

#### Scenario: 普通未上名使用数据库正式枚举
- **WHEN** 完赛名次为第 4 名及以后，或来源状态为 `finished` / `unplaced`
- **THEN** adapter 和审核 apply SHALL 将 `result_status` 归一为 `unplaced`
- **AND** 系统 MUST NOT 向 `HorseRaceRecord` 写入模型枚举以外的 `finished`

#### Scenario: 只有年份的履历不能满足完整门禁
- **WHEN** 一条履历只有比赛年份且 `race_date_precision=year`
- **THEN** 系统 SHALL 保留该履历和年份
- **AND** adapter dry-run 与数据库 evaluator SHALL 同时保持生涯 partial
- **AND** 只有 `race_date_precision=exact` MAY 满足逐场核心日期证据

#### Scenario: 人工证据 URL 必须严格有效
- **WHEN** 人工基础字段、血统、逐场赛果、官方总数或佐证 URL 含空格主机、非法端口或其它无效 HTTP(S) 语法
- **THEN** 证据解析 SHALL fail closed
- **AND** 该值 MUST NOT 进入冻结研究 JSON、工作簿或审核 apply

#### Scenario: cache 硬字段类型或日期格式非法
- **WHEN** source cache 的基础字段、血统字段或逐场核心字段使用对象/数组替代字符串，出生年份
  超出合理范围，或精确日期不符合 ISO 日期格式
- **THEN** cache validator SHALL fail closed
- **AND** 非空但类型错误的值 MUST NOT 被视为已补齐硬字段

#### Scenario: 审核 apply 与数据库来源引用含非法 URL
- **WHEN** 已审核行的主 URL、模块 URL、逐场 URL 或 `source_refs` URL 不符合严格 HTTP(S) 语法
- **THEN** apply SHALL 不写入该证据，数据库 evaluator SHALL 不把该引用计入完整度
- **AND** 仅非空或可由 `urlparse` 拆分 MUST NOT 视为有效

#### Scenario: 历史 APPLIED 模块保存非法 URL
- **WHEN** 历史 profile 或 pedigree 模块已标记为 `APPLIED`，但其 `source_url` 不符合严格
  HTTP(S) URL 语法
- **THEN** 最终数据库完整度 evaluator SHALL 阻断该模块
- **AND** 新 apply 入口是否已加门禁 MUST NOT 使历史非法证据获得豁免

#### Scenario: Sporting Life casualty reason 映射正式结果
- **WHEN** Sporting Life 逐场载荷的 casualty 以 `reason=Fell`、`reason=UnseatedRider` 或 `reason=BroughtDown` 表达
- **THEN** 系统 SHALL 映射为 `F`、`UR` 或 `BD` 的正式异常结果并保留原始 reason
- **AND** `finish_position` MAY 为空，但该记录 MUST 计入实际出赛

### Requirement: 跨来源履历必须安全去重并保留证据
系统 SHALL 使用马匹稳定身份与精确赛事事实生成跨来源规范键。海外远征在母国来源和举办地区来源中重复出现时，只能形成一条参赛事实，但 MUST 保留全部来源引用。仅有模糊名称或年份时不得自动跨来源合并。

#### Scenario: 两个来源描述同一场海外远征
- **WHEN** 两个来源具有同一马匹、精确日期、场地和相同场次号，或具有一致的比赛名与距离证据
- **THEN** 系统 SHALL 合并为一条 `HorseRaceRecord`
- **AND** `source_refs` SHALL 同时保留两个来源 URL 和外部身份

#### Scenario: HKJC 使用纯文本 Overseas 作为赛绩索引
- **WHEN** HKJC 完整赛绩首列为纯文本 `Overseas` 而不是数字 `Race Index`
- **THEN** 系统 SHALL 保留该行并标记 `is_overseas=true`
- **AND** 系统 SHALL 为该行生成稳定记录键
- **AND** 页面主表与下方重复的 `Overseas Horse Form Records` MUST 去重，但来源证据不得丢失

#### Scenario: 跨单位距离保留原文
- **WHEN** 两个来源分别使用米、英里或化朗描述距离
- **THEN** 系统 SHALL 保留各来源原始距离证据
- **AND** 只有在赛事身份其它证据充分时才可合并，不得仅按未经规范化的距离数字判断同一赛事
