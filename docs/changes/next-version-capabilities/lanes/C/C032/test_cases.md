# C032：马匹搜索空态测试先行

基线/已审方案 `46d564a06257797e144960a3fd29e9f2f60272ac`，原 R APPROVED_PLAN_ONLY，ROOT 已授权按原方案实施。只改 horse_index.html empty 分支、既有 HorseProfilePageMvpTests 的相关窄测试与 C 文档；不改 query/view/共享空态/schema/settings/catalog。最初固定准备测试后才申请窗口；实际 RED、模板实现与待 GREEN 状态见同目录 report.md。

五项真实 Django Client 测试位于 `stable.tests_legacy.HorseProfilePageMvpTests`：

| 方法后缀 | 行为与预期 | 捕获的 mutation |
| --- | --- | --- |
| `test_u04_unmatched_search_describes_public_search_scope` | published 存在、q 不匹配；新搜索空态，旧全站未发布文案消失；应真实 RED | 删除 filters.q 分支、误回退全站文案 |
| `test_u04_clear_search_restores_cards_and_preserves_anonymous_follow` | 从未匹配搜索找到真实清除链接，GET 点击后无 q/page/return_nav、恢复已关注公开卡片，匿名 cookie/hash 记录不变；应真实 RED | 删除/重复清除链接、链接携带旧搜索参数、清除误改关注身份 |
| `test_u04_hidden_only_search_remains_no_match_without_disclosure` | 只有 hidden，部分关键词 q；搜索空态，不输出完整 hidden 名称/卡片；应真实 RED | 搜索空态错误声称全站无资料、绕开 published 可见门禁 |
| `test_u04_empty_unfiltered_or_whitespace_search_keeps_no_data_copy` | 无资料且无 q/仅空白；原文案保留，无清除入口；保护项应原实现 GREEN | 对空 q 也套搜索文案、误显示清除动作 |
| `test_u04_matching_search_keeps_cards_and_detail_return_navigation` | q 命中 published；正常卡片和 signed return_nav 保留，无空态/清除入口；保护项应原实现 GREEN | 空态插入正常卡片、丢导航绑定 |

用现有 helper 创建独立合成档案；hidden 查询只用名称前缀，避免输入回显被误报为名称泄漏。身份测试用独立合成匿名 token，token 不输出。数据库/网络仅官方隔离环境；不写原 C027 库，不使用生产/Redis/第三方。无 Celery/迁移/并发/性能机制变化，不引入这些测试或新数据字段。失败/重试/全局新鲜度语义不在本片，沿已审方案延期，数据库异常不得伪装空集。

下一步先向 ROOT 提交固定准备 SHA、五个完整 IDs、一次官方 django 单容器资源预算；未获资源分配不运行 DB/Docker。RED 须是新文案或链接断言，不接受导入/环境错误；再做最小模板 GREEN，同五项复验，最近相关范围依现有影响计划交 ROOT 安排，禁止缩改正式准入。回滚面是纯模板恢复，不改变数据；尚无合并/发布授权。
