# 受审官方赛果包

本目录只保存可由研究 workflow 使用的仓库内三文件包，以及位于包目录外的审核 receipt。包目录必须只包含
`official_result_manifest.json`、`official_result_gaps.json` 和 `summary.json`，否则验证器会拒绝运行。

2025 年当前受审包为 `2025-official-results-433-r2`，精确身份与范围记录在
`2025-official-results-433-r2.review.json`。该包守恒覆盖 433 场：德国及中东 87 场进入 collect，澳洲
346 场保留为 `evidence_gap`。审核 receipt 不是生产写入、澳洲采集、official-results 网络运行或
`full_network=true` 的授权；这些动作仍遵守各自门禁。
