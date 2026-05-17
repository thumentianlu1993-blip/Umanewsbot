# AGENTS.md

## 项目定位

这是一个面向中文用户的日本赛马新闻平台，目标是把日本赛马资讯整理成清晰可读的中文内容，并提供后台审核、网页发布与后续 QQ 群分发能力。

技术栈主干：

- Django
- PostgreSQL
- Celery
- Redis
- Docker Compose
- Nginx

## 当前阶段

当前阶段已经完成：

- 基础采集、翻译、后台、前台链路搭建
- 公网服务器部署
- 正式域名 `umafans.run` / `www.umafans.run` 的 HTTP 接入修复
- 自动化内容运营 + AI 编辑改写 MVP 代码侧落地

下一阶段准备推进：

- 自动化运营 MVP 生产部署、迁移与灰度启用
- HTTPS / 证书接入
- 部署稳定化
- 监控、备份、回滚流程完善

## 工作原则

- 先闭环可用，再谈优化和扩展
- 不轻易重构主干架构
- 不把聊天记录当项目记忆
- 所有关键状态、决策、排查过程都要写回仓库文档
- 做生产相关改动时，优先核对运行态，而不是只看本地代码预期

## 开始任何任务前必须先阅读

1. [docs/project_overview.md](E:/Codex/docs/project_overview.md)
2. [docs/current_state.md](E:/Codex/docs/current_state.md)
3. [docs/decisions.md](E:/Codex/docs/decisions.md)
4. [docs/deploy_runbook.md](E:/Codex/docs/deploy_runbook.md)
5. [docs/session_bootstrap.md](E:/Codex/docs/session_bootstrap.md)
6. 如涉及部署或运维，再补充阅读：
   - [docs/deploy_production.md](E:/Codex/docs/deploy_production.md)
   - [docs/alicloud_hongkong_step_by_step.md](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
   - [docs/rollback_guide.md](E:/Codex/docs/rollback_guide.md)
   - [docs/backup_recovery.md](E:/Codex/docs/backup_recovery.md)

补充约定：

- [docs/current_state.md](E:/Codex/docs/current_state.md) 是当前真实工作状态主文档
- [docs/project_status.md](E:/Codex/docs/project_status.md) 是面向项目全局的概览/摘要
- 两者如有重复或冲突，以 [docs/current_state.md](E:/Codex/docs/current_state.md) 为准

## 输出风格

- 先确认当前真实状态，再给建议
- 涉及生产问题时，优先给文件、命令、路由、配置片段级别的说明
- 如果用户要求部署/排障，必须区分：
  - 仓库当前预期
  - 服务器当前运行态
- 不给模糊候选结论；如果有多个入口或路径，必须明确“本次验收以哪个为准”

## 每次任务结束后必须更新

- [docs/current_state.md](E:/Codex/docs/current_state.md)
- [docs/decisions.md](E:/Codex/docs/decisions.md)（若有新决策）
- [docs/deploy_runbook.md](E:/Codex/docs/deploy_runbook.md)（若涉及部署、排障、运维）
- [docs/project_overview.md](E:/Codex/docs/project_overview.md)（若产品定位或链路变化）
- [docs/project_status.md](E:/Codex/docs/project_status.md)（保留为项目级概览/摘要，如与 current_state 重复，以 current_state 为准）
