# 新闻正文提取边界测试用例

## 当前门禁

- 用户已明确G1 范围确认；测试与 fixture 已由测试 subagent 编写，并在实现前取得真实 RED。
- 当前测试已 GREEN，等待独立代码审核；这不构成 commit、发布或历史生产重处理授权。

## RED 取得方式

旧代码在 HRN 页面无语义 `<article>` 时选择整个 `main`。先只加入 fixture 和测试，运行聚焦用例；预期至少：

- “只提取 `.article-body`”用例失败，因为旧结果含 ticker/login/相关推荐且 `body_selector == "main"`；
- “选择器缺失 fail-closed”用例失败，因为旧 HRN 仍回退 `main`；
- “抓取失败详情不入库/不翻译”用例失败，因为旧国际抓取仍 upsert 并对新文章触发翻译；
- 历史只读识别和 manifest 绑定用例失败，因为旧命令不支持来源分批扫描，也不验证批准哈希。

RED 必须是断言目标行为尚未实现导致；fixture 读取、导入、语法、数据库或环境错误不算 RED。

实际 RED：

- 新闻核心聚焦 23 项：18 通过、5 个目标断言失败，分别证明旧实现命中 `main`、缺容器不 fail-closed、
  翻译输入仍含框架、失败详情仍 upsert、重复抓取仍覆盖既有文章。
- repair/scan 完整聚焦 34 项：除上述 5 个断言外，另有 5 个目标 CLI 未实现错误；均由
  `--source-site/--after-id/--max-id/--limit` 或 `--manifest/--manifest-sha256` 尚不存在导致。
- workflow 聚焦 1 项：三份八阶段文档断言通过，旧 checker 仍要求七阶段 marker，因此有效 RED。

## 自动化用例

| ID | 层级 | 场景 | 预期 |
| --- | --- | --- | --- |
| T1 | integration | 用 `hrn_9623.html` 解析 HRN 详情 | `body_selector=.article-body`、状态 `ok`；首段/末段保留；ticker、登录、标题元数据、Related Pages、Top Stories 不出现 |
| T2 | integration | fixture 正文含 `h2`、`blockquote`、`ul/li`、`table` | 各合法文本按 DOM 顺序保留，无中段截断 |
| T3 | integration | `.article-body` 内含真实赔率、普通链接文字与文章小标题 | 不因“Fair odds/Sign up”等页面外同词或宽泛语义规则误删真实事实；实现不依赖词黑名单 |
| T4 | integration | HRN 页面只有 `main` 和框架、缺少 `.article-body` | 空正文、`selector_not_found`，不回退 `main/body` |
| T5 | integration | 正常 HRN 反例只有可信正文容器和完整首尾段 | 输出逐段完整，开头、结尾、引用和列表均保留 |
| T6 | regression | 既有 Sporting Life、TDN、Sponichi fixture | 现有正文边界与清理结果不变 |
| T7 | integration | 国际抓取得到 `selector_not_found`、`empty_after_cleaning` 或空正文 | upsert、术语发现和翻译均未调用；计入 detail error/CrawlJob，其他文章继续 |
| T8 | integration | 既有文章重复抓取但详情解析失败 | 不更新原文、HTML、metadata 或 snapshot，不触发翻译 |
| T9 | application | 历史识别模式按 HRN、`after_id/max_id/limit` 扫描 | ID 稳定排序、scope 覆盖全部部署前 HRN 文章、只解析保存 HTML、输出逐篇哈希/状态，不写文章/日志/QQ |
| T10 | application | 历史识别遇到 missing HTML、selector failure、changed、unchanged | 四类分别计数并保留在历史 scope，不中断整批其他文章 |
| T11 | application | 历史识别传入不支持来源、非法/过大 limit 或 `--commit` | fail-closed，错误信息明确，无写入 |
| T12 | application | repair commit 使用 schema v2 批准 manifest + 正确 file SHA，逐篇输入及标题/raw/normalized/parse metadata 输出哈希全部匹配 | 单事务写回精确批准集合，保留既有发布/QQ 语义与 OperationLog |
| T13 | application | legacy v1、缺少 v2 字段，或 manifest 文件 SHA、文章集合、`updated_at`、HTML、旧正文、标题/raw/normalized 正文、canonical parse metadata 任一漂移 | 锁行复核后整批零写入、零 OperationLog；不接受当前状态为新基线 |
| T14 | application | 历史识别文章有人工正文或 `rewrite_body_zh` | 报告人工字段/有效正文层与 hash，供重处理决策，不自动覆盖或清除 |
| T15 | integration | 翻译 provider 输入 | 解析后的 HRN source body 不含页面框架，合法首尾和结构文本完整进入 prompt |

## 手工/运行态验收（发布后，需另行授权）

1. 在候选镜像离线解析真实 fixture，保存选择器、状态、正文首尾和 SHA。
2. 生产部署只读核对 web/worker/beat 镜像一致、Django check、迁移无漂移、队列可解释。
3. 等待或显式批准一个此前从未入库的新 HRN 抓取样本，核对：
   - `original_content_html` 仍保存；
   - `body_ja_raw/body_ja_normalized` 只含真实正文；
   - 翻译、改写和 `effective_body` 不含页面框架；
   - 公开详情首尾完整且返回 200。
4. 以部署前冻结 `max_id` 只读生成全量历史 scope 并保存 SHA；不得在同一授权下自动重处理。重复抓取的
   既有文章不计入 Gate A 成功，也不得因原文层变干净从历史 scope 消失。
5. 若未来另行批准重处理，至少逐篇验收 `9623`、`9519` 和一个正常反例，核对发布时间、文章 ID、
   workflow、人工字段和 QQ delivery 数。


```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true <bundled-python> server/manage.py test \
  stable.test_news_content_boundaries.InternationalNewsContentBoundaryTests \
  stable.test_news_content_boundaries.RepairArticleContentBoundariesCommandTests --noinput

DB_ENGINE=sqlite <bundled-python> server/manage.py check
<bundled-python> -m compileall -q server/stable/adapters/international.py \
  server/stable/management/commands/repair_article_content_boundaries.py
<bundled-python> .codex/scripts/test_workflow_contract.py
<bundled-python> .codex/scripts/check_workflow_contract.py
git diff --check
```

实现 subagent 应先根据仓库依赖加载结果替换 `<bundled-python>`，并记录实际命令、测试数和退出状态。

## GREEN 标准

- T1–T16 中所有已实现的自动化用例通过；workflow contract test 与 checker 两个命令均退出 0。
- 既有受影响回归无新增失败。
- Django check、编译/静态检查和 `git diff --check` 通过。
- 测试不得通过公开模板隐藏、中文词黑名单、文章 ID 特判或放宽失败门禁。

## 实际 GREEN（2026-07-23）

- `stable.test_news_content_boundaries`：`43/43`。
- `stable.tests.CrawlAutoTranslateTests`：`13/13`；三个旧裸对象 mock 已由测试 subagent 更新为有效
  `CanonicalNewsDraft`，生产 fail-closed 门禁未放宽。
- reviewer P2 的 schema v2 测试先在旧实现取得有效 RED：dry-run 缺少 normalized/parse metadata 输出哈希，
  legacy v1 仍可进入 commit，标题/normalized/parse metadata 漂移未被批准 manifest 阻断。
- schema v2 聚焦测试 `3/3`、完整 `RepairArticleContentBoundariesCommandTests` +
  `HorseRacingNationHistoricalBoundaryScanTests` `13/13`；命令 `compileall` 与全工作树 `git diff --check` 通过。
- workflow contract tests：`26/26`；checker 输出 `WORKFLOW_CONTRACT_OK`。
- Django check、目标 Python 文件 `compileall` 与 `git diff --check` 均通过。
