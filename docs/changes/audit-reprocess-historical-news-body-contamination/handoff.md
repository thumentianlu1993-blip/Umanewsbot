# 零上下文交接：历史新闻正文污染盘点与重处理

## 1. 接手目标

承接已经上线的 HRN 正文提取边界修复，完成三个独立阶段：

1. 历史 HRN 文章只读盘点；
2. 人工审核并冻结 exact candidate；
3. 在再次授权后小批、可回滚地修复历史中文正文。

当前只完成规划，不代表允许实现或生产执行。

## 2. 工作区

- 仓库：`/Users/mentianlu/Code/umanews`
- 本任务独立 worktree：
  `/Users/mentianlu/.codex/worktrees/audit-reprocess-historical-news-body-contamination/umanews`
- 分支：`codex/audit-reprocess-historical-news-body-contamination`
- 基线：`origin/main@97dd2350a193c74d5063bf7432a283e4d47f6d0a`
- 主工作区含其他任务修改，不得清理、覆盖或在那里实现。
- 任务 slug：`audit-reprocess-historical-news-body-contamination`

接手后先运行：

```bash
cd /Users/mentianlu/.codex/worktrees/audit-reprocess-historical-news-body-contamination/umanews
git status --short --branch
git fetch origin
git rev-parse HEAD origin/main
```

若 `origin/main` 已前进，先只读检查差异，再按仓库 workflow 更新干净基线；不要覆盖本文档或主工作区改动。

## 3. 必读

1. `AGENTS.md`
2. `docs/codex_workflow.md`
3. `docs/session_bootstrap.md`
4. `docs/project_overview.md`
5. `docs/current_state.md`
6. `docs/decisions.md`
7. `docs/deploy_runbook.md`
8. `docs/changes/fix-news-body-extraction-boundaries/` 全部文件
9. 本目录 `spec.md/design.md/test_cases.md/tasks.md/rollout.md`

禁止调用任何 旧规格流程 skill 或 CLI。现行主流程是：


## 4. 已完成的前置修复

- 前一任务已把 `HorseRacingNationAdapter.body_selector` 从宽泛 `article, main` 收紧到
  `.article-body`，并在 selector 漂移时 fail closed。
- 代码 PR #12 已部署，生产代码 revision 为 `0e4a3520`；证据文档 PR #13 已合并到
  `main@97dd2350`，但 docs-only revision 未部署。
- 生产镜像只读解析文章 `9623` 来源页得到 `.article-body / ok`、正文长度 9355、已知框架文本 0。
- 部署后自然 HRN 抓取只有重复稿，没有全新文章；新稿端到端 Gate A 仍待真实自然样本。
- 重复抓取已把 `9623` 的日文来源层变干净，但旧中文层未重译，因此公开正文仍污染。

## 5. 生产只读探索事实（2026-07-24）

权威服务器：`root@47.239.167.86:/opt/umanewsbot`。只读排查使用现有 web 容器，
不要使用 `docker compose run`。

冻结范围 `source_site=horse_racing_nation,id<=9788`：

- 282 篇，ID 5711..9788；
- 原始 HTML 缺失 0；
- workflow：duplicate 8 / ignored 12 / pending_review 162 / published 68 /
  translation_failed 32；
- translation：translated 248 / failed 33 / pending 1；
- automation：auto_published 68 / failed 17 / ignored 18 /
  manual_review_required 162 / pending 17；
- `manually_edited_fields` 非空 0；
- `rewrite_body_zh` 非空 0；
- QQ delivery 52：sent 47 / failed 5。

辅助词信号命中 174 篇，明显过宽，证明“当前/热门/登录”等词只能作为审核提示，不能成为候选规则。

文章 `9519`：

- published / translated / auto_published；
- effective layer 为 `body_zh`；
- QQ sent，message_id 已存在；
- 来源正文 5374 字符，中文翻译 1819 字符；
- 仍命中“热门/公平赔率/登录/免费注册”。

文章 `9623`：

- published / translated / auto_published；
- effective layer 为 `body_zh`；
- QQ sent，message_id 已存在；
- 来源正文 9355 字符，中文翻译 3060 字符；
- 仍命中用户列出的全部已知污染词。

这些数字是探索快照，正式 inventory 必须重新冻结并哈希，不能直接当批准清单。

## 6. 关键代码地图

- HRN 解析与适配：`server/stable/services/news_sources.py` 及关联 adapter 模块
- 入库/翻译任务：`server/stable/tasks.py`
  - `translate_article_task`
  - `rewrite_article_task`
- 翻译 provider：`server/stable/services/translation.py`
- 改写与应用：`server/stable/services/rewriting.py`
- 验证：`server/stable/services/validation.py`
- 内容模型和 effective layer：`server/stable/models.py::NewsArticle`
- 既有历史来源修复：
  `server/stable/management/commands/repair_article_content_boundaries.py`
- 既有测试：`server/stable/test_news_content_boundaries.py`
- 可参考但不可照搬的 manifest/lease 模式：
  `server/stable/services/term_gate_reprocessing.py`

现有 `repair_article_content_boundaries` 已支持：

- 显式 HRN 范围只读扫描；
- missing/selector/empty/parse/changed/unchanged 分类；
- 原始 HTML、before/after/effective SHA、人工字段、rewrite、workflow/translation/automation、QQ 数；
- schema v2 exact-ID source commit；
- 单事务锁全集、逐篇输入/输出 hash、漂移零写；
- 只写日文来源字段和 canonical parse metadata。

它不解决：

- 来源层已经干净但中文层仍陈旧；
- exact translation/rewrite candidate 的准备与人审；
- 中文字段的精确离线 apply/verify/rollback。

## 7. 必须保留的设计决定

1. 不用中文词黑名单决定边界或 action。
2. 正式 cohort 固定 HRN `id<=9788`，包含自然重复抓取后来源已干净的文章。
3. AI prepare 和数据库 commit 分离。人审批准 exact output/hash；commit 阶段不联网、不重新调用 AI。
4. 不直接复用 `translate_article_task(force=True)`：它会覆盖人工字段并在执行时写库。
5. 人工字段默认 `manual_review/keep_manual`；任何自动覆盖都必须重新方案审核。
6. 写入不改变 workflow/public timestamp/slug/publisher/QQ/tags/链接。
7. QQ sent 是外部不可逆历史：可修网站，不重发、不声称旧消息已修复。
8. 默认无 migration。若必须加批次模型或锁表，返回方案审核。
9. production artifact 必须显式持久挂载；当前 lowcost Compose 只挂了
   `runtime/horse_profile_completion`，本任务目录不持久。
10. pilot 最多 10 篇，包含 9623、9519、正常 no-action 反例和可选未公开样本。
11. 旧 TranslationRun 缺完整输入 hash 时不能自动 no_action；事实分类与人工 action 分开，正常反例
    也必须由可信 hash 或人工签署。
12. review template SHA 与 submitted workbook SHA 分开；人工填表后校验证据列 identity，再生成
    canonical approved decisions。
13. 完整 rollback before 值必须在 DB 事务前原子落盘并 fsync，OperationLog 绑定其 SHA；receipt
    可在 post-commit 崩溃后重建。
14. 首版逐字段批准且不改 title、translation status/error/retry/provider/model/time；failed/pending
    默认 manual review。
15. inventory/prepare 使用 DB read-only role/transaction 和写探针；prepare 只调用 detached DTO +
    pure provider，禁止 `translate_article()` 等会写 TranslationRun 的路径。

## 8. 当前门禁和下一步

当前阶段：方案审核已通过，等待用户明确G1 范围确认。

独立 reviewer 首轮给出 5 项 P1，限定复审又发现 1 项事务/文件顺序 P1；修订后同一 reviewer 会话
最终结论为 `VERDICT: APPROVED`。已关闭的问题是：

1. 缺 source-input hash 的旧译文不能自动 no-action；
2. review template 与 submitted workbook SHA 分离；
3. rollback 完整 before 在 DB 写事务前原子持久化并可重建 receipt；
4. 逐字段 allowlist，首版不改 title/翻译状态；
5. inventory/prepare 的数据库强制只读与 pure provider；
6. 文件 fsync 不跨越唯一写事务和行锁。

下一位 agent：

1. 先确认用户是否已经在本方案审核通过后明确回复“G1 范围确认/开始实现/继续实现”；旧任务中的授权
   不得自动继承到本专项；
2. 若尚未授权，继续停止并向用户汇报：
   - 根因；
   - 最终范围/预计文件；
   - 测试与 RED；
   - 历史边界；
   - 风险/非目标/回滚；
   - reviewer 结论；
3. 只有取得新授权后，才允许测试先行和实现 subagent。

## 9. 未获授权的动作

当前禁止：

- 编写或修改自动化测试；
- 修改应用代码、配置、migration；
- 启动实现 subagent；
- 运行正式历史 inventory、candidate prepare 或数据重处理；
- commit、push、PR、merge、deploy、服务重启、生产数据写入。

即使工具代码未来通过 review，仍需分别取得工具发布、正式只读 inventory、模型候选生成和 exact manifest
生产写入授权。
