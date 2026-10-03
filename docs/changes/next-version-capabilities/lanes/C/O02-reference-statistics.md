# O02 第二轮：真实引用、语义差异与碰撞诊断设计（未执行）

## 绑定与采集状态

root在2026-10-03 19:52:18+08执行Q1–Q4；metadata收据SHA0b60dc3ffe0092e714e65a894a9d9b56fb72e747b0e0231bcf877b5123f8e14d，本线已核digest和21条FK完整定义。19:53:32+08 Q5/Q6 heap byte重复收据SHA5b0f57e98b0d1481ff56a4ae436a8be1c134acedaf74c070395b6688c9694fc3，同样已核digest。新闻8组47行、术语226组558行是该snapshot的观察，不保证后续集合不变。索引valid不能推翻heap重复，byte重复不能单独定位损坏原因。

本线只新增O02文档。下一轮由root分配资源、执行只读连接；本稿未PG语法实跑，不宣称引用计数/语义比较/碰撞已通过。所有ID集合和单行digest保留root私有目录，聊天只回总计、差异布尔和收据digest。禁止SELECT正文、source key、OperationLog.detail/用户信息。

## 私有重复组映射：先确定统计对象，不选保留者

root仍需形成私有article_group_map / term_group_map，每行old_id正整数及group_no独立整数（不同实体空间）。同一ID不得重复/跨组，一个组必须完整覆盖同byte键全部成员。仅为统计分组，不包含keeper/survivor；用min(id)排序只供确定分页顺序，不是保留者选择。

采用与Q5/Q6相同forced heap + MATERIALIZED byte键，携带id，GROUP BY byte键 HAVING count(*)>1，array_agg(id ORDER BY id)仅存私有。按min(id) keyset分页每次最多20完整组；最多200 IDs/批。若超过200，root明确缩小组数重新设计批次；不能静默丢行/拆组。任何组>200、组范围变化/重复分页/预算超时均停并报告。新闻8组可一批；术语226组必须多批，但不据旧count自动无限循环。

每个连接仍3s statement/250ms lock/5s idle，RR read-only、parallel0/work4MB/temp16MB；一次最多6SELECT，工具总30s，batch完成ROLLBACK/close。两表key枚举不得用已知异常unique索引。实际count/group集合与Q5/Q6不一致时保存时点差异，不冒称根因变化。跨批snapshot不能提供事务一致性全图，最终守恒和manifest绑定在隔离固定副本重做。

## 实际21条FK计数

O02-reference-query-design.json逐条从已核Q4约束定义生成精确public表/列、参数映射类型与SELECT模板，无字符串拼接任意对象。所有21条是单列指向id，DB NO ACTION且DEFERRABLE INITIALLY DEFERRED；Django CASCADE/SET_NULL另属应用删除语义，两者不能混称。

每条输入私有JSON数组[{old_id,group_no}]，先在root内存校验正整数、类型、唯一性、完整组、≤200 IDs/≤20组，再psycopg绑定%s::jsonb。读取匹配子行最多50001，聚合各组引用行数、已引用父ID数量、capped；0引用组显式输出0。达到50001时全批视为截断，不用截断计数做守恒。无输出子内容或原parent ID。生产诊断默认强制heap并EXPLAIN非ANALYZE记录源表Scan计划；超过3s只记unknown，不转索引结果冒称完整。根因检查之外不使用长snapshot或重建索引。

新闻19条覆盖articlehorse/race link、automationlog、两headline表、mediaasset、newsarticle duplicate_of、relatedregion、image/snapshot、pushlog/qqdelivery、racefieldauthority/change、racenewsexposure、termcandidateevidence.article、translationrun及两windowdecision。术语2条为termcandidate self merged_into_candidate与evidence.candidate。行数为直接引用分母，不能证明传递引用/非FK完整或内容可合并。

## 辅助catalog：确认碰撞规则及outgoing引用

先对上述已核source_table集合和两父表取实际所有unique index定义（pg_index indisunique、indisvalid/ready、indkey/indcollation/indclass、pg_get_indexdef、pg_get_expr(indexprs/indpred,indrelid)）；取pg_attribute名称/类型与outgoing FK定义。表集合由固定JSON表名绑定ANY(text[])，不扫描业务正文。最多100 schema行预算；超过时私有保存完整元数据并标界限，不能LIMIT后声称全部。这些辅助catalog未采集，不从静态约束推断所有真实unique。

至少已见7类可能重指碰撞：article race(event)、horse(horse_profile)、relatedregion(region)、QQ delivery(target)、window candidate(window)、term evidence(candidate/article两维)、race exposure(event/channel/scope_key)。RaceNewsExposure还有依状态/channel的席位partial unique，WindowTargetDecision的decision_key是另一个非article唯一维度；规则改变status/decision_key会另触约束，必须保持，不因父引用“合一”视为等价。

仅在实际catalog列/规则一致后，逐表以map.group_no替代被重指的父ID，保留该唯一键其它列，GROUP BY逻辑键 HAVING count(*)>1；只输出碰撞键组数/涉及行数/max，不输出target/scope或业务文本。map只表示等价提案组，不指定keeper，因此这是潜在碰撞检测，不能宣称所有组最终允许合并。

模板（race link，参数同article map）如下，其它表根据真实catalog生成，禁止通用任意列模板绕过条件/NULL语义：

```sql
WITH map AS MATERIALIZED (
 SELECT old_id,group_no FROM jsonb_to_recordset(%s::jsonb)
 AS x(old_id bigint,group_no integer)
), matched AS MATERIALIZED (
 SELECT m.group_no,c.event_id FROM public.stable_articleracelink c
 JOIN map m ON m.old_id=c.article_id LIMIT 50001
), clashes AS (
 SELECT count(*) AS n FROM matched GROUP BY group_no,event_id HAVING count(*)>1
)
SELECT count(*) AS collision_groups,coalesce(sum(n),0) AS involved_rows,
       coalesce(max(n),0) AS max_rows,
       (SELECT count(*)>=50001 FROM matched) AS capped FROM clashes;
```

TermCandidateEvidence需同时考虑article map和term map；不在map的父ID保留为原ID，与group_no使用不同类型前缀/结构区分（禁止数值碰撞）。两维一起投影后检查(candidate_bucket,article_bucket)，再检查仅单实体投影，以定位冲突来源。复合/partial/表达式/nulls-not-distinct索引必须逐条按真实定义检测；未知规则阻断方案。

## 语义字段digest与差异布尔

在受限map JOIN父行后，数据库内计算sha256(convert_to(jsonb_build_object(...字段...)::text,'UTF8'))，可按group_no count(DISTINCT bytea digest)>1输出差异布尔；root私有保留单行id/完整to_jsonb行SHA256用于前置条件，不返回原文。缺失父行以map LEFT JOIN显式计数，不能inner join丢对象当全部相同。字节digest只证明字段一致性/漂移，不证明来源内容正确。

新闻分层字段：来源身份/source_url/source_mode/source_language；title/body原文及中文/rewrite/translation内容；manually_edited_fields/attribution_locked/editor_notes；status/workflow/公开时间/withdrawn/slug/发布依据与decision JSON；duplicate_of/cover_media_asset/来源crawl引用。术语：type/language/normalized_key/source_ja及中译/aliases；status/review时间与notes/reviewed_by；accepted_term/merged_into_term/merged_into_candidate；evidence counters/时间/conflicts。任何人工/公开/审核目标差异均列为实质冲突，不自动用updated_at覆盖。

正文只在数据库内参与hash，TOAST读取可能耗时；每条≤200父行/20组、3s，同一批不过6SELECT。field-budget不够则标unknown，不能只比ID/状态便断言等价。完整row digest含数据时点、ID/时间等故组内不同是正常；必须另以分层字段digest做语义比较，不能以整行不同直接断言内容不同。

## 非FK与URL/审计保持

已查代码证据：OperationLog有target_type/target_id，article调用存在article和news_article两种type；术语为term_candidate。只统计精确文本target_id=old_id::text的已知type，字符串变体/其它type是未闭合项，不任意cast或全表模糊搜索。原audit object ID/detail保持历史可追溯，不批量改写append-only记录。

MultiregionAttributionRun.selectors.article_ids及completed_article_ids由attribution_runs/published_time_repair消费。以私有映射逐ID检查明确JSON路径是否含numeric ID；非数组/字符串ID/未知形态分别计unknown，不做递归jsonb_path任意扫描正文。JSON evidence/payload/artifact/TaskExecutionLog、缓存/Celery载荷仍需责任函数逐项定义ID语义和可保留策略；本批不窥队列参数、不调用业务重处理。

public_slug及NewsArticle.public_path/路由/canonical为公开身份引用；先root私有记录每个现有slug/path与公开资格digest，不发网络探针、不取新闻全文。若后续删除原ID会使旧URL不可达，需别名/保留档案等独立身份方案由root确认，不能本稿隐含决定301或公开撤销。媒体存储key与外部artifact也不属于FK守恒自动覆盖；先记录只读出处，再确定保全。

## 交接与停止点

root下一步先私有组映射与辅助catalog，再按预算分批计数/碰撞/分层差异；仅返回汇总、收据SHA及unknown列表。相等/计数结果不同于旧snapshot、任何新关系、partial unique、未知非FK消费者、人工内容或公开依据冲突均保留并报告，不扩成清理。所有引用与规则闭合前不生成生产apply；本稿没有数据写入/索引重建/恢复执行权限。
