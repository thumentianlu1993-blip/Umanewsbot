## Why

2026-07-22 首个日本滚动批次（`p0batch-37fad126d645`，100 匹）prepare 触网后 **100/100 被身份锁 fail closed**：JBIS 客户端按马名精确检索，而日本赛马名大量复用，实测近年活跃马普遍返回 2-4 个同名结果（ドラゴンウェルズ/ディーズメンフィス 各 2、コンプリート 4）。候选四字段（父/母/出生年）为空，无法在同名结果中消歧，批次身份锁按设计全部阻断。

同时，身份回填已为日本 2,462 匹写入 netkeiba identity key（`netkeiba:{数字ID}`），netkeiba 马匹页 URL 可直接构造（`https://db.netkeiba.com/horse/{id}/`），无需检索、零歧义；页面含父母、出生日期、毛色、性别、马主、练马师与完整生涯成绩（生涯总数可作完整性校验值）——一个客户端同时解开**身份锁**与**四字段数据源**两个堵点（生产 ExternalHorse 的 12,405 条 netkeiba 记录父母/出生日期全空的问题也由此获得修复路径）。候选 netkeiba key 与 payload external ID 同源，`has_provider_bound_identity` 直接成立。

## What Changes

- 新增 netkeiba 马匹客户端：按候选 `netkeiba:{id}` 直接抓取马匹页与战绩页，不做名称检索；提取基础资料、父母、出生日期、生涯逐场与生涯总数；仅抽取客观比赛事实，遵守既有每地区预算与 per-host 限速（当前 8s 间隔）。
- 身份判据：payload 的 netkeiba ID 必须与候选 key 完全一致（provider-bound identity）；页面马名与候选名规范化不一致时 fail closed 进冲突，不猜测。
- adapter 接入：日本地区候选有 netkeiba key 时走 netkeiba 客户端；无 key 的候选保持 JBIS 检索路径（行为不变）。
- 解析层容错：页面结构变化（缺表、改版）一律 fail closed 记录不可解析，不猜字段；距离/日期等单位保留原文与规范化值两层。
- 批次集成后重跑首个日本滚动批次，验证 `publish-p0-horses-basic-tier` 的自动首发链路（该 change tasks 7.2 的前置）。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `horse-profile-data-completion`：日本滚动批次的来源抓取从"JBIS 名称检索（同名歧义高发）"扩展为"netkeiba ID 直取（有 key 候选）+ JBIS 检索（无 key 候选）"；有 netkeiba key 的候选具备 provider-bound 身份与四字段数据来源。

## Impact

- 代码：`server/stable/services/p0_horse_completion_source_clients.py` 新增 netkeiba client；`p0_horse_completion_adapters.py` 注册日本 netkeiba adapter；新增解析与集成测试（含同名马、缺页、结构变化 fail closed）。
- 数据：无模型变更、无迁移；批次抓取继续走既有缓存/checkpoint/预算通道。
- 运维：批次执行沿用既有门禁（ALLOW_NETWORK、限速、串行窗口、xlsx 人工复审）。
- 合规：netkeiba 访问延续既有保守限速（8s）；实际批量前复核访问条款与公开展示边界（KeibaScraper 调研已提示负载注意）。
- 明确不做：不改 JBIS 客户端既有行为；不做 netkeiba 全站爬取；不把页面专有预测/评论类内容入库；不在本 change 修复 ExternalHorse 存量空四字段（仅随批次自然覆盖，批量修复另立专项）。
