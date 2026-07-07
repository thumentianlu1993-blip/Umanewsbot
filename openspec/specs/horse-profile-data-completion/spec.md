# 马匹资料外部补全规格

## Purpose
为所有地区 P0 马提供可审计、可限速、可人工审核的外部资料补全流程。补全以 dry-run artifact 为门禁，默认不直接写库、不触发公开页外部网络请求，并以完整二代血统文本齐全作为成功口径。

## Requirements

### Requirement: 全地区 P0 马必须具备外部补全尝试路径
系统 SHALL 为所有地区 P0 马提供外部资料补全尝试路径。补全范围 MUST 覆盖日本、中国香港、英国、法国、美国和其它已配置地区；不得只实现日本马补全。

#### Scenario: 对所有地区输出补全报告
- **WHEN** 操作者执行全地区 P0 马补全 dry-run
- **THEN** 系统 SHALL 按地区输出 P0 总数、完整二代成功数、部分补全数、仅基础资料数、未命中数、歧义数、来源不可用数和限流数
- **AND** 每个地区 SHALL 有明确的补全尝试状态或未尝试原因

#### Scenario: 地区来源不可用不阻塞其它地区
- **WHEN** 某地区外部来源不可访问、返回限流或解析失败
- **THEN** 系统 SHALL 将该地区马匹标记为对应失败原因
- **AND** 继续处理其它地区或其它批次

### Requirement: 完整二代补全成功必须六项文本齐全
系统 SHALL 将父、母、父父、父母、母父、母母六项血统文本均存在作为完整二代补全成功标准。只有基础资料、别名、父母两项或父母母父三项不得计为成功。

#### Scenario: 六项齐全计为成功
- **WHEN** 外部补全结果包含父、母、父父、父母、母父、母母六项非空文本
- **THEN** 系统 SHALL 将该马匹统计为 `complete_pedigree_2gen`

#### Scenario: 缺任一项计为部分补全
- **WHEN** 外部补全结果缺少六项血统中的任意一项
- **THEN** 系统 SHALL 不得将该马匹计为完整二代成功
- **AND** 报告 SHALL 列出缺失字段

#### Scenario: 文本齐全不要求关联对象
- **WHEN** 六项血统文本齐全但部分项没有 `TermEntry` 或 `HorseProfile` 关联
- **THEN** 系统 SHALL 仍将该马匹计为完整二代血统成功

### Requirement: 补全必须先 dry-run 后 commit
系统 MUST 提供 dry-run 和 commit 两阶段补全流程。真实写入 `HorseProfile`、`HorseRaceRecord` 或候选资料前，必须先输出可审核 dry-run artifact；未经确认不得自动 commit。

#### Scenario: dry-run 不写入主表
- **WHEN** 操作者执行外部补全 dry-run
- **THEN** 系统 SHALL 输出候选 diff、请求证据、来源 URL、补全状态和未补全原因
- **AND** 不得修改 `HorseProfile`、`HorseRaceRecord` 或公开状态

#### Scenario: commit 必须读取已审核 artifact
- **WHEN** 操作者执行补全 commit
- **THEN** 系统 MUST 要求提供已审核 dry-run artifact 和显式确认参数
- **AND** 只写入该 artifact 覆盖的马匹和字段
- **AND** 不得通过重新抓取外部来源后直接写库绕过 artifact 审核

#### Scenario: commit 输出写入统计
- **WHEN** commit 完成
- **THEN** 系统 SHALL 输出实际写入数、候选数、跳过数、冲突数、人工锁定跳过数和失败原因

### Requirement: 补全结果按可信度分流
系统 SHALL 根据匹配可信度将外部补全结果分流到草稿字段或候选资料。唯一高可信命中可写入未锁定草稿字段；歧义、冲突或跨地区不一致必须进入候选或失败报告。

#### Scenario: 唯一高可信命中写入草稿字段
- **WHEN** 主 `TermEntry` 能唯一匹配到外部马，并且来源和地区可信
- **THEN** commit SHALL 写入未被人工锁定的基础资料和血统文本字段
- **AND** 保存 `source_refs`、来源 URL 和抓取时间

#### Scenario: 歧义命中进入候选
- **WHEN** 同一主 `TermEntry` 匹配多个外部马或地区/语言证据冲突
- **THEN** 系统 SHALL 创建 `HorseProfileDataCandidate` 或在 dry-run 中标记 `ambiguous`
- **AND** 不得直接覆盖 `HorseProfile`

#### Scenario: 人工锁定字段不被覆盖
- **WHEN** 外部补全结果包含已在 `manual_lock_flags` 中锁定的字段
- **THEN** 系统 SHALL 跳过该字段
- **AND** 在 diff 和 commit summary 中记录 `manual_lock_skipped`

### Requirement: 候选资料必须按模块管理
系统 SHALL 使用 `HorseProfileDataCandidate` 管理外部补全候选。候选模块 MUST 至少支持 `profile`、`pedigree`、`race_record` 和 `aliases`。

#### Scenario: 基础资料候选
- **WHEN** 外部来源提供出生日期、性别、毛色、地区、国家、马主或练马师
- **THEN** 系统 SHALL 将其归入 `profile` 候选或可直接应用字段

#### Scenario: 血统候选
- **WHEN** 外部来源提供父、母、父父、父母、母父或母母
- **THEN** 系统 SHALL 将其归入 `pedigree` 候选
- **AND** 包含文本值和可选 `TermEntry` / `HorseProfile` 关联建议

#### Scenario: 参赛履历候选
- **WHEN** 外部来源提供参赛、赛果或胜利记录
- **THEN** 系统 SHALL 将其归入 `race_record` 候选
- **AND** 可应用为 `HorseRaceRecord`

#### Scenario: 别名候选
- **WHEN** 外部来源提供英文名、日文名、中文名、繁体中文名、来港前名或其它别名
- **THEN** 系统 SHALL 将其归入 `aliases` 候选

### Requirement: 来源 adapter 必须低频、可缓存且可审计
系统 SHALL 为外部补全 adapter 提供请求限速、缓存、单批上限、失败隔离和 source evidence。补全请求不得发生在公开页面请求、新闻翻译、发布校验或关注流同步路径中。

#### Scenario: 真实请求受限速保护
- **WHEN** 补全任务访问外部来源
- **THEN** 系统 MUST 应用请求间隔、批次上限和单来源互斥或等价保护

#### Scenario: 页面请求不触发外部网络
- **WHEN** 普通用户访问 `/horses/`、`/horses/<id>/`、首页或新闻详情页
- **THEN** 系统 MUST 只读取本地数据库
- **AND** 不得实时请求 netkeiba、HKJC、Sporting Life、Racing Post、Geny、France Galop、HRN、Equibase 或其它外部站点

#### Scenario: 失败记录可审计
- **WHEN** 外部请求失败、解析失败、字段缺失或来源限流
- **THEN** 系统 SHALL 在 artifact 中记录来源、URL、目标马、错误类型和可读原因

### Requirement: 日本补全必须调研 netkeiba 和 KeibaScraper
系统 SHALL 将 netkeiba 作为日本 P0 马资料补全的关键候选源，并调研 `new-village/KeibaScraper` 作为参考实现或可选依赖。正式引入第三方依赖前必须完成许可、维护状态、字段覆盖、限速风险和本项目适配性评估。

#### Scenario: netkeiba 小样本字段覆盖调研
- **WHEN** 实现日本补全 adapter 前
- **THEN** 系统 SHALL 使用低频样本验证 netkeiba 是否可稳定获得父、母、父父、父母、母父、母母或可递归获得这些字段
- **AND** 将样本结果写入补全报告或仓库文档

#### Scenario: KeibaScraper 不默认成为强依赖
- **WHEN** 评估 `new-village/KeibaScraper`
- **THEN** 系统 SHALL 记录是否引入依赖的结论和理由
- **AND** 未完成评估前不得让核心补全流程强依赖该包

### Requirement: 补全报告必须列出未补全占比和原因
系统 SHALL 在每次 dry-run 和 commit 后输出补全报告。报告 MUST 包含全局和按地区的未补全占比，并列出每匹未完整补全马的具体原因。

#### Scenario: 输出未补全占比
- **WHEN** 补全 dry-run 完成
- **THEN** 报告 SHALL 包含全局和按地区的完整二代成功率、部分补全率、未补全率和失败原因分布

#### Scenario: 输出逐马失败原因
- **WHEN** 某匹 P0 马未达到完整二代成功
- **THEN** 报告 SHALL 为该马输出具体原因
- **AND** 原因 SHALL 区分 `no_external_match`、`ambiguous_match`、`source_unavailable`、`rate_limited`、`missing_pedigree_fields`、`profile_only`、`manual_lock_skipped` 或等价分类

#### Scenario: 报告可复核样例
- **WHEN** dry-run 输出失败或部分补全统计
- **THEN** artifact SHALL 提供每类原因的样例马匹、source evidence 和候选字段摘要
