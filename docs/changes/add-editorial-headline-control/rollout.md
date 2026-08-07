# 首页人工头条与 AI 编辑推荐 rollout

## 1. 当前阶段

- change：`add-editorial-headline-control`
- worktree：`/Users/mentianlu/Code/umanews/.worktrees/add-editorial-headline-control`
- branch：`codex/add-editorial-headline-control`
- 初始基线：`origin/main@10f341e6`
- 当前授权：探索、规格、方案审核
- 当前禁止：测试/业务实现、实现 subagent、commit、push、PR、部署、迁移、服务重启和生产写入
- 方案审核：同一独立 reviewer 三轮收敛，首轮 6 项 finding 全部关闭，最终
  `VERDICT: APPROVED`，剩余 P0/P1/P2 finding 为 0
- 下一门禁：等待用户明确“G1 范围确认/开始实现”

## 2. 前序 change 与冲突面

`simplify-public-navigation-and-attribution` 已通过 PR #16 合入 `main@438ab6a1`，当前
`origin/main@10f341e6` 是其后代。该 change 实际修改：

- `server/stable/views.py` 的统一公开 news queryset、旧 `?region=` 重定向和首页上下文；
- `_headline.html`、`_article_card.html`、`_hot_list.html`、`feed.html`、`detail.html` 等公开模板；
- `public.css`；
- `server/stable/tests.py` 和 `test_public_navigation_and_attribution.py`。

本变更预计只在 `views.py` 的最终头条解析点有直接重叠；不需要修改 `_headline.html`、`feed.html` 或
`public.css`。公开 partial 维持同一 `headline_article` 契约，因此来源/地区隐藏规则不应被重开。

实现前必须：

1. 确认未提交内容仅为本任务规格/状态文档，记录 `git status`、完整 diff 和逐文件内容 fingerprint；
2. 使用带名称的 `git stash push -u` 暂存全部本任务内容，记录精确 stash OID，并确认 worktree 干净；
3. `git fetch origin`，rebase 到届时最新 `origin/main`；
4. apply 第 2 步的精确 stash OID，逐文件核对恢复前后的内容 fingerprint；
5. 重新检查 `admin.py`、`views.py`、公开 headline/feed 模板、`public.css` 和两组公共页面测试的
   文件/hunk 重叠；只有无冲突且内容一致才删除临时 stash；
6. rebase/stash 恢复产生冲突、内容或方案变化时保留 stash、停止实现，复用同一方案 reviewer
   复审，并重新取得实现确认。

## 3. 生效边界

部署代码和迁移后：

- 新表为空；
- 没有人工选择；
- 首页继续使用当前算法头条；
- 不自动生成推荐；
- 不自动设置或替换头条；
- 不修改任何 `NewsArticle`；
- 不触发 QQ、抓取、翻译、正文提取、马名识别或赛事日历任务。

只有有权限运营人员通过后台 POST 才产生 recommendation/selection 状态。

## 4. 上线前检查

本地/候选版本：

- 聚焦测试与受影响回归全绿；
- PostgreSQL 条件唯一约束和双连接并发通过；
- Django check；
- `makemigrations --check --dry-run`；
- `git diff --check`；
- 1440px/390px 首页和后台验收；
- 独立原生只读 review 成功，前后 fingerprint 完全一致；

生产预检：

- 核对 `/opt/umanewsbot` HEAD、远端合并 SHA 和镜像 revision；
- 检查 web/worker/beat/race_live_worker 状态与队列；
- PostgreSQL custom-format 备份通过 `pg_restore -l`，保存 SHA-256；
- 记录回滚镜像/提交；
- 不输出 `.env` 值或凭据；
- 确认没有共享维护窗口或正在进行的文章编辑/发布事务。

## 5. 部署顺序

1. 使用项目指定低成本生产 compose/部署脚本；
2. 应用 `0054_homepage_headline_control`；
3. 验证两个新表、`UNIQUE(slot)` 和 active 条件唯一索引；
4. 确认 selection/recommendation 均为 0；
5. Django check、migration drift、内外网 healthz、首页和 admin login；
6. 比较部署前后算法头条与首页 DOM，确认来源隐藏、普通流和移动布局无回归；
7. 验证无权限 staff 得到 403、有权限账户可打开管理页；
8. 不在部署脚本中生成推荐或设置头条。

## 6. 灰度操作

首个运营验证应使用一篇已公开、内容完整且网页发布时间不在未来的文章：

1. 先只生成推荐，确认首页完全不变；
2. 查看推荐 reason/evidence 和 `OperationLog`；
3. 人工接受推荐，确认首页切换且普通流不重复；
4. 取消人工头条，确认立即回到原算法结果；
5. 再次设置并用受控撤稿验证失效回退；若不适合修改真实文章，使用候选环境完成该步骤，生产只做非破坏
   读取验收。

生产文章撤稿、删除和重新发布都不是本 rollout 自动执行项；需要时单独明确目标和授权。

## 7. 回滚

### 7.1 逻辑快速恢复

- 有效应用仍运行时，后台取消人工头条即可恢复原算法；
- 推荐记录无首页权力，无需为推荐单独关闭首页；
- 若管理入口异常，公开 resolver 仍应在 selection 缺失/无效时回退。

### 7.2 代码回滚

- 回滚到部署前 commit/镜像；
- 旧代码忽略新表，公开首页自然回到算法头条；
- 保留新增表，避免丢失人工选择、推荐和审计证据；
- 验证首页、详情页、admin login、worker/beat 和 healthz。

### 7.3 数据库反向迁移

故障窗口不执行反向迁移。经另行审核和授权后才可 reverse `0054`：

- 会删除 selection/recommendation 表及其记录；
- 不修改 `NewsArticle`；
- `OperationLog` 仍保留，但 detail 引用的推荐 ID 不再可反查；
- reverse 前必须再次备份并导出相关记录。

## 8. NO-GO

以下任一情况停止发布或首个运营动作：

- 分支未 rebase 到最新 `origin/main`；
- 前序公共页面来源隐藏测试失败；
- migration drift 或 PostgreSQL 条件唯一索引缺失；
- 固定 slot CheckConstraint 缺失或可写入其他 slot；
- 真实 PostgreSQL 并发留下多个 active 推荐或陈旧请求静默覆盖；
- 推荐生成改变 selection/首页；
- 无权限用户可写；
- 撤稿后仍显示无效人工头条；
- 首页或后台在 1440px/390px 有横向溢出/关键按钮不可用；
- review fingerprint 漂移；
- 生产备份、HEAD、镜像或服务状态无法确认。

## 9. 证据与 handoff

实现后在本目录记录：

- RED/GREEN 命令和关键结果；
- migration 与 PostgreSQL 约束证据；
- 并发测试结果；
- 1440px/390px 截图/DOM/console 结果；
- reviewer 会话、命令、fingerprint 和结论；
- 当前未解决风险。

发布后仅按 `docs/codex_workflow.md` 的 evidence-only allowlist 更新
`release_report.md`、`docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md` 和必要
发布决策；不得借证据收尾修改 spec/tasks/代码/测试/配置/迁移。
