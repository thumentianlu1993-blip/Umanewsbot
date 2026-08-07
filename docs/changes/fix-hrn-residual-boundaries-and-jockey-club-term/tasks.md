# 任务

## 测试

- [x] 1.1 (integration) 测试 subagent 增加真实 HRN video dialog fixture 与结构清洗 RED
- [x] 1.2 (integration) 测试 subagent 增加合法同词正文、正常文章及非 HRN 反例
- [x] 1.3 (integration) 测试 subagent 增加 HRN 美国机构确定性译名 RED、统一编号、边界、摘要、Dummy、占位符失败和英国来源反例

## 实现

- [x] 2.1 (integration) 实现 subagent 增加 HRN `role=dialog` 来源级 DOM 清洗与审计计数
- [x] 2.2 (integration) 实现 subagent 增加 provider 共用的 HRN 来源术语计划、统一 TERM 编号、冲突映射排除和 metadata
- [x] 2.3 (application) 更新本任务状态文档，明确无 migration、历史范围与发布门禁

## 验证

- [x] 3.1 (integration) 主代理复跑聚焦、translation/terms、内容边界和历史管线回归
- [x] 3.2 (application) 运行 Django check、migration drift、diff 检查
- [ ] 3.3 (application) 未参与实现的 reviewer subagent 执行原生只读 review 与 fingerprint 双检
- [ ] 3.6 (operations) 部署后重新 prepare 剩余 36 篇，逐篇抽查并按最多 10 篇批准/apply/verify
- [ ] 3.7 (operations) 输出成功、失败、拒绝、receipt、rollback 与剩余清单，完成 evidence-only closure
