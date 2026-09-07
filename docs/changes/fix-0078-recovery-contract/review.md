# 0078 方案与实现审核记录

本文件记录实施前r2方案的审核。用户随后授权实现，五份文档已进入实施记录阶段；
下述输入指纹和“字节一致”说明仅描述审核结束当时的r2快照，不覆盖后续实现修改。
实现审核如下，独立测试结果见 `validation.md`，不由方案结论替代。

## 实现审核

原生只读 `codex review` 审核首轮实现 `e79fe4ba1c1a8e1bb424bcb4e3f37ed0094e11f0`，
在同一 session `01a07b1d-7de0-7d10-a1a2-505f62a51bc2` 复审返修提交
`3c051364c692ff1cd1a68e4b51d8797a7ddae0f7`。审核基线为下文固定 main，
返修 tree 为 `4f9aef28982c8bc278c6d1beab5a93a0f586b93a`，审核前后工作树 clean。

| Finding | 修复与复审结果 |
| --- | --- |
| P1：已有 schema receipt 的恢复路径只检查 `.env`，调用环境可改变实际业务开关 | `prepare`、`finish` 与 host one-shot verify 比较实际 Compose project/flags；复审确认解决 |
| P2：旧测试仍要求 complete 早于 collectstatic，与新完成边界冲突 | 正常路径改为 migrate→collectstatic→complete，两个失败路径均要求不 complete；复审确认解决 |

第二轮结论：原 P1/P2 均解决，直接回归路径无新的 actionable findings。
reviewer 独立执行了 80 个配置检查场景、6 个 shell 成败场景及原排序断言，均通过。
shell 使用命令替身；该结论不等于真实 PG16 接缝或完整 stable 已通过。
原生报告保存在本地 `runtime/review_evidence/fix-0078-recovery-contract/code-review-r2.txt`。
后续测试/CI 差量经第三、四轮审核，记录如下；完整验证状态以 `validation.md` 为准。

第三轮固定 `2e11e7efe35efd86abcfe7db5d0b58e41139dfcb`，仅审 3c051364 之后的
测试、CI 与文档差量，发现两项 P2：

- “容器不存在”的夹具同时删除 Compose 服务定义，导致配置核验先遇到 KeyError。
- pre-0070 拒绝用例的 artifact 签名不正确，尚未到达 source leaf 门禁就被拒绝。

这两处分别修成配置服务与容器状态分离、正确签名的真实顶层入口测试并断言精确拒绝原因。
另修正 wrapper 夹具 acquire 时显式传 `DEPLOYMENT_LOCK_ACTION=deploy`。
第四轮在同一 session 固定 `17089d36d19ca293590b22293c94339471225c1d`、tree
`de8d1de21c2fce0ccbfa8a55757babeb70662b81`，确认两项 P2 均解决，三处改动的直接
回归无新增 actionable findings；5 个不落盘的定向场景通过，审核前后 HEAD/tree/clean 不变。
本地报告为同目录 `code-review-r3.txt`、`code-review-r4.txt`。

完整 CI 随后暴露的三个测试差量再由第五轮审核：conflicting attempt mode 精确验证
prepare 前拒绝；manual 的 fake preflight 使用独立 DB 事实；leaf/OID 精确列表补入 0078。
第五轮固定 `966e3455afc66a1476a8dc8e020ee81592237bbb`、tree
`6928c2a6fa2cb0c54348c75a1a9b9a5cdafe9ece`，6 个不落盘定向场景通过，无新增 finding，
审核前后 HEAD/tree/clean 不变，报告为 `code-review-r5.txt`。

因此生产实现与最终测试代码均已完成独立审核闭环。该结论不预判完整 stable CI，
也不代替生产镜像、队列或连接切换验收；最终结果只在 `validation.md` 中按实际证据回写。

Windows 原 fingerprint 脚本因缺少 `O_NOFOLLOW` 拒绝执行，未修改该检查。
本地以不可变 Git OID/tree 与审核前后 clean 状态绑定输入，Linux CI 另执行原脚本并保存前后指纹。

以下各节保留实施前方案审核的历史记录，其输入指纹不代表上述实现。

## 1. 审核对象与证据边界

- 日期：2026-09-07。
- 代码基线：main@a88bcbf669bd609e30f97c8a07f009881d2da705。
- 输入：spec.md、design.md、test_cases.md、tasks.md、rollout.md。
- 审核方式：作者之外的只读 reviewer；首次会话 review_0078_plan，连续复审保留同一上下文。
- 规则：[仓库 plan-eng-review skill](https://github.com/thumentianlu1993-blip/Umanewsbot/blob/a88bcbf669bd609e30f97c8a07f009881d2da705/.codex/skills/plan-eng-review/SKILL.md)。
- 本地固定源码 41 份均已与 GitHub tree 的 Git blob SHA-1 核对；清单保存在 runtime/review_sources/0078-a88bcbf6/SOURCE_MANIFEST.json。
- 本轮未执行应用测试、迁移、备份恢复或生产命令；未修改实现代码。下述审核不能替代实现后的测试与代码审核。

## 2. 首轮 r1

结论：VERDICT: REVISE。发现两项 high，以下为 reviewer finding 摘要。

### F1 [high] 同版本 0078 发布缺少实际备份检查路径

- 证据：r1 design.md:54、58、73；r1 test_cases.md:40。基线 run_application_release.sh 的备份分支只覆盖跨越 0077 的 admission-only 路径，deploy.sh、deploy_lowcost.sh、manual_release.sh 没有方案假定的通用备份检查。
- 问题：同版本 0078 发布没有必需的 manifest producer/consumer，发布意图中的备份绑定仍可缺失。
- 影响：可能已停服或执行 static，却没有与本次 DB、候选和原始发布意图绑定的恢复点。
- 修正要求：明确新备份的真实生产者、source=target=0078 的字段、全部入口及恢复消费者；拒绝缺失、替换、错源、错 DB/candidate 和其他 release 的证明，并在首个 stop/写动作前验证。

### F2 [high] 首次 stop 与恢复意图落盘之间存在不可续跑的空档

- 证据：r1 design.md:58–63、74；r1 rollout.md:54；r1 test_cases.md:29。实际 resume_migration_history_repair.sh 原入口要求已存在 DDL marker。
- 问题：部分服务已停止，但 closed handoff 或 DDL marker 尚未生成时，原恢复入口没有可接受的依据；schema completion 后服务尚未恢复也未定义完整收尾。
- 影响：关闭窗口中的正常异常可能被迫新建 deploy、手工修改 marker 或丢失原服务恢复意图。
- 修正要求：首次 stop 前持久化只授权继续关闭与复验的 prepared 意图；真实恢复入口覆盖各断点，同候选/备份/原始 provenance 在新锁下续跑；增加逐断点故障注入。

## 3. 作者 r2 修正

| Finding | 方案修正 | 对应验收 |
| --- | --- | --- |
| F1 | design 第 4 节加入 upgrade/same-schema 的实际备份 producer、强制 manifest 字段及标准/低成本/manual/one-shot/resume 消费者；每个新 release 生成新备份，同一 release 重试复用原证明 | T12–T16、T28；首个 stop 或 release-task 写动作前拒绝无效证明 |
| F2 | design 第 4–5 节加入停服前不可变发布意图和 active pointer；prepared 不授权 DDL；实际 resume 入口先于旧 marker 检查路由，区分 schema 完成与服务恢复完成 | T35–T42；真实 shell 入口逐断点重放、原服务意图不被覆盖、无提前 writer |

五份方案同步修订。r2 精确输入指纹保存在 runtime/review_evidence/fix-0078-recovery-contract/inputs-r2.json。

## 4. 复审结果

结论：VERDICT: APPROVED。同一 reviewer 确认“未发现阻断或需修正的问题”；仅复核原 F1/F2、对应修正及直接相关路径。

- F1 已解决：design.md 第 44–56 行明确两种操作的实际 producer、必需绑定和全部消费入口；T28 覆盖主要无效证明。
- F2 已解决：design.md 第 60–98 行定义首次 stop 前 prepared 意图、DDL 授权、schema 完成和服务恢复的阶段边界，并明确无 intent 时的 prepare 续跑；T35–T42 通过真实入口验证失败断点。
- 普通 rollback 禁用、旧 0077 artifact 不自动升级、单一 migration owner 边界保留。
- Reviewer 核对五份 r2 输入的 SHA-256 和字节数，均与 inputs-r2.json 一致。

审核后的记录性改动仅将 tasks.md 第 0 节两项“审核完成/结论保存”勾选，并新增本审核结果。其余四份方案与受审 r2 字节一致；tasks 的实施范围和未完成事项不变。最终交付指纹见同目录 input_fingerprints.json，保留受审 r2 与最终交付两组值。

剩余条件：完整 checkout、Linux/PG16 测试、真实隔离备份恢复、实现后的独立代码审核、生产实时核验均未执行。方案通过不等于代码通过，也不等于生产验收完成。

## 5. 作者文档检查

- 五份输入存在，标题、代码围栏与冲突标记检查通过。
- 测试矩阵包含唯一且连续的 T01–T42，验收标准 AC-01–AC-09。
- 实现、测试执行和生产任务均未勾选完成。
- 当前 Git clone 未成功，无可用 checkout/HEAD；实现前需完整仓库、独立分支/worktree 与隔离 Linux/PostgreSQL 16 环境。

文档结构检查通过不代表应用行为已验证。后续先实施和验证，再按仓库既有交付规则准备精确发布包。

VERDICT: APPROVED
