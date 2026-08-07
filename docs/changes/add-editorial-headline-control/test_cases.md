# 首页人工头条与 AI 编辑推荐测试用例

## 1. RED 规则

- 本文件只声明测试；在用户明确“G1 范围确认/开始实现”前不得创建或修改测试代码。
- 取得授权后，测试 subagent 先实现本节用例并实际运行。
- RED 必须因为模型、服务、路由或页面能力尚不存在/行为仍是算法头条而失败；语法错误、fixture 错误、
  数据库配置错误或误改旧断言不算有效 RED。
- 每组 RED 保存命令、失败测试名、关键失败原因和时间；实现完成后在同一位置记录 GREEN。
- 并发测试分为跨数据库可跑的版本冲突测试和真实 PostgreSQL 双连接测试；SQLite 的
  `select_for_update` 不能冒充 PostgreSQL 并发证据。

## 2. 模型与迁移

### T01 单例和默认回退

- 迁移后没有选择记录时，首页继续选择现有算法头条。
- 创建固定 slot 后不能再创建第二个同 slot 选择行。
- selection/recommendation 使用非 `homepage_primary` slot 时由数据库 CheckConstraint 拒绝。
- selection 只容纳一个文章 FK，空 article 表示人工控制关闭。

### T02 当前推荐唯一

- 同一 slot 最多一个 `status=active` 推荐。
- 历史 `accepted/superseded/invalidated` 可保留多条。
- 文章删除后 selection/recommendation FK 置空，历史记录保留。

### T03 迁移漂移

- `makemigrations --check --dry-run` 无额外迁移。
- PostgreSQL 能创建 `UNIQUE(slot)` 和 active 条件唯一索引。

## 3. 资格

### T04 合格文章

- `published`、网页发布时间不晚于当前时间，且有效标题/摘要/正文非空时合格。
- 无封面仍合格。
- 有效摘要由正文回退得到时合格。

### T05 不合格文章

分别拒绝：

- 未发布/待审核；
- 已撤稿；
- `published_to_web_at` 为空；
- `published_to_web_at` 在未来；
- 有效标题为空；
- 有效摘要为空；
- 有效正文为空；
- 不存在的文章 ID。

拒绝时 selection、recommendation 和 `OperationLog` 均无意外写入。

## 4. 人工设置、替换与取消

### T06 后台设置

- 有权限用户从管理页把一篇合格文章设为头条。
- selection 保存文章、操作者、时间，version 增加。
- 首页使用该文章，即使算法会选择另一篇。
- 写一条 `headline_set` 审计。

### T07 原子替换

- 当前为 A 时选择 B，在同一事务后 selection 只指向 B。
- 审计为 `headline_replaced`，detail 含 A/B 和版本。
- 首页为 B，普通流不重复 B。

### T08 取消

- 取消后 article 为空、version 增加、写 `headline_cancelled`。
- 首页立即回到原算法结果。
- 重复陈旧取消不影响更新后的选择。

### T09 无权限

- 匿名请求按现有后台登录规则处理。
- 普通非 staff 用户不能访问。
- staff 但没有 `change_homepageheadlineselection` 权限时 GET/POST 不能修改。
- 授权 staff 与 superuser 可操作。
- 页面不向无权限用户展示写按钮。

## 5. 并发与唯一性

### T10 陈旧版本冲突

- 两个请求都读取 version N；
- 请求一设置 A 后变为 N+1；
- 请求二仍携带 N 设置 B，得到明确冲突；
- 最终仍为 A，B 不产生成功审计。

### T11 PostgreSQL 双连接并发

- 两个事务同时选择 A/B；
- 两个事务同时生成推荐；
- 选择与选中文章失效协调交错。

断言：

- 没有两个 selection 行；
- 最多一个 active 推荐；
- 不死锁；
- 陈旧请求失败可见；
- version 单调；
- 审计与最终状态一致。

## 6. 失效与 fallback

### T12 撤稿失效

- A 为人工头条；
- 通过文章编辑路径撤稿；
- selection 被清空且 version 增加；
- 写一次 `headline_invalidated`；
- 首页返回算法头条 B，不 500、不空白。

### T13 其他失效

分别覆盖：

- 改为待审核/拒绝；
- 网页发布时间改到未来；
- 清空有效内容；
- 删除文章。

重复 signal/协调调用必须幂等，不重复失效审计。

### T14 Django Admin 批量状态变更

- 当前人工头条包含在 `mark_pending_review` action queryset 中；
- action 后文章为待审核、selection 清空、version 增加且写一次失效审计；
- 首页安全 fallback；
- action 不再通过 `queryset.update()` 绕过 signal/共享失效服务。

### T15 读取层 fail-safe

- 构造 selection 指向已不合格文章但尚未协调的状态；
- 首页不展示它，直接使用现有算法回退；
- 公开 GET 不写 selection/recommendation/OperationLog。

### T16 失效协调异常

- 注入 `on_commit` 协调服务异常；
- 文章保存/编辑响应不因 callback 再抛出而伪装成整体失败；
- logger 记录 article ID、reason、exception 和 traceback；
- selection 即使暂时残留，公开 GET 只读且不会展示无效文章；
- 后续重试成功只写一次失效审计。

### T17 算法窗口与统一资格

没有有效人工头条时继续覆盖既有行为：

- 近 72 小时高价值稿优先；
- 近 72 小时为空时回退 7 天；
- 7 天为空时回退最新已发布；
- 排序仍为赛事优先级、分数、封面、时间、ID；
- 未来网页时间、空有效标题/摘要/正文不会由算法选回；
- 前 48 个原始行含不合格文章时在 192 行扫描上限内补足；
- 第 49 篇合格文章不参与排序；
- 预取后的 48/192 篇候选不存在逐篇图片 N+1，并有 query-count 上限。

## 7. AI 推荐

### T18 生成一条推荐

- 有多个合格文章时只生成一个 active 推荐。
- 选中文章与现有排序信号一致。
- reason 为非空中文，evidence 含候选 ID、排序信号和 engine version。
- 写 `headline_recommendation_generated`。
- 生成前后的人工 selection 和首页头条完全不变。

### T19 推荐替换

- 已有 active 推荐 A 时刷新得到 B；
- A 标记 superseded，B 为唯一 active；
- 操作和推荐生命周期可审计。

### T20 有效人工头条不被静默覆盖

- 当前人工头条 A；
- 推荐生成 B；
- 首页仍为 A；
- recommendation 指向 B，selection 指向 A。

### T21 接受推荐

- 用户明确接受 active 推荐 B；
- selection 原子切换到 B；
- 推荐标记 accepted，保存 accepted_by/at；
- 写 `headline_recommendation_accepted` 和设置/替换审计；
- 首页才变为 B。

### T22 推荐接受失败

分别覆盖：

- recommendation 已 superseded；
- 推荐文章已撤稿/删除/内容不完整；
- selection expected version 陈旧；
- 用户无权限。

全部保持当前人工头条不变。

### T23 无候选

- 没有合格文章时刷新推荐显示明确提示；
- 不创建 article 为空的 active 推荐；
- 人工 selection 不变。

## 8. 缓存与实时性

### T24 无 headline cache 的实时更新

同一测试进程连续请求：

1. 算法头条 A；
2. 设置 B 后立即请求为 B；
3. 替换 C 后立即请求为 C；
4. 取消后立即回到 A；
5. B/C 失效后不再展示。

断言没有 headline cache key、模板 fragment cache 或进程 memoization。赛事 cache mock 不被本变更调用。

## 9. 页面和回归

### T25 后台交互

- 头条管理页展示当前 selection、算法回退状态、最新推荐、理由、合格文章和近期审计。
- 编辑台显示推荐卡；刷新推荐的独立 form 不提交文章编辑 form。
- 已有有效人工头条时接受替换文案明确。
- 错误/并发冲突用中文 messages/表单错误展示。

### T26 公开来源隐藏规则

人工头条与算法头条两种情况下，公开首页均不出现：

- `source_note/source_site`；
- 新闻地区标签；
- 新闻原文语言；
- `source_url`。

保留标题、摘要、网页发布时间和数字 ID 详情链接。

### T27 桌面与移动

真实浏览器：

- 1440px：首页 hero、普通流、今日赛事和热门侧栏无重叠；
- 390px：头条标题/图片、普通流和导航无横向溢出；
- 有图、无图人工头条各验收一次；
- 后台头条管理页和编辑台推荐卡在桌面/移动端可操作；
- 浏览器 console 无 error。

## 10. 验证命令（实现后）

聚焦：

```bash
cd server
DB_ENGINE=sqlite python manage.py test stable.test_editorial_headlines --verbosity 2
DB_ENGINE=sqlite python manage.py test \
  stable.tests.PublicHomeInfoFeedTests \
  stable.test_public_navigation_and_attribution --verbosity 2
```

权限、审计与缓存专项测试包含在 `stable.test_editorial_headlines`；若拆文件，最终命令必须显式列全。

基础验证：

```bash
cd server
DB_ENGINE=sqlite python manage.py check
DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run
cd ..
git diff --check
```

真实 PostgreSQL：

```bash
cd server
DB_ENGINE=postgres python manage.py test \
  stable.test_editorial_headlines_postgres --verbosity 2
```

具体 PostgreSQL 连接参数按仓库现有测试环境传入，不把凭据写入文档或命令输出。完整 `stable` 回归是否执行
按实现影响面和基线状态决定；至少执行包含新闻编辑、自动发布、公开首页和信号的相关组。

浏览器验收使用 1440px 和 390px，保存首页和后台关键状态截图/DOM 断言，并记录无横向溢出和 console 状态。
