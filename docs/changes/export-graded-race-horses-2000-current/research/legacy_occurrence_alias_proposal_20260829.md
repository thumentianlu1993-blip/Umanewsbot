# 英国旧 occurrence 系列别名审核提案（2026-08-29）

## 结论

英国旧历史结果审计中的 11 个 manual-review candidates 已全部映射到当前 AQPS target 中唯一、精确的
series/year target。输出仍为 `PROPOSED_NOT_APPROVED / execution_ready=false`；没有把研究者的建议当成
审核结论，也没有改变 source coverage、生成 runnable seed、访问网络或写数据库。

当前 artifact：

- root：`/Users/mentianlu/.codex/umanews-legacy-alias-proposal-v2-20260829.b8kgKj`
- proposal manifest SHA-256：`3081e7cb5a8e50874a53ed1882e4379251e692b871dd6b7a4b794316530b25de`
- proposal JSONL SHA-256：`a49cab78fe23a164e83f22489fa4745818188ae544e9f80a38c2cd7751ca9423`
- generator SHA-256：`b706bf025bdef074a65b973f088d38aa20e39773591652158caf4ff624578abd`
- proposal：11 场、111 个 actual-starter slots、3 个 series migrations
- 网络请求：0；数据库写入：0；approval：false

## 建议映射

| 旧 series key | 当前 series key | 场数 | actual starters |
|---|---|---:|---:|
| `GBR_CORONATION_CUP` | `united-kingdom-coronation-cup` | 4 | 29 |
| `GBR_ASCOT_GOLD_CUP` | `united-kingdom-gold-cup-ascot-flat-20-turf` | 2 | 25 |
| `GBR_CHELTENHAM_STAYERS_HURDLE` | `united-kingdom-stayers-hurdle-cheltenham-jumps-3-jumps` | 5 | 57 |

每行提案同时绑定 current target row SHA、旧 audit manifest/candidate row SHA、冻结 source URL/payload
SHA、日期、冠军锚点和全部 actual-starter names。匹配只接受 country/year/series/name/course/grade/
discipline 完全一致且候选数恰为 1；没有 fuzzy fallback。

## 审核边界

独立审核人仍需逐行核对 target、日期、赛名、场地、等级、冠军和冻结赛果，然后发布另一个绑定本 manifest
与 11 行集合 SHA 的 approval。批准前：

- 11 场仍保持 manual-review，不进入 current-held 计数；
- 111 个名字仍只是 occurrence evidence，不是 canonical horse identity；
- Sporting Life 冻结页只按 `frozen_human_reviewed_reference` 使用，不批准新的系统化抓取；
- target 仍为 PREPARED 时，即使 alias 审核通过也不能生成 runnable targeted-horse seed。

2015 Finale Juvenile Hurdle 是另一个跨年补赛 proposal，不在本 11 行 alias 包内，必须单独审核。

## 可复现命令

```bash
python runtime/research/prepare_legacy_occurrence_alias_review.py \
  --target-ledger /artifacts/umanews-target-aqps-evidenced-20260829.dn99Jz/target-ledger.jsonl \
  --target-manifest /artifacts/umanews-target-aqps-evidenced-20260829.dn99Jz/target-ledger-manifest.json \
  --approved-target-ledger-sha256 88313a59972196ddd6a275c22a09f7c9c7b8ae9b23efc5f67045a34076961a49 \
  --approved-target-manifest-sha256 b507d21d0f7bc5eef9785cb9a230200bbdbdb81a63686f5f63476a26add1ec5d \
  --audit-root /artifacts/umanews-legacy-audits-aqps-current-20260829.kZhaDH/uk \
  --approved-audit-manifest-sha256 386fe45f7f602f1f6550bb53de3a9344534e9d88de5eb33dfd72c5714da5b2ea \
  --output-dir /artifacts/<empty-output-dir>
```

测试覆盖正常生成、target 多解、audit-target binding 漂移和 symlink 输出目录；异常均 fail closed。
