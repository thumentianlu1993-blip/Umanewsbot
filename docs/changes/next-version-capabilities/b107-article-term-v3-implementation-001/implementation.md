# B107 article-term v3 实施候选

状态：实现候选已完成，本地隔离 SQLite/helper 检查通过；独立 R review、ROOT 官方 PG GREEN、并发/锁验收、legacy/core budget 回归与正式 CI 未完成。不是 M03 完成、合并、发布或生产验收。

## 固定依据与边界

任务 B107-M03-ARTICLE-TERM-V3-IMPLEMENTATION-001；实施基线 `d583d13dd6e5b6e8d65ff2db1005a968b8683ff6`，tree `963ee63e77f5976b6159be7d0f9442feeaa06ffa`。B105 原设计 commit `bb252cd4216d07c431188b3e66676bfe98a4c599`、原 R `6a769501731ac43d98be2a270286a97464629cea`，三份设计文档保持原字节。

B106 第三原件 `/Users/mentianlu/.codex/runtime/b106-model-response-exact2-red-host-binding-003` 是 2 target FAIL / 0 ERROR / 0 SKIP 的真实 RED；原 R `cc6ce81b22c2c9226d28efe5b4f49d023aa5a062` 接受，receipt SHA256 `3202715f3b7e9086b5e822d6f29a7ed86f0ead2ea6d9c0bcc97b7c6b2cc486a8`。旧 runtime 和失败记录只读保留，不重跑 RED。

只使用当前独立 worktree。没有 PG/Docker 分配或执行、生产 DB/Redis/外网/付费调用，没有新模型/迁移、production task、权限/预算/global settings 改动，没有新 runner。候选 SHA/tree、文件与证据 SHA 由 runtime `prepare.json` 在提交后绑定，避免文档自引用。

## 执行顺序与调用点

1. `managed_readonly_steps.py` 注册显式 v3 三元组 `managed-source-terms-v3 / source_terms_v3 / readonly-result-v3`；默认仍为 v1，v1/v2 key 集保持，已有 root 不升级。v3 固定一 read、body_chars=256。原 reservation/slot/CAS/锁序不变。
2. `_read_source_excerpt_once` 在原 Article 源 SQL 后，向新 `article_term_receipt.capture` 传完整源字段、Article ID、源 hash、read 开始时间。loader 真实查询活跃 Alias/Term/External 和同 Article 的英文 AUTO/MANUAL、未 removed 赛事 runner/result；最多五条材料 SELECT，另有原 Article SELECT，不能称作一次 SQL。材料读取在原业务锁之外。
3. 新 `article_term_receipt.py` 采用 scalar `values`、SQL Substr/Cast sentinel、LIMIT N+1、chunk 16 iterator；没有 ORM FK/lazy 加载。记录五类行的 ID/更新时间/完整投影 row hash 与最小关联值；alias→term ID、external 行→外部 ID、runner/result→event/article/normalized horse key。不把 row hash 当作外部签名或身份权限。
4. 同一个原 `terms.resolve_article_entities` 算法接收 preloaded index 与私有 `capture_budget`。新 `term_capture_budget.py` 在构造对象、追加/复制/归并容器、字符串增长前收费。对象 256，collection/string 各 1024，每类 canonical 字节 128 KiB，总计 256 KiB；四类字符串 list 各 64、单字符串 UTF8 1024。`None` 返回原生容器、原算法语义；各语言排序、notes/priority、冲突与 suppressed 不截断。原实体 key helper 改为共享 streaming 生成器，默认外部 helper 仍返回原集合。
5. 持久化 `article-term-snapshot-v1` 包含完整 resolution、inputs 与 read 区间。独立最终界限为 entities/suppressed/accepted 各 32、tags 12、result 总 JSON 8192；SQL 各类 64/128/64/128/128、raw key 128、query variant 256、JSON aliases 32、投影输入 512 KiB。超界整次拒绝，已预留 slot/inflight 不退款，重投 unknown 不再 query/provider。
6. `_validated_result` 使用 `_locked_context` 已加载且经过 live fence 的 Article 构建纯 source view，再完整 decode。严格 builtin 类型、schema/hash/时间区间、真实可见英文 HTML 清理后 span（含 excerpt 外）、term/external/structured 映射、accepted 与实体一致性、tags 原归并均校验；deferred 源字段拒绝，不发生 lazy SQL。
7. `managed_readonly_translation.py` 仅 v3 consumer 从持久 step decode resolution；v1/v2 与普通入口仍走原 resolver。注册、prepare、route、live controls、缓存、checkpoint/final 引用沿原源/授权/claim/version/时间 fence 验证；没有新增词典 SELECT 或 fallback。真实 provider/admission/usage journal/reconciliation/save 链保持。

`terms.py` private resolver 分支的 diff 较大，原因是显式传递 budget、把 selected 函数内容器增长改为 charged helper，并展开格式；独立复核应检查遗漏增长点以及 None 等价，不以 diff 行数或最终 small resolution 证明安全。

## 用例与实际证据

本地 `DB_ENGINE=sqlite SQLITE_DB_PATH=:memory:`，已有 Python 3.12 venv、`-B`，独立内存 test DB 创建/销毁。`stable.test_article_term_receipt` 20 项 + 原 `stable.test_english_term_context_gates` 17 项共 37 项通过。runtime 最终日志 `sqlite-final-bound.json.log`；不修改 settings、不 mock PG backend、不执行 step/consumer PG 用例。

`prior-resolver-equivalence.log` 使用 d583 原 terms 源的纯 preloaded scalar 对照，47 corpus × 3 languages × 2 key helpers = 282 集合等价；另有 6 组原 resolver / 当前 None / 当前 budget 完整结果等价。这是纯算法对照，不是 DB/provider/registered 成功证明。

| B105 场景 | 已编写的检查与当前证据 | 待闭合 |
|---|---|---|
| 1 v3 实际 read→持久 step→consumer | 原两目标 ID 保留，改显式 v3；真实 ORM baseline/row ID、同 step、provider 参数、真实成本对账与 Article 终态断言保留；SQLite helper 实际五类 SQL/完整 resolution 已通过 | ROOT exact2 PG GREEN，final 引用与资源回执 |
| 2 来源/身份安全 | SQLite 三语言、pending/nonHorse/空译名、映射/类型/hash/span/schema 篡改通过；新增 PG cached mapping/source/version fence | PG live拒绝与 request/provider=0；更广 run/claim/外来 step 由原 legacy 回归 |
| 3 限额 | SQLite 五类 N+1、notes/JSON sentinel、UTF8、keys/variants、输入累计、40 同 span 归并与最终限额、增长前拒绝通过；新增 PG slot/inflight/unknown 用例 | PG Cast/Substr 差异、实际 slot 持久化与 unknown 零查询 |
| 4 read 后材料变化/删除 | 原 GREEN2 保持真实 read 后改 target；新增独立删除 Term/Alias/External/link/runner/result 的实际 consumer 用例；SQLite 删除后纯 decode 零查询通过 | PG fresh scope 恢复、checkpoint 免费 apply/final redelivery、同 step/row hash/read interval |
| 5 cached/live fence | 新 PG source/grant/deadline/version/mapping，以及 read 前源变更/read 后撤权/timeout 的真实 fixture | PG 锁后截止与双消费者单胜者；原 max 三连接有界窗口 |
| 6 legacy 与默认 | 静态旧方法 AST 除两个目标不变，新增真实 v1/v2 exact keys/root 不升级用例；原英语 terms 17 项通过 | 原35+、直接 core budget/全 terms、正式 CI |
| R01 最小关联/全 source view | SQLite external/structured mapper 篡改、重复 kind/id、合法旧 updated_at、HTML visible span/256 外/deferred 拒绝通过；真实删除 consumer 已编写 | ROOT 删除恢复 PG |
| R02 收集期增长 | SQLite 独立256对象、65 list/1025累计、字节界、重复输入收费、40实际ORM中间归并、三语言 protected/suppressed 通过 | PG 超限未完成 step/provider=0；R逐增长点复核 |

40 行同 span 用例实际参加原 resolver 并归并成 1；包含 40 行 inputs 的最终 receipt 仍可能超过 8192，不能冒充完整工具成功。257 对象与四类 list 上限的 pure helper 检查证明边界函数；不冒充实际 PG step 到达该边界。

GREEN2 合成正文缩短以满足 v3 raw key≤128（旧长正文不合法）。人物在标题/正文各一次，响应 TERM_1 各一次、原质量门禁和真实 read→usage→reconciliation→save 断言保持；没有通过绕开 provider 或伪造 resolution 获得成功。测试方法中的 v2 命名是固定 exact2 历史 ID，不表示运行 v2。

## 固定计划与交接

runtime `/Users/mentianlu/.codex/runtime/b107-article-term-v3-implementation-001` 保存最终源 diff、文件/日志 hash、静态检查、exact2 GREEN plan、五项新增 v3 PG boundary plan、legacy obligations。计划只是 request-only；未 collect、未分配、未执行。复用原 official_host_bootstrap 与固定 controls，PG16、600=570+30 秒、CPU2/4GiB/256pids/3GiB tmpfs、network none、readonly、10001、cap-drop ALL、NNP、最多原三 PG 连接；镜像/endpoint 当前状态未重新验证。

`terms.py` 仍属于 high_risk，新增模块不能据此缩减正式 CI。ROOT 必须先取得原 R 独立复核，再在授权原窗口跑绑定候选的 exact2 GREEN、边界、legacy/core budget/terms/正式 CI；源对象变更须刷新 source binding/review。若 schema/权限/源/限额拒绝，保留真实失败与 runtime，不降级 v1/v2，不退款或另开资源。
