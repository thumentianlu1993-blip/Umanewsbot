# P0 马完整资料补全收尾任务

- [x] 1. (operations) 固化 50 匹全部确认纳入的机器可读审核 artifact，并校验地区、数量和候选键。
- [x] 2. (integration) 先补统一 payload、受控来源、完整履历、artifact 和模块审核 RED 测试。
- [x] 3. (integration) 实现统一 P0 单马补全 payload 与五地区 adapter 协议。
- [x] 4. (integration) 实现来源逐场结果到 `HorseRaceRecord` payload 的完整状态映射。
- [x] 5. (integration) 实现完整 dry-run artifact、失败/冲突清单和 SHA-256 manifest。
- [x] 6. (application) 实现候选模块 apply/ignore/conflict 审核记录。
- [x] 7. (operations) 运行 focused、相关回归、Django check、迁移漂移和静态验证。
- [x] 8. (operations) 在本地或生产备份副本执行五地区各 10 匹 dry-run，并记录 blocker。
- [ ] 9. (operations) 完成独立只读代码审核并清零 actionable findings。
- [ ] 10. (operations) 最新审核成功后重新取得发布授权，再处理主线集成与生产门禁。
