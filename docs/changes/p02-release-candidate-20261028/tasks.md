# 任务

- [x] (application) 对照 main 提取 P02 并移除 0082 假依赖。
- [x] (application) 验证模型/迁移、核心/地区与受影响回归，保存证据。
- [x] (operations) 明确六步迁移、关闭态升级、中断续跑和精确恢复流程。
- [x] (operations) 独立审核候选与升级流程。
- [ ] (operations) 后续发布演练：测试先行实现 P02 独立受保护执行器；验证 exact recorder/catalog、并发锁、拒绝漂移和故障续跑。
- [ ] (operations) 后续发布演练：固定镜像运行 CI、真实形状隔离副本 DDL/备份恢复/故障注入；回填资源与时限。

地区五类能力证据已形成[第2项盘点](../p02-source-capabilities-20261029/report.md)，缺口保持显式阻断；下一项业务准备：冻结目标覆盖与容量预算。执行器、CI和镜像演练未完成前不能提交生产执行请求。

- [x] (application) 修复全量CI直接发现的历史fixture、模板空白、固定查询预算及迁移测试恢复范围，定向复验通过。
- [x] (operations) 四项集成修复聚焦复审并重跑固定提交全量CI；6978项无failure/error，10项过期skip阻断。
- [x] (operations) 补齐[10项既有环境缺口](ci-environment-gaps.md)，实际执行10项通过并移除过期skip豁免；独立复审通过。完整候选CI仍以PR当前提交检查为准。

## 已授权CI补齐范围（2026-10-29）

- [x] (operations) 原全量6978项已核实：failure/error=0，10项过期skip导致最终验证失败。
- [x] (operations) 为精确ID、身份、镜像映射和缓存篡改补充拒绝测试；方案C1/C2复审通过。
- [x] (integration) 打包7份已保存原始公开页面与必要元数据，8项真实缓存断言及邻近回归47项通过。
- [x] (operations) 实际容器执行10项全部通过，root权限归零、应用镜像唯一审核文件、双镜像身份及额外文件拒绝均有证据。
- [x] (operations) 独立实现审核3项问题已修复并由原reviewer复审通过。
- [x] (operations) 提交633fecc5完整CI 40813370000通过6990项/51批，failure/error/skip=0；候选目录外交付核验verified。新提交另看当前检查。

- [x] (application) 修复全量CI发现的改期测试日期碰撞；新增日期不变量回归，26项PG测试及原reviewer审核通过，未改生产代码。

## 第3项目标与容量冻结准备（2026-10-29）

- [x] (operations) 只读事务盘点完整未来canonical清单及历史空确认、七天候选库存，保存固定摘要；未改生产。
- [x] (integration) 固定79场/25已知重点/25重点未知/29已知非重点基线与逐host预算台账，全部未知来源/额度保留阻断；见[报告](../p02-target-capacity-20261029/report.md)。
- [ ] (integration) 完整独立地区分母、逐场身份、历史义务归属、来源许可/额度及请求链成本闭合。
- [x] (application) 容量准入合同补齐未确认首日6次复查与实际全库存/多链成本并完成拒绝测试；见下方第3项继续收口，真实成本证据仍阻断。
- [x] (operations) 独立评审冻结准备包并复验，P2修正后原reviewer及原生复审PASS；第3项生产冻结仍未完成，见[评审](../p02-target-capacity-20261029/review.md)。

## 第3项继续收口（2026-10-29）

- [x] (operations) 只读交叉分类10,134场历史空确认，保存19场在管未完成与1场临时发布不一致；2场观察起点有official修订/publication证据。
- [x] (integration) 补两个未匹配英国目标、25场原等级依据与119/199来源身份候选；仍无生产绑定/自动用途和额度证明，见[覆盖表](../p02-target-capacity-20261029/identity-coverage.md)。
- [x] (application) 取得+4低估、缺库存仍放行、跨proof借用、未知等级低预算的RED，补+6及完整库存/成本/权限/逐目标绑定，78项隔离PG回归通过。
- [x] (operations) 真实阻断候选103条运行离线容量诊断，ready=0，未知未转成合成授权。
- [x] (operations) 本轮原生和子Agent独立review均PASS，无finding，审前后指纹一致。
- [x] (operations) 8790c1b1固定提交完整CI7,002项/51批通过，2026-10-31候选目录外交付核验verified；后续提交另看PR当前检查及对应收据。
- [ ] (integration) 完整第3项生产冻结：真实用途/额度、全覆盖、所有绑定、legacy义务及成本/时钟实测。不能由本轮技术收口替代。

## 小范围来源准入与历史处置候选（2026-10-31）

- [x] (operations) 补齐8790c1b1目录外交付核验，验证同轮镜像、测试树和7,002项完整清单。
- [x] (integration) 对NAR199旧卡页进行禁网兼容性诊断，并一次读取官方条款；身份候选不转成用途/额度或runtime批准。
- [x] (operations) 刷新固定历史集合及19场追踪/合同状态，形成逐场处置候选；重现registry证据陈旧，未续签或调用TRA。
- [x] (operations) 独立子Agent/原生只读评审与文档检查均PASS，无finding；来源准入仍阻断，新head CI另验。
- [ ] (integration) 取得符合免费约束的来源用途/额度证明，再推进适配和绑定；本轮未完成来源准入或生产冻结。


## 第4项执行器实现（2026-10-31）

- [x] (operations) 独立P02执行器与精确catalog实现；身份、并发、writer、漂移、故障恢复和收尾失败测试先行。
- [x] (operations) 合成PG16双集群真实备份/恢复、六步DDL及故障续跑验证；见[验证边界](executor-validation.md)。
- [ ] (operations) 固定候选完整Compose与生产形状隔离副本演练，实测资源、停写时限和RTO；合成测试不能勾选本项。
- [ ] (operations) 当前head独立review与所需CI全部通过，形成可交付发布包。
