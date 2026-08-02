# 测试用例

## RED 计划

先由测试 subagent 只修改 fixture 与自动化测试：

1. 在等价 HRN `.article-body` fixture 中加入真实层级的
   `#last-race-modal.modal[role=dialog]`、`Race Video` 标题和关闭按钮；
2. 断言当前解析结果不含 `Race Video` 与 `×`，并保留 dialog 前后的正文。
   旧代码会因递归抽取 dialog 文本而失败，构成真实 RED；
3. 构造 HRN 美国文章并提供现有英国同名术语，模拟 provider 原样返回占位符；
   断言输出为“美国赛马会”。旧代码会套用“英国赛马会”，构成真实 RED。

RED 不得来自缺 fixture、mock 结构错误、语法错误或外部 API。

## RED 实测证据（2026-07-25）

测试 subagent 仅新增测试与等价 fixture，未修改应用代码。执行命令：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_news_content_boundaries.InternationalNewsContentBoundaryTests.test_hrn_removes_role_dialog_without_clipping_surrounding_article_blocks \
  stable.test_news_content_boundaries.InternationalNewsContentBoundaryTests.test_non_hrn_role_dialog_is_not_removed_by_hrn_specific_rule \
  stable.test_hrn_source_term_translation -v 2
```

结果：发现 10 项测试，3 项通过，7 项按目标行为取得 RED。

- HRN modal 用例未取得 `hrn_structured_noise` 审计项，且旧实现仍会递归读取
  `role="dialog"` 内的 `Race Video`，证明结构清洗行为尚未实现；
- OpenAI-compatible provider 将预期来源机构占位符判为意外的 `TERM` 并报
  `Translation response changed required person terms`，证明来源机构计划尚未建立；
- 删除来源机构占位符的模拟响应未触发重试或 fail closed；
- Dummy provider 实际输出
  `[未配置真实翻译模型] 英国赛马会 registry`，证明 HRN 仍被英国冲突词条覆盖；
- 非 HRN `role="dialog"` 反例、非 HRN 英国机构译名反例和已有畸形占位符拒绝均通过。

所有失败均来自已审核目标行为尚未实现；SQLite 测试数据库迁移、Django system
check、fixture 读取、JSON mock 响应和测试发现均正常，没有外部 API 调用。

## 自动化用例

| ID | 域 | 场景 | 期望 |
|---|---|---|---|
| T1 | integration | HRN 正文含真实 `role=dialog` 视频 modal | `Race Video ×` 不进入正文；`hrn_structured_noise=1` |
| T2 | integration | modal 前后含段落、列表、表格 | 首尾与 DOM 顺序完整 |
| T3 | integration | 普通正文段落写有 `Race Video` | 该段落保留，证明不是词黑名单 |
| T4 | integration | 非 HRN 正文含 `role=dialog` | 不应用 HRN 专属规则；既有通用行为不意外扩大 |
| T5 | integration | HRN 缺少 `.article-body` | 保持 `selector_not_found` |
| T6 | integration | HRN 美国文章含 `The Jockey Club` 且 DB 有英国同名词条 | prompt 使用确定性占位符且不含英国映射；输出恢复“美国赛马会”；metadata 可审计 |
| T7 | integration | 同篇 HRN 同时含来源机构和人物 TERM，标题/正文各有多次机构出现 | 统一稳定编号无碰撞；各字段次数校验与恢复正确 |
| T8 | integration | `The Jockey Clubhouse`、混合大小写与标点边界 | Clubhouse 不命中；完整词组按大小写不敏感策略命中 |
| T9 | integration | provider 删除、跨字段移动或篡改机构占位符 | 重试耗尽后 fail closed |
| T10 | integration | 摘要复制合法机构占位符或伪造编号 | 合法占位符恢复；伪造编号 fail closed |
| T11 | integration | Dummy fallback 处理 HRN 美国机构 | 输出为“美国赛马会”，不经过英国普通 term 后处理 |
| T12 | integration | 非 HRN 英国文章含同名机构 | 沿用既有英国术语，不应用美国映射 |
| T13 | regression | HRN 正常文章 fixture | 首段、末段、引用、列表保持完整 |
| T14 | regression | 原 9623 fixture | 已知导航、登录、侧栏污染继续为 0 |

## GREEN 与验证

- 聚焦测试：HRN 内容边界与翻译 provider 专项；
- 受影响回归：`stable.test_news_content_boundaries`、相关 translation/terms 测试；
- 历史管线回归：`stable.test_news_body_history`；
- `python manage.py check`；
- `python manage.py makemigrations --check --dry-run`；
- `git diff --check`。

## GREEN 实测证据（2026-07-25）

实现 subagent 未修改测试预期。主代理在同一 worktree 独立复跑：

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_news_content_boundaries \
  stable.test_hrn_source_term_translation \
  stable.test_english_term_context_gates \
  stable.test_japanese_racing_translation_normalization -v 1
```

结果：`120/120` GREEN。

```bash
DB_ENGINE=sqlite /Users/mentianlu/Code/umanews/.venv/bin/python \
  server/manage.py test \
  stable.test_translation_failure_recovery_change \
  stable.test_term_gate_reprocessing \
  stable.test_race_display_name_translation_2026 \
  stable.tests.test_term_display \
  stable.test_news_body_history -v 1
```

结果：`170/170` GREEN。两组合计 `290/290`。

此外：

- `manage.py check`：通过；
- `makemigrations --check --dry-run`：`No changes detected`；
- `git diff --check`：通过。

## 生产候选抽查

代码发布后重新 prepare 36 篇。每篇至少检查：

- 原文和译文没有 dialog/UI、导航、侧栏、登录、工具菜单；
- `The Jockey Club` 语境正确时为“美国赛马会”；
- 标题、首段、末段、引用、列表和表格完整；
- 没有明显截断、编辑注残留或占位符；
- 候选内容 SHA 与批准 manifest 一致。
