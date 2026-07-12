## 0. Pre-declared hypotheses

- [x] 0.1 (integration) 正确性 PASS：固定真实单词型马名回归集零误放行，固定普通语法回归集零 `core_term_missing`；任一真实专名误放行为 BLOCKER
- [x] 0.2 (application) 状态安全 PASS：`off` 与 `shadow` 对文章门禁/工作流零写入差异，dry-run 对文章零写入，重复 commit 零重复副作用；任一状态越权为 BLOCKER
- [x] 0.3 (application) 一致性 PASS：全局快照漂移整批拒绝、单篇输入漂移逐篇跳过、同一未漂移输入的 dry-run/commit 结果摘要一致；静默覆盖漂移为 BLOCKER
- [ ] 0.4 (application) 性能 PASS：PostgreSQL 生产等价 100 篇完整 dry-run（含候选选择、批次上下文、重复检测和审计持久化）不超过 60 秒、总 SQL 不超过 35 条、术语索引仅构建一次、赛事实体预取不超过 2 次、外部马名 alias 预取不超过 1 次、正式马名术语复用批次数据且额外预取为 0、重复语料预取不超过 1 次、峰值 RSS 增量不超过 256 MiB；任一硬指标失败为 BLOCKER
- [x] 0.5 (operations) 产量 `2-5` 篇/天是上线后观测目标而非正确性门槛；低于目标触发规则覆盖复盘，高于目标触发误放抽检，但均不得替代真实专名零误放要求

## 1. 命中实例与批次上下文

- [x] 1.1 (integration) 定义英文术语命中实例和值对象，包含 term/alias 标识、实际文本、字符跨度、字段、句子、前后 token、核心位置和地区信息
- [x] 1.2 (integration) 调整英文术语匹配服务，使同一术语在同一文章中的每次出现都能独立返回且保持稳定顺序
- [x] 1.3 (integration) 实现按语言、地区和规范化术语快照固定的有界 `EnglishTermMatchIndex`，避免逐篇遍历全部术语
- [x] 1.4 (integration) 实现 `ValidationBatchContext`，一次预取术语/alias、结构化实体证据和重复检测候选语料，并供单篇与重处理路径复用
- [x] 1.5 (integration) 用所有有效相关术语与 alias 关键字段的规范化排序 SHA-256 标识快照；术语新增、更新、启停、alias 变化和合并后新批次必须重建
- [x] 1.6 (integration) 只从标题和清洗后的可见正文提取命中，剔除残留 HTML 属性、脚本、样式、导航、推荐卡片和嵌入样板文本
- [x] 1.7 (integration) 保持正式译名、实际命中文本、同语言 alias 和规范化等价形式的提前保留判断

## 2. 命中级上下文分类

- [x] 2.1 (integration) 实现结构化强实体证据提取，覆盖参赛/赛果、国别后缀、骑师/练马师、档位、负磅、赔率和可用马匹维表关系
- [x] 2.2 (integration) 实现强马名语法关系规则，覆盖 `won / finished / runs / ridden by / trained by` 和明确马匹名单结构
- [x] 2.3 (integration) 实现强普通词语法与固定搭配规则，覆盖生产误挡样本及大小写变体
- [x] 2.4 (integration) 实现 `proper_noun / common_word / uncertain` 分类、置信度、稳定原因码和有界证据摘要
- [x] 2.5 (integration) 确保单词型 `term_type=horse` 只作为先验而非专名充分条件，赛事/骑师/练马师强先验仍需遵守实际命中边界
- [x] 2.6 (integration) 支持同一句同词混合用法，分别分类并只对真实专名实例执行保留校验

## 3. 发布门禁集成

- [x] 3.1 (integration) 将命中级分类接入 `validate_rewrite()`，并保持地区过滤和已保留形式短路优先
- [x] 3.2 (integration) 对高置信普通词生成 warning/info，不生成 `core_term_missing` blocker
- [x] 3.3 (integration) 对标题、摘要和首段 uncertain 核心命中保持 blocker 或人工处理，对正文背景 uncertain 只生成 warning
- [x] 3.4 (integration) 同一术语同时存在 proper/common 命中时只以 proper 实例决定缺失 blocker，并在 details 中保留全部实例
- [x] 3.5 (integration) 保持真实赛事名、核心马名、骑师和练马师缺失 blocker，以及正文、翻译、URL、重复和人工终态门禁不变
- [x] 3.6 (application) 扩展文章门禁和审计序列化，展示命中位置、上下文分类、置信度、原因码和实体证据且不保存无界正文

## 4. 高性能受控重处理

- [x] 4.1 (application) 新增 `TermGateReprocessRun` 与单例 `TermGateReprocessLock`、状态枚举、约束、索引和 migration；Run 保存模式、选择器、复合游标、规则/设置/术语快照、候选指纹、结果 manifest、统计和错误，Lock 使用唯一固定 key 保存当前 run、owner token、租约和心跳
- [x] 4.2 (application) 为运行记录增加只读 Django Admin 检索，禁用新增/编辑/删除，显示失败原因、统计、租约和续跑信息，不提供直接发布动作
- [x] 4.3 (application) 重构 `reprocess_term_gate_blocked_articles` 为候选 ID 预筛选和选中正文批量加载两阶段流程，默认禁止无 limit 且无时间范围的全量执行
- [x] 4.4 (application) 增加编码 `(first_seen_at,id)` 的 `--cursor`、有界 limit、`--max-seconds`、来源/地区/时间筛选和下一游标输出，并拒绝游标与选择器不一致
- [x] 4.5 (integration) 在整个重处理批次复用同一 `ValidationBatchContext`，不为每篇文章重新编译术语、查询马匹 alias 或加载重复检测语料
- [x] 4.6 (application) 复用 `ExternalDataImportLock`/`ProductionWindow` 模式，以单例锁行、`select_for_update()`、owner token、心跳续租和过期接管实现全局互斥；首版任意地区只允许一个重处理运行，完成/失败均保留 Run
- [x] 4.7 (application) dry-run 持久化选择器、规则/设置/术语快照、候选 ID 与输入指纹、分类明细、产量漏斗、性能统计、停止原因、复合游标和 manifest SHA；JSON 仅作为可选导出
- [x] 4.8 (application) commit 必须引用 dry-run run ID 与 manifest SHA；全局漂移整批拒绝，单篇漂移跳过并报告，未漂移文章重新验证且结果摘要必须一致
- [x] 4.9 (application) commit 每批使用 `transaction.atomic()` 和 `select_for_update()`，原子更新门禁结果、`AutomationLog`、候选状态和 `ranked_revived_at`，异常整批回滚并标记运行失败
- [x] 4.10 (application) 保持重复执行幂等，人工终态、已发布、重复文章和仍有其他 blocker 的文章不可被恢复；命令不得设置公开时间或创建 QQ delivery

## 5. 配置、开关与运行文档

- [x] 5.1 (application) 增加单一 `off|shadow|enforce` 上下文模式、规则/设置版本、批次默认上限、最大执行时间、租约与续租配置；默认 `off`，拒绝非法值
- [x] 5.2 (operations) 更新 `.env.example`，说明 `off/shadow/enforce`、dry-run、基于 run ID 的 commit 和快速关闭方式
- [x] 5.3 (operations) 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和 `docs/deploy_runbook.md`，记录生产基线、2-5 篇/天预估口径、命令性能限制、部署和回滚步骤
- [x] 5.4 (operations) 提供按香港、英国、法国、美国分批创建/审核运行记录和执行 commit 的生产命令；数据库为事实来源，JSON 导出目录仅供留档

## 6. 自动化测试

- [x] 6.1 (integration) 测试 `Brilliant was brilliant at Sha Tin` 两次命中得到不同分类且只保护马名实例
- [x] 6.2 (integration) 测试生产普通词上下文：`something / brilliant / versatile / incredible / reputation / threat / title / too soon / yet` 不产生 blocker
- [x] 6.3 (integration) 测试真实单词型马名在参赛、赛果、骑师和练马师上下文中继续生成缺失 blocker
- [x] 6.4 (integration) 测试标题大写不能单独证明专名，核心 uncertain 保守阻断、背景 uncertain 只 warning
- [x] 6.5 (integration) 测试已保留译名/原文/alias、地区过滤、同记录多 alias 和大小写/全半角规范化边界
- [x] 6.6 (integration) 测试真实赛事名、骑师、练马师和其他硬门禁不受普通词规则影响
- [x] 6.7 (integration) 测试 HTML/样板清洗、术语索引只构建一次、批次实体/重复语料不产生 N+1、术语快照变化后重建，并锁定查询数和峰值内存
- [x] 6.8 (application) 测试 Run/单例 Lock migration、唯一约束、只读 Admin 权限、复合游标、limit、max-seconds、续跑、全局互斥、租约续期/过期接管/owner 隔离和幂等
- [x] 6.9 (application) 测试 `off/shadow/enforce`：off 保持旧行为、shadow 记录新结果但不改变门禁状态、enforce 才应用新判定
- [x] 6.10 (application) 测试 dry-run 对文章零写入、运行记录持久化、全局快照漂移拒绝、单篇漂移跳过、manifest 校验和 commit 事务回滚
- [x] 6.11 (application) 测试 commit 只恢复候选且不发布/不 QQ，`AutomationLog` 与文章状态同事务，重复 commit 无重复副作用
- [x] 6.12 (application) 使用生产 36 篇基线投影 fixture 测试地区聚合、普通词降级、真实专名保留和产量漏斗输出

## 7. 本地与生产等价验证

- [x] 7.1 (application) 运行新增命中级分类、门禁和重处理目标测试并修复失败
- [x] 7.2 (application) 运行完整 `stable` 测试、Django check、migration apply/rollback/重新 apply、迁移漂移检查和 `git diff --check`
- [ ] 7.3 (operations) 在 PostgreSQL 生产等价数据上执行固定 100 篇完整 dry-run 基准，证明 60 秒内完成、总 SQL 不超过 35 条、术语索引只构建一次、赛事实体/外部马名 alias/额外马名术语/重复语料预取分别不超过 `2/1/0/1` 次、峰值 RSS 增量不超过 256 MiB，并记录 CPU/内存和运行记录
- [x] 7.4 (operations) 严格校验本 change 和全部 OpenSpec specs，确认 proposal/design/spec/tasks/test_cases 一致

## 8. 生产灰度与验收

- [ ] 8.1 (operations) 部署前备份数据库和环境配置，核对服务器 HEAD、`.env`、容器环境、compose 状态，确认无外部导入、无有效重处理租约且健康检查正常
- [ ] 8.2 (operations) 部署并迁移后验证 web/worker/beat migration、日志和 `/healthz/`；保持历史 commit 禁止，将模式从 `off` 切到 `shadow` 并观察至少 24 小时
- [ ] 8.3 (operations) 按香港、英国、法国、美国分别执行小批量 dry-run，人工抽检真实单词型马名、普通词和 uncertain 样本
- [ ] 8.4 (operations) shadow 抽检通过后切 `enforce`；对近 7 天 36 篇基线候选生成分地区 dry-run 运行记录，审核 run ID/manifest 后小批量 commit，使其只重新进入发布窗口
- [ ] 8.5 (operations) 验收并记录 blocker 清除数、恢复候选数、最终公开数和地区分布，确认稳态新增公开落在约 2-5 篇/天且没有真实专名误放行
- [ ] 8.6 (operations) 通过接口、后台、窗口账本和浏览器回归公开页；异常时关闭新分类开关并保留审计数据
