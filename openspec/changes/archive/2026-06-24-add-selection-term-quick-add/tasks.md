## 1. 后端快速创建入口

- [x] 1.1 (application) 新增文章上下文快速创建术语的表单或服务封装，复用 `validate_term_payload()`，支持 `selected_text/source_ja`、`term_type`、`target_zh`、`next` 和来源文章备注。
- [x] 1.2 (application) 新增后台 POST 视图，校验 staff 权限、文章存在性、空选区、过长选区、中文译词必填和重复术语。
- [x] 1.3 (application) 新增 `server/stable/urls.py` 路由，例如 `candidates/<article_id>/quick-term/` 或 `articles/<article_id>/quick-term/`。
- [x] 1.4 (application) 创建成功时写入 `TermEntry`，记录操作日志，并通过 messages 提示术语已创建。
- [x] 1.5 (application) 创建失败时不写入 `TermEntry`，返回当前文章页面并展示字段级或摘要错误；重复术语尽量提供已有术语编辑入口。

## 2. 后台页面交互

- [x] 2.1 (application) 在 `candidate_detail.html` 的原文标题/正文区域增加可选区快速添加术语的入口和表单。
- [x] 2.2 (application) 在 `article_editor.html` 的来源参照区增加同等入口和表单。
- [x] 2.3 (application) 添加轻量 JavaScript：只读取原文容器内选区、裁剪空白、填入快速表单，并显示“加入术语库”按钮或弹层。
- [x] 2.4 (application) 保留无 JavaScript fallback：管理员可手工粘贴日文原词并提交。
- [x] 2.5 (application) 页面文案明确快速创建只写入术语库，不会自动重新翻译或改写当前文章。

## 3. 测试与验证

- [x] 3.1 (application) 增加视图测试：staff 用户从候选详情页快速创建术语成功，默认字段正确，默认类型为马名，备注或日志包含来源文章 ID。
- [x] 3.2 (application) 增加视图测试：staff 用户从编辑台上下文快速创建术语成功后返回编辑台。
- [x] 3.3 (application) 增加校验测试：中文译词为空、空选区、过长选区和重复 `term_type + source_ja` 均拒绝创建。
- [x] 3.4 (application) 增加权限测试：未登录用户和非 staff 用户不能快速创建术语。
- [x] 3.5 (application) 增加非联动测试：快速创建术语成功后不触发 `translate_article_task`，且不修改当前文章中文稿、基准翻译稿或改写稿。
- [x] 3.6 (application) 增加模板回归测试：候选详情页和编辑台包含快速创建术语入口、CSRF、必要隐藏字段、默认马名类型、原文选区容器标记和“不自动重翻译”提示。
- [x] 3.7 (operations) 执行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 3.8 (operations) 执行相关 `stable` 测试，必要时执行全量 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 3.9 (operations) 执行 `openspec validate add-selection-term-quick-add --strict`。

## 4. 文档与交付

- [x] 4.1 (operations) 更新 `docs/current_state.md`，记录 change2 本地实现、非联动边界和验证结果。
- [x] 4.2 (operations) 如生产部署涉及该能力，更新 `docs/deploy_runbook.md` 的验收入口；仅本地 proposal/实现阶段不写生产已上线结论。
- [x] 4.3 (operations) 浏览器验收候选详情页和文章编辑台：选中原文、创建术语、重复术语提示、返回当前页面。
