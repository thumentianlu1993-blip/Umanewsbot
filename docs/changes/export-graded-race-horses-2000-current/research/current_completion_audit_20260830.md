# 四地区 graded 参赛马导出当前完成度审计（2026-08-30）

## 结论

当前任务经冻结输入守恒审计后为 `INCOMPLETE`，不能解释为“样本链已跑通，所以全量已经完成”。本审计只读、
零网络、零数据库写入；production canonical 与公开页面没有提供 fresh inventory/apply receipt/verifier，状态均为
`not_audited`。

审计工件：

- root：`/Users/mentianlu/.codex/umanews-graded-horse-current-completion-audit-v2-20260830.BZrbHH`
- report：`completion-audit.json`
- report SHA-256：`c55d071d6e3a2d7702e038aee6bd2fb093e71a19a05e579bf7f35bf6fbea2081`
- tool SHA-256：`b374f24651fa821886448ea58a4d71ffbf2d65ba3e147be62da355663cfda839`
- marker：`AUDITED_INCOMPLETE`，内容精确绑定 report SHA-256
- 权限：目录 `0700`，report/marker `0600`
- 审计时间：`2026-08-30T03:54:51Z`

## 当前守恒账

| 层级 | 当前数量 | 已批准/已绑定 | 仍缺或状态 |
| --- | ---: | ---: | --- |
| 四地区目标赛事 | 12,048 | target ledger 已 COMPLETE | 113 场尚未到期 |
| 已到期目标 | 11,935 | current held result 350 | 11,585 场没有 current held result |
| occurrence evidence | 350 | 0 | 全部仍为 `PREPARED_NOT_EXECUTABLE` |
| actual-starter occurrence | 3,192 | stable `hrs_*` 0 | 2,321 个 exact name 仅可召回，不是 identity |
| 真实 P0 candidate | 2 | 0 | Westover/Economics 均待独立审核 |
| provider career rows | 20 | 0 canonical apply | 13 + 7，只代表两个样本 |
| identity/module proposal | 2 / 2 | 0 / 0 | 均为 `PROPOSED_NOT_APPROVED` |
| production canonical | 未审计 | 无 fresh receipt | 不得从本地工件推断 |
| 公开单马页 | 未审计 | 无 verifier | 不得从字段矩阵推断已发布 |

地区分母为英国 3,194、法国 1,891、爱尔兰 1,957、美国 5,006；等级分母为 G1 6,915、G2 2,015、
G3 3,118。350 场 held slice 仅占总目标 2.91%，且只覆盖英国/法国，不能用于外推四地区全量完成度。

## 工具合同

新增 `runtime/research/audit_current_graded_horse_export_completion.py`，逐层验证：

1. target manifest/ledger/COMPLETE marker 的 SHA 与 12,048 个唯一 target key；
2. coverage plan 对完整 target set 的一一守恒及 evidence-state counts；
3. occurrence proposal 对 target artifact 的精确绑定，并与 coverage 的 held-result target set 精确同集；
4. starter census 对 occurrence target、唯一逐 target summary、starter count 和 provider-ID count 的守恒；
5. 真实 candidate、identity proposal、module proposal 的 candidate/record/provider-ID set 守恒；
6. 只有全部输入通过后才原子写入 `completion-audit.json + AUDITED_INCOMPLETE`。

输入 marker 同时兼容已观察到的两种冻结格式：纯 manifest SHA，或 JSON marker 的
`manifest_sha256` 精确绑定。其他内容、SHA 漂移、symlink/路径逃逸、已有非空输出目录都失败关闭。

测试 `runtime/research/test_audit_current_graded_horse_export_completion.py` 当前 `6/6`，覆盖正常未完成报告、
coverage target set 漂移、coverage/occurrence target set 漂移、starter target count/重复 summary 漂移和
candidate/module proposal 漂移；失败均不产生输出。完整 `runtime/research` 回归为 `417/417`。

## 复验

输出目录必须不存在或为空；复验时间必须是带时区 ISO-8601。以下命令只读冻结输入，不连接生产：

```bash
python runtime/research/audit_current_graded_horse_export_completion.py \
  --target-root /Users/mentianlu/.codex/umanews-target-reviewed-complete-20260829.9WzJJH \
  --target-manifest-sha256 a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f \
  --coverage-root /Users/mentianlu/.codex/umanews-source-coverage-not-due-aware-v4-20260830.5ghcHz \
  --coverage-manifest-sha256 44fb91ab1e10ad1f992d4fcabca98b7189e7bac60dc6e97a7fd499059b633faf \
  --occurrence-root /Users/mentianlu/.codex/umanews-reviewed-occurrence-consolidation-v2-20260830.wJIln5 \
  --occurrence-manifest-sha256 71c4454e4d6a6023bdd1bcb15940e928bc1be075f5b66ed966d34ec838be07cd \
  --starter-census-root /Users/mentianlu/.codex/umanews-held-actual-starter-census-v1-20260830.q8BroW/artifact \
  --starter-census-manifest-sha256 32b12aa76f912647d74d9a612afe1e49a3af51e9c2551812126922e303273233 \
  --candidate /Users/mentianlu/.codex/umanews-four-region-p0-candidate-audit-20260830.ZqQCYw/france-westover-p0-candidate.json \
  --candidate-sha256 64dafd20f7589fb5d7428516d8ec22a38714bb49cdc2ae61a2ed2b8a3c574263 \
  --candidate /Users/mentianlu/.codex/umanews-four-region-p0-candidate-audit-20260830.ZqQCYw/ireland-economics-p0-candidate.json \
  --candidate-sha256 81afe3287b43a866926c28e76cce729d89a4b9c02159bd18d4286f92da652e7e \
  --identity-proposal-root /Users/mentianlu/.codex/umanews-four-region-p0-candidate-audit-20260830.ZqQCYw/identity-review-proposal \
  --identity-proposal-manifest-sha256 b9c2b6f71c76c0e3e28b0b1d6ad6756b1812adcec50048b6721e45f12ac2a826 \
  --module-proposal-root /Users/mentianlu/.codex/umanews-four-region-p0-candidate-audit-20260830.ZqQCYw/module-review-proposal \
  --module-proposal-manifest-sha256 e9ff268918ee4b7a35cc7cd34874000e27f16fab8fbbef95a9898b3192c520a5 \
  --audited-at <timezone-aware-iso8601> \
  --output-dir <new-empty-output-dir>
```

复验后用 `shasum -a 256 completion-audit.json` 对比 `AUDITED_INCOMPLETE`；两者必须逐字相等。

## 下一硬门禁

1. 为每个已到期 target 补齐并独立批准 historical occurrence；
2. 将每个 actual-starter occurrence 对账到唯一 TRA `hrs_*`，关闭 unmatched/ambiguous/count gap；
3. 对全部唯一马逐匹审核 identity 以及 profile/pedigree/race_record/major_wins；
4. 每批先备份、再用 exact reviewed package 写入，保存 receipt/reverse ledger；
5. 独立核对数据库守恒和公开单马页后，才允许最终审计从 `INCOMPLETE` 转为完成。

当前生产内存门禁与 shared canonical 门禁没有解除。本审计不获取 deployment lock，不允许据此执行 UK/USA
TRA proof、生产联网、数据库写入、canonical 修改或消费 `race_live`。

## 2026-08-31 v3 复验

使用当前工具和同一组 exact frozen inputs 重新运行，生成：

- root：`/Users/mentianlu/.codex/umanews-graded-horse-current-completion-audit-v3-20260831T055908Z`；
- report SHA-256：`24a99e3d5be8576a12f641e04048f04f058f86545ddabfbdcbe9e492aaf49ff6`；
- marker：`AUDITED_INCOMPLETE`，内容精确等于 report SHA；
- 权限：report/marker 均为 `0600`；
- audit network/database writes：`0/0`。

v3 同时重验 target scope：12,048 个唯一 key、2000–2026 连续、范围违规 0。当前缺口仍为 11,585 个 due target
没有 current held result、350 occurrence 未可执行、3,192 starter occurrence 的 approved provider IDs=0、
identity/module approvals=0，production/public 状态未审计。

## 2026-08-31 exact candidate-batch 增量

旧 v2 审计 artifact 保持不可变，仍可用上方逐文件兼容命令复验。selected 批次的正常新入口改为：

```bash
--candidate-batch-root <candidate-batch-root> \
--candidate-batch-manifest-sha256 <exact-candidate-batch-manifest-sha256>
```

该模式与所有 `--candidate/--candidate-sha256` 参数互斥，并额外守恒 source materialization/batch manifest、
每个 source run、candidate path/SHA/size/status/blocker、唯一 `hrs_*` 与 exact member set；identity/module proposal
必须引用同一 absolute path + SHA 集合。JSON、JSONL 与 JSON marker 统一拒绝重复 key 和 `NaN/Infinity`。

增量专项 `11/11`，完整 research `547/547`。真实 selected batch 尚未联网，故没有可生成的新 batch 审计 artifact；
不能用 synthetic 通过替代真实 candidate/approval/receipt/public verifier。
