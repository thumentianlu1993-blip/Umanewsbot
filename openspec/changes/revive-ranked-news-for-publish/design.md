## Context

当前抓取入库链路已经能识别同一篇文章从普通来源进入榜单来源：`upsert_article_from_draft()` 会在既有文章从 `latest` 提升到 `access / attention` 等榜单模式时返回 `source_elevated=true`，并更新文章主来源。已发布文章在该信号出现时会触发 QQ 自动推送编排。

缺口在未发布文章：如果文章首次抓取时因为低分、翻译失败或转人工而没有发布，后续进入榜单只会更新来源标签，不会自动重新翻译、重新评分，也不会按榜单信号重新进入发布窗口。多地区窗口已经具备候选决策账本，因此本变更应复用现有流水线和窗口账本，而不是新增直接发布路径。

## Goals / Non-Goals

**Goals:**

- 让榜单二次命中成为未发布文章的“唤醒”信号。
- 允许低分忽略、价值不足转人工、翻译失败或待翻译文章在榜单命中后重新进入正常自动化流水线。
- 翻译失败或未翻译成功时自动触发一次受控翻译重试。
- 翻译成功后重新评分，使榜单来源的高价值配置真正影响发布候选状态。
- 发布窗口按榜单唤醒时间重新拾取候选，并在窗口决策中保留唤醒来源。
- 保持硬门禁、人工拒绝、撤回、重复 blocker、发布配额和 QQ 限流不被绕过。

**Non-Goals:**

- 不新增人工运营 UI。
- 不改变 QQ 推送的群级地区、范围、重点策略或限流模型。
- 不让榜单命中直接发布文章。
- 不自动复活人工明确拒绝、已撤回、已发布或高度重复 blocker 文章。
- 不调整各新闻源抓取频率或榜单来源清单。

## Decisions

### 1. 榜单唤醒作为抓取 upsert 后的编排步骤

当 `upsert_article_from_draft()` 返回 `source_elevated=true` 时，抓取任务应分流：

- 已发布文章：保持当前 QQ 补推逻辑。
- 未发布文章：执行榜单唤醒服务。

备选方案是在发布窗口里检查 `NewsSnapshot` 是否出现榜单快照。这个方案会让发布窗口承担过多抓取语义，也难以及时触发翻译重试。选择 upsert 后编排，是因为来源升级信号在这里最准确，且已有抓取任务已经处理 `source_elevated`。

### 2. 使用显式唤醒元数据驱动候选窗口

榜单唤醒必须写入稳定元数据，例如 `decision_reason.ranked_revival`，包含：

- `revived_at`
- `source_site`
- `source_mode`
- `previous_workflow_status`
- `previous_automation_status`
- `action`

发布窗口候选查询应把“首次入库时间在回看范围内”扩展为“首次入库时间或最近榜单唤醒时间在回看范围内”。如果 JSON 查询在 SQLite / PostgreSQL 上实现复杂或不可维护，实施时可以新增 `ranked_revived_at` 之类的轻量字段和迁移，避免依赖脆弱 JSON 查询。

备选方案是直接更新 `first_seen_at`。不采用该方案，因为 `first_seen_at` 是文章首次进入系统的事实时间，改写它会污染审计和来源新鲜度判断。

### 3. 复用自动化评分和校验，不新增榜单专用发布通道

榜单唤醒后，系统只负责把文章送回既有流水线：

- 翻译失败或未翻译：派发翻译任务。
- 已翻译：重新执行评分。
- 评分后仍需通过现有发布准备、校验和窗口选择。

这样可以让 `HIGH_VALUE_SOURCE_RULES`、`AUTO_REVIEW_THRESHOLD`、`gate_issues`、地区/来源自动发布策略和发布窗口配额继续统一生效。

### 4. 可复活状态白名单

榜单唤醒只处理尚未发布且没有人工终态的文章。第一版允许：

- `workflow_status=ignored` 且原因为低分或价值不足。
- `workflow_status=pending_review` 且 `automation_status=manual_review_required`，并且不是人工拒绝或硬 blocker。
- `workflow_status=translation_failed`。
- `workflow_status=pending_translation` 或翻译状态未成功。

第一版不复活：

- `published`
- `withdrawn`
- `rejected`
- `duplicate`
- 明确人工编辑拒绝或撤回的文章
- 具有当前 blocker 的文章

### 5. 翻译重试必须受控且幂等

榜单唤醒触发翻译重试时，必须避免同一篇文章在多个榜单来源或重复抓取中反复派发翻译任务。可通过唤醒元数据记录最近重试时间、重试原因和任务 ID，或复用已有翻译任务状态判断。

翻译重试失败后不应反复刷屏；失败原因继续保存在文章翻译状态、自动化状态和通知/窗口账本中。

## Risks / Trade-offs

- [Risk] 榜单来源重复抓取导致同一文章多次唤醒。  
  Mitigation: 以文章 ID 加唤醒状态幂等判断；已处于翻译中、已重新评分或最近已唤醒的文章不重复派发同类任务。

- [Risk] 低质量文章因榜单信号被过度发布。  
  Mitigation: 榜单只提升评分信号，不绕过翻译成功、正文完整、核心术语、重复检测和地区/来源自动发布策略。

- [Risk] 发布窗口 JSON 查询唤醒时间性能或兼容性不好。  
  Mitigation: 如果实现中查询复杂，新增索引友好的 `ranked_revived_at` 字段；保持迁移小且可回滚。

- [Risk] 翻译失败文章进入榜单后增加模型调用量。  
  Mitigation: 只在 `source_elevated=true` 且文章可复活时重试；同一篇文章同一轮唤醒只触发一次重试。

## Migration Plan

1. 本地实现并完成 SQLite 测试；如新增字段，生成 Django migration。
2. 部署前确认当前生产无长时间运行中的导入或部署冲突任务。
3. 部署后运行迁移、`manage.py check`、目标测试和健康检查。
4. 观察生产窗口账本：确认榜单唤醒候选、翻译重试、重新评分和发布窗口决策均可追溯。

Rollback 策略：

- 如未新增字段：回滚代码即可，已有 JSON 元数据不影响旧逻辑。
- 如新增 `ranked_revived_at` 字段：回滚代码后字段可保留不用；必要时后续单独清理迁移。

## Open Questions

- 实施时是否需要新增 `ranked_revived_at` 字段，取决于现有 JSON 元数据查询能否保持清晰、可测且跨 SQLite / PostgreSQL 稳定。
