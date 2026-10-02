# 实施与激活状态

截至当前：实现及独立返修已完成，PR #233 保持Draft；固定代码版本有界验证和独立复审通过。**未合并、未激活策略、未配置保护、未执行full校准。**
首次Linux工具链run [36996581104](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/36996581104)：
222项分成29/193两批，221通过、1个UTF-8环境问题失败；未过滤失败，门禁失败。修复为`initdb --encoding=UTF8`后另跑固定版本。
选测RED为12项中的11个断言失败；Git权限/index两项真实RED；空分片伪证据一项真实RED；对应小型GREEN已通过。
完整catalog只收集名称和分片，不等于全量执行。10个真实历史单文件diff回放见[产物](diff_replay.json)。

激活使用仓库变量`IMPACT_TEST_POLICY=active`；当前未设置。inactive的业务PR gate拒绝通过，docs-only仍可静态验证。
因此本PR不能在未完成切换前草率合并，否则旧PR入口已移除而业务PR会被阻断。
后续按根`AGENTS.md`交付；本次不操作生产数据库、应用容器、服务、队列或开关。

# 启用、恢复与交接

本轮已实现 CI 和选测工具，在分支进行有界验证；未启用定时全量、未部署服务。人工确认只引用根 AGENTS.md。
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

## 第二轮固定版本验证与整轮审查

`209ba770cd612b1e1a4135a02f33f36c05c1942e` 的 [CI36997377841](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/36997377841)
通过258项（60项Django/198项Python，约21.2秒/5.0秒），零失败/错误/skip。
Python子进程、curl外网均阻断，独立Docker容器不可用；只收集6143个canonical ID、34批、最大200，没有执行全量。

独立整轮review对0e6ac960..209ba770给出REVISE，前后指纹一致。
9项finding：模式伪装、容器Git初始状态、已知环境skip、下游漏选、共享夹具、映射演进、文档合同退化、manual引导、同SHA补合同。
正在统一返修，新增真实Git演进和候选外CLI端到端测试；下一固定版本复审前不得宣称最终通过。
10项环境skip逐项设2026-10-16复核期限；它们仍是覆盖缺口，不算执行通过。源码存在的Compose配置检查改为仅提供无daemon的CLI。

只读查询：rules/branches/main返回[]，传统branches/main/protection返回404 Branch not protected，IMPACT_TEST_POLICY未设置。
尚未做G2配置或合并。actionlint1.7.12对四份新增/重写工作流通过；研究手动工作流的空choice既有告警在base也复现，13项原有结构合同通过，未改变该输入语义。

## 第三轮固定版本与最终边界返修

`d6a6b8dad2a5622d8e3de0756de077c90bb50c4d` 的 [CI36999240204](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/36999240204)
通过277项（65/195/17三批），零失败/错误/skip；总run约2分19秒，不等于P95。
目录仅收集6157个canonical ID、34批、最大200。声明skip9项，另有1项运行时环境skip登记；没有执行这些全量测试。
三批均证明Python/curl外网阻断、Docker daemon不可用，包含Compose配置、迁移漂移及Linux符号链接合同。

整轮独立review对该版本提出4项：暂存删除漏记、删除重导出误删canonical测试、精细标签改名失效、直接合同遗漏。
已新增5个真实失败回归后修复，本地47项通过；旧精细标签扩大为现存模块覆盖并记录superseded_test_labels，
候选外交付核验同步重算删除及替换审计。补齐历史恢复阶段权限与collector身份/断点/完整性合同。
下一固定版本仍只做有界验证，最终复审结果待回写。

## 最终代码验收（策略尚未启用）

受验代码 `4949317ff47cf0fcfd443cb6e86bdaef92eea667`，测试tree `8473f83aac2ecd18a7adc46af34afdedbb557ce2`。
[CI37000293909](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37000293909) **SUCCESS：296项，65/197/34三批，零失败/错误/skip**。
全run约2分21秒；批内执行约17.5/5.1/0.8秒，非P95。完整目录仅收集6162个canonical ID、34批、最大200，未全量执行。
镜像`sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc`；各批独立PG/无网络隔离检查通过。

原reviewer对最终返修差异及直接回归给出 **APPROVE**，4项全部关闭；独立47项小测试通过，原生review无finding。
详见[审核记录](review.md)与[机器可读验证摘要](validation.json)。随后只回写文档，不改变已受验代码；后续交付仍须绑定最终候选tree，不能复用旧tree冒充新head验证。

剩余运行验证：首次固定SHA full校准、实际非文档候选外delivery核验、strict required checks/admin约束、shadow后策略激活。
本轮遵守不执行全量要求，以上均未进行。当前Draft不可在inactive状态直接合并，以免移除旧入口后阻断业务PR。
没有生产迁移、配置、数据动作、服务重启或外部消息发送；后续精确交付包仍按根AGENTS.md处理。
