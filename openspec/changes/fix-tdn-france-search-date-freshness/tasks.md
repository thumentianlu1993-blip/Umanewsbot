## 1. 实现修复

- [x] 1.1 (integration) 阅读 TDN / TDN France adapter 与国际来源抓取路径，确认 search item、post API、详情解析和入库字段的当前数据流。
- [x] 1.2 (application) 先补充回归测试：TDN France search item 无日期时必须二次读取 post API，历史旧文必须被过滤，无真实日期必须跳过。
- [x] 1.3 (integration) 实现 TDN France search item 的 post API 日期补齐、无日期跳过和新鲜度过滤，并确保单条失败不拖垮整轮抓取。
- [x] 1.4 (application) 补充或更新抓取摘要测试，确认历史旧文、无日期和详情失败会记录可理解跳过原因。

## 2. 本地验证

- [x] 2.1 (application) 运行针对性 Django 测试，覆盖 TDN France 日期修复和国际来源抓取回归。
- [x] 2.2 (application) 运行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 2.3 (operations) 运行 `openspec validate fix-tdn-france-search-date-freshness --strict`、必要的 `openspec validate --all` 和 `git diff --check`。

## 3. 部署与生产数据处理

- [ ] 3.1 (operations) 部署前记录生产 commit、容器状态、健康检查和数据库备份结果。
- [ ] 3.2 (operations) 将修复代码部署到生产并重建 `web / worker / beat`，确认 `manage.py check` 与 `/healthz/` 通过。
- [ ] 3.3 (operations) 清理已确认误发布的 TDN France 历史旧文，将其撤出公开前台并保留可追溯原因。
- [ ] 3.4 (operations) 重新启用 `NewsSource#21 TDN 法国宽关键词英文新闻`，恢复 `enabled=true` 与 `production_approved=true`。
- [ ] 3.5 (operations) 执行线上回归：只读探测、一次真实抓取或最近窗口审计，确认不会再抓入 2020/2022 等历史旧文。

## 4. 文档与归档

- [ ] 4.1 (operations) 更新 `docs/current_state.md`、`docs/deploy_runbook.md` 和 `docs/project_status.md`，记录修复、清理和重新启用结果。
- [ ] 4.2 (operations) 完成 OpenSpec 归档，确保规格同步到正式 spec。
