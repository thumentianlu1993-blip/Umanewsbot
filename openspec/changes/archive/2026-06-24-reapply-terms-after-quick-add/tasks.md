## 1. 后端联动能力

- [x] 1.1 (integration) 新增当前文章指定术语应用服务函数，只替换刚创建术语的日文原词和日文别名，对机器翻译字段、基准翻译稿和未人工编辑发布稿字段返回更新字段与跳过字段结果
- [x] 1.2 (application) 新增后台 POST 视图、路由和权限检查，支持对当前文章触发轻量应用指定术语，并用安全上下文返回候选详情页或编辑台
- [x] 1.3 (application) 在术语应用动作中保护 `manually_edited_fields`，默认跳过人工标题、正文、摘要和推送摘要，并通过 messages 告知工作人员
- [x] 1.4 (application) 在指定术语应用动作中记录操作日志，包含文章 ID、触发用户、来源术语、更新字段和跳过字段；页面级重新翻译日志记录文章、触发用户和任务触发结果
- [x] 1.5 (application) 复用现有 `translate_article_task` 保留当前文章上下文的页面级重新翻译入口，触发后只更新翻译状态并提示已派发任务，不自动发布
- [x] 1.6 (application) 限制返回路径：只接受候选详情页或编辑台等站内后台上下文，非法 `next` 或外站 URL 回退到当前文章安全默认页

## 2. 后台页面交互

- [x] 2.1 (application) 在候选详情页快速创建术语成功后保留当前候选上下文；后续展示形态由 5.2 统一调整为只承载当前术语应用的浮层
- [x] 2.2 (application) 在文章编辑台快速创建术语成功后保留当前编辑上下文；后续展示形态由 5.2 统一调整为只承载当前术语应用的浮层
- [x] 2.3 (application) 在候选详情页和编辑台展示指定术语应用结果反馈，包括无变化、已更新字段、已保护人工字段和任务触发状态
- [x] 2.4 (application) 确认首版不提供默认强制覆盖人工字段入口；如代码保留 force 参数，模板不得在普通路径隐式启用
- [x] 2.5 (application) 确认刷新、离开页面或非快速创建成功上下文不会展示上一次术语创建的常驻应用入口

## 3. 测试与验证

- [x] 3.1 (integration) 覆盖指定术语应用服务测试：更新机器翻译字段、更新基准翻译稿、同一术语多次出现全部替换、日文别名可替换、其他正式术语不被重应用、仅影响当前文章、不派发翻译任务
- [x] 3.2 (application) 覆盖人工编辑保护测试：人工标题、正文、摘要和推送摘要默认不被覆盖，未人工编辑发布稿可更新，并返回跳过字段提示
- [x] 3.3 (application) 覆盖后台视图测试：候选详情页和编辑台触发后返回原页面，非法 `next` 回退安全默认页，messages 展示成功、无变化和保护提示
- [x] 3.4 (application) 覆盖一次性入口测试：快速创建成功后展示入口，刷新或非创建成功上下文不展示上一次入口
- [x] 3.5 (application) 覆盖重新翻译入口测试：派发现有翻译任务、使用当前文章、不会因触发重翻译而发布文章
- [x] 3.6 (application) 覆盖操作日志测试：指定术语应用日志包含文章、用户、来源术语、更新字段和跳过字段；页面级重翻译日志包含文章、用户和任务触发结果
- [x] 3.7 (operations) 运行 `DB_ENGINE=sqlite python manage.py check`
- [x] 3.8 (operations) 运行相关 `stable` 测试，必要时运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`
- [x] 3.9 (operations) 运行 `openspec validate reapply-terms-after-quick-add --strict`

## 4. 文档与交付

- [x] 4.1 (operations) 更新 `docs/current_state.md`，记录本 change 的实现范围、验证结果和未上线状态
- [x] 4.2 (operations) 如后续涉及生产部署，更新 `docs/deploy_runbook.md` 的部署和回滚注意事项

## 5. Review 后交互修正

- [x] 5.1 (application) 将 quick-term follow-up session 从全局单槽改为多 pending 结构，避免多标签页互相覆盖；渲染不匹配文章或不匹配上下文时不得消费其他 pending follow-up
- [x] 5.2 (application) 将候选详情页和编辑台的内嵌后续动作面板改为页面上方浮层，文案为 `术语【日文名（中文名）】已添加，点击此处立即应用到文章中`；浮层只承载应用当前术语，删除 `retranslate-created-term-*` follow-up 表单/按钮，重新翻译沿用页面级按钮且不新增浮层入口
- [x] 5.3 (application) 实现浮层关闭 icon、15 秒自动消失、点击应用后消失，以及当前页面新浮层替换旧浮层
- [x] 5.4 (application) 保证浮层不阻塞当前页面选区、滚动、编辑和其他不离开页面的点击行为
- [x] 5.5 (application) 补充多标签页 pending follow-up、渲染不匹配页面不消费 pending、浮层文案、旧内嵌面板不存在、`retranslate-created-term-*` 不存在、关闭、超时、点击应用无需二次确认和刷新后不补显示的测试（TDD 红灯测试已写入，待实现转绿后勾选）
- [x] 5.6 (operations) 重新运行 `DB_ENGINE=sqlite python manage.py check`、相关 `stable` 测试和 `openspec validate reapply-terms-after-quick-add --strict`
