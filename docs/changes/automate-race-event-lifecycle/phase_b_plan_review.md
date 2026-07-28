# 阶段 B0.1 方案审核记录

## 审核范围

- 任务：`automate-race-event-lifecycle` 阶段 B0.1 赛后内部参考源。
- 基线：`origin/main@a59956b327157d29630fab1f1c98ba9c9cacfed0`。
- reviewer：`/root/phase_b_plan_review`。
- reviewer 未参与规格、设计和交接文档编写，仅执行只读方案审核。
- 本记录是 Codex 原生工作流产物，不属于 OpenSpec change。

## 第一轮：REVISE

日期：`2026-07-27`

reviewer 提出以下 finding：

1. `race_reference_observation_v1` 未冻结精确 schema、canonical hash、上限和 legacy 权威字段降级。
2. 单层 observation 无法同时满足跨 run 重放、run membership、重新匹配和 append-only。
3. manifest 未冻结精确 schema、source key、event snapshot、URL 路由和 artifact 完整性。
4. 三个现有 parser 实际只处理 `finished` 赛后入口，不能据此承诺赛前 racecard。
5. 连续观察的 selector、锁、budget、worker/queue 未闭合。
6. 现有 HTTP helper 在完整读取 body 前没有单响应大小上限。
7. 测试矩阵缺少上述 schema、重放、manifest、HTTP 和运行边界。

## 第一轮修订

- 将首个实现单元收窄为 **B0.1 赛后内部参考源**，仅处理三个 parser 已有的 `finished`
  结果页；赛前 route 另行 proof/spec/review。
- 数据拆为不可变 `RaceReferencePayload` 与逐 run `RaceReferenceReceipt`，run/payload/receipt
  三层均有明确唯一约束、事务和 PostgreSQL advisory lock。
- 冻结 v1 payload schema、legacy 字段降权、recursive forbidden keys、NFC/canonical JSON、
  256 KiB/80 runners/深度 12 等上限及 completeness 规则。
- 冻结 manifest schema、source key、event snapshot、host/path、artifact file list/hash、
  `COMPLETE` marker 和数据库 drift 零写合同。
- 不增加 Celery/Beat/task/queue/worker；七日观察改为每天逐来源显式 manifest-bound
  one-shot collect/record，自动调度属于 B0.2。
- 网络 collect 与离线 record 分离；collect 数据库零写，record 永不联网。
- 从三个历史 parser 抽取正式 parse-only API，并让历史 CLI 反向共用，collect 只请求 manifest
  精确 URL，不复用日期扫描、R/C 扫描或“取首个候选”。
- HTTP 增加 content type、`Content-Length` 与实际流式 4 MiB 双上限，以及最多两跳逐跳
  URL 合同校验。
- 测试矩阵扩至 B32-B57，覆盖跨 run、重新匹配、并发 record、manifest/DB drift、HTTP 上限、
  artifact 完整性以及 public/news/QQ/race-live/lifecycle 零耦合。

## 第二轮：REVISE

日期：`2026-07-27`

第一轮 7 项主要问题已经闭合；reviewer 继续发现 4 项 P1、1 项 P2：

1. `fetched_at` 在 semantic payload 中会使每日抓取必然产生新 hash。
2. 三源 `provider_event_key/parser_context` 没有来源级强身份语法，HRN 仍可能退回首候选。
3. `artifact.json` 的 files、自身 hash、`COMPLETE` 和锁文件存在自引用/额外文件歧义。
4. “每日最多一次”没有跨 run 持久门禁，换目录仍可触网。
5. HTTP content type allowlist 和缺失 header 行为未冻结。

## 第二轮修订

- semantic payload 只保留来源事实；抓取时间、URL、raw/cache、parser 与 legacy hash 全部移入
  receipt provenance，并分别计算 `payload_sha256/provenance_sha256`。
- `observation_key=source_key:provider_event_key`；Sporting Life 数字 race ID、ZEturf
  `date+R/C`、HRN `track+date+race_no` 与 URL 必须一致，parser context 只从 key 派生。
- HRN track-day 页按 race number 必须唯一命中，禁止名称 fallback 或 `candidates[0]`。
- artifact 成功目录冻结为 `raw/`、manifest、reference JSONL、ledger、artifact 和 COMPLETE；
  files 清单排除 artifact 自身与 COMPLETE，锁文件位于目录外。
- 明确 B0.1 只有 run-local budget；“每日一次”是需新联网授权的人工上限，不宣称程序强制，
  重复 run 在报告中标识。程序级跨 run budget 属 B0.2。
- HTTP MIME 只允许 HTML/XHTML 及 charset；缺失、冲突或其他 MIME 在读取 body 前拒绝。

## 第三轮：APPROVED

日期：`2026-07-27`

同一 reviewer 确认第二轮 4 项 P1、1 项 P2 全部闭合，未发现新的 actionable finding：

- semantic payload、receipt provenance 与 `unchanged_count` 一致；
- 三源强身份和 HRN 唯一 race number 匹配已冻结；
- artifact 文件集合、外置锁、`COMPLETE` 与自引用边界明确；
- 每日一次明确为人工联网授权上限，不冒充程序门禁；
- HTML/XHTML MIME 白名单及缺失/冲突行为明确；
- B37/B49/B54/B56/B57 覆盖对应回归；
- 跨文档未发现不可实现矛盾，`git diff --check` 通过。

最终结论：`VERDICT: APPROVED`。

该结论只代表阶段 B0.1 方案审核通过，不构成实现、联网、生产写入或发布授权。
