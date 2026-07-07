## 1. 法国候选源探测

- [x] 1.1 (integration) 梳理现有法国来源 `france_galop_news`、`tdn_france` 的 adapter、去重和生产窗口表现，形成基线。
- [x] 1.2 (integration) 调研并列出法国候选新闻源短名单，优先选择公开、稳定、低反爬、与法国赛马强相关的来源，并记录候选 URL。
- [x] 1.3 (integration) 扩展或新增只读探测命令，输出 HTTP 状态、列表样本、详情样本、重复比例、访问限制和解析质量。
- [x] 1.4 (integration) 对候选源执行真实只读探测，保存样本证据和 deferred / accepted 结论；若没有至少 1 个 accepted 新来源，则输出 no-go 审计并停止生产接入。

## 2. 来源接入与生产灰度

- [x] 2.1 (integration) 为通过探测的法国来源实现或完善 adapter，正确解析标题、正文、发布时间、原文 URL、语言、地区和 metadata；若来源语言当前不受支持，先补齐语言链路测试或保持 deferred。
- [x] 2.2 (application) 更新 `SourceSite` / `NewsSource` 同步定义或等价来源配置；如新增枚举或字段选择值，补充迁移，且新增法国来源默认保持可灰度控制。
- [x] 2.3 (integration) 确保新增法国来源复用 URL / source_article_id 去重，并记录 canonical source site 和 discovered source metadata。
- [x] 2.4 (application) 扩展来源健康和生产审计，区分无新稿、重复旧稿、解析失败、访问受限和入库后门禁阻断。
- [x] 2.5 (operations) 更新 `.env.example` 或部署文档中新增法国来源的灰度启用、停用和回滚步骤。

## 3. 测试与验证

- [x] 3.1 (application) 补充新增法国 adapter 的 fixture 测试，覆盖列表解析、详情解析、空样本和单篇详情失败继续处理。
- [x] 3.2 (application) 补充 `NewsSource` 同步和生产批准开关测试，确认未批准来源不进入生产窗口。
- [x] 3.3 (application) 补充审计输出测试，覆盖法国来源成功无新增、解析失败和入库后门禁阻断。
- [x] 3.4 (operations) 执行 `DB_ENGINE=sqlite python manage.py check`、目标测试、`openspec validate expand-france-news-sources --strict`、`openspec validate --all` 和 `git diff --check`。
- [ ] 3.5 (operations) 上线前执行真实只读探测并保存结果，确认至少 1 个新增法国来源 accepted；上线后观察法国最近若干窗口的抓取成功率、新增量、重复量、候选量和公开量。
- [x] 3.6 (operations) 更新 `docs/current_state.md`、`docs/project_status.md` 和 `docs/deploy_runbook.md`，记录法国新增来源、启用状态、验收结果和后续风险。
