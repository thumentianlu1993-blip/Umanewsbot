# BHA / France Galop 官方赛历 not-due 守恒（2026-08-30）

## 结论

已把 reviewed 2026 BHA / France Galop calendar audit 的 `373` 个唯一 target candidates 按
`as_of_date=2026-08-29` 分开：`113` 个官方日期尚未到期，转成 occurrence ledger 可校验的
`not_due` disposition；`260` 个已过官方赛历日期仍保持 `past_schedule_needs_result`，没有被冒充为 held
或 cancelled。source coverage 因此由原来的 `292 calendar-only` 修正为 `113 not_due + 179 calendar
result gaps`；另外 81 个 past calendar target 已有其他 held evidence，继续优先标 held。

这只接入当前已审核的 BHA / France Galop 2026 赛历，不代表历史英法 held/not-held 已完成。Horse Racing
Ireland 尚无同等 hash-bound 官方赛历/结果 artifact，1,957 个 IRE target 仍全部依赖后续来源或 TRA proof。

## 当前 artifacts

### not-due-aware source coverage

- root：`/Users/mentianlu/.codex/umanews-source-coverage-not-due-aware-v4-20260830.5ghcHz`
- manifest SHA-256：
  `44fb91ab1e10ad1f992d4fcabca98b7189e7bac60dc6e97a7fd499059b633faf`
- generator SHA-256：
  `5babd98c2f5272a95e07cb571195065e72b4ff1a54e9fced2d7f5249f2a3de96`
- target plan SHA-256：
  `7dfe417d708e5ac2abfd68b6e805286dd3fdd50d7746db33e3507d48acfb4bec`
- coverage buckets SHA-256：
  `e259b34b3a894550ab48d593f11d5cd088fcfc756dcc76bd3cb00ef3bc730a9c`
- 状态：`PREPARED / execution_ready=false`；网络 `0`；数据库写入 `0`

| evidence state | targets |
| --- | ---: |
| current held | 350 |
| TOBA review | 3,726 |
| official calendar not due | 113 |
| past calendar result required | 179 |
| source route only | 7,680 |
| 总计 | 12,048 |

`not_due` 不再进入 unresolved execution-state blocker。其他三类真实 gap 仍保留，TRA 凭据虽然已在当前
进程安全注入，但 entitlement 与 fresh executable exclusive-account proof 仍未由本 artifact 验证。

### official calendar non-held proposal

- root：`/Users/mentianlu/.codex/umanews-official-calendar-non-held-proposal-v2-20260830.CDYApz`
- proposal manifest SHA-256：
  `f2cf6609df3456db045a84b15ab1299e2416aaef36aee32a33337c1739ddbd9a`
- generator SHA-256：
  `ad081cc035ded94310de375d12b55538472bad9d3842fb2daa8bfb72e64a9835`
- `non-held-target-ledger.jsonl`：113 行，SHA-256
  `bbb53e57685f9805ca5b5a7a34cb93fa089f1d623d53cebc406b1c101f2912e5`
- `past-schedule-needs-result.jsonl`：260 行，SHA-256
  `76fbbcfbd0830d1585c8629be602acc42883eabcfbacf30dd435f634eb818e76`
- source unmatched / target issues：2 / 123，逐字节保留原 audit 输出身份
- 状态：`PREPARED_NOT_EXECUTABLE / approval=false`；网络 `0`；数据库写入 `0`

113 条 non-held rows 已通过现有 `build_graded_horse_occurrence_ledger.validate_non_held_rows` 真实校验。
每行绑定 target、官方日期、provider/authority、source URL、payload SHA/size/path；只允许
`disposition=not_due`。past schedule 不进入该文件。

## 门禁

1. `not_due` 只表示截至冻结 as-of date 尚未到期；日期经过后必须重新获取 held/cancelled/postponed 终态。
2. 260 个 past schedule rows 必须补正式赛果或明确 non-held evidence，不能从赛历推断 held。
3. 两个 source unmatched 和 123 个 target issues 仍保留，不能通过降低 fuzzy/grade/track 门槛消除。
4. HRI 没有当前等价 artifact；不得借 BHA/France Galop 的 113 行推断 Ireland 状态。
5. 本提案不批准 TRA 请求、winner seed、staging/canonical apply 或公开发布。

新增 official-calendar adapter 专项 `4/4`；与 source coverage/occurrence ledger 合并 `21/21`。
