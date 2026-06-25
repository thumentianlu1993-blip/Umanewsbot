## Context

公开首页和详情页目前通过 `article.public_path` 生成详情链接，路由为 `/news/<slug>/`。`public_slug` 由标题生成，日文/中文标题会让链接很长。QQ 自动推送消息也使用 `SITE_URL + article.public_path`，所以链接可读性问题会直接出现在群消息里。

## Goals / Non-Goals

**Goals:**

- 将公开文章详情主 URL 改为 `/news/<article_id>/`。
- 保持旧 slug URL 可用并跳转到 ID URL。
- 让首页、详情页、后台前台查看入口和 QQ 消息自然使用 ID URL。

**Non-Goals:**

- 不删除 `public_slug` 字段。
- 不新增短链、ULID、hashid 或自定义公开 ID 字段。
- 不改变文章公开过滤规则。
- 不做 SEO canonical 标签或 sitemap，本轮只处理路由和链接生成。
- 不专门兼容历史 `public_slug` 恰好为纯数字的极低概率旧链接。

## Decisions

1. 第一阶段使用数据库主键作为公开 ID。
   - 选择原因：已有全局唯一、短、稳定，不需要迁移。
   - 替代方案：新增 `public_id`。更隐私但需要迁移和回填，当前收益不足。

2. `public_path` 统一改为 ID URL。
   - 选择原因：项目模板和 QQ 推送多数已经复用该属性，改动集中。
   - 替代方案：只改 QQ 推送 URL。会导致站内和群消息 URL 规则不一致。

3. 旧 slug 路由保留并跳转。
   - 选择原因：历史首页缓存、已发 QQ 消息或手动复制过的旧链接不能突然断掉。

## Risks / Trade-offs

- [Risk] 公开 URL 暴露递增 ID。Mitigation: 当前站点没有用户隐私内容，文章 ID 暴露风险可接受；后续可单独引入 public_id。
- [Risk] 历史 `public_slug` 恰好为纯数字时，旧 slug 链接会优先按 ID 路由解析。Mitigation: 接受该极低概率边界，本轮不为纯数字旧 slug 增加 fallback 逻辑；普通非数字旧 slug 继续跳转。
- [Risk] 外部旧链接直接 404。Mitigation: 保留旧 slug 查找并 redirect。

## Migration Plan

1. 本地修改 `public_path`、URL 路由和详情 view。
2. 补充非纯数字旧 slug 跳转测试和首页/QQ URL 测试。
3. 部署后抽检 `/news/<id>/`、旧 `/news/<slug>/`、首页文章链接和 QQ 发送消息。
4. 回滚时恢复 `public_path` 和路由即可；不涉及数据迁移。

## Open Questions

无。
