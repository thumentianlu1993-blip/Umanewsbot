# 计划：JRA 多来源登记扩展至全部 10 个中央马场

> 状态：计划草案 v4（已按独立审阅第 1–3 轮 REVISE 修订）。待复审与用户批准。未实施、未改生产。
> 审阅记录：见同目录 REVIEW.md。

## 1. 背景与当前真实状态（2026-09-26 核验）

- 生产运行 PR216 合并提交 `c71dcdfc`，schema 0079；多来源登记（PR212）已上线，JRA route 真实启用。
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
- 既有 103–107 登记在扩版后持续自然刷新，不发生 digest 漂移断链。
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
- 验收：换绑后 103–107 的 result checkpoint 至少一次自然成功、公开赛果行数不变。

该 PR 必须与 3.2 的 T/F 归一 PR 先后合并部署（顺序不限，但激活必须绑定两者之后的生产 commit）。

### 3.2 名称归一补齐 T/F（代码小改，独立 PR 先行发布）

`normalize_jra_race_name` 的长后缀表追加 `('トロフィー','T')`、`('フィリーズ','F')`（`race_pre_race.py:181-192` 结构兼容：endswith + 长度守卫 + break）。回归测试在既有 `JraNameNormalizationTests` 扩展：

- 111 `アイルランドT`↔`アイルランドトロフィー`、138 `阪神ジュベナイルF`↔`阪神ジュベナイルフィリーズ` 双向匹配；
- 拒绝用例：以 T/F 结尾但本体不同的名字不合并（如 `テストT` vs `テストフィリーズ`）；不同赛事名（シリウス vs スプリンターズ）仍拒绝。
- 该 PR 必须先合并并部署，生产 commit/镜像随之更新；后续激活脚本必须绑定该新 commit。

101/106/107/111/138 已按用户授权手工补的别名继续保留（幂等、双保险）。

### 3.3 逐马场真实来源 proof（激活前置）

对 10 个马场各取一场 2026 年已完赛 G 级赛的真实官方结果页（accessS），离线执行 `parse_jra_observation` 合同校验：CNAME 马场代码 ↔ 页头回数/马场名/日期/赛事编号一致、venue 别名单一命中、名单/赛果结构完整。建议锚点（**仅为候选，实施时以真实抓取为准**；若锚点赛事当年更换马场或页面不可解析，则换该马场另一场已完赛 G 级赛，任一马场不过则该马场暂不进入本批 policy）：

- 札幌：札幌記念；函館：函館記念；福島：七夕賞；新潟：新潟記念；
- 東京：安田記念；中山：皐月賞；中京：中京記念（个别年份换场，实施时核实当年举办场）；京都：天皇賞（春）；
- 阪神：103 阪神ジャンプS（已有线上闭环证据）；小倉：小倉記念。

proof 产物（页面 SHA、解析结果、逐场校验明细）归档进 release 证据目录，其摘要即新 policy 的 `proof_digest`。网络访问低频只读、遵守既有 host budget。

### 3.4 激活脚本：按 9/22 模式新写，不是字面复用

独立审阅已确认 9/22 的 `activate-jra.py` 硬编码不可直接重跑：绑定旧 commit `26706602`、旧 policy SHA/路径、`import release_0079`、镜像 tag `umanewsbot:pr212-26706602`、"恰好一个已完成 0079 release"断言，以及"providers 不含 jra"的前置断言（当前生产已含 jra，原脚本必失败）。

因此本变更按同款模式新写激活脚本，要求：

- 绑定任务 1（T/F 归一 PR）与任务 2（换绑 PR）均合并部署之后的新 commit/镜像、新 policy 路径/SHA、当前实际 providers 集合；
- 意图文件逐字段独立审阅，新意图 SHA 冻结后执行；
- 服务器侧 `release_0079` 模块与运行态（`.env` 实际值、锁状态）无法从仓库核对，列为实施前只读核对项；
- 切换只改 `RACE_DATA_MULTISOURCE_POLICY_FILE/SHA256` 两项 + 必要的轮换动作；回滚为恢复 v1 policy 文件+SHA（已轮换的 enrollment 与新产生的登记不回滚，与 9/22 口径一致）。

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
| 激活窗口挤压 107 闭环 | 激活必须排在 107 正式赛果自然闭环（9/27 赛后）之后 |

## 5. 任务清单（含时间约束）

1. (integration) 归一规则追加 T/F 后缀 + 回归测试（RED→GREEN），独立 PR 合并并同 schema 发布。
2. (integration) 新增受审的 v2 换绑路径（3.1 对策段）+ 回归测试（含 binding digest 旧→新、identity 不变、非 enrolled/漂移不符即 fail closed），独立 PR 合并并同 schema 发布。
3. (integration) 定位 v1 `proof_digest` 的生成方式并记录；生成 v2 policy 草案（10 venue_aliases），离线校验 schema 与 venue 代码一致性。
4. (operations) 逐马场真实 proof 采集与离线解析校验，产出 proof_digest 与证据目录（任一马场失败则该马场移出本批并记录）。
5. (operations) 生产只读预检：当前登记/告警/预算基线；服务器 `release_0079` 模块与 `.env` 实际状态核对；新 policy 文件落盘与 SHA 绑定。
6. (operations) **时间约束：107（9/27）正式赛果自然闭环之后、108/109 seed 窗口打开（约 9/30）之前**，执行激活：新写激活脚本经独立审阅 → 排空 → 原子切换 policy → 立即执行 103–107 换绑（任务 2 的新路径）→ 旧 policy_id incident 收口。
7. (operations) 激活后观察：108/109（10/4）自然闭环 身份→登记→正式赛果→双域名公开；103–107 换绑后至少一次自然刷新成功；告警行为按 3.5 实测。
8. (application) 文档回写：current_state、deploy_runbook、handoff 第 4 节 P0 项状态更新。

**降级预案**：若任务 1–5 未能在 9/30 前全部就绪（含新激活脚本独立审阅），则 108/109 放弃作为验收样本，激活顺延到下一周赛事（10/10–12 的 110/111/112）之前；顺延期间 103–107 继续在 v1 policy 下正常运行，不做任何切换。

## 6. 完成标准（精确口径）

- 10 个马场各有至少一条真实 proof 通过解析合同（或明确记录某马场延后及原因）；proof_digest 与 policy SHA 绑定。
- 108 或 109 自然完成全流程（不手工触发业务任务、不固定 ID 回填），公网双域名赛果与官方一致；若按降级预案顺延，则以 110/111/112 中的自然闭环替代验收。
- 告警口径与代码一致：`enrollment_missing` 于 T−1 日开单；有 `race_datetime` 的已登记赛事 T+30 分钟无正式赛果开 `result_overdue`；无 `race_datetime` 的 T+1 日开 `time_unknown_overdue`；范围内漏管不被静默；旧 policy_id incident 无残留重复 open。
- 103–107 既有登记经新换绑路径迁移后持续自然刷新（checkpoint 成功、`binding_route_missing`=0），公开赛果行数不回退。
- 任一阶段失败可回到 v1 policy；已换绑登记与新登记不回滚。
