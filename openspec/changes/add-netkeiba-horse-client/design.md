## Context

日本滚动批次的唯一抓取通道是 `_JBISClient` 名称检索（`p0_horse_completion_source_clients.py:1929+`），对同名马 fail closed。2026-07-22 生产实测：队列前 100 匹 100% `ambiguous_identity`。身份回填已为日本 2,462 匹提供 netkeiba key，netkeiba 马匹页 URL 可直接构造，页面含完整资料与生涯。

既有约束：客户端基类 `_BaseSourceClient`（同文件，allowed_hosts + 预算钩子 + 缓存）；adapter 注册 `_CLIENTS`（同文件 ~3062）；身份锁 `_require_expected_identity_matches_payload`（`p0_horse_completion_adapters.py:917-981`，provider-bound 时放宽四字段锁）；净keiba 保守限速 8s 已配置；`ExternalHorse`（netkeiba, 12,405 条）父母/出生日期全空。

## Goals / Non-Goals

**Goals:**

- 有 netkeiba key 的日本候选经 ID 直取完成 prepare：身份锁 provider-bound 通过、四字段与生涯从页面提取。
- 页面解析失败一律 fail closed，不猜值。
- 重跑首个日本滚动批次并验证批次自动首发。

**Non-Goals:**

- 不改 JBIS 客户端；不做 netkeiba 全站抓取；不批量修复 ExternalHorse 存量空四字段；不入库预测/评论类专有内容；不绕过限速与预算。

## Decisions

### 1. netkeiba 客户端结构与抓取序列

新增 `_NetkeibaClient(_BaseSourceClient)`：`provider_name = "netkeiba"`、`allowed_hosts = frozenset({"db.netkeiba.com"})`、`record_authority_status = "source_records_verified"`。抓取序列 **3 页/马**（实测页面结构）：马匹页 `/horse/{id}/`（基础资料表 `db_prof_table` + **通算成績总数** + 标题行性别/毛色）→ 战绩页 `/horse/result/{id}/`（`db_h_race_results` 逐场）→ 血统页 `/horse/ped/{id}/`（`blood_table` 两代六字段）。生涯总数在**马匹页**（`通算成績 13戦6勝`），不在战绩页；`source_url` 用马匹页 URL 使 `official_start_count_source_url` 指向携带总数的页面。日本每候选预算 3→**4**（3 页 + 1 次 redirect 余量，redirect 计入预算；JBIS 路径仍只用 3）；**不做 netkeiba 失败中途回退 JBIS**（2+3 超预算且必然 fail closed）。

### 2. 客户端选择层（review P0-1 修正）

`_CLIENTS` 每地区只有一个客户端类，且 prepare 每地区只实例化一次（per-client `batch_limit` 计数）。选择层实现为：

1. **select 阶段 namespace 偏好**：日本候选持有 netkeiba key 时 `source_namespace` 直接取 netkeiba；其余情况保持既有 identity_keys 顺序扫描（确定性，不引入 frozenset 迭代——独立 review P1-1 修正）。
2. **dispatcher 客户端**：`_CLIENTS[japan]` 注册组合 dispatcher，按 `request.candidate_source_name == "netkeiba"` 分发 `_NetkeibaClient`，否则 `_JBISClient`（HKJC 的候选守卫为先例）；`last_request_count` 与 `_request_count` 在 finally 中双向代理（异常下也正确）；`batch_limit` 由 dispatcher 自身统一执行（地区上限 1×，子客户端上限不可达——独立 review P2-3 修正文档口径）。

### 3. 身份判据

- payload external ID = URL 中的数字 ID，必须与候选 key ID 完全一致（provider-bound）。
- 客户端先把 netkeiba 页面马名的**括号国别后缀**（如 `(USA)`）剥除再写 `identity.horse_name`；比较器是 adapter 的 `_normalized_text`（NFKC + casefold + 空白折叠），不是 `_normalize_identity_name`。原始页面名与罗马字英文名进 `aliases`（身份锁会查 aliases）。净keiba 页面只有罗马字英文名，无中文别名。
- **部分期望字段陷阱**（如实记录）：候选只要带任一非空 sire/dam/birth_year 期望值，provider-bound 放宽即失效，全部期望字段必须命中——回填四字段只填了一部分的候选仍会 fail closed，重跑预期成功率口径应排除这类候选。

### 4. 解析与字段口径

- 基础资料：`country` 由 `db_prof_table` 的 `産地` 判定——单字缩写按映射表（`米`→美国等）；多字值为国内产地（北海道等）→ `日本`；**未识别的单字标记 fail closed**（不得误标日本）；缺失 fail closed（独立 review P2-4 修正）。`sex`/`color` 来自标题行（`現役　牡4歳　芦毛`），毛色必须命中白名单（鹿毛/黒鹿毛/青鹿毛/青毛/芦毛/栗毛/栃栗毛/尾花栗毛/白毛），不命中即 fail closed 不猜字段（独立 review P1-2 修正）；`trainer` 剥 `（栗東）` 类后缀；`馬主` 单元格前置 `<img>` 忽略；生产牧场取 `生産者`。
- 血统：`blood_table` 两代六字段（父 = row0 cell0、父父 = row0 cell1、父母 = row8 cell0、母 = row16 cell0、母父 = row16 cell1、母母 = row24 cell0）；名称剥 `(米)` 国别标记、年份、毛色、`[血統][産駒]` 标记。payload 校验要求**六字段全非空 + birth_date 为完整 ISO 日期**——**只有年份的出生日期 = 该候选 fail closed 阻断**（不虚构月日，也不存在精度保留路径）；任一血统字段缺失同理阻断。
- 生涯逐场：`db_h_race_results` 行：日期（`YYYY/MM/DD`）、開催（`大井` 或 `2中山8` 格式）、レース名（含 `(JpnI`/`(OP)` 等级标记保留原文）、着順、騎手、馬番、斤量、距離（`ダ1200` 原文保留、单位统一为米但原文必须保留）、タイム。
- 异常状态映射（客户端层翻译，与 JBIS 先例一致并补齐）：`取消→scratched`、`除外→withdrawn`（两者不计出赛）、`中止→did_not_finish`、`失格→disqualified`（两者计出赛）；未映射状态不得折叠 unknown 放行（会变成 `unconfirmed_start_status` 阻断，这是既有行为，保持）。
- 海外行判定：開催不符合 JRA `回場日` 格式且不在 NAR 场地名单 → `is_overseas=True`，场地与比赛名保留原文。
- `source_start_count` 只计实际出赛（排除 scratched/withdrawn），与通算成績（中央+地方合计）对账，不一致进缺口。
- 逐场日期非精确（如老年份 2 位年）会产生 `race_record_core_evidence_missing` 阻断（既有行为，保持并如实记录）。

### 5. 规格与合规

沿用 `_default_source_client_factory` 的每地区预算账本与 per-host 限速（8s）；429/5xx 有限重试、4xx 不重试（既有基类行为）。payload 复用 `_BaseSourceClient._payload`（形状与 JBIS 相同，`adapter_key` 自动为 `japan_jbis`——地区键非来源键，如实记录）。批量执行前复核 netkeiba 访问条款。

### 6. 编码与缓存（生产首轮返修，2026-07-22）

- **EUC-JP 解码**：netkeiba 响应 `Content-Type: text/html` 无 charset，requests 按 ISO-8859-1 解码得到乱码（生产首轮 61/100 因此阻断）。客户端一律用 `_netkeiba_page_text` 对原始 bytes 按 EUC-JP 解码后再解析。
- **跨源缓存守卫**：候选级缓存只按 candidate_key 寻址，不区分来源；日本 dispatcher 引入双来源后，JBIS 时代缓存会让 netkeiba 候选的 provider-bound 失效并永久卡死四字段锁（生产首轮 39/100 因此阻断）。`run_p0_horse_completion_adapter` 对日本地区校验缓存 payload 的 `source.name` 与候选 `candidate_source_name` 一致才允许命中；其他地区（美国 equibase/HRN 互补流）保持既有跨来源缓存语义。

### 7. 第二轮生产发现与恢复设计（2026-07-23）

批次 `p0batch-e5cee174ba05` 后续已在相同相关代码下完成 prepare，说明早先 `7/100` 无声退出更符合 detached exec/进程会话中断，而非第 8 个候选的稳定 Python 异常。该批最终为 `27/100` 完整、`73/100` 阻断、`300` 次请求：`62` 个 `title_sex_color`、`10` 个四字段身份不完整、`1` 个履历核心证据不足。普通解析异常均被现有 prepare 转为 blocker staging，因此没有错误数据写库。

- **标题状态**：真实已注销页面使用 `抹消　牡　黒鹿毛`，既有正则只接受 `登録抹消` 等状态。解析应把状态、性别、毛色分开验证，精确加入 `抹消`，未知 token 继续 fail closed；不得把整行改成任意前缀的宽松匹配。
- **部分期望字段诊断**：受控复现已确认样本页面实际四字段齐全；10 个 `identity_incomplete` 来自候选仅携带部分 `expected_sire_name/expected_dam_name/expected_birth_year`，触发既有完整期望锁。该锁不得放宽；错误必须列出候选缺少的期望字段并归类为可解释的 source/identity blocker，而不是 `unexpected_adapter_error`。
- **异常履历行 characterization**：单个 `partial_career` 的第 15 行为 `2025-03-17 水沢 C1`，页面行有骑师/距离/马号但头数与着顺为空，马体重为 `計不`；这些事实不足以证明实际出赛或取消。先写 characterization 测试保存该不确定性；只有官方页面/结果证据能证明合法状态时，才另写期望映射与计数语义的 RED 测试后实现，否则保持 blocker。
- **解析器版本与 cache 绑定**：`adapter_config_fingerprint()` 当前只覆盖 schema、来源集合、预算和批次上限，代码改动不会使已成功 staging 失效。新增显式 `NETKEIBA_PARSER_VERSION`（机器稳定常量）并纳入 fingerprint，同时写入 netkeiba canonical source payload；日本同来源 cache 缺失或不匹配当前版本时强制 cache miss。网络刷新成功后必须在 sidecar 文件锁内原子替换 stale cache，并让并发调用复用同一份当前版本 payload；普通 cache 首写仍保持 no-clobber，其他来源/地区不变。任何会改变 canonical payload 的 netkeiba 解析规则都必须递增版本并用测试锁定。
- **批次处置**：blocked payload 也按候选级 `succeeded` 保存，故修复后不得直接重跑当前 prepared 批次或手改 checkpoint。当前批只保留证据、不 bundle/commit；新版本部署后 abandon，再重新 select/approve。旧 netkeiba canonical cache 因缺少当前 parser version 不再复用，新批在预算内重新抓取。
- **验收阈值**：不要求来源天然缺失的候选达到 `100/100`，但要求 `unexpected_adapter_error=0`、已支持结构造成的系统性 blocker=0；剩余 blocker 必须字段级可解释。仅完整且经 xlsx 人工复审的子集可以 bundle/commit，并核验自动首发与审计。
- **运行态恢复**：每个触网窗口结束都必须把 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false` 注入实际执行容器并验证，不能只改 `.env`。2026-07-23 已恢复 false，web/Nginx 与公开健康检查通过。

### 8. 发布候选与正式批准拆分（task 5.3 门禁修复）

现有 `--bundle` 只生成 research/mapping/authority，而 `--commit` 才生成 commit artifact 与
release manifest，随后在同一调用内 dry-run、真实写库和自动首发。这样无法在写库前把最终
artifact SHA、预计动作与自动首发范围交给用户做精确授权；提前调用
`build_region_release_manifest` 又会把 `approved_by` 和 `release_approved` 写入可信账本，错误地把
内容复审冒充生产发布批准。

最小改动是在既有 batch command 增加 `--prepare-release` 阶段，并复用
`prepare_reviewed_p0_completion_artifact`：

1. `--bundle` 仍生成并冻结 research/mapping/authority，仅纳入无 `failure_reason` 的完整子集。
2. `--prepare-release` 重算并规范写出 `commit_artifact_{region}.json`，从 artifact 自带的
   `expected_actions` 读取预计 profile/race/source/audit 动作。commit artifact 现有
   `prepared_at=now()` 会导致同一输入得到不同 SHA，因此本阶段为准备函数增加可选的确定性
   `prepared_at`：batch 路径固定使用已冻结 mapping 的人工审核时间，旧入口不传参时保持原行为。
   正式 commit 重算时复用 candidate 绑定的同一时间值。
3. 自动首发范围必须从 commit artifact 的已复审行推导，不能复用当前
   `_run_region_publish` 的“整个地区 batch manifest”集合。后者会把 39 个 blocker 也列为发布
   目标，是本门禁必须一并封闭的越界。对 artifact 中 `update_existing` 记录精确 profile ID；
   对 `create_new` 记录确定性 identity key，并在 commit 后只加入本次 completion run 实际创建的
   profile。对既有 profile 另记录当前
   `review_status`、hidden/manual-lock 状态和预计 disposition
   （`attempt_publish_after_commit` / `skip_already_published` / `block_hidden` /
   `block_manual_lock`）。未进入 artifact 的 blocker 不得出现在 candidate 或自动首发目标中。
4. 生成 `p0_horse_production_release_candidate.v1`，状态固定
   `pending_independent_release_approval`，绑定 batch manifest SHA、combined artifact SHA、
   三个 bundle SHA、commit artifact SHA、production snapshot SHA、预计动作与自动首发范围。
   candidate 不含 `approved_by`，只写 `release_candidate_prepared` 证据事件，不写
   `release_approved`。
5. commit artifact、candidate 与正式 v2 release manifest 均按完整 SHA 使用候选专属不可变路径，
   不复用会被下一候选覆盖的地区固定文件名。batch state 的 `release_candidate:{region}` 只作为当前
   待批准候选指针，同时保留按 SHA 索引的历史记录。重复 prepare 若输入和生产快照未变，
   应产生字节一致的 candidate。为保证确定性，candidate 不写易变生成时间；人工审核时间沿用已冻结
   mapping。candidate 文件原子替换、state 写入、账本查重与
   `release_candidate_prepared` 追加必须全部位于现有 batch serial/file lock 内；查重在持锁后执行，
   因而相同 candidate SHA 的重复或并发 prepare 都只产生一条证据事件。
6. `--commit` 新增必填 `--release-candidate-sha256`。提交前重新加载 candidate、重算 artifact、
   预计动作和自动首发范围并逐项比较；任何差异均在正式 release manifest 和数据库事务前阻断。
7. 用户授权后才生成正式 manifest。既有
   `p0_horse_production_release_manifest.v1` 继续只服务历史 trusted/rolling release 的复验，
   validator 保持其原五项 bindings 合同；新 rolling release 使用
   `p0_horse_production_release_manifest.v2`，其 bindings 在原五项之外强制新增
   `release_candidate_sha256`。builder 不再生成新 v1，validator 按 schema 分支校验，防止破坏旧发布
   回放。
8. 同一 candidate 只能对应一个正式 release manifest。首次批准在 batch serial/file lock 内写入
   `approved_by` 与唯一 `approved_at`，原子发布 manifest，幂等追加 `release_approved` 后写 state；
   重复 commit 必须复用相同 manifest/SHA。若进程在 manifest 或账本写入后、state 写入前崩溃，
   恢复逻辑应从同目录 manifest 与账本验证 candidate SHA、approver 和 executor 后复用，不得生成
   新批准。相同 candidate 以不同 approver 重试时 fail closed。数据库 commit 后崩溃继续依赖既有
   artifact 幂等语义，publish retry 始终使用 candidate 冻结的 reviewed scope。
9. 若旧 candidate 已批准但尚无 `HorseProfileCompletionRun(COMMITTED)` 或等价 artifact 落库证据，
   新一轮 `prepare-release` 与针对新 SHA 的明确授权可以推进到新的候选专属 v2 manifest；系统保留
   旧 manifest/ledger，并幂等追加 `release_superseded` 关联旧、新 candidate/release SHA。若旧
   artifact 已落库，则严禁换候选，必须按旧 candidate 做幂等恢复，防止一批多次提交。
10. 正式 manifest 已存在但数据库尚未落库时，每次 commit 重试仍必须重新生成 artifact、预计动作和
   当前自动首发范围，与已批准 candidate 逐项比较。`hidden_at`、`review_status`、manual lock 等任何
   发布资格漂移都在 DB 写入前阻断并要求新 candidate/new SHA 授权；只有确认 artifact 已完整落库后，
   才可跳过“提交前当前状态”比较进入幂等复验与 candidate 冻结范围的 publish recovery。
11. 后续 dry-run、commit、幂等复验和自动首发保持既有顺序；任何失败均不得把 scope 回退为地区
   batch manifest 全集。旧 commit state 若没有 `publish_scope`，`retry-publish` 必须明确
   fail closed 并要求走人工审计恢复，不能用空集合调用发布服务后误标成功。
12. candidate bindings 中 research/mapping/authority SHA 以刚生成 commit artifact 的
   `inputs.*.sha256` 为事实来源，并在任何 artifact/candidate/state/ledger 落盘前与 bundle state
   声明逐项核对；bundle 文件被一致替换但 state 未同步时直接拒绝 prepare，不生成“可展示但不可提交”
   的 candidate。
13. `prepare-release` 校验当前 bundle 后，把 research/mapping/authority 原始字节复制到按 SHA 命名
    的候选不可变输入路径，并让 commit artifact 的 `inputs.*.path` 指向这些快照。DB 前重试与
    DB 后幂等恢复都只从 candidate 历史记录和不可变输入复验，不依赖可能被后续 `--bundle` 覆盖的
    region-current 文件；因此已落库 A 在重做 bundle 后仍能按 A 恢复 publish，而新 B 仍因 A 已
    落库被拒绝。
14. commit 不得在取得 batch serial/file lock 前读取 combined、state 或 current bundle 决定候选
    有效性。所有校验移入锁内；未落库候选至少再次核对当前 combined SHA，已落库恢复使用 candidate
    冻结的不可变输入和 SHA，避免锁等待期间读取旧值的 TOCTOU。
15. v1 release manifest 兼容仅限 validator 读取和复验已有证据；rolling release builder 不再接受
    空 candidate SHA，也不得新建 ledger-backed v1 批准。测试历史兼容时使用已冻结 fixture，而非
    调用生产 builder 生成新 v1。
16. 自动首发执行范围必须同时满足“位于 candidate”与冻结
    `disposition=attempt_publish_after_commit`。`block_hidden`、`block_manual_lock`、
    `skip_already_published` 只进入排除审计，不得因 commit 后/重试前 live 状态放宽而被发布；live
    gate 只可在冻结尝试集合上进一步收紧。
17. batch serial/file lock 下沉为 batch 服务共享合同；会重写 combined 或 region-current
    research/mapping/authority/state 的 `--prepare`、`--bundle`，以及 `--prepare-release`、
    `--commit` 必须从文件生成到 state 写入全程使用同一把锁，避免 read-modify-write 丢更新。
    不可变 snapshot 同时要求目标为普通文件、拒绝 symlink，并以独占/原子发布方式避免非合作覆盖。
18. 数据库事务成功后若需要暂时释放锁，写 completion-run 元数据、`commit:{region}` checkpoint、
    publish state/ledger 前必须重新取得同一 batch lock、重新读取最新 state 并合并；publish 的
    state 更新保持在该锁内。DB commit 与二次加锁之间进入的 bundle/prepare-release 必须依据 DB
    artifact 落库证据安全拒绝或完成，其 state 更新不得被旧内存 state 覆盖。
19. rolling release builder 除精确 SHA 外必须接收并加载真实 candidate path，验证普通文件、
    字节 SHA、schema/status、batch/region/executor、artifact SHA、五项输入 bindings、
    expected actions 与冻结 publish scope 均和待签发 release 上下文一致。builder 自身是正式批准
    边界，不能依赖上层 commit 已做过校验；任意伪造 64 位 hex 或错 candidate 文件均不得生成
    manifest/ledger。
20. 新增独立 `batch-execution` lock，正式 commit 从旧候选失效、新候选批准、DB apply/复验到
    checkpoint/inline publish 全程持有；共享 state lock 只在短文件/state 窗口内嵌套，所有路径统一
    按 execution -> state 顺序取锁。`--abandon` 同样先取 execution 再取 state，因此不会在 DB gap
    插入终止；取得锁后若 state 已 abandoned，commit 在批准/DB/publish 前后检查并 fail closed。
21. supersede/approve 账本顺序固定为：原子写新 manifest（尚未批准）-> 幂等追加旧 candidate 的
    `release_superseded` -> 追加新 manifest 的 `release_approved`。这样任一崩溃点最多导致暂时没有
    active 新批准，不会出现旧、新同时可提交；同批 execution lock 防止旧 candidate 在转换中执行。
22. release manifest 崩溃恢复只接受非 symlink 普通文件，且文件名内 SHA 必须等于当前完整字节
    SHA；payload key 集、approved_by/approved_at/decision_reference/executor/region/ledger path/
    bindings 必须全量符合原签发合同。任何改字节导致文件名不匹配时不得补写 `release_approved`。
23. `auto_publish_profiles` 在 PostgreSQL 下必须在每匹马的 `transaction.atomic()` 内按 ID
    `select_for_update()` 后再评估 live gate 与状态迁移；调用方不得在事务外求值带
    `select_for_update()` 的 QuerySet。SQLite/TestCase 绿色不能替代这一事务边界回归。
24. 通用 production apply 的 v2 validator 必须从 release manifest 目录按 region+candidate SHA
    推导并加载真实 candidate，复验普通文件/SHA/schema/status/metadata/artifact bindings/actions，
    以及 state history 和 `release_candidate_prepared`。它必须严格按 ledger 顺序计算 active
    approval：找到 release_approved 后若存在指向该 release/candidate 的后续
    `release_superseded`，所有 direct dry-run/commit 入口都拒绝旧 A。
25. ledger parser 统一严格模式：任何非空 malformed/partial 行均转为业务层 fail-closed 错误，不能
    静默跳过潜在 supersede；append 前先严格验证现有文件，使用单条完整写、flush 与 fsync。尾部破损
    只允许人工审计修复，不由正式 apply/builder 猜测截断。
26. abandon 仅适用于尚未落库的批次。在 execution lock 内同时检查 manifest/state 的 commit/publish
    checkpoint 与 candidate 专属 artifact 的 committed completion-run 证据；任一存在即拒绝
    abandoned 终态，不伪装成已撤回生产写入。
27. 自动发布报告仅在每匹 `transaction.atomic()` 成功退出后增加 published/ID，避免 deferred
    commit failure 同时计为成功和 error；多次 retry 的累计基线优先使用此前
    `cumulative_published_profile_ids`，再合并本次结果。
28. 通用 v2 validator 读取 candidate state 时必须把 `state.stage=abandoned` 或 batch manifest
    `status=abandoned` 视为永久拒绝，复验 manifest schema/internal SHA；因此已批准但 DB 前停止的
    batch 不能再被 standalone direct apply 复活。
29. strict ledger 按事件 schema/version 验证。新 `auto_first_publish` 事件显式标记 v2 并强制
    frozen exclusion 字段；升级前无版本的 legacy 事件允许缺少这些新字段，读取时仅在内存归一为空
    集合，原始 JSONL 不修改。malformed JSON 和已声明 v2 却缺字段仍 fail closed。
30. `batch_execution_window` 对同线程同 batch 可重入。通用 v2 dry-run/commit 必须从 candidate
    validation 到 DB transaction 完整持有该 execution lock；batch wrapper 的嵌套调用复用同一
    lease。这样 A 校验后，B 不能在 A 落库前追加 supersede；锁后若 A 已失效则 DB 零写。
31. 通用 v2 validator 对尚未 committed 的 artifact 复验 candidate 绑定与当前 batch manifest
    实际内部 SHA、当前 combined 文件完整 SHA；manifest 或 combined 重生成后 stale candidate 的
    direct dry-run/commit 均拒绝。只有以 committed completion-run + 精确 artifact path/SHA 确认
    已完整落库时，幂等恢复才改用 candidate 不可变 snapshot，不依赖 region-current 输入。

release candidate 是“待批准的精确施工方案”，不是 release manifest，也不进入现有可信发布批准
校验。正式 commit 仍只接受带独立批准账本事件的 release manifest，因此该拆分不降低既有写入门禁。

### 9. 已审核空胜绩与完整度策略版本（task 5.4 返修）

task 5.4 首次正式写入在 PostgreSQL 事务内 fail closed：61 匹中的 10 匹没有胜绩记录，虽然
`major_wins` 模块已人工批准为空列表，旧完整度判断仍把“没有胜绩记录”解释为“胜绩资料缺失”，
导致首匹无胜绩马严格验收失败并整批回滚。

修复采用窄语义：

1. 有实际获胜或重大胜绩记录时，沿用既有完整判定；
2. 没有胜绩记录时，只有最新非 ignored 的 `major_wins` 候选为 `applied`、审核为
   `approved`、payload 精确为空列表，并有 `applied_by`、`applied_at` 时，才表示“已审核确认
   无胜绩”并满足资料完整度；
3. 没有审核记录，或最新记录为 pending/conflict/rejected 时仍阻断；ignored 新建议继续沿用此前
   已 applied 的有效审核，不放宽未审核资料；
4. 新生成 commit artifact 与 release candidate 都写入
   `p0-horse-full-profile-completeness.v2`。candidate 与正式 v2 release 必须精确匹配当前策略
   版本。历史 v1 artifact 仅允许可信 v1 release 的只读 dry-run 复验，commit 明确拒绝；
5. 手工 ready 复审无胜绩马时，新 `major_wins` 审计继续保存空列表，不能用
   `{"manual_review": true}` 覆盖并自我推翻完整度。

## Risks / Trade-offs

- [页面结构脆弱] -> 解析器按表格标签语义定位而非绝对位置；结构不识别即 fail closed，配 fixture 回归。
- [netkeiba 与 JBIS 字段冲突] -> 同候选两来源字段不一致时记冲突不覆盖；netkeiba 路径只服务有 key 候选。
- [生涯总数口径] -> 总数与逐场数不一致进缺口，不标完整（沿用完整性验收口径）。
- [同名马 payload 污染] -> ID 直取零检索歧义；页面马名比对兜底。

## Migration Plan

1. 实现 client + 解析 + adapter 注册，fixture 测试（正常页、同名马、缺表、改版、总数不符、海外行）。
2. 本地 sqlite 端到端：select → prepare（缓存模拟）→ bundle → commit → 自动首发。
3. 独立 code review 后合并 main。
4. 第二轮生产 fixture 先写 RED：`抹消` 标题、字段级 identity blocker、异常履历行、parser version fingerprint；再最小实现至 GREEN。
5. 独立方案复审、代码复审与本地验证通过后，重新取得精确代码版本的部署/触网授权；部署后保留并 abandon 旧批次，新建日本批次只执行到 prepare 与 xlsx；prepare 成功或异常后立即在 finally 路径恢复并验证 `ALLOW_NETWORK=false` 和 worker，不等待人工复审。
6. 用户人工复审 xlsx 后冻结 bundle/hash；再取得绑定该 bundle/hash、完整子集与自动公开首发范围的精确 commit 授权，最后执行 commit、首发验收与网络开关恢复。
7. task 5.3 先执行 `--bundle` 与 `--prepare-release`，向用户展示 release-candidate SHA、全部
   bindings、预计写入和自动首发范围；取得该精确 candidate SHA 授权后，task 5.4 才生成正式
   release manifest 并执行 commit。
8. task 5.4 首次写入整批回滚后，先修复已审核空胜绩语义并绑定完整度策略版本；本地验证与独立
   review 通过后部署精确版本，再从冻结 bundle 重新生成 candidate 并取得新的精确写入授权。

## Resolved Questions

- 客户端选择策略：有 netkeiba key 走 netkeiba，无 key 保持 JBIS（用户 2026-07-22 决定方向 1）。
