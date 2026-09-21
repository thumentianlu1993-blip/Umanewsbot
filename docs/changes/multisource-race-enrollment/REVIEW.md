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

## 用户追加的独立代码审核（2026-09-21）

全新只读 reviewer `independent_pr212_review` 对固定 `8f2bb9c55d99cec8304a97099d007017e14924fb` 初审，不沿用此前结论。自行运行的六个模块48项通过，但独立3个反例均失败，初审 **REVISE：1项P1、2项P2**。

| ID | 发现 | 修复与回归 |
| --- | --- | --- |
| IR1 / P1 | 赛卡的 `number:<马号>` 可将同号不同马名直接覆盖；赛果链已有校验但赛卡末端缺失 | 赛卡与赛果共用槽位身份校验，在锁内要求规范姓名一致或受审 event-local crosswalk；整批回滚并记待审核。末行换马/首行trainer变化整批回滚和受审crosswalk正例通过 |
| IR2 / P2 | 来源明确 corrected 的结果未生成 writer 要求的 correction_marker，更正无法发布 | 标记只从受审parser明确 corrected 语义产生；首次发布→更正revision→公开读通过，普通official内容变化不补猜更正 |
| IR3 / P2 | checkpoint首次为now、selector未约束结果开放窗口，T+3前会每5分钟领取并耗预算 | 分离首次开放下界与后续轮询间隔；登记、selector和失败重试共同约束。精确T+3和date-only当地比赛日边界验证通过 |

同一新 reviewer 复审 **APPROVED**：原3探针全部GREEN，六模块54项全部通过，无新增P0/P1/P2。审核的五个业务文件及JRA测试增量（相对8f2bb9c）SHA256为 `086045c75a1b9bcd1f823cbfa4888bc3fd6f39efb58a9f63ee1c15abfe483053`，主线程已重新计算一致。审核未连接真实provider/生产、未代替PG验证。

### CI 与历史合同单独复审

原 `plan_reviewer` 独立核实：run35554080816在8f2bb9c的5184项中为65 failures+32 errors=97；上次生产候选3a174b1e为5129项、45失败ID，当前新增52且修复0。工作流固定的a88bcbf6在本次环境实际有328个失败/错误，比较只报告12新增，掩盖另外40项；不能用它宣称无新增回归。

52项均定位至旧0078文件/迁移图或旧0074列集合保护遇0079：rollback harness36、catalog9、artifact/校验4、preflight3。维护历史测试的精确文件集合、真实M78私有schema和模拟git路径；新增当前0079必须被旧catalog/rollback拒绝的测试，生产guard未放宽。原测试断言未改成接受漂移。

CI改为本PR固定base.sha；手动运行要求完整baseline_sha；fetch/checkout及比较产物两端commit.txt均核对准确SHA。该 reviewer 对此增量 **APPROVED**，独立执行比较脚本6组合成正反例全部通过（包含新增失败、base/head漂移和非法SHA），未重新跑完整PG/rollback套件。主线程补跑结果见validation.json；新提交的Linux全量仍待运行，当前不标无新增失败或发布可用。

## 持续返修与完整业务终审（2026-09-21）

按用户要求，对544bbf0全业务范围再次独立终审，补出IR4/IR5两项P2，而非仅复核前三项增量：

| ID | 发现与修复 | 反例及边界 |
| --- | --- | --- |
| IR4 | 同事实指纹漏骑师、练马师、负重、档位，吞掉来源明确更正；补全公开结果字段 | 四字段逐项明确更正可发布，普通official变化保持待审。相同内容重放不重复发布 |
| IR5 | coverage已分类missing_timezone，告警再次无保护解析时区，使一场坏数据阻断整轮；日期缺失还会误resolve旧incident | 未知日期/时区保留原incident，合法赛事继续；明确赛果确认/取消可resolve。另防census后并发改坏时区 |
| IR4返修回归 | 初次补raw姓名造成跨语种合法fallback更正冲突；独立review拦下后继续修复 | 已验证runner映射后，普通跨来源忽略姓名语种差异；同源或明确corrected仍比较姓名。13匹英文马名/骑师/练马师来源接管仅保留1revision/1publication |

原两反例先RED（3测试2failures/3errors），修复后GREEN；reviewer另证实跨source明确corrected可产生公开revision2，随后相同内容仅补证据不重复发布。相同source/phase/payload复用原observation及primary evidence，不要求重复supporting行。

固定544bbf0的run35572737991已完成：准确base953ea626为5129项，candidate5192项；各16failures+29errors=45个相同历史失败ID，新增0、修复0。候选测试48m44s，发布合同通过。最终返修提交仍需独立SHA绑定CI，不能把544的全量结果当作新提交验收。

最终同一reviewer **APPROVED（整个PR已审业务范围）**：IR1–IR5及返修回归全部关闭，无未关闭的可复现P0/P1/P2。独立原探针6项与跨来源更正/重放探针通过，JRA+coverage36项分批复验通过。四文件相对544bbf0的diff SHA256为 `867a5c360210359a37ef3268a326de494d1284b6b19b6ba892ad52ef38409ced`，主线程重新计算一致；不代表未知风险为零或真实来源/生产验收。

### 最终固定业务提交CI

`ec5f7791bc2d54e4841f912449e6acbc470ba7ad` 的run35577038611全部完成：基线953ea626为5129项，候选5205项；各16failures+29errors，共同45个历史失败ID，新增0、修复0。候选多1项skip在专用49项发布合同中实际执行通过。主线程核对两端commit.txt、result.json和comparison.json一致，发布合同前后指纹一致、迁移无漂移。本地最终同步模块348项、PG16业务46项通过。收尾仅更新文档，代码验收仍精确绑定上述业务SHA。

原CI reviewer再次独立复核上述最终raw artifacts后 **APPROVED**：准确SHA、失败ID集合、49项零跳过发布合同与工作流结果一致；未重跑测试或访问生产。
