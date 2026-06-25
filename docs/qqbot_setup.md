# QQ Bot 配置教程

## 1. 当前 QQ 推送能力状态

当前项目已经实现两条 QQ 推送链路：

- 自动推送：文章公开详情页 URL 可访问后，按配置自动推送到所有启用 QQ 群。
- 手动推送：工作人员仍可在 Django Admin 中手动选择群或使用默认群推送。

自动推送默认关闭：

```env
QQ_PUSH_ENABLED=false
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
```

生产应先配置 OneBot、测试群和后台群目标，再灰度开启。

## 2. 推荐接入方式

推荐路线：

- QQ 客户端侧：`NapCatQQ`
- 协议侧：`OneBot v11`
- 项目侧：HTTP API 调用 `/send_group_msg`

不建议把业务逻辑直接绑死到某个 QQ 框架内部实现。`go-cqhttp` 不作为新接入推荐方案。

## 3. 生产安全边界

OneBot API 具备发群消息能力，不能公网裸露。

同机部署时优先使用 Docker 内网：

```env
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_ACCESS_TOKEN=change-this-token
ONEBOT_TIMEOUT_SECONDS=30
```

如果临时映射到宿主机，只允许绑定回环地址：

```yaml
ports:
  - "127.0.0.1:3000:3000"
```

不要使用 `0.0.0.0:3000:3000` 对公网开放。

## 4. 自动推送配置

`.env` 中的关键项：

```env
QQ_PUSH_ENABLED=false
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_ACCESS_TOKEN=change-this-token
ONEBOT_TIMEOUT_SECONDS=30
```

含义：

- `QQ_PUSH_ENABLED`：自动推送总开关，默认关闭。
- `QQ_PUSH_SCOPE`：`high_value_only` 只推重点新闻；`all_public` 推所有公开且无 blocker 的新闻。
- `QQ_PUSH_IMPORTANCE_STRATEGY`：重点新闻判定方式，本期只支持 `ranked`。
- `QQ_PUSH_MAX_ATTEMPTS`：每篇新闻对每个群最多尝试次数，默认 3。
- `QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS`：推送前检查公开详情页 URL 的超时。
- `QQ_PUSH_SENDING_STALE_SECONDS`：`sending` 状态超过该秒数仍未更新时，允许后续任务重新领取该交付记录，默认 600。
- `ONEBOT_TIMEOUT_SECONDS`：调用 OneBot HTTP API 的超时。

本期重点新闻口径：

```text
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
source_site=netkeiba
source_mode in (access, attention)
gate_blockers 为空
```

也就是说，本期只自动推 netkeiba 访问量榜和注目数榜新闻；新着顺新闻不会因为分数高而进入 QQ 自动推送。

## 5. 在后台配置群

进入 Django Admin：

```text
/django-admin/stable/pushtarget/
```

新增或维护：

- `name`：群名称或备注，例如 `赛马新闻测试群`
- `group_id`：QQ 群号
- `is_active`：是否启用
- `is_default`：仅用于手动推送“不选群时默认群”

自动推送只看 `is_active=true`，不会用 `is_default` 过滤目标群。

## 6. 自动推送消息格式

自动推送固定发送文本：

```text
【UmaFans】标题
摘要内容……
阅读全文：http://umafans.run/news/123/
```

规则：

- 标题使用前台有效中文标题。
- 摘要优先使用前台有效中文摘要。
- 摘要为空时从正文截断，并用 `……` 表示截断。
- 链接使用 `SITE_URL + public_path`，公开文章主路径为 `/news/<article_id>/`。当前 HTTP 阶段生产示例为 `http://umafans.run/news/123/`。

## 7. 灰度启用顺序

1. 保持 `QQ_PUSH_ENABLED=false`，先部署代码和迁移。
2. 在后台新增测试群，确认 `is_active=true`。
3. 启动 OneBot 网关，确认机器人账号已进测试群。
4. 用 curl 或 Postman 直接测试 OneBot：

```bash
curl -X POST "$ONEBOT_BASE_URL/send_group_msg" \
  -H "Authorization: Bearer $ONEBOT_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_id":"QQ群号","message":[{"type":"text","data":{"text":"UmaFans 测试消息"}}]}'
```

5. 在 `.env` 设置：

```env
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
```

6. 重启 `worker/beat`。
7. 发布或自动发布一篇测试文章，查看 QQ 群和 `QQPushDelivery` 后台记录。

## 8. 后台排查入口

自动推送交付记录：

```text
/django-admin/stable/qqpushdelivery/
```

重点字段：

- `status`：`pending / retrying / sending / sent / failed`
- `attempt_count`
- `last_error_type`
- `last_error`
- `response_payload`
- `message_id`
- `sent_at`

错误类型：

- `url_unavailable`：公开详情页 URL 暂不可访问。
- `send_failed`：OneBot 请求失败、超时、HTTP 错误或 OneBot JSON 返回业务失败。
- `not_eligible`：不符合推送范围。
- `no_targets`：没有启用群。

## 9. 常见问题

### 9.1 自动推送没有发送

依次检查：

- `.env` 中 `QQ_PUSH_ENABLED=true`
- `QQ_PUSH_SCOPE` 是否为 `high_value_only` 或 `all_public`
- `QQ_PUSH_IMPORTANCE_STRATEGY` 是否为 `ranked`
- 文章是否已发布且有 `published_to_web_at`
- 文章是否存在 blocker；有 blocker 的文章不会自动推送
- 文章详情页 URL 是否可访问
- 后台是否存在 `is_active=true` 的 `PushTarget`
- `worker` 是否运行
- 如果记录长时间停在 `sending`，检查 `last_attempt_at` 是否已超过 `QQ_PUSH_SENDING_STALE_SECONDS`；超过后再次触发任务会重新领取该交付记录。

### 9.2 重点新闻没有推送

`high_value_only` 下检查：

```text
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
source_site=netkeiba
source_mode in (access, attention)
gate_blockers 为空
```

如果只是想验证链路，可以临时把测试环境设为：

```env
QQ_PUSH_SCOPE=all_public
```

### 9.3 OneBot 发送失败

依次检查：

- `ONEBOT_BASE_URL` 是否能从 `worker` 容器访问
- `ONEBOT_ACCESS_TOKEN` 是否正确
- 机器人账号是否在线
- 机器人账号是否在目标群里
- 群是否允许机器人发言

### 9.4 被风控怎么办

这是第三方 QQ 机器人方案的客观风险，代码不能完全规避。建议：

- 先只启用测试群
- 默认 `high_value_only`
- 默认 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`
- 控制发布频率
- 使用专门机器人账号

## 10. 停用和回滚

快速停用自动推送：

```env
QQ_PUSH_ENABLED=false
```

然后重启：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

停用自动推送不会影响公开网站、自动发布或后台手动推送。
