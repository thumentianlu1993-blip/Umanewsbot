# Netkeiba 日本批次发布候选门禁测试

## 范围

本文件补齐在途 `add-netkeiba-horse-client` 变更进入 task 5.3 前的测试合同。规格与设计仍以
`旧规格流程/changes/add-netkeiba-horse-client/` 为准；本轮只修复“人工复审后、生产提交前”缺失的
精确授权门禁，不扩大来源抓取或马匹资料模型。

task 5.4 空胜绩修复追加两项不可回退合同：

1. 只有 applied、approved、payload 精确为空且带 applied 人/时间的 `major_wins` 证据可让真实
   无胜场对象通过完整度；非空 payload、未审核和 conflict 必须阻断。
2. 当前完整度策略必须在 v2 release/candidate 链路强制；缺少新策略字段的历史 v1 artifact
   仍可在可信 v1 release 下只读 dry-run 验证，但 v1 commit 必须在数据库写入前拒绝。
3. 无胜绩档案执行手工 ready 后，最新 `major_wins` 审计的 payload 仍必须精确为空列表，完整度
   复验不得反转。

## 必须先出现的 RED

实现前先在现有 batch command 与 production apply 测试中加入以下用例，并保留因
`--prepare-release`、candidate schema 或精确 SHA 校验尚不存在而失败的真实输出：

1. `prepare-release` 为同一冻结 bundle、mapping 审核时间与生产快照生成字节一致的 commit
   artifact 和 release candidate；第二次执行 SHA 不变。
2. candidate schema 固定为 `p0_horse_production_release_candidate.v1`，状态固定为
   `pending_independent_release_approval`，且不存在 `approved_by`、易变生成时间或
   `release_approved`。
3. candidate 精确绑定 batch manifest、combined candidates、research、mapping、authority、
   commit artifact 与 production snapshot SHA；逐项参数化篡改其中任一文件或声明 SHA 均在写入前
   fail closed。
4. `prepare-release` 前后 `HorseProfile`、`HorseP0Source`、`HorseRaceRecord`、
   `HorseProfileDataCandidate`、`HorseProfileCompletionRun`、`OperationLog`、
   `TaskExecutionLog`、`TermEntry`、`TermAlias` 计数及 profile 审核/隐藏/发布状态完全不变。
5. 自动首发范围只来自 commit artifact 的已复审行：同一日本 batch manifest 中未进入 artifact
   的 blocker profile 不得出现。
6. `update_existing` 记录精确 profile ID；`create_new` 记录确定性 identity key。已发布、
   hidden、manual lock 与普通待发布 profile 分别得到稳定 disposition。
7. 相同 candidate SHA 的 `release_candidate_prepared` 证据事件只记录一次；双线程/双进程并发
   prepare 也只能得到一个 candidate SHA 和一条事件，candidate/state/ledger 不出现半成品组合。
8. `--commit` 缺少、错误或篡改的 `--release-candidate-sha256` 时，在正式 release manifest、
   OperationLog、马匹写入和自动首发前 fail closed。
9. candidate 生成后 profile/mapping/commit artifact/预计动作/自动首发范围任一漂移时，
   `--commit` fail closed，并要求重新 prepare 与授权新 SHA。
10. 正式 release manifest 只在精确 candidate SHA 校验通过后写 `approved_by` 和
    `release_approved`；新清单使用 `p0_horse_production_release_manifest.v2`，bindings 反向包含
    `release_candidate_sha256`。仓库可信与既有 rolling v1 清单仍按旧五项 binding 成功复验。
11. commit 后自动首发只处理 artifact 已复审既有 profile 与本次 completion run 实际创建的
    profile；同地区未复审 blocker 即使已满足其他发布条件也不得被处理。
12. commit 幂等复验及 publish retry 继续使用被冻结的 reviewed scope，不得回退到整个地区
    batch manifest。
13. 首次批准在正式 manifest 写入后、账本追加后、state 写入后和数据库 commit 后分别模拟崩溃；
    相同 candidate SHA 重试必须复用原 `approved_at`、manifest SHA，只存在一条
    `release_approved`，并能继续完成幂等 commit/publish。
14. 已存在正式 manifest 的 candidate 以不同 `approved_by` 重试时 fail closed，不覆盖原批准，
    不生成第二份清单或第二条批准事件。
15. candidate A 已批准但 dry-run/commit 在数据库事务前失败后，重新 prepare 得到 candidate B 并
    取得新 SHA 授权时，A 的 artifact/candidate/manifest 文件和批准事件保持不可变；B 使用独立
    SHA 路径继续，且仅有一条关联 A/B 的 `release_superseded`。若 A 的 completion run 已
    `COMMITTED`，B 必须在任何写入前被拒绝。
16. candidate A 的正式 manifest 已生成但数据库尚未落库时，分别改变目标 profile 的
    `hidden_at`、`review_status` 和 auto-publish manual lock；相同 A SHA 重试必须重新计算 scope，
    在数据库写入前 fail closed。只有确认 A artifact 已完整落库后，幂等恢复才使用冻结 scope 继续
    publish。
17. 构造升级前 `commit:{region}` state（有 artifact/release/verification，但无
    `publish_scope`）并执行 retry；命令必须 fail closed，`auto_publish_profiles` 不被调用，
    `publish:{region}` 不完成，也不追加成功账本事件。
18. bundle state 冻结后分别一致替换 research、mapping、authority 文件及其内部自校验字段，但不
    更新 bundle 声明 SHA；`prepare-release` 必须逐项在任何 commit artifact、candidate、state 或
    `release_candidate_prepared` 事件落盘前拒绝。正常候选 bindings 必须等于 artifact
    `inputs.*.sha256`。
19. candidate A 准备时生成按 SHA 命名、字节一致且不可覆盖的 research/mapping/authority 输入
    快照，artifact `inputs.*.path` 和 state 历史均指向快照。A artifact 完整落库后模拟 commit
    checkpoint/publish 前崩溃，再重做同地区 bundle 覆盖 current 文件；A 仍能从不可变输入恢复
    publish，新 candidate B 仍在候选证据写入前被拒绝。
20. 用两个执行线程控制锁时序：commit 先在 serial/file lock 外等待，另一路径更新 combined 后释放
    锁；commit 必须读取锁内新 SHA 并在正式批准/数据库写入前阻断。测试同时断言 commit 的
    state、candidate 和 bundle 有效性读取不再依赖锁外快照。
21. 直接调用 rolling release builder 且不提供 candidate SHA 时必须在 manifest/ledger 写入前
    失败；历史 v1 fixture 仍可通过 production validator，证明兼容入口只读而不能新建批准。
22. candidate 同时包含 `attempt_publish_after_commit`、`block_hidden`、`block_manual_lock` 和
    `skip_already_published` 的既有 profile；即使后三者在 inline publish/retry 前解除隐藏/锁或改为
    待发布，传给 `auto_publish_profiles` 的 ID 仍只有冻结 attempt 集合，报告保留三个排除项。
23. 用线程和事件分别让 `prepare`、`bundle` 与 `prepare-release`/`commit` 竞争；断言四条路径使用
    同一 lock，state 中 bundle current pointer、candidate current/history 和 ledger 均不丢更新。
    预置同名 symlink 或非普通 snapshot 目标时必须 fail closed，不能读写链接目标。
24. 在 DB commit 成功、首次 serial lock 释放后暂停 commit，让 bundle writer 更新 state，再恢复
    commit；commit 必须二次加锁、重新读取并合并，最终同时保留新 bundle pointer、candidate
    current/history、completion run 参数、commit checkpoint 和 publish state/ledger，不得用旧
    BatchRunState 覆盖。
25. 直接调用 builder，分别传任意 64 位 hex、不存在 candidate、SHA 不符、symlink/nonregular、
    错 schema/status/batch/region/executor、错 artifact/input binding、篡改 expected actions 或
    publish scope；全部必须在 manifest/ledger 零写时失败。只有真实 candidate 文件与完整上下文
    一致时才生成 v2 release。
26. 用故障注入让 B 替代 A 时分别崩溃于 B manifest rename 后、A superseded 追加后、B approved
    追加后；每次恢复都不得出现 A/B 同时可执行，ledger 事件唯一且顺序为 superseded 在 approved B
    之前。B 执行期间并发重试 A 必须被 execution lock 阻塞，随后因 superseded 拒绝。
27. A 在首次 state lock 释放后进入 DB apply 时，并发启动 B commit 与 abandon；二者必须等待同一
    execution lock。A 完成后 B 因 A 已落库拒绝；若 abandon 先取得 execution lock并成功，则随后
    A 在 approval、DB 和 publish 各边界均拒绝，不产生终止后的写入或公开。
28. release manifest rename 后、ledger 前故障，分别篡改 approved_at、decision_reference、
    approvals_ledger_path、额外字段或原文件 bytes，并测试 symlink/nonregular；恢复必须因普通文件、
    文件名完整 SHA 或精确 payload 合同不符而拒绝，不为新 SHA 补批准。
29. PostgreSQL 语义单测断言传入发布服务的 QuerySet 不在事务外使用 `select_for_update()`；
    每个 profile ID 在自己的 atomic 内重新 `select_for_update().get()`、重验 gate、状态写和
    OperationLog 同事务。覆盖 inline 与 retry，并保留单马失败隔离。
30. 在 A release_approved 后追加 A->B release_superseded，用通用
    `dry_run_reviewed_p0_completion_artifact` 和 `commit_reviewed_p0_completion_artifact` 直接传 A；
    二者必须加载 A 的真实 candidate/state/prepared evidence，按 ledger 顺序拒绝且数据库零写。
    未 supersede 的真实 active v2 和历史 v1 fixture 仍通过。
31. 分别构造 committed completion run 但删除 state checkpoint、仅 commit checkpoint、仅 publish
    checkpoint、manifest status=committed；`--abandon` 在 execution lock 内全部拒绝，state/manifest
    字节不变。纯 pending 未落库批次仍可 abandon。
32. 在 prepared、approved、superseded 之前或之后插入 malformed JSON、中间 partial 和尾部 partial；
    production validator、builder、supersede/approve append 全部报业务错误且不新增事件。正常 append
    mock/spy 验证完整单条写、flush/fsync。
33. 模拟 `transaction.atomic()` 退出时抛 deferred commit error；该 profile 只进入 errors，不出现在
    published 计数/ID。连续三次 retry 每次成功不同 ID，第三次 cumulative 集合仍包含前三轮全部 ID。
34. v2 release_approved 后、DB commit 前成功 abandon，分别保留 state abandoned/仅 manifest
    abandoned，再直接调用 production dry-run 与 commit；共同 validator 必须校验 batch manifest
    schema/internal SHA/status并在数据库事务前拒绝，全部业务表计数不变。
35. 加载真实升级前 `auto_first_publish` fixture（无 event schema、无
    frozen_exclusions/counts）仍可完成 v1/rolling ledger 复验，返回的内存事件归一为空集合且原文件
    bytes 不变；新 writer 事件带 v2 schema，删除任一冻结字段后 strict parser 拒绝。
36. 受控线程让 standalone candidate A commit 在 v2 validation 后暂停，candidate B 尝试 batch
    commit/supersede；B 必须被同一 execution lock 阻塞直到 A 完成。反向时序中 B 先激活后，A
    在锁内重验 superseded 并保持所有业务表零写。
37. candidate 批准后、DB 前分别合法重写 batch manifest（同步内部 SHA）和 combined bytes；
    standalone dry-run/commit 必须比较当前实际 SHA 并在 DB 前拒绝，candidate/release/ledger
    bytes 不变。
38. candidate artifact 已完整 COMMITTED 后，重建 current batch/combined 并删除 commit
    checkpoint；standalone v2 幂等 dry-run/commit 仍从不可变 snapshot 与 committed-run 证据恢复，
    planned writes 为 0。
39. 首次 commit + publish completed 后，分别人工把已发布对象降回可发布状态、清除首次冻结的
    manual-lock gate，再以相同 candidate 普通重复 commit；两者都必须复用冻结 publish
    checkpoint/report，不调用发布服务、不改变当前公开状态、不新增 ledger 或 state publish
    证据。首次 publish 失败或 commit 后尚未 publish 时，普通重复 commit 必须在 DB/publish 重跑前
    fail closed 并提示显式 `--retry-publish`。

## GREEN 与回归门禁

实现完成后至少运行：

- 发布候选与 batch command focused tests；
- `stable.test_p0_horse_production_apply`；
- P0 completion 直接相关测试套件；
- `DB_ENGINE=sqlite python manage.py check`；
- `DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run`；
- 当前变更严格校验与全量规格校验；
- `git diff --check`。

所有 focused 测试必须在禁网环境运行。本轮本地实现与验证不得访问生产、不得写生产马匹数据、
不得生成带正式批准语义的生产 release manifest。

## 本轮 TDD 证据

RED（实现前）：

- 命令：
  `python manage.py test stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_prepare_release_is_deterministic_read_only_and_unapproved -v 2`
- 结果：失败；管理命令尚不识别 `--prepare-release`。
- 发布范围用例同时因 `_build_auto_first_publish_scope` 尚不存在而导入失败。

GREEN（实现后）：

- 候选确定性、零业务写、精确 SHA、七项 binding 漂移、四类 disposition、同批 blocker
  排除、v1/v2 release manifest 兼容和冻结范围重试均已覆盖。
- SQLite 相关模块：
  `python manage.py test stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply -v 1`
- 结果：162 项通过，0 失败；全程未启用网络，未访问或写入生产。

## 独立审查 P1 修复证据（task 4.10a）

RED：

- 运行候选 A/B 故障注入后，旧实现因缺少
  `release_candidate:{region}:{candidate_sha}` 历史记录而报 `KeyError`，且三类证据仍共用地区固定路径。
- 在 candidate A 已生成正式 manifest、但故障注入阻断数据库提交后，分别修改目标 profile 的
  hidden、review status 与 manual lock；屏蔽 production apply 的下游快照保护后，旧实现没有在
  batch commit 服务层重算 candidate/scope，继续调用了数据库 commit。

GREEN：

- commit artifact、release candidate、v2 release manifest 均使用完整 SHA 专属不可变路径；
  batch state 同时保留当前指针与 candidate SHA 历史记录。
- A 已批准但未落库时，重新 bundle/prepare 的 B 可生成独立证据并提交；A 三份文件字节不变，
  `release_superseded` 仅一条。A 被 supersede 后不可再次提交。
- 是否完整落库只依据 `HorseProfileCompletionRun.status=committed`、精确 `artifact_path` 与
  summary 中 artifact SHA；测试删除 candidate state 指针和历史后，仍能识别 A 已落库并拒绝 B，
  且不追加 candidate 账本证据。
- A manifest 存在但无完整落库证据时，每次重试仍重算 artifact、expected actions 与当前发布范围；
  hidden、review status、manual lock 任一漂移均在 dry-run/数据库 commit 前 fail closed。
- SQLite 相关模块最终回归：
  `python manage.py test stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply -v 1`
  共 172 项通过，0 失败。

## 第二轮独立审查修复证据（task 4.10b）

RED：

- 构造升级前 commit state，删除 `commit:japan.publish_scope` 并恢复为待 retry 状态。旧实现把
  `{}` 传给 `auto_publish_profiles`，测试中的 mock 返回值随后进入 state 写入，证明发布服务已被
  错误调用且路径会把空目标误标为成功。
- 分别对 research、mapping、authority 做保持内部引用一致的文件替换，但不更新 batch state
  声明。旧实现对 research/mapping 未报错并生成候选；authority 只被下游参数 SHA 偶然阻断，
  没有统一执行 artifact inputs 对 bundle 声明的三项前置校验。

GREEN：

- `retry-publish` 要求 commit state 明确包含字典类型 `publish_scope`；缺失时提示人工审计恢复，
  在 `auto_publish_profiles` 前 fail closed，不完成 publish stage，不追加成功账本事件，也不回退
  到地区 batch manifest。
- `prepare-release` 先以实际 authority 文件 SHA 只读生成 artifact，再从
  `artifact.inputs.research_v3/authority_manifest/profile_mapping_decisions.sha256` 构造 candidate
  bindings；三项逐一与 bundle state 声明比较，任一不符均在 artifact/candidate/state/ledger
  证据落盘前阻断。
- 参数化覆盖 research、mapping、authority 替换；失败前后 state 与 ledger 字节不变，候选证据
  文件集合不变。正常候选另断言三项 bindings 与 artifact inputs 完全一致。
- SQLite 相关模块最终回归：
  `python manage.py test stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply -v 1`
  共 179 项通过，0 失败。

## 第三轮独立审查修复证据（task 4.10c）

RED：

- candidate A 的 history 不存在 `snapshot_bundle`，commit artifact 的 `inputs.*.path` 仍指向会被后续
  `--bundle` 覆盖的 region-current 文件，已落库 A 无法在重做 bundle 后恢复。
- 受控 serial-window 时序中，在 commit 进入锁时更新 combined；旧实现仍调用正式 release builder，
  证明 combined SHA、state 与 current bundle 的候选有效性读取发生在锁外并沿用了旧值。

GREEN：

- `prepare-release` 完成 current bundle 三项实际 SHA 校验后，原字节原子复制到
  `approval/input_snapshots/` 下按完整 SHA 命名的不可变 research、mapping、authority 文件；
  已存在同 SHA 文件只接受字节完全一致，不覆盖。
- 正式 commit artifact 的 `inputs.*.path` 指向上述快照；candidate history 的
  `snapshot_bundle` 同时记录三项路径和 SHA。DB 前重算与 release builder 使用 candidate snapshot
  bundle，不再使用 region-current 文件。
- 已 COMMITTED 的恢复分支以精确 completion run/artifact SHA 确认证据后，使用冻结 combined binding
  与不可变输入；测试删除 commit checkpoint、模拟 publish 前崩溃并重做 bundle 后，A 仍完成幂等
  commit/publish，随后 B 仍在候选证据前被拒绝。
- commit 在进入 `_serial_window` 前不再读取 state、combined 或 current bundle。双线程事件控制测试
  让 commit 等待、另一执行路径更新 combined 后再放行；commit 读取锁内新 SHA，并在 release builder
  与数据库写入前以 stale candidate 阻断。
- SQLite 相关模块最终回归：
  `python manage.py test stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply -v 1`
  共 182 项通过，0 失败。

## 第四轮独立审查修复证据（task 4.10d）

RED（第四轮审查复现）：

- rolling release builder 的 candidate SHA 为空时会选择 v1 schema、写地区固定 manifest，并追加
  `release_approved`，可绕过候选授权。
- `_run_region_publish` 把 candidate 中所有既有 profile 重新交给 live gate；冻结为
  `block_hidden`、`block_manual_lock` 或 `skip_already_published` 的对象在状态后来放宽时会被发布。
- `--prepare`、`--bundle` 未持有 commit 服务私有的 serial lock，产物生成与 state 更新可和
  `prepare-release`、`commit` 交错；snapshot 又会跟随 symlink，并以 `os.replace` 覆盖目标。

GREEN：

- rolling builder 现在要求精确 64 位小写十六进制 candidate SHA，且只生成 v2；缺失或非法 SHA
  在读取 artifact、创建 manifest 或追加 ledger 前失败。历史 v1 仅由冻结 fixture 走 validator。
- 发布执行只把冻结 disposition 为 `attempt_publish_after_commit` 的既有 profile 和本次新建目标
  交给 `auto_publish_profiles`；其余 disposition 写入 `frozen_exclusions` 与计数审计。inline 与
  retry 两条路径均覆盖“隐藏/人工锁后来解除仍不发布”，live gate 只能收紧尝试集合。
- serial lock 下沉到 batch 服务；management command 的 `prepare`、`bundle` 从产物生成到 state
  写入全程持锁，和 `prepare-release`、`commit` 共用同一锁且无嵌套。受控线程测试在两条生成钩子
  内争锁，均 fail closed。
- snapshot 目标使用 `lstat` 拒绝 symlink 与非普通文件；临时文件以独占创建、`fsync` 后通过
  `os.link` 原子无覆盖发布，竞争目标只允许同字节普通文件。
- focused SQLite：
  `python manage.py test stable.test_p0_horse_completion_batch.P0HorseBatchApprovalBundleTests stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests stable.test_p0_horse_completion_batch.P0HorseBatchAutoPublishTests --noinput`
  共 95 项通过，0 失败。
- SQLite 相关模块最终回归：
  `python manage.py test stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply --noinput`
  共 189 项通过，0 失败；全程禁网，未访问或写入生产。

## 第五轮独立审查修复证据（task 4.10e）

RED：

- 在 artifact DB transaction 与幂等复验后暂停 commit，让另一线程取得共享 batch lock、更新
  `bundle:japan` state，再恢复 commit。旧实现继续使用第一次锁内读取的 `state` 写 commit/publish
  checkpoint，会覆盖并发 bundle 字段。
- direct rolling builder 使用任意格式正确的 64 位 hex、但没有对应 candidate 普通文件时，旧批准
  边界仍只检查 SHA 格式并继续构造 v2 manifest；错 candidate、内容篡改与 symlink 也没有 builder
  自身的完整复验。

GREEN：

- pre-DB 的 candidate/release 校验与证据写入仍在第一段共享锁内；dry-run、数据库事务和幂等复验
  在文件锁外完成，避免数据库行锁跨 file lock。随后 commit 二次取得共享锁，重新读取最新
  `BatchRunState`，合并 completion-run 参数、verification 与 `commit:{region}` checkpoint。
- 自动首发的数据库状态转换在文件锁外完成；publish report、state/error、成功 ledger 与
  completion-run summary 在新的共享锁窗口内重读并合并。retry 路径不再用旧内存 state 二次覆盖。
- 受控线程测试在第二次 dry-run（即 DB commit 后的幂等复验）暂停主流程，让并发 writer 更新
  `bundle:japan.concurrent_writer_marker`；恢复后 marker、commit checkpoint 与 publish checkpoint
  三者均保留。
- rolling builder 新增真实 `release_candidate_path` 门禁：目标必须是 batch approval 目录下按
  region+SHA 命名的非 symlink 普通文件；复验文件字节 SHA、candidate schema/status、
  batch/region/executor、artifact prepared time、七项 bindings、expected actions、publish scope，
  并要求 candidate history 与 `release_candidate_prepared` 账本证据同时匹配。
- 覆盖任意 hex 指向真实但不同 SHA 文件、伪造 expected actions 且同步伪造 state/准备事件、以及
  symlink candidate；三类均在 manifest/`release_approved` 写入前 fail closed，ledger 与 manifest
  集合不变。同 candidate 的既有正式 manifest 恢复路径继续通过完整 candidate 复验后复用。
- focused SQLite：
  `python manage.py test stable.test_p0_horse_completion_batch.P0HorseBatchApprovalBundleTests stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_post_commit_checkpoint_merges_concurrent_bundle_state stable.test_p0_horse_completion_batch.P0HorseBatchAutoPublishTests --noinput`
  共 64 项通过，0 失败。
- SQLite 相关模块最终回归：
  `python manage.py test stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply --noinput`
  共 192 项通过，0 失败；全程禁网，未访问或写入生产。

## 第六轮独立审查修复证据（task 4.10f）

RED：

- 第五轮只在 DB 后重新取得 state lock，同批 candidate B 或 abandon 可在 candidate A 的 DB gap
  进入；B 可先 supersede A，随后 A 仍继续 DB/checkpoint/publish。
- 旧 supersede 事件在 builder 已追加 B `release_approved` 后才由 commit 补写；任一中断可留下 A/B
  同时具有 approved 证据。
- release 恢复按 payload 中 candidate SHA 扫描文件，只比较部分字段；symlink、目录、文件名 SHA
  与 bytes 不一致、`approved_at`/decision/ledger path/额外 key 篡改均可能进入补批准路径。
- `auto_publish_profiles` 在调用方事务外迭代 `select_for_update()` QuerySet；PostgreSQL autocommit
  会在 locking read 求值时失败，且 live gate 不是在每匹行锁内重验。

GREEN：

- batch 服务新增按批次独立、阻塞式 `execution-window.lock`。正式 commit 与 retry 从批准状态转换、
  DB apply/幂等复验、checkpoint 到 inline publish 全程持有 execution lock；state lock 只按
  execution -> state 顺序嵌套。受控双线程证明 candidate B 在 A 释放前不会进入内部 commit。
- `--abandon` 同样按 execution -> state 取锁。受控线程证明 abandon 等待正在执行的 commit；
  已成功 abandon 的批次在 commit 入口即 fail closed，DB apply 与自动发布 mock 均未调用。commit
  在首次 state、DB 后 checkpoint state 与 publish boundary 三处复验 abandoned。
- builder 在写新 manifest 前先把确定的 path/SHA/payload 写入 candidate history 作为恢复锚点；
  ledger 状态转换固定为 manifest 落盘 -> 幂等 `release_superseded` -> 唯一
  `release_approved`。superseded 列表由 commit 传入 builder，原 commit 后置循环已删除。
- 故障注入在 B manifest 已写且 A superseded 后阻断 B approval；此时 B 无 approved 事件。重试先
  复用同 SHA manifest、确认 supersede 唯一，再追加 B 唯一 approval，账本顺序严格正确。
- v2 release 恢复要求非 symlink 普通文件，文件名中的完整 SHA 等于当前 bytes；payload key 集、
  schema、approved_by、带时区 approved_at、decision_reference、executor、region、ledger path 与
  bindings 全量精确匹配。参数化篡改 approved_at、decision、ledger path、额外 key，以及 symlink/
  目录目标均不修改 ledger、不补新 SHA 批准。
- 发布服务只接受 profile ID、model 列表或非 locking QuerySet；外部 locking QuerySet 在求值前
  明确拒绝。每个 ID 在独立 `transaction.atomic()` 内执行
  `select_for_update().get()`，随后重验 already-published/live gate 并在同事务写状态与
  OperationLog；单马异常仍隔离到 report。
- 第六轮 focused：
  `python manage.py test stable.test_horse_profile_publish.AutoPublishProfilesTests.test_locking_read_and_gate_run_inside_per_profile_atomic stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_execution_lock_serializes_two_same_batch_commits stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_abandon_waits_for_execution_window_then_stops_batch stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_supersede_recovery_orders_old_invalidation_before_new_approval stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_release_recovery_rejects_tampered_bytes_without_reapproval stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_release_recovery_rejects_symlink_and_nonregular_file --noinput`
  共 6 项通过，0 失败。
- SQLite 相关模块最终回归：
  `python manage.py test stable.test_horse_profile_publish stable.test_p0_horse_completion_batch stable.test_p0_horse_production_apply --noinput`
  共 229 项通过，0 失败；全程禁网，未访问或写入生产。

## 第七轮独立审查修复证据（task 4.10g）

RED：

- 通用 production apply 对 v2 release 只检查 candidate SHA binding 与
  `release_approved`，不加载真实 candidate/state/prepared evidence，也会跳过坏 ledger 行；
  caller 可直接复用已被 supersede 的旧 release。
- `--abandon` 在 execution/state lock 内仍会把 committed manifest、commit/publish checkpoint，
  或已有 committed completion run 但 checkpoint 被删除的批次标为 abandoned。
- validator、builder 与 append 各自解析 ledger；malformed/partial 行存在继续、裸
  `ValueError` 或追加到破损尾部的分歧，append 也没有 flush/fsync durability。
- 自动发布在 `transaction.atomic()` context 成功退出前增加 published 计数；第三次 retry 只继承
  上一次 `published_profile_ids`，丢失更早累计 ID。

GREEN：

- production apply 的 v2 validator 从 release 目录按 region+candidate SHA 加载真实普通 candidate，
  复验字节 SHA、schema/status、batch/region/executor、artifact prepared time、七项 bindings、
  expected actions、publish scope 结构、candidate history 与 artifact SHA；按 ledger 顺序要求
  prepared 先于 approved，并拒绝其后匹配旧 release/candidate 的 superseded。真实 active v2
  direct dry-run 继续通过，superseded 后 direct dry-run/commit 均在数据库事务前拒绝；历史 v1
  路径保持原兼容合同。
- `--abandon` 在 execution -> state lock 内、修改任何文件前拒绝 committed manifest、
  commit/publish artifact 或 completed-stage checkpoint，并从 candidate history 反查
  `HorseProfileCompletionRun(status=committed)` 与 artifact SHA；纯 pending 仍可 abandon。
- 新增共享 strict approvals ledger parser，覆盖 batch approval、region module approval、
  candidate prepared、release approved/superseded 与 auto publish 事件的业务必填字段和 SHA；
  validator、builder、supersede/approve 和 batch validation 全部复用。任一非空 malformed/partial
  行均报 `P0HorseBatchError`/`P0ReviewedArtifactError`，append 前先完整复验旧 ledger，单次写完整
  JSONL 行后 flush/fsync，破损尾保持原字节等待人工审计。
- 自动发布只在每匹 atomic 成功退出后合并 skipped/blocked/published 报告；deferred commit failure
  只进入 errors。publish checkpoint 优先继承既有
  `cumulative_published_profile_ids`，三轮成功后保留全部历史 ID。
- 第七轮 focused：
  `python manage.py test stable.test_horse_profile_publish.AutoPublishProfilesTests.test_atomic_exit_failure_is_counted_only_as_error stable.test_p0_horse_production_apply.P0HorseProductionApplyTests.test_release_gate_rejects_v2_without_real_candidate_and_missing_binding stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_apply_rejects_v2_release_after_supersede stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_abandon_rejects_committed_manifest_without_mutation stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_abandon_rejects_commit_or_publish_checkpoint_without_mutation stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_abandon_rejects_committed_candidate_run_without_checkpoint stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_ledger_append_rejects_malformed_tail_without_writing stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_ledger_append_flushes_and_fsyncs_complete_line stable.test_p0_horse_completion_batch.P0HorseBatchAutoPublishTests.test_third_publish_attempt_preserves_all_cumulative_ids --noinput`
  共 9 项通过，0 失败。
- SQLite 相关模块最终回归：
  `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test stable.test_horse_profile_publish stable.test_p0_horse_production_apply stable.test_p0_horse_completion_batch --noinput`
  共 243 项通过，0 失败；全程禁网，未访问或写入生产。

## 第八轮独立审查修复证据（task 4.10h）

RED：

- v2 production apply 虽加载真实 candidate 与 state history，但未检查 `state.stage` 或 batch
  manifest `status`；release 已批准、DB 前成功 abandon 后，standalone dry-run/commit 仍可继续。
- 第七轮 strict parser 把新冻结排除字段直接设为所有 `auto_first_publish` 事件必填，导致升级前无
  event schema、缺少 `frozen_exclusions`/`frozen_exclusion_counts` 的合法历史账本无法复验。

GREEN：

- v2 共同 validator 读取 batch manifest 普通文件后复验
  `p0-horse-completion-batch.v1` schema、内部 `batch_sha256`、batch ID 与合法
  `approved|committed` status；manifest 或 `BatchRunState.stage` 任一为 abandoned 都在数据库事务前
  fail closed，state batch ID 不一致也拒绝。
- 测试分别保留 state-only abandoned 与 manifest-only abandoned，直接调用 production dry-run 和
  commit；`HorseProfile`、candidate、race record、completion run 与 OperationLog 计数全部不变。
  另参数化篡改 batch schema/internal SHA，direct validator 均拒绝。
- 新 writer 的 `auto_first_publish` 事件携带
  `event_schema=p0_horse_auto_first_publish.v2`，v2 强制
  `frozen_exclusions` 与 `frozen_exclusion_counts` 且校验集合类型；删除字段继续以 partial 业务错误
  fail closed。
- 无 event schema 的 legacy 事件继续校验旧公共字段；缺少冻结字段时仅对返回的内存副本补
  `[]`/`{}`，已有合法冻结内容原样保留，JSONL 原始 bytes 不改。真实 legacy fixture 与动态
  rolling v1 `release_approved` 共存时，production dry-run 复验通过。
- 第八轮 focused：
  `python manage.py test stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_apply_rejects_state_or_manifest_abandoned_without_db_writes stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_apply_validates_batch_manifest_schema_and_internal_sha stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_legacy_auto_publish_ledger_is_normalized_without_rewrite stable.test_p0_horse_production_apply.P0HorseProductionApplyTests.test_rolling_v1_accepts_legacy_auto_publish_fixture --noinput`
  共 4 项通过，0 失败。
- SQLite 相关模块最终回归：
  `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test stable.test_horse_profile_publish stable.test_p0_horse_production_apply stable.test_p0_horse_completion_batch --noinput`
  共 252 项通过，0 失败；全程禁网，未访问或写入生产。

## 第九轮独立审查修复证据（task 4.10i）

RED：

- standalone direct v2 在共同 validator 返回后未持有 batch execution lock，另一线程可在数据库事务
  前激活新 candidate 并追加 supersede；旧 candidate 随后仍可能落库。
- v2 validator 只校验 candidate 中的 SHA 字段格式和不可变 snapshot，没有在 artifact 尚未落库时
  比较 current `batch_manifest.json` 的内部 SHA 与
  `artifact/combined_candidates.jsonl` 的真实字节 SHA。
- 为 schema 路由直接增加一次 release manifest 预读会破坏既有“每个 JSON 输入只读一次”的
  TOCTOU 防护测试。

GREEN：

- `batch_execution_window` 以规范化 lock path 维护线程本地 lease 深度；同线程同 batch 嵌套直接
  复用，其他线程仍由 `flock` 阻塞。generic v2 dry-run/commit 读取并冻结 release manifest 一次，
  随后在 execution lock 内完成 artifact、candidate/state/ledger validation；commit 持锁直至
  `transaction.atomic()` 完整退出。锁顺序保持 execution -> state。
- 双线程正向时序让 direct A 在 validation 后、数据库事务前暂停，B 通过真实 batch commit 外层
  入口尝试 supersede，确认 B 一直阻塞至 A 退出；反向时序先由 B 激活并 supersede，A 等锁后在
  validator 内拒绝，`HorseProfileCompletionRun` 零新增。
- v2 validator 仅在找不到 `status=COMMITTED`、精确 `artifact_path` 且 parameters 中 SHA 相同的
  completion run 时，比较 current batch manifest 的 `batch_sha256` 与 candidate binding，并从普通
  非 symlink combined 文件的真实 bytes 计算 SHA。manifest drift 的 dry-run 与 combined drift 的
  commit 均在数据库前拒绝。
- exact committed-run 存在时，重复 dry-run/commit 继续使用 candidate 专属 artifact 与输入
  snapshot；current manifest/combined 后续合法变化不影响恢复，planned/database writes 均为 0。
- 第九轮 focused：
  `python manage.py test stable.test_p0_horse_production_apply.P0HorseProductionApplyTests.test_json_inputs_are_read_once_and_symlinks_are_rejected stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_v2_uncommitted_rejects_current_manifest_and_combined_drift stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_v2_committed_recovery_ignores_current_input_drift stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_v2_commit_holds_reentrant_execution_lock_after_validation stable.test_p0_horse_completion_batch.P0HorseBatchCommandPipelineTests.test_direct_v2_commit_revalidates_supersede_after_waiting_for_lock --noinput`
  共 5 项通过，0 失败。
- SQLite 相关模块最终回归：
  `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test stable.test_horse_profile_publish stable.test_p0_horse_production_apply stable.test_p0_horse_completion_batch --noinput`
  共 260 项通过，0 失败；全程禁网，未访问或写入生产。

## task 4.11 最终验证与基线

- 相关集合由主代理再次执行：`260/260` 通过。
- `python manage.py check`：无问题；`makemigrations --check --dry-run`：无漂移。
- `旧规格流程 validate add-netkeiba-horse-client --strict` 与 `旧规格流程 validate --all`：
  `37/37` 通过；`git diff --check` 通过。
- 使用相同 SQLite、Celery eager/memory backend、禁网环境对 detached
  `21610ae8` 基线与当前工作区分别运行完整 `stable`：
  - 基线：`2748 tests / 21 failures / 67 errors / 57 skipped`；
  - 当前：`2836 tests / 21 failures / 67 errors / 57 skipped`。
- 本轮新增 `88` 项测试，failure/error/skipped 增量均为 `0`。既有失败集中于历史 runner 的
  macOS 临时路径/canonical root、实时赛果时钟和旧页面/环境契约，未落入本轮修改模块。
- 第十轮 full-diff review 新发现的 2 个 P1 已由 task 4.10i 通过 RED→GREEN 修复。第十一轮对
  最终完整差异执行原生只读 review，结论 `APPROVED`，无 P0/P1/P2 actionable finding；session
  `019f901d-7b9f-77e3-96e0-792546d3eb4f`，审查前后 fingerprint
  `60cf62da1514f00fce451c89aa39b46146d20a4ef5245bdc84651a037559e164` 一致。

## 2026-07-24 最新主线集成验证

- 受审未提交差异 fingerprint
  `15f8c3b80b0ddd0a6715dfbee0c17ba8a0ede59bac8ad6b22c8bdb540f1fbbbe`
  提交为 `ffa12214`，再合并 `origin/main@97dd2350a193c74d5063bf7432a283e4d47f6d0a`，
  形成集成提交 `8e3716bc`。
- 集成及 4.10j 返修后 P0 相关三模块 `263/263`；主线新闻正文边界与赛事系列身份相邻模块
  `90/90`（1 skip）。
- Django check 无问题，`makemigrations --check --dry-run` 无漂移，旧规格流程 strict/all
  `37/37`，`git diff --check` 通过。
- 使用相同 SQLite、Celery eager/memory backend、禁网环境完整运行 stable：
  - `origin/main@97dd2350`：`2784 tests / 21 failures / 67 errors / 59 skipped`；
  - 集成返修工作区：`2882 tests / 21 failures / 67 errors / 59 skipped`。
- 集成相对最新主线新增 98 项测试，failure/error/skipped 增量均为 0。临时 detached baseline
  worktree 已移除并 prune。

## 最新主线集成审查返修证据（task 4.10j）

RED：

- 相同 candidate 在 `publish:<region>` 已进入 completed stages 后，普通重复 commit 仍无条件调用
  `_run_region_publish`。人工把首次发布对象降回 ready 后会再次进入发布；首次冻结为
  `block_manual_lock` 的对象在清除 lock 后虽不扩大冻结 scope，但仍重复调用发布服务并重写
  publish checkpoint/ledger。
- 首次 publish 记录 errors、commit stage 已完成时，普通重复 commit 会再次运行 DB 幂等 apply 和
  publish；显式 `--retry-publish` 不再是唯一恢复入口。
- 新增 3 项测试在旧实现上为 2 error + 1 failure，明确观测到发布 mock 被调用及失败 publish 被
  普通 commit 恢复。

GREEN：

- 同 candidate 且 commit stage 已完成时，普通 commit 在 execution -> state lock 内读取 publish
  stage。已 completed 必须存在字段完整、`errors=[]` 的冻结 checkpoint，后续 DB 幂等复验完成后
  直接返回该 report，完全跳过 `_run_region_publish`。
- publish stage 缺失、未 completed 或失败时，普通重复 commit 在 artifact/DB/publish 重跑前以
  领域错误拒绝并明确提示 `--retry-publish`；显式 retry 入口及既有成功后拒绝 retry 的合同不变。
- 人工降级与 manual-lock 放宽测试均断言发布 mock 零调用、profile 当前 review status 不变、
  `publish:japan` report 不变、completed stage 唯一、ledger bytes 不变。失败 publish 测试断言
  state/ledger 不变且发布 mock 零调用。
- focused 3 项与完整 `P0HorseBatchAutoPublishTests` 72 项通过；P0 相关三模块最终为
  `263/263`。全程使用 SQLite/Celery eager 禁网测试环境，未访问生产。

## fresh review 返修证据（task 4.10k）

RED：

- `prepare` 只持有 state serial lock，正式 commit 可在 prepare service 尚未退出时取得 execution
  lock 并读取同批次半更新证据；双线程测试确认 commit 提前进入。
- completed commit 普通重放仍调用两次 production dry-run；虽然 apply 幂等，completion run、
  source、audit、task log 与业务表的零写合同未由入口结构保证。
- 删除或篡改该 batch/region/artifact 的 v2 `auto_first_publish` 成功账本事件后，旧实现仍复用
  publish checkpoint，不能证明冻结报告来自成功发布。

GREEN：

- `prepare` 的完整 service、manifest reload、review workbook 与 summary 窗口先取得同 batch
  execution lock，再取得 state serial lock；双线程时 commit 在 prepare 退出前保持阻塞。
- completed 重放在 execution -> state lock 内、任何 dry-run/DB apply/publish 前，复验普通文件与
  SHA、candidate/commit/publish/release bindings、零 remaining verification、精确 committed
  completion run，以及唯一匹配的 prepared/approved/v2 auto publish ledger。
- 重放成功直接返回冻结 commit/publish 结果；测试断言 production dry-run、apply、publish 零调用，
  completion run/source/audit/task log/业务表计数、run/source 内容、state 与 ledger bytes 全部不变。
- 缺失 publish ledger 或发布计数不匹配均要求 manual audit，且 state、ledger、数据库与上述调用
  全部零写。
- focused 3 项通过；SQLite/Celery eager 禁网的
  `stable.test_horse_profile_publish + stable.test_p0_horse_production_apply +
  stable.test_p0_horse_completion_batch` 为 `266/266`，未访问生产。

## 第二轮 fresh review 返修证据（task 4.10l）

RED：

- `prepare-release` 的 command 入口没有 execution lock，public service 也只取得 state serial
  lock。direct service caller 可在同 batch commit 的 DB 窗口内进入 candidate 生成路径。
- abandon 已更新 state/manifest、但仍持 execution lock 时，direct prepare-release 会提前读取终态
  并返回，而不是等待完整 execution window 退出。

GREEN：

- public `prepare_p0_horse_batch_release_candidate` 先取得同 batch execution lock，再调用 locked
  helper 进入既有 state serial lock；command 和 direct caller 使用同一边界。
- helper 在两层锁内重新加载 manifest/state；manifest committed 或 manifest/state abandoned 时，
  在 candidate/state/ledger 写入前 fail closed。
- commit DB-window 与 abandon post-body 双线程测试均确认 prepare-release 等待 A 完整退出；随后
  分别以 committed/abandoned 拒绝，candidate 文件、A 完成后的 state 与 ledger bytes 不变。
- 两项线程测试在 pipeline 基类及 auto-publish 子类继承集合共执行 4 项，全部通过；SQLite/Celery
  eager 禁网的 P0 三模块为 `270/270`。Django、迁移、旧规格流程 与 diff 门禁见本轮验证记录；
  未访问生产。

## task 5.4 已审核空胜绩门禁返修

RED：

- 有完整履历但没有胜绩的 profile，即使已有 applied `major_wins` 空审核，旧完整度仍返回
  `major_wins` blocker。
- 正式 reviewed artifact 对同类马应用后，因 data evaluation 不完整而不会设置
  `full_profile_reviewed_by/at`，随后 strict-complete 失败并触发事务回滚。
- 新生成 candidate/artifact 不包含完整度策略版本，旧批准可在代码语义变化后被误复用。

GREEN：

- applied 且带 `applied_by/applied_at` 的最新非 ignored `major_wins` 审核满足无胜绩完整度；
  没有审核和最新 conflict 两种情况继续阻断。
- 正式 artifact 能为经审核无胜绩马写入完整复审元数据并通过严格完整度。
- artifact/candidate 同时绑定 `p0-horse-full-profile-completeness.v2`；stale artifact 在
  production dry-run 的数据库路径前拒绝。
- 3 项关键测试通过。组合运行
  `P0HorseProfileDataCompletionTests + stable.test_p0_horse_production_apply +
  stable.test_p0_horse_completion_batch` 共 312 项，308 项通过；4 项公开页面文案失败在修复前
  `04c89e35` 基线 4/4 同样失败，因此本轮增量失败为 0。全程 SQLite/Celery eager、未触网、
  未访问生产。
- 排除上述基线失败后单独运行两项新增完整度回归与
  `stable.test_p0_horse_production_apply + stable.test_p0_horse_completion_batch`，
  `247/247` 通过。Django check 无问题，迁移无漂移，旧规格流程 strict/all `37/37`，diff check
  通过。
