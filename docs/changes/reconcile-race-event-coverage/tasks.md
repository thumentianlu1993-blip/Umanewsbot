# 任务

- [x] 1. (application) 固化 RED 测试和 2024/2025 分层边界。
- [x] 2. (application) 实现只读 reconciliation 分类与 identity hashing。
- [x] 3. (application) 实现 `not_due` 采用既有 scheduled/postponed event 的事务服务。
- [x] 4. (application) 实现版本化 historical/current/result 覆盖报告。
- [x] 5. (application) 实现 artifact 原子导出、HTML/CSV 审核表、manifest、独立 approval 和 verifier。
- [x] 6. (application) 实现 manifest+approval 双哈希绑定的 dry-run/apply/rollback 管理命令和 OperationLog。
- [x] 7. (application) 调整现有赛事导入路径复用共享关联规则，保持旧历史物化行为。
- [ ] 8. (application) 运行 focused、历史批次、赛事导入和完整 stable 回归。
  - 首次 reviewer 修复后 focused `22/22`，历史批次/赛事导入专项合计 `100/100`。
  - 旧失败 `RaceEventPageMVPTests.test_csv_import_candidate_fetch_and_candidate_apply` 已以测试夹具最小修正解决，单测 `1/1`；生产门禁未放宽。
  - 按用户要求未重新启动超长完整 `stable`，因此本项保留未完成。
- [ ] 9. (operations) 在生产生成全量只读审计，核对 2025–2026 五地区及东海锦标。
- [ ] 10. (operations) 取得当前内容的发布授权后构建并切换镜像。
- [ ] 11. (operations) 备份、校验、dry-run、串行 apply、逐目标 verifier；公开开关保持关闭。
- [ ] 12. (operations) 回写 current_state、decisions、deploy_runbook、project_status。
