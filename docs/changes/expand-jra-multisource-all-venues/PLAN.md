# 计划：JRA 多来源登记扩展至全部 10 个中央马场

> 状态：v5（任务 1/2 已实施并上线；3.3 proof 改为分层口径）。实施中。
> 审阅记录：见同目录 REVIEW.md。

## 1. 背景与当前真实状态（2026-09-26 核验）

- 生产运行 `15c79f22`（PR216 + PR219 T/F 归一 + PR221 换绑路径），schema 0079；多来源登记（PR212）已上线，JRA route 真实启用。
- 当前 multisource policy（`jra-official-results-20260922-v1`，SHA `d28a690b…f993`）只覆盖：
  - provider `jra` / region `japan_jra` / capabilities `["result"]`；
  - `venue_aliases` 仅 `hanshin`（阪神）与 `nakayama`（中山）；
  - 有效期至 `2026-10-21T17:14:43Z`。
- 已完成自然闭环证据：103/104/105（9/22，见 `docs/changes/multisource-race-enrollment/release-20260922/README.md`）。106/107 在 9/26 18:01 交接样本中仍未登记（`docs/current_state.md` 既有条目），此后状态以任务 5 的生产只读预检为准——换绑 manifest 的目标清单（3 条还是 5 条）由预检时的实际 enrolled 集合生成，本计划不预设该数量。
- 赛前 seed 路径（`discover_jra_pre_race`）本身覆盖全部 10 个 JRA 马场（`JRA_COURSES`），CNAME 解析表 `_JRA_VENUE_CODES` 也已内置 01–10 全部马场代码；瓶颈只在 policy 的 venue 范围。
- 名称匹配已上线确定性归一（PR216）：等级前缀 + `ステークス→S`／`カップ→C`。JRA 官方缩写字母为 S/C/T/F 四个，剩余系统性差异为 `T=トロフィー`、`F=フィリーズ`（111 アイルランドトロフィー已经 JRA 官方出马表页证实；138 阪神ジュベナイルフィリーズ为 GⅠ 官方赛事名，实施前以真实页面复核）。
- 当前后果：下周末 108 毎日王冠（10/4 東京）、109 京都大賞典（10/4 京都）等政策外赛事会赛前有出马表预览、但不登记、不闭环正式赛果，且因分类为范围外而不产生覆盖告警。

## 2. 目标与非目标

**目标**

- JRA 官方 result 路线的登记/赛果闭环覆盖全部 10 个中央马场（札幌、函館、福島、新潟、東京、中山、中京、京都、阪神、小倉）。
- 预检时实际 enrolled 的既有登记（预期 103–105 或 103–107，以任务 5 预检为准）在扩版后持续自然刷新，不发生 digest 漂移断链。
- 覆盖告警（`enrollment_missing`）对该范围生效，未登记不再静默。
- 用 108/109（10/4）作为首个自然闭环验收样本。

**非目标**

- 不改变 NAR/地方、海外（TRA/Sporting Life/ZEturf/HRN/RP/ATR）任何路线与范围。
- 不修改 v1 census standing policy；不动旧 `race_live=7543` 队列。
- 不放宽强身份规则：身份仍由 CNAME 结构 + 页头一致性 + venue 别名单一命中证明，名称相似度不用于合并。
- 不承诺 D-30 等 provider 不支持的窗口；结果能力仍以官方结果页发布后为准。

## 3. 设计

### 3.1 policy 扩版与 digest 漂移处置（核心变更 + 审阅 P0 对策）

新建 policy `jra-official-results-2026-v2`（schema_version 3 不变），相对 v1 的 diff 仅为：

- `venue_aliases` 扩为 10 个马场，key 用英文小写（`sapporo/hakodate/fukushima/niigata/tokyo/nakayama/chukyo/kyoto/hanshin/kokura`），每个含日文名与英文名，与 `_JRA_VENUE_CODES`（`race_data_source_adapters.py:257-268`）逐码一致；
- 新 `policy_id`、新有效期（自激活起 30 天）；
- `proof_digest` 按 v1 同款生成方式重新计算（v1 的具体摘要输入集合实施前先定位并记录，见任务 2）；
- `contract_digest`、`parser_version=jra-cname-v2`、hosts/path 前缀、tiebreak_order 等不变。

**digest 漂移是确定发生的**（venue_aliases、policy_id、有效期变化必然改变 route digest 与 policy digest），其后果已经独立审阅在代码层证实：

- `claim_binding`（`race_data_source_adapters.py:525-526`）要求 `route.digest == binding.route_digest`，否则 `binding_route_missing`，既有登记的赛果刷新停止；
- admission（`race_data_sync_admission.py:459-463`）以 `binding_contract_drift` 拒绝；
- `attach_multisource_observation`（`race_data_sync_enrollment.py:1486-1487`）要求 `enrollment.standing_policy_digest == policy.digest`，否则 `enrollment_policy_drift`，既有 enrollment 无法自行 re-attach。

**复审进一步证实：现有代码不存在可用的换绑路径**——`adopt_stalled_event_policy` 明确拒绝 v2 登记（`race_data_sync_repair.py:108-111`，authority_version=2 直接返回 `multisource_claim_required`）；stalled 扫描只覆盖未公开/有 open incident 的赛事，扫不到健康的 103–107；`rotate_enrollment` 走 legacy provider 注册表（不含 multisource jra route）且从不更新 `RaceDataSyncSourceBinding`；`disenroll` 后 re-attach 会被 `enrollment_not_active` 拒绝。

**对策（新增受审的 v2 换绑路径，独立 PR 先行）**：在 `race_data_sync_enrollment.py` 新增 `rebind_multisource_enrollment`（或同级服务函数）+ 管理命令，语义为：

- 输入为 SHA 绑定的 manifest（逐 event 列出 binding 旧 digest → 新 digest），dry-run 默认；
- 逐场单事务，前置条件：event 处于 enrolled、binding 当前 digest 精确等于旧 route digest、既有 source identity 的 canonical_url 在新 route 下仍 `permits_url` 且 CNAME/venue 解析不变；任何一项不满足即该场 fail closed；
- 更新必须覆盖完整 digest 闭集（第 3 轮审阅逐点核实，遗漏任一都会在运行态被确定性地 fail closed）：
  1. binding：`route_digest`/`proof_digest`/`binding_manifest`（含内嵌 `policy_digest`）/重算 `binding_manifest_sha256`/`valid_until` 同步新 route 有效期；
  2. enrollment：`standing_policy_digest` 与 `route_digest`（后者与 claim 签发/校验链一致，`race_data_sync_control.py:242,248,2864`）；
  3. **直接复用既有 `_multisource_manifest`（`race_data_sync_enrollment.py:1276-1386`）重新生成 source set manifest 与 lifecycle 证据并使旧 claim 失效**，不手写局部更新（否则 `source_set_drift`/`binding_set_drift`，见 `race_data_sync_admission.py:271,283-284,309-317`）；
  4. checkpoint：`registry_digest` 同步为新 route digest（claim 选取循环的强一致条件，`race_data_sync_control.py:2816-2820`）；
  5. source identity 的 `valid_until` 同步新 route 有效期（`admission.py:458,477-478`）；
- 身份行（source identity 本体）不变、不重建；不重抓网络；写 OperationLog/审计；
- 上述每一点都必须有对应回归测试：换绑后 claim 可签发、`claim_plan_drift`/`binding_contract_drift`/`source_set_drift`/`binding_set_drift`/`binding_route_missing`/`enrollment_policy_drift` 均为 0，103–107 形态的 fixture 走通；
- 验收：换绑后目标集合（预检时实际 enrolled，预期 103–105 或 103–107）的 result checkpoint 至少一次自然成功、公开赛果行数不变。

该 PR 必须与 3.2 的 T/F 归一 PR 先后合并部署（顺序不限，但激活必须绑定两者之后的生产 commit）。

### 3.2 名称归一补齐 T/F（代码小改，独立 PR 先行发布）

`normalize_jra_race_name` 的长后缀表追加 `('トロフィー','T')`、`('フィリーズ','F')`（`race_pre_race.py:181-192` 结构兼容：endswith + 长度守卫 + break）。回归测试在既有 `JraNameNormalizationTests` 扩展：

- 111 `アイルランドT`↔`アイルランドトロフィー`、138 `阪神ジュベナイルF`↔`阪神ジュベナイルフィリーズ` 双向匹配；
- 拒绝用例：以 T/F 结尾但本体不同的名字不合并（如 `テストT` vs `テストフィリーズ`）；不同赛事名（シリウス vs スプリンターズ）仍拒绝。
- 该 PR 必须先合并并部署，生产 commit/镜像随之更新；后续激活脚本必须绑定本 PR 与换绑 PR 均部署之后的新 commit（同 3.4）。

101/106/107/111/138 已按用户授权手工补的别名继续保留（幂等、双保险）。

### 3.3 分层来源 proof（2026-09-27 修订：按用户"尽快修复"要求调整激活节奏）

proof 分三层，逐马场记录状态：

1. **生产已证明**：中山（104/105 闭环；107 已登记、正式赛果待 9/27 赛后）、阪神（103/106 闭环）。106/107 的 9/26 登记与 106 闭环证据见同目录 `evidence-106-107-enrollment-20260926.json`（SHA-256 `dd16f5ae93991a0e36fc80888555305bb2de02147377bb6ecd900a4c475fd38b`，生产只读快照，含审计留痕与 incident 收口记录）。
2. **CNAME 级 proof**：东京/京都/中京。JRADB 单场 CNAME 只在赛前出马表发布后出现（历史页不公开链接），因此这三场在 **10/1（周四）10/4 赛事出马表发布当天**从 thisweek 索引取得真实 accessD CNAME 并完成 `parse_jra_observation` 合同校验；随后即激活。
3. **结构级 proof（已于 2026-09-27 完成，8 马场）**：札幌/函館/福島/新潟/小倉/東京/京都/中京（東京/京都/中京在激活前另完成 CNAME 级 proof）。以各马场 2026 年已完赛 G 级赛官方结果页（datafile）验证：页头日期/回数/马场名可解析（解析方法与 `parse_jra_observation` 同款页头正则与选择器）、马场名唯一命中 venue_aliases、赛果表完整。证据包同目录 `structural-proof-20260927.json`（SHA-256 `e2816af905c7b6f488d6802c6a0dea927c278ef973fbad9d44fb0b82e7f76f45`，8/8 通过，页面 SHA 逐场在案；原始页面字节保存在本机 runtime 证据目录，不进仓库）。结构级-only 马场（札幌/函館/福島/新潟/小倉）的 CNAME 级补证在其下一场赛事出马表发布后完成：福島記念（11/21）约 11/17，其余 2026 年内无更多重赏、补证顺延到其下次开赛。

**纳入未完成 CNAME 级 proof 马场的安全性论证**：`_JRA_VENUE_CODES` 或 venue_aliases 映射错误只会导致 `jra_header_url_disagreement`/`venue_unreviewed` fail closed 并产生覆盖告警，不可能写入错误数据；纳入后覆盖告警立即对这些马场生效（满足"未登记不静默"）。因此 v2 policy 一次性纳入全部 10 马场，proof 状态分层记录，CNAME 级补证列为后续任务。

v1 `proof_digest` 生成方式核查结论：无法从仓库归档复原其推导输入（可能来自未归档的临时 proof 包）；v2 的 `proof_digest` 定义为本次分层 proof 证据包（含结构级 bundle、10/1 CNAME 级记录与既有生产闭环引用）的 canonical SHA-256，生成过程写入发布证据目录。

### 3.4 激活脚本：按 9/22 模式新写，不是字面复用

独立审阅已确认 9/22 的 `activate-jra.py` 硬编码不可直接重跑：绑定旧 commit `26706602`、旧 policy SHA/路径、`import release_0079`、镜像 tag `umanewsbot:pr212-26706602`、"恰好一个已完成 0079 release"断言，以及"providers 不含 jra"的前置断言（当前生产已含 jra，原脚本必失败）。

因此本变更按同款模式新写激活脚本，要求：

- 绑定任务 1（T/F 归一 PR）与任务 2（换绑 PR）均合并部署之后的新 commit/镜像、新 policy 路径/SHA、当前实际 providers 集合；
- 意图文件逐字段独立审阅，新意图 SHA 冻结后执行；
- 服务器侧 `release_0079` 模块与运行态（`.env` 实际值、锁状态）无法从仓库核对，列为实施前只读核对项；
- 切换只改 `RACE_DATA_MULTISOURCE_POLICY_FILE/SHA256` 两项 + 必要的换绑动作；回滚为恢复 v1 policy 文件+SHA（已换绑的 enrollment 与新产生的登记不回滚，与 9/22 口径一致）。注意回滚语义：恢复 v1 policy 后，已换绑登记的 binding digest 与 v1 route 同样不匹配，其自然刷新会停止（已公开内容不受影响），回滚只用于中止扩版，不用于恢复原刷新。

### 3.5 覆盖告警行为（激活前后核对项）

- 告警仅落库、无发送任务（`race_data_sync_alerts.py:192-289`），无外发风险。
- `enrollment_missing` 的 incident `dedupe_key` 含 `policy_id`（`alerts.py:267-269`）：切 v2 后旧 policy_id 的 incident 不会因新 key 自动关闭。激活步骤必须**先只读核对每个事件当时的实际 open incident**（不预设哪些仍 open——已确认赛果的赛事其 incident 已由 `alerts.py:209-215` 按 scope_key 自动收口），再对仍 open 的旧 key incident 受控 resolve，不得遗留重复 open。
- 激活时点回看窗口（约 T−9 日）内新马场的已过赛事会同时产生 `enrollment_missing` 与 `result_overdue`。按 9/17–9/26 日历新马场无重赏，预计为 0；激活报告必须实测列出，不能只写预算数字。

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 既有 103–107 登记 digest 漂移断链 | 3.1 新增受审 v2 换绑路径为激活的必要前置；换绑未完成前不宣布激活完成 |
| 某马场页头结构与阪神/中山样本不同 | 3.3 逐马场 proof 先行，任一马场不过则分批入 policy |
| 名称差异超出 S/C/T/F 与等级前缀（如赞助前缀） | 仍 fail closed 到 `jra_race_identity_no_match`；按 9/26 Track A 同款 SHA 绑定别名修复，不为消缺放宽匹配 |
| policy 到期 | 新有效期 30 天；到期前按同流程续期，proof 复用需重新核验页面可解析 |
| T/F 归一的外部事实错误 | T=トロフィー 已有 JRA 官方页面证据；F=フィリーズ 实施前以真实页面复核；两类均叠加同日+同马场校验，跨事件误合并在该链路不存在通道 |
| 激活与在途赛事冲突 | 不再等待 107 闭环（用户指令）；激活后立即换绑既有 enrolled 集合（含 107，若已登记），其赛前/赛后刷新在新 route digest 下继续 |

## 5. 任务清单（含时间约束）

1. ~~(integration) 归一规则追加 T/F 后缀 + 回归测试（RED→GREEN），独立 PR 合并并同 schema 发布~~ **已完成（PR #219，生产 15c79f22）**。
2. ~~(integration) 新增受审的 v2 换绑路径（3.1 对策段）+ 回归测试（含 binding digest 旧→新、identity 不变、非 enrolled/漂移不符即 fail closed），独立 PR 合并并同 schema 发布~~ **已完成（PR #221，生产 15c79f22，含审阅加固）**。
3. (integration) v1 `proof_digest` 生成方式核查（结论：仓库归档无法复原其推导输入，v2 重新定义并记录，见 3.3）；生成 v2 policy 草案（10 venue_aliases），离线校验 schema 与 venue 代码一致性（已通过 `parse_multisource_policy` 实跑验证）。
4. (operations) 分层 proof（3.3）：结构级 8 马场已完成；**10/1（周四）10/4 出马表发布后**完成东京/京都/中京的 CNAME 级 proof。
5. (operations) 生产只读预检：当前登记/告警/预算基线；服务器 `release_0079` 模块与 `.env` 实际状态核对；新 policy 文件落盘与 SHA 绑定。
6. (operations) **10/1 CNAME proof 完成后尽快激活**（不等 107 赛果闭环——换绑路径已上线，107 与其他既有登记在切换后立即换绑、刷新不断链）：新写激活脚本经独立审阅 → 排空 → 原子切换 policy → 立即执行既有 enrolled 集合换绑（任务 2 的新路径）→ 旧 policy_id incident 收口。
7. (operations) 激活后观察：108/109（10/4）自然闭环 身份→登记→正式赛果→双域名公开；既有登记换绑后至少一次自然刷新成功；告警行为按 3.5 实测；福島（11/21）与其余马场的 CNAME 级补证——**补证必须先于（或同日早于）该赛事首次 discovery 尝试完成**（窗口约 T−5 开启）；未完成则该赛事按既有 fail-closed + incident 流程处理，不追赶手工补救。
8. (application) 文档回写：current_state、deploy_runbook、handoff 第 4 节 P0 项状态更新。

**降级预案**：若 10/1–10/2 未就绪（含新激活脚本独立审阅），则 108/109 放弃作为验收样本，激活顺延到下一周赛事（10/10–12 的 110/111/112）之前；顺延期间既有登记继续在 v1 policy 下正常运行，不做任何切换。

## 6. 完成标准（精确口径）

- 分层 proof：东京/京都/中京在激活前完成 CNAME 级校验；札幌/函館/福島/新潟/小倉持结构级 proof 并在其下一场赛事出马表发布后补 CNAME 级；proof_digest 与 policy SHA 绑定。
- 108 或 109 自然完成全流程（不手工触发业务任务、不固定 ID 回填），公网双域名赛果与官方一致；若按降级预案顺延，则以 110/111/112 中的自然闭环替代验收。
- 告警口径与代码一致：`enrollment_missing` 于 T−1 日开单；有 `race_datetime` 的已登记赛事 T+30 分钟无正式赛果开 `result_overdue`；无 `race_datetime` 的 T+1 日开 `time_unknown_overdue`；范围内漏管不被静默；旧 policy_id incident 无残留重复 open。
- 既有 enrolled 登记经新换绑路径迁移后持续自然刷新（checkpoint 成功、`binding_route_missing`=0），公开赛果行数不回退。
- 任一阶段失败可回到 v1 policy；已换绑登记与新登记不回滚。
