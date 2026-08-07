# 新闻正文提取边界任务清单

## 0. 当前阶段与授权边界

- [x] 0.1 (operations) 从最新已核对的 `origin/main` 建立独立干净 worktree 和 `codex/` 分支
- [x] 0.2 (operations) 只读追踪 HRN 页面结构、抓取、清洗、入库、翻译、改写和公开展示链路
- [x] 0.3 (operations) 检查同源公开样本、既有 fixture、原始 HTML 留存和历史修复命令
- [x] 0.4 (operations) 编写 durable spec/design/test/tasks/rollout 并更新原生工作流实现确认门禁
- [x] 0.5 (operations) 完成独立方案审核；首轮 findings 已修正并由同一 reviewer 会话复审通过
- [x] 0.6 (operations) 方案审核通过后停止，并取得用户明确“开始实现”授权


- [x] 1.1 (integration) 测试 subagent 添加 HRN `9623` 等价真实结构最小 fixture，不含凭据/广告脚本/无关整页内容
- [x] 1.2 (integration) 测试 subagent 添加 HRN 可信容器、框架排除、首尾/小标题/引用/列表/表格保留测试
- [x] 1.3 (integration) 测试 subagent 添加 HRN 选择器缺失 fail-closed 和正常文章不过度裁剪反例
- [x] 1.4 (integration) 测试 subagent 添加国际详情失败在 upsert 前阻断、既有文章不更新、无术语/翻译派发及 CrawlJob 可见证据测试
- [x] 1.5 (application) 测试 subagent 添加历史只读全量 scope、冻结 max ID、稳定分页、分类计数、哈希与零副作用测试
- [x] 1.6 (application) 测试 subagent 添加批准 manifest/file SHA、事务锁行后全集哈希校验、漂移整批零写入和人工/机器改写状态报告测试
- [x] 1.8 (integration) 实际运行聚焦测试并记录由目标行为未实现导致的 RED；环境/fixture/语法错误必须先修正后重取 RED

## 2. 实现（仅在有效 RED 后）

- [x] 2.1 (integration) 实现 subagent 将 HRN 正文边界收紧到可信 `.article-body`，移除 `article/main/body` 宽泛兜底
- [x] 2.2 (integration) 实现 subagent 在国际抓取 upsert 前拒绝失败/空正文，沿用 detail error/CrawlJob 摘要且同轮继续
- [x] 2.3 (application) 实现 subagent 在现有正文修复命令内增加只读、有界、冻结 max ID 的全量历史 scope 识别
- [x] 2.4 (application) 实现 subagent 增加 schema v2 批准 manifest/file SHA、单事务全集锁行与逐篇输入及
  `title_ja/body_ja_raw/body_ja_normalized/canonical parse metadata` 输出哈希绑定；任一漂移整批零写入，
  同时保留 OperationLog、无发布/QQ 副作用语义
- [x] 2.5 (operations) 实现 subagent 同步 workflow contract checker 的八阶段 canonical marker，恢复契约检查 GREEN
- [x] 2.6 (integration) 实现 subagent 取得 GREEN，并确认没有文章 ID/URL/中文词黑名单或展示层隐藏逻辑
- [x] 2.7 (operations) 主代理在所有实现 subagent 结束后整合检查，并更新本任务状态/决策文档

## 3. 验证与独立代码审核

- [x] 3.1 (integration) 运行 HRN 聚焦、既有国际正文边界和管理命令回归
- [x] 3.2 (application) 运行 Django check、必要 compile/static check 和 `git diff --check`
- [x] 3.3 (operations) 未参与实现的 reviewer 已执行 Codex 原生只读 review；首轮四项 P2 已由测试 RED 后修复
- [x] 3.4 (application) 针对 reviewer 的 manifest 输出绑定 P2 先取得 RED，再升级 schema v2，绑定
  `title_ja/body_ja_raw/body_ja_normalized` 和 canonical parse metadata；legacy/缺字段/输出漂移整批拒绝
- [ ] 3.5 (operations) 若仍有 actionable finding，由实现 subagent 修复并复用同一 code reviewer 会话限定复审

## 4. 全新文章采集修复发布（需最新 review 后单独授权）

- [ ] 4.1 (operations) 核对精确受审内容、生产 HEAD/镜像/队列/开关，创建并验证数据库与 `.env` 恢复点
- [ ] 4.3 (operations) 验证 Django check、迁移漂移、容器镜像、healthz、来源状态与一个此前从未入库的 HRN 样本端到端正文；既有重复文章不计入本 Gate
- [ ] 4.4 (operations) 异常时暂停 HRN 来源/自动发布并按部署前镜像回滚；不得用模板隐藏止血冒充修复

## 5. 历史文章（独立于代码部署，再次授权）

- [ ] 5.1 (operations) 以部署前冻结 max ID 分批只读生成全部既有 HRN 历史 scope，保存 JSON、SHA、范围与分类计数；零生产数据写入
- [ ] 5.2 (operations) 人工审核候选，区分未发布、机器翻译、机器改写和人工正文，形成精确批准 ID/决定清单
- [ ] 5.3 (operations) 生成独立 schema v2 批准 manifest 并绑定 file SHA；commit 在事务锁定全集后核对文章集合、
  逐篇输入与全部持久化 parser 输出哈希，任一漂移整批零写入
- [ ] 5.4 (operations) 仅在历史重处理明确授权后串行执行原文修复、中文层处理和逐篇公开验收
- [ ] 5.5 (operations) 验证文章 ID、workflow、发布时间、人工字段和 QQ delivery 不变，记录失败/回滚与未处理候选
