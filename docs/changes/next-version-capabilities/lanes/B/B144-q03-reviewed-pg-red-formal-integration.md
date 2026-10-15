# B144：Q03 私有 PG RED 正式 CI 整合候选（未启动）

2026-10-15。**PRIVATE RED CANDIDATE ONLY / 禁止 merge、deploy、activate**。只完成本地精确整合与静态登记，不是PG RED或GREEN。固定main/parent `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`，独立codex/b144-q03-reviewed-pg-red-integration；ROOT最近live main作为输入，不在本卡联网刷新或写其他候选。PR250/251保留原fixed对象；未导入N02/R04、未wholebranch merge/cherry-pick。

## 1. 14 个准确功能依赖与审查链

唯一导入源 `75abf99547a324361adc8bb5ec36a1f888258787`，tree `819eb9903075199b42ec203a2585061cbbf10c98`，相main的server功能变化准确14paths。每个导入Gitblob/bytes/SHA与最终源相同，未重新实现：

| 路径组 | 文件数 | 精确历史reviewed源码与原R |
| --- | --- | --- |
| public_news_snapshot.py / test_public_news_snapshot.py | 2 | C144-R01 source1dae4a6068bc75f4aec842b49e998412cca5e7d8，R a21c71e834c5d0397685d57efba9469e6e4d6ae3，duplicate PK finding已关闭 |
| public_news_queries.py / public_news_snapshot_loader.py / loader test | 3 | C145 f7437356d88eb2fad1ce4c7b074c61ba4daaab37，R3c3bc1731a5c632d56cd9ddbf5f377cbb7839767，SQLite ORM有限审 |
| public_news_snapshot_http.py / HTTP test | 2 | C1465de12aad39f9cd6fe55269ddda0a268ad37ec23f，R476d00a317f6bd68e566ac85c26efffbe6c8b551，未挂URL有限审 |
| news_feed_semantics.py / pure test | 2 | C151869be1783191e7323918f2a1b4e457de3a7ec429，R8480070de292f7d52e8b48a57d9926f6df34e6bf，仅纯参考 |
| models.py / views.py / 0082 migration / news_feed_commit.py | 4 | C15398b7534969945a60caf8fd518eec5ef4c8877e9a逐字相同；R137e653aa39d18ffa07de1a37aef312f5e2c85cf静态schema/helper/API无其他finding；views继承C145的query提取和C153的唯一article_update_api改动 |
| test_news_feed_commit_postgres.py | 1 | C153-R01最终75ab，R458590d6495e9b29ef2d8e2b714261beffc0879a/SHAfef44d9503f1c98bcd9f725530e4bd493e219dc773ed9a0648f259bb31082cd3；receipt62bb7d83b9de6144b9e584b74e0a4537db82bdd492de7d585f456a11d0e1da06 |

最终R关闭唯一medium：真实NOWAIT的55P03且savepoint已恢复才变AssertionFAIL，未知SQL/连接/表/权限或needs_rollback未恢复仍ERROR；14 test方法体/worker finally/时限保持。不是已经取得PG FAIL。C152 source2cd907+R01source11df2b36611dffaf497cf0a381d399c87cab9c93，最终R d224e2079f626f0812f894793c76dfd0f23f5492只确认fresh pg_stat_activity每轮clear snapshot合同；不当运行证据。7份历史/最终R报告均从Git逐SHA核，ROOT相关ledger仅只读。

本候选没有导入C143–C153整套作者docs，只保留本说明；原方案/合同/RED前件及旧C151/C152/C153/Rpack以固定runtime pins引用，不能用精确代码整合冒称补齐全部交付文档或历史测试证明。

## 2. 骨架与范围锁定

news_feed_commit.capture_news_change默认getattr(NEWS_FEED_CAPTURE_ENABLED,False)；false直接yield，true只普通atomic、真实Article行锁/业务save，**故意不Clock、不capture、不outer durable、不reentry poison**。唯一既有API body在这个私有context内，身份/method/CSRF路径保留；新HTTP适配未挂URL。正常schema三模型与0082准备供受控PG fixture，绝不因本次mapping通过改成GREEN、启用feed或合并该骨架。源码任何需修项交原C/原R，不由B改14blobs。

0082_news_feed_commit_primitive归原C153，AST dependency精确0081_managed_readonly_steps。静态Git检查固定main、A07650a87d7b455fe47da1786fce6825dbfb7dc7fcf8、PR251登记0c41ed6f9d94e1f4e4e1b1e7a783c79f45bd9521、PR250登记afed9bbe0e91ae9c93f318af8c2ae9e2715dfdc9均有0081、无0082；最终C153源仅此0082。**仅这些准确登记对象无撞号**，未核global/unregistered branches或生产，不称全局clear，不重分配其他owner迁移号。

## 3. 五模块与profile/dedicated

| 模块 | 静态声明方法（非native count） | profile / 原因 |
| --- | --- | --- |
| stable.test_news_feed_commit_postgres | 14，同一FeedCommitPrimitiveTransactionTests | django，TransactionTestCase、真实PG16/target/SQL/锁/两个client；dedicated_batch_modules增加此模块，原sharder按整class独立分片，AST模拟只该14且无其他class混批 |
| stable.test_news_feed_semantics | 22 | python，implementation与test只有stdlib/纯DTO，无Django/ORM依赖；标准worker所有profile仍先Django.setup，模块import模式不安装其仅__main__启用的standalone audit hook；不以此profile为PG逃生，PG14保持django |
| stable.test_public_news_snapshot | 20 | django，signing/QueryDict/SimpleTestCase和真实未保存model DTO |
| stable.test_public_news_snapshot_loader | 8 | django，实际ORM/TestCase；已有STANDALONE私有SQLite设置仅settings未configured时启用，正式worker已setup Django，不能当stdlib |
| stable.test_public_news_snapshot_http | 10 | django，RequestFactory/JsonResponse及loader ORM fixture；正式依原django profile，不绕DB |

只声明5模块及各自方法，不相加推新native总分母；没有执行它们的import/collect/实例化/测试/迁移。原worker/profile/Dockerfile/workflow完全原字节：PG16/127.0.0.1:5432/bounded_ci→test_bounded_ci、django batch600s、docker rm30s、job120min、pool4；两client只该class测试A/B，不是PG server max_connections=2，不改server预算。正式fixture/真正业务FAIL/cleanup须未来标准CI日志。

## 4. 最小mapping与旧覆盖

新增领域q03_news_feed含这5labels。六exact功能路径（commit/semantics/query/snapshot/loader/http）映射该域；views symbols新增_public_published_articles/article_update_api映射，public_news_feed原domains上仅追加该域，原module initialization full规则原样。models及migrations原high-risk full保留。新域依赖既有module:stable.tests_legacy（含API auth/CSRF/OperationLog等）、editorial_headlines、race_news_exposure、public_new_regions、public_term_consistency；core自动包含。不能用14 PG方法取代这些旧回归。

验证：六helper/五test路径各targeted19humanlabels；models/migration各full333；views完整实际diff targeted26。所有这些selection含5新label、core与旧legacy/headline/曝光/公开投影。移除明确新增path/symbol/domain/dependency/test/profile/owner/dedicated量后rules/catalog parsed对象**整体等于main**，未删改旧labels、依赖、highrisk/init/skip/分片规则。新增dedicated仅这一module，旧3保留。unknown路径单独或并highrisk仍fail-closed；实际planner的catalog-drift负例另留收据，不能借full遮漏。

静态全集从main328到333humanlabels、267domains；按选中label profile为django258/python72/release-postgres3。按catalog模块profile条目另为django241/python72/release3，分母不同。10允许skip原reason/profile/review_by2026-10-16不变、不延期、不计closed。真实native ID/count/profiles/batches/RUN/实际skip/owned cleanup均UNKNOWN；labels、AST声明方法和历史6886/6913/6932都不是新分母。

## 5. 本卡验证与后续

仅现有映射合同3module（scripts.tests.test_test_impact/test_impact_git/test_impact_evolution）在既有venv执行，父进程socket.connect/BaseDatabaseWrapper.ensure_connection guards生效，**39PASS/exit0，3.488s**。没有Django.setup、应用tests、native collector或migration执行；guard不冒充子进程或正式CI隔离证明。mapping日志validation-only/missing release evidence为既有unit fixture，不是本候选结果。未跑pure22/snapshot20/loader8/HTTP10/PG14，不重复先前资源/CI。

使用原main byte-identical impact_ci/planner对固定Git对象出wholemain、parent（同main）及changed-slice路径/static计划：全候选因models/migration和mapping变动full333，保留old+new全域。head/test=head只本地静态身份，非PR test merge。原20control paths仅rules/catalog两个blob允许变化；不改worker/runner/workflow/Dockerfile/requirements等18control原件。源14各Git/本地/runtime逐字，旧13个C151/C152/C153/Rpack小型保护pins前后相同，不写原作者包或ROOT ledger。

先ROOT/原R精确整合审，再另派**唯一DraftPR**正常CI取得真实PG业务RED；本卡不push/PR/CI，不另建runner、数据库/容器/VM或读失败image artifact，不source/provider/付费/网络/merge/deploy/activate。若真实环境或helper有确定性问题，准确区分业务FAIL/环境ERROR，交原C/R，不在B卡私改GREEN。原完整Q03/I2、B04–B07、生产旧worker、baseline、auth/retention/SLA/资源清理及full trusted delivery继续未闭合。

通用门禁只引用根AGENTS.md；worktree/native默认路径失效，按用户显式fallback授权用正确owner/PID/SHA短OSflock建独立Git worktree并登记mapping，收据保存实际持锁/释放时间。runtime /Users/mentianlu/.codex/runtime/b144-q03-reviewed-pg-red-integration-001 保存14blob/review-chain/migration范围/旧pins/control/profile/静态planner/合同测试和最终receipt/seals。仅本候选14功能+两mapping+本文（17paths）。
