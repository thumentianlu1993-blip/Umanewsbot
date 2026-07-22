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

### 1. netkeiba 客户端结构与抓取序列

新增 `_NetkeibaClient(_BaseSourceClient)`：`provider_name = "netkeiba"`、`allowed_hosts = frozenset({"db.netkeiba.com"})`、`record_authority_status = "source_records_verified"`。抓取序列 **3 页/马**（实测页面结构）：马匹页 `/horse/{id}/`（基础资料表 `db_prof_table` + **通算成績总数** + 标题行性别/毛色）→ 战绩页 `/horse/result/{id}/`（`db_h_race_results` 逐场）→ 血统页 `/horse/ped/{id}/`（`blood_table` 两代六字段）。生涯总数在**马匹页**（`通算成績 13戦6勝`），不在战绩页；`source_url` 用马匹页 URL 使 `official_start_count_source_url` 指向携带总数的页面。日本每候选预算 3→**4**（3 页 + 1 次 redirect 余量，redirect 计入预算；JBIS 路径仍只用 3）；**不做 netkeiba 失败中途回退 JBIS**（2+3 超预算且必然 fail closed）。

### 2. 客户端选择层（review P0-1 修正）

`_CLIENTS` 每地区只有一个客户端类，且 prepare 每地区只实例化一次（per-client `batch_limit` 计数）。选择层实现为：

1. **select 阶段 namespace 偏好**：日本候选持有 netkeiba key 时 `source_namespace` 直接取 netkeiba；其余情况保持既有 identity_keys 顺序扫描（确定性，不引入 frozenset 迭代——独立 review P1-1 修正）。
2. **dispatcher 客户端**：`_CLIENTS[japan]` 注册组合 dispatcher，按 `request.candidate_source_name == "netkeiba"` 分发 `_NetkeibaClient`，否则 `_JBISClient`（HKJC 的候选守卫为先例）；`last_request_count` 与 `_request_count` 在 finally 中双向代理（异常下也正确）；`batch_limit` 由 dispatcher 自身统一执行（地区上限 1×，子客户端上限不可达——独立 review P2-3 修正文档口径）。

### 3. 身份判据

- payload external ID = URL 中的数字 ID，必须与候选 key ID 完全一致（provider-bound）。
- 客户端先把 netkeiba 页面马名的**括号国别后缀**（如 `(USA)`）剥除再写 `identity.horse_name`；比较器是 adapter 的 `_normalized_text`（NFKC + casefold + 空白折叠），不是 `_normalize_identity_name`。原始页面名与罗马字英文名进 `aliases`（身份锁会查 aliases）。净keiba 页面只有罗马字英文名，无中文别名。
- **部分期望字段陷阱**（如实记录）：候选只要带任一非空 sire/dam/birth_year 期望值，provider-bound 放宽即失效，全部期望字段必须命中——回填四字段只填了一部分的候选仍会 fail closed，重跑预期成功率口径应排除这类候选。

### 4. 解析与字段口径

- 基础资料：`country` 由 `db_prof_table` 的 `産地` 判定——单字缩写按映射表（`米`→美国等）；多字值为国内产地（北海道等）→ `日本`；**未识别的单字标记 fail closed**（不得误标日本）；缺失 fail closed（独立 review P2-4 修正）。`sex`/`color` 来自标题行（`現役　牡4歳　芦毛`），毛色必须命中白名单（鹿毛/黒鹿毛/青鹿毛/青毛/芦毛/栗毛/栃栗毛/尾花栗毛/白毛），不命中即 fail closed 不猜字段（独立 review P1-2 修正）；`trainer` 剥 `（栗東）` 类后缀；`馬主` 单元格前置 `<img>` 忽略；生产牧场取 `生産者`。
- 血统：`blood_table` 两代六字段（父 = row0 cell0、父父 = row0 cell1、父母 = row8 cell0、母 = row16 cell0、母父 = row16 cell1、母母 = row24 cell0）；名称剥 `(米)` 国别标记、年份、毛色、`[血統][産駒]` 标记。payload 校验要求**六字段全非空 + birth_date 为完整 ISO 日期**——**只有年份的出生日期 = 该候选 fail closed 阻断**（不虚构月日，也不存在精度保留路径）；任一血统字段缺失同理阻断。
- 生涯逐场：`db_h_race_results` 行：日期（`YYYY/MM/DD`）、開催（`大井` 或 `2中山8` 格式）、レース名（含 `(JpnI`/`(OP)` 等级标记保留原文）、着順、騎手、馬番、斤量、距離（`ダ1200` 原文保留、单位统一为米但原文必须保留）、タイム。
- 异常状态映射（客户端层翻译，与 JBIS 先例一致并补齐）：`取消→scratched`、`除外→withdrawn`（两者不计出赛）、`中止→did_not_finish`、`失格→disqualified`（两者计出赛）；未映射状态不得折叠 unknown 放行（会变成 `unconfirmed_start_status` 阻断，这是既有行为，保持）。
- 海外行判定：開催不符合 JRA `回場日` 格式且不在 NAR 场地名单 → `is_overseas=True`，场地与比赛名保留原文。
- `source_start_count` 只计实际出赛（排除 scratched/withdrawn），与通算成績（中央+地方合计）对账，不一致进缺口。
- 逐场日期非精确（如老年份 2 位年）会产生 `race_record_core_evidence_missing` 阻断（既有行为，保持并如实记录）。

### 5. 规格与合规

沿用 `_default_source_client_factory` 的每地区预算账本与 per-host 限速（8s）；429/5xx 有限重试、4xx 不重试（既有基类行为）。payload 复用 `_BaseSourceClient._payload`（形状与 JBIS 相同，`adapter_key` 自动为 `japan_jbis`——地区键非来源键，如实记录）。批量执行前复核 netkeiba 访问条款。

### 6. 编码与缓存（生产首轮返修，2026-07-22）

- **EUC-JP 解码**：netkeiba 响应 `Content-Type: text/html` 无 charset，requests 按 ISO-8859-1 解码得到乱码（生产首轮 61/100 因此阻断）。客户端一律用 `_netkeiba_page_text` 对原始 bytes 按 EUC-JP 解码后再解析。
- **跨源缓存守卫**：候选级缓存只按 candidate_key 寻址，不区分来源；日本 dispatcher 引入双来源后，JBIS 时代缓存会让 netkeiba 候选的 provider-bound 失效并永久卡死四字段锁（生产首轮 39/100 因此阻断）。`run_p0_horse_completion_adapter` 对日本地区校验缓存 payload 的 `source.name` 与候选 `candidate_source_name` 一致才允许命中；其他地区（美国 equibase/HRN 互补流）保持既有跨来源缓存语义。

### 7. 第二轮生产发现与恢复设计（2026-07-23）

批次 `p0batch-e5cee174ba05` 后续已在相同相关代码下完成 prepare，说明早先 `7/100` 无声退出更符合 detached exec/进程会话中断，而非第 8 个候选的稳定 Python 异常。该批最终为 `27/100` 完整、`73/100` 阻断、`300` 次请求：`62` 个 `title_sex_color`、`10` 个四字段身份不完整、`1` 个履历核心证据不足。普通解析异常均被现有 prepare 转为 blocker staging，因此没有错误数据写库。

- **标题状态**：真实已注销页面使用 `抹消　牡　黒鹿毛`，既有正则只接受 `登録抹消` 等状态。解析应把状态、性别、毛色分开验证，精确加入 `抹消`，未知 token 继续 fail closed；不得把整行改成任意前缀的宽松匹配。
- **部分期望字段诊断**：受控复现已确认样本页面实际四字段齐全；10 个 `identity_incomplete` 来自候选仅携带部分 `expected_sire_name/expected_dam_name/expected_birth_year`，触发既有完整期望锁。该锁不得放宽；错误必须列出候选缺少的期望字段并归类为可解释的 source/identity blocker，而不是 `unexpected_adapter_error`。
- **异常履历行 characterization**：单个 `partial_career` 的第 15 行为 `2025-03-17 水沢 C1`，页面行有骑师/距离/马号但头数与着顺为空，马体重为 `計不`；这些事实不足以证明实际出赛或取消。先写 characterization 测试保存该不确定性；只有官方页面/结果证据能证明合法状态时，才另写期望映射与计数语义的 RED 测试后实现，否则保持 blocker。
- **解析器版本与 cache 绑定**：`adapter_config_fingerprint()` 当前只覆盖 schema、来源集合、预算和批次上限，代码改动不会使已成功 staging 失效。新增显式 `NETKEIBA_PARSER_VERSION`（机器稳定常量）并纳入 fingerprint，同时写入 netkeiba canonical source payload；日本同来源 cache 缺失或不匹配当前版本时强制 cache miss。网络刷新成功后必须在 sidecar 文件锁内原子替换 stale cache，并让并发调用复用同一份当前版本 payload；普通 cache 首写仍保持 no-clobber，其他来源/地区不变。任何会改变 canonical payload 的 netkeiba 解析规则都必须递增版本并用测试锁定。
- **批次处置**：blocked payload 也按候选级 `succeeded` 保存，故修复后不得直接重跑当前 prepared 批次或手改 checkpoint。当前批只保留证据、不 bundle/commit；新版本部署后 abandon，再重新 select/approve。旧 netkeiba canonical cache 因缺少当前 parser version 不再复用，新批在预算内重新抓取。
- **验收阈值**：不要求来源天然缺失的候选达到 `100/100`，但要求 `unexpected_adapter_error=0`、已支持结构造成的系统性 blocker=0；剩余 blocker 必须字段级可解释。仅完整且经 xlsx 人工复审的子集可以 bundle/commit，并核验自动首发与审计。
- **运行态恢复**：每个触网窗口结束都必须把 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false` 注入实际执行容器并验证，不能只改 `.env`。2026-07-23 已恢复 false，web/Nginx 与公开健康检查通过。

## Risks / Trade-offs

- [页面结构脆弱] -> 解析器按表格标签语义定位而非绝对位置；结构不识别即 fail closed，配 fixture 回归。
- [netkeiba 与 JBIS 字段冲突] -> 同候选两来源字段不一致时记冲突不覆盖；netkeiba 路径只服务有 key 候选。
- [生涯总数口径] -> 总数与逐场数不一致进缺口，不标完整（沿用完整性验收口径）。
- [同名马 payload 污染] -> ID 直取零检索歧义；页面马名比对兜底。

## Migration Plan

1. 实现 client + 解析 + adapter 注册，fixture 测试（正常页、同名马、缺表、改版、总数不符、海外行）。
2. 本地 sqlite 端到端：select → prepare（缓存模拟）→ bundle → commit → 自动首发。
3. 独立 code review 后合并 main。
4. 第二轮生产 fixture 先写 RED：`抹消` 标题、字段级 identity blocker、异常履历行、parser version fingerprint；再最小实现至 GREEN。
5. 独立方案复审、代码复审与本地验证通过后，重新取得精确代码版本的部署/触网授权；部署后保留并 abandon 旧批次，新建日本批次只执行到 prepare 与 xlsx；prepare 成功或异常后立即在 finally 路径恢复并验证 `ALLOW_NETWORK=false` 和 worker，不等待人工复审。
6. 用户人工复审 xlsx 后冻结 bundle/hash；再取得绑定该 bundle/hash、完整子集与自动公开首发范围的精确 commit 授权，最后执行 commit、首发验收与网络开关恢复。

## Resolved Questions

- 客户端选择策略：有 netkeiba key 走 netkeiba，无 key 保持 JBIS（用户 2026-07-22 决定方向 1）。
