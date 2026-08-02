## ADDED Requirements

### Requirement: 一期候选池必须由重赏赛事反向建立

系统 SHALL 从已完成身份合并且具有参赛或赛果证据的 `RaceEvent` 反向建立去重候选池。范围 SHALL 为 1998–2026 年日本训练马参加的 JRA G1/G2/G3、J-G1/J-G2/J-G3、地方 JpnⅠ/JpnⅡ/JpnⅢ，以及等级已规范化且训练范围有证据的海外 G1/G2/G3。具有 JRA/NAR 官方锚点但训练范围尚待官方档案确认的对象 MAY 以 `provisional_japan` 进入 prepare，但 MUST NOT 成为 `candidate_pass`。系统 MUST NOT 纳入 Listed/L、普通开放赛、只有马名术语记录的马或外国训练临时访日马。

#### Scenario: 一匹马参加多场重赏

- **WHEN** 同一 `HorseProfile` 具有多个符合范围的赛事来源
- **THEN** 系统 SHALL 只生成一个候选，并在 `qualification[]` 保存全部资格赛事
- **AND** SHALL 计算最高参赛等级、重赏出赛次数和最近参赛日期

#### Scenario: 日本训练身份得到确认

- **WHEN** 官方 JRA 档案明确给出日本中央练马师及 JRA 所属，NAR 档案明确给出日本地方所属与练马师，或仓库已有经人工审核且绑定来源 URL/ID、赛事日期和所属地的等价证据
- **THEN** 系统 SHALL 标记 `confirmed_japan` 并保存结构化 `training_evidence[]`
- **AND** 海外赛事 SHALL 证明参赛当时属于日本训练体系，不得用当前所属无条件回推历史

#### Scenario: 日本训练身份不能确认

- **WHEN** 对象仅有 `racing_region=Japan`、日本赛事、日文马名、日本生产地、Netkeiba 地区字段或其它不能证明训练所属的线索
- **THEN** 系统 SHALL 标记 `TRAINING_SCOPE_UNRESOLVED` 或 `NOT_JAPAN_TRAINED`
- **AND** `provisional_japan` MAY 进入官方档案 prepare，但 MUST NOT 自动通过或提交

#### Scenario: 海外重赏资格

- **WHEN** 日本训练马参加海外 G1/G2/G3，且赛事等级、赛事身份、参赛身份和官方来源均完整
- **THEN** 系统 MAY 将该赛事保存为资格证据
- **AND** 任一条件缺失时 MUST NOT 仅凭赛事名称或 Netkeiba 记录纳入

### Requirement: 批次排序必须区分赛事优先级与身份证据

系统 SHALL 将 G1/J-G1/JpnⅠ、G2/J-G2/JpnⅡ、G3/J-G3/JpnⅢ依次作为 Priority 1、2、3。每批最多 100 匹，并在同一等级内依次优先选择已有官方身份锚点、具有完整官方赛事上下文、唯一 Netkeiba ID、当前公开、重赏次数多、最近参赛较新的对象。赛事等级 MUST NOT 影响身份匹配标准或证据等级。

#### Scenario: G3 马具有完整双源证据

- **WHEN** 一匹只参加过 G3 的马具有唯一官方身份锚点，且 Netkeiba 与 JRA/NAR 四字段完整一致
- **THEN** 系统 SHALL 允许其进入待审核候选
- **AND** MUST NOT 因其最高等级为 G3 降低证据等级

#### Scenario: G1 马只有单一来源

- **WHEN** 一匹 G1 参赛马只有 Netkeiba ID，没有可用官方身份锚点
- **THEN** 系统 SHALL 标记 `OFFICIAL_ANCHOR_MISSING`
- **AND** MUST NOT 因赛事级别高而通过身份锁

### Requirement: 官方赛事锚点必须先于马名检索

系统 SHALL 优先消费资格赛事中已保存的 JRA/NAR horse ID 或详情 URL；若当前记录只有官方赛事
URL，系统 SHALL 使用冻结的赛事日期、场地、马号和精确马名，从同一官方赛事页面确定性解析唯一
参赛行及其唯一马匹链接。JRA 与 NAR SHALL 由独立 provider 处理。系统 MUST NOT 进行无赛事
上下文的开放式马名搜索。

#### Scenario: JRA 官方锚点

- **WHEN** JRA 资格赛事来源包含唯一马匹链接
- **THEN** artifact SHALL 保存完整 JRA URL、`CNAME` 原始值或稳定 horse code、赛事上下文和取得时间
- **AND** `JraHorseIdentityProvider` SHALL 从对应档案提取身份字段

#### Scenario: NAR 官方锚点

- **WHEN** NAR 资格赛事来源包含唯一马匹链接
- **THEN** artifact SHALL 保存完整 NAR URL、`k_lineageLoginCode`、赛事上下文和取得时间
- **AND** `NarHorseIdentityProvider` SHALL 从对应档案提取身份字段

#### Scenario: 没有直接马匹链接

- **WHEN** 官方赛事记录完整但没有马匹详情链接或代码
- **THEN** 系统 SHALL 在 allowlist 官方赛事 URL 中，以赛事日期、场地、马号和精确马名定位恰好
  一个参赛行，并要求该行恰好包含一个同 provider 马匹链接
- **AND** 页面若为赛事索引，最多跟随一个由赛事名、日期和场地唯一确定的详情链接；零/多赛事、
  零/多参赛行、零/多马匹链接或回链失败 SHALL 使用 `OFFICIAL_CONTEXT_NOT_FOUND` 或
  `OFFICIAL_CONTEXT_AMBIGUOUS`
- **AND** 每匹最多访问 3 个不同的 JRA/NAR URL、每个 URL 最多传输 2 次；重定向计入预算且
  MUST 留在同 provider allowlist host
- **AND** MUST NOT 启用站内马名搜索或选择第一条结果

### Requirement: 日本 P0 身份底稿必须由完整双来源共识建立

系统 SHALL 支持 `PREEXISTING_BASELINE`、`NETKEIBA_JRA_CONSENSUS`、`NETKEIBA_NAR_CONSENSUS` 和 `NETKEIBA_JRA_NAR_CONSENSUS`。对于底稿不完整且持有唯一 `netkeiba:{id}` 的候选，只有 Netkeiba 与至少一个官方 provider 对登记马名、父名、母名和出生年份一致，且最终能确认同一完整出生日期时，才可生成 `candidate_pass`。单一来源、模糊匹配、年份级日期或任一冲突 MUST fail closed。

#### Scenario: Netkeiba 与 JRA 完整一致

- **WHEN** Netkeiba 与唯一 JRA 官方档案的马名、父名、母名和完整出生日期规范化后均一致
- **THEN** 系统 SHALL 生成 `NETKEIBA_JRA_CONSENSUS`、证据等级 A 的待审核候选
- **AND** SHALL 分别保存两个来源的原始值、规范值、URL、ID 和内容摘要

#### Scenario: Netkeiba 与 NAR 完整一致

- **WHEN** Netkeiba 与唯一 NAR 官方档案的马名、父名、母名和完整出生日期规范化后均一致
- **THEN** 系统 SHALL 生成 `NETKEIBA_NAR_CONSENSUS`、证据等级 A 的待审核候选

#### Scenario: JRA 与 NAR 同时存在

- **WHEN** Netkeiba、JRA 和 NAR 三源四字段完整一致
- **THEN** 系统 SHALL 生成 `NETKEIBA_JRA_NAR_CONSENSUS`、证据等级 A+ 的待审核候选
- **AND** 任一来源冲突时 MUST 进入 blocker，不得以多数票覆盖

#### Scenario: 只有出生年份一致

- **WHEN** 来源只能确认同一出生年份但不能确认完整出生日期
- **THEN** 系统 SHALL 生成不可批准的 `candidate_partial`
- **AND** MUST NOT 推断月日或写入 `birth_date`

#### Scenario: 格式与文字体系差异

- **WHEN** 原始值存在 Unicode、空白、引号、连字符或国别后缀差异
- **THEN** 系统 MAY 使用已冻结的保守规范化规则比较并保留原值
- **AND** MUST NOT 自动音译或推测片假名与拉丁字母等价；无审核 alias 时 SHALL 使用 `SCRIPT_ALIAS_UNRESOLVED`

### Requirement: 来源访问必须有界且不由常驻服务触发

系统 SHALL 在个人非商用学习用途边界内，仅由一次性人工命令按显式清单访问 Netkeiba、JRA 和 NAR。每个 provider MUST 使用独立限速、持久请求预算、有限重试、缓存和 checkpoint；命令级 `--allow-network` 与启用的环境网络开关缺一不可。单匹全部来源合计 MUST NOT 超过 6 个不同 URL、18 次传输，且第二层 JRA/NAR 官方链 MUST NOT 超过 3 个不同 URL、6 次传输。系统 MUST NOT 将完整源页面、图片或视频作为公开产品内容或提交到仓库。

#### Scenario: 网络双重门禁

- **WHEN** 操作者没有同时提供命令级网络许可和启用的环境网络开关
- **THEN** 系统 MUST 在首个请求前 fail closed

#### Scenario: 来源拒绝或异常流量信号

- **WHEN** provider 返回 429、访问拒绝、验证码、异常访问提示或无法识别的限制页面
- **THEN** 系统 SHALL 立即停止该 provider 的新请求并记录 `SOURCE_ACCESS_DENIED`
- **AND** MUST NOT 通过代理、换域、并发放大或绕过限制继续

#### Scenario: 公开请求与常驻服务

- **WHEN** 用户访问公开页面或常驻 web/worker/beat/race worker 正常运行
- **THEN** 身份补证 SHALL NOT 被自动触发
- **AND** 常驻环境网络开关 SHALL 保持关闭

### Requirement: JRA-VAN 补证必须通过离线清单与 manifest 交换

系统 SHALL 为后续 Windows JRA-VAN DataLab 节点定义离线交换合同。Linux SHALL 输出显式待核对清单；Windows SHALL 只为清单对象导出 `horse_identity.jsonl` 和 manifest，保存血统登记编号、UM record type、数据规格版本、snapshot 时间、逐记录 SHA 和输入清单 SHA；Linux SHALL 在无网络状态下校验后对账。

#### Scenario: JRA-VAN 记录完整一致

- **WHEN** 受清单约束的 UM 记录与 Netkeiba 四字段及完整出生日期一致，且 manifest/SHA 全部有效
- **THEN** 系统 MAY 生成 `NETKEIBA_JRAVAN_CONSENSUS`、证据等级 B 的待审核候选
- **AND** 普通 DataLab 原始记录 MUST NOT 被直接公开复制

#### Scenario: 清单、版本或哈希漂移

- **WHEN** 输入清单 SHA、数据规格版本、snapshot、记录 SHA 或血统登记编号缺失或不匹配
- **THEN** 系统 MUST 拒绝整个导入 artifact

### Requirement: 身份补证必须使用显式有界输入并隔离旧 blocker

系统 SHALL 使用显式 profile ID 输入清单执行身份补证。单批必须为 1 至 100 匹，profile ID、candidate key 和数字型 Netkeiba ID 均须唯一；输入 SHALL 记录旧批次 blocker 排除集合和资格快照。选择查询 MUST 批量预取资格与来源，不得产生逐匹 N+1。

#### Scenario: 新批次排除旧 blocker

- **WHEN** 从上一批完成后的队列生成新输入
- **THEN** 输入 SHALL 列出旧 blocker profile ID 和排除理由
- **AND** 新批集合与旧 blocker 集合交集 SHALL 为空

#### Scenario: 输入或资格漂移

- **WHEN** 输入冻结后 profile 身份字段、Netkeiba key、qualification 或官方锚点发生漂移
- **THEN** prepare 或 commit SHALL 拒绝旧输入并要求重新生成 artifact

#### Scenario: 输入超过上限或身份不唯一

- **WHEN** 输入超过 100 匹，或存在重复 profile/candidate、缺失/多个/非数字 Netkeiba ID
- **THEN** 系统 MUST 在任何网络请求前 fail closed

### Requirement: prepare 必须可恢复且不写业务数据

系统 SHALL 将 prepare 限定为一次性任务。prepare SHALL 输出 qualification JSONL、候选 JSONL、blocker JSONL、summary、source evidence manifest、请求预算、checkpoint state 和 xlsx，且 MUST NOT 修改 `HorseProfile`、`HorseProfileDataCandidate`、公开状态或其它业务表。

#### Scenario: 单匹来源失败

- **WHEN** 某匹马发生超时、零结果、多结果、结构变化、字段缺失或冲突
- **THEN** 系统 SHALL 为该匹写入稳定 blocker 和 checkpoint
- **AND** 在剩余预算允许时继续其它对象

#### Scenario: 中断恢复

- **WHEN** prepare 部分完成后中断
- **THEN** 相同输入和 parser/config fingerprint 的重试 SHALL 复用已验证缓存与 checkpoint
- **AND** parser 或配置变化 SHALL 使旧缓存失效或 fail closed

#### Scenario: 稳定 blocker 分类

- **WHEN** 对象不能形成唯一完整共识
- **THEN** 系统 SHALL 使用设计中冻结的稳定 blocker 代码并保存来源、字段、原始值、规范值和可读说明
- **AND** MUST NOT 只记录自由文本异常

### Requirement: 身份底稿提交必须绑定审核 SHA 且只填充空字段

系统 MUST 先人工审核 prepare artifact，再生成绑定输入、qualification、候选、blocker、工作簿、来源证据和配置指纹的精确批准 SHA。首次 commit MUST 要求该 SHA 和独立批准人，在一个整批事务内复验全部目标，只可填充仍为空且未人工锁定的 `sire_text`、`dam_text` 和 `birth_date`，并保存来源引用、OperationLog 和数据库唯一 receipt。任一漂移 MUST 使整批回滚。

#### Scenario: 精确批准后提交

- **WHEN** `candidate_pass` 已被精确 SHA 批准，目标字段仍为空且未锁定
- **THEN** commit SHALL 写入三个身份字段和对应来源引用
- **AND** MUST NOT 改变公开状态、中文名、履历、完整度终态或 P0 来源

#### Scenario: partial 或 blocker 被批准

- **WHEN** 批准集合包含 `candidate_partial` 或 blocker
- **THEN** 系统 MUST 在数据库写入前拒绝整个批准集合

#### Scenario: 重复提交

- **WHEN** 使用相同批准 SHA 重复执行已成功 commit
- **THEN** 系统 SHALL 以成功 receipt 复验字段、来源引用和审计记录后返回同一份零写报告
- **AND** 没有该 receipt 时，即使字段值相同也 MUST 视为漂移

### Requirement: 首批生产放大前必须通过 20 匹 PoC

系统 MUST 在首次 100 匹真实 prepare 前，从最新只读快照的第二层对象选择 20 个唯一 profile：
每个对象须具有唯一数字型 Netkeiba ID、不完整身份底稿、冻结资格赛事、官方赛事 URL、赛事日期、
马号和精确马名，并与旧 blocker 零交集。PoC SHALL 验证“赛事上下文 → 唯一官方马匹锚点”、
JRA/NAR provider、Netkeiba 对账、缓存、blocker、请求预算和关网恢复。每个 profile SHALL 被分配
一个且仅一个主 `sample_stratum`：10 匹现役、5 匹退役、2 匹具有外国出生线索、2 匹同时具有
中央/地方赛事上下文或经审核转籍线索、1 匹障碍重赏马，五类计数之和必须恰为 20；交叉属性只能
作为 `secondary_traits`，不得重复计数。外国出生和转籍线索只可保存到 `sampling_clue[]` 作为
抽样依据，MUST NOT 视为日本训练身份或转籍事实，也 MUST NOT 写入 `training_evidence[]`；
触网后仍须由官方档案确认训练范围。样本还 SHALL 覆盖 G1/G2/G3 优先层级及 JRA/NAR provider。
候选池无法满足时必须报告缺口，不得静默替换。

#### Scenario: PoC 通过

- **WHEN** 20/20 对象均先形成唯一官方锚点或稳定上下文 blocker，最终进入 pass/partial/稳定
  blocker、未知异常为零，且至少 1 匹完成赛事上下文解析和完整双源 pass、请求账本闭合且常驻
  网络恢复 false
- **THEN** 操作者 MAY 规划最多 100 匹 prepare
- **AND** PoC 本身 MUST NOT 写数据库或自动批准

#### Scenario: PoC 失败

- **WHEN** 任一 provider 结构、访问边界、请求预算、缓存、证据合同或样本构成失败
- **THEN** 系统 MUST 停止放大
- **AND** MUST NOT 通过换来源、扩大搜索或放宽四字段锁强行继续
