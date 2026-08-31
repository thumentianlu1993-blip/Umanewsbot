# TOBA occurrence 双向守恒审核提案（2026-08-30）

## 结论

已从 reviewed `COMPLETE` 四地区 target 与冻结 TOBA history 生成一份不可执行、不可自批的双向审核包。
它没有用模糊匹配直接修改任何 occurrence；而是分别保存全部自动绑定、每个 source occurrence、每个
target 和两侧待审项。美国 TOBA 平地来源现能逐行守恒，但 `210` 个 source identity 与 `259` 个 flat
target 仍需独立 reviewer 作出 alias/grade/reused-source 决定，不能据此把美国 coverage 改成 complete。

本轮另修正一个分母口径：TOBA graded-stakes history 是平地来源，不覆盖美国障碍赛。`2000–2024` 同一
范围内有 `184` 个 US jumps target；它们已明确标为 `unsupported_by_toba_flat_history`，继续走其他
authority/TRA 路由，不再混入 TOBA unmatched。

## 冻结身份

- proposal root：`/Users/mentianlu/.codex/umanews-toba-occurrence-review-proposal-v2-20260830.v28UvK`
- proposal manifest SHA-256：
  `7617092b2aa5f61a6dddb46f45a36adba3084ef35a6f0223cd679a67788c65df`
- generator SHA-256：
  `1f629bf3e86070a3d822a0c7564e58f450bc696df31a1aba55312e1d4f6dd76a`
- reviewed target manifest/ledger SHA-256：
  `a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f /`
  `de5aabfb70257ba65d407cbf05f431595180ef475d0efd768438dca7b17b4264`
- TOBA cache SHA-256：
  `553f1dd210ff88d4f83837e8c6454e47d90492f3370edd2c4f0958d53fffe166`
- 状态：`PROPOSED_NOT_APPROVED / execution_ready=false / approval=false`
- 网络请求：`0`；数据库写入：`0`

第二个空目录确定性重放得到相同 manifest SHA，五个 JSONL 输出 SHA 也逐项相同。

## 守恒结果

| 维度 | 数量 | 状态 |
| --- | ---: | --- |
| TOBA 全页解析行 | 11,223 | 冻结输入 |
| 范围内 physical TOBA rows | 3,941 | 全部进入 source census |
| 范围内唯一 source occurrence identities | 3,940 | 1 条 physical duplicate 显式保留 |
| 自动绑定 occurrence / target | 3,730 / 3,726 | 不进入人工决策 |
| source unmatched review | 202 | 待独立审核 |
| source reused identities | 8 | 由 16 个 target-side issue 组成 |
| target review items | 259 | alias/grade/not-unique/reuse 分开保留 |
| 范围内 US flat targets | 3,985 | 3,726 auto + 259 review |
| 范围内 US jumps targets | 184 | TOBA 不支持，保留其他来源 gap |

原始 issue 仍为：`231 match_missing`、`202 source_unmatched`、`11 grade_conflict`、
`16 source_reused`、`1 match_not_unique`。这些类别有双侧和复用重叠，审核时不能相加推导缺失场数。

## 输出合同

- `automatic-bindings.jsonl`：3,730 个现有自动绑定，不与人工待审候选混写；
- `source-occurrence-census.jsonl`：3,940 个唯一 occurrence，并保存 physical row count；
- `source-review-items.jsonl`：210 个唯一 source review item；
- `target-census.jsonl`：4,169 个 flat+jumps target 及其唯一状态；
- `target-review-items.jsonl`：259 个 target review item；
- `proposal-manifest.json` + `PREPARED`：绑定输入、generator、全部输出 SHA 和守恒计数。

每个待审项只在“未解决的另一侧集合”中列出最多 5 个排序候选；已自动绑定的 source/target 不会重新进入
候选池。排序信号仅含同届等级、已知 track code 和名称 shape score，并明确保存
`candidate_rank_is_decision=false`。reviewer 必须逐项决定；排名第一不等于批准，也不能被 runner 消费。

## 后续门禁

1. 独立 reviewer 对 `210 source + 259 target` 两侧逐项签署一对一 bind、not-held/source-gap、grade
   resolution 或 duplicate-target/reused-source 决定，并生成另一个 exact SHA approval。
2. approval publisher 必须重新验证 physical/unique source、flat target、复用 identity 和双向 unmatched
   守恒；任一 source 不得绑定两个 target。
3. 美国 `184` 个 jumps target 继续保留非 TOBA 来源缺口；TOBA review 通过也不能把它们改为 resolved。
4. 只有 reviewed occurrence 才能进入 winner anchor/TRA race reconciliation；本提案不批准 TRA 请求、
   staging、canonical apply 或公开发布。

## 重放命令

命令只读冻结输入并写新 artifact 目录；不联网、不写数据库。

```bash
docker run --rm \
  -v /Users/mentianlu/.codex:/artifacts \
  -v /Users/mentianlu/.codex/worktrees/export-graded-race-horses-2000-current/runtime:/app/runtime:ro \
  -w /app umanews-review:race-data-sync \
  python /app/runtime/research/prepare_toba_occurrence_review.py \
  --target-root /artifacts/umanews-target-reviewed-complete-20260829.9WzJJH \
  --approved-target-ledger-sha256 de5aabfb70257ba65d407cbf05f431595180ef475d0efd768438dca7b17b4264 \
  --approved-target-manifest-sha256 a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f \
  --toba-history /artifacts/umanews-source-conflict-review-proposal-20260829/evidence/umanews-toba-history.html \
  --approved-toba-sha256 553f1dd210ff88d4f83837e8c6454e47d90492f3370edd2c4f0958d53fffe166 \
  --output-dir /artifacts/<empty-output-dir>
```

新增专项 `5/5`，与 source coverage/occurrence ledger 相邻组合 `21/21`；完整 `runtime/research` 在挂载
整个 worktree 后为 `315/315`，`py_compile` 通过。第一次完整运行只挂载 `runtime/`，导致一个测试读取
`/app/.github/workflows/...` 时出现 1 个 `FileNotFoundError`；修正只读挂载范围后重跑通过，该误调用没有
网络或数据库副作用。
