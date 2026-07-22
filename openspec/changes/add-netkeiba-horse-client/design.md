## Context

日本滚动批次的唯一抓取通道是 `_JBISClient` 名称检索（`p0_horse_completion_source_clients.py:1929+`），对同名马 fail closed。2026-07-22 生产实测：队列前 100 匹 100% `ambiguous_identity`。身份回填已为日本 2,462 匹提供 netkeiba key，netkeiba 马匹页 URL 可直接构造，页面含完整资料与生涯。

既有约束：客户端基类 `_BaseSourceClient`（同文件，allowed_hosts + 预算钩子 + 缓存）；adapter 注册 `_CLIENTS`（同文件 ~3062）；身份锁 `_require_expected_identity_matches_payload`（`p0_horse_completion_adapters.py:917-981`，provider-bound 时放宽四字段锁）；净keiba 保守限速 8s 已配置；`ExternalHorse`（netkeiba, 12,405 条）父母/出生日期全空。

## Goals / Non-Goals

**Goals:**

- 有 netkeiba key 的日本候选经 ID 直取完成 prepare：身份锁 provider-bound 通过、四字段与生涯从页面提取。
- 页面解析失败一律 fail closed，不猜值。
- 重跑首个日本滚动批次并验证批次自动首发。

**Non-Goals:**

- 不改 JBIS 客户端；不做 netkeiba 全站抓取；不批量修复 ExternalHorse 存量空四字段；不入库预测/评论类专有内容；不绕过限速与预算。

## Decisions

### 1. netkeiba 客户端结构

新增 `_NetkeibaClient(_BaseSourceClient)`：`provider_name = "netkeiba"`、`allowed_hosts = frozenset({"db.netkeiba.com"})`、`record_authority_status = "source_records_verified"`（netkeiba 战绩页生涯总数与逐场记录一致时）。抓取序列：马匹页 `/horse/{id}/`（基础资料 + 父母 + 出生日期）→ 战绩页 `/horse/result/{id}/`（生涯逐场 + 总数校验）。仅当候选携带 `netkeiba:{id}` key 时可用；无 key 候选不构造 URL（回退 JBIS 路径）。

### 2. 身份判据

- payload external ID = URL 中的数字 ID，必须与候选 key ID 完全一致（provider-bound）。
- 页面马名（含括号国别后缀的原文）与候选名按 `_normalize_identity_name` 语义比对；不一致 fail closed 记身份冲突，不猜测合并。
- 页面列出英文/中文别名时进 aliases；原名以日文表记为准。

### 3. 解析与字段口径

- 基础资料：性别、毛色、出生日期、马主、练马师、生产牧场；只有年份时保留日期精度，不虚构月日。
- 生涯：逐场日期、场地、比赛名、跑道/距离（保留原文单位）、名次/异常状态（`取消`/`除外`/`中止` 等按既有结果状态语义映射，不折叠 unknown）、骑师、马号、负磅、时间、奖金；战绩页生涯总数写 `official_or_source_start_count` 并与逐场数对账，不一致进缺口而非放行。
- 海外远征行保留并在统计中计 overseas。
- 任何预期表缺失/结构改版：`source_payload_unavailable` 式 fail closed，记录不可解析。

### 4. adapter 接入

`p0_horse_completion_adapters.py` 日本 adapter 增加 netkeiba 来源：`REGION_ADAPTERS[japan].client_factory` 按候选是否有 netkeiba key 选择 `_NetkeibaClient` 或 `_JBISClient`；`source_names` 已含 netkeiba。identity key 合并沿用既有 `_participant_identity_keys`（netkeiba URL 提取已实现）。

### 5. 限速与合规

沿用 `_default_source_client_factory` 的每地区预算账本与 per-host 限速（8s）；不重试 4xx；429/5xx 有限重试。批量执行前复核 netkeiba 访问条款。

## Risks / Trade-offs

- [页面结构脆弱] -> 解析器按表格标签语义定位而非绝对位置；结构不识别即 fail closed，配 fixture 回归。
- [netkeiba 与 JBIS 字段冲突] -> 同候选两来源字段不一致时记冲突不覆盖；netkeiba 路径只服务有 key 候选。
- [生涯总数口径] -> 总数与逐场数不一致进缺口，不标完整（沿用完整性验收口径）。
- [同名马 payload 污染] -> ID 直取零检索歧义；页面马名比对兜底。

## Migration Plan

1. 实现 client + 解析 + adapter 注册，fixture 测试（正常页、同名马、缺表、改版、总数不符、海外行）。
2. 本地 sqlite 端到端：select → prepare（缓存模拟）→ bundle → commit → 自动首发。
3. 独立 code review 后合并 main。
4. 生产执行（分步授权）：部署 → 首个日本批次全链路（含 xlsx 人工复审）→ 核验自动首发 → `publish-p0-horses-basic-tier` tasks 7.2 闭环。

## Resolved Questions

- 客户端选择策略：有 netkeiba key 走 netkeiba，无 key 保持 JBIS（用户 2026-07-22 决定方向 1）。
