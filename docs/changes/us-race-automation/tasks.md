# 执行任务

- [x] (integration) 核对来源证据和现有route/observation边界。
- [x] (integration) 编制五份方案文件。
- [x] (integration) 方案审核：同一reviewer修正两条finding后APPROVED。
- [x] (integration) U03/U04/U12 RED → Del Mar发现/卡解析 → GREEN。
- [x] (integration) U01/U02/U05—U08逐行为RED → TOBA/NSA/PDF/changes → GREEN。
- [x] (integration) U09—U11 RED → bounded collector/缓存/命令 → GREEN。
- [x] (operations) 274项Linux固定树范围回归、零跳过；独立只读review全部finding关闭，工作流检查通过。
- [x] (integration) 原件回放和有界网络验收，输出覆盖与缺口。
- [x] (operations) 回写状态与准备Draft交付；提交、推送及PR链接以实际Git记录为准。

## 美国整体剩余链路

- [x] (integration) 本次1/2/5：全窗口只读清单、已赛最终名单、当前公开赛前资料、NSA完整结果和冲突对账；未来阶段保留等待。
- [x] (application) 来源接入既有候选/生命周期/公开字段并完成TDD；生产启用仍待交付。
- [ ] (operations) 精确发布包、生产及自然调度验收，按根AGENTS.md。

## 2026-11-12 线上回归及3/4/6

- [x] (operations) 只读生产142条关联记录及107个公开详情回归，记录具体缺口。
- [x] (application) 展示字段与分场行为真实RED→GREEN，字段语义及Glen Cove独立页面已实现。
- [x] (integration) 全年赛场/自动补表/单场observation与阶段候选RED→GREEN；Gallant Bob实时站点故障单列。
- [x] (integration) 5/10分钟、7天更正、日期/时区和失败重试隔离测试及实现；生产自然调度仍待发布后验收。
- [x] (operations) 精确US数据manifest、恢复和全范围隔离重放；独立代码及发布文档review通过。
- [x] (operations) 原PR #299精确提交940项范围CI与交付收据。
- [ ] (operations) 原包已获准但数据事务回滚；修复历史检查点后重新绑定交付，完成生产写入、自然调度和公共页验收。

## 2026-11-12 发布中发现的历史来源检查点

- [x] (integration) 复现历史检查点误拒绝及dry-run漏检，完成真实RED。
- [x] (integration) 仅保留有同赛事来源摘要证据的历史检查点，未知记录继续拒绝；本机57项与最终候选PostgreSQL58项通过。
- [x] (integration) 全部109条真实控制记录隔离dry-run、写入、重复执行和精确事务恢复；30条旧检查点及公开投影不变。
- [x] (integration) 复审发现的replay漏检及stdout丢失恢复窗口已真实RED→GREEN；PostgreSQL锁等待测试通过。
- [ ] (operations) 独立复审、增量范围CI、修订精确包与真实上线验收。
