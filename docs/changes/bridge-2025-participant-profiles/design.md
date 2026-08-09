# 设计

新增纯离线批次编译器，输入 `p0_participant_candidates.json`，按允许地区和稳定 candidate key 排序，
输出共享 source snapshot、生产 census manifest、全局 batch plan 与若干单地区批次目录。每个目录包含
reviewed CSV 和 v2 review manifest；独立 execution ledger 以文件锁和原子替换维护严格 ordinal。

现有 `run_reviewed_p0_horse_completion_batch` 增加可选 batch contract：

- 旧 manifest 无 contract 时保持精确 50 行合同；
- v2 contract 声明逐地区行数、source/生产 manifest/global plan identity 和范围；
- loader 重读三层 evidence，逐行比对身份、来源、实际起跑证据、review 状态及全局唯一 membership；
- 网络 adapter、cache、完整度、module review 和 production release 逻辑不变。

本变更不新增 migration，不写生产数据库，不启用常驻网络开关，也不纳入澳洲、德国或中东。
