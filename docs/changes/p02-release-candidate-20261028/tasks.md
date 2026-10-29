# 任务

- [x] (application) 对照 main 提取 P02 并移除 0082 假依赖。
- [x] (application) 验证模型/迁移、核心/地区与受影响回归，保存证据。
- [x] (operations) 明确六步迁移、关闭态升级、中断续跑和精确恢复流程。
- [x] (operations) 独立审核候选与升级流程。
- [ ] (operations) 后续发布演练：测试先行实现 P02 独立受保护执行器；验证 exact recorder/catalog、并发锁、拒绝漂移和故障续跑。
- [ ] (operations) 后续发布演练：固定镜像运行 CI、真实形状隔离副本 DDL/备份恢复/故障注入；回填资源与时限。

下一项业务准备：按地区补齐来源的五类能力证据。执行器、CI和镜像演练未完成前不能提交生产执行请求。

- [x] (application) 修复全量CI直接发现的历史fixture、模板空白、固定查询预算及迁移测试恢复范围，定向复验通过。
- [x] (operations) 四项集成修复聚焦复审并重跑固定提交全量CI；6978项无failure/error，10项过期skip阻断。
- [x] (operations) 补齐[10项既有环境缺口](ci-environment-gaps.md)，实际执行10项通过并移除过期skip豁免；独立复审通过。完整候选CI仍以PR当前提交检查为准。

## 已授权CI补齐范围（2026-10-29）

- [x] (operations) 原全量6978项已核实：failure/error=0，10项过期skip导致最终验证失败。
- [x] (operations) 为精确ID、身份、镜像映射和缓存篡改补充拒绝测试；方案C1/C2复审通过。
- [x] (integration) 打包7份已保存原始公开页面与必要元数据，8项真实缓存断言及邻近回归47项通过。
- [x] (operations) 实际容器执行10项全部通过，root权限归零、应用镜像唯一审核文件、双镜像身份及额外文件拒绝均有证据。
- [x] (operations) 独立实现审核3项问题已修复并由原reviewer复审通过。
- [ ] (operations) 最终固定提交全量CI：状态与证据以PR #270当前提交检查为准，本文件写入在CI之前。
