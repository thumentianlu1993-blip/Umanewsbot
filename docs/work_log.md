# 工作日志

## 2026-05-17

### 项目一：自动化内容运营 + AI 编辑改写上线

#### 今日目标

- 将自动化内容运营 MVP 从本地代码推进到线上可用状态
- 打通自动评分、AI 改写、一致性校验、自动发布的生产链路
- 在保证可回滚的前提下，逐步提高自动发布吞吐

#### 已完成

- 完成自动化 MVP 代码提交并推送到 `main`
- 线上完成部署、迁移、容器重启与后台登录验证
- 修复后台管理员密码被容器启动脚本反复重置的问题：
  - 原因是 `.env` 中存在 `DJANGO_SUPERUSER_PASSWORD`
  - `start-web.sh` 每次启动都会执行 `seed_admin`
  - 处理方式是删除服务器 `.env` 中的 `DJANGO_SUPERUSER_PASSWORD`，再手动重置管理员密码
- 灰度启用 `AUTOMATION_ENABLED=true`
- 验证单篇文章自动化链路：
  - SiliconFlow 改写 API 返回正常
  - 文章可进入 `publish_ready`
  - `rewrite_title_zh / rewrite_summary_zh / rewrite_body_zh` 可生成
- 将自动发布策略调整为：
  - 常规时段每 15 分钟最多发布 4 篇
  - 每周日北京时间 13:00-16:00 每 15 分钟最多发布 10 篇
- 已完成相关代码、测试、文档更新并推送：
  - `feat: add automation operations mvp`
  - `fix: ignore generic racing words in horse detection`
  - `fix: tolerate control chars in rewrite json`
  - `feat: add peak auto publish batch limit`

#### 当前状态

- 自动化内容运营链路已经上线
- 自动发布批量规则已经改为常规 4 篇、周日重点窗口 10 篇
- 前台开始具备持续自动更新能力
- 仍建议继续人工抽检自动发布稿，尤其是重点赛事、长采访和含大量未收录马名的稿件

#### 风险与待观察

- AI 改写质量依赖模型稳定性、术语库覆盖率和 prompt 约束
- 自动发布虽然已通过校验，但仍可能存在表达风格、事实细节、术语覆盖不足等质量波动
- 周日高峰窗口发布量提高后，需要观察首页内容节奏和自动稿质量

#### 下一步建议

- 观察 1-2 个赛马日的自动发布效果
- 抽查 `AutomationLog` 中转人工原因，判断是否需要优化评分阈值
- 根据实际稿件质量决定是否补充风格样稿摘要规则

### 项目二：翻译稳定性与未知马名保护

#### 今日目标

- 解决大量文章因 `Translation response changed unknown horse names` 翻译失败的问题
- 确保未知马名不会阻断整篇新闻翻译

#### 已完成

- 排查确认原逻辑过于严格：
  - 系统会提取疑似未知马名
  - 如果模型没有在译文中原样保留这些名称
  - 连续重试后会直接抛出 `Translation response changed unknown horse names`
- 修复策略：
  - 翻译前将未知马名替换为 `__UMA_KEEP_n__` 占位符
  - prompt 明确要求模型原样复制占位符
  - 模型返回后系统自动把占位符还原为原始日文马名
  - 如果模型仍然漏保留未知马名，不再让整篇翻译失败，而是写入 `metadata.warning`
- 补充测试：
  - 未知马名占位符可正确还原
  - 模型仍漏保留未知马名时，翻译不失败，只记录 warning
- 已完成提交并推送：
  - `fix: do not fail translation on unknown horse names`

#### 当前状态

- 未知马名不再是阻断翻译的硬失败项
- 翻译链路会尽量保留未知马名原文，同时继续翻译剩余正文
- 相关 warning 会保留在翻译 metadata 中，后续可用于后台排查或术语库补全

#### 风险与待观察

- 疑似马名识别仍可能误判普通片假名词，需要继续通过停用词和上下文规则优化
- 如果模型完全删除占位符，系统会接受译文但记录 warning；这类稿件需要通过后续抽检发现
- 术语库覆盖率越高，未知马名保护压力越小

#### 下一步建议

- 后台增加“翻译 warning”筛选或提示，便于定位需要补术语的文章
- 定期从 warning 中提取高频未知马名，批量补充术语库
- 继续维护片假名停用词，减少普通词被误判为马名

