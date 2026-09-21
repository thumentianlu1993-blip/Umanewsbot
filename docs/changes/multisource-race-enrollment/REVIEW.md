# 独立工程审核

基线：`953ea62604cd97709310d1e78e16972dd38eba3f`；分支：`codex/multisource-race-enrollment`。

Reviewer：本任务独立只读 Agent `plan_reviewer`。边界：不修改文件、不访问生产或provider、不实现业务；主线程编写和返修方案。审核采用完整架构、身份、并发、测试、性能、来源与恢复检查，纯技术finding由主线程返修后交同一reviewer复审。

## 预审提示（已纳入v1）

- 复用已有一赛事多来源identity、event单enrollment/owner，不将ProductCanonicalLink当自动合并表。
- eligible route当前强制full data_kinds，discovery/dispatch仍硬编码TRA；必须同时改协议、claim与所有末端writer。
- 全roster摘要影响旧route，需冻结legacy resolver和新版本route-local digest。
- 跨来源并发需要数据库全局key唯一约束，不能只锁可能不存在的row；savepoint/重读及整组原子性。
- 日期未知的赛后结果、改期、source finality、旧公开结果不退化需明确测试。

## 正式审核

### 第 1 轮：REVISE

- F-001 / P1：首次绑定循环依赖已有source ID/key/受审series，104冷启动仍可能卡住。返修：design §3.1新增A0，从旧日历/候选/binding的原始证据和新鲜真实链接链生成seed receipt；伪造URL、错日期或证据不全保持待审，T01加入正反例，tasks/rollout列明seed范围。
- F-002 / P1：已登记来源合法但持续超时/403时无法让可用备用来源接管。返修：design §4定义两次transport失败或访问拒绝circuit后的有期限alternate授权、generation、成功receipt、恢复粘滞与去重；T11/T20加入用例。
- F-003 / P2：统一30分钟时效与date-only六小时轮询矛盾。返修：H4拆分实时与late admission目标，budget_deferred不移出分母，T14/T30/T32与rollout同步。

预审锁序、lifecycle缺行竞争、无赛时结果轮询、legacy摘要稳定及public_read历史证据边界已由reviewer确认纳入。

### 第 2 轮：APPROVED（方案阶段）

同一 reviewer 确认 F-001、F-002、F-003 全部关闭，无未关闭的 P0/P1/P2。复审覆盖 A0 首次证据绑定、备用请求授权与 generation、实时和补录时限，以及全地区范围、强身份去重、数据库并发约束、单 owner、赛后补入、旧登记兼容与前向恢复。

Reviewer 全程只读，未改文件、未访问生产或请求 provider。批准只代表方案具备可实施合同；业务实现、PostgreSQL 并发测试、逐地区来源 proof 与生产验收尚未完成。

## 审核定稿文件摘要

以下为第 2 轮通过后的文档快照；PLAN 的阶段文字已据实更新，技术合同未再修改。项目主文档仅同步阶段和链接。

| 文件 | SHA256 |
| --- | --- |

| PLAN.md | `2a24ee1340f79a74b8e9ccb5ecdf15eda05f927eea25876c92a9a108c43033da` |
| design.md | `229b01b7f3b4766c621070077e829aa8f7ccd3b1d38cd2ca3447a542816f0443` |
| sources.md | `205e4f0a533eb82745d3f8b5047af3d0cee4658db0429b1546c0788375063643` |
| test_cases.md | `f96eedc42f9137c5abb407e7d09e337b72afdfeabe3be2b7c1efb1110c3746b0` |
| tasks.md | `1a9bebd181dd87996d2397a224a043119e00bd06ff73127746b26ffd57b583a8` |
| rollout.md | `6ad15c5dfea29d57ff7577be82aa9165f247b72dddc02ed33d0f15a83dfc5f8f` |

## 实现阶段独立审查（2026-09-20）

复用同一只读 `plan_reviewer`，不参与源码修改。多轮REVISE已修复：生命周期开关准入、未选来源checkpoint饥饿、20场共享批次上限、基于完整HTML的错误名单完整性、显式来源撤销、取消/延期覆盖、同号换马、锁等待越过授权截止、转换独立verify漏报、运行代码SHA自报及TRA host预算初始化。核心范围最终APPROVED；转换/adapter权限补充范围最终APPROVED。

Reviewer独立SQLite探针及保存回归通过；其结论明确不代表七地区实网proof或生产验收。主线程另外完成独立PG16并发与事务测试，结果见validation.json。上述文档快照SHA保留为方案阶段历史，不宣称与本轮更新文档一致。

历史0078测试夹具追加复审：初审发现递归排除同名0079文件会隐藏未知嵌套迁移（P2），已改为仅根目录精确排除。nested和__pycache__中的同名.py经复制后保留并拒绝；reviewer独立4项合同测试通过，最终APPROVED。生产guard/固定SHA未改，当前0079代码仍拒绝旧0078发布准入。

历史迁移图隔离补充复审：动态模块无法被Django reload的问题已修复为真实唯一临时包，清理后恢复0079图；reviewer独立5项合同测试通过，核对6项真实PG日志，最终APPROVED。生产文件与迁移图校验保持拒绝0079。
