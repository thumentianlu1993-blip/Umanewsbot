## ADDED Requirements

### Requirement: 日本候选有 netkeiba key 时必须经 netkeiba ID 直取抓取

系统 SHALL 为携带 `netkeiba:{id}` identity key 的日本候选直接抓取 netkeiba 马匹页、战绩页与血统页，MUST NOT 依赖名称检索消歧；payload 的 netkeiba ID 与候选 key 完全一致才构成 provider-bound 身份；页面马名与候选名规范化不一致时系统 SHALL fail closed 并记录身份冲突。无 netkeiba key 的候选 SHALL 保持既有 JBIS 检索路径。页面结构无法识别时系统 SHALL 记录不可解析并 fail closed，MUST NOT 猜测字段值。

#### Scenario: ID 直取无检索歧义

- **WHEN** 某日本候选携带 `netkeiba:{id}` key 且 JBIS 名称检索存在同名马
- **THEN** 系统 SHALL 经 netkeiba ID 直取页面完成 prepare，身份锁按 provider-bound 通过
- **AND** 页面提取的父母、出生日期 SHALL 满足四字段口径

#### Scenario: 马名不符 fail closed

- **WHEN** netkeiba 页面马名与候选名规范化比对不一致
- **THEN** 系统 MUST NOT 写入该候选的任何字段，并记录身份冲突

#### Scenario: 生涯总数与逐场数对账

- **WHEN** 马匹页的通算成績总数与战绩页逐场记录数不一致
- **THEN** 系统 SHALL 记录生涯缺口，MUST NOT 标记生涯完整

#### Scenario: 结构变化 fail closed

- **WHEN** 页面结构无法被解析器识别（缺表、改版）
- **THEN** 系统 SHALL 记录不可解析并阻断该候选，MUST NOT 猜测字段值

#### Scenario: 已注销马标题按精确状态词解析

- **WHEN** netkeiba 标题使用 `抹消　牡　黒鹿毛` 等已知已注销状态形态
- **THEN** 系统 SHALL 独立解析状态、性别和毛色并继续处理候选
- **AND** 未知状态、性别或毛色仍 SHALL fail closed，MUST NOT 通过宽松正则猜测字段

#### Scenario: 候选部分期望身份字段保持完整锁并给出字段级诊断

- **WHEN** 候选仅携带父名、母名或出生年中的部分期望字段
- **THEN** 系统 SHALL 保持完整四字段期望锁、阻断候选并记录候选缺少的具体期望字段
- **AND** 系统 MUST NOT 以空值、默认值或同名推断补齐身份

#### Scenario: 解析器规则变化不得复用旧 checkpoint

- **WHEN** netkeiba 解析语义版本发生变化且旧批次已有 succeeded staging
- **THEN** 系统 SHALL 使批次输入指纹发生变化或拒绝旧 approval binding
- **AND** 运维人员 SHALL 通过 abandon 后重新 select/approve 建立新批次，不得手改 `state.json`

#### Scenario: 旧版 netkeiba canonical cache 不得绕过新解析器

- **WHEN** netkeiba canonical cache 缺少当前 parser version 或版本不匹配
- **THEN** 系统 SHALL 将其视为 cache miss，并在网络门禁与预算允许时重新抓取三页
- **AND** 刷新成功后 SHALL 并发安全地原子替换 stale cache，当前调用与竞争调用均只使用同一份当前版本 canonical payload
- **AND** 该规则 MUST NOT 改变 JBIS 或其他地区的既有 cache 兼容语义

### Requirement: 生产提交前必须冻结不带批准语义的发布候选

系统 SHALL 在人工 xlsx 复审后、任何生产马匹写入或自动首发前生成不可变 release candidate。
该 candidate SHALL 绑定批次 manifest、完整子集 bundle、commit artifact、预计数据库动作与
自动首发范围的精确 SHA；MUST NOT 写入 `approved_by`、MUST NOT 产生正式发布批准账本事件，
且 MUST NOT 修改马匹数据库或公开状态。正式 commit SHALL 要求调用方提供已获用户授权的精确
candidate SHA，并生成反向绑定该 SHA 的正式 release manifest；candidate、artifact、bundle、
生产映射快照或自动首发范围任一漂移时系统 SHALL fail closed。

#### Scenario: 准备发布候选不写库也不公开

- **WHEN** 操作者对人工复审通过的完整子集执行 `prepare-release`
- **THEN** 系统 SHALL 生成 release candidate、commit artifact、预计数据库动作和自动首发范围
- **AND** 马匹资料、审核状态、公开状态和 OperationLog SHALL 保持不变
- **AND** 审批账本 MUST NOT 出现 `release_approved`

#### Scenario: 正式提交绑定用户批准的精确候选

- **WHEN** 用户针对 release-candidate SHA、完整子集、预计写入和自动首发范围明确授权
- **THEN** 正式 commit SHALL 要求该精确 SHA 并重新验证其全部绑定
- **AND** 正式 release manifest SHALL 记录 `approved_by` 并绑定 release-candidate SHA
- **AND** 缺失、错误、篡改或过期的 candidate SHA SHALL 阻断写入与自动首发

#### Scenario: 准备后生产状态漂移

- **WHEN** release candidate 生成后，目标 profile、映射快照、artifact 或自动首发范围发生漂移
- **THEN** 正式 commit SHALL 在事务写入前 fail closed
- **AND** 操作者 SHALL 重新执行 `prepare-release` 并取得新 SHA 的授权

#### Scenario: 自动首发范围仅包含人工通过的完整子集

- **WHEN** 同一批次同时包含人工复审通过的完整资料和未完成 blocker
- **THEN** release candidate 与正式自动首发目标 SHALL 只包含 commit artifact 中的复审通过行
- **AND** 未进入 artifact 的 blocker profile MUST NOT 因其位于同一地区 batch manifest 而进入自动首发

#### Scenario: 相同冻结输入重复准备候选

- **WHEN** bundle、mapping 审核时间、生产快照和目标状态均未变化且操作者重复执行 `prepare-release`
- **THEN** commit artifact 与 release candidate SHALL 字节一致且 SHA 不变
- **AND** 系统 SHALL NOT 重复追加同一 candidate SHA 的准备证据事件

#### Scenario: 并发准备同一候选

- **WHEN** 两个操作者或进程对相同冻结输入并发执行 `prepare-release`
- **THEN** 系统 SHALL 在同一 batch serial/file lock 内原子发布 candidate、state 和账本证据
- **AND** 最终 SHALL 只有一个 candidate SHA 和一条对应的准备证据事件

#### Scenario: 批准后中断并重试正式提交

- **WHEN** 正式 release manifest 或批准账本已经生成，但进程在 state 更新、数据库提交或自动首发完成前中断
- **THEN** 相同 candidate SHA 的重试 SHALL 复用原正式 manifest、批准时间与 release SHA
- **AND** 系统 SHALL NOT 重复追加 `release_approved`
- **AND** publish retry SHALL 继续使用 candidate 冻结的人工复审范围

#### Scenario: 已批准但未落库的旧候选被新授权候选替代

- **WHEN** 旧 candidate 已生成正式 manifest，但其 artifact 没有完整落库，操作者修正漂移后重新准备并取得新 candidate SHA 的明确授权
- **THEN** 系统 SHALL 使用候选专属不可变路径保留旧证据并允许新 candidate 生成新的 v2 manifest
- **AND** 账本 SHALL 记录旧、新 candidate/release 的 superseded 关系
- **AND** 若旧 artifact 已有完整落库证据，系统 MUST 拒绝替换并只允许旧 candidate 的幂等恢复

#### Scenario: 正式清单生成后、数据库提交前发布资格漂移

- **WHEN** v2 release manifest 已生成但 artifact 尚未落库，目标 profile 的隐藏、审核或人工锁状态发生变化
- **THEN** commit 重试 SHALL 重新计算并比较 candidate 的自动首发范围与 disposition
- **AND** 任一差异 SHALL 在数据库写入前 fail closed，并要求生成和授权新的 candidate SHA

#### Scenario: 历史 v1 发布清单继续可复验

- **WHEN** 系统复验升级前生成的可信 `p0_horse_production_release_manifest.v1`
- **THEN** validator SHALL 按历史五项 bindings 合同继续接受有效清单
- **AND** 新生成的 rolling release SHALL 使用要求 `release_candidate_sha256` 的 v2 schema

#### Scenario: 旧提交状态缺少冻结发布范围

- **WHEN** 操作者对升级前的 commit state 执行 `retry-publish`，且该 state 没有 candidate 冻结的 `publish_scope`
- **THEN** 系统 SHALL fail closed 并报告需要人工审计恢复
- **AND** 系统 MUST NOT 用空目标集合调用发布服务或把 publish stage 标记成功

#### Scenario: bundle 声明与实际输入文件不一致

- **WHEN** bundle state 记录后 research、mapping 或 authority 文件被替换，实际 SHA 与声明不一致
- **THEN** `prepare-release` SHALL 在 artifact、candidate、state 和账本落盘前 fail closed
- **AND** candidate bindings SHALL 只使用 commit artifact 实际读取并验证的输入 SHA

#### Scenario: 已落库候选在后续 bundle 后恢复

- **WHEN** candidate A 的 artifact 已完整落库但 commit/publish checkpoint 未完成，随后同地区重新生成 region-current bundle
- **THEN** A 的幂等恢复 SHALL 使用其 SHA 专属不可变 research、mapping、authority、artifact、candidate 和 release 输入
- **AND** current bundle 的覆盖 MUST NOT 阻断 A 的 publish recovery
- **AND** 新 candidate B 仍 MUST 因 A 已落库而被拒绝

#### Scenario: commit 等待串行锁期间 combined 发生变化

- **WHEN** commit 在等待 batch serial/file lock 期间 combined artifact 被另一路径更新
- **THEN** 系统 SHALL 在取得锁后读取并验证当前 SHA，不得沿用锁外旧值
- **AND** 未落库 candidate 的 combined binding 漂移 SHALL 在批准或数据库写入前 fail closed

#### Scenario: 禁止新建绕过候选的 v1 正式清单

- **WHEN** rolling release builder 未提供精确 release-candidate SHA
- **THEN** 系统 SHALL 拒绝生成 release manifest 和 `release_approved` 事件
- **AND** v1 schema 支持 SHALL 仅用于读取和复验升级前已有证据

#### Scenario: 冻结为不尝试发布的对象后来解除阻断

- **WHEN** candidate 将既有 profile 冻结为 `block_hidden`、`block_manual_lock` 或 `skip_already_published`，且其 live 状态在 commit 后或 retry 前变化
- **THEN** 自动首发 SHALL NOT 把该 profile 加入发布调用
- **AND** 报告 SHALL 保留其冻结 disposition 和排除原因
- **AND** live publish gate SHALL 只能进一步收紧 `attempt_publish_after_commit` 集合

#### Scenario: prepare 与 bundle 并发修改批次状态

- **WHEN** `prepare` 或 `bundle` 与 `prepare-release` 或 `commit` 并发运行
- **THEN** 所有路径 SHALL 从产物生成到 state 写入持有同一 batch serial/file lock
- **AND** 系统 SHALL NOT 丢失 candidate/bundle state 更新或形成不一致的 evidence 组合

#### Scenario: 数据库提交后并发更新批次状态

- **WHEN** artifact 数据库事务已成功，但 commit checkpoint/publish state 尚未写入，另一 batch writer 更新了 state
- **THEN** commit SHALL 在写 checkpoint 前重新取得共享锁并重新加载、合并最新 state
- **AND** completion-run、commit checkpoint、publish state 与 ledger 更新 SHALL NOT 覆盖并发 writer 的有效字段

#### Scenario: builder 收到伪造 candidate SHA

- **WHEN** caller 向 rolling release builder 传入格式正确但没有对应真实冻结 candidate 的 SHA，或 candidate 文件的 schema、region、executor、artifact、bindings、expected actions、publish scope 任一不匹配
- **THEN** builder SHALL 在正式 manifest 与 `release_approved` 写入前 fail closed
- **AND** builder SHALL 只签发对真实普通文件 candidate 完整复验通过的 v2 release

#### Scenario: 新候选批准过程中发生崩溃

- **WHEN** candidate B 替代已批准但未落库的 candidate A，进程在新 manifest 写入、A superseded 事件或 B approved 事件任一点中断
- **THEN** 系统 SHALL NOT 留下 A 与 B 同时可执行的状态
- **AND** 恢复 SHALL 先幂等确认 A 已失效，再激活或补写 B 的唯一批准

#### Scenario: 正式执行期间收到另一候选或 abandon

- **WHEN** candidate A 已进入正式 approval-to-DB-to-publish 执行窗口，candidate B commit 或 `abandon` 并发到达
- **THEN** 独立 batch execution lock SHALL 串行化完整执行
- **AND** B MUST NOT 在 A 的 DB gap supersede A
- **AND** abandon 返回成功后 MUST NOT 再发生该批 DB 写入或自动发布

#### Scenario: release 文件落盘后、批准账本前被篡改

- **WHEN** v2 release manifest 已重命名但 `release_approved` 尚未追加，文件内容、文件名 SHA、元数据或 ledger path 随后被修改
- **THEN** 恢复 SHALL fail closed，MUST NOT 为修改后的 bytes 补写批准事件
- **AND** 只有文件名 SHA、当前 bytes 和完整签发合同一致的普通文件可恢复

#### Scenario: PostgreSQL 自动发布锁

- **WHEN** 系统在 PostgreSQL autocommit 环境执行 inline 或 retry publish
- **THEN** 每个 profile SHALL 在 `transaction.atomic()` 内通过 `select_for_update()` 读取、重验 live gate 并迁移状态
- **AND** 系统 MUST NOT 在事务外求值 locking QuerySet

#### Scenario: direct apply 尝试使用已失效候选

- **WHEN** caller 绕过 batch command，直接向 production dry-run/commit 提供 candidate A 的 v2 release，而 ledger 中 A 后续已被 candidate B supersede
- **THEN** 通用 validator SHALL 加载真实 A candidate/evidence 并按 ledger 顺序判定其不再 active
- **AND** direct apply SHALL 在数据库事务前 fail closed

#### Scenario: 已落库批次被 abandon

- **WHEN** batch 已有 committed completion run、commit/publish checkpoint 或 committed manifest，操作者执行 `--abandon`
- **THEN** 系统 SHALL fail closed，保持原 committed/published 证据与终态
- **AND** 系统 MUST NOT 用 abandoned 状态暗示既有生产写入已撤回

#### Scenario: approvals ledger 出现 malformed 或 partial 行

- **WHEN** validator、builder 或 append 路径读取到任一非空 malformed/partial JSONL 行
- **THEN** 系统 SHALL fail closed，MUST NOT 跳过该行继续批准、supersede 或 apply
- **AND** 新 append SHALL 完整写入并 flush/fsync；破损尾部 SHALL 进入人工审计恢复

#### Scenario: 发布事务退出时失败及第三次重试

- **WHEN** 单匹发布事务在退出时回滚，或同一 publish scope 进行第三次及以后 retry
- **THEN** 回滚 profile SHALL 只计入 errors，不得同时计入 published
- **AND** cumulative published IDs SHALL 保留所有历史成功 ID

#### Scenario: 已批准未落库批次 abandon 后 direct apply

- **WHEN** v2 release 已批准但尚未落库，随后 batch 被成功 abandon，caller 再直接调用 production dry-run/commit
- **THEN** 通用 validator SHALL 因 state 或 manifest abandoned 在数据库事务前 fail closed
- **AND** abandoned batch MUST NOT 被 standalone 入口复活

#### Scenario: 历史 auto-first-publish 事件缺少新审计字段

- **WHEN** strict ledger 读取升级前无事件版本且没有 frozen exclusion 字段的合法 `auto_first_publish`
- **THEN** 系统 SHALL 按 legacy schema 接受，并在内存归一为空排除集合
- **AND** 新 v2 事件 SHALL 显式版本化并强制新字段
- **AND** parser MUST NOT 修改历史原始 JSONL

#### Scenario: direct v2 commit 校验后被另一候选 supersede

- **WHEN** standalone direct commit 的 candidate A 已通过 validation、尚未进入数据库事务，candidate B 尝试 supersede A
- **THEN** A 的 validation 到 DB/checkpoint SHALL 全程持有同一可重入 batch execution lock
- **AND** B SHALL 等待 A 完成；若 B 先激活，A 在锁内 SHALL 因 superseded 在 DB 前拒绝

#### Scenario: direct v2 使用当前 batch 或 combined 已漂移的候选

- **WHEN** candidate 批准后、artifact 尚未落库，当前 batch manifest 或 combined artifact 被合法重生成并产生新 SHA
- **THEN** standalone dry-run/commit SHALL 比较当前真实 bytes 与 candidate bindings 并 fail closed
- **AND** 已有 committed-run 精确证据的幂等恢复 SHALL 使用 candidate 不可变快照，不因 current 文件后续变化失效

#### Scenario: prepare 与同批正式提交并发

- **WHEN** `prepare` 正在更新同一 batch 的 artifact、workbook 或 checkpoint，正式 commit 同时到达
- **THEN** 两者 SHALL 先取得同一 batch execution lock，并保持 `execution -> state` 锁顺序
- **AND** commit SHALL 等待 prepare 完整退出后再读取 candidate、state 与账本

#### Scenario: completed commit 的只读重放证据

- **WHEN** 相同 candidate 的 commit 与 publish stage 均已完成，操作者普通重复 commit
- **THEN** 系统 SHALL 在任何 dry-run、数据库 apply 或 publish 调用前，完整复验 candidate、artifact、release、commit/publish checkpoint、committed completion run 与账本
- **AND** 只有唯一且精确匹配 batch、region、artifact、发布计数、published IDs 与冻结排除集合的 v2 `auto_first_publish` 成功事件存在时，系统 SHALL 返回冻结 commit/publish 结果
- **AND** 该重放 SHALL 对 completion run、source、audit、task log、业务表、state 与 ledger 零写入
- **AND** 证据缺失、重复或不匹配时系统 MUST fail closed 并要求人工审计，不得尝试修补 checkpoint 或重跑 apply/publish
