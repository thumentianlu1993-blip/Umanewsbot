# A031：H03 基础档案首片接入计划（不发布）

任务 A031-H03-FIRST-PUBLISH-SLICE-PLAN-001，base `87515c372ad43b8a731de05f4ccf3650b107e30c`。原R a1463050已通过A030；本轮仅A报告/runtime和现有代码只读定位，不执行producer/测试/数据库或改共享文件。其他线并行不覆盖；后台/QQ暂缓，A隔离资源选择仍不等于已批。名称含publish-slice的任务**本片只让本地已有未公开档案获得基础资料，不调用发布，不改公开页面**。

## 一个最小切片与执行顺序

推荐下一片新增 `horse_basic_profile_from_cache.py` 的单候选旁路：**一个HKJC原件、一个H02 reusable候选、一个已存在且未公开的HorseProfile**。不建立新马，不应用血统/别名/履历/主胜鞍，不更新中文名或术语。没有可信原件/来源授权或身份绑定时拒绝，不造reviewed/verified/confidence评分来绕既有门槛。

1. 调用方显式提供H02候选、可信固定H01输入、单份原bytes及独立expectedSHA/ref/source_ref、实体版本、as_of/TTL、目标profile预期updated_at和本地actor。expectedSHA/H01身份输入的可信来源必须明确；目前仅合成fixture可用，真实producer/授权/输入清单仍未知。
2. 新服务再次调用已审 `adapt_hkjc_source_cache`，避免信任外部自称parse_status=complete；重算 `plan_cache_reuse` 单原件下相应目标的候选，并逐字段/规范SHA与传入候选一致。首片只接受单cache_ref scope；多源组合留后续。只有reusable、entity_key=profile:<pk>且版本/idempotency_key/内容hash/来源/身份一致才继续；refresh/conflict/insufficient/候选篡改退出，无取数fallback。
3. 从原件 basic_profile 只取 country/sex/color/birth_date/owner_name/trainer_name/breeder_name七字段；birth_date先转date，按HorseProfile字段max_length及既有格式约束验证，不截断，不清空已存值。source来源时间/URL/hash/H01证据/实体版本只进入候选审计raw_payload，不写`horse_identity_verified_keys`，不把ingest时间当原件时间。
4. 外层 `transaction.atomic()`，按profile pk锁 `HorseProfile.select_for_update()`，锁后重读目标、状态、manual_lock_flags、source_refs及当前updated_at。此步暂不以expected_updated_at过时拒绝。只DRAFT/READY且hidden_at为空；PUBLISHED/HIDDEN/不存在拒绝，避免首片对已公开档案产生隐式公开更新。H01强身份还需与当前profile的**horse_identity_verified_keys**一致、同namespace无相矛盾ID；flat horse_identity_keys/名字匹配不够。存储旧强身份键采用现有enrichment的casefold规范，比较时沿既有规范且保留原ID证据，不修改adapter精确URL-ID规则或补写验证标记；规范歧义/冲突拒绝。局部受控fixture还需检查同一已核key没有另一profile命中。
5. 锁内查同profile、PROFILE模块、固定H03来源角色的历史候选 `raw_payload.h02_idempotency_key`。若已有APPLIED且input摘要相同，直接返回already_applied及既有结果，profile/candidate/log零写；首次成功导致updated_at推进不得阻断以原expected_updated_at完整重投的同一请求。同key异内容拒绝version_content_conflict，不因旧baseline而绕过摘要冲突。只有未消费的新key才严格检查expected_updated_at，陈旧则拒绝。版本为不透明token，不发明v1/v2字面排序；新key必须匹配锁后expected_updated_at基线，旧输入不能重取新基线自动覆盖。此去重仅保证新旁路自身串行调用，不声称约束全部旧写入者。
6. 复用 `horse_profiles.build_candidate_diff`，将date/datetime值严格转ISO等JSON原语，再用现有 `HorseProfileDataCandidate.objects.create(module=PROFILE, ...)` 保存一条候选（candidate_payload中的birth_date为ISO字符串）。通用save_data_candidate没有JSON-safe diff/date转换，不能直接假定它可存日期；此薄保存接缝留在新模块，不改共享函数。内存中的同一candidate在应用前把birth_date转date，随后 `apply_data_candidate(candidate, user=actor)` 在外层事务内应用。它只写BASIC_PROFILE_FIELDS并检查field锁和module PROFILE锁，重算现有completeness；候选标APPLIED及写操作日志。包外没有事务缝隙，任何验证/save/apply/log异常整片回滚。confidence沿既有save默认值0作为未给模型评分的审计值，是否能进入本旁路由确定性来源/身份/版本校验决定，不伪造“90分=已批准”。有锁字段允许其余字段应用、返回skipped_locked；全module锁同样不覆盖。已消费版本不因日后解锁偷偷重新应用，需明确新实体版本及新baseline。
7. 输出applied/already_applied/blocked、七字段before→after、locked清单、候选ID/输入摘要、旧来源时间，以及既有 `evaluate_basic_publish_gate` 的**只读eligibility/理由**。输出published=false且实际review_status不变。无中文名时沿已有HorseProfile.display_name对原名/TermEntry的回退，不自动造中文译名；命名为空只读gate仍可阻止发布。

## 为什么选这些既有函数

| 现有代码 | 复用/不直接使用的实际原因 |
| --- | --- |
| horse_profiles.save_data_candidate / build_candidate_diff / apply_data_candidate | 复用build_candidate_diff和apply的字段/模块保护、审计与completeness；save_data_candidate的JSONField日期diff不自动可序列化，因此新薄保存接缝做严格JSON安全化；apply本身无强身份/行锁/实体版本唯一保证，由新外层服务先校验和串行化 |
| horse_profile_completion._matches_for_profile / plan_profile_completion | 含名称fallback，不用于本片强身份决定 |
| horse_profile_completion.apply_completion_artifact | 接收通用rows及confidence、能直接覆盖字段且自身没有输入强身份/hash/版本去重；不直接喂H02候选 |
| p0_horse_profiles.apply_reviewed_completion_artifact | 依赖真实reviewed/reviewer/模块approval，含多模块/full-profile流程；不把自动H02候选伪装人工审核。_apply_profile_payload字段锁可参考，但不另外重造writer |
| p0_horse_identity_enrichment已核keys写入 / HorseIdentityEvidenceCommitReceipt | 说明现有identity provenance来源；本片读已核标记，不创建commit receipt/验证身份，合成fixture不冒生产证据 |
| horse_profile_publish.evaluate_basic_publish_gate / auto_publish_profiles | 前者可读；后者有事务重核/transition_review_status审计且旧gate可接受三字段分支，但本片绝不调用。H02强身份比旧gate更严，不拿eligibility替代发布授权 |
| horse_race_records.canonical_race_key / record_idempotency_key / upsert_race_record | 已有独立履历/来源合并与幂等，后续履历片复用；本片不调用且不删除旧记录。event为空/重复绑定/非出赛计数另测 |

## 事务、幂等与真实缺口

HorseProfileDataCandidate只有索引，没有(entity,version)唯一字段；首片无需新model/migration；候选payload/diff/raw审计全部JSON安全，应用用内存typed date且现有apply的update_fields只保存status/applied元数据，不将date重写入JSON。借现有profile行锁＋固定raw_payload审计键可串行化本旁路重复请求。profile被锁时再save/apply，不能像直接apply_data_candidate那样用锁前实例。同key异hash必须拒绝，任何失败不得留下PENDING孤儿。首次全部字段已相同也只消费一次输入版本并留一次候选，不能重复产生无变更审计。

SQLite可以演示本地业务保存/回滚/字段锁，不能证明select_for_update/并发；并发与JSON查询须在ROOT明确隔离PG测试窗口验证，当前不创建资源。其他旧身份写者可并发改变另一个profile或创建同key，JSON标记没有全局唯一约束；本片不声明全库身份写入线性化。真实推广前需当前可信H01生产输入与共享身份写入合同/数据库锁策略闭合，若必须新约束/共享文件，由ROOT安排，不能本片私改。外层actor只用于已有操作日志，不替代来源许可或人类审核。

## 关键测试与本地演示

下一片先RED再GREEN，独立合成HKJC原件＋独立expectedSHA、H01已核fixture、已有draft profile/TermEntry及本地actor，经过真实adapter→H02→既有candidate模型/字段diff/apply函数演示；禁止网络/producer/发布，隔离测试DB不可指向生产。

1. 七字段实际保存、birth_date正确类型及JSON audit ISO值（覆盖当前已有date与空date两种）、旧来源时间/hash进入audit、原名回退；profile/TermEntry身份及中文名、公开状态、verified_keys、race records、career模块不变。
2. field锁保留旧owner、PROFILE module锁不改基础字段；全字段相同重跑只一候选；首次真实改字段并推进updated_at后，以原expected_updated_at及其余完整同请求重投，必须already_applied且profile/candidate/log零写、仅一候选和一次审计；同version不同hash拒绝。另以未消费新key携带旧baseline，必须拒绝且零写，不得让旧输入自动获取新baseline覆盖。
3. hash/候选字段篡改、刷新/不足/身份冲突、profile verified key缺失或漂移、另profile同key、hidden/published/target不存在均不写；不从名字/旧三字段publish gate升级身份。
4. save/apply/操作日志失败注入，事务后profile/候选/log都回滚；失败不遗留待应用candidate，不自动补跑。PG窗口内同profile两个完整相同请求携带同一原expected_updated_at，第一位真实改字段提交后，等待行锁的第二位必须already_applied且零写，只消费一次并输出准确并发证据；没有PG只交有限SQLite状态，不造并发PASS。
5. 只读publish gate返回eligible或原因而不调用auto_publish/transition；用patch guard producer/network/QQ以及记录数/公开状态断言。中文名空可保留原名，资料部分更新不得冒full profile或career完整。

变异：移除锁/去重会重复候选；只比version不比摘要会接异内容；忽略baseline会旧覆盖新；忽略field/module锁会覆人工资料；只用flat键/name/gate会错绑；事务缩到候选应用内部会留下孤儿或日志不一致；调用发布/履历函数会超出首片范围。

## ownership与交接

下一片建议仅新 `horse_basic_profile_from_cache.py`、独立数据库测试及A报告/合成fixture，复用既有函数，不改shared models/views/settings/mapping、无migration；ROOT另集成catalog/如需PG窗口。真实producer/来源授权/当前身份全局并发仍待，不标H03全卡完成。现任务只有只读代码与计划，没有DB/测试/网络/producer/构建/生产执行，无allocation，额度起8；固定小方案交ROOT→原R后停止，不自动开始实现。无代理/模型CLI/积分/reset/push/PR/merge/deploy。

## A031-R01 局部修正记录

任务 `A031-R01-IDEMPOTENCY-ORDER-PLAN-REPAIR-001`，对应原R唯一P2 `A031-R01`。原固定方案 `3f05e754357dd1496655aec5551a7e67936840d2` 的第4步先拒旧baseline，会让第5步同输入重投无法成立；现仅澄清安全核验→已消费key/摘要→新key基线的顺序，并补首次实际变更后的原请求重投、并发第二位相同请求、新key旧baseline拒绝三断言。安全校验仍先于幂等返回；不扩大身份、公开或迁移范围。仅文档检查，不执行这些业务测试或DB，不创建新资源；修正固定后交同原R局部复审，未开始实现。额度本轮起9%已用、91%剩余。
