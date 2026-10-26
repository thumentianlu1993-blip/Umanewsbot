# D003：空筛选恢复测试候选矩阵

2026-10-17（Asia/Shanghai）。方案 `b58b35cb874bbf8db563dd59ab9d6cf4692b636e`；原 R_D 方案复审报告 `f66da24071c5b76b6f1a6b67f78b5f20d255f8fd` / `docs/changes/next-version-capabilities/lanes/R_D/D001/plan-review-002.md`。仅准备测试/最小映射，不写页面实现。本文件的通过预期不是执行结果。

唯一新类 `stable.test_calendar_empty_filter_recovery.CalendarEmptyFilterRecoveryTests`，直接继承 Django TestCase，19 个声明方法；没有从旧测试类继承或动态复制测试。新模块使用自有合成 fixture，受控 `TODAY=2026-10-17`、`NOW=2026-10-17T04:00:00Z`，合成公开日本 P2/G3 赛事；不代表任何真实赛事。LocMem cache/mail，不覆盖数据库连接，未来只由隔离 django profile 建立本地测试库。没有 skip/expectedFailure，也不改历史维护 gate。未导入、collect 或执行应用/测试。

| 方法（同一类下，均以 test_ 开头） | 前件与目标 | 可捕获的错误改动/基线预期 |
| --- | --- | --- |
| combined_empty_filters_restore_real_public_card_via_dom_href | tab/key+德国+G1+完赛+2025+不匹配q，先验证规范 filters 与原顶部清除仅去 year/q，再解析新空态真实 href GET 恢复卡片 | RED 预期缺新文案/链接；捕获重置只去部分筛选、href带旧状态、破坏原清除语义 |
| name_only_empty_filter_recovers | tab=all，只有 q 导致空 | RED 预期；漏判 q |
| year_only_empty_filter_recovers | tab=all，只有 year 导致空 | RED 预期；漏判 year |
| region_only_empty_filter_recovers | tab=all，德国过滤日本；校验规范地区有效，原顶部无清除 | RED 预期；漏判 region |
| grade_only_empty_filter_recovers | tab=all，g1过滤G3 | RED 预期；漏判 grade |
| finished_only_empty_filter_recovers_scheduled_card | tab=all，when=finished 过滤 scheduled | RED 预期；漏判 finished |
| upcoming_only_empty_filter_recovers_finished_card_without_winner | tab=all，when=upcoming 过滤 finished，恢复不能编冠军 | RED 预期；漏判 upcoming/伪造赛果 |
| default_key_empty_filter_recovers_non_key_card | 无查询，默认key过滤P2 | RED 预期；漏判默认重点范围 |
| undated_public_event_restores_existing_cross_period_fallback | 唯一公开赛事 local_date/race_datetime/clock均空，先 public_time.day=None；q不匹配后href点击 | RED 预期；恢复断言仅 GREEN 后可执行到。捕获误加日期限制/伪造日期/默认窗口误导说明 |
| exclusive_valid_return_nav_restores_empty_filters_before_reset | `_public_nav_token` 真实生成，`_public_read_nav` 解码相等；单个return_nav独占query，Client实际还原filters后断言恢复 | RED 预期；捕获按原始GET判断、保留token；producer/还原失败单列前件失败 |
| valid_future_cursor_past_last_row_recovers_without_old_cursor | 真实encoder为唯一集合末项签名，decode成功+event_id一致，同year/tab filters，future空页仍保留有效游标前件 | RED 预期；捕获游标空页无入口或恢复仍带cursor；非法cursor降级不算本项覆盖 |
| default_all_empty_has_original_copy_without_useless_reset | tab=all空库，无其他过滤 | 基线应通过；捕获无意义循环重置链接、改原默认空文案 |
| hidden_and_canonical_duplicates_do_not_become_public_after_reset | hidden canonical及published active duplicate；先默认all确实空且不泄露，再q空页href恢复仍空 | 前半保护基线应通过，目标入口预期RED；捕获解除公开资格或canonical排除 |
| matching_card_preserves_detail_return_navigation_without_empty_ui | q命中，真实卡片href解码、GET详情、提取签名返回URL再GET原筛选 | 基线应通过；捕获正常卡片出现空态、破坏U02签名返回 |
| unknown_query_redirect_is_checked_separately_from_empty_page | 首个响应必须301且Location仅tab/q，然后Client GET最终200空页恢复 | 301保护不算业务RED；最终页面目标预期RED，捕获混入unknown/把重定向误判缺入口 |
| invalid_filters_and_cursor_use_normalized_all_empty_contract | 非法region/grade/when/cursor+future，经规范filters清空，taball空库 | 基线应通过；捕获按raw GET错误展示入口/无效cursor当成功游标 |
| search_text_is_escaped_and_cannot_control_recovery_href | q含script/扩展汉字，先校验规范q与无原文标签注入，再提取固定恢复href | RED预期；捕获插入用户原文/任意跳转 |
| date_only_and_display_flags_preserve_unknown_clock_after_reset | 德国Europe/Berlin、只有当地日期，两展示开关四组合，q空页再href恢复 | RED预期；恢复断言仅GREEN后到达。捕获伪造北京时间00:00、开关分叉或假冠军 |
| reset_does_not_promote_unconfirmed_result_to_finished_filter_or_winner | finished有未确认第一名；finished过滤为空，恢复全部卡片不显示冠军姓名/冠军 | RED预期；捕获恢复越过正式赛果语义；不替代真实live读门禁验收 |

所有恢复项先确认 `groups` 与实际 cal-card 均空，再断言固定新文案/默认规则说明、唯一指定链接文字及 DOM href 精确 `/races/?tab=all`，之后真实 GET 验证规范 filters、公开卡片与all激活。不能将代码中硬编码的预期href直接当页面输出请求。上述16个目标方法预计RED（含权限方法的基线保护前缀）、3个纯保护方法预计基线通过；总声明19（含子用例不另计执行数）。最终执行数、failure/error、业务断言位置以真实收集/运行结果为准。

部署、迁移、Celery重试/并发和写入权限变化均不在本片；性能无提升承诺，手机浏览器未运行。若环境、签名producer、canonical301或setup失败，先报前件/环境失败，不能改skip、放开维护gate、接生产DB或先写页面GREEN。本卡未安排运行。未来 ROOT 分配正常隔离运行后取得真实 RED，才另派 empty 块实现及同例 GREEN；所有 finding 回原 R_D。U04/U05 整卡不验收。
