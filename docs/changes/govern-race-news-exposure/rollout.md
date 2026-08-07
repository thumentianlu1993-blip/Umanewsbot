# rollout：赛事新闻聚类与首页 / QQ 曝光治理

## 当前状态

- 阶段：`implemented`。
- 用户已于 2026-07-26 明确授权实现；代码已由 Claude subagent 完成实现。
- 实现 worktree: `impl-race-news-quality-20260726`，分支 `codex/impl-race-news-quality-20260726`，
  基线 `origin/main@ef54a183`。
- RED：`test_race_news_exposure.py` 46/47 RED（因 RaceNewsExposure 模型/服务/开关不存在）。
- GREEN：47/47 GREEN。
- 回归：test_editorial_headlines 57 OK，test_english_term_context_gates + test_term_gate_reprocessing 57 OK，
  其他 182 tests OK。Django check + makemigrations --check --dry-run 通过。
- 新增模型 `RaceNewsExposure` + migration `0061`；
  新增服务 `race_news_exposure.py`；
  新增管理命令 `backfill_race_exposure.py`；
  新增 settings 5 项。
- 下一门禁：独立代码 review；commit、push、PR、部署和生产写入仍未授权。

## 影响边界

- 预计触及新闻模型、发布窗口、QQ 窗口、即时 QQ、首页/头条、赛事详情和运营审计。
- 不触及赛事赛果权威状态、新闻来源采集、地区归属或翻译供应商。
- 与 `unify-public-racing-terms` 可并行评审，但实现时先冻结共享赛事身份接口，避免重复解析。
- 当前已知并行线包括 `normalize-race-and-career-fields`、`fix-external-english-horse-context-gate`、
  `automate-race-event-lifecycle` 及主检出区 `news_reflect`。实现前必须重新 fetch
  `origin/main`，逐文件检查模型、terms、validation、views、tasks、publishing/QQ services 和迁移
  图；相关线未合并或接口未冻结时不得凭当前快照直接实现。
- 实现使用新的干净隔离工作树；本规划工作树不承接应用代码。

## 灰度顺序

1. 部署 schema 与代码，所有新开关关闭。
2. 开启 shadow，只记录建议 exposure，不改变首页或 QQ。
3. 审核至少一个重要赛事窗口，确认身份 unresolved、硬重复、两席和替换计数。
4. 先开启首页 enforce，验证 1440px / 390px 与赛事详情完整性。
5. 再开启 QQ enforce，目标为现有测试群；观察至少两个自然窗口。
6. 历史 exposure 回填另生成冻结 dry-run，经独立审核和用户单独授权后执行。

## 回滚

1. 关闭 `RACE_NEWS_EXPOSURE_ENABLED`，恢复旧首页和 QQ 选择。
2. 保留 exposure 审计和 migration，不删除历史记录。
3. 若数据回填异常，按批准 manifest 精确撤销本批新增 exposure；不改文章和 QQ 历史。

## 发布前证据

- 最新 `origin/main`、迁移图、Django check、目标测试与完整受影响回归。
- shadow 报告及英皇锦标逐篇决策。
- reviewer 成功结论与冻结 fingerprint。
- 实现完成后更新 `docs/current_state.md`、`docs/decisions.md`、`docs/project_status.md`；涉及开关、
  worker、迁移、灰度和回滚的实际命令与证据同步更新 `docs/deploy_runbook.md`。
