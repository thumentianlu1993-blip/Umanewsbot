# 后续工作路线图与 Agent 交接

> - 状态日期：2026-09-10（下文旧日期快照按历史解释）
> - 当前主线：`f62a6edadbe6173c6a5b3ec58ad957916588a15f`；生产候选：`69955960`
> - 文档用途：后续工作的统一入口、跨 Agent 交接清单与优先级依据
> - 重要说明：本文记录的是截至状态日期的可核验证据和执行建议，不替代实时生产核查

## 0. 当前持续收口清单（2026-09-10）

用户已确认：本轮只收口 M2、测试基线和运维遗留，M3–M6 暂不实施。
本文以下带旧日期的清单保留历史依据；当前执行顺序和状态以本节与 `current_state.md` 最新记录为准。
执行沿用仓库原生流程，每项先形成明确问题、最小修改及可验证完成标准；审核或外部等待不阻塞其他独立事项。
人工门禁只引用根 [AGENTS.md](../AGENTS.md)，本清单不增加确认层级或扩大既有授权。

| 事项 | 当前状态 | 本轮完成标准 / 下一步 |
| --- | --- | --- |
| M2 新赛事自然闭环 | 962/963 已有身份、enrollment 和赛卡，正式赛果待赛后验证；由独立只读任务跟进 | 至少一场自然完成发现→身份/纳管→赛时/赛卡→状态→正式赛果/公开；再证明一轮成功取回相同赛果的 correction 幂等。真实变化分支按原决定用隔离 fixture 验证，不制造生产更正 |
| M2 当地赛时显示（当前优先） | #194 `51a46c37` 修复来源未单列 local_start_time 时误拒绝推导值；5 项新回归和独立审核通过，Linux/PG16 CI 运行中；生产未变 | 完成候选 CI 和精确交付审核；发布后观察自然同步补齐 962/963，并核验双域名当地时间 15:00/15:35。不手工回填或触发同步 |
| 490/766 发现未匹配归因 | 独立观察已补存截至 9 月 10 日 01:40 UTC 的自然诊断：490 为 response_empty；766 随窗口出现 course_not_found / local_date_not_found | 核对来源日期/场地证据，区分外部缺数和实现缺陷；分桶结果不等于根因已解决，不放宽身份规则、不额外调用来源 |
| stable 测试基线 | 生产仍为 274 个唯一失败；#193 `9ebdf657` 的 #186–191 组合 CI 已核验，实际消除 163 个、剩余 111 个、无新增。独立 #192 当前 `de5fb540` 剩余 235 个，38 个发布相关失败消失，另 1 个未改动性能用例本轮通过；相关模块及三项新增 PG 回归通过 | 继续处理其他旧合同/夹具簇，后续整合须重新核验实际组合；#193 不含 #192/#194，不能将独立修复数相加。禁止删测试、降低断言或批量 expectedFailure 掩盖 |
| 历史测试工具源码恢复 | 9 条既有失败引用 `tmp/run_known_calendar_shards.py` 与 `tmp/run_current_year_source_override.py`；本机定向文件搜索、本地全部 refs 的路径历史及 GitHub 默认分支路径历史均未找到源码 | 保留原测试与诊断；需要可验证的原 PC/备份或远端来源，不能凭测试临时伪造 helper 或删测试。当前检索不证明其他远端分支或原 PC 无源码 |
| 文档合同与状态漂移 | Draft PR #186 修复 5 个文件的旧流程引用；原检查器及 4 项合同测试、文档增补独立复审通过，最终版本随 PR 记录 | 更新当前状态和历史边界，保持原校验规则；交付时上传最新证据。新闻恢复、0078、956 和 PR #184 的已完成事实有明确证据 |
| 审核工具和本机可复现性 | #187–193 当前已核验候选的 Linux CI 提供一致的正式前后指纹；Windows 缺少 O_NOFOLLOW/部分 dir_fd 支持，补充快照不冒充正式通过。当前原生 CLI 已完成 #194 只读审核 | #194 等新候选仍需自身 Linux/PG16 CI；保存正式指纹及文件身份、符号链接和读写边界检查。原生进程中断须先核实终止，再恢复原审核上下文 |
| 历史 PR / worktree 交接 | 7 个历史 open PR 的只读分类见 §0.1；原 PC 两个 candidate-only 目录尚未证明可在本机获取 | 按分类保留历史证据及待判断项，继续核对旧目录是否有可恢复的远端提交；不把大分支整包合入，不批量关 PR 或删目录 |

已完成并移出执行队列：M1 主链实现与启用、755/756/757 恢复、0078 发布恢复合同、956 公开恢复、PR #184 镜像版本标记及有界发现诊断、PR #185 交接上传。
新闻主链已于 9 月 8 日充值后自然恢复；历史失败稿件明确不处理。少量术语占位符问题仅保留已知边界，本轮不开展模型/翻译改造。
保持隔离的 `race_live=7543`、现行普通代码 rollback 禁用和人工锁不是待“清零”的错误；不得为完成清单而改变它们。

完成一项后在本节更新实际状态、PR 和证据；需要用户核心判断或精确交付审核时提交具体候选包。
本轮整体完成须有 M2 验收证据、测试问题的可核对处理结果、运维遗留处置及主线文档回写；等待外部条件或待审核项不冒充完成。

### 0.1 历史 PR 只读分类（2026-09-09）

已读取各 PR 的当前 head、说明及完整文件列表，并与主线 `f62a6eda` 文件内容核对。
这是上述交接事项的证据展开，不代表这些 PR 已关闭或其未完成能力已实现。

| PR | 已核对事实 | 处置建议 |
| --- | --- | --- |
| [#87](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/87) | head `75b14d07`，仅 3 份历史 PR #86 发布记录；主线文件已演进，不能整页当作现状覆盖 | 保留旧版本/备份证据，后续只补主线缺失的历史事实，不重复发布 |
| [#85](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/85) | head `7e4a4726`，仅 5 份 0072 发布文档；当前 `current_state.md` 已有 0072 完成记录，当前数据库世代为 0078 | 保留历史证据；不将旧迁移记录解释为当前待执行迁移 |
| [#59](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/59) | head `19f89a41`，18 文件包含启发式赛事关联、批量导入、页面及 Nginx/Compose；其新增导入/匹配模块在当前主线不存在 | 涉及身份规则和产品扩展，留待未来核心范围判断；本轮不实施 |
| [#49](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/49) | head `35daa7ae`，15 文件研究原型；旧 `graded_participants` 包不在主线，同名采集器/README/workflow 已有不同实现 | 与后续研究实现发生分化，不能盲合；扩展研究按本轮范围暂停 |
| [#45](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/45) | head `47d0d144`，2 文件修复多文章曝光席位；当前主线仍统一建议 `comprehensive_result / slot=1`，未包含该新增回归用例 | 缺陷未修复，列为待核心判断的历史曝光回填项；本轮只完成分类，不执行生产回填 |
| [#26](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/26) | head `226aab0c`，5 份历史生命周期文档；主线已有 `production_release_20260726.md` 及相应历史记录 | 保留关闭部署/dry-run 历史；不据此重新关闭或启用当前服务 |
| [#24](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/24) | head `61d4c526`，12 文件研究证据；原 PR 明确保持 Draft、不计划合并，结果仍保留抓取和映射错误 | 保留可追溯研究构件，尊重原研究用途；不导入生产或继续扩量 |

原 PC 未提交文件不能从 PR 状态推断已恢复。2026-09-09 已只读列出远端 205 个 branch refs：未找到 `stabilize-race-data-pipeline` 或 `racing-completion-orchestration` 同名分支；相近的 `codex/feat-tra-completion-orchestration` 指向 `e94c0d8e`，最新提交为 9 月 1 日的研究来源守恒修复，不能证明两个旧目录中的未提交候选已保存。目录内容仍需原 PC 或其备份，当前保留为外部恢复项，不重建或盲合候选，也不阻塞已在仓库内可验证的 M2 与测试修复。

## 1. 如何使用本文

本文解决两个问题：

1. 汇总近期已经启动但还没有收口的工作；
2. 收录“记录待修复事项与方案”中尚未完成的产品、数据和运维事项，并给出依赖明确的执行路线。

状态来源按以下优先级解释：

1. 当前任务内重新核验的代码、Git、运行态和公网证据；
2. [当前状态](current_state.md)；
3. [关键决策](decisions.md)；
4. 本文的日期化摘要；
5. [项目状态文档](project_status.md) 与历史会话记录。

如果本文与 `docs/current_state.md` 冲突，以后者为准；涉及生产时，还必须重新只读核对服务器，不能把本文中的数量、SHA、进程或页面快照当成永久真相。

## 2. 新 Agent 的必读入口

开始工作前依次阅读：

1. 仓库根目录的 [AGENTS.md](../AGENTS.md)；
2. [新 Session 启动模板](session_bootstrap.md)；
3. 本文；
4. 按任务关键词查询 [当前状态](current_state.md) 与 [关键决策](decisions.md)；
5. 赛事自动化任务再读 [完整赛事状态自动化方案](changes/complete-race-status-automation-coverage/spec.md)、
   [工程设计](changes/complete-race-status-automation-coverage/design.md)、
   [测试方案](changes/complete-race-status-automation-coverage/test_cases.md)、
   [任务清单](changes/complete-race-status-automation-coverage/tasks.md)、
   [上线与回退](changes/complete-race-status-automation-coverage/rollout.md) 和
   [工程审核记录](changes/complete-race-status-automation-coverage/review.md)；
6. 部署、生产数据或服务操作再读 [部署运行手册](deploy_runbook.md)、
   [生产部署说明](deploy_production.md)、[回滚指南](rollback_guide.md) 和
   [备份恢复](backup_recovery.md)。

每个 Agent 开始前必须写明：目标、负责文件、非目标、当前 worktree、依赖、验证方式和适用的 G1/G2/G3。人工确认门禁只以根 `AGENTS.md` 为准，本文不新增授权。

## 3. 当前真实基线与证据边界

### 3.1 已经证明的能力

- event 956 已真实走通
  `scheduled -> running -> finished -> official result -> canonical result -> publication -> public page`，
  并完成一次“来源内容未变化”的自然 correction 幂等周期。
- France 2023 五马已完成 External staging：只写 External 数据和审计 receipt，没有自动晋级
  canonical identity、`HorseProfile`、registry 或公网发布。
- 赛事日历默认日期窗口、月份浏览和移动端级别徽章已经完成。
- 马匹履历分页和数值名次规范化基础已经上线。
- 新闻地区页/来源元数据、正文抽取、历史正文污染修复、英文常用词马名上下文门禁、后台标题控制和
  AI 标题建议均已完成。

以上只能证明对应范围，不代表全站所有赛事、马匹、来源或历史数据已经完整。

### 3.2 仍然不能宣称的能力

- 不能宣称“全部未来赛事会自动纳管并更新状态”。
- 不能宣称“所有已结束赛事都有完整正式赛果”。
- 不能把 Celery `SUCCESS`、HTTP 200、邮件/通知 `SENT`、wrapper exit 0 或页面可打开单独当成业务成功。
- 不能把 candidate-only、offline shadow、测试通过或旧生产快照当成生产已发布。
- 不能把五马 External staging 的 SUCCESS receipt 推导为 canonical identity 或公网马匹资料已经完成。

### 3.3 2026-09-04 至 2026-09-05 的只读观察

- 全站赛事自动化盘点中，未来目标 128 场：127 场因备用来源与主来源竞争导致 route ambiguity，1 场受人工锁阻断。
- 赛事结果复核的最近一次记录为 run #105：40 个目标、0 个 candidate、40 个
  `route_missing` blocker、dry-run 数据库写入 0；对应定时任务已经由用户停止，但底层缺口没有消失。
- event 755、756、757 已有 official observation/revision，但状态、canonical result 或 publication
  没有完整闭环；不得直接把旧 revision 投影到公开页。
- 公网 `/healthz/`、首页和抽查页面返回 HTTP 200；同时仍观察到首页“今日赛事”与“时刻待定”、马匹主要胜场混入
  G2/G3、香港马名/履历字段仍为英文或来源原文、QEII 页面保留年份切换和非完赛展示缺口。
- 最新监控记录中的服务器 checkout 与运行 image revision 不一致。该差异未证明事故，但进入任何发布窗口前必须
  重新确认“仓库预期、服务器 checkout、实际容器 image、migration leaf”四者关系。
- 旧 Redis `race_live=7543` 是隔离遗留队列；任何后续工作不得擅自消费、迁移、purge 或重排。

这些是日期化快照。新 Agent 使用前必须刷新。

## 4. 不可破坏的产品与数据原则

1. **先只读、后写入。** 生产诊断从只读开始；写库、迁移、重启、开关、发布、真实网络扩量和外发必须按根
   `AGENTS.md` 的门禁执行。
2. **候选数据 fail closed。** 未审核的来源、模糊身份、partial result、未知状态和缺证据字段只进入
   candidate/review/observation，不得进入 canonical writer。
3. **来源可信与纳管授予分开。** 所有已批准来源都视为可信；赛事纳管按“先到先得”授予：一次性
   授予、同轮平局按 policy 固定顺序裁决、授予后粘滞。只有具备完整能力（赛时/出马表/赛果）的
   来源可竞争纳管；仅赛果能力来源只作为更正证据渠道，不得直接改写 canonical。来源选型参考
   顺序仍为 The Racing API、赛事权威官方站点、Racing Post、ATR 等可信综合来源，但该顺序不再
   指定固定主来源。
4. **稳定身份优先。** 使用 source-scoped stable ID、alias 和 provenance；不得仅凭名称、翻译或模糊相似度合并马匹或赛事。
5. **赛果完整性按实际参赛者守恒。** `finished` 不等于“只有有名次的马”；退赛、未出赛、竞走中止、
   失格、未完赛等必须保留明确状态。
6. **状态、赛果、公开必须共用授权。** lifecycle writer、result writer 和 public reader 不能各自复制一套
   admission 判断。
7. **公开时间统一为北京时间。** 数据层保留举办地 wall-clock、IANA timezone 和 aware UTC，展示层统一明确标注北京时间；
   DST 由原时区计算，不能把无时区时间直接当 UTC。
8. **外部成功信号不能替代业务守恒。** 验收必须同时核对身份、状态终态、结果行、确认字段、事务写入、
   publication 和公网展示。
9. **旧链隔离。** `race_live` 在新链稳定并另有决策前保持原样。
10. **不输出秘密。** secret、token、Cookie、原始敏感 payload 和生产凭据不得进入日志、文档或提交。

## 5. 近期未收口工作

| 工作 | 当前状态 | 已有成果 | 剩余动作 | 主要阻塞 |
| --- | --- | --- | --- | --- |
| 完整赛事状态自动更新 | 2026-09-07 已生产上线并分阶段启用完成（PR #176/#177/#178，运行 `ca6e9d06`） | 独立 review APPROVED；全量回归与基线一致；关闭态部署→A-F 阶段验收通过 | 自然闭环持续验收（等 today/tomorrow 赛事自然走完）；观察期后进入 M3 | 无 |
| 赛事数据链路稳定化候选 | 本地 candidate-only，未提交/未推送/未部署 | 多语言赛事/场地身份、JRA/NAR fail-closed route、D-1..D+3 审计、field-scoped evidence、五事件 offline shadow；聚焦测试 136/136 | 从最新主线做逐文件 diff，只提取完整赛事自动化需要的基础，不得整分支直接合并 | 与主计划存在重叠，含 migration 0079 候选 |
| 定时赛果复核 | 任务已停止，问题未解决 | 调度、审核包、通知和 dry-run 可运行 | 先修先到先得 route admission，再恢复只读复核；不得把通知成功当结果补齐 | 40/40 `route_missing` |
| event 755/756/757 恢复 | 2026-09-07 已完成 | 三场经审计修复包修复：轮换+复核+dry-run+apply+verifier+公网验收全过，incident 收口 | 无剩余动作；更正观察由 standing policy 接管 | 无 |
| Racing API 四地区重赏马导出 | `BLOCKED / INCOMPLETE` | 559/559 本地研究测试；21/200 stable IDs 有可复用 profile+career | 等待可审计的 provider 权限/回复或用户精确 G3；重新绑定 ledger、scope、预算后才可联网 | 两份 proposal 均未批准；179 个 stable ID 缺口 |
| P0 马匹资料生产补全 | 候选已冻结，未获新写入授权 | 最近记录候选：32 profile updates、180 race creates、230 cross-source updates、32 source upserts、128 audits；422 条目标守恒，16 个 blocker 冻结 | 重新生成并核验不可变 candidate，提交精确 G3 包；写后独立 verifier | 旧 candidate/旧授权不可复用 |
| 历史 PR 与 worktree 收口 | 未完成 | 2026-09-05 仍有 7 个 open PR 和大量 worktree | 逐项判断继续、拆分、替代或归档；先只读，不批量关闭或删除 | 分支陈旧、依赖关系不清 |

本地候选位置仅用于当前机器交接，不能作为远端已保存证明：

- `/Users/mentianlu/.codex/worktrees/stabilize-race-data-pipeline/umanews`
- `/Users/mentianlu/.codex/worktrees/racing-completion-orchestration/umanews`
- 原计划来源：`/Users/mentianlu/.codex/worktrees/plan-complete-race-status-automation/umanews`

本文分支已把完整赛事自动化的六份计划文档纳入仓库；其他两个 worktree 仍需后续 Agent 做差异提取和持久化。

## 6. 完整赛事自动化：用户已定稿的五项决定（2026-09-05）

以下五项已于 2026-09-05 由用户审核定稿；第 1、4 项否决了工程建议并按用户口径改写，方案文档已同步修订。
完整决定文本与后果见 [关键决策](decisions.md)。

1. **不设指定主来源**：所有可信来源按“先到先得”竞争首次纳管；纳管权只授予一次、同轮平局按
   policy 固定顺序（`tiebreak_order`）裁决、授予后粘滞；只有具备完整能力（赛时/出马表/赛果）的
   来源可竞争，仅赛果能力来源只进更正渠道；获胜来源失效时回池重新授予并留换手审计。
2. SLA 从 provider 实际开放窗口开始计算；保留未来 30 天盘点，但窗口外标记
   `awaiting_source_window`，不承诺当前 provider 无法提供的 D-30 出马表。（同意原建议）
3. 新链以 data-sync enrollment + standing policy 授权 lifecycle；legacy registry 只服务旧固定名单，
   双 authority 必须拒绝。（接受原建议）
4. event 755/756/757 一类停滞赛事**不等待新链自然恢复**，改用一次性审计修复包单独修复上线：
   来源证据复核 -> SHA 锁定候选 -> dry-run -> 备份 -> 人工批准 -> apply -> 独立 verifier ->
   公网验收；不硬编码 event ID。（否决原建议）
5. correction 变化分支在隔离 PostgreSQL 用 fixture 验证；生产发布完成只要求自然无变化周期幂等，
   不制造虚假更正。（同意原建议）

详细依据与反例见
[工程审核记录](changes/complete-race-status-automation-coverage/review.md)；
第 1、4 项修订记录见同文件第 12 节，修订设计复审已于 2026-09-05 通过（§12.1），
下一步从 tasks 的 RED 测试开始。

## 7. “记录待修复事项与方案”未完成清单

### 7.1 赛事数据、状态与赛果

| 待修事项 | 建议方案 | 完成标准 | 依赖/优先级 |
| --- | --- | --- | --- |
| 非空出马表停止刷新，无法反映退赛、取消参赛、骑师、档位和开赛时间变化 | 在来源开放窗口内继续按 cadence 抓取；用版本化 observation 比较字段级变化；合法来源才更新 canonical | 变更有 provenance、无跨赛事写入、重复响应幂等、页面展示最新合法版本 | M1，P0 |
| entry 状态和 result 状态混用 | 明确拆分 `entry_status` 与 `result_status`，定义状态映射和不变量；先模型/接口设计与 migration 评审 | 退赛/未出赛不会被误当完赛；历史兼容和回滚通过 | M1/M3，P0 |
| 非完赛马在正式赛果中丢失 | 以 declared/actual starter 守恒生成结果；保留 scratched、withdrawn、non-runner、DNF、PU、DSQ 等稳定 reason code | 每个实际参赛者恰好一条结果或非完赛状态；未知状态 fail closed | M1，P0 |
| provisional 与 official 复核不完整 | 保存 observation/revision，只有完整 terminal + 来源优先级 + admission 通过才确认；更正 supersede 旧 revision | `is_confirmed`、`result_confirmed_at`、rows、publication 一致 | M1/M2，P0 |
| 全站赛事字段不统一 | 分字段保存来源证据，分批补齐 distance、age restriction、surface、course、grade；冲突进 review | 每字段有来源/时间/hash；无证据不覆盖已有可信值 | M3，P1 |
| 时区和 DST 口径不统一 | 存举办地 wall-clock + IANA + aware UTC；公开统一北京时间标签 | 跨 DST fixture、数据库值、页面文案一致 | M3，P1 |
| 赛果复核长期 `route_missing` | policy v2 改为先到先得纳管（一次性授予、固定平局顺序、授予后粘滞）；audit 输出无可信 route、窗口等待、not-found、多解等守恒分类 | 候选不再静默消失；`route_missing` 有可行动原因 | M1，P0 |

### 7.2 赛事页面、首页与新闻联动

| 待修事项 | 建议方案 | 完成标准 | 依赖/优先级 |
| --- | --- | --- | --- |
| 赛事详情页年份切换增加噪音 | 移除详情页 year switch；历史年份从赛事列表/系列入口进入 | 桌面和移动端无回归，旧 URL 可访问 | M3，P1 |
| 首页“今日赛事”范围和空时间显示不合理 | 改为“近期赛事”，范围为今天起 7 天（今天 + 6 天），最多 4 场；无可靠时间时不显示“时刻待定” | 排序、数量、空态、时区均有测试 | M3，P1 |
| 赛事影响新闻与结构化数据没有清楚边界 | 新闻可只绕过与赛事影响冲突的 soft gate，不绕过来源、安全和事实 hard gate；结构化赛事数据写入继续独立审核 | 新闻发布不自动写赛事/马匹 canonical；审计可追溯 | M3，P1 |
| 非完赛状态前台表达不足 | 为退赛、竞走中止、失格、未完赛提供中文稳定显示，不用空名次代替 | QEII 等历史 fixture 显示正确，来源证据不泄露内部字段 | M3，P1 |

### 7.3 马匹资料

| 待修事项 | 建议方案 | 完成标准 | 依赖/优先级 |
| --- | --- | --- | --- |
| 履历分页存在但生涯记录不完整 | 建立 career completeness 守恒：来源声明总场次、抓取页数、去重赛事、已写行数和缺口原因必须相等 | 不以“有分页”冒充完整；缺页/重复/冲突可审计 | M4，P1 |
| “主要胜场”混入 G2/G3 | 只展示胜出的最高级别，优先 G1/Jpn1/地区等价 G1；定义并测试同名重复赛事和等级映射 | 抽查 Art Power 等页面不再混入低等级胜场 | M4，P1 |
| 香港马匹缺官方中文名 | 以 HKJC stable ID 和官方繁体名建 alias，再按受审规则转简体；例如 `DINOZZO -> 達羅素 -> 达罗素` | 不按英文名模糊合并；title、搜索、历史记录一致 | M4，P1 |
| 履历缺骑师、完成时间、前后比较马 | 扩展字段级 evidence contract；缺值保持空，不解析展示文本猜测 | 每个新增字段有 provenance、冲突策略和回归测试 | M4，P1 |
| 2020+ 顶级赛胜马中文名仍有缺口 | 生成 G1/Jpn1/HK local G1 gap ledger；当前排除日本地方非 Jpn1 和其他地区 local G1 | 分母、命中、阻断和来源角色守恒；候选不直接发布 | M4，P1 |
| 马匹索引无法体现资料完整度 | 建立显式 completeness score/status，并把人工优先、冲突、近期活跃等排序因素分开 | 排序稳定、可解释、无空 identity 加分 | M4，P2 |

### 7.4 地区扩展

| 地区 | 建议顺序与方案 | 前置条件 |
| --- | --- | --- |
| Ireland | 第一优先；补 region/provider contract、stable identity、测试和只读 census，再进入 candidate | 完整赛事主链 M2 稳定；来源和授权明确 |
| Australia | 第二优先；先解决赛季制目录、访问稳定性和官方证据覆盖，再做映射 | 不把跨年赛季文件冒充自然年完整目录 |
| Middle East | 第三优先；region 下按 UAE、Saudi、Qatar、Bahrain 等国家分别校验身份和来源 | country 不能缺失或冲突；不得把一个国家的证据外推到整个地区 |

新增地区不得直接复制旧地区路由，也不得因可信第三方可访问就自动获得纳管竞争资格（`enrollment_eligible`）。

### 7.5 内容生产、后台与模型

| 待修事项 | 建议方案 | 完成标准 | 优先级 |
| --- | --- | --- | --- |
| AI 改写可能改变事实 | 建立 golden set、结构化事实槽位和禁止改写字段；先单文章，再多文章聚合 | 人名、马名、赛事、日期、数字、引语不漂移；失败回退原文/人工审查 | M6，P2 |
| 多文章聚合缺少可追溯性 | 句段级保存来源映射和冲突，不把多个来源合成为无出处“事实” | 每条重要断言可回到来源；冲突进入 review | M6，P2 |
| 后台移动端操作密度不足 | 以高频审核路径为单位重做 mobile-first 布局，不先重构后台主干 | 核心审核可在手机完成，桌面行为不退化 | M6，P2 |
| DeepSeek/GPT 路由缺少系统评估 | 建立模型能力、成本、延迟、失败率评估；配置 circuit breaker 和 rollback | 模型切换可审计、可灰度、可回退，不因供应商失败阻塞发布 | M6，P2 |

## 8. 分阶段 Roadmap

### M0：收口与建立唯一实施主线

目标：在继续写代码前，消除重复方案、陈旧分支和不明确的生产基线。

- 用户审核第 6 节五项产品决定（已完成：2026-09-05 定稿，第 1、4 项按用户口径改写）。
- 以 `complete-race-status-automation-coverage` 作为赛事自动化唯一产品主线。
- 对 `stabilize-race-data-pipeline` 做逐文件差异审计，只迁入被主方案需要且有测试的基础；不得整体 cherry-pick。
- 刷新 open PR、worktree、远端分支和生产运行态清单。
- 给 7 个 open PR 分别标记：继续、需要 rebase/拆分、已被替代、待归档；归档/关闭另行执行。
- 冻结一份脱敏生产 census：未来赛事、source identity、enrollment、lifecycle authority、official revision、
  publication、人工锁、三队列、服务和资源。

完成标准：

- 只有一个赛事自动化实现分支和一份按第 6 节决定修订并复审通过的计划；
- 所有候选 worktree 都有 owner、用途、保存位置和处置状态；
- 生产四层版本关系及分母可重放；
- 没有执行生产写入、联网扩量、服务变更或队列操作。

### M1：实现完整赛事自动化的代码闭环

目标：解决全站 enrollment、状态、赛果和公开授权的结构性缺口。

顺序：

1. 先写 policy v2、discovery 守恒、双 authority、755/756/757 审计修复、correction 和 PostgreSQL 并发 RED；
2. 实现先到先得纳管（一次性授予、固定平局顺序、授予后粘滞、仅完整能力来源可竞争）、未来 30 天盘点与最近 7 天恢复清单；
3. 实现唯一 `validate_data_sync_lifecycle_admission()`；
4. 让 lifecycle、result projection 和 public read 共用校验器；
5. 增加审计分类、incident reason code、kill switch 和资源门禁；
6. 完成本地 SQLite/Eager、独立 PostgreSQL 16、Compose、migration drift、secret scan 与独立 review。

完成标准：

- [任务清单](changes/complete-race-status-automation-coverage/tasks.md) 第 0–4 节全部完成；
- 预计无 migration；如产生 migration，立即返回产品/发布风险审核；
- event 956 成功 fixture 不变，755/756/757 型停滞 fixture 可通过审计修复包完成闭环；
- legacy `race_live` 和 France staging 范围零变化。

### M2：关闭态发布与自然灰度

目标：证明新链在生产自然运行，而不是只在测试或手工命令中成立。

发布顺序固定为：

`只读 policy/census -> future discovery/enrollment -> time/racecard -> lifecycle -> result apply/public -> correction`

每阶段都核对：

- exact commit/image/migration leaf；
- policy/registry SHA 和 feature flags；
- shared lock、服务 restart/OOM、内存、磁盘、Swap 和三队列；
- scheduler admission、provider request、observation/revision、canonical write、publication、root/www；
- 任何异常时 fail closed，旧 `race_live` 不变。

完成标准：

- 至少一场新的 today/tomorrow 赛事自然完成发现、身份、纳管、时间、出马表、状态和正式赛果公开；
- 755/756/757 型赛事通过一次性审计修复包恢复并公开（证据复核、dry-run、备份、批准、apply、verifier 全流程），不绕过审计直接改库；
- 完成一轮自然“内容未变化” correction 幂等验证；
- 首个真实 correction 留作持续验收，不在生产造数；
- 最终事实写回所有受影响状态和运行手册。

### M3：赛事数据质量与公开体验

目标：在主链稳定后补齐连续 racecard、状态模型、字段规范和页面口径。

建议拆成独立 change：

1. `entry_status/result_status` 与非完赛状态；
2. continuous racecard refresh；
3. 北京时间、IANA timezone 与 DST；
4. distance/age/surface/course/grade 字段级补全；
5. 首页近期赛事、移除详情页年份切换、非完赛中文展示；
6. 赛事影响新闻 soft gate 与结构化数据写入解耦。

完成标准：

- 每个 change 独立测试、独立 review、独立灰度；
- 不以一次大 migration 同时修改模型、历史数据和 UI；
- 页面抽样和数据库守恒同时通过。

### M4：马匹资料闭环

目标：把“页面存在”提升为“身份稳定、履历完整、中文可用”。

顺序：

1. 重新生成 P0 不可变 candidate，并按精确 G3 完成已批准范围的 apply/verifier；
2. career completeness 守恒；
3. 主要胜场只显示最高等级；
4. HKJC 官方中文名和稳定 ID alias；
5. 骑师、完成时间、比较马等字段级证据；
6. 2020+ G1/Jpn1/HK local G1 中文名缺口 ledger；
7. 马匹索引 completeness 排序。

完成标准：

- canonical 与 external identity 的新增/合并都有不可变证据；
- source total、分页、去重、写入、阻断数量守恒；
- 公网页不再以原始英文/source fragment 代替可用中文；
- 阻断项被明确保留，不为追求覆盖率猜测合并。

### M5：地区扩展

目标：在主链和身份规则稳定后扩大覆盖。

顺序固定为：Ireland -> Australia -> Middle East。

每个地区先完成：

1. 来源许可/能力与开放窗口确认；
2. source contract、stable identity 和 country/region 规则；
3. 只读 census 与 candidate-only shadow；
4. review 后的小批灰度；
5. 自然赛事完整链验收；
6. 才扩大分母。

### M6：内容质量、模型路由与移动后台

目标：在数据真相稳定后提升运营效率。

顺序：

1. golden set 与事实槽位评估；
2. DeepSeek/GPT 路由、成本和 circuit breaker；
3. 单文章事实安全改写；
4. 多文章聚合与句段级来源；
5. 移动端高频审核路径重构。

该阶段不能反向放宽赛事/马匹 canonical 门禁，也不能因为 AI 输出流畅就跳过事实验证。

## 9. 并行与依赖关系

可以并行：

- M1 的 integration policy/discovery 测试与 application validator 测试，可在文件责任不重叠时并行；
- operations 可并行准备只读 census、容量预算和回滚草案；
- M4 的中文名 gap ledger 可以 candidate-only 运行，不写 canonical；
- M6 的 golden set 设计可与 M3/M4 并行，但不能接入自动发布。

必须串行：

- M0 产品决定 -> M1 实现 -> M2 生产灰度；
- 先到先得 route admission 修复 -> 恢复定时赛果复核；
- 身份规则稳定 -> canonical 马匹写入；
- 完整赛事主链稳定 -> 新地区 production enrollment；
- 数据真相稳定 -> AI 自动改写/聚合自动发布。

## 10. 多 Agent 协作边界

| 责任域 | 建议负责内容 | 主要文件边界 |
| --- | --- | --- |
| application | Django model/service、admin、public view/template、状态与展示 | `server/stable/models.py`、应用 service、admin、template、application tests |
| integration | provider contract、identity、matching、import、Celery 编排、policy | `server/stable/services/race_data_*`、`tasks.py`、runtime policy、integration tests |
| operations | Compose、发布、容量、监控、备份、回滚、生产只读验证 | `docker-compose*`、`deploy/`、运行手册、production verifier |
| reviewer/security | 只读检查架构、并发、注入、secret、权限和回滚完整性 | 不拥有实现文件，不提交产品改动 |

协作规则：

- 每个 Agent 使用独立 `codex/<slug>` 分支和独立 worktree；
- 同一时间只有一个 Agent 拥有共享状态文档或同一个核心模块；
- 任务说明必须列出文件 ownership，其他 Agent 不回退、不覆盖已有修改；
- 跨域接口先写契约和测试，再分别实现；
- reviewer 只读；finding 回到原 owner 修复并在同一 reviewer 上下文复审；
- commit、push 和 Draft PR 可按根 `AGENTS.md` 在已批准范围内连续完成；合并/发布仍走 G2/G3；
- runtime artifact、凭据、生产 dump 和原始第三方 payload 不提交到 Git；
- 每个 change 完成后更新实际受影响的 `current_state`、`decisions`、运行手册和本 roadmap 状态。

## 11. 统一验收矩阵

任何“已完成”都要给出对应证据，至少覆盖：

| 维度 | 必须回答的问题 |
| --- | --- |
| 页面症状 | 用户看到的内容是否正确，而不只是 HTTP 200？ |
| 身份与路由 | event/horse stable ID 是否唯一？本场纳管权由哪个来源持有、何时授予、平局裁决与换手是否有审计？ |
| 调度准入 | Beat/selector 是否真的纳管，还是只生成了审核包？ |
| 来源调用 | 是否命中获准 route/window/budget？响应是否完整和可重放？ |
| 数据库写入 | 哪些表、多少行、哪个事务、是否越界？dry-run 必须明确为 0 写入。 |
| 终态 | `finished`、runner/result 数、nonfinish、`is_confirmed`、`result_confirmed_at` 是否一致？ |
| 公开投影 | revision、publication、root/www 是否一致且不泄露内部状态？ |
| 运行安全 | exact image/commit/leaf、flags、locks、queues、restart/OOM、资源和回滚点是否通过？ |

单一 `SUCCESS`、`SENT`、HTTP 200 或静态截图不能让整行验收通过。

## 12. 当前 open PR 清单

截至 2026-09-05，只读查询仍有以下 7 个 open PR：

| PR | 状态 | 主题 | 建议动作 |
| --- | --- | --- | --- |
| [#87](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/87) | Draft | PR #86 G2 发布记录 | 核对是否已被后续发布记录替代 |
| [#85](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/85) | Draft | migration 0072 生产完成记录 | 核对当前 leaf 和历史归档价值 |
| [#59](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/59) | Open | 重赏马 alias 与启发式 RaceEvent link | 重新审查启发式身份风险，避免直接合并 |
| [#49](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/49) | Draft | 多年度重赏参赛马研究 | 与 Racing API 四地区工作统一分母和来源 |
| [#45](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/45) | Open | 曝光回填席位分配 | 核对是否被现行曝光逻辑替代 |
| [#26](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/26) | Draft | lifecycle dry-run 记录 | 与已完成 event 956 证据比对后决定归档 |
| [#24](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/24) | Draft | 2026 重赏前五 Wikipedia 映射 | 并入统一马匹 identity/gap ledger，避免双轨 |

该表只授权后续只读分类，不授权批量关闭、删除分支、合并或部署。

## 13. 下一位 Agent 的第一轮执行清单

以下是 2026-09-05 的历史启动清单；当前任务先执行第 0 节，不重跑已完成的 M1/0078/956 交付：

1. `git fetch --prune origin` 后记录 `origin/main`、当前分支和 worktree 状态；
2. 读取第 2 节全部核心文档，用自己的话重述五项产品决定；
3. 只读刷新 7 个 open PR、关键 worktree 和生产四层版本关系；
4. 对稳定化 candidate 与主计划做 path-level diff，输出“迁入 / 重写 / 丢弃 / 需决策”表；
5. 生成新的脱敏全站 census，逐项区分页面、身份、route、admission、任务、数据库写入和 publication；
6. 产品决定已于 2026-09-05 定稿，第 1、4 项修订设计复审同日通过；从
   [任务清单](changes/complete-race-status-automation-coverage/tasks.md) 的 RED 测试开始；
7. 未获得外部权限时，继续只读和本地验证，不启动 provider、生产写入、服务变更或队列操作。

## 14. 文档维护规则

- 完成一个 milestone 后，在本文对应条目写明完成日期、commit/PR、验证证据和剩余限制；
- 新发现若属于现有条目，更新原条目，不再复制一份并行 backlog；
- 新产品决定写入 `docs/decisions.md`，这里只保留摘要和链接；
- 生产状态写入 `docs/current_state.md`，这里只保留日期化快照；
- 详细实现继续放在 `docs/changes/<slug>/`，不要把本文扩成代码级设计文档；
- 数量、SHA、URL 页面结果和资源值都必须带日期；过期后先刷新再使用。
