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
- [x] 2.2 (integration) `_CLIENTS[japan]` 注册 dispatcher（netkeiba/JBIS 按 `request.candidate_source_name` 分发，`last_request_count` 代理；batch_limit 由 dispatcher 按日本地区统一执行 1× 上限并如实记录）；日本每候选预算 3→4（3 页 + 1 redirect 余量）。
- [x] 2.3 (integration) 同候选 netkeiba 与既有来源字段冲突时记冲突不覆盖。

## 3. 测试

- [x] 3.1 (integration) fixture 测试（使用已捕获真实页面 `netkeiba_horse_2022110137.html` / `netkeiba_result_2022110137.html` / `netkeiba_ped_2022110137.html`）：正常页全字段、同名马 ID 直取无歧义、马名不符 fail closed、括号国别后缀剥除、缺表/改版不可解析、通算与逐场不符进缺口、海外行、异常状态四档映射与非出赛不计数、年份生日阻断、障害距离前缀。
- [x] 3.2 (integration) adapter 层 JSON fixture（`source.name="netkeiba"` + provider-bound 通过）；select 偏好测试（netkeiba key 候选 → netkeiba namespace；仅 jbis key → 不变）；本地 sqlite 端到端 select → prepare（缓存）→ bundle → commit → 自动首发。

## 4. 验证与文档

- [x] 4.1 (operations) 本地验证矩阵（check、目标测试、完整 stable 回归基线对照、makemigrations --check、openspec validate --strict、git diff --check）。
- [x] 4.2 (operations) 独立 code review 修复全部 actionable finding；更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、`docs/decisions.md`；合并 main。

## 4A. 第二轮生产返修（2026-07-23）

- [x] 4.3 (integration) 测试先行：新增真实最小 fixture/回归，证明旧代码对 `抹消　牡　黒鹿毛` 标题失败；证明部分 expected identity 字段会列出缺失的候选期望字段并保持身份锁；对第 15 条履历只做 characterization 并保持 blocker，除非另有官方证据；锁定 parser version 变化会改变 adapter/candidate fingerprint，旧版 netkeiba canonical cache 强制 miss。
- [x] 4.4 (integration) 最小实现：标题状态、性别、毛色独立精确解析并支持 `抹消`；部分 expected identity 锁输出字段级、可解释 blocker 而非 `unexpected_adapter_error`；异常履历行只有在官方证据证明合法语义且先补期望 RED 测试后才增加显式规则，否则保持阻断。
- [x] 4.5 (integration) 新增显式 `NETKEIBA_PARSER_VERSION`，同时纳入 `adapter_config_fingerprint()` 与 netkeiba canonical source payload/cache guard；测试证明同版本稳定、版本变化失效旧 checkpoint、旧/错版本 netkeiba cache 强制 miss，并在网络刷新后通过 sidecar lock 原子替换、并发复用当前版本 payload，且不改变普通 no-clobber、JBIS/其他地区缓存语义。
- [x] 4.6 (operations) 验证：netkeiba 专项、P0 completion 套件、Django check、完整 stable 基线对照、迁移漂移、OpenSpec strict/all、diff check；更新状态与运行手册，记录 `27/100` 旧批证据、abandon/new batch 恢复规则与网络开关实测恢复。
- [x] 4.7 (operations) 独立 code review 清零 actionable finding并冻结受审代码版本；随后再取得绑定该精确版本的生产部署与触网 prepare 授权。

## 5. 生产执行（分步用户授权）

- [ ] 5.1 (operations) 取得受审精确版本授权后执行备份与部署，只验证代码 HEAD、镜像、Django check、容器/Nginx/healthz；默认保持 `ALLOW_NETWORK=false`，本步不触网、不写马匹资料。
- [ ] 5.2 (operations) 取得该版本触网授权后进入串行窗口：停相关 worker、开启并验证 `ALLOW_NETWORK=true`、保留并 abandon `p0batch-e5cee174ba05`、重新 select/approve 日本批次并 prepare 到 xlsx；验收 `unexpected_adapter_error=0`、已支持结构系统性 blocker=0，剩余失败字段级报告。本步不 bundle、不 commit、不自动公开；prepare 成功或异常后都必须立即在 finally 路径恢复并验证 `ALLOW_NETWORK=false`、启动 worker/beat/race_live_worker、检查容器 env/日志/healthz，不等待人工 xlsx 复审。
- [ ] 5.3 (operations) 用户人工复审 xlsx 后生成仅含通过完整子集的 bundle，冻结 bundle/release manifest SHA 与预计写入/自动首发清单；本步不写生产数据库、不公开。
- [ ] 5.4 (operations) 用户针对 5.3 的精确 bundle/hash、完整子集和自动首发范围重新授权后，执行 commit `--confirm-reviewed-artifact`，核验幂等复验、auto_first_publish、OperationLog、`/horses/?region=japan` 新马与徽章（闭环 `publish-p0-horses-basic-tier` task 7.2）。
- [ ] 5.5 (operations) commit/自动首发成功或中止后重复终验安全态：确认 `ALLOW_NETWORK=false`、worker/beat/race_live_worker 正常，容器 env、日志、healthz 与 `/horses/` 200。
- [ ] 5.6 (operations) 复核 netkeiba 访问条款与限速合规记录；状态文档更新、主规格同步与两个 change 的归档评估。
