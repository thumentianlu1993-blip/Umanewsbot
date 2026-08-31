# 350 场 reviewed-held 冠军 seed 扩展 v2（2026-08-30）

状态：`PREPARED_NOT_EXECUTABLE`；等待独立 exact-SHA decision
副作用：0 TRA 请求、0 数据库写入、0 production 变更

## 结论

旧提案 `d810272f…2441` 已不能由当前 generator 从其绑定输入逐字重放，publisher 正确失败关闭。重放差异不是
无害格式变化：当前冲突检查发现 313 条既有 COMPLETE seed 中有两条第三方 winner 与 France Galop 唯一
official winner 冲突：

- `2026-07-14 Paris (G.P. de)`：旧 ZEturf seed 为 `GERARD TER BORCH`，官方结果为 `Maltese Cross`；
- `2026-07-05 Saint-Cloud (G.P. de)`：旧 ZEturf seed 为 `ZELMAN`，官方结果为 `Calandagan (IRE)`。

因此不能继续宣称“313 条全部逐字复用”。v2 的守恒为：311 条旧 seed 复用、37 条缺失 seed 新增、2 条错误
旧 seed 显式替换，最终仍为 350 个 target/350 条 combined seed candidate。

## 冻结 v2 提案

- root：`/Users/mentianlu/.codex/umanews-held-winner-seed-extension-final-v2-20260830.Ibybid/artifact`；
- proposal manifest：`f950593c8f2d2043d1bbdfe81167eb29258f8acf3d60928a5af1c4b2840df787`；
- existing bindings：313 行，`9fd7a3e15336e766d9b3d9acd0f3dd308449548ab8e59893210ea6bc226125d9`；
- review candidates：39 行，`ae5be072e7e2536caf96a822811a8d610a7506db37200d4c487726d4a431e845`；
- combined seeds：350 行，`6e91cc1f679ba95219f8d60f4e5d4cdbe3aceed0b8ad0f83c066f4040031deda`；
- generator：`031bdd14fd7a0f2f2e7e0c8a474bc410e0f9e3227a7550de4fcf8413f73489b8`；
- publisher：`606b38cefaaea16255366be69795c062e8ed553ec2cbd9d3368bb23976a1d303`。

所有 artifact 文件为 `0600`，parent 为 `0700`。publisher 已对 v2 做当前代码完整 replay，350 seed、三份 member
SHA、精确文件集合、0 network/0 DB 均通过。

## 审批边界

39 条 candidate 必须由非实现者逐项审核并提交带时区、independence acknowledgement、immutable decision
reference、proposal SHA 和三份 output SHA 的 regular decision file。当前没有该文件，所以没有生成
`APPROVED/COMPLETE` seed artifact，也没有创建 26 批网络计划。

旧提案及旧 313-seed 24 批计划保留历史证据，但两条错误 winner 使其不能作为新的 350-target 执行输入。
未来只有 v2 或其后可重放、独立批准的版本能进入 350-seed batch planner；每批仍需 fresh exclusive proof 与
exact G3。

## 验证

- proposal + publisher 专项：`10/10`；
- v2 publisher full replay：通过；
- `network_requests=0 / database_writes=0`。
