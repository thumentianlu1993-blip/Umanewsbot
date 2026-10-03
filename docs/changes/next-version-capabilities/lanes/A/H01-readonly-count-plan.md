# H01 / F06 有界只读取数方案（未执行）

本方案供root/原R审核；不包含生产查询收据。固定代码schema基线815，实际生产revision、数据库迁移、表结构与索引要先实时核对。预计Django app label=stable、默认schema=public、默认表名如下；实际不匹配时停止，不改schema、不跨库或换用未经批准数据源。

## 表、必要字段与用途

`id/created_at/updated_at` 为各TimestampedModel公共字段。只读取下列字段或外键id；不读取整张表、账户字段、review notes、新闻正文、raw_payload、完整source_refs或含token的URL。

| 预计固定表 | 必要字段（除公共字段） | 用途 |
|---|---|---|
| public.stable_raceevent | country_region,local_date,timezone_name,normalized_grade,grade_text,status,visibility_status,series_key,source_refs受控等级证据片段 | 九地区/时间/等级赛事范围、缺日期/来源统计；grade_text用于待核而非自动等级识别 |
| public.stable_raceeventproductcanonicallink | duplicate_event_id,canonical_event_id,is_active | 需核实际字段后canonical映射；不由重复名称去重 |
| public.stable_raceeventprojectioncontrol | event_id,current_racecard_revision_id,current_result_revision_id | 生效版本起点，不猜max revision |
| public.stable_raceeventrevision | event_id,kind,revision_no,phase,content_sha256,supersedes_id,published_at,conflict_status | 固定生效/更正/冲突；不导出decision_reason/applied_by |
| public.stable_raceeventrevisionpublication | revision_id,published_at,registry_digest,coverage_proof_digest,authorization_kind | 公开版本证据引用；不等于来源当前许可 |
| public.stable_raceeventrevisionitem | revision_id,participant_id,source_order,horse_number,status | 全参与项及出赛状态；首轮计数不取骑师等资料 |
| public.stable_raceeventparticipant | event_id,stable_key,horse_profile_id,country_region,review_status | 未建档target和参与项引用；birth_year不参与窗口 |
| public.stable_raceeventparticipantsourceidentity | participant_id,source_identity_id,external_runner_id | 赛事内来源参赛项桥接，不能当全球horse ID |
| public.stable_raceresultsourceidentity | event_id,source_key,region_code,identity_namespace,external_race_id,review_status,registry_digest,valid_until | 来源赛事枚举与缺来源；canonical_url/identity_fields仅提取无敏感的稳定horse键路径（若有），默认不导出 |
| public.stable_raceeventrunner | event_id,external_runner_id,horse_number,running_status,source_refs白名单horse身份键 | legacy全报名列表；raw_payload首轮禁止 |
| public.stable_raceeventresult | event_id,horse_number,running_status,is_confirmed,source_refs白名单horse身份键 | legacy全结果/非完赛；不只取finish_position=1 |
| public.stable_horseracerecord | horse_profile_id,event_id,race_date,race_date_precision,race_region,start_status,result_status,canonical_race_key,idempotency_key,source_name | exact实际参赛补充/去重；仅目标关联和范围内有证据记录 |
| public.stable_horseexternalidentity | horse_profile_id,source,namespace,external_id,status,payload_sha256,verified_at,rejected_at | 强身份/撤销/冲突；不取verified_by、notes或evidence_url |
| public.stable_horseprofile | primary_term_id,racing_region,review_status,completeness_status,published_at,hidden_at,manual_lock_flags白名单,career_history_status,official_or_source_start_count | 已建档及公开状态层；不能作为全集入口 |
| public.stable_horsep0source | profile_id,race_event_id,race_runner_id,race_result_id,source_type,status,participant_key,observed_at,revoked_at | 旧目标与来源状态对照；不调用sync/apply |
| public.stable_externalhorse | source,horse_id,fetched_at,last_seen_at | staging稳定source ID存在性；不因名称相似判matched |
| public.stable_articlehorselink | horse_profile_id,article_id,status | 新闻优先关系；仅auto/manual认可关系，候选另列 |
| public.stable_newsarticle | racing_region,published_at,published_to_web_at,withdrawn_at,duplicate_of_id | 90天认可新闻优先级，不读取title/body/账户信息 |
| public.stable_racedatasnapshotlease | cache_key,state,artifact_sha256,manifest_data受控schema/source范围片段 | 共享快照存在性；owner_token禁止读取，lease不等于持久缓存内容完整 |

模型字段白名单须通过本地AST及生产信息schema双重核对。cache还包括既有filesystem source manifest：首轮只读被root确认的目录与manifest条目的schema/source-key/内容SHA/字节数，不遍历未知宿主路径，不读取原文/秘密。无法确认cache路径/当前有效manifest时 cache覆盖保持unknown，不能从staging倒推缓存。

## 查询和资源预算（工程建议，待审核冻结）

首轮是F06容量预检，不是完整目标冻结：单个显式 `REPEATABLE READ READ ONLY` 会话，固定 `transaction_timestamp()` 和数据库snapshot；`statement_timeout=5000ms`、`lock_timeout=250ms`、`idle_in_transaction_session_timeout=5000ms`，整体最长120秒，最多24条SELECT、无并发、结果总量最多500条聚合/状态行和2 MiB。不执行EXPLAIN ANALYZE、建临时表、导入Django任务、写入租约或扩大权限。超时/缺字段/预算耗尽立即结束，会话回滚，输出partial及已执行条数，不盲重试。

1. Q01：在信息schema/pg_catalog核public schema内19个列明表、仅所需字段/主键/现有索引；只做存在性聚合，输出最多19行。不得复制环境连接串或从错误中输出密码。Q02：固定snapshot时间/生产revision/schema版本引用与截止条件；实际部署与schema不匹配停止。
2. Q03–Q10：分地区窗口、等级、缺日期/名单/当前revision、versioned参与项、legacy runner/result、exact实际出赛record、已verified/未解/冲突身份做有界聚合。数据很多时数据库按已存在索引与日期/事件条件执行；timeout限定实际扫描成本，不声称SELECT/COUNT天然低成本。每个CTE预先列明范围和行数上限，不能扫描全HorseProfile、staging或新闻正文。
3. Q11–Q18：只关联前面有界目标的profile/source/staging/新闻关系做分层状态计数；限定对应窗口与target IDs，不从全档案循环N+1。JOIN可能膨胀必须先按稳定参与项/目标ID去重，保留raw与distinct两计数。read_limit截断则该统计partial，不能拿DISTINCT名字算真马数。
4. Q19–Q22：核旧P0目标差集、未建档数、无来源/无人数事件及地区缺口；cache metadata白名单。Q23–Q24保留为查询异常诊断预算；不是自动重试配额。每条输出执行编号/模板SHA/参数hash/耗时/行数/是否截断，原始SQL结果不直接输出终端。

源项读取若必须流式才能强身份去重：另一个独立获准只读切片提案，单连接同snapshot、keyset而非OFFSET、500行/页，初版最多40页/20,000参与项、20 MiB及120秒；只导出规范化必要字段到专属私有artifact，起点/终点/完整性和摘要固定。容量预检未证明量级前不承诺此预算足够。任何上限触发均partial；需要更大读取预算由root评估，禁止用局部抽样冒充完整分母。

跨会话水位/updated_at不保存旧值，不能独自保证复算。正式冻结必须保存完整必要输入的不可变脱敏snapshot + SHA、来源manifest和policy/version；新增/更正另存delta。不能在120秒预算用完后留长期MVCC snapshot或后台游标持续占用生产资源。

## 脱敏输出与未知

对root/F06输出只含参数/时点/revision/schema摘要、九地区计数、status/分层计数、未解/冲突组数量、未知人数事件、截断与耗时、容量结论。源ID/事件/参与项ID如需审计关联，使用固定本次snapshot的受控映射或带私有盐的摘要；盐只存私有runtime、不入repo/报告。不输出马主/用户、Cookie、token、完整URL query、新闻正文、账户信息。公开马名可在后续本地验收数据使用，但首轮容量报告只需计数。

尚未知：真实生产表/索引和revision语义、一等爱尔兰/legacy other映射、九地区完整枚举人数、cache位置与完整性、当前源权限/额度、missing roster可取性、真实耗时/吞吐。旧批次统计与A00417个候选键不能填本卡真实数量。取数结果由root固定后原R审核；方案落盘、SELECT成功或HTTP200都不意味着目标已补齐/公开。
