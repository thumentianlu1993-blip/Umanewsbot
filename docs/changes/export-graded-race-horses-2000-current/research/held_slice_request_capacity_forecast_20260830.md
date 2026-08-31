# 350 场 held slice 请求容量与时长预测（2026-08-30）

## 1. 结论与适用范围

当前可审计的 actual-starter census 只覆盖 350 场英国/法国 held occurrence，共 3,192 个实际出赛槽位；它不
覆盖 Ireland/USA，也只占 12,048 条正式 target 的 `350 / 12,048 = 2.91%`。因此本预测只能给 350 场局部
slice 做后续 G3 容量拆账，不能冒充全目标工作量或可执行批次。

冻结输入：

- root：`/Users/mentianlu/.codex/umanews-held-actual-starter-census-v1-20260830.q8BroW/artifact`；
- census manifest SHA：`32b12aa76f912647d74d9a612afe1e49a3af51e9c2551812126922e303273233`；
- 3,192-row census SHA：`5916ed2691407b50ced2adb8dbd8f5facb99fbe22e8cc1668304b530d3b4c056`；
- 350-row target summary SHA：`262cc0380b2870b4f345296e9c36a3917b84f7e12fe31385b079ad6475f39eb9`；
- 状态：`PREPARED_NOT_EXECUTABLE`，provider horse IDs assigned=`0`，network/DB writes=`0/0`。

当前结论固定为：

`HELD_SLICE_CAPACITY_FORECAST_ONLY_STABLE_ID_CARDINALITY_UNKNOWN_NO_EXECUTION_PLAN`

## 2. 已知分母与不能去重的边界

| 维度 | 数量 |
| --- | ---: |
| held target occurrences | 350 |
| actual starter occurrences | 3,192 |
| excluded withdrawals/NP | 94 |
| UK slots | 1,957 |
| France slots | 1,235 |
| flat / jumps | 1,682 / 1,510 |
| G1 / G2 / G3 slots | 2,220 / 197 / 775 |
| exact name strings | 2,321 |
| TRA `hrs_*` assigned | 0 |

2,321 只是 recall-only 的逐字名称集合，不是马匹身份数：同一马可能有大小写、国别后缀或跨语言 alias；同一
字符串也可能对应不同出生年/血统的同名马。source runner key 也不能跨 provider 当 TRA ID，France Galop 本批
key 的语义尤其不支持直接计数。因此在 occurrence reconciliation 完成前：

- 唯一 provider horse 数 `N` 为 unknown；
- 不能把 2,321 当作精确 N；
- 为最坏容量校验，可以用 `N <= 3,192` 的“每个槽位不同马”上界；
- 正式 batch plan 只能在 3,192 槽位全部映射、unmatched/ambiguous/count mismatch=0 且独立批准后生成。

重复只说明去重价值，不构成 identity：1,787 个 exact strings 只出现一次，534 个出现至少两次，单一 exact
string 最多出现 12 次。profile/career enrichment 必须按获批 `hrs_*` 去重，不能按名字减少请求。

## 3. 第一阶段：350 个 winner anchor 的目标场定位

最新修正后的 350-seed 口径为 `311 reuse + 37 add + 2 replace`，但 39 条 add/replace 仍缺非实现者 exact-SHA
决定，因此当前没有可执行的 350-seed COMPLETE artifact。旧 313-seed/5,008-GET 计划含两条错误 winner，不能
继续当最终计划。

按现有 targeted-horse 合同的保守 `16 GET/seed` 与 projected 26 batches 计算：

| 项目 | 公式 | 上限 |
| --- | --- | ---: |
| request ceiling | `350 × 16` | 5,600 GET |
| 纯最小请求时间 | `5,600 × 250ms` | 23m20s |
| completed-to-next-start gaps | `25 × 30m` | 12h30m |
| 无失败/无人工等待理论墙钟 | 上两项相加 | 12h53m20s |

真实每批还需要 proposal、独立 exact G3、双主机 exclusive proof、空 output/budget 和完成后 verifier；这些人工
与现场门禁不计入理论墙钟。任何 safe-stop 会保留已消费请求，并要求新的 resume proposal/approval/proof，
不能从上限中“退回”已用额度。

## 4. 第二阶段：稳定 `hrs_*` 的 profile/parent/full-career enrichment

稳定 ID plan 默认且最大允许：

- `/horses/{id}/results` 最多 201 pages（`limit=100`，`skip<=20000`）；
- target profile Pro/Standard fallback 最多 2 GET；
- 父、母最多 2 个 parent，每个 Pro/Standard fallback 最多 2 GET；
- search requests=`0`；batch size cap=`5`；单并发；250ms 最小间隔；上一批完成后至少 30 分钟。

所以每匹稳定 ID 的保守上限为：

`201 + 2 + 2 × 2 = 207 GET/horse`

令 reconciliation 后的唯一 `hrs_*` 数为 `N`：

- request ceiling = `207N`；
- batches = `ceil(N/5)`；
- 纯最小请求时间 = `51.75N` 秒；
- 批间等待 = `(ceil(N/5)-1) × 30` 分钟；
- 无失败/无人工等待理论墙钟 = 纯请求时间 + 批间等待。

### 4.1 两个非批准的容量情景

| 情景 | N | GET ceiling | batches | 纯请求时间 | 批间等待 | 理论墙钟 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 每个 exact name 恰好一匹（仅测算，不是 identity 结论） | 2,321 | 480,447 | 465 | 33h21m52s | 232h | 11d1h21m52s |
| 每个 starter slot 都是不同马（绝对槽位上界） | 3,192 | 660,744 | 639 | 45h53m06s | 319h | 15d4h53m06s |

两份真实样本只有一页 career，实际取得 target profile + 2 parent profile + results 的 GET 数远低于 207；但
Westover/Economics 不能证明历史长生涯、深分页或 USA add-on 的分布。正式预算必须保持 207/horse，除非冻结
stable-ID census 后又有独立、可重放的 provider total/page 证据把每匹上限安全收窄。

## 5. 为什么当前不能冻结正式频率

当前小样本使用 1 concurrency、至少 250ms，即最多 4 req/s，低于公开 5 req/s endpoint limit。两批 France/
Ireland 成功只证明这一保守频率可用；尚未证明：

1. UK/USA entitlement 与 North America add-on；
2. common-name 多候选、日港海外英文 alias 与跨语言 resolver 的真实错误率；
3. 100+ results page、429/Retry-After 和长批次 account budget 行为；
4. 12,048 targets 中其余 11,698 条 occurrence 的实际赛果来源与 starter 分母；
5. 39 条修正 winner seed、3,192 slot reconciliation 与独立审核已完成。

所以正式配置继续保持：`max_concurrency=1`、`min_interval_ms>=250`、逐批 fresh proof、逐批 exact G3、前批完成
后至少 30 分钟、artifact-only/0 DB writes。不得为了缩短上述 11–15 天 held-slice 上界而提高并发或放宽门禁。

## 6. 下一次可重算点

只有以下输入齐备时才生成真正的 stable-ID batch plan：

1. 修正后的 350-seed extension 由非实现者批准并形成 COMPLETE；
2. 350 个 target race 全部唯一 reconciliation；
3. 3,192 starter slots 全部绑定 `hrs_*`，unknown/ambiguous/unmatched/count mismatch=0；
4. approved stable-runner ledger 与 reconciliation approval manifest SHA 均冻结；
5. UK/USA sample 与字段/identity review 完成，rollout owner 给出新的生产安全窗口和 canonical SHA。

本预测没有执行网络、创建 approval、生成 executable plan、修改 shared canonical 或写入任何数据库。
