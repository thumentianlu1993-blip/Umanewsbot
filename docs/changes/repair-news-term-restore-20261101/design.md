# 隔离试修与恢复验证设计

## 1. 建议路径

先保留本轮只读基线，在第二份独立副本实现并验证确定性修复；不在诊断副本直接边试边删。副本中仅做本方案明列的主表合并及引用移交；同身份不同内容保留权威版本，其他版本完整归档。成功后重新dump，再到第三个空库完整恢复，作为进入后续完整Compose演练的前置条件。

数据规则依据[诊断](diagnosis.md)；代码依据为models.py的NewsArticle、TermCandidate、TermCandidateEvidence、WindowCandidateDecision、QQPushDelivery，以及term_discovery.aggregate_finding、term_candidate_review.merge_candidate、views.public_article_detail。现有merge_candidate仅标记关系，不改自然键，不适用于修复这两条唯一约束。

## 2. 不可执行预览到固定清单

现有预览仅表达候选映射。未来工具必须先只读生成计划，绑定固定代码、数据库身份、备份SHA、0079 schema、完整重复分母、每组所有主表/子表before SHA256、映射、字段策略和预计数量。范围漂移、未枚举入站关系、新状态或第三处约束异常均拒绝；不能自动把更多行加入既有清单。

先以全表顺序读取核验重复范围，不能信任可疑唯一索引的检索结果。所有ID映射按实体类型区分，包含规范键字节及行哈希；自然键不改写。实施时原始/目标同键组一致且目标ID在组内；禁止映射链、循环、跨类型/语言/来源合并。

## 3. 新闻规则

8组候选保留ID为6809、9649、9772、9783、9786、9797、16303、16517。选择理由逐组写入清单，不能实现成通用min(id)删除器。

- 9783优先级来自公开和sent证据、历史已批准正文修复；所有公开/内容/slug/时间/作者字段保持该行原值。它的QQ delivery#652原样保留，不生成投递、翻译或刷新任务。
- 其他组保持候选权威行的内容和workflow/automation/translation状态，不以新建时间、最高评分或更长正文覆盖；9786保持ignored，失败组不变pending。6809发布时间差异留档，不自动更正。
- 4组不同中文版本及9783的原文差异全部以完整before-image留档；完整旧行归档不限于冲突字段，亦保留来源方式、HTML、元数据、时间和指纹。
- NewsSnapshot、TranslationRun、AutomationLog等多对一历史行只移交FK，不去重历史发生次数；保留原行ID及其他字段，回执记录原article_id。媒体/事件/自引用本批为0，执行前仍重新扫描；出现未覆盖非零即中止重新计划。
- 原公开路径不变；历史后台/日志旧ID由修复清单追溯，不对OperationLog和历史JSON做全文替换，也不新增公开重定向机制。后续若出现多个已发布ID或已有对外旧路径，退出该批，单独设计路径兼容。

## 4. 术语规则

213组纯pending保留最早既有ID；405所在组保留405及rejected、reviewed_by/at/notes。该组其他pending不是恢复人工审核的授权。所有正式术语外键必须仍为空，中文名/别名仍为空且原文逐组相同，否则本规则不适用。

移交全部证据。候选时间采用first_seen最小、last_seen最大；created_at保留权威行原值。发现原因按稳定顺序取并集。最终article_count=证据不同article数，occurrence_count=合并后每条证据occurrence_count之和，confidence=证据最大值；若某组无证据，则计数为0、confidence保留组内最大已有值并在清单列明。不要把候选表缓存计数直接相加。

候选组8686的两个证据碰撞分别涉及article13219/13919，各3行。保留最早证据ID，contexts、source_fields、detectors、reasons稳定去重并集且不截断；共同article同一次出现不重复计数，现有count/confidence相同则保持原值。若新基线出现occurrence/confidence冲突，默认拒绝并要求明确计数口径，不能静默取最大或相加。原证据行全部留档后才折叠4行。

## 5. 窗口决策与软引用

34组(window, mapped_article)冲突都是历史succeeded窗口中的blocked决策；组内status/score/rank相同，且没有候选保留文章自己的决策行。建议每组保留最早原决策ID，移交到权威article；其他48行完整归档。不同reason/payload不覆盖或拼成新的自动决策；保留行原值，修复回执列出全部原决策与差异。历史窗口result_payload不重写，借映射清单解释原ID；计数显示的历史候选次数不伪装为合并后的实时池大小。

唯一selected决策、全部11条WindowTargetDecision及sent投递均保留。执行前若窗口不再是succeeded、出现租约、queued/retry投递、selected状态冲突或未覆盖的联合唯一键碰撞，拒绝继续。

TaskExecutionLog、OperationLog及历史JSON维持原始事实。必须按task_name/实体类型辨认candidate_id；赛事候选及门禁文章候选不能被术语ID映射命中。实际broker/定时任务不在dump里，生产实施前须证明没有可重新引用被移除ID的待执行/运行消息；不能清空整个队列以通过检查。

## 6. 原子性、留档与失败

计划工具与apply分离，apply只接受精确SHA清单。修改前持久化并fsync完整归档，验证可读取/摘要一致；归档仅存本任务私有恢复目录。数据库短事务锁定两主表及实际移交/碰撞表，重新核验全范围与before-image，再按依赖处理子表碰撞、外键、主表重复行、候选聚合。一次事务提交这些关联变更及可查询修复回执；外部文件有ready/committed状态，不把文件存在当作数据库已提交。

副本缺失的两条约束必须按原始精确DDL建立，其他约束不排除。生产若仍有原约束定义，不采用副本“缺约束”状态作准入依据；应先独立核实物理索引健康，生产具体索引重建/切库方式在新基线发布包中确定，不能把隔离ALTER语句直接照搬。

同清单重跑应校验after状态并返回already_applied；before/after均不匹配即拒绝。事务中断必须整体回滚；提交后文件收尾中断则从数据库回执与after哈希恢复，不重复移交。禁止用Django实例delete触发未审级联；工具须显式枚举并校验依赖，任何未知关系中止。

## 7. 恢复基础与根因边界

修复后须恢复原唯一语义、检查FK/catalog、做无重复和源内容/证据守恒验证，再全库dump并在空库严格pg_restore --exit-on-error，核对数据/序列/权限/触发器。不能把旧失败dump排除两条约束后的副本算作完成。

原备份已经证明不能直接完成逻辑恢复，不能把它单独当作生产修复的有效回滚点。未来生产包应优先评估“停写切点的新备份→独立副本按固定清单修复→完整往返恢复验证→受控切换”的路线，保留原数据库/存储恢复面；角色/权限、配置/资产、真实镜像、空间与时限都需重新绑定。若选择原地事务修复，必须另行提供已演练的完整恢复路径和精确回滚方案，不能仅凭旧dump或事务成功就批准。

归档不包含源物理索引页，根因尚未确定。进入生产前还需只读核验真实索引/heap一致性及数据库/存储历史，不能只看indisvalid=true，也不能把本轮重复直接归因为并发或排序规则。保留原唯一约束和正常get_or_create入口；隔离测试需证明相同键并发写最终只保留一条。
