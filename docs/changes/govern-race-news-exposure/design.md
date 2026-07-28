# design：赛事新闻聚类与首页 / QQ 曝光治理

## 现状

- `NewsArticle.duplicate_of/duplicate_score/duplicate_reason` 表达内容重复。
- `ArticleRaceLink` 已能把文章关联到 `RaceEvent`，并区分 candidate / confirmed。
- `select_publish_candidates()` 只在当前候选池内用 `content_fingerprint()` 去重。
- `resolve_homepage_headline()`、首页 queryset、热门榜和 QQ 窗口各自选择，缺少共享赛事预算。
- `QQPushDelivery` 只保证同一文章和目标群不重复发送。

## 总体设计

新增独立的“分发曝光层”，不改变文章公开状态：

```text
公开合格文章
  -> 主赛事身份解析（fail closed）
  -> 硬重复判断
  -> 角度分类
  -> RaceNewsExposurePolicy
       -> 首页 site 两席（头条计入）
       -> QQ 每 target 两席
  -> 首页/热门榜过滤或 QQ delivery
  -> 赛事详情仍读取全部公开文章
```

## 数据模型

新增 `RaceNewsExposure`：

- `event`、`article`
- `channel`: `homepage / qq`
- `scope_key`: 首页固定 `site`；QQ 为 `target:<id>`
- `slot`: `1 / 2`
- `status`: `waiting / active / replaced / sent / suppressed`
- `angle`
- `policy_version`
- `reason`、`evidence` JSON
- `activated_at`、`replaced_at`
- `replaced_by` 可空自关联
- `delivery` 可空一对一关联、`lease_expires_at`

约束：

- 同一 `(event, channel, scope_key, article)` 唯一；
- 首页对 `waiting/active` 的 `(event, channel, scope_key, slot)` 建立条件唯一约束；
- QQ 对 `waiting/active/sent` 的 `(event, channel, scope_key, slot)` 建立单独条件唯一约束，使已发送
  席位由数据库保持终身占用；
- `slot` 只允许 1 或 2，channel/scope 组合必须合法。

首页第二席替换时，在同一事务中锁定赛事/作用域两席，将旧记录置为 `replaced`，再激活新记录。
第一席一旦激活不由自动策略替换。

## 主赛事身份

解析优先级：

1. 唯一 `status=manual` 的 `ArticleRaceLink`；
2. 不存在 manual 冲突时，唯一达到可靠阈值的 `status=auto` link，且年份、地区、赛事日期窗口
   均一致；
3. 否则 unresolved。

`candidate/removed` 不构成身份依据。不得仅按名称字符串跨年度聚类；存在多个 manual、多个合格
auto，或 manual 与 auto 指向不同赛事时均 unresolved。`link_type=post_race` 只描述稿件关系，
不等于主身份优先级。术语别名只帮助发现候选，最终身份仍是 `RaceEvent.id`。

## 硬重复

新增共享 `RaceNewsDuplicateClassifier`，先执行确定性规则：

1. 同来源文章 ID 唯一约束；
2. 同赛事内规范化来源标题完全相同；
3. 现有内容指纹相同；
4. 经校准的近似阈值。

前两项为硬规则，不受窗口相似度阈值影响。硬重复 winner 可按可信度、正文完整度、发布时间与 ID
稳定排序。loser 记录 `duplicate_of` 和证据，但不取得曝光席位。不同角度只能影响曝光预算，不写
`duplicate_of`。

## 角度分类

优先使用结构化证据：标题实体、赛果语义、人物/马匹焦点和已确认赛事关联。允许模型提供候选标签，
但输出必须在固定枚举内并保存 evidence；冲突或低置信统一降为 `other`。

第二席必须满足：

- 第一席生效已满 15 分钟；
- 非硬重复；
- 角度与第一席明确不同；
- 达到既有发布门禁和第二席质量阈值。

排序键固定为：质量门禁等级、`score_total`、角度置信度、`published_at`、`id`。

## 首页与头条

首页 queryset 先取得公开文章，再批量预取有效 `homepage/site` exposure：

- 有可靠赛事身份的文章只有 active 席位可进入首页和热门榜；
- 无可靠赛事身份的普通新闻沿用现状；
- 赛事详情页不应用此过滤。

头条解析器必须在同一策略层预留/占用席位。手工头条选择保持权限与版本 CAS，但在事务内同步曝光：
若同赛事已满两席，手工稿替换第二席并留下审计；若只有第一席，仍须等第一席满 15 分钟才可占
第二席。等待期内给编辑明确冲突提示，不用手工操作暗中绕过两席节奏；不得形成第三席。

## QQ

即时 QQ 与窗口 QQ 都先调用同一 `reserve_exposure(event, target)`：

- 第一席可立即保留；
- 第二席遵守 15 分钟和角度差异；
- `QQPushDelivery` 成功发送后 exposure 置 `sent`；
- 发送失败重试复用原 exposure / delivery；
- 两席已发送后返回 `race_exposure_limit`。

现有地区、类别、群级和站点级额度仍先后生效。赛事席位、quota ledger 与 delivery 的创建/绑定在
同一数据库事务内完成，事务中不调用 OneBot。worker 发送成功后把 exposure 置 `sent`；进程崩溃
或可确认未发送的终态失败由 lease 回收并释放席位。若请求结果不明或已经取得 message ID，则
fail closed 保留席位并进入人工核对，避免以“重试”制造第三次实际发送。

## 并发、性能与可观测性

- 使用事务和 `select_for_update()` 锁定同一 event/channel/scope 的记录。
- 首页按当前页文章 ID 一次预取，不逐文查询赛事链接或 exposure。
- 以首页 50 篇候选为测试形状，赛事链接与 exposure 的额外查询固定不超过 3 次；以 QQ 100 篇
  候选、5 个目标群为测试形状，禁止 article × target 查询，选择阶段本地 PostgreSQL 基准不超过
  5 秒。生产 shadow 的首页 p95 不得比关闭策略时恶化超过 20%。
- 窗口决策 payload 增加 `event_id / angle / exposure_slot / exposure_reason / policy_version`。
- 运营后台按赛事显示首页两席、QQ 各群两席、等待/抑制/替换记录。
- 指标至少包括 unresolved identity、hard duplicate、slot wait、slot selected、slot replaced、
  race exposure limit。

## 开关

- `RACE_NEWS_EXPOSURE_ENABLED=false`
- `RACE_NEWS_EXPOSURE_SHADOW=true`
- `RACE_NEWS_SECOND_SLOT_DELAY_MINUTES=15`
- `RACE_NEWS_HOMEPAGE_MAX=2`
- `RACE_NEWS_QQ_TARGET_MAX=2`

shadow 只记录建议，不影响首页或 QQ。enforce 前必须核对 shadow 计数和英皇锦标样本。

## 迁移与回滚

- schema migration 只建表、约束和索引，不回填。
- 历史 exposure 回填由独立命令生成 dry-run manifest；默认不写库。
- 代码回滚先关 enforce；旧 exposure 保留为审计，不影响现有查询。
- migration 回滚只有在确认没有其他版本依赖且已备份后执行，正常回滚不删表。

## 与术语变更的关系

本变更以 `RaceEvent.id` 为权威，不依赖中文字符串聚类。`unify-public-racing-terms` 提升别名候选发现
和公开显示一致性，但不得成为放宽赛事身份门禁的理由。
