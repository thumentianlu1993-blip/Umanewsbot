# C041 精确五例测试设计

本文件机械展开 C040 原 R 已审方案 `956c2e184f6bbd46b9a9f4ac9e8a1907f88be870` 的五例范围；原 R `adf9c066e0eb1903eb8d181abc6132b2f36bb6b7` APPROVED_PLAN_ONLY、零 finding。不是新公开能力方案。固定开发底座 C036 `558df2a3bf83d590ccbdb010d3f73dc70d528041`，人工门禁统一根 AGENTS.md。

每个完整ID前缀为 stable.tests_legacy.PublicHomeInfoFeedTests.；准确名单由runtime test-ids.json/diagnostic-plan.json绑定，不加载整继承类。新增代码仅该类五方法，旧helper/方法和整个模块其他AST保留。

| 方法 | 正常前置与断言 | 捕获的 mutation | 原模板预期 |
| --- | --- | --- | --- |
| test_u04_headline_only_empty_copy_describes_current_page | 真实published文章→真实自动头条→feed空；解析实际hero链接，Client点击详情、读标题/正文，再断言新“本页暂无其他新闻。”与旧文案不存在 | 保留无条件全局空态；移除头条入口/破坏详情 | 有效文案RED，导航前置须先正常 |
| test_u04_headline_empty_copy_keeps_truly_empty_home | 无公开文章，headline=None、feed=[]；旧“目前还没有已发布文章。”在，新文案不在 | 无头条也显示“其他新闻”，误导真实空集 | 保护项应通过 |
| test_u04_headline_empty_copy_does_not_disclose_hidden_articles | PENDING_REVIEW、WITHDRAWN和PUBLISHED但公开时间NULL；旧空态、无标题/来源/内部枚举，实际详情404 | 扩大公开查询或头条准入、遗漏NULL条件、泄露隐藏对象 | 保护项应通过 |
| test_u04_headline_with_regular_cards_keeps_dedup_and_no_empty_copy | 真实高分带cover头条+普通稿；只普通稿在feed-card，两种空态不在；Client点击渲染普通稿→解析真实返回链接→返回列表 | 删除去重；错误出现空态；破坏signed return导航 | 保护项应通过 |
| test_u04_headline_only_first_page_preserves_next_page | 只patch真实分页常量为1，仍使用真实ORM/头条；首page仅headline、feed=[]，实际下一页URL→page2普通稿，feed不含headline，新文案仅首空页 | 全局空态误报；移除分页；signed navigation丢page；普通feed重复头条 | 有效文案RED，分页前置须先正常 |

范围细节：

- 复用原make_article；None公开时间会被helper替换为published_at，所以NULL子例显式ORM update后refresh并断言None。所有数据库写入仅将来隔离TestCase fixture，当前尚未运行或写入任何库。
- BeautifulSoup已在原requirements内，只解析真实响应，不引入依赖。scope限定section aria-label=最新新闻；不将hotlist/关注区已有同名展示误当重复feed。
- 不mock resolve_homepage_headline/public queryset，不直接render伪HTML。page size常量patch只造两页边界，不替换业务服务。example.com cover/source URL只作合成字符串，Client不会请求图片或外站。
- 本片不新增读取失败处理：DB/模板异常继续抛出，不转成空集或造“整理中”。setup/import/fixture/权限错误不构成行为RED；新文案意外已通过时报告ROOT，不伪RED。
- 性能无新查询/模型/迁移/队列/并发合同；五独立TestCase方法，准确单batch<=200，受信worker的PG16/Django环境隔离、网络禁止等保持，不跑整个stable/tests_legacy类。
- 原预期为2文案业务RED+3保护通过，实际结果须看原executed/failures/errors/skips/lifecycle，不能以静态准备证明RED/GREEN。

GREEN之后才申请已审五个既有精确回归（不是本次RED窗口自动追加）：三项PublicHomeInfoFeedTests头条选取/fallback/去重，两项PublicNavigationAndAttributionTests头条来源隐藏/无region第二页。准确ID在C040获审方案；本轮未执行或扩窗。

未来GREEN仅feed.html for-empty传固定文案。rollback面为该模板分支的代码回退；部署/生产由ROOT后续精确交付包处理。本轮无部署或迁移，不改当前公开数据。未来桌面/手机可见验收沿已审C040独立合成演示，不改C027现存库/服务。

## GREEN准确十方法申请

C041真实RED已完整得到2文案失败/3保护通过、0errors/skips，原五方法字节冻结在 `a59fed26e8c23a73e6859d66436fb28eb667ce4e`。本轮模板实现后申请一次C041-TEN-GREEN-PG-WINDOW-001，将上表五完整方法和下列原C040获审五旧回归合并为一个准确10方法django batch，不重跑RED候选、不展开整类、不collect/full、不预填执行结果。

| 原有完整canonical ID | 保护合同 |
| --- | --- |
| stable.tests_legacy.PublicHomeInfoFeedTests.test_public_home_selects_recent_high_value_cover_article_as_headline | 原高价值带cover头条选取 |
| stable.tests_legacy.PublicHomeInfoFeedTests.test_public_home_headline_falls_back_to_latest_published_article | 原最新公开稿fallback |
| stable.tests_legacy.PublicHomeInfoFeedTests.test_public_home_feed_articles_do_not_repeat_headline | 原普通feed头条去重 |
| stable.test_public_navigation_and_attribution.PublicNavigationAndAttributionTests.test_headline_hides_source_and_region | 原头条来源与region隐藏 |
| stable.test_public_navigation_and_attribution.PublicNavigationAndAttributionTests.test_unified_feed_page_two_works_without_region | 原统一首页无region真实第二页 |

10ID逐AST定位class/method/line与文件hash；旧回归模块和整份tests_legacy.py不改。GREEN未获PG分配，静态准备不是测试通过。正式delivery/full分母不由此诊断申请变更；独立review和合成桌面/手机可见验收由ROOT后续安排。
