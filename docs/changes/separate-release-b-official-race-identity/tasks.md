# 任务

- [x] (application) 为官方结果身份、不同 URL 和不可信 marker 增加 RED 测试。
- [x] (application) 实现最小 `_official_result_identity` 和严格 fallback。
- [x] (application) 运行 Release B 聚焦测试并确认 GREEN。
- [x] (operations) 只读核对生产 12 对的 approved provider/URL/content SHA。
- [x] (application) 完成 Django check、migration drift、diff check 与独立 review。
- [ ] (operations) 提交精确 G2/G3 发布包并等待一次用户确认。
- [ ] (operations) 合并、部署固定 SHA、生成新 census 并审核 overlay。
- [ ] (operations) 门禁通过后执行 manifest-bound apply/verifier。
- [ ] (integration) 启动并有界监控 2025 `full_network=true` workflow。
- [x] (application) 修复 canonical path 临时 staging 的条件唯一冲突并新增生产形状回归。
- [x] (application) 在 SQLite 与 PostgreSQL 16 运行最终完整 Release B `38/38`。
- [x] (application) 对 path staging follow-up 完成独立只读审查。
- [ ] (operations) 发布 follow-up 固定 SHA 并生成全新 census/reviewed artifact。
