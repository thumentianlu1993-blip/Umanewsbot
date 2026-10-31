# 新闻与术语候选重复：隔离诊断结果

日期：2026-11-01。状态：诊断完成、修复方案待实施。全部SQL诊断运行于本机禁网副本的READ ONLY事务，未连接生产、未执行去重或修改业务行。先从未改动归档重新恢复；仍只有两个原唯一约束建立失败，其余恢复过程结束后才开始查询。

## 证据边界

输入为2026-09-26的OSS归档600,598,916字节，SHA256 `01c339772037efec52628deda7eb73210e3daa678dc674368fa8d026fc1b19c9`。PG16.14、固定镜像RepoDigest与[前轮恢复演练](../p02-release-candidate-20261028/backup-rehearsal-20261031.md)相同，network=none、无发布端口、1 CPU/1GiB。本轮结论属于该快照，不代表11月1日生产重复规模，也不验证源库当前物理索引。诊断查询禁用indexscan/bitmapscan、statement_timeout=120秒。

两类重复键各字段的UTF-8字节完全相同：新闻8/8组、术语214/214组。故不仅是规范化或排序规则把不同字符串折叠到一起；确有同键多行。逻辑dump不包含源库物理索引页，不能单凭这些结果确定重复产生的根因。仓库current_state的“2026-07-14生产DB/Redis意外重建事故已恢复”曾记录新闻索引异常及修复；这是历史线索，不是本轮根因证明。

## 主表规模与内容

| 项目 | 全表行数 | 重复组 | 重复组内行数 | 每组保留一条后的冗余行数 |
|---|---:|---:|---:|---:|
| NewsArticle | 18,397 | 8 | 47 | 39 |
| TermCandidate | 11,568 | 214 | 532 | 318 |

新闻最大组13条；术语最大组19条。不同主键、时间及状态证明它们不是同一物理行被重复展示。

### 新闻逐组建议

下表ID为候选保留ID，非已批准生产清单。8组的source_url及原文标题组内一致；9783组原文正文有差异，4组中文标题/正文有多个非空版本。所有47行manually_edited_fields均为空，但不能据此抹掉已发布正文或历史批准的内容修复。

| 候选保留ID | 组内条数 | 来源 | 诊断与建议 |
|---|---:|---|---|
| 6809 | 7 | Sky Sports Racing | 1条待审核、6条翻译失败；保留原待审核行。原文发布时间不同，保留原值并归档差异，不自动选最新时间。历史事故记录也曾以6809为权威行。 |
| 9649 | 3 | Horse Racing Nation | 1条待审核、2条忽略；中文版本有差异，保留权威行，其他版本归档。 |
| 9772 | 13 | Horse Racing Nation | 原待审核行与忽略/待译/失败行并存；中文版本不同，不复活忽略记录。 |
| 9783 | 8 | Horse Racing Nation | 唯一已发布行及唯一sent QQ delivery均指向9783；保留原ID、原文/中文正文、公开状态、slug与发送事实。已有正文边界修复历史，不用其他旧版本覆盖。 |
| 9786 | 7 | TDN | 5条忽略、2条翻译失败；候选9786为忽略，不能合并成待发布；中文不同版本完整留档。 |
| 9797 | 2 | TDN | 原待审核与翻译失败各1条；保留已翻译的原待审核行。 |
| 16303 | 5 | Horse Racing Nation | 4条翻译失败、1条待译，暂无中文内容；保留原ID和失败状态，不触发新翻译。 |
| 16517 | 2 | Horse Racing Nation | 失败与待译各1条，暂无中文内容；保留原ID和失败状态。 |

唯一发送记录：QQPushDelivery#652，article=9783，status=sent，attempt_count=1。不得重置或重发。

### 术语候选

532条中531条pending，1条rejected（ID405）；无accepted、无合并关系，无accepted_term/merged_into_term绑定。214组内source_ja相同，target_zh、suggested_target_zh及中外文别名均为空；不存在本批中文名称取舍问题。差异集中在发现时间、统计、置信度与少量发现原因。

建议213组pending保留最早既有ID；含405的一组保留405的rejected与审核信息。禁止将其变回pending。统计从合并后的证据重新计算，不相加候选表的缓存计数。

## 外键引用与合并撞键

从副本catalog枚举21条入站外键，均validated。以下是重复组全部成员的引用数；“非保留ID”列是按上述候选ID映射计算的搬移前数量，含之后需合并的撞键行。

| 表/关系 | 引用行数 | 指向非保留ID |
|---|---:|---:|
| NewsSnapshot → 新闻 | 3,364 | 119 |
| TranslationRun → 新闻 | 47 | 37 |
| AutomationLog → 新闻 | 34 | 22 |
| WindowCandidateDecision → 新闻 | 252 | 181 |
| WindowTargetDecision → 新闻 | 11 | 0 |
| QQPushDelivery → 新闻 | 1 | 0 |
| TermCandidateEvidence → 候选 | 4,680 | 682 |

其余直接关系在该重复集合上为0：文章马匹/赛事链接、首页推荐/选择、媒体/图片、新闻自引用duplicate_of、关联地区、PushLog、赛事字段authority/change、RaceNewsExposure、证据的article端、候选自引用merged_into_candidate。0仅对当前快照和集合成立。

- 新闻合并会令WindowCandidateDecision的(window, article)出现34组撞键，共82行，需折叠48行；受影响252行最终为204行。这34组均无原保留文章的decision行，均为blocked且组内status/score/rank一致；5组reason不同，4组payload不同，不能丢弃历史内容。全部受影响252条决策来自163个succeeded窗口；唯一selected决策不在撞键组中。
- 术语合并会令(candidate, article)出现2组撞键，均属候选组8686，article为13219、13919，各3条证据。occurrence_count/confidence组内相同，但contexts/source_fields不同；需保留并集，不能直接删掉任意两条。4,680条受影响证据映射为4,676个唯一组合；共涉及2,718篇文章。
- 两类集合在TermCandidateEvidence.article_id上没有交集，本快照可分别处理；新生产快照必须重算，不能沿用此假设。

## 软引用与历史记录

按字段语义核验而非全文替换ID：

- OperationLog：新闻3条（2条incident_duplicate_merge、1条news_body_history_applied），术语1条人工拒绝；Django admin log对应实体引用均0。
- TaskExecutionLog.payload中158行引用这47篇新闻，来自翻译、评分、术语发现、自动化等明确任务类型。
- ProductionWindow.result_payload按article_id、published_article_ids、failed_article_ids核验，5行命中；AutomationLog.payload有1行命中。
- 初步数字扫描的692条candidate_id实际属于race_event_candidate_saved/applied，另8条位于术语门禁重处理的文章候选列表；不是本批术语引用。按真实文章ID复核该门禁result_payload为0命中。绝不能做数字全文替换。
- JSON扫描覆盖新闻/术语/任务/窗口/额度/推送/归属/首页/关联等业务表中相关JSON列的命名ID字段；自由文本、外部文件、Redis任务与未知格式不声称穷尽。历史日志与JSON默认保留原值，并用不可变修复清单的旧ID→保留ID映射解释；运行中的可重放工作项需在未来停写窗口单独核验，不能将历史payload改成新任务。

## 结果材料

私有目录：`/Users/mentianlu/.codex/runtime/p02-duplicate-diagnosis-20261031/`。包含只读SQL、聚合结果、字段差异计数、逐行哈希、外键清单及不可执行的映射预览。预览显式executable=false，无生产DB身份；MD5仅用于本轮字段比较，未来执行清单必须使用SHA256并绑定新快照与真实DB身份。原始正文、私有归档、日志不入Git。

修复路径见[设计](design.md)，验收见[测试用例](test_cases.md)。本轮未试修、未重建失败唯一约束、未完成新备份往返恢复，也未解除P02第4步阻断。
