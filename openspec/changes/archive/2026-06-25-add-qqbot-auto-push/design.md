## Context

当前公开站点已经使用 `workflow_status=PUBLISHED` 与 `published_to_web_at` 暴露文章列表和详情页，自动化内容运营也会把符合条件的文章发布到网页端。仓库内已有 OneBot HTTP 客户端 `stable.services.onebot.BotPusher`、手动推送服务 `stable.services.pushing`、群配置 `PushTarget`、推送日志 `PushLog`、Django Admin 手动推送入口和 `push_article_task`，但这些能力仍以手动触发为主，不能保证“公开 URL 可访问后自动推送到多个群”。

本变更要在不重构 Django 单体、Celery、Docker Compose 主架构的前提下，把 QQ 群推送纳入发布后的自动分发链路。生产阶段继续采用低成本同机部署，Django/Celery 通过 Docker 内网或本机回环地址访问 OneBot v11 HTTP 网关。

## Goals / Non-Goals

**Goals:**

- 文章公开详情页 URL 可访问后，自动向多个启用 QQ 群发送中文标题、摘要和站内链接。
- 支持 `QQ_PUSH_SCOPE=high_value_only` 与 `QQ_PUSH_SCOPE=all_public`，默认只推高价值新闻。
- 对每个“文章 x 群”维护唯一自动交付记录，避免重复推送并保留失败原因。
- 支持有限次重试，失败不阻断文章发布或公开网站访问。
- 通过 Django Admin 配置群、查看交付状态和排查失败。
- 补充同机 OneBot 部署、安全配置、灰度启用和验收文档。

**Non-Goals:**

- 不实现原生 QQ 协议登录，也不把业务代码绑定到某个 QQ 客户端框架内部。
- 不做后台人工审核按钮、撤回消息、重推按钮或复杂运营编排。
- 不做定时汇总推送、消息节流队列、A/B 群策略或多渠道统一通知平台。
- 不在本变更中接入 HTTPS 证书或重做生产 Nginx 主入口。
- 不移除现有手动推送入口和 `PushLog` 历史日志。

## Decisions

### 1. 使用新增自动交付表，而不是直接复用 `PushLog`

新增 `QQPushDelivery` 或等价模型，字段包含 `article`、`target`、`status`、`attempt_count`、`max_attempts`、`last_error`、`message_id`、`response_payload`、`last_attempt_at`、`sent_at`，并加唯一约束 `article + target`。

理由：

- `PushLog` 当前更像一次手动推送尝试日志，允许多次创建，不适合作为去重状态机。
- 自动推送需要稳定的幂等键，Celery 重试、重复发布触发或 worker 重启时都应复用同一条交付记录。
- 保留 `PushLog` 可以降低对既有后台手动推送的影响。

备选方案：

- 直接给 `PushLog` 增加唯一约束：会改变既有手动推送语义，也可能影响历史排查。
- 在 `NewsArticle` 上记录整体推送状态：无法表达多群部分成功、部分失败。

### 2. 发布入口统一调用自动推送编排函数

新增 `enqueue_qq_auto_push_for_article(article_id)` 或等价服务函数，由人工发布和自动发布成功后调用。该函数只负责入队，不直接访问 OneBot，避免发布事务被外部服务拖慢。

人工发布入口包括运营后台编辑发布和 `publish_article()` helper；自动发布入口包括 `publish_article_automatically()`。实现时必须查找所有设置 `workflow_status=PUBLISHED` 与 `published_to_web_at` 的路径，避免漏推。

### 3. 公开 URL 检查放在 Celery 编排任务中

编排任务基于 `SITE_URL + article.public_path` 构造公开链接，并在发送前检查公网 URL。检查允许最终返回 `200`，允许跟随重定向，设置短超时；失败时按有限次数重试。

理由：

- 用户点击 QQ 消息时应能打开网页，不能只依赖数据库状态。
- URL 检查与 OneBot 发送都属于外部 I/O，适合异步执行。

备选方案：

- 发布时同步检查 URL：会增加后台发布延迟，也会把网络波动带进发布链路。
- 不检查 URL：实现简单，但容易推送 404 或缓存未就绪页面。

### 4. 高价值策略复用现有自动运营字段

默认 `QQ_PUSH_SCOPE=high_value_only`。高价值判断首版使用唯一口径：`score_total >= AUTO_REVIEW_THRESHOLD`。`review_mode` 可以作为后台排查信息保留，但不参与首版自动 QQ 推送资格判断。实现时以统一函数 `should_push_news_to_qq(article)` 收敛。

当 `QQ_PUSH_SCOPE=all_public` 时，只要求文章已公开且 URL 可访问。当 scope 配置非法时，应保守回退到 `high_value_only` 并记录日志。

### 5. 自动推送目标只看启用状态

自动推送读取所有 `PushTarget.is_active=True` 的群目标，不使用 `is_default` 过滤。`is_default` 继续服务现有手动推送入口中“不选择目标时默认推送”的语义。

### 6. 自动推送消息只发送站内内容链接

消息模板：

```text
【UmaFans】<有效中文标题>
<有效中文摘要或正文截断>……
阅读全文：<SITE_URL + public_path>
```

摘要优先使用 `effective_summary`，但当有效摘要为空时从 `effective_body` 截断；自动生成的截断摘要使用中文省略号 `……`。消息不再使用上游原文链接作为主要入口。

### 7. URL 检查失败和发送失败必须可区分

公开 URL 暂不可访问时，交付记录可以进入等待重试或最终失败状态，但最近错误类型必须能标识为 `url_unavailable`。OneBot 请求失败、超时或返回错误时，最近错误类型必须能标识为 `send_failed`。后台列表和日志需要能帮助工作人员区分“页面还没通”和“机器人发不出去”。

### 8. OneBot 使用 HTTP 网关，生产默认同机内网访问

Django/Celery 只调用 OneBot v11 HTTP API `/send_group_msg`。推荐生产先使用 NapCatQQ 作为 OneBot 实现，Lagrange.OneBot 作为备选，go-cqhttp 不作为新项目推荐方案。

Compose 示例应避免把 OneBot API 暴露到公网。若必须映射端口，只绑定 `127.0.0.1:3000:3000`；更推荐只在 Docker 网络内通过 `http://onebot:3000` 访问，并配置 access token。

## Risks / Trade-offs

- [Risk] QQ 账号风控、掉线或群权限变化导致发送失败。 → [Mitigation] 交付记录保留失败原因，有限重试，不阻断网站发布；文档要求先测试群灰度。
- [Risk] 公开 URL 检查依赖公网链路，短时网络抖动会延迟推送。 → [Mitigation] 设置短超时和有限重试，最终失败可在后台筛选。
- [Risk] 自动发布批量任务可能短时间产生多条 QQ 消息。 → [Mitigation] MVP 默认 `high_value_only`，后续如刷屏再独立增加节流或汇总 change。
- [Risk] OneBot API 暴露公网会带来滥发风险。 → [Mitigation] Compose 和文档默认 Docker 内网或 `127.0.0.1`，并要求 token；日志不得打印 token。
- [Risk] 复用 `score_total` 作为高价值判断可能受自动评分质量影响。 → [Mitigation] 通过 `QQ_PUSH_SCOPE` 可切换策略；实现时集中到一个判断函数，后续可独立演进。

## Migration Plan

1. 本地实现并新增迁移，部署前保持 `QQ_PUSH_ENABLED=false`。
2. 生产部署代码和迁移，确认 `web/worker/beat` 正常，后台能看到自动推送交付模型。
3. 在 Django Admin 配置 `PushTarget` 群号，先使用测试群。
4. 同机启动 OneBot 网关，配置 `ONEBOT_BASE_URL`、`ONEBOT_ACCESS_TOKEN` 和 `QQ_PUSH_SCOPE=high_value_only`。
5. 手动或通过单篇文章触发灰度验证，确认 URL 检查、发送、交付记录和失败日志。
6. 将 `QQ_PUSH_ENABLED=true` 并重启 `worker/beat`，观察测试群；稳定后再启用正式群。

回滚策略：

- 快速停用：设置 `QQ_PUSH_ENABLED=false` 并重启 `worker/beat`。
- OneBot 故障：停止 OneBot 容器或清空启用群，不影响公开站点。
- 代码回退：按现有部署回滚流程回退应用代码；新增交付表可保留，不影响旧代码主链路。

## Open Questions

- NapCatQQ 生产镜像和配置文件路径需在实施/联调时按实际部署方式确认。
- 公开 URL 检查是否使用外网域名访问，还是容器内访问 Nginx 入口，需要结合服务器网络和 `SITE_URL` 实测。
- 后续是否需要后台“重推失败项”按钮，本变更先不实现。
