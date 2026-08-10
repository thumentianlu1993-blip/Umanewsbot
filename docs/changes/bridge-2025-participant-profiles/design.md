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

participant completion 以参赛 occurrence 为行，旧 production apply 则要求唯一四字段身份。新增
`bridge_p0_participant_release` 作为两者间唯一入口：一次读取并验证 batch index、execution ledger、
completion manifest 和 candidates JSONL，按 `source_name + external_horse_id` 分组；重复组只忽略
`candidate_key`、抓取/官方核验时间以及 occurrence 自身的 reviewed-candidate evidence 后比较全部内容。
选择最新核验行作为 canonical，同时在 `participant_source_binding.json` 保留所有 occurrence key、
赛事入口 evidence、blocker 与输入 SHA。

输出目录采用既有 rolling batch 的 `batch_manifest.json + state.json + artifact/combined_candidates.jsonl`
形状，但只继承原 participant batch inclusion 决策，状态仍是四模块 `pending`。用户完成精确模块审核后，
才调用既有 `--bundle` 查询新鲜 production mapping snapshot；随后 `--prepare-release`、独立 release
approval、G3、apply 和 verifier 完全复用原链路，不新增旁路。
