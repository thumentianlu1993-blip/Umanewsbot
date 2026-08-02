## Why

首个日本 P0 滚动批次完成后，下一批大量对象虽然持有唯一 `netkeiba:{id}`，但数据库没有父名、母名和出生日期，现有四字段身份锁会将其全部阻断。此前考虑的 JAIRS 自动链路不再采用；一期改从已完成的重赏赛事数据反向建立候选池，用 JRA/NAR 官方赛事上下文和马匹档案为 Netkeiba 身份提供独立锚点。

一期同时覆盖 G1、G2、G3，不按赛事级别放宽身份证据。赛事等级只决定处理优先级，能否提交仍只取决于官方身份锚点与四字段完整一致。

2026-07-25 生产只读盘点确认：7,228 个日本地区潜在 profile 中，数据库已保存的 JRA/NAR
马匹详情 ID/URL 为 0；7,164 个只有官方赛事上下文。唯一 Netkeiba ID 且身份底稿不完整的
第二层候选上界为 1,283。因此一期 PoC 的首要能力不是消费既有马匹锚点，而是从已冻结的官方
赛事上下文中精确解析唯一参赛马链接；解析失败时保持阻断。

## What Changes

- 定义一期日本重赏候选池：1998–2026 年日本训练马参加的 JRA G1/G2/G3、J-G1/J-G2/J-G3、地方 JpnⅠ/JpnⅡ/JpnⅢ，以及日本训练马参加的海外 G1/G2/G3。
- 候选从 `RaceEvent → RaceEventRunner/RaceEventResult/HorseP0Source → official source horse id/url → HorseProfile` 反向生成；一匹马只处理一次，并保存全部资格赛事及最高参赛等级。
- 核心身份模式改为 `NETKEIBA_JRA_CONSENSUS`、`NETKEIBA_NAR_CONSENSUS` 和 `NETKEIBA_JRA_NAR_CONSENSUS`；保留既有完整底稿的 `PREEXISTING_BASELINE`。JAIRS 完全退出本变更。
- JRA/NAR 官方赛事页中的马匹链接或代码仍是最短路径；但当前数据库覆盖为 0，一期 PoC
  SHALL 从官方赛事 URL、赛事日期、马号和精确马名定位同一参赛行，并提取该行唯一马匹链接。
  页面没有参赛表、零/多行匹配、链接缺失或回链赛事不一致时均阻断；不得按马名选择第一条。
- Netkeiba 与 JRA/NAR 必须对马名、父名、母名和出生年份一致；双方均有完整日期时日期必须一致。只有完整出生日期得到确认的候选才可进入提交；年份级证据、字段缺失、冲突或候选不唯一均 fail closed。
- JRA 与 NAR 同时存在且三源完整一致时标记 `A+`；任一官方主源与 Netkeiba 完整一致时标记 `A`。赛事等级不参与证据等级计算。
- JRA-VAN DataLab 作为官方网页缺失时的后续离线补证来源，使用 Windows 采集节点导出受清单和哈希约束的 `horse_identity.jsonl`；本期网页 PoC 不依赖它，普通 DataLab 数据也不直接公开展示。
- 项目按个人非商用学习用途处理，不把另行申请 JRA/NAR 商业数据授权设为实现前置条件；仍执行低频、最小字段、请求预算、缓存、禁止公开源页面副本和异常访问阻断。
- 继续采用“有界 prepare → 审核 artifact/xlsx → 精确 SHA 批准 → 整批原子 commit”门禁；prepare 不写业务表，commit 不改变公开状态，只填充获批且仍为空、未锁定的身份底稿字段。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `horse-profile-data-completion`: 增加日本重赏 P0 候选池、JRA/NAR 官方身份锚点、双/三来源身份共识、审核与精确 SHA 提交要求。

## Impact

- 主要影响 P0 候选选择、JRA/NAR 身份 provider、来源对账、artifact、审核与提交服务，以及对应管理命令、测试和 commit receipt 迁移。
- 复用现有 `RaceEvent`、`HorseP0Source`、Netkeiba 解析、请求预算、缓存和人工审核基础设施；JRA 与 NAR 分别实现独立 provider。
- 当前在途的 JBIS/JAIRS provider 与测试不再是有效实现证据；receipt、事务、显式清单和幂等门禁可以在重新核对后保留。
- 不新增公开 API，不公开保存的源页面副本，不改变 `HorseProfile` 公开资格；真实 PoC 和生产写入仍须分别获得执行授权。
