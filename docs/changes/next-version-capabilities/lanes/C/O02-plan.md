# C010 / O02 最小诊断与恢复方案（仅准备，待事实与原R审核）

2026-10-03 Asia/Shanghai。接续U02固定方案后，优先准备首批生产发布前O02阻塞诊断。本卡仅拥有lanes/C/O02*文档；没有脚本、模型、migration、共享maps或生产操作变更。当前代码基线见O02-offline-inventory.json。现有指令覆盖只读仓库探索和方案；生产动作统一由协调者按根AGENTS.md处理。

## 已知事实与未知

2026-10-02备份恢复报告记载：私有custom dump完整装载后，新闻uq_article_source_article_id、术语uq_term_candidate_type_normalized两处唯一约束建立失败；生产对报错新闻键强制heap读取13行。convalidated/indisvalid/indisready=true并不能消除这个反证。报告中的636531864字节及SHA只是该次归档身份；不证明今日数据不变。赛事副本排除两失败约束后的演练仅证明赛事恢复，O02整库恢复仍不通过。

root O01运行报告19:07–19:13时点为ad50abdb/0079/PostgreSQL16.14，ICU能力可见；只作为运行身份线索，不证明当下窗口、索引或collation健康。协调者保有正式dump，不下载到本地、不输出新闻/术语正文、凭据或用户数据。B的480秒独占窗口必须由root排队，C不开PG容器。

目前未知：重复的完整组数和行数、byte-identical还是索引collation下相等、源与目标collation/provider版本是否一致、是否存在损坏/漏索引项、生产历史DDL/数据路径、所有引用及不同版本内容/公开资格。不能将导出顺序、排序规则升级或某次发布预设为根因。

## 静态引用与修复风险

models.py解析得到新闻19条入站外键（包括self duplicate_of）、术语2条（self merged_into_candidate及TermCandidateEvidence.candidate）；完整model/field/on_delete/行号见inventory。新闻关联包括赛事/马匹链接、相关地区、图片/媒体、快照、术语证据、推送历史与delivery、窗口两类decision、翻译/自动化日志、头条selection/recommendation、赛事字段authority/change、新闻曝光。许多CASCADE不能直接删；SET_NULL也会丢失来源指向。

必须另查实际数据库pg_constraint全部schema与应用非FK引用。至少MultiregionAttributionRun.completed_article_ids、OperationLog的target_type/target_id、JSON selectors/payload/evidence、任务/缓存及公开URL需要逐项归属，catalog不能证明这部分完备。操作审计原object ID应保持可追溯，不盲改append-only审计。

可能冲突的子表唯一键包括(event,article)、(horse_profile,article)、(article,region)、(candidate,article)、(article,target) QQ delivery及(window,article) decision。多条父记录指向同一子业务键时，直接FK改写可能再次违反唯一约束，且合并已发送/待发delivery可能引起重发。需逐表规则与守恒断言，QQ历史不可触发发送。

term_candidate_review.merge_candidate仅把pending原行标为MERGED并设指向，不删除原候选或改变唯一键；因此该操作本身不能修复现有重复唯一键。term_discovery.aggregate_finding依赖get_or_create/select_for_update及唯一约束，一旦真实重复，读写路径可能抛MultipleObjectsReturned；是否已发生需证据，不能擅自运行其业务入口。

## 第一阶段：最小只读取证

交root O02-readonly-sql.md。先catalog/版本/大小/外键元数据，再由root决定强制heap的有界汇总。按不同读取策略分别保留结果与EXPLAIN计划，不做EXPLAIN ANALYZE、REINDEX、amcheck安装或全库查询。超时=未知，不能自动加预算。私有报错键通过参数绑定，不把原键写文档或日志；统计只输出计数与对象定义。

完整引用统计需先用真实catalog结果生成逐关系、候选ID集合受限的SELECT，再交root第二轮；本轮不动态执行未知表查询。不能为了完成诊断长时间持有snapshot或争抢其他线程窗口。

## 第二阶段：隔离复现及根因分流（尚未执行）

root分配专属无生产网络、无外发、固定镜像/客户端/资源限制的环境。现有真实dump仅在服务器私有目录按既有访问边界恢复，不作为自动测试输入；自动测试另用无敏感合成数据。先忠实复现未修复dump失败，包括两个约束原SQL和实际日志，不能把跳过失败项当通过。

对照源/目标database与列/索引collation/provider/deterministic/声明及actual版本、扩展/PG版本；使用byte分组与原collation分组分开比较。byte完全相同且源heap重复是数据/索引一致性反证；仅collation等价差异需验证源目标等价规则；不能仅REFRESH COLLATION VERSION消除错误或改C collation逃避业务唯一规则。索引路径与heap差异只形成索引不一致假设，需要副本重建/检查进一步定位；有效标志不作健康验收。

只有证据证明恢复顺序/环境差异且数据符合原语义，才考虑最小导出/恢复脚本修复。若真实数据违反唯一语义，则先形成独立、可审核的数据方案；不能强行把原卡解释为批量去重授权。

## 第三阶段：保留/合并规则与副本演练（条件方案）

先为每组保存私有完整字段/引用快照与digest，比较source URL、原文/中文内容、人工修改/锁、公开状态与时间、slug、revision/来源依据、媒体、delivery与审计。不存在统一“最小ID留存”默认。完全相同且引用可守恒的组可提出确定保留者；内容/公开依据或accepted_term/审核结论冲突必须单独列阻塞，不按时间覆盖人工结果。必要别名/公开旧URL保留方案会涉及产品/身份规则，交root确认范围。

逐子表区分直接重指、等价重复合并、保留不同历史及不可合并冲突；计数不能仅要求所有表行数不变。使用预期变更delta、逻辑关联多重集和逐行审计digest证明没有未批准丢失；新闻公开/人工字段/媒体/赛马关系、术语证据contexts/detectors/reasons与计数、历史QQ发送不重发分别断言。发生合并时原候选证据去重必须有明确计数语义，不能简单相加article_count。

副本以固定manifest（每组ID、所有字段和引用前置digest、保留者、逐表动作、schema/collation绑定）prepare/dry-run/apply/重复apply/中断回滚、并发前置变化拒绝。父子唯一冲突、未知引用、缺行或digest漂移fail closed。完整引用闭合前不写apply脚本。

## 第四阶段：完整恢复与回退验收

backup_db.sh当前custom/no-owner/no-privileges、私有临时文件与SHA/TOC原子落盘；restore_db.sh的dump路径为clean/if-exists/exit-on-error/single-transaction。这些是现有技术合同，无证据先不改。该restore脚本绑定真实.env/Compose，隔离演练不能直接在生产checkout调用。rollback现有forward-only边界保留，不靠逆向migration回退。

在修复副本生成新完整dump，恢复至第二个新空库，不排除任何约束/索引/触发器。逐表精确行数与预期delta、所有FK无孤儿、关键关系及人工/公开依据digest、两唯一键在heap和数据库原相等语义下无重复、catalog完整及schema与migration一致；完整pg_restore退出0且日志无被忽略错误。二次恢复用新空库重验，既有目标clean不能冒称exact恢复（旧dump可能不包含新增对象）。旧兼容镜像读取新schema、当前镜像关键页面及只读业务验证，关闭所有外网/队列/邮件/QQ。

记录dump起止/snapshot点、备份耗时、恢复/索引验证/应用可读耗时和切换模拟RTO；RPO按实际恢复点与写入停止/切点比较，不能用演练耗时宣称0数据损失。新旧备份都私有保存身份与有效期。完整恢复验收未通过就保持O02阻塞。

## 后续生产包需求与停止条件

若需要生产数据修复或索引操作，由root在必要测试与独立review后形成精确包：commit/manifest SHA、对象数量及范围、schema/collation前置条件、备份与已经真实恢复的恢复面、暂停哪些写入/队列、索引锁/磁盘/时长上界、重建/配置/服务动作、功能开关、验证、失败停点和回退。manifest变化/新增范围交root按AGENTS.md处理；此文档不授权任何生产动作。

恢复旧整库会覆盖修复后在线业务变化，不能称无损回滚；优先副本演练可逆逐对象操作，确需整库切换时必须列停写与损失窗口。根因未定、引用未闭合、恢复仍有错误、资源窗口不符、新缺陷或无法保全人工/发送历史均停止并报告。首批发布阻塞只能由实际全库恢复通过证据解除。

## 当前交付

已完成仓库静态盘点、最小诊断SQL设计和条件恢复方案；生产新取证、根因定位、隔离复现、修复/完整恢复/RTO-RPO均未完成。本线不声明O02已修复或通过，下一步由root安排有界只读查询，再固定事实与原R方案审。
