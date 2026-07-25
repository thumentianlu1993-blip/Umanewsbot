## Context

上一批 61 匹日本 P0 马已正式写入，39 匹按既有门禁保留为 blocker。新的队列对象普遍只有唯一 Netkeiba ID，没有父名、母名和出生日期，不能通过现有四字段锁。

本次方案取消 JAIRS，改用两条互不依赖 Netkeiba ID 的官方竞赛身份链：

```text
官方重赏赛果 → 官方马匹链接/代码 → JRA 或 NAR 马匹档案
Netkeiba ID → Netkeiba 马匹档案
两条链路四字段完整一致 → 待审核候选
```

一期不再只验证 G1 马，而是覆盖日本训练马在 1998–2026 年参加的 G1/G2/G3、J-G1/J-G2/J-G3、JpnⅠ/JpnⅡ/JpnⅢ和海外 G1/G2/G3。这接近完整日本 P0 范围，因此必须先从赛事反向建池、按证据可处理性分批，不能逐个按马名无界搜索。

## Goals / Non-Goals

**Goals:**

- 从已入库重赏赛事及其参赛/赛果来源反向生成去重的一期候选池。
- 保存每匹马的全部资格赛事、最高等级、官方赛事上下文和官方身份锚点。
- 支持 `PREEXISTING_BASELINE`、`NETKEIBA_JRA_CONSENSUS`、`NETKEIBA_NAR_CONSENSUS` 和 `NETKEIBA_JRA_NAR_CONSENSUS`。
- 只有马名、父名、母名和完整出生日期得到完整、唯一、一致证据时才形成可提交候选。
- 保留直接官方马匹 ID/详情 URL 的快速路径；当前生产覆盖为 0，因此一期先验证可由赛事上下文
  唯一定位马匹档案的对象。只有 Netkeiba 的对象继续阻断。
- 输出按最高参赛等级和 provider 分层的通过率、blocker 和请求账本。

**Non-Goals:**

- 不使用 JAIRS。
- 不因参加过 G1 而降低身份锁，也不因只参加过 G3 而降低证据等级。
- 不纳入 Listed/L、普通开放赛、只有术语记录而无重赏资格证据的马。
- 不自动纳入外国训练、仅临时来日参赛的马。
- 不把马名搜索第一条、赛事同名或单一 Netkeiba 页面当作身份结论。
- 不在本变更内建立常态 Celery 抓取，不给公开 web/worker/beat 常驻网络权限。
- 不在身份补证时写履历、二代血统、胜绩、新闻或公开状态。

## Decisions

### 1. 一期候选池由赛事反向生成

资格范围固定为：

```text
1998-01-01 至 2026-12-31
日本训练马参加：
- JRA 平地 G1/G2/G3
- JRA 障碍 J-G1/J-G2/J-G3
- 地方 JpnⅠ/JpnⅡ/JpnⅢ
- 海外正式 G1/G2/G3
```

仓库现有 `RaceGrade` 中的 `G1/G2/G3/JG1/JG2/JG3/JPN1/JPN2/JPN3` 作为日本赛事选择基础。海外赛事只有在等级已完成规范化、赛事身份已合并、参赛/赛果来源完整且能证明日本训练身份时才进入；不能用 `racing_region=Japan` 单独推断训练地。

每匹马输出：

- `profile_id`、唯一 `netkeiba_id`；
- 全部 `qualification[]`：`race_series_id`、`race_event_id`、等级、日期、官方来源、官方 horse id/url；
- `highest_grade`、`highest_grade_priority`、`graded_start_count`、`latest_start_date`；
- `training_scope_status=provisional_japan|confirmed_japan|foreign_visitor|unresolved`、结构化 `training_evidence[]` 及依据。

资格建池阶段允许具有 JRA/NAR 官方身份锚点和重赏上下文的 `provisional_japan` 进入 prepare，以便读取官方档案完成判定；只有 `confirmed_japan` 可成为 `candidate_pass`。确认依据必须至少命中以下一项：

- JRA 官方档案明确给出日本中央练马师及美浦/栗东等 JRA 所属；
- NAR 官方档案明确给出日本地方竞马所属与练马师；
- 仓库已有经人工审核、带来源 URL/ID、赛事日期和所属地的等价证据。

只出现日本赛事、`racing_region=Japan`、日文马名、日本生产地或 Netkeiba 的地区字段均不足以确认。海外赛事还必须证明参赛当时属于上述日本训练体系；当前档案不能无条件回推历史所属。`foreign_visitor` 排除，无法确认者以 `TRAINING_SCOPE_UNRESOLVED` 阻断。重复赛事或多来源不得造成同一 profile 重复处理。

### 2. 等级只决定执行优先级，官方锚点决定可处理性

优先级为：

```text
Priority 1: G1 / J-G1 / JpnⅠ
Priority 2: G2 / J-G2 / JpnⅡ
Priority 3: G3 / J-G3 / JpnⅢ
```

每批最多 100 匹，排序键固定为：

1. `highest_grade_priority ASC`
2. `has_official_identity_anchor DESC`
3. `has_complete_official_context DESC`
4. `has_unique_netkeiba_id DESC`
5. `is_public DESC`
6. `graded_start_count DESC`
7. `latest_start_date DESC`
8. `profile_id ASC`

执行分三层。2026-07-25 只读盘点的当前形状为：第一层 0、第二层中“唯一 Netkeiba +
底稿不完整”上界 1,283、第三层至少 10；数字只作为本次基线，不硬编码进运行逻辑。

- 第一层：唯一 Netkeiba ID + 官方马匹 ID/详情 URL + 明确赛事上下文；
- 第二层：唯一 Netkeiba ID + 官方赛事 URL + 赛事日期/场地/马号/精确马名，但没有直接
  马匹锚点；通过 provider 的赛事上下文解析器取得唯一链接；
- 第三层：只有 Netkeiba ID，保持 blocker，等待 JRA-VAN 或人工补证。

首个 PoC 从第二层选择，不能因为第一层为 0 而退回站内开放式马名搜索。选择过程须数据库侧
批量预取，禁止逐匹 N+1；显式输入、赛事上下文字段和生产快照在 prepare 前冻结。

### 3. JRA 与 NAR 是独立 provider

`JraHorseIdentityProvider`：

- 首选 JRA 官方赛果中的马匹链接；
- 保存完整 URL 和 `CNAME` 原始值/可稳定提取的官方 horse code，不猜测 token 内部语义；
- 提取登记马名/欧字名、父、母、出生日期及必要的训练身份字段。

`NarHorseIdentityProvider`：

- 首选 NAR 官方赛果中的马匹链接；
- 保存 `k_lineageLoginCode` 和完整 URL；
- 提取登记马名、父、母、出生日期及所属/履历上下文。

同一匹马同时有 JRA 与 NAR 档案时，两 provider 分别取证；不把 NAR 逻辑塞入 JRA provider，也不让一方覆盖另一方冲突。

### 4. 身份共识与证据等级

Netkeiba 只提出 `candidate_unverified`。官方 provider 通过独立官方锚点返回身份。比较字段为：

- 规范化登记马名；
- 父名；
- 母名；
- 出生年份；
- 双方均有完整日期时的完整出生日期。

可提交候选还必须最终获得完整出生日期；只有年份一致为 `candidate_partial`，不可批准或 commit。

证据等级：

| 等级 | 模式 | 自动结论 |
| --- | --- | --- |
| A+ | Netkeiba + JRA + NAR 完整一致 | 待审核候选 |
| A | Netkeiba + JRA 完整一致 | 待审核候选 |
| A | Netkeiba + NAR 完整一致 | 待审核候选 |
| B | Netkeiba + JRA-VAN 完整一致 | 后续待审核候选 |
| C | 单一来源、年份级或不唯一 | blocker |

任何来源冲突都进入 blocker，不按“多数票”覆盖。`qualification_grade` 只说明入池原因，不参与 `identity_evidence_grade`。

### 5. 无直接链接时只允许确定性的赛事上下文解析

不得从候选池逐个做开放式马名搜索。第二层对象只能使用冻结的官方赛事 URL、日期、场地、马号、
精确马名和来源域解析：

- 输入 URL 必须属于对应 JRA/NAR allowlist host，且绑定同一 `race_event_id`；
- 页面若是赛事索引，最多跟随一个由赛事名、日期和场地唯一命中的详情链接；
- 参赛表必须恰有一行同时匹配规范化马号和精确规范化马名；
- 该行必须恰有一个同 provider 的马匹详情链接/代码；
- 结果必须保存索引/详情 URL、参赛行原始字段、马匹链接和每跳内容 SHA，并回链同一赛事；
- 官方档案与 Netkeiba 四字段必须完整一致；
- 请求数须进入 provider 独立预算。第二层每匹最多访问 3 个不同的 JRA/NAR URL（赛事索引、
  赛事详情、马匹档案各至多 1 个），每个 URL 最多传输 2 次，因此官方链每匹最多 6 次传输；
  重定向计入 URL 和传输预算且只能停留在同 provider allowlist host；
- 页面无参赛表、零/多赛事、零/多参赛行、零/多马匹链接、回链失败或字段不全均为稳定 blocker。

PoC 不启用 JRA/NAR 站内搜索。不得选择第一条，不做模糊马名最高分匹配；若赛事上下文无法直接
解析锚点，先以 `OFFICIAL_CONTEXT_NOT_FOUND` 或 `OFFICIAL_CONTEXT_AMBIGUOUS` 阻断。站内搜索
如未来确有必要，必须以新的可审方案和独立 PoC 引入。

### 6. 规范化只处理格式

原始值与规范值同时保存。只执行 Unicode NFKC、空白压缩、引号/连字符统一和国别后缀拆分；不自动音译、不推测片假名与拉丁字母等价。

日期保存 `birth_date`、`birth_year`、`birth_date_precision=day|year|unknown`：

- `day/day`：完整日期必须一致；
- `day/year` 或 `year/year`：年份一致只能 partial；
- 任一缺失：`REQUIRED_FIELD_MISSING`；
- 完整日期冲突：`BIRTH_DATE_MISMATCH`。

已审核 alias 或来源同时提供的日文/欧字名可用于等价；否则为 `SCRIPT_ALIAS_UNRESOLVED`。

### 7. 个人非商用用途下仍执行最小化访问合同

项目所有者确认 UmaFans 为个人爱好与学习用途，不做商业运营；本变更不再要求先另行申请 JRA/NAR 商业数据授权。

这项决定不放宽技术边界：

- 只在一次性人工命令中按显式清单访问；
- 命令级 `--allow-network` 与环境开关必须同时开启；
- JRA、NAR、Netkeiba 分 host 限速、持久请求预算、有限重试、缓存和 checkpoint；
- 单匹全部来源合计最多 6 个不同 URL、18 次传输；其中第二层 JRA/NAR 官方链另受
  3 URL、6 次传输的更严格子预算约束；
- 优先复用数据库已保存的官方 URL/ID，不重复请求；
- 只解析身份所需最小字段，不保存或公开发布完整 HTML、图片、视频或页面副本；
- 公开页面和常驻服务不得触发抓取；
- 429、访问拒绝、robots/页面提示变化或异常流量迹象立即停止，不通过换域、代理或绕过限制继续。

artifact 保存 URL、取得时间、HTTP 状态、解析器版本以及原始响应的 SHA；原始响应仅进入受限临时缓存并按运行手册清理，不进入公开仓库或产品页面。

### 8. JRA-VAN 是后续离线补证路线

官方网页缺失的第三层对象可在后续使用 Windows 节点上的 JRA-VAN DataLab/JV-Link：

```text
Linux 生成显式待核对清单
→ Windows 读取 UM 竞走马主档
→ 导出 horse_identity.jsonl + manifest
→ Linux 离线校验与四字段对账
```

导出必须保存血统登记编号、UM record type、数据规格版本、snapshot 时间、逐记录 SHA 和清单 SHA。普通 DataLab 订阅数据不得直接复制到公开页面；若未来产品用途或数据使用方式改变为商业/对外数据提供，须重新评估 JRA-VAN/JRADB 合同。本变更只定义接口，不把 Windows 节点列为一期网页 PoC 的前置。

### 9. prepare、审核和 commit 继续 fail closed

prepare 输出候选 JSONL、blocker JSONL、qualification JSONL、source evidence manifest、summary、state/checkpoint、请求预算和 xlsx，不修改业务表。

稳定 blocker 至少包括：

```text
NOT_JAPAN_TRAINED
TRAINING_SCOPE_UNRESOLVED
OFFICIAL_ANCHOR_MISSING
OFFICIAL_CONTEXT_NOT_FOUND
OFFICIAL_CONTEXT_AMBIGUOUS
JRA_PROFILE_NOT_FOUND
NAR_PROFILE_NOT_FOUND
NAME_MISMATCH
SIRE_MISMATCH
DAM_MISMATCH
BIRTH_YEAR_MISMATCH
BIRTH_DATE_MISMATCH
REQUIRED_FIELD_MISSING
SCRIPT_ALIAS_UNRESOLVED
SOURCE_LAYOUT_CHANGED
SOURCE_ACCESS_DENIED
REQUEST_BUDGET_EXHAUSTED
```

人工只可批准 `candidate_pass`。批准 manifest 绑定输入、qualification、候选、blocker、工作簿、来源证据和配置指纹 SHA。

commit 在单一事务内稳定顺序锁定全部目标，复验 Netkeiba key、资格来源、身份字段、人工锁和证据；只填仍为空的 `sire_text`、`dam_text`、`birth_date`，合并来源引用并创建唯一 `approved_sha256` receipt 与 OperationLog。任一漂移整批回滚。相同 SHA 只有在 receipt、字段、来源引用与日志完全一致时才允许零写 replay。

### 10. 先做 20 匹 PoC，再按 100 匹滚动

PoC 固定 20 匹，从最新只读快照中符合以下条件的第二层对象分配互斥 `sample_stratum`：

- 唯一数字型 Netkeiba ID；
- 身份底稿不完整；
- 唯一 `HorseProfile` 与冻结资格赛事；
- JRA/NAR 官方赛事 URL、赛事日期、马号和精确马名完整；
- 与旧 39 blocker 零交集。

- 10 匹现役重赏马；
- 5 匹退役重赏马；
- 2 匹具有外国出生线索的对象；
- 2 匹同时具有中央/地方赛事上下文或经审核转籍线索的对象；
- 1 匹障碍重赏马。

每个 profile 只能计入一个主分层，因此五类计数之和必须恰为 20；现役/退役、外国出生、转籍、
障碍等其它属性仍可作为 `secondary_traits` 交叉记录，但不得用来重复满足主分层名额。样本还必须
覆盖 G1/G2/G3 三个优先层级及 JRA/NAR 两个 provider，并在真实请求前冻结20条赛事上下文。
“外国出生线索”和“转籍线索”只用于样本覆盖，不构成日本训练身份或转籍事实；其依据必须保存为
`sampling_clue[]`，不得写入 `training_evidence[]`。触网后仍须由 JRA/NAR 官方档案确认日本训练
身份，不能确认者按 `TRAINING_SCOPE_UNRESOLVED` 或 `NOT_JAPAN_TRAINED` 阻断。
若最新只读候选池无法满足某类或上下文缺字段，PoC 阻断并报告缺口，不静默替换。

PoC 只生成证据，不写数据库。必须 20/20 先得到唯一锚点或稳定上下文 blocker，再进入身份对账；
最终全部为 pass/partial/稳定 blocker、未知异常为 0、至少 1 匹完成“赛事上下文 → 唯一锚点 →
完整双源 pass”、请求账本闭合且结束后网络开关恢复 false，才可规划首个 100 匹 prepare。

## Risks / Trade-offs

- [G2/G3 令范围快速扩大] → 全量建池但按等级、官方锚点和近年性排序，每批最多 100。
- [历史马官方档案缺失] → 不按名字猜；转 JRA-VAN/人工补证或保留 blocker。
- [同名和转籍增加] → 保存赛事上下文与官方 ID；JRA/NAR 冲突不以多数票解决。
- [来源页面结构或访问策略变化] → 分 provider parser fingerprint、低频 PoC、结构未知即停止。
- [个人非商用仍可能受到站点使用条件约束] → 最小字段、缓存、无公开页面副本、异常访问立即停止；用途变化重新评估。
- [一期身份通过但履历仍不完整] → 身份补证只解除四字段门禁，履历 blocker 继续走既有流程。
- [队列审核期间漂移] → 显式清单与快照绑定 SHA，漂移后重新 prepare。

## Migration Plan

1. 冻结本修订方案并使旧 JBIS/JAIRS 实现证据失效。
2. 测试先行实现重赏资格建池、去重、排序、训练范围门禁和官方锚点解析。
3. 分别实现 JRA/NAR provider、保守匹配、artifact、审核、receipt 和原子 commit。
4. 使用合成 fixture 完成离线 RED/GREEN、回归、迁移和并发验证。
5. 独立只读代码审查通过后，提交并部署精确版本；常驻网络保持关闭。
6. 从最新生产只读快照生成 20 匹 PoC 清单；另获触网授权后在一次性容器低频执行，结束立即关网。
7. PoC 通过后生成首批最多 100 匹 prepare，按最高等级分别报告覆盖率和 blocker。
8. 获得精确候选 SHA 的写入授权后，备份、commit 身份底稿并复验幂等与公开状态。
9. 重新进入现有 P0 完整资料批次流程。

## Open Questions

- 当前赛事库中多少资格记录已带 JRA/NAR 官方 horse ID/URL，需先做本地只读覆盖率盘点。
- 海外 G1/G2/G3 的等级规范化和“日本训练”证据覆盖率未知；不足者不会自动进入一期。
- 当前在途实现仍混有 JBIS/JAIRS provider 与测试；receipt、事务和显式清单逻辑需逐项保留审查，旧 provider/fixture/字段名必须替换，既往 GREEN 不计入本方案验证。
- `HorseSourceIdentity` 新表暂不新增；首版优先使用现有 `source_refs`、qualification artifact 与 receipt。PoC 证明查询或审计不足时再修订迁移设计。
