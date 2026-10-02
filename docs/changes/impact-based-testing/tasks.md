# 任务与状态

当前仅方案，所有实现项均未开始；不把勾选计划审核等同于 CI 已启用。

## 测试先行

- [ ] (operations) 固定真实 diff 回放样本、catalog 归属、核心冒烟 ID、高风险/未知路径预期。
- [ ] (operations) 为计划选择、Git 边界、规则降级、分片完整性、skip/收尾失败编写小型 RED 测试。
- [ ] (integration) 为跨领域依赖、子进程网络/配置隔离及 PostgreSQL profile 编写 RED 测试。

## 实现（待用户审阅后另行推进）

- [ ] (operations) 建立受审规则/catalog，覆盖文档、模板、独立服务和共享高风险路径；未知路径显式阻断。
- [ ] (operations) 实现固定 Git 输入、合并树与本地未提交内容的计划生成；复用已有 runner 核心且兼容50项旧入口。
- [ ] (integration) 实现network none的非root PG/测试镜像、子进程/容器拒绝验证、按类≤200分批及最多4并发。
- [ ] (operations) 实现候选目录外的交付核验器、workflow/审核身份核验、STALE_BASE和strict配合；保留引导证据。
- [ ] (operations) 实现真实状态聚合和简短日志，三份旧工作流按唯一归属迁移且保留研究手动依赖链。
- [ ] (operations) 接入统一 PR gate，移除默认双全量；迁移现有离线合同，保留手动真实网络流程。
- [ ] (operations) 实现高风险/手动/日周 full profile、失败处理和跨 run 身份核验。
- [ ] (operations) 修改 TDD skill/codex_workflow 的停止规则；更新 deploy_runbook 中“补合同不补全量”的用法。

## 验证与交付

- [ ] (operations) 同一计划下完成最小GREEN、相关分批、workflow表达式和全量目录完整性验证。
- [ ] (operations) 独立 code review、原 reviewer 返修复审，保存指纹和有限范围验证证据。
- [ ] (operations) 完成后续专门安排的一套 full profile 首次校准，明确范围、失败及跳过，不伪报通过。
- [ ] (operations) 只比较计划的shadow验收后，在既有门禁下切换 CI；检查真实仓库 branch rules 与新gate接入。
- [ ] (operations) 用10个代表性小改动验证范围、token日志长度和实际耗时；更新当前状态/决策/操作说明。

纯CI/测试治理无应用实现或生产迁移任务；不为满足角色格式添加无实际工作的(application)条目。
