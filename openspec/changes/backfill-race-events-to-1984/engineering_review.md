# 工程方案审查

## 审查结论

- Change：`backfill-race-events-to-1984`
- Review mode：Full
- Profile：`feature`
- 收敛轮次：2
- 最终结论：**APPROVED**

本结论只批准进入“编写完整测试用例”阶段，不代表允许实现、上线、触网或生产写入。后续必须继续遵循：测试用例 -> `/opsx:apply` -> 代码 review/修复/复审直至无可修复问题 -> 上线与抓取。

## 第一轮发现与返修

1. 年度总账把客观举办事实和处理状态混在单一 disposition 中，容易产生 `not_held + imported` 等非法组合。
   - 已拆分 `expectation_status` 与 `resolution_status`，并要求模型和共享状态转换服务双重校验。
2. 逐年 graded/pattern 目录只能发现分级年份，无法满足“升格前和降级后的完整系列史”。
   - 已增加 lineage/timeline discovery 阶段和标准 timeline artifact。
3. 现有赛果/历史冠军唯一约束无法可靠表达并列冠军。
   - 已设计 `official_finish_position` 数据迁移，并放宽历史补位唯一约束到马匹维度。
4. 生产网络没有全局关闭门禁，source cache 也没有磁盘预算。
   - 已增加默认关闭的功能/网络开关、共享请求预算、缓存字节上限、最小磁盘和 cache 保留要求。
5. “停办系列也必须抽近年”在逻辑上不可满足。
   - 已改为每地区 3 系列、约 9 个真实 held/cancelled 目标，地区整体覆盖三年代；停办系列在真实范围取样。
6. 赛事 slug 和地区同步护栏不够确定。
   - 已锁定稳定地区前缀 slug、创建后 URL 不随名称变化；全量默认每地区 50 目标，领先限制按 100 个标准目标计算。
7. 百万级 runner/result 若重复保存整页原件会导致数据库和备份膨胀。
   - 已限定数据库只保存结构化事实与有限 provenance，HTML/PDF 留在受控 cache，并增加容量预估门禁。
8. 缺少 TDD 可量化阈值与关键操作日志要求。
   - 已新增 `Pre-declared hypotheses`，覆盖 50,000 目标内存/耗时、后台查询、首批选择、网络预算和原子回滚；commit、mapping、永久缺档、publication 和网络 run 均要求操作日志。

## 第二轮复审

- 架构：保持 Django 单体、管理命令/服务/adapter 分层，不引入新服务或前端构建系统。
- 模型与迁移：新增表均可空部署；`RaceEvent.race_series` 和 official finish position 为 nullable 兼容迁移；唯一约束调整是放宽历史冠军并增加稳定系列年度约束。
- 状态与事务：总账状态维度分离；artifact commit、详情 apply 和 publication scope 有明确事务与回滚边界。
- 网络与生产：默认关闭、审批绑定、请求/缓存/磁盘预算、备份和写后核验完整。
- 性能：流式 artifact、分页、索引、标准批次、source payload 边界和 sitemap 分片均有实现与验证任务。
- 权限与审计：后台只读汇总保持 staff 权限，不能绕过 artifact；关键状态进入操作/任务日志。
- 测试：82 项任务格式合法且无重复编号；所有 requirement 均有模型、服务、adapter、页面、测试和生产验收任务。
- 文档：proposal、design、4 份 delta spec、tasks 均通过 `openspec validate --strict`，`git diff --check` 通过。

第二轮未发现剩余可修复问题。来源是否真实覆盖到 1984 年属于 adapter spike 和生产证据任务，不以计划中的推测结论替代。
