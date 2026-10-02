# 启用、恢复与交接

本轮只设计，不改 CI、不触发定时全量、不部署服务。人工确认只引用根 AGENTS.md。
前置 PR232 已上线；本方案不是该发布包中的追加生产动作。

## 后续实施顺序

1. 在最新 main 的独立分支/worktree 实施，固定代码和规则版本；不得影响仍运行的发布脚本或其他工作树。
2. 实现计划与小型测试，建立实际测试归属和高风险路径，先验证计划再执行少量相关批次。
3. 首个引导 PR 使用明确固定SHA的手动工作流，独立审核受信校验器、规则并集与门禁；
   协调者从独立审核锁定的对象提取交付核验器，在候选目录外执行并保存delivery receipt。
   后续直接用固定main/base版本，禁止用尚不存在的base工具或候选自报允许名单自证通过。
4. 旧策略只保留为可回退版本；shadow仅比较选集，不额外跑一套全量。完成一个明确固定SHA的 full profile 校准，
   再检查真实仓库规则/required checks，切换默认 PR gate。该次校准属于未来实施验证，不在本轮执行。
5. 启用顺序：先让新gate对docs/targeted/full/error都生成正确结论；检查传统branch protection与rulesets，
   在未来精确交付包内配置新gate的strict required checks及管理员约束，验证服务端拒绝陈旧base。
   协调者默认入口接入候选外delivery核验器后，才移除三份旧workflow的PR触发，精确归属见design第7节。
   若不能建立严格检查，保留诊断模式、不宣称自动交付就绪；不擅自提升权限或关闭保护。
   当前rules/branches/main只读返回[]，不是“保护已配置”的证据。
6. 按受审配置启用高风险、日周和手动 full。普通 PR 不再依赖 `[skip ci]` 规避成本。
   现有研究工作流的人工 `full_network` 入口、checkpoint和不取消在途真实任务的设置保持原语义。
7. 文档回写 current_state、decisions、codex_workflow、TDD skill 和 deploy_runbook；项目概览/里程碑无实质变化则不机械更新。

## 在途任务和异常

切换前记录仍在运行的旧CI及其SHA、计划/规则版本和PR，旧证据只能满足其原计划，不能冒充新策略。
同PR旧隔离测试可由concurrency取消；生产发布、备份、真实抓取不在取消范围。
base前移由交付工具返回STALE_BASE拦截；代理在自己的干净分支整合main并push触发新计划，
GitHub strict挡住核验后再次前移的竞态。没有新tree证据就不调用merge。

选择器不可用时 gate 保持失败，先修复映射/工具；确需继续验证则明确手动选择对应领域或 full，
产物仍绑定候选与受信计划。不能无声回退全量，也不能关闭门禁。缺测试/参数/环境时不猜成功。
需要恢复旧策略时通过受审Git变更回退CI及规则，记录恢复后“小改动可能再次全量”的成本；
这是 CI 配置恢复，不涉及数据库、容器或业务数据回滚。新旧检查名按相反顺序交接，保留已有验证证据。

## 交接必须带走的证据

base/head/test SHA/tree；规则/catalog/依赖/runner摘要；计划与选择理由；执行/跳过/失败全集；
CI run/attempt/job状态；原 reviewer 与 findings；是否启用 required checks/定时任务；已测/未测范围。
隔离本地、Linux CI 和生产验收分别报告；没有业务/数据库变更就不安排一次多余的生产重启。
