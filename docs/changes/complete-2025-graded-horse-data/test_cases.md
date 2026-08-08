# 2025 分级赛参赛马补全与生产导入测试

## 研究 artifact

- RED：强制英文地区的正式赛果行只有纯拉丁 `horse_display_name`、profile not found 时，旧实现错误
  输出 `missing_required_english`。
- GREEN：同一赛果行填入 `name_en`，但 profile issue 仍保留；混合中文/日文字符串不得误填英文。
- policy version 变化拒绝恢复旧 checkpoint。
- AU/DE/UAE/SA/QAT/BHR 官方 fixture 覆盖 G1/G2/G3、退赛、DNF、DSQ、同着、马号缺失和 horse ID。
- 官方 catalog 与 results 数量/URL/provider ID 守恒；缺结果或等级不明时 partial/blocked。

## 身份与补全

- provider horse ID 唯一绑定 existing profile；同 provider ID 多档案阻断。
- 四字段完全一致可绑定；仅马名、同名多候选、出生/父母冲突均阻断。
- existing empty profile 走 update，不创建重复 profile。
- new region 不得降级成 `other`；country 与 middle-east region 分开验证。
- 缺基础字段、二代血统任一字段、总出赛数或生涯行不对齐时不可进入 reviewed apply。
- 主胜鞍只由正式生涯 won+G1/G2/G3 重算；来源摘要冲突进入 blocker。

## 生产 apply

- prepare/dry-run 零业务写；manifest、mapping、DB identity 任一漂移拒绝。
- apply 单事务、receipt exactly-once、reverse ledger no-replace、同 artifact 重放零写。
- 新档案不自动公开，不启用 auto update/first publish，不发送外部消息。
- verifier 覆盖 create/update/alias/record/major-win 守恒与 scope 外零变化。
- SQLite 聚焦、真实 PostgreSQL migration/并发/rollback、Django check、migration drift 全部通过。
