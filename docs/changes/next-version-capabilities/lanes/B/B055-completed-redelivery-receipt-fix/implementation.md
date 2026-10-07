# B055 完成态同消息重投收据修复

## 依据与边界

基线 `ddfa6e1a5586c0b102ce35f68aed7f2b801cc3a3` / tree `1776f2a0bef24c106f83b2492ca4cac9aa01bd26`。B054 实际 E01/E02 两 PASS 是基线证据；E03 实际目标 FAIL 已由原 R `f9cf04fa2468b41c92942af3b696cb336dd3c0af` 接纳，receipt SHA `03a041ecf2a4e7db1655188a5da4887f0aaacf1c7cfb37815a4b7122717cc04f`。初次真实 consumer 已落 Article/Run/final；fresh 同消息重投在 `claim_already_consumed` 分支未返回 final receipt，原测试第 238 行失败。之后的零变更、零重复调用与零通知断言没有到达，不能据此声称通过。

本轮范围是 B 私有 offline consumer 的完成态只读返回。已有 G1 授权覆盖该最小修复；不触发共享主线或生产交付，不执行 G2/G3 动作。隔离新 worktree，保留原源码、两阶段包、实际结果及全部封存证据。

## 执行顺序

1. 真实 task 路由仍先验证精确消息、登记控制键、scope 及封闭 reader/SDK 依赖。没有真实 SDK 调用。
2. 原 parent→read→Article→Run 锁序保持。仅当原 claim 检查返回 consumed 且调用方明确允许完成态时，检查 strict final_applied、原 completed claim、run success、Article translated 且无新 claim、精确 article/run/claimed_at/execution UUID。
3. 原 typed checkpoint codec 核对 payload 摘要、provenance、claim input/deadline/suppress 与 final checkpoint 摘要；Article translated_at 必须等于原 final applied_at。其他终态不授予执行权限。
4. 原当前 grant/permission epoch、期限、版本、身份与 Article 当前输入指纹校验保持。这里校验已锁 Article 字段，没有再次调用 source reader。step/request 历史及缓存校验保持，登记 identity 必须等于实时 identity。
5. consumer 在上述校验及锁后期限检查之后返回 detached 原 final receipt，保留 translated=false、skipped=true、reason=claim_already_consumed。直接退出，不进入 read_ready、模型/provider、checkpoint 保存、Article/Run apply、请求/读计数或通知路径。

普通 claim primitive、read-only cache、预算/恢复/API/task、模型授权与 writer 未修改。默认 allow_completed=false；仅私有完成路由与 consumer 入口允许受上述约束的只读重投。无 deadline 续期，无 grant/fence 绕过，无付费重试。

## 验证与下一范围

新增 21 项纯 AST 合成校准：真实控制与 typed checkpoint codec、新完成 helper 的归属/篡改/状态拒绝，完成 consumer 返回同一 detached 收据并在 downstream trap 前退出，期限到达仍拒绝。仅数据类型 import 用 stdlib stand-in，consumer 的事务和已验证 live 使用 stand-in；这些结果不证明真实 PG 锁、授权门或 E03 GREEN。

静态核验比较完整模块 AST，只有一个新 helper、上下文完成选项与早返回；其余 guard、资源/预算、读、SDK、checkpoint/apply 函数保持。原三测试方法及整个测试文件原字节不变，另外七方法未创建，35 总义务和旧 obligations 保留。

下一最小真实 GREEN 建议精确 E01/E02/E03 三方法，验证公共私有路由改动后的原两条链及完成态重投。需原 R 审新源码，再由 ROOT 授新 host 准备/PG 窗口。本轮没有 collect/native/PG/Docker/共享锁/旧 suite 重跑、生产、真实付费或 push。新候选未实际执行，M02 未完成。
