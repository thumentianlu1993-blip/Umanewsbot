# TRA 网络与批次入口 strict JSON 复核

日期：2026-08-31

## 结论

严格 JSON 边界已从 materialization/staging 前移到最早 ingress。以下输入全部拒绝 duplicate key 和
`NaN/Infinity`：

- HTTP 200 provider response，包括 credential/entitlement diagnostic；
- 冻结 OpenAPI fingerprint 与单马 targeted seed；
- bulk target-ledger manifest 与 JSONL；
- targeted batch seed ledger 与本地 batch-definition/checkpoint JSON。

SHA/COMPLETE marker 只证明字节身份，不能证明 JSON 语义唯一。测试已覆盖重新计算内容 SHA、manifest SHA 和 marker
后仍失败关闭。

## 验证

- `test_racing_api_auth_diagnostic.py`：`3/3`；
- `test_racing_api_horse_export.py`：`42/42`；
- bulk + targeted batch 专项：`17/17`；
- 完整 `runtime/research`：`579/579`；
- candidate/identity/module/global/staging Django 链：`97/97`；
- change test IDs：`338/338` 唯一。

## 生产边界

本轮没有 acquire shared lock、停止 Beat、修改 canonical/reference registry、生产联网、数据库写或消费
`race_live`。event 956 尚未明确释放，旧 `race_live=7543` 保持不变。

selection v2 的当前零写审计仍返回 France 2023 / 5 seeds / 1,035 GET / zero-search，execution ledger 与 lock SHA
未变化；当前进程 username/password 只读状态均为 `set`，未显示值。event-owner 的复核 turn 没有返回可见结论或
evidence，因此不能替代明确 safe-window release。
