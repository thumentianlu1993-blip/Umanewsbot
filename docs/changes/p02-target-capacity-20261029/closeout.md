# 第3项收口：历史义务、目标证据与容量准入

本轮按历史义务→逐场身份/覆盖→容量准入的顺序推进。基线为`db8a584a`，沿用独立worktree和分支；未授权合并、部署或生产数据修复。人工确认仅引用根[AGENTS.md](../../../AGENTS.md)。

## 范围与证据边界

- 用只读可重复读事务交叉检查旧赛果、修订/发布、纳管与控制记录，不以`result_confirmed_at`为空直接激活历史轮询。
- 核对既有年度目标与canonical，以明确关联或来源日期/名称/场地复核形成候选；未建canonical的目标也保留。不生成或写入生产来源身份。
- 只使用免费匿名公开页面及已保存的官方资料；拒绝登录、付费墙和访问限制。页面可读与source ID存在不等于自动用途许可、完整性或运行时证明。
- 新的容量合同保持full-fetch，按重点60秒/常规120秒发现及每小时6次完整复查计算保守峰值；不修改业务SLA、实际轮询频率或启用范围。

## 容量合同修正

旧清单没有证明完整库存、逐场来源绑定、额外请求和共享host负载，不能仅凭`runtime_verified=true`准入。新合同在原targets/proofs/budgets上要求：

- `inventory`：`verified=true`、非空`evidence_refs`、与targets完全一致的`target_keys`，以及逐host显式`other_requests_per_hour`（其他消费者的峰值，零也必须证明）。未确认/七天观察/缺源/待匹配均不能从证据分母中隐藏。
- 每份proof显式绑定`target_keys`；五类能力及identity、自动用途、请求成本和额度均须有证明。新增`schedule`、`withdrawal`、`automated_use_permitted`、`request_costs_verified`、`quota_verified`必须为true；`cost_evidence_refs/use_evidence_refs/quota_evidence_refs`非空。
- `requests_per_fetch`计入同host全部同时有效模块、名单/赛果配对和分页，不得仅记入口页；`extra_requests_per_hour`显式计入该目标的寻址和失败重试峰值。共享开销可保守重复计数，不凭设想去重。
- 每host基数为各目标及每个可切换来源的`requests_per_fetch × (60或30 + 6) + extra_requests_per_hour`之和，再加`other_requests_per_hour`；总额除以0.70并向上取整。统一+6是保守上界，涵盖首日未确认6次、确认首日4次及后续日复查集中小时；不会缩短实际复查间隔。
- 来源绑定检查必须使用同一份合格proof并确认整个清单ready；另一个provider或目标的成功不能给当前来源放行。旧格式缺字段保持拒绝，不自动填0或补true。

## 验证计划

先取得真实RED：三请求重点链275额度拒绝、283额度接受；同host多目标/多来源与额外请求、缺库存/成本/用途/额度证据、目标绑定错误及不完整proof均拒绝。随后GREEN、隔离PostgreSQL回归与原生/子Agent独立评审。合成额度和身份只用于离线测试，不填入真实候选证据。

逐项核验结果与未闭合项目将在本文件追加；未证明的能力继续阻断上线。

## 本轮收口结果

- [历史义务核验](obligations.md)：10,134场空标记拆成9,995旧赛果无纳管、119无赛果无纳管、19在管未完成、1临时发布不一致。2场七天候选以最早official修订及publication交叉证明起点；旧Control缺新增字段如实记录。没有批量修复。
- [逐场身份与覆盖](identity-coverage.md)：79场canonical之外追加两个既有未匹配英国目标；25场缺规范等级的原始官方日历证据已核对，候选重点依据29场、非重点52场。生产规范字段未回写。119/199取得来源身份候选；其余仍缺可执行绑定。没有把日历索引或内部ID当provider ID。
- 已知工作候选103条=未来81+在管未完成19+七天候选2+临时发布不一致1；另10,114条legacy义务UNKNOWN不从完整库存证明中删除。真实诊断输入没有proof或额度、inventory.verified=false，实际命令输出targets=103/ready=0/gaps=103，符合预期阻断。
- 容量合同RED：旧公式192而非198、无inventory仍ready、跨provider借用不完整proof、其他目标阻断时当前来源仍放行，均实际失败；缺规范等级仍使用120秒预算也取得独立RED。实现后78项容量、JRA多来源和九地区producer隔离PG回归通过，failure/error/skip=0（同一批，不与早期35/41重复相加）。
- 新合同要求显式完整库存与逐场来源/用途/额度/请求成本证据，不自动兼容缺字段的旧manifest。命令和网络准入共用检查；缺规范等级需60秒保守预算，保守预算不补造等级或解除其他证据阻断。
- 本地影响计划要求full；本地78项不替代最终固定提交CI。当前无生产有效期、没有新增网络自动化、没有schema/配置/服务变更。

## 仍阻断及下一项

本轮完成可核查的历史分类、逐场证据补充和容量准入技术收紧，**完整第3项生产冻结仍未通过**。所有地区自动用途/真实额度、完整目标目录、可执行来源绑定、legacy义务解除/保留的权威依据，以及实际请求链/时钟/全库存峰值证明仍需补齐。两个身份候选不是全部地区producer已接入；浏览可见不代替本机受审网络路径。

下一项优先完成首个小范围地区的逐场可执行来源与用途/额度证据，并对19场已纳管失败与legacy集合形成只读处置候选；生产修复另按根规则绑定具体包。源码可并行准备P02受保护执行器及隔离恢复演练，但不能将它当作绕过来源/覆盖阻断的发布理由。

## 固定诊断产物

- `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/blocked-capacity-input.json`，SHA256 `861ee6eb2eae3801cf1f0f9d38e886c6cac3cad6576e957386630da7cf0c3bdb`。
- `/Users/mentianlu/.codex/artifacts/p02-capacity-20261029/blocked-capacity-report.json`，SHA256 `5cb8c47b0e83d07ca4cdb5814e0bfc9bfa2a65c9b8f8d87ea2db3fc4e2e87c87`。
