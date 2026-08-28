# 赛事日历自动更新与赛事生命周期测试用例

## 1. RED 原则


- lifecycle control/audit 模型不存在；
- 纯时间决策/原子推进服务不存在；
- 新闻 impact assessment/特殊池不存在；
- 来源权威比较不存在。

fixture、迁移依赖、语法、数据库不可用或错误 mock 不算有效 RED。PostgreSQL 并发用例必须在
临时 PostgreSQL 运行，不能用 SQLite 的锁语义冒充。

证据追加格式：

```text
RED: command / timestamp / exit / failed test / expected capability gap
GREEN: command / timestamp / exit / counts
```

阶段 A 已存在历史 RED/GREEN 和生产关闭部署证据；不得事后重造。

### 1.1 阶段 B0.1 实际 RED/GREEN（2026-07-27）

阶段 B0.1 已在用户明确授权后按测试先行执行，未联网、未连接生产数据库：

- 首轮聚焦测试真实 RED：缺少内部 reference 模型、record 服务、三个 parse-only parser、
  四个管理命令和增强后的安全 HTTP 参数，失败均指向目标能力尚未实现，不是 fixture、迁移、
  语法或环境错误。
- 追加 4 项 append-only 实例门禁测试后再次取得真实 RED：
  `RaceReferencePayload` 的实例 `save/delete` 与 `RaceReferenceReceipt` 的实例
  `save/delete` 均因“预期抛出 `ValidationError`、实际未抛出”失败；实现实例级不可变门禁后转为
  GREEN。
- B0.1 SQLite 聚焦矩阵：
  `stable.test_race_reference_sources` +
  `stable.test_race_reference_management_commands`，首轮实现为 `41/41 GREEN`；独立代码 review
  首轮的 4 项 P2 均先补真实 RED 后修复为 `45/45 GREEN`；第二轮限定复审的另 4 项 P2
  同样先补真实 RED 后修复为 `49/49 GREEN`；第三轮发现的 1 项 P1 与 3 项 P2 继续先补
  真实 RED 后修复为 `53/53 GREEN`；第四轮剩余 2 项 P2 也先补真实 RED 后修复，当前为
  `60/60 GREEN`；第五轮新增 4 项 P2 均先补真实 RED 后修复为 `64/64 GREEN`；第六轮新增
  5 项 P2 也先补真实 RED 后修复为 `69/69 GREEN`；第七轮新增 3 项 P2 均先补真实 RED
  后修复为 `78/78 GREEN`；第八轮唯一 P2 对应的 3 项测试先取得真实 RED，修复后当前为
  `80/80 GREEN`；第九轮 1 项 P1 与 3 项 P2 对应 4 项真实 RED，修复后当前为
  `82/82 GREEN`；第十轮唯一 P2 对应 2 项真实 RED，修复后为 `84/84 GREEN`；第十一轮
  2 项 P2 对应 3 项真实 RED，修复后为 `87/87 GREEN`；第十二轮 2 项 P2 对应反例
  RED，修复后为 `89/89 GREEN`；第十三轮 3 项 P2 对应 3 项真实 RED，修复后当前为
  `93/93 GREEN`；第十四轮 2 项 P2 对应时间窗口与重复分组 RED，修复后当前为
  `96/96 GREEN`；第十五轮 2 项 P2 对应重签 artifact 真实 RED，修复后当前为
  `98/98 GREEN`；第十六轮唯一 P2 对应 6 项真实 RED 与 5 项实例/`SET_NULL` 正例，
  修复后当前为 `104/104 GREEN`。
- B0.1 PostgreSQL 矩阵：
  `stable.test_race_reference_sources_postgres`，在临时本机 PostgreSQL 16 容器执行，
  advisory lock/并发重放与事务回滚 `2/2 GREEN`；容器验证后已删除。这只是本地测试数据库，
  不是生产迁移或生产写入。
- lifecycle PostgreSQL 矩阵：
  `stable.test_race_event_lifecycle_postgres`，`5/5 GREEN`。
- Sporting Life、ZEturf、HRN 历史 parser、direct URL 与安全 HTTP 聚焦回归：
  `82/82 GREEN / 4 conditional skips`。

扩展回归及已知主线基线：

- lifecycle/race-live/calendar 组合共 `141` 项：`140 pass / 1 fail`。唯一失败为暂定赛果页面
  仍含栏目标题“正式赛果”，已在纯 `origin/main` 同环境复现，未归因于 B0.1。
- 新闻门禁组合共 `141` 项：`140 pass / 1 fail`。唯一失败为错误消息 wording mismatch，
  已在纯 `origin/main` 同环境复现，未归因于 B0.1。
- historical batch 扩展矩阵共 `123` 项：`18 errors / 7 skips`；代表性错误已在纯
  `origin/main` 复现，为 macOS `/var` 与 `/private/var` 路径规范化差异，不作为 B0.1
  新增回归，也不宣称该扩展矩阵全绿。
- Django check、`makemigrations --check --dry-run`、变更文件 `py_compile`、
  `git diff --check` 均通过。
- Codex workflow contract 检查通过：
  fingerprint `24/24`、transition `10/10`、workflow `26/26`。
- Compose config 因隔离 worktree 不含 `.env` 未成功执行；本阶段未修改
  `docker-compose*.yml`，也未新增 Celery task、route、Beat 或 worker。Compose 仍是发布前
  待补门禁，不能记为已通过。

独立代码 review 首轮证据：

- reviewer session：
  `019fa021-3552-7f23-a17f-2cae48ccc4bb`；
- 受审原 fingerprint：
  `f2463878ffa4011aa91cf5b3cd7c5fe817b66157691e9eaf6e309640623695cd`；
- 结论：`VERDICT: REVISE`，P0 `0`、P1 `0`、P2 `4`；
- 4 项 P2 分别为：collect 可能误绑定赛事、ZEturf 没有证明 manifest 中的 `R/C` 与页面赛事
  一致、`source_only` 路径可能抛出 `KeyError`、report 缺少多日观察所需指标；
- 四项 finding 均先增加由缺陷本身导致的真实 RED，再由原 implementation subagent 按既有文件
  边界修复；修复后 SQLite `45/45`、历史 parser `52 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django check、migration drift 和 `git diff --check` 通过；
- 首轮 `REVISE` 不是成功审核；该轮修复后进入同一 reviewer 的第二轮限定复审，review 与
  release 门禁当时均未完成。

同一 reviewer 第二轮限定复审证据：

- inner session：
  `019fa02f-1976-7d10-b177-a18a0216591e`；
- 本轮 fingerprint：
  `561cdbf66dd3a26c702366bd113d2aed197dc98446eec34856d2c2c1350e9200`；
- 结论仍为 `VERDICT: REVISE`，新增 4 项直接 P2：record 没有独立重验 racecourse；
  report 的 `event-id` 过滤错误依赖 nullable FK；report 日期过滤只看 run 范围而非冻结赛事日期；
  默认开发 Compose 的 bind mount 会遮住位于 `runtime` 的 parser 实现；
- 四项均先补由缺陷本身导致的真实 RED。修复后 record service 独立重验 racecourse，并与
  collect 共用同一 racecourse helper；report 改按 frozen snapshot 的 `event_id/local_date`
  过滤；parser 单一实现迁至 `server/stable`，compat wrapper 与三个历史 CLI 复用该实现，
  避免默认开发 Compose bind mount 遮蔽；
- 修复后 B0.1 SQLite `49/49`、PostgreSQL concurrency `2/2`、历史 parser
  `52 OK / 4 conditional skips`，Django check、migration drift、workflow contract 和
  `git diff --check` 通过；
- 第二轮仍是 `REVISE`，不能标记 review 完成；该轮修复后进入同一 reviewer 第三轮限定
  复审，release 继续保持 pending。

同一 reviewer 第三轮限定复审证据：

- inner session：
  `019fa044-4483-72e1-b836-53e6900df34c`；
- 本轮 fingerprint：
  `22675d91cb097737bb678bd547874cce1ae1d7c481f416710911740a24981f06`；
- 结论仍为 `VERDICT: REVISE`。第二轮的 4 项 P2 已全部关闭；本轮新发现 1 项 P1：
  safe HTTP 把 HTML MIME 设为全局默认，破坏既有 PDF/JSON/XML 调用；另有 3 项 P2：
  ZEturf `NP`、HRN 国家后缀和 Sporting Life 下划线状态没有统一规范化；
- 四项均先补真实 RED。safe HTTP MIME 检查改为 opt-in，internal reference collect 显式只允许
  HTML/XHTML；三个 parser 对上述值做统一规范化，同时保留来源 raw 证据；
- 修复后 B0.1 SQLite `53/53`、历史 HTTP/parser `80 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django check、migration drift、workflow contract 和
  `git diff --check` 通过；
- 第三轮仍是 `REVISE`；该轮修复后进入同一 reviewer 第四轮限定复审，review 与 release
  继续 pending。

同一 reviewer 第四轮限定复审证据：

- inner session：
  `019fa051-bcf9-7e71-bd04-f11090fe8112`；
- 本轮 fingerprint：
  `a3f862fd93041831250fe855e383ee911843f6eb940433604c5a08b1f835b63b`；
- 结论仍为 `VERDICT: REVISE`。第三轮 4 项 finding 中 3 项已关闭，Sporting Life
  description 仅部分关闭；剩余 2 项 P2 为 `ride_description` 下划线值尚未统一，以及
  manifest parser identity 没有绑定实际加载的模块；
- 两项均先补真实 RED。description 现统一规范化并保留 raw；service 冻结
  `source -> stable module / parser name / reference-v1`，validate/record 对漂移 fail closed；
  build/collect 在创建目录或联网前实际 import 并核对模块常量，合法 fixtures 同步更新；
- 修复后 B0.1 SQLite `60/60`、历史 HTTP/parser `80 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django check、migration drift、workflow contract 和
  `git diff --check` 通过；
- 第四轮仍是 `REVISE`；该轮修复后进入同一 reviewer 第五轮限定复审，review 与 release
  继续 pending。

同一 reviewer 第五轮限定复审证据：

- inner session：
  `019fa062-e917-76e2-aacd-e807fb0f1f9b`；
- 本轮 fingerprint：
  `50b50866f19853534daad66c9a2cd18650d4d74cafbfebec106b09c8b36c274d`；
- 结论仍为 `VERDICT: REVISE`。第四轮 2 项 P2 已全部关闭；本轮新发现 4 项 P2：
  circuit 只应计入 transport failure、parse 失败时 raw 未持久化、HRN 可能跨 race heading
  block 取值、请求 timeout 没有唯一固定为 15 秒；
- 四项均先补真实 RED。collect 将 network 与 parse 分段并只对 transport failure 分类熔断；
  fetch 成功后、parse 前即保存 raw、responses ledger，并在失败时追加 `parse_error`；
  HRN 解析严格限定当前 race heading block；timeout 统一为唯一 15 秒；
- 修复后 B0.1 SQLite `64/64`、历史 HTTP/parser `80 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django check、migration drift、workflow contract 和
  `git diff --check` 通过；
- 第五轮仍是 `REVISE`；该轮修复后进入同一 reviewer 第六轮限定复审，review 与 release
  继续 pending。

同一 reviewer 第六轮限定复审证据：

- inner session：
  `019fa071-ca82-7b80-9af1-d4725efb6c`；
- 本轮 fingerprint：
  `41307729d9896c7fbd721b2e8864177990a7d190d3c25011b53a0bf284db0d87`；
- 结论仍为 `VERDICT: REVISE`。第五轮 4 项 P2 已全部关闭；本轮新发现 5 项 P2：
  `request_count` 漏计失败请求、HRN alias 过宽或映射错误、ZEturf 组合后缀 `FR + NP`
  未完全规范化、报告缺少重复指标、按 `event-id` 过滤时 run 计数包含无关运行；
- 五项均先补真实 RED。ledger 增加严格的 phase 与 `request_issued` 合同；HRN 使用显式双向
  alias 且禁止 substring；ZEturf 迭代剥离后缀；report 增加 duplicate runs/observations，
  并在筛选后对相关 run 做 distinct 计数；
- 修复后 B0.1 SQLite `69/69`、历史 HTTP/parser `80 OK / 4 conditional skips`、
  PostgreSQL concurrency `2/2`，Django check、migration drift、workflow contract 和
  `git diff --check` 通过；
- 第六轮仍是 `REVISE`；该轮修复后进入同一 reviewer 第七轮限定复审，review 与 release
  继续 pending。

同一 reviewer 第七轮限定复审证据：

- inner session：
  `019fa07f-90e2-7f60-b08d-125e01d55ba3`；
- 本轮 fingerprint：
  `6dd68951fe0ff90847c74f3873fb0539eec8226441473c294e7c444591ebba1a`；
- 结论仍为 `VERDICT: REVISE`。第六轮 5 项 P2 已全部关闭；本轮新发现 3 项 P2：
  不完整 ledger 仍可能被 record、unknown 结果被误算 complete、receipt 的 `SET_NULL`
  删除行为与 matched 必须有 event 的数据库约束冲突；
- 三项均先补真实 RED。record 现在要求 ledger 精确覆盖 manifest，并强绑定 source/final/
  response；unknown 计入 incomplete；历史 matched receipt 在 event 删除后保留 matched
  snapshot，数据库约束要求 snapshot，service 新建 matched receipt 时仍必须绑定 event；
- 修复后 B0.1 SQLite `78/78`、历史 HTTP/parser `80 OK / 4 conditional skips`、
  PostgreSQL concurrency + `SET_NULL` `3/3`，Django check、migration drift、workflow
  contract 和 `git diff --check` 通过；
- 第七轮仍是 `REVISE`；该轮修复后进入同一 reviewer 第八轮限定复审，review 与 release
  继续 pending。

同一 reviewer 第八轮限定复审证据：

- review session：
  `019fa08e-e782-7d31-9cbc-921bb3b4efbd`；
- review fingerprint 交接仅提供前缀：
  `d98034f…`；不得据此前缀虚构完整 digest，后续冻结以 reviewer 返回的完整原始输出为准；
- 本轮唯一 P2：collect 仍依赖 `runtime` 下的 safe HTTP 实现，会被默认开发
  `./server` bind mount 遮蔽；围绕唯一实现、兼容 wrapper 与 collect import 路径先取得
  3 项真实 RED；
- 修复后 `server/stable/race_event_safe_http.py` 成为唯一实现，
  `runtime/tools/race_event_safe_http.py` 仅保留兼容 wrapper，collect 直接 import stable
  实现；
- 主线程复验 B0.1 `80/80`、历史 HTTP/parser `81/81`（另 4 项 conditional skip）；
  Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 通过；
- 一次把整仓错误挂载到 app 容器的验证失败属于验证环境/挂载方式误用，不是产品失败或
  B0.1 回归，不计入上述 GREEN 证据；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第八轮唯一 P2 修复后进入同一 reviewer 第九轮限定复审，review 与 release 继续
  pending。

同一 reviewer 第九轮限定复审证据：

- review session：
  `019fa09e-88c5-7180-a678-39874ff6e045`；
- review fingerprint：
  `84e8f4fafc4db634911c9aa18f6f473bdba12078e2957072a660434505c5ce6f`；
- 结论：`VERDICT: REVISE`，1 项 P1 为 runtime CLI 的 `sys.path` 不能可靠导入 stable
  实现；3 项 P2 为 event/raw 未逐场强绑定、run `error_summary` 不完整、报告遗漏没有
  receipt 的失败 run；
- 四项均先补真实 RED 后修复：runtime CLI 导入路径闭合；event 与 raw 逐场绑定；
  `error_summary` 完整记录失败；report 纳入无 receipt 的失败 run；
- 主线程复验 B0.1 `82/82`、历史 HTTP/parser `82/82`（另 4 项 conditional skip），项目
  venv 下真实 runtime CLI `--help` 退出码为 `0`；Django check、
  `makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和 workflow contract
  通过；
- 使用系统 Python 运行时因缺少 `bs4` 的失败属于解释器/依赖环境误用，不是产品失败或 B0.1
  回归；项目 venv 的真实 CLI 结果才是本次验收依据；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第九轮仍为 `REVISE`；四项修复后进入同一 reviewer 第十轮限定复审。

同一 reviewer 第十轮限定复审证据：

- review session：
  `019fa0ad-c024-7a21-8ebb-31b19df760ab`；
- review fingerprint：
  `abbc00318318447abb86627ffe29a076012f8eceee4aa1b8d3f6c0c157dc4b20`；
- 结论：`VERDICT: REVISE`，唯一 P2 为 reference observations 必须与 ledger 中
  `outcome=parsed` 的 event 精确一一对应，`parse_error` event 必须零 observation；
- 先增加 2 项由该缺陷本身导致的真实 RED，再做最小实现；既有正向 fixture 同步修正为合法
  `parsed + observation`，跨 run replay 合同继续验证；
- 主线程复验 B0.1 `84/84`、历史 HTTP/parser `82/82`（另 4 项 conditional skip）；
  Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十轮仍为 `REVISE`；唯一 finding 修复后进入同一 reviewer 第十一轮限定复审。

同一 reviewer 第十一轮限定复审证据：

- review session：
  `019fa0b9-b2c8-77d0-9473-7caff58d87eb`；
- review fingerprint：
  `ef778594f1d471a239432c6bd65054dcb2491fb918c46a660ea321436a827b0d`；
- 结论：`VERDICT: REVISE`，2 项 P2 为共享 safe HTTP 默认 `4MiB / 2 跳` 会破坏 legacy
  大 PDF/redirect，以及跨日 run 的单日报告会把错误归到错误日期；
- 测试调查在纯 `origin/main` 确认旧 transport 没有 body cap，且 `urllib` 使用默认 redirect；
  围绕两项 finding 共取得 3 项真实 RED；
- 修复后 legacy 默认不自定义 body cap/redirect 上限，internal reference collect 仍显式使用
  `4MiB / 2 跳`；report 按 event/date 归属错误，并单列 `unattributed_errors`；
- 主线程复验 B0.1 `87/87`、历史 HTTP/parser `82/82`（另 4 项 conditional skip）；
  Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十一轮仍为 `REVISE`；两项 finding 修复后进入同一 reviewer 第十二轮限定复审。

同一 reviewer 第十二轮限定复审证据：

- review session：
  `019fa0c7-7f55-7960-9f5d-5b81ba13437c`；
- review fingerprint：
  `6b0246db6647786e351492822d86f70a8dd15dbb272a19a6a34a324f15ca7b3b`；
- 结论：`VERDICT: REVISE`，2 项 P2 为 matched 没有核对来源赛事名，以及单日无 receipt
  错误没有回退到 run 的唯一日期；
- 测试调查确认可以复用 race-live 的 exact normalized alias 合同并将其冻结进 manifest，
  两项 finding 均取得由反例触发的真实 RED；
- 修复新增公开 normalization helper；manifest 冻结 `normalized_accepted_race_names` 并将其
  纳入 snapshot SHA，record 要求来源赛事名 exact membership；单日 run 增加唯一日期
  fallback，过时 fixture 按新合同修正；
- 主线程复验 B0.1 `89/89`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）；真实 PostgreSQL 并发/锁 `2/2`、`SET_NULL` `1/1`，
  临时容器验证后已删除；
- Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十二轮仍为 `REVISE`；两项 finding 修复后进入同一 reviewer 第十三轮限定复审。

同一 reviewer 第十三轮限定复审证据：

- review session：
  `019fa0db-0a80-72c0-a6ad-bb1142432a83`；
- review fingerprint：
  `384ef97820f9e6d9c0c8f6df7190f1fb546746570aff018379b742a41e3b0c00`；
- 结论：`VERDICT: REVISE`，3 项 P2 为 collect 遇到来源异名时没有降为 `source_only`；
  多日错误 detail 缺少 `local_date`；`--event-id` 漏掉无 receipt 但错误明细匹配的 run；
- 三项 finding 各取得真实 RED。修复后 collect 按冻结赛事名 exact membership 分类；
  ledger 每个 event 冻结 `local_date` 且 record 复核；event filter 按错误 detail 纳入相关
  run，同时隔离该 run 的其他错误；6 个旧 fixture 补齐新合同必需字段；
- 主线程复验 B0.1 `93/93`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）；真实 PostgreSQL `3/3`，临时容器验证后已删除；
- Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十三轮仍为 `REVISE`；三项 finding 修复后进入同一 reviewer 第十四轮限定复审。

同一 reviewer 第十四轮限定复审证据：

- review session：
  `019fa0ea-65a3-7383-b208-c0f571e7b98a`；
- review fingerprint：
  `18ac8b531f2d123b132fbe45104999feeea814315087ac6e4cdc0d043a4baeae`；
- 结论：`VERDICT: REVISE`，2 项 P2 为 record 丢失 artifact 采集窗口，以及无 receipt
  失败 run 没有计入 `duplicate_runs`；
- 测试锁定 `started_at = 最早 ledger fetched_at`、`finished_at = artifact.completed_at`，
  并要求逆序、naive datetime 和显著未来时间 fail closed；另以同 event/day 的失败 run
  重复分组取得真实 RED；
- 修复增加 5 分钟 clock skew 容忍并原子保存签名时间窗口；report 将 receipt 与 error
  details 统一纳入 run membership 后计算重复；
- 主线程复验 B0.1 `96/96`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）；真实 PostgreSQL `3/3`，临时容器验证后已删除；
- Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十四轮仍为 `REVISE`；两项 finding 修复后进入同一 reviewer 第十五轮限定复审。

同一 reviewer 第十五轮限定复审证据：

- review session：
  `019fa0fa-b908-7d43-9f7e-807bf132a9a3`；
- review fingerprint：
  `59ffcb96972cef74dcff8df87e5a9d1b0f3923ecf59f5f5b594e58e48594424f`；
- 结论：`VERDICT: REVISE`，2 项 P2 为采集窗口只校验最早 ledger 时间，以及 observation
  provenance 的 `fetched_at/final_url` 没有逐 event 绑定；
- 以重新签名 artifact 的反例取得真实 RED。修复要求 `max(ledger fetched_at) <=
  artifact.completed_at`，并要求每个 observation 的 `source_url/final_url/fetched_at`
  及 raw/ref/hash 与 manifest、parse ledger、response 逐 event 精确一致；
- 主线程复验 B0.1 `98/98`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）；真实 PostgreSQL `3/3`，临时容器验证后已删除；
- Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十五轮仍为 `REVISE`；两项 finding 修复后进入同一 reviewer 第十六轮限定复审。

同一 reviewer 第十六轮限定复审证据：

- review session：
  `019fa106-3b52-7a02-b756-31f718ffe4d0`；
- review fingerprint：
  `571664940ea3e77b60368fe4ddf72292404060fedfb27f281d6b7f7d1f815cc7`；
- 结论：`VERDICT: REVISE`，唯一 P2 为 Payload/Receipt 的 `QuerySet.update()`、
  `bulk_update()`、`delete()` 可以绕过 append-only；
- 围绕批量绕过取得 6 项真实 RED，并以 5 项实例操作/`SET_NULL` 正例锁定合法行为；
- 修复新增专用 QuerySet/Manager：Payload 的上述批量变更全部拒绝；Receipt 仅允许
  Collector 精确执行 `event=None/event_id=None`，其他批量变更全部拒绝；无需迁移；
- 主线程复验 B0.1 `104/104`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）；真实 PostgreSQL `3/3`，临时容器验证后已删除；
- Django check、`makemigrations --check --dry-run`、`py_compile`、`git diff --check` 和
  workflow contract 均通过；
- Compose config 仍因隔离 worktree 缺 `.env` 未执行成功，不能宣称 Compose 已通过；
- 第十六轮仍为 `REVISE`；唯一 finding 已修复，但最终 review 与 release 继续 pending。

同一 reviewer 第十七轮与 latest-main 集成证据：

- session `019fa113-9c02-7c63-b48d-466c40d323cf` 对 fingerprint
  `5095a06e326a9cef470f4ef5d2111c87e8daa77a45fbc9507a27b024369edea7`
  给出 `APPROVED`，P0/P1/P2/P3 均为 0，审前审后 fingerprint 一致；
- 随后 fetch 发现 `origin/main` 从 `e7dc1b20` 前进到 `6ac08e40`，候选迁移到最新 main；
- 集成后 B0.1 `104/104`、race-live `23/23`、历史 HTTP/parser `82/82`
  （另 4 项 conditional skip）、真实 PostgreSQL `3/3` 通过；
- 上游新增 recovery/P0 URL/HTTP budget 组合的 `14/87` macOS 路径错误在纯
  `origin/main@6ac08e40` 精确复现，不是 B0.1 增量；
  不跨父提交复用。

## 2. 阶段 A：生命周期

| ID | 场景 | 预期 |
|---|---|---|
| A01 | 有出走时间，T-1 秒 | 保持 scheduled |
| A02 | 到达 aware `race_datetime` | 单次 scheduled -> running |
| A03 | T+30 分钟无赛果 | finished，result_confirmed_at 仍空 |
| A04 | 来源任务失败 | 时间状态仍推进，不生成 result/revision |
| A05 | 无时间，当地赛事日 23:59 | 不推进 |
| A06 | 无时间，当地次日 00:00 | finished，结果待补全 |
| A07 | `Europe/London` DST 开始/结束 | 边界由 ZoneInfo 正确换算 |
| A08 | `Europe/Paris` DST 开始/结束 | 同上 |
| A09 | `America/New_York` DST ambiguous/nonexistent | 有 offset 正确；无 offset fail closed |
| A10 | `America/Los_Angeles` 与纽约同 instant | 当地日期/时间分别正确 |
| A11 | 日本/香港 | 不受 DST 影响 |
| A12 | 无效 timezone | 不推进，记录错误，不用服务器时区 |
| A13 | cancelled 到点 | 不变 |
| A14 | postponed 旧时间到点 | 不变 |
| A15 | 延期写新时间/generation | 旧 generation task 拒绝，新时间生效 |
| A16 | 同任务重复 10 次 | 只一条有效 transition |
| A17 | 两 worker 同时处理 | 只一次状态更新/审计 |
| A18 | claim 超时 | 后续 scanner 可回收 |
| A19 | dry-run | 零业务/审计写入，返回计划 |
| A20 | shadow | 写候选审计，不改变公开 status |
| A21 | enforce | 原子写 status/audit/control |
| A22 | 事务晚期失败 | status/audit/control 全回滚 |
| A23 | official/corrected 已存在 | 不回退结果 phase |
| A24 | provisional 已存在 | finished 与 provisional 同时成立，confirmed_at 为空 |
| A25 | 无 lifecycle control | 默认不启用、不隐式回填执行 |
| A26 | 显式纳管 manifest apply 两次 | 第一次建档，第二次 replay，零重复 |
| A27 | priority/featured/visibility 失去资格 | 既有 control 关闭，不扫描全表扩容 |
| A28 | 新重点赛事不在 manifest | 不自动纳管 |
| A29 | shadow 三次后首次 enforce | 一条 proposal、一条 applied、状态只改一次 |
| A30 | enforce 再重放 | applied 不重复 |
| A31 | 香港/英国/法国使用其他有效 IANA zone | 全部 fail closed |
| A32 | 日本使用非东京有效 zone | fail closed |
| A33 | 美国 `America/*` 与 manifest 审核 zone 不同 | fail closed |

## 3. 来源权威与字段审计

| ID | 场景 | 预期 |
|---|---|---|
| B01 | 官方结构化写空字段 | 写入 authority=500 与 field change |
| B02 | 专业 API 后写不同值 | 不能覆盖官方 |
| B03 | 官方新闻覆盖可信媒体 | 允许并升级 authority |
| B04 | 同 authority 同值重放 | 不重复 field change |
| B05 | 同 authority 不同值 | 冲突候选，不覆盖 |
| B06 | 人工 lock | 任一自动来源不覆盖 |
| B07 | 闸位变化 | old/new/source/url/confidence/task 完整 |
| B08 | 骑师变化 | 同上 |
| B09 | 退赛变化 | runner 状态与审计一致 |
| B10 | 时间变化 | instant/local fields/generation 原子一致 |
| B11 | provider omission | 不自动解释为退赛 |
| B12 | 多地区某来源 429 | 仅该来源降频，其他地区继续 |
| B13 | 请求预算耗尽 | 无新网络请求，保留 due/retry 证据 |
| B14 | racecard/result owner 为 live | 历史/普通候选不能抢写 |
| B15 | 同场两匹马分别更新 jockey/barrier | authority/change 以 stable_key 隔离 |
| B16 | participant stable identity merge | 未审核不合并；审核后 provenance 可追溯 |
| B17 | 已付费但非官方聚合 API | authority 仍为 supplemental，不得产生 official |
| B18 | 合同只授权英国 official | 不得把同 provider 的法国/日本数据提升为 official |
| B19 | `provider_contract_version`/schema 变化 | registry fail closed，旧批准不自动继承 |
| B20 | racecard 只覆盖未来 7 天 | 不得伪装满足 P0 T-21/T-14 窗口 |
| B21 | 商业来源超额、停服或合同到期 | fallback 生效，时间状态继续推进，不伪造字段/结果 |
| B22 | JRA external event ID 尝试绑定 NAR/JPN1 | 身份拒绝、零写；不能只按 `JPN1`/地区名称路由 |
| B23 | NAR provider 合同/许可未冻结 | provider 保持关闭，时间生命周期仍推进 |
| B24 | TRA 法国某场 G1 缺失 | 逐场 fail closed/result pending，不从地区库存推断覆盖 |
| B25 | North America entries 省略 runner | 不解释为退赛；只有明确 `changes` 语义才可候选 |
| B26 | 爱尔兰赛事进入 selector | 本 change 拒绝纳管，不映射为英国或 `other` |
| B27 | snapshot 无 `COMPLETE`/签名或 payload hash 错 | 整批零写，消费水位不推进 |
| B28 | snapshot collector/build/schema/contract/token 漂移 | fail closed，旧 token 在轮换后不可重放 |
| B29 | snapshot 重放/乱序/缺前驱 | 重放 noop；乱序和缺前驱零写并告警 |
| B30 | snapshot DB 事务失败 | 字段候选和 high-watermark 同时回滚 |
| B31 | collector split brain | 只有 registry 活动 fencing token 被接受 |
| B32 | Sporting Life reference wrapper | 仅 finished 输入；输出统一 v1 schema，不创建正式 candidate/result |
| B33 | ZEturf reference wrapper | `R/C`、日期、马场、赛事名唯一匹配；历史误配 fixture 保持 ambiguous |
| B34 | HRN reference wrapper | 仅 finished 输入；重复 DOM 去重，启发式字段保留 raw，result 默认 partial |
| B35 | manifest collect | 数据库零写、Celery 零 dispatch、公开表计数零变化 |
| B36 | record 内部观察 | 只新增 reference run/payload/receipt |
| B37 | 同语义事实、不同 fetched/raw 跨 run | payload 复用；两个 run 各有 provenance 不同的 receipt |
| B38 | 相同来源内容变化 | 追加新 payload，旧 payload/receipt 保留 |
| B39 | 名称单信号/多个候选 | unmatched/ambiguous，不绑定 event |
| B40 | source/region 不匹配 | fail closed，整批零写 |
| B41 | record 事务晚期失败 | run/payload/receipt 全部回滚 |
| B42 | public race calendar/detail/API/sitemap | 不查询、不展示 reference 数据 |
| B43 | 新闻/QQ/race-live/lifecycle | collection 前后零新增、零状态变化、零 dispatch |
| B44 | Admin 普通用户/未登录 | 不可见 |
| B45 | Admin reference viewer | 只读；无 add/change/delete/promotion |
| B46 | 未提供 `--allow-network` | collect 零网络；record 永远无网络 |
| B47 | Celery 边界 | B0.1 不注册 task/route/Beat/worker |
| B48 | 单来源 403/429/timeout/DOM drift | 无自动重试；连续 3 次开 circuit，本来源停止，下一来源仍可独立运行 |
| B49 | 多日观察报告 | 输出覆盖、延迟、完整度、partial/mismatch 和 event/source/day 重复运行 |
| B50 | legacy authority 字段 | `official/is_confirmed/official_finish_position` 不进入 payload/admin |
| B51 | schema 上限与 forbidden key | 额外字段、深度>12、runner>80、payload>256KiB、float 均拒绝 |
| B52 | 同 payload 重新匹配 | 新 manifest/classifier 下新增 receipt，旧 receipt 不修改 |
| B53 | 双进程并发 record | 同 artifact 只有一个 run；不同 run 同 payload 只有一个 payload且 receipt 完整 |
| B54 | manifest 信任根 | canonical SHA、provider key/URL 不一致、错误 source、DB drift 均整批零写 |
| B55 | source URL 越界 | 非固定 HTTPS host/path 或 redirect 越界拒绝 |
| B56 | HTTP 响应合同 | MIME 缺失/非法/冲突、长度>4MiB、redirect>2 只失败当前来源 |
| B57 | artifact 重启连续性 | 精确文件集合无自引用；缺 marker/多文件/symlink 均不可 record |

## 4. 新闻特殊放行

| ID | 场景 | 预期 |
|---|---|---|
| C01 | 官方闸位公告＋唯一赛事＋高置信 | 绕过普通分数进入发布流程 |
| C02 | 退赛/骑师/名单/时间延期 | event_type 与 extracted_changes 正确 |
| C03 | 翻译失败 | 仍阻断 |
| C04 | 高度重复 | duplicate 终态/阻断 |
| C05 | 窗口 fingerprint 重复 | 特殊池不选 |
| C06 | 只出现赛事名 | 不特殊放行 |
| C07 | 跨届同名、日期不明确 | review_required |
| C08 | 多个候选赛事 | 不写入 |
| C09 | confidence 89 | 不特殊放行 |
| C10 | confidence 90 且明确变更 | 可绕过软门禁，但仍过 validation |
| C11 | 缺标题/正文/source URL | 阻断 |
| C12 | published_at 未验证 | 阻断 |
| C13 | 核心术语/实体冲突 | 阻断 |
| C14 | 来源未 production approved | 阻断 |
| C15 | 普通地区配额已满 | 使用独立特殊小配额 |
| C16 | 特殊小配额已满 | 延后，不丢失，不占普通配额 |
| C17 | 新闻发布事务失败 | RaceEvent 字段零变化 |
| C18 | 新闻发布成功、candidate apply 失败 | 新闻保持公开，候选可重试 |
| C19 | 可信媒体与官方字段冲突 | 人工候选，不能覆盖 |
| C20 | `possible_duplicate_content` blocker | 仍阻断或转人工，不得特殊放行 |
| C21 | 内容编辑后 hash 漂移 | 旧 assessment 失效，需重评 |
| C22 | 重放 publish task | 不重复公开/AutomationLog |
| C23 | QQ | `(article,target)` 仍唯一，racecard_update 默认不自动 QQ |

## 5. 赛果与现有链路回归

| ID | 场景 | 预期 |
|---|---|---|
| D01 | T+2:59 | 不请求赛果 |
| D02 | T+0 | 只 CAS 到 awaiting_result、next=T+3、transport 调用 0 |
| D03 | T+3:00 | 已批准 tracking 首次调用 provider |
| D04 | provisional | tracking provisional，result is_confirmed=false |
| D05 | official | official authority/marker 后 confirmed=true |
| D06 | supplemental 声称 official | 拒绝 |
| D07 | T+30 来源仍失败 | RaceEvent finished、tracking awaiting、无伪造结果 |
| D08 | 无时间次日 | finished＋补采候选，不直接启动未批准 provider |
| D09 | corrected | official -> corrected 受控前进 |
| D10 | 现有 event 924 | publication/read/kill-switch 行为不回归且不重跑 |
| D11 | scheduler disabled | selector 不 claim/dispatch |
| D12 | race_live_worker | 只消费 race_live queue |
| D13 | 生命周期任务 | 不重复 dispatch 同一 live claim |
| D14 | JRA 三名阶段 | 只能 provisional，`result_confirmed_at` 为空 |
| D15 | JRA 五名阶段重放 | 仍 provisional，审计和 revision 不重复 |
| D16 | JRA 全马但 marker 未登记 | fail closed，不 official |
| D17 | JRA proof 中明确最终 marker | official，且只设置一次 confirmed_at |
| D18 | JRA official 后明确 correction marker | corrected，保留前序 revision |
| D19 | NAR CSV 使用 JRA marker | 拒绝；必须命中 NAR 独立合同 |
| D20 | 美国长期无官方复核 | 保持 provisional/official-overdue，不伪造 official |

## 6. 性能、页面与回归

1. 100 个 due control 的选择不超过 8 个查询，内存由 batch size 限制。
2. 并发 scanner 使用 `skip_locked`，没有全表锁。
3. 日历和详情在同一 commit 后显示一致状态。
4. `RaceEvent` save 与 bulk lifecycle apply 都能失效赛事 cache。
5. 日历 query 继续满足既有 live read `<=12` 门禁。
6. 1440px/390px/320px 日历月份、等级 badge、无横向溢出不回归。
7. 赛事详情的暂定/正式标签不回归；provisional 不显示为“正式赛果”。
8. 字段归一化测试、赛事导入/历史 inventory、racecard sync、race-live、新闻 validation、
   publishing window、QQ delivery 全部回归。
9. `manage.py check`。
10. `makemigrations --check --dry-run`。
11. PostgreSQL 竞争/事务测试。
12. `git diff --check`。
13. 一次性 dry-run 连续执行两次均为零数据库写入/零 Celery dispatch；持久 scanner 不支持
    dry-run mode。
14. rollback baseline manifest 的 SHA、generation 漂移、反向 candidate dry-run 和隔离恢复。

## 7. 推荐测试文件

- `server/stable/test_race_event_lifecycle.py`
- `server/stable/test_race_event_lifecycle_postgres.py`
- `server/stable/test_race_event_field_authority.py`
- `server/stable/test_race_reference_sources.py`
- `server/stable/test_race_reference_sources_postgres.py`
- `server/stable/test_race_news_impact.py`
- 扩展现有 `test_realtime_race_results.py`
- 扩展现有 `test_race_live_racecard_sync.py`
- 扩展现有 publishing/validation/QQ 测试

## 8. 2026-08-28 实际新增与回归覆盖

| 编号 | 用例 | 结果 |
|---|---|---|
| E01 | 来源等级、同级时间/provider 稳定决胜、manual lock | 通过 |
| E02 | race time/racecard 最慢 12 小时与临赛加密 cadence | 通过 |
| E03 | future discovery 唯一匹配、standing policy、route drift | 通过 |
| E04 | claim generation/token/plan SHA 过期完成拒绝与动态 successor | 通过 |
| E05 | T/T+30 lifecycle、postponed、无时间、幂等 transition | 通过 |
| E06 | The Racing API host/path/budget、分页、racecard/result 解析 | 通过 |
| E07 | API not-found 后官方导入优先、再尝试地区第三方 receipt | 通过 |
| E08 | partial/multi-match 不投影、complete receipt 自动投影 | 通过 |
| E09 | immutable revisions、dead heat reported position、更正观察 | 通过 |
| E10 | 公开页统一“赛果”、无来源阶段标签、陈旧警告保留 | 通过 |
| E11 | 审计 missing policy 为 blocked、有效 policy 为 ready、route drift 阻断 | 通过 |
| E12 | 全新数据库全配置 dry-run 前后 hash 不变 | 通过 |

最终聚焦命令共执行 171 个测试，全部通过；隔离 PostgreSQL 16 的并发/事务专项 23/23 通过；另有
`manage.py check`、`makemigrations --check --dry-run` 和 Python compileall 通过。
