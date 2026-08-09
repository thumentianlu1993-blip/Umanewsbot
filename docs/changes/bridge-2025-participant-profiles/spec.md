# 2025 五地区参赛马资料桥接规格

## 目标

把生产只读生成的 2025 年实际起跑马候选 census，确定性切分为可续跑、可审核、SHA 绑定的
P0 资料补全批次。范围仅包含日本、中国香港、英国、法国和美国；澳洲、德国和中东不进入本轮。

## Requirements

### Requirement: 批次必须绑定原始候选 census

每个批次必须绑定同一份 regular non-symlink 候选 JSON、生产 census manifest 和全局 batch plan 的
路径、大小和 SHA-256，并保存单一地区、连续 rank、候选行数、唯一 ordinal 和批准范围。运行时必须
逐级拒绝 symlink、重新校验全局无重叠与总数守恒，不能仅信任导出的 CSV。

### Requirement: 只允许实际起跑且可继续补强的候选

只有 `actual_start_evidence_count > 0`、存在来源 URL、无 identity conflict 的候选可以进入批次。
弱身份可以进入 provider profile identity enrichment；来源搜索无结果、多解或四字段不一致时仍须
fail closed 到 blocker，不得按马名直接绑定或新建。

### Requirement: 批次有界并可部分收敛

每个批次只处理一个地区且不超过现有地区批次上限。成功对象生成后续 module review 产物，失败对象
留在 blocker pool；不得因部分失败丢弃已完成 cache，也不得为凑固定五地区各十匹而重复候选。
严格顺序 execution ledger 必须拒绝跳批、重复已完成批次或不同 manifest 抢占，并允许相同 active
身份从精确 cache 续跑；最终 verify 必须证明所有 ordinal 均已完成。

### Requirement: 兼容既有首批 50 匹合同

没有新 batch contract 的既有审核 CSV 继续严格要求五地区各 10 匹。新入口不能放宽历史 artifact 或
production apply 的审核、release candidate、用户批准和 verifier 门禁。
