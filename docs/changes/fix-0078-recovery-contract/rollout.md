# 0078 修复发布与恢复方案

## 1. 本轮边界

这是候选发布设计，尚非绑定可部署SHA/镜像的执行包。人工确认唯一依据根AGENTS.md。
当前只读源码基线为a88bcbf6；生产ca6e9d06/leaf0078/queue7543等来自9月7日交接，必须在实际发布时重新读取。

已取得完整checkout和独立修复分支，候选代码已完成独立审核与隔离验证，结果见validation.md。
本轮尚未绑定实际生产镜像、配置或发布包，也没有生产连接和新生产备份；不得用历史SHA或自报健康值填充。

## 2. 发布包必须包含

- 通过代码审核的PR、commit/tree、image ID/OCI revision及必要源码制品。
- 预计无新migration；预期生产leaf为exact0078且migration plan为空。发现其他leaf或DDL即停止，不自动扩大包。
- 配置：不修改业务开关的最终值；关闭窗口及恢复值使用本次冻结快照。
- 服务：明确Web、ordinary worker、Beat、race_sync_v2_worker、Nginx的stop/rebuild/reload范围，旧race_live worker按当前隔离策略维持。
- 数据：生产业务写入和restore均为0；schema/catalog审计只读。
- 新恢复点：本次exact0078 custom dump、SHA/权限/TOC、compatible image/config、备份时间以及可恢复范围。
- 验证：只读preflight、空migration plan、catalog、服务、三队列、代表性赛事/马匹页面。
- 止损：同候选forward恢复方案；确需数据库restore时另给精确恢复包，明确恢复点之后的数据损失。

## 3. 发布前只读核验

1. 核对本次生产host/project/DB身份、实际容器image和migration recorder/catalog，不以checkout或.env替代容器状态。
2. 确认没有历史runner、External staging或其他release owner冲突。
3. 确认deployment lock可获取且不存在旧restricted marker/control state。发现旧世代在途任务则本包不进入，保全其原artifact并由原控制镜像恢复。
4. 冻结服务恢复意图、10个data-sync flags、celery/race_sync_v2/race_live队列、OOM/restart、磁盘/内存。
5. 在本release_id准备窗口生成新0078恢复点和operation=same-schema的可信备份证明；标准/低成本/manual入口必须实际消费它，不能依赖不存在的通用检查。只保存TOC不够，候选恢复机制此前必须已通过隔离完整restore演练。
6. 新候选先执行只读0078 preflight；失败时旧服务不受影响，不能绕过gate强行部署。

## 4. 解决旧控制面不认识0078的启动问题

发布检查必须从已审核候选镜像运行，使用固定候选入口与已有部署锁，不能先调用运行镜像中钉0077的verifier再用手工SQL绕过。

制作和只读运行候选镜像属于精确发布包的一部分；只读preflight用--no-deps和明确资源/网络范围，不启动应用writer，不替换运行中image tag。成功后才进入关闭窗口。

如标准deploy入口在候选preflight之前会先改动checkout或tag，实施时必须记录并验证这些动作可恢复；任何服务stop之前的失败还原原标识。生产上不临时patch旧release目录。候选部署脚本、镜像和helper须来自同一已审核SHA。

## 5. 关闭态发布

在唯一release coordinator持有的既有部署锁内：

1. 在第一条stop前验证本release_id备份证明，持久化并复读prepared发布意图及active pointer，绑定候选、DB、原admission和全部服务/开关恢复意图。任何一项失败都不得停服。
2. 停Beat并自然drain普通与专用任务，按发布包关闭写入和停止受影响服务；不purge任何队列，不改写原意图。
3. 全停后生成bound closed-state handoff，重新验证DB/image/candidate/catalog和空计划；one-shot仅在此后建立DDL marker。
4. 单一one-shot release task执行check、空计划确认、static和schema completion；不重复应用0078，不--fake。此时发布意图继续活动。
5. Web健康后恢复原先服务与开关，必要时reload/restart Nginx重新解析upstream。
6. 核对本次冻结的race_live队列原值、ordinary/v2队列可解释、restart/OOM及业务抽样；写本发布完成receipt，再按文件身份校验清本发布active pointer并释放锁。

## 6. 失败边界

| 失败位置 | 处置 |
| --- | --- |
| 备份/候选只读preflight失败 | 不进入stop；还原本次暂态tag/checkout，旧服务继续 |
| 备份证明已写而prepared intent未完成 | 无stop；原release_id走prepare续跑，保留原admission/backup绑定 |
| 部分stop后、closed handoff或DDL marker创建失败 | 用停服前已持久化的prepared意图经resume_migration_history_repair.sh新分支继续；不要求尚不存在的DDL marker，不重新deploy |
| 0077→0078隔离升级中失败 | live必须是完整0077或0078；按同发布marker/backup继续，不换候选 |
| 同版本0078 static/completion失败 | 不迁移、不丢意图；同候选重试，验证后恢复服务 |
| schema completion已完成但服务未全部恢复 | prepared发布意图仍活动；同入口读取schema receipt继续原服务恢复，最后才归档发布意图 |
| 新candidate、DB、SHA、文件身份漂移 | 拒绝继续；不重签旧manifest伪造一致 |
| 已恢复服务后发现行为问题 | 使用发布包既有止损开关并保全数据，准备fix-forward；不调用普通rollback强退 |
| 必须恢复数据库 | 列出精确dump/image/config、数据损失窗口和独立验收；根AGENTS.md要求的确认后另行执行 |

普通rollback仍关闭是有意保留，不是本次验收失败。修复完成的说法必须是“0078发布/恢复合同与备份恢复路径已验证”，不能写“已开放任意代码回滚”。

实际恢复入口为扩展后的resume_migration_history_repair.sh，以原RELEASE_0078_INTENT_PATH/SHA、release_id选择新分支，先于旧分支的DDL marker必需校验。它每次取得新部署锁，重新验证候选、DB、backup和可信文件；原锁token摘要只保留provenance。各阶段重试矩阵见design.md第5节，必须通过test_cases.md的T35–T42才可把该入口放入发布包。

## 7. 备份恢复演练和实际恢复边界

本次开发验证只使用合成隔离数据。实际事故恢复需要：

- 写前保全当前数据；停止所有writer与相关长期runner，固定恢复窗口。
- 目标必须是新空数据库/新实例；准确绑定目标身份，不能用旧0077 dump对已有0078库--clean后直接认定exact0077。
- 用现有restore_db.sh选定明确Compose project/DB执行；不在通用脚本里新增自动删库。
- 恢复后的recorder、catalog、关键表计数/关联、snapshot内容与对应备份一致；由兼容镜像只读验证。
- 只在独立verifier通过后切换连接、启动Web并恢复受准writer。恢复到旧备份会丢失其时间点后的业务变化，不能把服务200视作无数据损失。
- 旧0077控制artifact如需保留，只由其原控制镜像使用；不得在本次新合同中静默迁移。

## 8. 文档收尾

实现完成后更新current_state、deploy_runbook、rollback_guide、backup_recovery与测试基线报告；新的架构决定写decisions，里程碑摘要按需写project_status。区分本地测试、隔离PG验证、已合并、已部署和生产验收，不能提前勾选。
