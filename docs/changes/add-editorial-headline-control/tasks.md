# 首页人工头条与 AI 编辑推荐任务清单

## 0. 探索、规格与门禁

- [x] 0.1 (operations) 从最新 `origin/main@10f341e6` 建立独立干净 worktree
  `codex/add-editorial-headline-control`
- [x] 0.2 (application) 确认 `simplify-public-navigation-and-attribution` 已通过 PR #16 合入当前基线
- [x] 0.3 (application) 只读核对头条算法、公开 queryset、模板、后台、AI 编辑、权限、审计和缓存
- [x] 0.4 (operations) 编写本变更 spec/design/test_cases/tasks/rollout
- [x] 0.5 (operations) 由独立方案 reviewer 使用 plan-eng-review 完成首次审核（结论 REVISE）
- [x] 0.6 (operations) 有 finding 时修正规格并复用同一 reviewer 会话复审至通过（三轮，
  最终 `VERDICT: APPROVED`）
- [x] 0.7 (operations) 审核通过后停止，等待用户明确“G1 范围确认/开始实现”
- [x] 0.8 (operations) 编写可供无上下文 Claude agent 接手的完整 `handoff.md`


- [ ] 1.0 (operations) 测试前确认未提交内容仅为本任务规格/状态文档，记录 `git status`、完整 diff
  与这些文件的内容 fingerprint；用命名 `git stash push -u` 暂存并记录精确 stash OID，确认 worktree
  干净后 fetch、rebase 到届时最新 `origin/main`，再 apply 该 stash。恢复后逐文件核对内容 fingerprint，
  并检查 `admin.py/views.py`、公开模板/CSS 和相关测试 hunk 重叠；只有核对一致且无冲突才删除临时
  stash。若 rebase/stash 恢复发生冲突、内容或方案变化，则保留 stash、停止实现，复用同一方案 reviewer
  复审，通过后重新取得实现确认
- [ ] 1.1 (application) 测试 subagent 添加模型、迁移、固定 slot check、资格、唯一 selection 和
  active 推荐约束 RED
- [ ] 1.2 (application) 测试 subagent 添加设置/替换/取消、权限、版本冲突和审计 RED
- [ ] 1.3 (application) 测试 subagent 添加失效协调、删除、Django Admin bulk action、callback 异常、
  读取 fail-safe、统一资格算法 fallback 与实时更新 RED
- [ ] 1.4 (integration) 测试 subagent 添加推荐生成/替换/接受/失效及“推荐不改首页”RED
- [ ] 1.5 (application) 测试 subagent 添加 48 合格/192 扫描边界、图片查询数、后台管理页、编辑台独立
  form、来源隐藏和公开模板回归 RED
- [ ] 1.6 (application) 测试 subagent 添加真实 PostgreSQL 双连接并发测试；SQLite 下显式 skip
- [ ] 1.7 (operations) 实际运行聚焦测试，记录因目标能力尚未实现导致的真实 RED

## 2. 实现（仅在有效 RED 后；按文件边界串行委派）

- [ ] 2.1 (application) 模型 subagent 实现 selection/recommendation 模型与 `0054` 迁移，不注册可写 Admin
- [ ] 2.2 (application) 服务 subagent 实现统一资格、单例锁、版本检查、推荐、接受、失效和审计服务
- [ ] 2.3 (application) 信号 subagent 实现事务提交后保存协调与删除协调，保证幂等和只读 GET
- [ ] 2.4 (application) 后台 subagent 修复已知 `mark_pending_review` bulk 绕过，并实现权限 form、路由、
  管理视图和模板
- [ ] 2.5 (application) 编辑页 subagent 增加 AI 推荐卡和非嵌套操作 form
- [ ] 2.6 (application) 首页 subagent 接入人工优先 + 原算法 fallback，不重构热门/普通流
- [ ] 2.7 (operations) 文档 subagent 更新 current_state/decisions/project_status 和本变更实施证据

所有 subagent 均不得 commit、push、PR、部署、执行迁移或写生产。

## 3. 验证

- [ ] 3.1 (application) 运行针对性头条、后台权限、审计、AI 推荐和缓存实时性测试
- [ ] 3.2 (application) 运行首页 view/template 与
  `simplify-public-navigation-and-attribution` 来源隐藏回归
- [ ] 3.3 (application) 在真实 PostgreSQL 运行唯一性、行锁、版本冲突和 active 推荐并发测试
- [ ] 3.4 (application) 运行 Django check 与 `makemigrations --check --dry-run`
- [ ] 3.5 (application) 运行必要的完整 `stable` 回归并区分既有基线失败与新增回归
- [ ] 3.6 (operations) 运行 `git diff --check`
- [ ] 3.7 (operations) 使用真实浏览器完成 1440px/390px 首页与后台验收、DOM/overflow/console 检查
- [ ] 3.8 (operations) 记录最终预计迁移、部署顺序、回滚点和未解决风险

## 4. 独立代码审核

- [ ] 4.1 (operations) 冻结完整未提交范围并运行仓库 `review_fingerprint.py`
- [ ] 4.2 (operations) 未参与实现的 reviewer subagent 实际执行 Codex 原生只读
  `codex review -c 'sandbox_mode="read-only"' --uncommitted`
- [ ] 4.3 (application) 有 actionable finding 时由实现 subagent 修复
- [ ] 4.4 (operations) 复用同一代码 reviewer 会话只复审 finding、修复及直接触及路径

## 5. 发布（仅在最新成功 review 后取得明确授权）

- [ ] 5.1 (operations) 重新 fetch，确认已审核 HEAD 仍基于当前 `origin/main` 且远端没有新增漂移；若主干
- [ ] 5.2 (operations) staging 前用相同 scope 重算 fingerprint 并与批准基线逐字节一致
- [ ] 5.3 (operations) 显式 stage 后验证 approved parent、无 unstaged/untracked/conflict 和 content hash
- [ ] 5.4 (operations) 经授权后 commit、push、创建 PR；未授权不得执行
- [ ] 5.5 (operations) 部署前核对生产 HEAD、容器、队列、磁盘、`.env` key 存在性和数据库备份
- [ ] 5.6 (operations) 经授权部署、应用 `0054`，selection 为空且不创建推荐/人工头条
- [ ] 5.7 (operations) 验证迁移、Django check、healthz、首页算法结果、后台权限、1440px/390px
- [ ] 5.8 (operations) 如需启用首个人工头条，由运营在后台显式操作；部署本身不得写 selection
- [ ] 5.9 (operations) 按 evidence-only allowlist 追加 release_report/current_state/project_status/
  deploy_runbook 必要事实，并复用同一代码 reviewer 会话审核
