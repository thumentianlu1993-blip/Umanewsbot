## Why

运营在审核新闻时经常会在原文里发现需要补入术语库的日文词，但当前流程必须离开文章页、进入术语工作台手工复制创建，打断编辑判断，也容易丢失上下文。

本 change 先解决“选中文本后快速创建正式术语”的最短闭环，让管理员在候选详情或编辑台内选中原文片段，只补中文译词即可写入术语库；保存后重新应用术语或重翻译联动放到后续 change。

## What Changes

- 在候选详情页和文章编辑台的原文参照区支持选中文本后快速加入正式术语库。
- 提供轻量交互入口：选区浮动按钮或右键菜单均可，最终以一个小表单让管理员确认日文原词、选择术语类型、填写中文译词；术语类型默认马名，可由管理员修改。
- 日文原词默认来自当前页面选区；中文译词必须由管理员填写；其他字段使用安全默认值：启用、优先级 0、比赛等级空、别名空、备注自动记录来源文章。
- 后端复用现有 `validate_term_payload()` 校验与 `TermEntry` 创建逻辑，保持与术语工作台、API 和导入一致的重复检查、类型校验、比赛等级校验。
- 保存成功后留在当前文章页面，并给出成功提示。
- 重复术语或校验失败时不创建新记录，页面必须展示明确错误，并尽量给出现有术语编辑入口。
- 该 change 不自动改写当前文章的译文、发布稿、基准翻译稿或自动化状态；术语保存后的重新应用/重翻译联动属于 change3。
- 不新增数据库模型或迁移。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `termbase-and-race-priority`: 正式术语库增加从文章原文选区快速创建术语的后台维护入口。

## Impact

- `server/stable/urls.py`：新增文章上下文里的快速创建术语 POST 路由。
- `server/stable/views.py`：新增或复用术语创建视图逻辑，接收选区原文、中文译词、术语类型和来源文章。
- `server/stable/forms.py` / `server/stable/services/term_admin.py`：必要时补充面向快速创建的轻量表单或服务封装，但必须复用现有校验规则。
- `server/stable/templates/stable/console/candidate_detail.html` 与 `article_editor.html`：原文区域增加选区快速创建术语的交互与弹层/表单。
- `server/stable/templates/stable/console/base.html` 或静态资源：如需要，补充少量页面脚本和样式；不引入前端构建系统。
- `server/stable/tests.py`：新增视图、校验和页面交互基础回归测试。
- `docs/current_state.md`：记录本地实现和验证结论；不涉及生产部署时不更新生产运行态。
