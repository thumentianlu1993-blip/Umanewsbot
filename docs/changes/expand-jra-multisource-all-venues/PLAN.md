# 计划：JRA 多来源登记扩展至全部 10 个中央马场

> 状态：计划草案，待独立审阅与用户批准。未实施、未改生产。

## 1. 背景与当前真实状态（2026-09-26 核验）

- 生产运行 PR216 合并提交 `c71dcdfc`，schema 0079；多来源登记（PR212）已上线，JRA route 真实启用。
- 当前 multisource policy（`jra-official-results-20260922-v1`，SHA `d28a690b…f993`）只覆盖：
  - provider `jra` / region `japan_jra` / capabilities `["result"]`；
  - `venue_aliases` 仅 `hanshin`（阪神）与 `nakayama`（中山）；
  - 有效期至 `2026-10-21T17:14:43Z`。
- 已完成自然闭环证据：103/104/105（9/22）与 106/107（9/26）均走完 身份→登记→正式赛果→公网。
- 赛前 seed 路径（`discover_jra_pre_race`）本身覆盖全部 10 个 JRA 马场（`JRA_COURSES`），CNAME 解析表 `_JRA_VENUE_CODES` 也已内置 01–10 全部马场代码；瓶颈只在 policy 的 venue 范围。
- 名称匹配已上线确定性归一（PR216）：等级前缀 + `ステークス→S`／`カップ→C`。已知剩余系统性差异为 JRA 官方缩写 `T=トロフィー`、`F=フィリーズ`。
- 当前后果：下周末 108 毎日王冠（10/4 東京）、109 京都大賞典（10/4 京都）等政策外赛事会赛前有出马表预览、但不登记、不闭环正式赛果，且因分类为范围外而不产生覆盖告警。

## 2. 目标与非目标

**目标**

- JRA 官方 result 路线的登记/赛果闭环覆盖全部 10 个中央马场（札幌、函館、福島、新潟、東京、中山、中京、京都、阪神、小倉）。
- 覆盖告警（`enrollment_missing`）对该范围生效，未登记不再静默。
- 用 108/109（10/4）作为首个自然闭环验收样本。

**非目标**

- 不改变 NAR/地方、海外（TRA/Sporting Life/ZEturf/HRN/RP/ATR）任何路线与范围。
- 不修改 v1 census standing policy；不动旧 `race_live=7543` 队列。
- 不放宽强身份规则：身份仍由 CNAME 结构 + 页头一致性 + venue 别名单一命中证明，名称相似度不用于合并。
- 不承诺 D-30 等 provider 不支持的窗口；结果能力仍以官方结果页发布后为准。

## 3. 设计

### 3.1 policy 扩版（核心变更）

新建 policy `jra-official-results-2026-v2`（schema_version 3 不变），相对 v1 的 diff 仅为：

- `venue_aliases` 扩为 10 个马场，key 用英文小写（`sapporo/hakodate/fukushima/niigata/tokyo/nakayama/chukyo/kyoto/hanshin/kokura`），每个含日文名与英文名，与 `_JRA_VENUE_CODES`（adapters :257-268）逐码一致；
- 新 `policy_id`、新有效期（建议自激活起 30 天）；
- `proof_digest` 必须重新生成（见 3.3），不允许沿用 v1 的 proof；
- `contract_digest`、`parser_version=jra-cname-v2`、hosts/path 前缀、tiebreak_order 等不变。

发布动作：新 policy 文件落盘到持久 runtime（`/opt/umanewsbot-persistent/runtime/race_data_sync/multisource/`），更新 `RACE_DATA_MULTISOURCE_POLICY_FILE/SHA256` 两个环境值，按 9/22 已审核的激活脚本同款流程（意图 SHA 绑定 + 排空 + 原子切换 + 可回滚到 v1 policy）执行。无代码镜像变更、无迁移。

### 3.2 名称归一补齐 T/F（代码小改，随本变更走正常 PR）

`normalize_jra_race_name` 的长后缀表追加 `('トロフィー','T')`、`('フィリーズ','F')`。这是 JRA 官方四个固定缩写字母的完整集合（S/C/T/F），规则仍确定性、歧义 fail closed。回归测试复用 9/26 的测试类扩展：111 `アイルランドT`↔`アイルランドトロフィー`、138 `阪神ジュベナイルF`↔`阪神ジュベナイルフィリーズ` 双向用例，外加不同名拒绝用例。101/111/138 已按用户授权手工补的别名继续保留（幂等、双保险）。

### 3.3 逐马场真实来源 proof（激活前置）

对 10 个马场各取一场 2026 年已完赛 G 级赛的真实官方结果页（accessS），离线执行 `parse_jra_observation` 合同校验：CNAME 马场代码 ↔ 页头回数/马场名/日期/赛事编号一致、venue 别名单一命中、名单/赛果结构完整。建议锚点（已开赛、页面仍可访问）：

- 札幌：札幌記念；函館：函館記念；福島：七夕賞；新潟：新潟記念；
- 東京：安田記念；中山：皐月賞；中京：中京記念；京都：天皇賞（春）；
- 阪神：103 阪神ジャンプS（已有线上闭环证据）；小倉：小倉記念。

proof 产物（页面 SHA、解析结果、逐场校验明细）归档进 release 证据目录，其摘要即新 policy 的 `proof_digest`。网络访问低频只读、遵守既有 host budget。

### 3.4 覆盖告警与预算

- 扩版后 `build_multisource_coverage` 的分类范围扩大到全部 10 马场：政策内未登记将产生 `enrollment_missing` 内部 incident（与 106/107 的 22/23 同款）。需要在激活前确认告警仅内部记录、不外发（沿用 9/22 口径）。
- 请求预算不变（512 请求/来源/地区/日、1GiB/日）；10 马场全天赛事的出马表+结果页请求量远低于上限，但激活报告需给出实测值。

## 4. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 某马场页头结构与阪神/中山样本不同 | 3.3 逐马场 proof 先行，任一马场不过则不激活该马场（venue 可分批入 policy） |
| 名称差异超出 S/C/T/F 与等级前缀（如赞助前缀） | 仍 fail closed 到 `jra_race_identity_no_match`；按 9/26 Track A 同款 SHA 绑定别名修复，不为消缺放宽匹配 |
| policy 到期 | 新有效期 30 天；到期前按同流程续期，proof 复用需重新核验页面可解析 |
| 激活后回退 | 恢复原 policy 文件+SHA 即回滚；已产生的登记/赛果不回滚（与 9/22 口径一致） |
| 测试替身代替真实页 | proof 必须来自真实页面字节，SHA 入档；离线重放必须字节不变 |

## 5. 任务清单

1. (integration) 归一规则追加 T/F 后缀 + 回归测试（RED→GREEN），独立 PR 合并并同 schema 发布。
2. (integration) 生成 v2 policy 草案（10 venue_aliases），离线校验 schema 与 venue 代码一致性。
3. (operations) 逐马场真实 proof 采集与离线解析校验，产出 proof_digest 与证据目录。
4. (operations) 生产只读预检：当前登记/告警/预算基线；新 policy 文件落盘与 SHA 绑定。
5. (operations) 按 9/22 激活模式执行切换（意图 SHA、排空、原子切换、四应用配置一致性核验、可回滚点）。
6. (operations) 激活后观察：108/109（10/4）自然闭环 身份→登记→正式赛果→双域名公开；既有 103–107 不回退；覆盖告警对范围外分类正确、范围内漏管会开单。
7. (application) 文档回写：current_state、deploy_runbook、handoff 第 4 节 P0 项状态更新。

## 6. 完成标准

- 10 个马场各有至少一条真实 proof 通过解析合同；proof_digest 与 policy SHA 绑定。
- 108 或 109 自然完成全流程（不手工触发业务任务、不固定 ID 回填），公网双域名赛果与官方一致。
- 范围内任意已开赛未登记赛事在 T+30 产生内部 incident；无 incident 被误发外部渠道。
- 任一阶段失败可回到 v1 policy 且既有登记/公开不回退。
- 103–107 既有公开内容与登记数不变（除自然刷新外）。
