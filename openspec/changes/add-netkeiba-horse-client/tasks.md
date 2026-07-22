## 0. Pre-declared hypotheses

- [x] 0.1 (operations) 实现前确认客户端选择策略：有 netkeiba key 的日本候选走 netkeiba 客户端，无 key 保持 JBIS 检索路径（用户 2026-07-22 已确认方向 1）。
- [x] 0.2 (operations) 实现前确认本 change 不批量修复 ExternalHorse 存量空四字段（仅随批次自然覆盖，批量修复另立专项）。
- [x] 0.3 (operations) 在更新 proposal 后执行 plan-eng-review，并将 review 结果写入 `.openspec.yaml`。

## 1. netkeiba 客户端

- [x] 1.1 (integration) 新增 `_NetkeibaClient`：allowed_hosts 仅 `db.netkeiba.com`；按候选 `netkeiba:{id}` 直取马匹页 + 战绩页 + 血统页（3 页/马）；无 key 候选 fail closed 回退；不做 netkeiba 失败中途回退 JBIS。
- [x] 1.2 (integration) 马匹页解析：`db_prof_table`（生年月日完整 ISO、調教師剥后缀、馬主、生産者、産地单字映射 country、獲得賞金、通算成績总数）+ 标题行性别/毛色；括号国别后缀剥除后写 `identity.horse_name`，原名与罗马字英文名进 aliases；马名不符 fail closed 进冲突。
- [x] 1.3 (integration) 血统页解析：`blood_table` 两代六字段（row0c0 父 / row0c1 父父 / row8c0 父母 / row16c0 母 / row16c1 母父 / row24c0 母母），剥国别标记/年份/毛色/`[血統]` 标记；任一缺失或出生日期仅年份 = 候选 fail closed 阻断。
- [x] 1.4 (integration) 战绩页解析：`db_h_race_results` 逐场（日期/開催/レース名原文/着順/騎手/馬番/斤量/距離原文/タイム）；异常状态 `取消→scratched`、`除外→withdrawn`、`中止→did_not_finish`、`失格→disqualified`；海外行判定（開催非 JRA 格式且非 NAR 名单）；通算成績与实际出赛数对账，不一致进缺口。
- [x] 1.5 (integration) 结构容错：预期表缺失或结构不识别一律 fail closed 记录不可解析，不猜字段。

## 2. adapter 与选择层接入

- [x] 2.1 (integration) select 阶段 namespace 偏好：日本候选持有 netkeiba key 时 `source_namespace` 优先 netkeiba（`p0_horse_completion_batch.py`），保证 manifest 携带 `candidate_source_name="netkeiba"` 与数字 ID。
- [x] 2.2 (integration) `_CLIENTS[japan]` 注册 dispatcher（netkeiba/JBIS 按 `request.candidate_source_name` 分发，`last_request_count` 代理；batch_limit 按子客户端实例计并如实记录）；日本每候选预算 3→4（3 页 + 1 redirect 余量）。
- [x] 2.3 (integration) 同候选 netkeiba 与既有来源字段冲突时记冲突不覆盖。

## 3. 测试

- [x] 3.1 (integration) fixture 测试（使用已捕获真实页面 `netkeiba_horse_2022110137.html` / `netkeiba_result_2022110137.html` / `netkeiba_ped_2022110137.html`）：正常页全字段、同名马 ID 直取无歧义、马名不符 fail closed、括号国别后缀剥除、缺表/改版不可解析、通算与逐场不符进缺口、海外行、异常状态四档映射与非出赛不计数、年份生日阻断、障害距离前缀。
- [x] 3.2 (integration) adapter 层 JSON fixture（`source.name="netkeiba"` + provider-bound 通过）；select 偏好测试（netkeiba key 候选 → netkeiba namespace；仅 jbis key → 不变）；本地 sqlite 端到端 select → prepare（缓存）→ bundle → commit → 自动首发。

## 4. 验证与文档

- [x] 4.1 (operations) 本地验证矩阵（check、目标测试、完整 stable 回归基线对照、makemigrations --check、openspec validate --strict、git diff --check）。
- [x] 4.2 (operations) 独立 code review 修复全部 actionable finding；更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、`docs/decisions.md`；合并 main。

## 5. 生产执行（分步用户授权）

- [ ] 5.1 (operations) 部署 → 首个日本滚动批次全链路（含 xlsx 人工复审）→ 核验批次自动首发（`publish-p0-horses-basic-tier` tasks 7.2 闭环）；部分期望字段候选的失败计数单独如实报告。
- [ ] 5.2 (operations) 复核 netkeiba 访问条款与限速合规记录；状态文档更新与归档评估。
