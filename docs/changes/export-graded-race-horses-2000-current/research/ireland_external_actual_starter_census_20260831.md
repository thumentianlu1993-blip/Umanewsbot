# Ireland 单场 external actual-starter census proposal

日期：2026-08-31（Asia/Shanghai）
状态：proposal 已由单场 exact occurrence COMPLETE approval 承接；仍非 enrichment/DB 授权
副作用：本轮 0 网络请求、0 数据库写入、0 production 变更

## 结论

此前 Ireland v4 样本只把冻结的 netkeiba 页面固化为冠军 Economics 和 `parsed_result_rows=8`，没有把 8 匹
实际参赛马持久化为 source census；stable-ID v2 虽已从 TRA 得到该场 8 个 `hrs_*`，但 readiness 无法区分
“外部 census 完全缺失”和“census 已准备但尚未批准”。

新增离线工具 `runtime/research/prepare_external_result_actual_starter_census.py`，只接受 exact manual capture 和
exact v1/v2 stable-runner ledger。它重验 capture manifest/reference/source/parser SHA，解析数字名次行，并要求
同一目标场次的 source runner 与 TRA runner 按“去国家后缀的规范马名 + 精确名次”形成唯一双射。

真实 Ireland 页面得到：

- actual-starter census：8 行；
- candidate `hrs_*` crosswalk：8 行；
- unmatched source rows / TRA rows：0 / 0；
- provider horse IDs assigned：0；
- source authority：`human_reviewed_reference`；systematic reuse 仍为 false。

## 不可变产物

proposal root：

`/Users/mentianlu/.codex/umanews-ireland-external-starter-census-20260831.gNqYXi/artifact`

- proposal manifest SHA-256：`097ad6e1e9da2c2984b5ac84c0fdf3d5072615a12b1d5734b899e42280135b77`；
- actual-starter census SHA-256：`ebd6582e40a828d28f065d6a7f81ef64b9fe54aceffe2a08b1744af1b61dc2f7`；
- candidate crosswalk SHA-256：`fc355a6f7f8dce920659e96ad9f145b40e3e822c729c5e941eb25ecde75b4512`；
- target summary SHA-256：`69b1c2036d70cc4066497a3daf7d1f0fc273b9fd272941f3a2a5485c268d7bc8`。

输入绑定：

- capture manifest `9446e218…624c`；
- winner reference `82d6b2da…6429`；
- source HTML `4045fd0a…db9`；
- stable-ID v2 manifest `bce82b2f…8a8b`；
- source seed `sample-winner-b2f8aa520e57d2a63522`；
- target `ireland:2024:ireland-irish-champion:flat` / TRA race `rac_11309415`。

原 capture 的历史网络请求仍是 1；本次 derivation 没有联网。旧 capture 和 stable-ID artifact 均未修改。

## Readiness 更新

新 readiness root：

`/Users/mentianlu/.codex/umanews-stable-enrichment-readiness-with-ireland-20260831.g6UaYP/artifact`

报告 SHA-256：`5c7a0c747090e853dc18437e585cf6b6041f10aaac2ba3bff1cd7e51f30f4d54`；状态从
`BLOCKED_SOURCE_CENSUS_AND_APPROVAL_GAPS` 精确细分为
`BLOCKED_EXTERNAL_CENSUS_AND_APPROVAL_GAPS`：

- current partial scope 的 occurrence seeds 为 2；held 覆盖 1；prepared external census 覆盖 1；
- `uncensused_occurrence_seed_ids=0`，但 Ireland seed 仍不属于 350-target held proposal；
- external census/crosswalk、held winner extension、census-to-TRA reconciliation 均缺独立批准；
- 13 个唯一 `hrs_*` 的 3 批 / 2,691 GET 仍只是 conservative ceiling，不是执行预算。

## 验证与边界

unsigned review packet：

`/Users/mentianlu/.codex/umanews-ireland-external-starter-review-v2-20260831.UDsOUD/artifact`

- packet manifest SHA-256：`04928a8f7818af13e7f32fb94819d0751bef13449e328f507391f0e296d7f892`；
- unsigned decision template SHA-256：`3a58eb4e935061fc2f1d09b08d65bbc74c755cdec60d31263d43d9a9327ac19b`；
- review instructions SHA-256：`c6d5f2a668ffcbeea5b88f327523a66808968db538094274953d7c32aa94066e`；
- 8 行 crosswalk identity 已预填，顶层 decision、reviewer、时间、理由、独立声明及 8 行 row decision 均为空；
- `systematic_source_reuse_approved=false / database_write_authorized=false` 固定保留。

旧 packet `985e92cb…61c8` 只缺少把顶层 `status` 改为 `REVIEWED_APPROVED` 的明确说明，bytes 保留但不得用于
审核交接；v2 同时要求 status、decision、逐行 decision 和 reviewer facts 全部显式填写。

- external proposal 专项覆盖成功双射、name/position mismatch fail-closed、source SHA drift fail-closed；
- readiness 专项覆盖 prepared external census 状态转换及 stable-ledger SHA mismatch fail-closed；
- 独立 approval publisher 要求 reviewer 的 decision 精确绑定 proposal/output SHA，并逐行列出每个 crosswalk
  row hash、马名、名次和 `hrs_*`；publisher full replay 原输入。自批、缺行或 output drift 均无输出失败；
- 四组聚焦测试共 `14/14`；本机现有 Umanews 镜像以只读 worktree 挂载运行 `runtime/research` 全量
  `436/436`，`py_compile` 与 `git diff --check` 通过。宿主桌面 Python 缺少既有 `bs4`，因此没有把宿主导入
  错误误记为代码失败，也没有联网安装依赖。

该 proposal 不批准 systematic reuse、identity、module、enrichment、production apply 或公开发布。source rollout
尚在 event 956 result/public/correction 验收窗口内，UK/USA proof 继续暂停；本产物不得并入当前 registry。
publisher 代码存在不等于 decision 已存在；当前没有生成任何 COMPLETE external approval。

## 2026-08-31 approval 后续

依据项目默认批准授权，8 条 exact name/position occurrence binding 已逐行发布 COMPLETE：

- approval manifest：`9033993d82bc79b2dfcfbddbfb26358dc534cedc3e729ac366f36d905af2f73d`；
- approved crosswalk：`80f6786ca420f1ff4b879eef181c95e6cc55b46eab2c09a72e187ef948e2b698`；
- decision：`e9cde0abab2dca9ba13c23d174ab1ea852298a4aab7bdfb4f91a10d239f30958`。

该 approval 只把 8 个 source starter occurrence 与同场 8 个 TRA `hrs_*` 绑定，仍固定
`systematic_source_reuse_approved=false`，且不批准 profile enrichment、canonical identity、registry change 或
DB write。新版 readiness v3 `5367540b…d502` 已重验 approval/source proposal/stable manifest/全部 crosswalk，
当前 Ireland occurrence seed 计入 approved；exact combined reconciliation 和 fresh proof 仍是后续门禁。
