# C175：L03 导航 test-only 候选与正常 PR CI 包

状态：TEST_SOURCE_AND_CI_PACKET_ONLY，实际collection/测试/RED均NOT_RUN。依据获审C174 report SHA256 `c4bded5e59291ba79ad023d1ceb7e80e89e73a63909129b08ce8471cde4a38b9`，精确父基线 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1`。最终head/tree与各工件SHA见本线runtime source-binding/receipt，不以本报告自指提交。

## 变更范围

新增 `server/stable/test_article_race_navigation.py`，独立 `ArticleRaceReturnNavigationTests(TestCase)` 共8个静态方法；未继承旧整类、未改codec。仅在catalog作三项添加：horse_page领域加入 `stable.test_article_race_navigation`、tests新增该文件/领域/label、profiles新增该模块为既有django。不需要改rules，catalog本身识别测试路径；没有新增skip/expectedFailure或修改既有名单。product views/template、models/settings、core/git_input/runner/workflow均保持父提交字节。

原生create_worktree因登记cwd失效返回Not a git repository；本次派单显式允许fallback，已从精确父SHA用git worktree add创建本线独立codex/c175-l03-nav-red。随后attach管理工具返回not a managed worktree；此状态如实记录，未重复建树或改旧C172。工作树路径 `/Users/mentianlu/.codex/worktrees/c175-l03-nav-red/umanews`。

## 测试与预期RED位置

fixture固定时钟，按真实PUBLIC_FEED_PAGE_SIZE+1篇严格递减发布时间，target为第13篇；有效非target手选头条避免目标被feed排除，MANUAL关系及ACTIVE HOMEPAGE/site/slot1曝光保证真实新闻查询资格。均为未来CI专用数据库的合成输入，不在本轮建立。使用当前REMOTE正常CI的临时PG16，不复用demo SQLite或本地环境。

`_article_from_page_two`先真实GET /?page=2，确认context页码/对象PK/头条，再在最新新闻卡片标题内按原target路径与标题定位唯一实际article href，验证实际news/page2 token，GET该文章并确认身份。chip与teaser分别在专用class下定位，即使同路径也不共享首个href。

8条静态方法（模块前缀均为stable.test_article_race_navigation.ArticleRaceReturnNavigationTests）：

1. test_fixture_control_page_two_article_and_both_event_entries_are_visible：独立前件正控制，目标文章与两入口正常、直接赛事裸路径可见且默认返回日历。
2. test_news_page2_article_race_chip_returns_same_page：曝光开/关各独立请求全链；预计在_assert_round_trip中实际chip href的return_nav等于真实列表token断言失败。
3. test_news_page2_article_race_teaser_returns_same_page：独立teaser定位与全链；预计同一业务断言对teaser失败。两方法合计4个拟subTest调度，不计为4个唯一方法。
4. test_invalid_news_navigation_uses_existing_bare_public_path：无/空/篡改/过期/重复/跨kind/非法超长输入不传播，两个入口裸路径回退。
5. test_candidate_removed_or_hidden_targets_add_no_public_entry：准确CANDIDATE/REMOVED枚举；隐藏目标不增加入口且404。
6. test_same_name_distinct_editions_keep_identity_and_rename_keeps_path：不同届次同名保留各自path/year，改名不改身份。
7. test_horse_entry_retains_bare_path_and_horses_only_return_contract：horse链接不附news token，horse详情仍拒news来源并回默认horses。
8. test_news_page_and_legal_slug_stay_within_existing_request_line_budget：合法schema最大ASCII slug，实际page2和合法10位page分别检输入/返回/目标请求行预算；不造news q或超schema对象、不patch预算、不假称存在十亿页。

正常页面/fixture/导入/对象可见的任何失败都不是目标RED。只有容器实际收集完整8个唯一ID，正控制与其余保护方法成立、两主方法在指定“赛事入口未传播实际news token”断言得到AssertionError，才能由ROOT记录有效RED。不得把ModuleNotFoundError、DB/migration、fixture资格、页面404、集合缺失、skip/expectedFailure、CI步骤被跳过当成RED。当前没有实际失败trace；以上均为源码预期。

## 正常CI收集路径与成本

.github/workflows/affected_tests.yml正常pull_request到main，checkout github.sha的真实test-merge；generate-plan将base/head/test分别绑定PR base、PR head与test-merge。scripts/plan_affected_tests.py读取固定Git目录/rules/catalog，新增测试文件已在catalog.tests。catalog变化按原有算法选旧/新领域全量并集（不是仅两方法的小计划），不缩分母或改runner。

catalog horse_page模块label → scripts/test_plan_worker.py loadTestsFromNames →该独立TestCase的8方法；catalog.profiles将完整ID匹配至django。worker collect写完整execution-plan和每批最多200的方法ID，django批次用DiscoverRunner.run_tests(batch.ids)。scripts/run_test_plan.py按固定Git archive/source binding、同一镜像在network-none非root只读容器收集/执行，临时PG16及memory broker在既有工作流内。本轮不启动该路径。

正常PR execute步骤另要求仓库vars.IMPACT_TEST_POLICY=active。其当前远端值本轮未查询，必须由ROOT在下一授权阶段核实；若非active/未收集本类8ID，报告具体阻塞，不改workflow/runner、不中途手动workflow_dispatch/新建环境强接。PR/test-merge/run/attempt/batches/完整分母均未创建或观察，不能预填。

test-only期望使正常CI tests步骤及gate变红；verify-execution仅execute成功才运行，upload-evidence为always，因此RED证据应从实际run/attempt的完整收集清单和批次原生结果核验。失败运行未通过交付gate，不能作为GREEN或合并证据；其他全量失败也须单独定位，不归因本两断言。

## 下一步与边界

精确唯一Draft PR/标准CI待执行包在runtime ci-packet.json与draft-pr-body.md。ROOT先将候选源码、catalog最小映射和CI包送同R_C审；本线本轮仅commit，不push、不建PR、不触发CI。获审后ROOT精确派push/唯一Draft PR/正常pull_request CI，核远端base漂移、policy active、不可变test-merge与运行证据。不得在实际有效RED之前改views/template写GREEN。

只做源码AST(feature_version3.12)/compile-source、模型符号AST比对、JSON三项增量/映射计划与Git diff检查，未运行planner/collection、候选import/Django/DB/Redis/队列/模型/网络/Docker/服务/CI。本地未建立测试域，不恢复旧停止域或宿主替跑；无合并部署/启用。此候选不闭合全L03/I2，也不解除L02/H06依赖。
