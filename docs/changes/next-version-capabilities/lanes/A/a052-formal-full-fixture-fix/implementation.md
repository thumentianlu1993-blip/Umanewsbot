# A052：正式 full 的历史迁移夹具兼容修正

PR245 的 head `511fcd87`，实际 merge `13a07e9339d5ac7d03cb984fac9e6955acd822c2`
与已审源码 tree 相同。pull_request run `37593926987` attempt1 正式 full 失败：
48 个 batch 报告记录 6816 唯一 ID，6 个失败 batch、166 个唯一失败方法；
原42和A050新增10无skip/error/failure/expected-failure，原10runtime skip保持。
整体 full 未通过，不能用这些局部结果作为集成交付 GREEN。

166 方法全部属于旧0078/0079 release、rollback、单迁移owner或schema preflight测试。
共同根因是 `release_0078_test_fixture.py` 的两代历史目录复制，仅显式剔除0079/0080，
0081被带入历史目录，导致原历史摘要和精确rollback ceiling按设计拒绝。
失败 artifact SHA256 `7998fe2b181d739e3d7b3cce8fd1e54a072522c6565d370c6b73e46aa4ffe68b`，
新runtime保存完整plan、48reports及日志：
`/Users/mentianlu/.codex/runtime/a052-fixed-candidate-draft-pr-formal-full-001/`。

最小修订只给历史0078/0079夹具的精确后继文件集合增加
`0081_managed_readonly_steps.py`。生产release/recovery/rollback源码、原摘要常量、
allowlist、schema/marker授权规则逐字不变；当前真实全迁移目录仍被旧合同拒绝。
原15 A/B文件、原全部测试方法和断言不变。新候选隔离自511f，旧worktree与所有失败原件保留。

在已有技术模块追加3个纯stdlib方法：提取真实fixture/contract函数，确认历史0078/0079
目录重获各自原固定摘要；未知0081/0082文件及nested/__pycache__下同名文件仍复制并被拒绝；
真实当前目录仍拒绝。相关模块共24项通过，其中本次3项。未import业务模块、未PG/Docker、
未native collect或CI重跑。新增技术方法只扩大原分母，静态预期6819，实际候选收集数待定。

新固定commit/tree、精确patch与旧源码/断言保持证明写新runtime收据，先回原R复审。
当前PR245仍Draft/head511f、失败attempt1保留；本修订未push，未另建PR或触发CI。
R/ROOT核新版本、测试计划和资源边界后才可更新PR及执行下一正式full。
