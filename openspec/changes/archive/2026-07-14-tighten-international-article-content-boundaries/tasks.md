## 1. 回归测试代码

- [x] 1.1 (application) 从生产问题页面提炼文章 `8086`、`8267`、`8316`、`8318` 的最小本地 HTML fixture，去除账号、密钥和无关大段内容
- [x] 1.2 (integration) 编写 Sporting Life 正文节点、无整页兜底、站点框架清理和博彩例外的失败回归测试
- [x] 1.3 (integration) 编写 TDN 编辑注、跳转 CTA、完整赛果链接和正文中相似普通句不被误截断的失败回归测试
- [x] 1.4 (integration) 编写正文解析元数据、空正文失败状态和翻译元数据不复制整页 HTML 的失败回归测试
- [x] 1.5 (application) 编写历史正文修复命令 dry-run/commit、显式 ID 限制、OperationLog 和无发布/QQ 副作用的失败回归测试
- [x] 1.6 (application) 编写同步强制重译覆盖已批准人工稿且保持发布状态、发布时间和 QQ delivery 不变的失败回归测试

## 2. 正文边界与清理实现

- [x] 2.1 (integration) 实现可审计的国际新闻正文清理服务，支持结构化节点移除、来源级前导跳过、尾部截断和移除规则计数
- [x] 2.2 (integration) 修改国际新闻基础适配器：只接受可信正文选择器，未命中时返回显式失败且不回退整页 `body`
- [x] 2.3 (integration) 为 Sporting Life 声明可验证的正文容器，并过滤导航、分享、推荐、博彩导流和责任博彩内容
- [x] 2.4 (integration) 为 TDN 清理编辑注、纯跳转说明、完整赛果/活动 CTA 和 `Read Today's Paper` 尾部模板
- [x] 2.5 (integration) 实现博彩段落保护规则：保留赔率和赛事标题、马主等专有名词中的博彩公司名称
- [x] 2.6 (application) 实现按显式文章 ID 离线重解析已保存 HTML 的管理命令，默认 dry-run，显式 commit 后事务写回正文、清理审计元数据和 OperationLog
- [x] 2.7 (application) 为现有 `translate_news` 命令和翻译任务增加默认关闭的强制参数，复用 `apply_translation_result(force=True)` 且不触发发布或 QQ

## 3. 本地验证与复核

- [x] 3.1 (application) 运行四篇文章目标测试、国际适配器相关测试、`manage.py check` 和 `makemigrations --check --dry-run`
- [x] 3.2 (integration) 使用问题 fixture 检查清理前后正文差异，确认真实新闻段落和图片说明未被误删
- [x] 3.3 (application) 完成只读代码 review；修复全部技术问题并重复 review，直到零问题

## 4. 生产部署与历史修复

- [x] 4.1 (operations) 部署前核对生产 `HEAD`、容器、任务和健康状态，备份 `.env` 与 PostgreSQL 并验证备份可读
- [x] 4.2 (operations) 部署经 review 的 commit，运行 Django 检查、目标测试和 `/healthz/`，记录仓库预期与服务器运行态
- [x] 4.3 (operations) 对文章 `8086`、`8267`、`8316`、`8318` 先执行离线正文修复 dry-run，核对差异后 commit，再按显式 ID 同步强制重译和校验；保持既有公开状态且禁止重复发布和 QQ 分发
- [x] 4.4 (operations) 逐篇验收后台与公开详情，确认页面框架、编辑注、跳转 CTA 和不允许的博彩内容均已消失
- [x] 4.5 (operations) 随机抽取 Sporting Life、TDN 近期新文章回归正文首尾、博彩噪声和解析失败可见性

## 5. 文档与收尾

- [x] 5.1 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`，记录正文边界决策、生产 commit、备份、历史修复和回归证据
- [x] 5.2 (operations) 确认 OpenSpec 任务、规格和生产事实一致，为同步与归档准备最终验证证据
