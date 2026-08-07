# test_cases：赛事新闻聚类与首页 / QQ 曝光治理

## RED 计划

环境错误。证据记录实际命令、失败测试名和关键断言。

## 单元测试

- 相同赛事、规范化来源标题完全相同，即使 Jaccard 低于旧阈值仍判为硬重复。
- 相同赛事但综合赛果、胜者、练马师反应等不同角度不写 `duplicate_of`。
- 唯一 manual link 或唯一合格 auto link 得到 event identity；candidate/removed、manual 冲突、
  多个合格 auto 和跨年度同名时 unresolved。
- 第一席立即激活；第二席 15 分钟前 waiting，15 分钟后才可 active。
- `other` 角度不能自动证明与第一席不同。
- 更高质量稿只替换首页第二席，不替换第一席。
- 同策略重复执行幂等。

## 模型与并发

- 条件唯一约束拒绝同赛事/频道/作用域/席位的两个有效记录。
- 两个发布窗口并发争抢第二席时只有一个成功。
- QQ 已发送席位不可替换；失败重试不增加席位。
- worker 在预留后崩溃：可确认未发送时 lease 回收；结果不明或已有 message ID 时保留席位并停止
  自动重试。
- quota、exposure 与 delivery 任一数据库写失败时事务整体回滚，不留下幽灵额度或空席位。
- migration forward/backward 在支持的测试数据库上通过，索引名称和长度合法。

## 首页与头条

- 同赛事 5 篇公开文章：首页含头条在内最多 2 篇，分页和热门榜不泄漏第 3 篇。
- 被抑制文章详情为 200，且出现在对应赛事详情新闻列表。
- 手工头条选中同赛事第三篇时原子替换第二席，不形成第三席；第一席未满 15 分钟时明确拒绝占用
  第二席。
- 无赛事身份的普通新闻保持现有排序和展示。
- 查询数不会随同赛事文章数线性增长。
- 首页 50 篇候选的赛事链接/exposure 额外查询不超过 3 次，生产 shadow p95 退化不超过 20%。

## QQ

- 同群同赛事最多发送 2 篇；不同群各自独立计数。
- 第一篇即时推送后，窗口任务不重复发送。
- 第二篇未满 15 分钟不创建 delivery。
- 首页第二席后来被替换，不为新稿创建第三次 QQ delivery。
- 原有地区、类别、soft-fill、群级和站点级额度回归通过。
- QQ 100 篇候选、5 个目标群无 article × target 查询，本地 PostgreSQL 选择阶段不超过 5 秒。

## 历史回填

- dry-run 只输出确定性 manifest，不写文章、delivery、headline 或 exposure。
- 重复 article/event ID、身份漂移、manifest SHA 不一致整批拒绝。
- apply 只写批准的 exposure，前后正文、公开时间、QQ delivery 和 `duplicate_of` 守恒。
- 重放同一批准包零额外业务效果。

## 生产验收

- shadow 至少覆盖一个重要赛事完整 30 分钟窗口。
- 英皇锦标样本：全部相关文章仍可直达，赛事详情可见；首页和目标群各最多 2 篇。
- 核对第一席时间、第二席等待时间、角度和替换审计。
- 1440px 与 390px 检查首页、分页、热门榜、赛事详情；浏览器控制台无错误。
- 内外 `/healthz/`、worker/beat、窗口成功率和队列积压正常。

## 预计测试入口

- `stable.tests.PublishWindowServiceTests`
- `stable.tests.QQWindowServiceTests`
- 首页/头条相关测试类
- 新增 `stable.test_race_news_exposure`

实现时以实际测试类为准，并把 RED/GREEN 命令和结果追加到本文件。

## RED 执行结果

### 命令

```bash
cd /Users/mentianlu/Code/umanews/.worktrees/impl-race-news-quality-20260726/server
../.venv/bin/python manage.py test stable.test_race_news_exposure -v2
```

### 总览

- **总测试数**: 47
- **RED (失败)**: 46
- **GREEN (通过)**: 1 (`test_ordinary_news_stable` — 无赛事身份的普通新闻保持现有排序和展示，为当前已实现行为)
- **Error**: 0

### 所有 RED 失败根因分类

| 根因类别 | 失败测试数 | 说明 |
|----------|-----------|------|
| `RaceNewsExposure` 模型不存在 | 16 个测试类中所有测试 | `stable.models` 中无 `RaceNewsExposure` 类 |
| `stable.services.race_news_exposure` 模块不存在 | 所有服务调用测试 | `resolve_race_identity`, `classify_hard_duplicate`, `reserve_exposure`, `replace_slot2`, `classify_angle`, `reserve_qq_exposure`, `get_featured_articles`, `reclaim_expired_lease` 均未实现 |
| `backfill_race_exposure` 命令不存在 | 4 个 | `stable.management.commands.backfill_race_exposure` 不存在 |
| 功能开关未定义 | 5 个 | `RACE_NEWS_EXPOSURE_ENABLED`, `RACE_NEWS_EXPOSURE_SHADOW`, `RACE_NEWS_SECOND_SLOT_DELAY_MINUTES`, `RACE_NEWS_HOMEPAGE_MAX`, `RACE_NEWS_QQ_TARGET_MAX` 未在 `settings.py` 中定义 |

### 失败测试明细

| 测试类 | 测试方法 | 失败原因 |
|--------|----------|---------|
| `RaceIdentityTests` | `test_race_news_exposure_model_exists` | ImportError: RaceNewsExposure 模型未实现 |
| `RaceIdentityTests` | `test_event_identity_by_unique_manual_link` | ImportError: resolve_race_identity 服务未实现 |
| `RaceIdentityTests` | `test_event_identity_by_unique_auto_link` | ImportError: resolve_race_identity 服务未实现 |
| `RaceIdentityTests` | `test_candidate_link_unresolved` | ImportError: resolve_race_identity 服务未实现 |
| `RaceIdentityTests` | `test_manual_conflict_unresolved` | ImportError: resolve_race_identity 服务未实现 |
| `RaceIdentityTests` | `test_multiple_qualified_auto_unresolved` | ImportError: resolve_race_identity 服务未实现 |
| `HardDuplicateTests` | `test_hard_duplicate_same_source_normalized_title` | ImportError: classify_hard_duplicate 服务未实现 |
| `HardDuplicateTests` | `test_hard_duplicate_does_not_cross_event` | ImportError: classify_hard_duplicate 服务未实现 |
| `DifferentAngleNoDuplicateTests` | `test_comprehensive_result_and_winner_not_duplicate` | ImportError: classify_hard_duplicate 服务未实现 |
| `CrossYearNoClusterTests` | `test_cross_year_same_name_not_clustered` | ImportError: resolve_race_identity 服务未实现 |
| `TwoSlotStateMachineTests` | `test_first_slot_immediately_active` | ImportError: reserve_exposure 服务未实现 |
| `TwoSlotStateMachineTests` | `test_second_slot_waiting_before_15min` | ImportError: reserve_exposure 服务未实现 |
| `TwoSlotStateMachineTests` | `test_second_slot_active_after_15min` | ImportError: reserve_exposure 服务未实现 |
| `TwoSlotStateMachineTests` | `test_other_angle_not_prove_difference` | ImportError: reserve_exposure 服务未实现 |
| `TwoSlotStateMachineTests` | `test_higher_quality_replaces_slot2_only` | ImportError: replace_slot2 服务未实现 |
| `TwoSlotStateMachineTests` | `test_idempotent_same_policy` | ImportError: reserve_exposure 服务未实现 |
| `ModelConstraintTests` | `test_no_two_active_records_same_event_channel_scope_slot` | ImportError: RaceNewsExposure 模型未实现 |
| `ModelConstraintTests` | `test_qq_sent_slot_persists` | ImportError: RaceNewsExposure 模型未实现 |
| `ConcurrentSlotTests` | `test_concurrent_slot2_fight` | ImportError: reserve_exposure 服务未实现 |
| `ConcurrentSlotTests` | `test_qq_retry_does_not_add_slot` | ImportError: RaceNewsExposure 模型未实现 |
| `ConcurrentSlotTests` | `test_lease_reclaim_on_confirmed_not_sent` | ImportError: RaceNewsExposure 模型未实现 |
| `ConcurrentSlotTests` | `test_fail_closed_on_unknown_result` | ImportError: RaceNewsExposure 模型未实现 |
| `TransactionRollbackTests` | `test_rollback_on_any_write_failure` | ImportError: RaceNewsExposure 模型未实现 |
| `HomepageAndHeadlineTests` | `test_max_two_same_event_on_homepage` | ImportError: RaceNewsExposure 模型未实现 |
| `HomepageAndHeadlineTests` | `test_suppressed_article_accessible` | ImportError: RaceNewsExposure 模型未实现 |
| `HomepageAndHeadlineTests` | `test_manual_headline_replaces_slot2` | ImportError: RaceNewsExposure 模型未实现 |
| `HomepageAndHeadlineTests` | `test_slot2_rejected_before_15min` | ImportError: reserve_exposure 服务未实现 |
| `QQDeliveryTests` | `test_same_group_same_event_max_two` | ImportError: RaceNewsExposure 模型未实现 |
| `QQDeliveryTests` | `test_different_groups_independent_counts` | ImportError: RaceNewsExposure 模型未实现 |
| `QQDeliveryTests` | `test_no_window_duplicate_after_instant_push` | ImportError: reserve_qq_exposure 服务未实现 |
| `QQDeliveryTests` | `test_second_qq_before_15min_no_delivery` | ImportError: reserve_qq_exposure 服务未实现 |
| `QQDeliveryTests` | `test_slot2_replaced_no_new_qq_delivery` | ImportError: RaceNewsExposure 模型未实现 |
| `HistoricalBackfillTests` | `test_dry_run_no_writes` | ImportError: backfill_race_exposure 命令未实现 |
| `HistoricalBackfillTests` | `test_duplicate_article_event_id_rejected` | ImportError: backfill_race_exposure 命令未实现 |
| `HistoricalBackfillTests` | `test_apply_preserves_original_data` | ImportError: backfill_race_exposure 命令未实现 |
| `HistoricalBackfillTests` | `test_replay_no_extra_effects` | ImportError: RaceNewsExposure 模型未实现 |
| `PerformanceTests` | `test_homepage_50_articles_query_count` | ImportError: RaceNewsExposure 模型未实现 |
| `MigrationTests` | `test_migration_forward` | ImportError: RaceNewsExposure 模型未实现 |
| `FeatureFlagTests` | `test_race_news_exposure_enabled_flag_defined` | hasattr: RACE_NEWS_EXPOSURE_ENABLED 未定义 |
| `FeatureFlagTests` | `test_race_news_exposure_shadow_flag_defined` | hasattr: RACE_NEWS_EXPOSURE_SHADOW 未定义 |
| `FeatureFlagTests` | `test_second_slot_delay_defined` | hasattr: RACE_NEWS_SECOND_SLOT_DELAY_MINUTES 未定义 |
| `FeatureFlagTests` | `test_homepage_max_defined` | hasattr: RACE_NEWS_HOMEPAGE_MAX 未定义 |
| `FeatureFlagTests` | `test_qq_target_max_defined` | hasattr: RACE_NEWS_QQ_TARGET_MAX 未定义 |
| `AngleClassificationTests` | `test_classify_angle_service_exists` | ImportError: classify_angle 服务未实现 |
| `AngleClassificationTests` | `test_classify_angle_returns_valid_enum` | ImportError: classify_angle 服务未实现 |
| `AngleClassificationTests` | `test_low_confidence_falls_to_other` | ImportError: classify_angle 服务未实现 |

### GREEN 测试

| 测试 | 通过原因 |
|------|----------|
| `test_ordinary_news_stable` | 无赛事身份的普通新闻在当前代码中已能正常渲染首页。该测试验证"不破坏已有行为"这一边界，不需要 RaceNewsExposure 模型或任何新服务。 |

