# TRA targeted-horse 批次执行账本

状态：代码与离线合同已完成；真实 G3 proposal、exclusive-account proof 和网络 claim 均未生成。
本步骤没有调用 The Racing API、读取凭据或写业务数据库。

## 结论

313 个 reviewed winner-anchor 的 24 批计划现在有独立于 production apply ledger 的网络执行账本。
`racing_api_targeted_batch_export.py` 的 CLI 已改为强制要求：

- 精确 batch plan manifest/plan SHA；
- 当前 ordinal 的独立 G3 approval；
- 与 G3 proposal SHA、credential alias、scope ID 精确绑定且仍在有效期内的 exclusive-account proof；
- 私有 execution ledger 的唯一 claim；
- 与 approval 完全相同的 seed、输出目录、预算目录、参数、request ceiling 和 resume 状态。
- 与 proposal/approval 完全相同的 OpenAPI fingerprint 绝对路径、文件 SHA 及内部 selected contract/schema。

因此，直接手工给 seed/ceiling 调用网络 CLI 已不再是有效执行路径。底层 Python 函数仍保留给离线测试和
组合调用，但不读取环境、不开网络；生产运行必须经过 CLI claim。

## 冻结计划只读验收

- plan root：
  `/Users/mentianlu/.codex/umanews-targeted-batch-plan-313-20260829.ESBLjZ`
- manifest SHA-256：
  `de9f321784f927ac1ca76ac7e9f504b79afa93a9590db546dc1dc0208655c247`
- plan SHA-256：
  `88c002273c837e8f4373b209d7c59f2efaa1dbfc6e790e16f0c335c62cf3653d`
- 新 loader 逐批重读 24 个 seed ledger，验证 path/size/SHA/rows、ordinal、总 seed 和总预算；结果仍为
  `24 batches / 313 seeds / 5,008 GET`。

这只是冠军锚点定位计划，不能冒充完整 actual-starter census 或后续 stable-ID 全资料预算。

## 状态机

```text
plan + ledger(next ordinal)
  -> PROPOSED_NOT_APPROVED G3 proposal
  -> independent exact approval
  -> fresh exclusive proof
  -> running claim
     -> COMPLETE batch artifact -> completed receipt -> wait >= 30 minutes
     -> safe-stop attempt -> new resume proposal + new approval + new proof
```

账本只允许一个 active batch，并严格使用 `len(completed)+1`。claim token 防止另一进程复用同一 approval；
完成时重新验证 batch manifest/COMPLETE、seed SHA、参数、seed count、请求数和零数据库写入。以后每次读取
ledger 还会重读所有已完成 batch manifest/COMPLETE；产物丢失或哈希漂移时停止后续批次。

## 续跑预算语义

进程内 GET cache 不跨 resume。某 seed 中途失败时，下次必须从该 seed 重新运行；已发出的 request 不会
返还。账本因此保存每次 attempt 的：

- approval/proposal/proof SHA；
- 本次 ceiling 和实际 request count；
- safe-stop 类型、脱敏错误和 account-budget state SHA；
- 完成 batch manifest SHA。

retry proposal 根据 checkpoint 只计算未完成 seed 的新最坏 ceiling，同时显式列出
`prior_request_count` 和 `cumulative_request_ceiling`。例如原批 8 GET、已消耗 5 GET 且剩 1/2 seed，
retry 本次 ceiling 为 4，累计批准上限为 9；不能继续拿原 8 GET approval 重放。

若 claim 后在首个 request 前发生本地 preflight 错误，账本保留 `request_count=0` 的 attempt，并允许使用
新的输出/budget 路径生成 fresh-run proposal；只要已消耗 1 个或更多 request，没有精确 safe-stopped
checkpoint 就拒绝续跑。

## 命令边界

准备下一批 proposal（零网络、零数据库写入）：

```bash
python3 runtime/research/racing_api_targeted_batch_execution_ledger.py prepare \
  --plan-root=<exact-plan-root> \
  --plan-manifest-sha256=<exact-manifest-sha> \
  --batch-plan-sha256=<exact-plan-sha> \
  --execution-ledger=<private-ledger.json> \
  --batch-output-dir=<new-absolute-output-dir> \
  --account-budget-root=<new-private-attempt-budget-dir> \
  --credential-alias=tra-primary \
  --account-scope-id=<unique-batch-attempt-scope> \
  --openapi-fingerprint=<reviewed-fingerprint.json> \
  --approved-openapi-fingerprint-sha256=<exact-file-sha256> \
  --output-dir=<new-proposal-dir>
```

`publish` 只在项目所有者批准 proposal manifest 的精确 SHA 后运行。网络 CLI 还必须提供 G3 approval、
fresh proof 和上述全部冻结参数；任何参数漂移在 claim 前失败。发生 safe-stop 后不得手工清空 active；应先
确认旧进程已经退出和账号无其他 caller，再用账本记录实际 account request count，重新生成 retry proposal。

fingerprint 身份进入 G3 proposal 的 `scope.run.openapi_contract`。claim 会重新读取文件并用命令传入的
path/SHA 重建 scope；即使内部 selected hash 相同，改用另一文件路径或 bytes 也不会复用旧 approval。
batch manifest completion 和 resume definition 继续与该 scope 做 exact comparison。

## 当前未执行原因

- Montjeu N1 虽已批准，但当前进程 `RACING_API_USERNAME`、`RACING_API_PASSWORD` 均为 missing；
- N1 未完成前，四地区样本和 24 批均不得开始；
- 真实运行 host、绝对输出目录、budget root 和现场独占检查尚未冻结，因此没有提前生成伪 G3 proposal；
- 24 批仍需逐批独立批准，不能由本代码或本文自我批准。

## 验证

- 新 execution-ledger 专项：`4/4`；
- 与 targeted batch runner 合并：`10/10`；
- `runtime/research` 全量：`307/307`；
- 真实 24 批计划只读合同：`24 / 313 / 5,008`；
- `py_compile`、`git diff --check` 通过。

完整 `stable` suite 的既有失败状态不变；上述聚焦通过不能覆盖该结论。
