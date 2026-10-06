# A033：H03 履历首片——已有赛绩补连已有赛事

任务 `A033-H03-CAREER-FIRST-SLICE-PLAN-001`，固定已审base `e775ad2deb9ce94b1c9f2dbc2cb52d2ba32b27a0`。当前A树clean、A032已交原R批准/C033装配（状态来自ROOT任务卡）；本轮仅代码只读和本A方案，未执行DB/业务测试/producer/network或占PG窗口。目标是一个可用的局部接入点，不重建履历pipeline；当前指令覆盖只读方案范围，不触发G2/G3。

## 现有调用流与实际缺口

- `p0_horse_completion_adapters.normalize_p0_horse_race_records`（772）做已有履历归一、started/nonstart和来源总数对齐；原cache HKJC例中PU为started、WV为nonstart，不得计成两次出赛。`p0_horse_profiles.apply_reviewed_completion_artifact`（3058）在真实reviewed/模块审核后逐条调用共享writer，不可给H02自动候选伪造review。
- `horse_profiles.apply_data_candidate`的RACE_RECORD分支逐条调用`upsert_race_record`，但没有本片需要的锁后强身份/版本验证，也不复核RACE_RECORD module锁，不能直接当安全入口；不改此共享函数。
- `horse_race_records.upsert_race_record`（1049）复用source idempotency（222）、canonical（110）、resolve（478）、跨来源保守等价（383）；`record=`显式编辑分支保护原raw_payload/source_refs，并拒另一记录占用同source/canonical identity。关联后会重算既有normalization及career派生计数。**去重/补连算法本身已有，无需重写**。
- `test_p0_horse_career_history`已有跨源保守合并、不同distance/surface/race number/event不合并、未关联记录后续补连（533）和nonstart等测试；这些直接writer测试不覆盖H02可信原件→锁后已有profile/赛绩/赛事绑定→版本审计、人工模块锁、原请求旧baseline重投及日志失败整体回滚。旧补连例只检查result属于event，没有证明result属于此horse，因此本片明确不接受/写result_id。

## 唯一推荐最小片

新增薄入口 `horse_career_record_link_from_cache.py`：**一个HKJC原件＋一个H02 reusable候选＋一个已存在未公开强身份profile＋一个已有未关联HorseRaceRecord＋一个已有RaceEvent/已审RaceResultSourceIdentity**。只补record.event_id与共享writer所需canonical key/normalization元数据、profile career派生计数，条数不增不删；不新建马/赛绩/赛事/赛果，不写result_id、成绩事实、主胜鞍、中文/术语、公开状态或来源总数/authority验证标记。普通未进日历履历继续独立存在，不造空赛事页。fixture中可预建明确合成模型，绝不称真实赛事/结果基线。

1. 输入沿A032的可信H01/H02候选、原bytes/独立expectedSHA、版本/as_of/TTL/本地actor；另显式给selected_row_sha、record_pk、source_identity_pk、event_pk、固定binding SHA及profile/record新写入预期baseline。再次adapter→H02复算并逐字段规范摘要相等，单cache scope且reusable；从原件完整career只选择精确行摘要，不用名字、数组位置或相似度选行。行必须有稳定provider external_race_id、同一external_horse_id、精确日期、显式venue_key/race_number，不能从示例URL或race_name猜这些身份。缺任一项即保持未关联并blocked；其余career行不消费。
2. 复用既有normalizer得选中行的实际start/result事实；首片只选有完整事实的started（可PU），nonstart/未知/年精度不补连，数量和来源总数仍由旧合同处理。cache不能自带event/result ID要求直写；拒result_id和越界字段。现有HKJC合成原件只有事实及示例URL，缺上述强赛事字段；下一片需独立合成副本明确增加这些字段并标合成，不改旧fixture，不拿hash当认证。
3. 外层atomic，先锁profile，确认DRAFT/READY、hidden_at空、current verified keys/H01强身份同namespace一致，复用A032已审身份核验。随后对指定record/event/source identity按固定顺序取行锁，子资源使用nowait、忙则整片退出；同profile第二请求仍在profile锁等待。不要声称其他旧writer都遵守此锁合同。赛绩必须属于此profile、来源HKJC、外部race identity精确一致、event/result均空或event已是本次目标（重投），source原件/事实指纹一致；人工RACE_RECORD module锁阻止新写入，原人工/受保护来源不接管。
4. 赛事绑定只读既有`RaceResultSourceIdentity`：route source_key/region_code/identity_namespace/external_race_id与绑定输入/行完全一致，指向本次event；读取既有已审identity_fields.multisource_v2的operator/venue_key/local_date/race_number，与行精确相符且绑定SHA未漂移，当前review/terms与证据仍许可此次离线用途。缺这种已审合同就blocked，不创建身份或开启automation/proof_network。event.local_date/地区/确定性场地文本与行一致，首片仅`year == edition_year == race_date.year`；跨年届次即使别处支持也暂不接，不用年份代替赛事身份。同日同场不同race_number/provider race ID、同名跨届或多个绑定都拒绝/不合并；不调用source resolver的名字fallback。
5. 安全检查后先查同profile/RACE_RECORD/固定H03来源角色的H02消费key：同key同完整输入摘要且APPLIED返回already_applied、record/profile/candidate/log/normalized_at零写；同key异绑定/行/摘要拒绝。只有未消费新key才核profile/record baseline。首片每profile/entity_version只消费一个选定record；另一个record需新实体版本，不悄悄扩批。已关联同目标的未消费输入可留一次无变化审计，跳过writer，避免`_normalize_race_record`和career refresh本来每次会推进时间；不因重投改normalized_at。
6. 将锁后record的**全部现有writer管理字段**完整投影，保持全部成绩/source字段原值，只替换event_id；不能只传event而被`_race_record_values`默认空值清字段。严格核源行事实与既有record一致，不用源行覆盖人工改值。调用共享`upsert_race_record(profile, payload, record=locked_record)`，保留原raw/source refs和原external idempotency key；unique/旧歧义直接拒绝。直接用这个已存在writer而非无record参数的generic candidate apply，保证不会新建行。`_normalize_race_record`会吞异常写issues，不能将“无异常返回”视为成功：首片要求旧normalization无issue，写后检查新增issues/关联/数量/事实保护，失败整片回滚。
7. 既有HorseProfileDataCandidate保存RACE_RECORD单项审计（JSON-safe日期diff、原件SHA/旧source_time/H01证据/绑定SHA/版本、before→after及result），本地actor/默认confidence0，不造人工review/已核来源标签。writer、候选APPLIED、日志全部在外层atomic；任何save/upsert/后验/log失败无孤儿、无半关联。来源总数/authority不从本行升级，profile派生状态由既有refresh重算，不能用它宣称全career/full-profile完成。输出applied/already_applied/blocked、record ID/link diff、派生计数及published=false；不调用发布/QQ。

## 下一片3–5个真实RED断言（本轮未运行）

| 断言 | 实际业务失败/mutation |
| --- | --- |
| 单行已有赛绩补连后仍同PK/同条数，source idempotency/raw/source refs/成绩不变，linked+1/unlinked-1，来源总数/authority/公开与术语不动 | 缺最小入口时实际关联仍空；误create重复、空值投影清字段、错升级完整/公开 |
| 首次实际补连后，以完整原请求及原profile/record baseline重投already_applied；candidate/log各一次、normalized_at/profile updated_at不再变 | baseline优先误拒、重复writer/normalization/audit；同key换event/行摘要必须拒绝 |
| 同名不同届次/同日场地另一场次/相同race ID但绑定漂移/缺稳定ID/强马身份漂移/人工module锁/public/hidden拒绝，所有行和候选日志零写 | 名称fallback、年份替身份、遗漏race_number/强身份/锁或赛事绑定权限 |
| upsert实际改record/profile派生后注入候选或log失败，所有赛绩/计数/audit整片回滚；已有唯一键歧义不任选 | 缺外层事务、半关联/孤儿、吞normalization issues冒成功 |
| 隔离PG同profile两完整相同请求，观察真实Lock及blocking PID，第一位提交、第二位already_applied，一次消费 | 缺锁/版本去重；资源忙/漂移须fail closed。SQLite不作并发证据 |

最小RED须由正常导入/签名的无写占位入口导致“record.event_id仍空”的业务断言失败，不能以缺模块/环境错误冒RED；由ROOT审核后分配既有官方隔离PG窗口，本轮无资源请求/执行。既有writer/源归一能力若定向基线已满足就报告无需改，新增仅此可信接入/审计边界。

## ownership、依赖与停止

下一片只新service、独立tests/合成fixture、A报告；不改A032 helper/shared models/settings/views/migration/catalog/B翻译/C集成，不新增framework。需要通用metadata/真实源身份合同或shared schema才能落地时交ROOT，不把合成fixture“approved”变成真实授权。首片无法处理真实HKJC缺稳定race字段、跨年届次、result马归属、全量新增赛绩/跨源更正/撤销、全career覆盖与生产并发；这些明确后续依赖。候选audit薄接缝不是第二套赛绩writer；已有唯一约束和共享upsert继续权威。

本轮只报告与runtime代码hash封存，文档静态/diff检查；没有DB、业务测试、Docker、PG分配或生产/真实源/付费/发布/权限变化，不标实现。固定计划交ROOT→原R快速审核后停，RED/实现另卡。周额度起11%已用、89%剩余。
