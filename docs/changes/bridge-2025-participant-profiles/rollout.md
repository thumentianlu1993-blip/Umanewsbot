# 上线与回滚

1. 代码先以所有高风险开关关闭的状态部署；无 migration。
2. 从生产只读 census 生成绑定批次；网络 prepare 使用 one-shot 精确 manifest SHA，不修改全局开关。
   每次 prepare 前 claim 全局 execution ledger；按 `prepared -> released -> applied -> verified` 绑定后才
   允许下一 ordinal，相同 active 身份才可精确续跑。
3. 每批先审核完整度与 blocker，再生成 production release candidate。
4. 只有精确 G3 批准的 release manifest 才能写库；写前备份、锁/队列检查和写后 verifier 必须通过。
5. 任一确定性身份或完整度错误停止该候选，不回退到马名合并；批次代码回滚不删除已生成 evidence。
