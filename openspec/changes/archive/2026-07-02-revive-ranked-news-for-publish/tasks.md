## 1. 测试用例与数据边界

- [x] 1.1 (application) 为榜单唤醒低分 ignored 文章新增失败测试，覆盖 `source_elevated=true` 后文章恢复为可重新评分状态并记录唤醒元数据。
- [x] 1.2 (application) 为榜单唤醒 `manual_review_required` 价值不足文章新增失败测试，覆盖无 blocker 时重新评分并可进入自动发布候选。
- [x] 1.3 (application) 为榜单唤醒翻译失败和待翻译文章新增失败测试，覆盖自动派发一次翻译重试且不在翻译成功前发布。
- [x] 1.4 (application) 为人工拒绝、撤回、duplicate 和当前 blocker 文章新增失败测试，覆盖榜单命中后不复活、不发布。
- [x] 1.5 (application) 为发布窗口候选查询新增失败测试，覆盖首次入库超过 3 小时但最近 3 小时榜单唤醒的文章仍进入候选决策。
- [x] 1.6 (application) 为重复榜单命中新增失败测试，覆盖同一篇文章不会因重复抓取或多个榜单来源反复派发翻译任务或重复写入无意义唤醒。

## 2. 榜单唤醒服务

- [x] 2.1 (integration) 新增或扩展自动化服务函数，判断文章是否允许被榜单唤醒，并区分已发布 QQ 补推、未发布复活、不允许复活三类结果。
- [x] 2.2 (integration) 实现榜单唤醒字段和元数据写入，更新 `ranked_revived_at`，并记录唤醒时间、榜单来源、原状态、执行动作和幂等标识。
- [x] 2.3 (integration) 实现翻译失败 / 待翻译文章的受控翻译重试编排，避免重复抓取或多个榜单来源反复派发同一篇文章的翻译任务。
- [x] 2.4 (integration) 实现已翻译文章的重新评分编排，确保高价值来源规则参与评分且不绕过 blocker。

## 3. 抓取任务接入

- [x] 3.1 (application) 在 netkeiba 榜单抓取和国际榜单抓取的 `source_elevated=true` 分支接入榜单唤醒服务。
- [x] 3.2 (application) 保持已发布文章现有 QQ 补推行为，并确保未发布文章不会直接创建 QQ delivery。
- [x] 3.3 (application) 确保榜单唤醒分支异常不会中断整个抓取任务，并记录可排查日志或 payload。

## 4. 发布窗口候选支持

- [x] 4.1 (application) 新增 nullable `ranked_revived_at` 字段、迁移和索引；历史文章默认 `NULL`，不做批量回填。
- [x] 4.2 (application) 扩展发布窗口候选查询，使最近 3 小时榜单唤醒文章可重新进入候选池。
- [x] 4.3 (application) 扩展 `WindowCandidateDecision.payload`，记录候选是否来自榜单唤醒、唤醒时间和榜单来源。
- [x] 4.4 (application) 确保榜单唤醒候选仍遵守地区窗口 1-5 篇、全站小时上限、去重和硬门禁。

## 5. 验证与文档

- [x] 5.1 (application) 跑通目标测试：榜单唤醒、翻译重试、重新评分、发布窗口候选和 QQ 补推相关测试。
- [x] 5.2 (application) 执行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 5.3 (application) 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`，或记录无法完整执行时的目标测试替代证据。
- [x] 5.4 (operations) 更新 `docs/current_state.md`、`docs/project_status.md` 和必要的运行手册，记录榜单唤醒语义、上线观察点和回滚边界。
- [x] 5.5 (operations) 执行 `openspec validate revive-ranked-news-for-publish --strict`、`openspec validate --all` 和 `git diff --check`。
