# The Racing API schema v2 proof runner 测试用例

## 测试先行 RED

1. schema v2 + `region=france` 应按固定顺序构建 today/tomorrow/results 三条 URL，并在
   manifest 记录实际 path；旧实现因不接受 `region` 真实 RED。
2. 缺失 region、非法 region、超过 registry budget 均应在 transport 前拒绝；旧实现因缺少
   参数支持真实 RED。
3. 管理命令应接受并透传 `--region`；旧命令以 unknown option 真实 RED。
4. schema v2 命令缺少 region 应得到 `CommandError`，transport 为 0；旧实现以
   `KeyError: endpoints` 真实 RED。

## 回归

- schema v1 原有 12 项 proof 合同保持 GREEN；
- v2 route builder、多地区 pipeline、racecard sync 回归；
- secret 权限、registry SHA/terms/evidence/预算、redirect、超时、响应大小和 atomic artifact；
- 非法 URL 测试使用未支持地区 code，并 mock resolver，断言拒绝路径绝不触网；
- `Django check`、`makemigrations --check --dry-run`、`py_compile`、`git diff --check`。

## 当前结果

- 新增合同测试：`4/4 GREEN`；
- 完整 source proof：`16/16 GREEN`；
- proof + multiregion pipeline + racecard sync：`55/55 GREEN`；
- realtime 扩展套件的 9 个 claim 时间敏感失败已在未修改 `origin/main` 得到相同签名，
  不归因本变更。

所有测试均使用 fake transport；没有读取生产 secret 或发出网络请求。

