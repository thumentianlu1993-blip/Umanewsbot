## Why

当前自动发布链路把 AI 改写校验中的多类 warning 当作硬性失败，导致高价值新闻即使评分足够高，也会因为片假名误判、背景术语省略、数字摘要化或引语较多被转入人工审核。近期候选池样本显示，`タイトル`、`メートル`、`オッズ`、`ハンデ` 等普通词被识别为未收录马名，数字一致性和背景术语校验也产生大量误伤，阻碍自动化运营进入稳定可用状态。

本变更目标是在不降低基础内容安全的前提下，重新定义自动发布门禁：用 blocker / warning / info 区分风险，把真正不能发布的问题挡住，把需要关注但不应阻断的事项记录并通知人工。

## What Changes

- 新增自动发布门禁分级：`blocker` 阻断发布，`warning` 初期不阻断但记录并可告警，`info` 仅用于诊断。
- 自动发布链路支持短期关闭 AI 改写前置，使用基准翻译稿作为自动发布内容来源。
- 删除“长采访或引语较多”作为硬性门禁；引语较多改为 warning。
- 删除“数字一致性校验失败”作为硬性门禁；数字省略改为 warning 或 info。
- 高价值来源支持配置化评分放行；首批范围为 `netkeiba` 访问量榜和 `netkeiba` 注目数榜。
- warning 初期不阻断自动发布，但高价值文章出现 warning 时发送邮件告警，默认收件人 `754652181@qq.com`。
- 关键术语校验改为分层规则：标题、摘要、首段和高优先级术语更严格，正文背景术语缺失降级为 warning。
- 未收录马名未原样保留保留为校验项，但在马名识别准确性未提升前降级为 warning。
- 引入非马名普通词 / 固定译法种子，避免 `タイトル`、`メートル`、`オッズ` 等片假名普通词继续触发未知马名硬失败。
- 新增重复内容检测门禁，避免跨来源或相似来源文章与已发布内容高度重合后重复发表；高度重复文章使用独立重复内容状态，不再混入普通忽略。
- 后台候选详情和日志展示结构化门禁结果、warning 和阻断原因，避免“评分 100 但需人工审核”的原因不可见。
- 不在本 change 实现“新闻编辑区选中文本快速加入术语库”；该能力后续拆为独立 change。

## Capabilities

### New Capabilities

- `automation-publish-gates`: 自动发布评分、门禁分级、warning 告警、基准翻译发布、高价值来源放行和重复内容拦截。

### Modified Capabilities

- `termbase-and-race-priority`: 术语校验将读取普通词 / 固定译法种子，并按核心术语与背景术语区分校验等级。

## Impact

- 代码影响：
  - `server/app/settings.py`：新增自动发布门禁、改写开关、高价值来源、warning 邮件等配置。
  - `server/stable/models.py` 与迁移：新增校验结果字段、重复内容字段和 `WorkflowStatus.DUPLICATE`。
  - `server/stable/services/automation.py`：调整评分放行、硬门禁和自动发布就绪判定。
  - `server/stable/services/validation.py`：改为结构化 issue 输出，支持 blocker / warning / info。
  - `server/stable/services/notifications.py` 与 `server/stable/tasks.py`：新增高价值 warning 告警触发。
  - `server/stable/services/terms.py`：加入非马名词过滤和术语校验归一化。
  - `server/stable/views.py`、模板和后台列表：展示结构化校验结果。
  - `server/stable/tests.py`：覆盖新门禁、warning 不阻断、邮件告警、重复内容和配置化来源规则。
- 数据影响：
  - 可能新增迁移。
  - 固定译法 / 非马名普通词可通过数据迁移或 seed 管理命令导入。
- 运维影响：
  - `.env.example` 与部署文档需补充新开关。
  - 生产启用建议先低批量观察 warning 邮件和自动发布结果。
