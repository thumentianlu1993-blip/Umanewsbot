# 法国/爱尔兰真实 P0 候选与 identity census 复核（2026-08-30）

## 结论

已把法国 Westover 与爱尔兰 Economics 的真实 TRA materialization 写入一份本地隔离 SQLite 的
`External*` staging，并从同一冻结响应生成两份 `racing-api-horse-p0-candidate.v1`。两份候选均为
`review_required`、`blockers=[]`、`database_writes=0`，没有 canonical `HorseProfile`、identity 或
`HorseRaceRecord` 写入。显式双马 identity census 也为 `COMPLETE_READ_ONLY`、0 网络、0 数据库写入。

这只证明“真实 provider 响应 -> staging -> P0 候选 -> 只读 identity census”链可运行；两匹均仍是
`create_new_candidate`，必须经过独立 identity/module review，不能直接进入 production apply。

## 真实响应边界修正

真实包揭示两类离线 fixture 未覆盖的正常响应：

1. profile 的父、母 Pro/Standard 响应属于声明过的 parent evidence；候选生成器现在要求 normalized
   `parent_profiles`、字段矩阵中的 parent payload SHA 与冻结响应 canonical payload SHA 三方一致。
2. `/horses/search?name=Economics` 同时返回英国与澳大利亚同名马，采集器为 occurrence 消歧读取了澳洲马
   的 `/results`。这种 response 只有在同一冻结、严格 `name`/`q` search response 已披露该 `hrs_*` 时，
   才作为 `discovery_probe` 被忽略；它绝不进入目标马 `source_evidence`。任意未披露 horse endpoint、
   credential/host/query 漂移、未声明 parent 或 parent payload SHA 漂移仍失败关闭。

因此同名马 probe 不会污染 Economics 的 career，任意额外端点也不能借“search 可忽略”绕过证据 allowlist。

## 不可变产物

私有审计根：

`/Users/mentianlu/.codex/umanews-four-region-p0-candidate-audit-20260830.ZqQCYw`

| 产物 | 关键结果 | SHA-256 |
| --- | --- | --- |
| `france-westover-p0-candidate.json` | `hrs_26036913`；France target 1；13 career rows；target Pro + 2 parent Pro；4 evidence rows | `64dafd20f7589fb5d7428516d8ec22a38714bb49cdc2ae61a2ed2b8a3c574263` |
| `ireland-economics-p0-candidate.json` | `hrs_37860606`；Ireland target 1；7 career rows；target Pro + 2 parent Pro；4 evidence rows | `81afe3287b43a866926c28e76cce729d89a4b9c02159bd18d4286f92da652e7e` |
| `identity-census/manifest.json` | 2 rows；两匹均 `united_kingdom/create_new_candidate`；current identity、official claim、candidate profile 均为 0 | `7cd24d0ed0ef966d7fd3914055911c6b0e8c65302921dfbc8b21a3f08da4e013` |
| `identity-census/identity-census.jsonl` | fixed scope/time deterministic rows | `d8645f868e72d2c6ef79ced4842cebd92d15562dbc4914e5cbaa6ec248bda93e` |

候选的共同 review reasons 为 `career_authority_review_required`、`module_review_required`、
`profile_create_review_required`。两份候选均没有 missing/conflicting page fields；provider career 仍诚实标为
`count_aligned_records_unverified / partial`，不冒充逐场官方权威已审核。

## 验证与当前边界

- candidate 专项：`13/13`；
- identity/module review proposal 聚焦：`34/34`；扩大相邻链：`393/393`；
- 产物权限为 `0600`，隔离 SQLite 不属于项目或生产数据库；
- 没有新增 TRA 请求，复用了已冻结 v4 response cache；
- 英国/美国样本、production census、canonical、production apply 继续暂停；共享 canonical 的 registry
  SHA 漂移由 PR129 rollout owner 独立收口，本任务不 acquire、不生成 proof、不修改 canonical。

当前 verdict：`REAL_FR_IRE_P0_CANDIDATES_REVIEWABLE_CANONICAL_WRITES_NOT_APPROVED`。

## 精确审核提案

两份候选已组成两个独立、零写 `PROPOSED_NOT_APPROVED` 包；实现者没有填写决定或发布 approval：

| 提案 | manifest SHA-256 | rows SHA-256 | 当前建议 |
| --- | --- | --- | --- |
| identity review | `b9c2b6f71c76c0e3e28b0b1d6ad6756b1812adcec50048b6721e45f12ac2a826` | `854660cc980d013133d38a0e451f96809833e9e283050baf2c2d693246f0f260` | 两匹均 `create_draft`，待独立 identity 决定 |
| module review | `e9ff268918ee4b7a35cc7cd34874000e27f16fab8fbbef95a9898b3192c520a5` | `73b9a64d6ed8930475a5b63acd9478b7a537943ab497bab8a36b56fb2942712f` | 20 条实际出赛履历及四模块待独立审核 |

identity decision template SHA 为
`e41aca4c617bb152627c70b29203a7feb49a00a34056344f05215f3a34371d4c`。推荐动作只是机器生成的审核起点，
不是批准；identity 必须先定，module approval 也不能替代 production apply。

用同一隔离 DB 和候选 SHA 在新空目录重放后：identity `review-rows` 与 decision template 逐字节一致，manifest
除运行生成的 `generated_at` 外语义一致；module rows 与 manifest 全部逐字节一致。identity approval 仍只能绑定
原 proposal manifest `b9c2b6f7…a826`，不得拿 replay 的新时间戳 manifest `7ca11781…3f5f` 替换。
