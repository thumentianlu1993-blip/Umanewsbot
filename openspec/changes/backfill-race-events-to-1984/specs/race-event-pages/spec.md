## MODIFIED Requirements

### Requirement: 历史回填必须通过批准批次控制赛事可见性
系统 MUST 保持普通结构化资料补充与 `RaceEvent` 可见性控制分离；已有赛事的常规详情重抓不得自动改变可见性。历史 inventory 批次 MAY 在年度身份完整、无来源冲突、出马表与赛果达到当年可得标准且 publication scope 已显式批准时，将新建历史赛事从 draft 转为 published。资料不足、身份待审和来源冲突赛事 MUST 保持 draft。

#### Scenario: 已公开赛事补充数据
- **WHEN** 已公开 `RaceEvent` 通过普通详情编排补充出走表、赛果或冠军证据
- **THEN** 公开赛事详情页 MAY 展示新增结构化数据
- **AND** 普通详情编排 MUST 不改变可见性字段

#### Scenario: 历史批次新建完整赛事
- **WHEN** 已批准历史批次创建的年度赛事身份完整、无冲突且 runners/results 达到公开门槛
- **THEN** 同一批准 publication scope MAY 将赛事设为 published
- **AND** 操作人、批次、门槛证据和时间 MUST 记录

#### Scenario: 已完赛历史赛事达到明确门槛
- **WHEN** 年度赛事稳定系列、年份、名称、地区、举办状态和来源已批准，完整正式 results 存在，且 runners 来自独立 racecard 或可信完整赛果
- **THEN** 系统 SHALL 将其视为达到结构化公开门槛
- **AND** 缺少来源未提供的赔率或闸位 MUST NOT 单独阻止公开

#### Scenario: 永久不可得但资料不完整
- **WHEN** 年度目标被批准 permanently unavailable 且缺少完整 runners 或 results
- **THEN** 对应年度赛事 MUST 保持 draft

#### Scenario: 历史批次资料不足
- **WHEN** 新建年度赛事存在身份待审、来源冲突或结构化资料不足
- **THEN** 系统 MUST 保持 draft
- **AND** 系统 MUST NOT 将其加入 sitemap

#### Scenario: 已确认取消赛事
- **WHEN** 年度赛事已排期后取消且取消证据已批准
- **THEN** publication scope MAY 公开取消赛事及其说明

## ADDED Requirements

### Requirement: 历届冠军必须按稳定系列动态汇总
系统 SHALL 从同一稳定赛事系列的年度正式赛果官方第一名和缺赛果年份的可信 `RaceEventHistoryWinner` 补位记录动态汇总历届冠军，按年份和马匹去重。`RaceEventResult` MUST 保存可查询的官方名次以支持并列冠军；正式赛果 MUST 优先于补位记录。`RaceEventHistoryWinner` MUST 允许同年多个不同冠军马匹，系统 MUST NOT 向每个年度赛事复制整张冠军表。

#### Scenario: 同系列多个年度都有正式赛果
- **WHEN** 用户访问该系列任一年度详情页
- **THEN** 历届冠军 SHALL 按年度汇总同系列正式冠军
- **AND** 每个冠军年份 MUST 只显示一次

#### Scenario: 某年只有冠军补位证据
- **WHEN** 某年缺少完整赛果但存在已批准冠军证据
- **THEN** 历届冠军 MAY 使用该补位记录
- **AND** 后续正式赛果补齐后 MUST 由正式赛果替代

#### Scenario: 官方赛果为并列冠军
- **WHEN** 同一年度存在多个官方第一名
- **THEN** 历届冠军 SHALL 展示全部并列冠军
- **AND** 稳定存储顺序 MUST NOT 覆盖官方名次

### Requirement: 历史赛事不得自动创建马匹资料或正式术语
系统 MUST NOT 因历史 runners/results 批量创建新 `HorseProfile`，也 MUST NOT 自动音译人马名称写入正式术语库。已有正式术语或马匹资料 MAY 关联；未命中名称 SHALL 保留来源原文并进入候选或术语缺口清单。

#### Scenario: 历史马名没有中文术语
- **WHEN** 已公开历史赛事中的马名未命中 active 正式术语
- **THEN** 页面 SHALL 显示来源原文
- **AND** 系统 MUST NOT 因缺中文名阻止结构化赛事公开

#### Scenario: 历史参赛马没有 HorseProfile
- **WHEN** 历史批次写入一匹未识别参赛马
- **THEN** 系统 MUST NOT 自动创建 HorseProfile
- **AND** 系统 MAY 生成后续审核候选

### Requirement: 达标历史赛事必须进入分片 sitemap
系统 SHALL 将 published 且达到历史质量门槛的年度赛事 URL 加入分片 sitemap。draft、身份冲突、资料不足、空壳和 `not_held` 目标 MUST NOT 进入 sitemap。

#### Scenario: 已发布完整历史赛事
- **WHEN** 历史年度赛事已 published 且质量达标
- **THEN** 其年度详情 URL SHALL 出现在某个赛事 sitemap 分片

#### Scenario: 草稿或 not held 目标
- **WHEN** 年度赛事为 draft，或总账目标为 not_held 且没有 RaceEvent
- **THEN** sitemap MUST 不包含对应 URL

### Requirement: 历史结构化数据不得保存整页原件
系统 SHALL 在产品数据库中只保存结构化赛事事实、有限行级 provenance 和 source cache 文件身份。整页 HTML、PDF 或重复页面 payload MUST 保存在受控 source cache，不得复制到每条 runner/result 或公开页面。

#### Scenario: adapter 解析完整 PDF
- **WHEN** adapter 从官方 PDF 解析多个年度赛事
- **THEN** runner/result SHALL 只保存对应结构化字段和 PDF 身份/页码
- **AND** 数据库 MUST NOT 为每行重复保存 PDF 字节或整页文本
