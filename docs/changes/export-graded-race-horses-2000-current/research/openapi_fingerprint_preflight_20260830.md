# TRA OpenAPI 指纹请求前门禁

日期：2026-08-30（Asia/Shanghai）
状态：本地合同完成；`/openapi.json` 在线刷新仍待单独 exact G3
外部副作用：`0` TRA 请求、`0` 数据库写入、`0` production 变更

## 结论

`racing_api_horse_export.py`、`racing_api_bulk_results_export.py` 和
`racing_api_targeted_batch_export.py` 现在都强制接收：

- `--openapi-fingerprint=<reviewed-local-file>`；
- `--approved-openapi-fingerprint-sha256=<exact-file-sha256>`。

三个入口在账号预算、批次 claim、client 和首个 GET 前验证冻结文件。底层 artifact 函数也会在首个
client call 前重新打开同一路径并重验，避免 CLI 预检后文件被替换。manifest/批次 definition 记录该
文件的绝对路径、SHA、size、生成时间、source URL、full OpenAPI SHA、version 以及 selected
contract/schema SHA；resume 时任一身份漂移都会失败关闭。

## 冻结身份

- 文件：`tra_openapi_fingerprint_20260829.json`
- 文件 SHA-256：
  `c1dad02e0e53a48e6e7d889af2ce97032c79d0fbf56fe002ac67c6589a3a8b92`
- source URL：`https://api.theracingapi.com/openapi.json`
- OpenAPI version：`1.4.4`
- full OpenAPI SHA-256：
  `e1ec8bd34df75808fae65cbaffb0c634adf204fa7d06627d92421dd86193a06b`
- selected contract SHA-256：
  `d291af21a5a646ec803e9bafcdeb8786b87593dff6dfc10220da8ce00a66a0c9`
- selected schema SHA-256：
  `e7298d8a29751d8e985400e626a9b28abf3c39ef80fb0a9dce8b51591f61df0c`

文件 SHA 与文件内部的 full OpenAPI SHA 是两个不同身份：前者批准当前 review artifact 的精确 bytes，
后者标识生成该 artifact 时的完整 provider schema。命令不得混用。

## 请求边界

Montjeu N1 只批准 horse search、候选 horse results、唯一候选 Pro/Standard 和最多两个父母
Pro/Standard，最多 16 GET。`/openapi.json` 不在批准路径中，因此本轮没有为了“在线比对”偷偷增加第
17 个请求或新 path。

当前门禁由两层组成：

1. 请求前：冻结文件 exact SHA + 内部 source/version/full/selected path/schema 合同；
2. 每次受批响应后、下一请求前：search result 的 `hrs_*`/name，profile 的 ID/名称/父母 ID，results 的
   `results/total/limit/skip/query`、race/runner/position 与分页守恒分别由 endpoint-specific validator
   校验。

这能阻断本地合同或实际响应漂移，但不声称 provider 当前 `/openapi.json` 与 2026-08-29 bytes 在线相同。
真正在线刷新必须先新增该 path/request 的 exact G3；若结果变化，先冻结新 artifact、独立 review 并更新
fixtures/normalizers，再重新批准业务 proof。

## Safe-stop 顺序

1. network 双门未开启：退出；
2. request ceiling 公式不匹配：退出；
3. fingerprint 文件缺失、symlink、超 64 KiB、文件 SHA 或内部合同漂移：exit 75；
4. 仅全部通过后才读取 exclusive proof/account budget、创建 batch claim/client；
5. live response schema/pagination 漂移：记录已实际消耗的请求后停止，不发下一页或下一 endpoint。

targeted batch 的 fingerprint 身份进入 batch definition parameters，所以 resume 不能换成另一份 schema
继续；它也进入逐批 G3 proposal/approval scope，claim 会重建 scope 并比较命令的 exact path/SHA；单 seed
与 bulk manifest 也保存同一身份。

## 验证

- `test_racing_api_horse_export.py`：`27/27`；
- `test_racing_api_bulk_results_export.py`：`6/6`；
- `test_racing_api_targeted_batch_export.py`：`6/6`；
- historical bridge/materializer 相邻测试：`6/6`；
- 合计：`45/45`；
- targeted batch execution-ledger（含 fingerprint approval/claim/resume/completion 绑定）：`4/4`；
- `runtime/research` 全量：`310/310`；
- `py_compile` 通过。

专项覆盖有效指纹、文件 SHA 漂移、内部 version 漂移、预算/client 前停止、预检后文件替换、manifest
绑定和 batch resume 定义绑定。上述数字是本地聚焦证据，不替代完整 `stable` suite，也不构成 G2、G3、
commit、deploy 或 production apply 授权。
