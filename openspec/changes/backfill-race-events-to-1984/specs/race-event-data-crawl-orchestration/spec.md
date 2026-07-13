## MODIFIED Requirements

### Requirement: 第一版必须覆盖三类赛事详情模块
系统 SHALL 在历史回填范围内同时支持 `runners`、`results` 和 `history_winners` 三类产品能力，并对同一目标范围采用相同历史深度。held/due 年度必须取得独立出马表或从可信完整赛果派生 runners，必须取得可信完整 results；该年度冠军 SHALL 由正式赛果第一名提供，只有缺完整赛果但有可信冠军证据时才使用 `RaceEventHistoryWinner` 补位。系统 MUST NOT 为每个年度赛事复制整张历届冠军表。

#### Scenario: plan 缺少任一目标能力
- **WHEN** plan 声明历史回填但没有 runners、results 或系列冠军覆盖能力
- **THEN** 系统 MUST 拒绝将该 plan 标记为完整历史回填计划
- **AND** 系统 MUST 在错误或审计结果中列出缺失能力

#### Scenario: 三类能力历史范围不一致
- **WHEN** 同一地区、来源和赛事系列的 runners、results、冠军覆盖声明不同历史起点或年份范围
- **THEN** 系统 MUST 将该批次标记为 invalid 或 incomplete
- **AND** 系统 MUST 不允许该批次进入 apply 候选

#### Scenario: 完整赛果派生出马表
- **WHEN** 历史来源提供包含全部参赛者的可信完整赛果但没有独立 racecard
- **THEN** 系统 MAY 从赛果派生 runners
- **AND** 派生记录 MUST 标记 `derived_from_results` 且缺失字段保持为空

#### Scenario: 年度冠军由正式赛果提供
- **WHEN** 某年度赛事已有正式完整赛果
- **THEN** 该年度冠军覆盖 SHALL 由赛果第一名满足
- **AND** 系统 MUST NOT 要求再复制一份相同的历史冠军候选

## ADDED Requirements

### Requirement: 历史详情目标必须先完成日期与直接来源发现
系统 SHALL 在历史详情 prepare 前为每个目标发现并审核精确 `local_date` 与直接来源页面。发现结果 MUST 绑定不可变selection snapshot、inventory manifest SHA、target SHA、请求账本和source cache manifest；selection snapshot中的目标即使没有候选也 MUST 留在缺口账本，不得被省略、替换或静默进入已完成scope。

#### Scenario: 年度目录只有年份没有日期
- **WHEN** 已批准年度目标只有年份、赛事名和赛场
- **THEN** 系统 MUST 先执行 date/source discovery
- **AND** 详情 adapter MUST NOT 因空日期跳过后把目标计为已处理

#### Scenario: 难抓目标没有发现候选
- **WHEN** selection snapshot包含某target_id但本轮没有日期候选
- **THEN** discovery artifact MUST 为该target_id记录missing_candidate缺口
- **AND** 系统 MUST NOT 通过省略该target_id或替换为其他目标改善完成率

#### Scenario: 发现结果通过审核
- **WHEN** 日期、赛场、年度显示名和直接结果页唯一匹配且 manifest 已批准
- **THEN** apply SHALL 保留既有来源证据并只补充该目标的 `local_date`、稳定直接URL、detail discovery provenance和工作流状态
- **AND** apply MUST NOT 改变已批准 series/year/expectation 身份

#### Scenario: 届次年份与实际举办年份不同
- **WHEN** 权威来源证明某年度届次在相邻自然年举办，例如2001届布里斯托尔新秀跨栏赛于2002-01-11举行
- **THEN** `year` SHALL 保持年度届次年份且 `local_date` SHALL 保存实际举办日期
- **AND** 候选 MUST 记录 `actual_year`、跨年原因和权威证据并经过人工批准
- **AND** 系统 MUST NOT 仅因 `local_date.year != year` 拒绝该目标

#### Scenario: 日期来源批准后进入可抓取状态
- **WHEN** pending held目标具有已批准日期和结果页或权威直接赛事页
- **THEN** apply SHALL 在同一事务中把目标转为ready并materialize draft RaceEvent
- **AND** apply SHALL 输出变更前后target SHA映射
- **AND** 任一步失败 MUST 回滚整批日期、来源、状态和赛事对象变更

#### Scenario: 取消赛事只有取消证据
- **WHEN** cancelled目标没有赛果页但有已批准预定日期和权威取消公告
- **THEN** 系统 SHALL 接受 `cancellation_url` 作为直接证据并materialize cancelled RaceEvent
- **AND** 系统 MUST NOT 为其伪造runners或results

#### Scenario: 同一目标出现多个日期或跨赛事候选
- **WHEN** 来源返回多个无法唯一归属的日期或直接页面
- **THEN** 系统 MUST 标记 `identity_review_required`
- **AND** 系统 MUST NOT materialize 或抓取该目标详情

### Requirement: 赛前声明、实际出走、退出马与赛果来源必须分离
系统 SHALL 分别记录 `declared_runners_url`、`actual_runners_url`、`non_runner_url`、`result_url` 和 `cancellation_url` 及其来源权威。完整赛果 MAY 派生实际出走名单，但 MUST 标记 `derived_from_results`，且 MUST NOT 冒充赛前声明出马表。

#### Scenario: 只有完整 Full Result 或 chart
- **WHEN** 历史来源提供全体实际出走马和完整赛果但没有赛前 racecard
- **THEN** 系统 MAY 从赛果派生 actual runners
- **AND** `declared runners` 状态 MUST 保持缺失

#### Scenario: Sky Sports 或 HKJC 保存赛前页面
- **WHEN** 独立赛前页面列出声明出马及退出马
- **THEN** 系统 SHALL 分别保存 declared runners 与 non-runners 证据
- **AND** 不得用最终名次覆盖赛前马号或闸位顺序

### Requirement: 日期与详情来源必须遵循地区权威矩阵
系统 MUST 使用设计中批准的五地区来源优先级。低权威来源只可补空；同级或更高权威来源冲突 MUST 阻断相应目标。英国2000年前后历史赛果 SHALL 以 Racing Post Full Result 为主，Sky Sports Racecard 补赛前信息；美国 SHALL 以 Equibase chart 为主，美国障碍赛 SHALL 支持 NSA。

#### Scenario: BHA 无法覆盖2000年英国赛事
- **WHEN** 英国目标年份早于BHA公开结果覆盖范围
- **THEN** 系统 MUST 使用 Racing Post 等批准历史主源
- **AND** 系统 MUST NOT 把BHA无结果解释为赛事未举办

#### Scenario: 美国平地与障碍来源不同
- **WHEN** 美国目标为平地Stakes
- **THEN** 系统 SHALL 优先使用Equibase/BRIS chart
- **AND WHEN** 目标为NSA障碍赛事
- **THEN** 系统 SHALL 使用NSA作为重要权威来源

#### Scenario: Equibase单场PDF身份复核
- **WHEN** 系统从Equibase单场PDF生成美国平地赛事详情候选
- **THEN** 系统 SHALL 复核PDF页眉日期、赛场和场次号，并保留`1a`等联合投注编号
- **AND** 任一身份字段不符时 SHALL 阻断该目标，不生成可写入候选

### Requirement: 直接来源URL必须受adapter域名边界约束
系统 MUST 为每个日期发现和详情adapter声明允许的HTTPS host，并校验候选URL、每次重定向和最终URL。artifact中的URL不得成为任意网络抓取入口；内网地址、非HTTP(S) scheme、未批准host或越界重定向 MUST fail closed。

#### Scenario: 批准artifact含有未授权host
- **WHEN** 候选URL指向adapter白名单外域名或重定向到白名单外域名
- **THEN** 系统 MUST 拒绝请求并记录URL边界错误
- **AND** 该目标 MUST 留在缺口账本

### Requirement: materialize 后发现的补充详情源必须独立审批
系统 SHALL 为已经 ready/materialized 的目标提供独立 detail-source artifact，以批准后发现的更完整直接详情页。artifact MUST 绑定当前 target SHA、inventory SHA、provider/authority、直接 URL 和实际 source-cache capture 的路径、大小及 SHA-256；apply MUST 同时非破坏更新 target 与 RaceEvent 来源证据，不得改变赛事身份、状态或可见性。

#### Scenario: 法国日期页之后发现完整专业数据库详情页
- **WHEN** ready 法国目标原先以 France Galop 页面确定日期，后续从批准 host 找到 ZEturf 完整详情页
- **THEN** 系统 SHALL 生成独立 detail-source manifest/review/approval
- **AND** 批准 apply SHALL 保留原 France Galop 证据并追加 ZEturf 直接来源
- **AND** 目标 SHALL 保持 ready，RaceEvent SHALL 保持 draft

#### Scenario: 同一URL的缓存正文发生变化
- **WHEN** packager 使用的source cache与批准capture的source URL、大小或SHA-256任一不一致
- **THEN** 系统 MUST 拒绝打包
- **AND** 不得因URL字符串相同而接受新正文

#### Scenario: 补充来源批准后目标发生漂移
- **WHEN** detail-source审批后target SHA、inventory SHA或ready/materialized状态发生变化
- **THEN** apply MUST 在写入任何target或RaceEvent前整批失败
- **AND** OperationLog不得记录成功

### Requirement: 各地区赛事距离必须保留来源单位语义
系统 SHALL 保留来源 `distance_text`，并在provenance中显式记录可解析的数值、单位和计量体系。英国来源的mile/furlong/yard与米制metre MUST 分开解释；没有显式单位或来源定义时不得猜测。标准化距离 MAY 作为带公式的派生值保存，但 MUST NOT 覆盖来源原文。

#### Scenario: 英国距离写作3m 210y
- **WHEN** 英国来源提供 `3m 210y`
- **THEN** 系统 SHALL 将 `m` 解释为mile、`y`解释为yard并保留原文
- **AND** 系统 MUST NOT 把该距离解释为3210 metres

#### Scenario: 法国距离写作2400m
- **WHEN** 法国来源定义距离为 `2400m`
- **THEN** 系统 SHALL 将 `m` 解释为metre并保留来源定义
- **AND** 任何标准化值 MUST 记录换算来源或公式

### Requirement: 分阶段首批验收必须匹配已批准总账年代范围
系统 SHALL 先对1998–2026总账执行五地区跨年代首批验收，覆盖2000年前后、中间年份和近年；1984–1997总账完成后 SHALL 另行执行五地区早期年代验收。任一阶段不得要求选择尚未建账的年代，也不得以较新页面通过代替旧页面结构验收。

#### Scenario: 当前仅批准1998–2026总账
- **WHEN** 系统生成第一批应到清单
- **THEN** 每地区 SHALL 选择3个系列和约9个目标
- **AND** 地区样本 SHALL 覆盖2000年前后、中间年份和近年

#### Scenario: 第一批目标尚未发现日期
- **WHEN** 约45个样本目标仍为pending且没有RaceEvent
- **THEN** 预发现选择器 SHALL 从批准总账按身份和时间锚点固定target_id
- **AND** 选择器 MUST NOT 要求目标已经ready或已有RaceEvent
- **AND** 日期apply后详情计划 MUST 继续使用相同target_id并绑定新的target SHA，不得替换抓取失败目标

#### Scenario: 后续批准1984–1997总账
- **WHEN** 系统准备抓取1984–1997详情
- **THEN** 系统 MUST 先执行五地区早期年代验收
- **AND** 未通过的地区 MUST NOT 进入该年代带扩大批次

### Requirement: 历史批次必须从已批准总账切分
系统 MUST 从已批准年度应到总账选择目标并生成 batch plan。plan MAY 缩小到批准 scope，但 MUST NOT 添加总账外目标、删除未解决目标的总账记录或自行改变目标 expectation/resolution 状态。

#### Scenario: plan 包含总账外目标
- **WHEN** 批次 plan 声明的 series/year 不在批准总账
- **THEN** 编排器 MUST fail closed
- **AND** 系统 MUST NOT 发起网络请求

#### Scenario: 批次只选择完整可执行目标
- **WHEN** 总账同时包含 ready、source unavailable 和 identity review 目标
- **THEN** plan MAY 只选择 ready 目标执行
- **AND** 未选择缺口 MUST 继续保留在总账

### Requirement: 当前阶段第一批历史验收必须跨五地区和三个时间锚点
系统 MUST 为 1998–2026 阶段第一批选择每地区 3 个代表系列和约 9 个真实 held/cancelled 年度目标，地区样本整体覆盖 2000 年前后、阶段中段和近年，目标约 45 个年度赛事。长寿现役系列 SHOULD 跨三个时间锚点取样；历史停办系列无法覆盖近年时 MUST 在其真实举办范围取代表年份，并由同地区其他系列补足近年锚点。样本 MUST 包含长寿、改名/迁场以及历史独有或停办系列。

#### Scenario: 某地区缺少当前阶段时间锚点
- **WHEN** 1998–2026 第一批计划中某地区没有 2000 年前后、阶段中段或近年样本
- **THEN** 第一批校验 MUST 失败
- **AND** 系统 SHALL 列出缺失的地区和时间锚点

#### Scenario: 1998–2026总账尚未包含1980年代
- **WHEN** 当前批准总账只覆盖1998–2026
- **THEN** 第一批校验 MUST NOT 要求1980年代目标
- **AND** 系统 MUST 保留1984–1997总账批准后的独立早期年代验收门

#### Scenario: 五地区当前阶段样本完整
- **WHEN** 五地区均满足 3 系列和 3 个当前阶段时间锚点
- **THEN** 第一批计划 MAY 进入应到审批

### Requirement: 全量批次必须按已批准年代带保持地区同步
系统 SHALL 先按 `2016–2025`、`2006–2015`、`1998–2005` 从新到旧完成已批准的 1998–2026 总账；1984–1997 总账完成身份审核和五地区早期年代验收后，系统 SHALL 再为该阶段生成独立年代带。每个年代带 MUST 覆盖五地区。标准批次每地区最多 50 个 held/cancelled 年度目标；地区进度 MUST 按同年代带 accounted/imported 的 due 目标数计算，任何地区不得比最慢地区领先超过 100 个标准目标。

#### Scenario: 生成年代带标准批次artifact
- **WHEN** 操作者为已批准总账生成指定年代带的下一标准批次
- **THEN** 系统 SHALL 只选择该年代带内pending且未materialize的held/cancelled目标
- **AND** 输出 SHALL 包含不可变selection snapshot、完整审核CSV、地区分母summary、manifest和pending approval
- **AND** 空批次、重复target、inventory SHA不符或年代带外目标 MUST fail closed

#### Scenario: 单地区试图连续领先
- **WHEN** 某地区将比最慢地区领先超过 100 个同年代带标准目标
- **THEN** 批次生成器 MUST 阻止新计划
- **AND** 系统 SHALL 提示需要推进落后地区

#### Scenario: plan 修改标准批次上限
- **WHEN** 操作者需要调整每地区 50 个目标的默认上限
- **THEN** 新上限 MUST 写入 plan 和应到审批
- **AND** 地区进度护栏 MUST 继续按标准目标数计算而不是按 run 数量计算

### Requirement: 历史年度 URL 身份必须稳定
系统 MUST 从已批准稳定系列 key 生成带地区前缀的历史年度 slug，并保持 `(year, slug)` 和 `(race_series, year)` 唯一。年度赛事创建后，名称、翻译、冠名或马场修正 MUST NOT 自动改变 slug；现有年度 URL MUST 保持不变。

#### Scenario: 历史冠名后续修正
- **WHEN** 已创建年度赛事的赛事名称或中文译名被修正
- **THEN** 其 slug 和公开 URL MUST 保持不变

#### Scenario: 同年 slug 冲突
- **WHEN** 建议 slug 与同年其他赛事冲突
- **THEN** 基础年度 apply MUST 在写入前阻断
- **AND** 冲突 MUST 进入身份审核

### Requirement: Coverage 必须允许完整 scope 独立应用
系统 SHALL 按年度目标拆分完整 scope 和缺口 scope。完整 scope MAY 继续 dry-run、apply-check 和正式写入；`source_unavailable / identity_review_required` 等缺口 MUST 留在总账且不得进入批准候选。

#### Scenario: 同批存在完整和缺失目标
- **WHEN** 45 个目标中 40 个三类能力完整、5 个来源暂不可用
- **THEN** coverage SHALL 为 40 个完整目标生成可审核 apply scope
- **AND** 5 个缺口 SHALL 留在 gap ledger 且不计为完成

#### Scenario: 缺口被空候选占位
- **WHEN** adapter 为不可用目标输出空 items 试图满足模块键
- **THEN** coverage MUST 拒绝该目标
- **AND** 系统 MUST NOT 将其计入完整 scope

### Requirement: 历史写入必须保留字段级变更和人工锁
系统 SHALL 对已存在年度赛事生成字段级 before/after/source diff。更高权威或更完整来源只有在新批准批次中才能更新未人工锁定字段；人工锁定字段 MUST 保留。apply artifact MUST 保存回滚所需旧值。

#### Scenario: 更高权威来源补齐空字段
- **WHEN** 新官方来源补齐现有空字段且字段未人工锁定
- **THEN** 新批准批次 MAY 更新该字段
- **AND** 系统 SHALL 保存旧值、来源和变更原因

#### Scenario: 新来源试图覆盖人工字段
- **WHEN** 候选与人工锁定字段不同
- **THEN** apply MUST 保留人工值
- **AND** diff SHALL 显示冲突和跳过原因

#### Scenario: 日期发现已保存显式距离单位但年度赛事仍为裸数字
- **WHEN** 已批准日期来源在 provenance 中保存 `2400m` 或 `3m 210y`，而 materialize 后的年度赛事仍保留目录裸数字
- **THEN** 系统 SHALL 通过独立权威字段批次生成 before/after diff 并更新未锁定的 `RaceEvent.distance_text`
- **AND** 批次 MUST 保留原目录值、显式单位来源、snapshot、parser 和变更 artifact，不得按地区猜测裸数字
- **AND** 字段更新后详情候选 MUST 重新绑定新的 target SHA

#### Scenario: 权威字段批次中一个 target 在审批后漂移
- **WHEN** 批次 JSONL 已批准，但任一 target 的字段、provenance、状态或 event identity 在 apply 前变化
- **THEN** apply MUST 在写入任何 scope 前失败
- **AND** 整批年度赛事、target provenance 和 OperationLog MUST 保持不变

#### Scenario: 权威字段批次中途写入失败
- **WHEN** 前若干 scope 已进入外层事务而后续 scope 抛出校验或数据库异常
- **THEN** 系统 MUST 回滚整批字段变更和日志
- **AND** 运营方 MAY 修复候选后重新生成新 SHA 的批次，不得续用部分成功状态

### Requirement: 写后核验必须回写总账而不删除缺口
系统 MUST 在每个 apply scope 后核对年度赛事、runner、result、冠军覆盖、可见性和来源计数，并将成功目标更新为 imported。失败或未选目标 MUST 保留原状态和证据。

#### Scenario: 部分 scope 写入成功
- **WHEN** 某批准 scope 原子写入并通过写后计数
- **THEN** 对应目标 SHALL 更新为 imported
- **AND** 同批其他缺口状态 MUST 保持不变

#### Scenario: 写后计数不符
- **WHEN** 实际 runner/result 数量与批准 artifact 不一致
- **THEN** 总账 MUST NOT 标记 imported
- **AND** 系统 MUST 生成写后 blocker 和回滚指引

### Requirement: 历史批次关键状态必须写操作日志
系统 MUST 为 inventory commit、series mapping、永久不可得批准、publication transition、网络 run 开始/失败/恢复和写后核验记录操作或任务日志。日志 MUST 绑定 artifact SHA、目标范围、操作者、状态和摘要，且不得记录整页原件或敏感环境变量。

#### Scenario: 历史批次正式写入
- **WHEN** 批准 scope 完成或失败
- **THEN** 系统 MUST 记录批次身份、目标计数、结果和失败摘要

#### Scenario: 永久不可得获得批准
- **WHEN** 运营人员批准 permanently unavailable
- **THEN** 操作日志 MUST 记录批准人、年度目标和证据 manifest 身份
