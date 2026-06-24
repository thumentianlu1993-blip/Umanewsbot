## Why

`add-selection-term-quick-add` 让工作人员可以在候选详情页或编辑台快速把原文片段加入正式术语库，但术语创建成功后，当前文章的译稿并不会变化。工作人员仍需要手动判断应该重新应用术语、重新翻译，或保持当前稿件不动。

这个 change 解决“补完术语后如何让当前稿件立刻吃到新术语”的下一步工作流，降低人工复制和重复点击成本，同时避免自动覆盖正在编辑的稿件。

## What Changes

- 在文章上下文快速创建术语成功后，通过页面上方浮层提供一次性的“应用到当前稿件”动作；错过该成功反馈后不补充常驻入口。
- 支持两类能力，但交互层级必须严格分离：
  - 轻量应用新术语：仅将刚创建的术语应用到当前文章整篇已有中文稿/基准翻译稿中，不重新调用翻译模型，不重新应用整个术语库。
  - 页面级手动重新翻译：沿用现有翻译任务，让当前文章重新走翻译与术语提示链路；该能力不放入术语成功浮层，若页面已有按钮则不新增。
- 在候选详情页和文章编辑台展示术语创建后的浮层后续动作入口与状态反馈；浮层可点击应用、手动关闭或 15 秒后自动消失。不得继续使用术语表单内部的内嵌后续动作面板。
- 移除术语成功上下文中的“重新翻译”follow-up 表单或按钮；候选详情页/编辑台原有页面级重新翻译入口如已存在则保留原位。
- 保护人工编辑稿：不得在无确认的情况下覆盖工作人员正在编辑或已经手动修改的发布稿。
- 记录操作日志，保留“哪篇文章因哪个新增术语触发了术语应用”的审计线索；页面级重新翻译继续记录任务触发日志。
- 不引入批量全站重翻译，不自动发布文章，不修改公开前台展示规则。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `termbase-and-race-priority`：新增文章上下文中创建术语后的轻量应用要求，并明确页面级重新翻译入口与术语成功浮层分离，使正式术语库更新能安全作用于当前文章译稿。

## Impact

- 后台视图、表单与模板：
  - `server/stable/views.py`
  - `server/stable/forms.py`
  - `server/stable/urls.py`
  - `server/stable/templates/stable/console/candidate_detail.html`
  - `server/stable/templates/stable/console/article_editor.html`
- 术语与翻译服务：
  - `server/stable/services/terms.py`
  - `server/stable/services/translation.py`
  - `server/stable/tasks.py`
- 测试：
  - `server/stable/tests.py`
- 文档：
  - `docs/current_state.md`
  - 如涉及生产部署，再更新 `docs/deploy_runbook.md`
