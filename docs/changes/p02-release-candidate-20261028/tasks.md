# 任务

- [x] (application) 对照 main 提取 P02 并移除 0082 假依赖。
- [x] (application) 验证模型/迁移、核心/地区与受影响回归，保存证据。
- [x] (operations) 明确六步迁移、关闭态升级、中断续跑和精确恢复流程。
- [x] (operations) 独立审核候选与升级流程。
- [ ] (operations) 后续发布演练：测试先行实现 P02 独立受保护执行器；验证 exact recorder/catalog、并发锁、拒绝漂移和故障续跑。
- [ ] (operations) 后续发布演练：固定镜像运行 CI、真实形状隔离副本 DDL/备份恢复/故障注入；回填资源与时限。

下一项业务准备：按地区补齐来源的五类能力证据。执行器、CI和镜像演练未完成前不能提交生产执行请求。

- [x] (application) 修复全量CI直接发现的历史fixture、模板空白、固定查询预算及迁移测试恢复范围，定向复验通过。
- [ ] (operations) 四项集成修复聚焦复审并重跑固定提交全量CI。
- [ ] (operations) 独立处理[10项既有环境缺口](ci-environment-gaps.md)，不自动延期skip豁免。完整候选CI未通过前，第1项不能标为发布就绪。
