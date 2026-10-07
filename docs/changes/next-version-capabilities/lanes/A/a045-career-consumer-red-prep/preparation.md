# A045 本地测试先行准备（未执行）

授权：ROOT A045-CAREER-CONSUMER-RED-PREP-001；已审方案 A044 `374108463f01a3ca78e1e18f2c78d5c81ff194d9`，原 R `397db1e32c486660a65b4d504e9a5c0e4d19df33`。独立 checkout 从 `main90f73d8093df00827a7ec78cc41dc3d3b91730c0` / tree `3e02fd2150bcc5c77b7d4e734bc8012089ff35e9` 起步；保留 A044。只新增本线 command/service/test/docs，旧 writer eligibility 改动留待真实 RED 后 GREEN。

## 已落代码与 RED 接口

新 service `prepare_reviewed_career_record` 对原始 packet/source/review bytes 做 SHA/严格 schema/独立 scope/目标绑定，调用原 cache adapter、H02 planner、P0 normalizer。复用原纯输入 `_prepare` 的真实 adapter/planner/完整 source validator，没有调用 basic-profile `_review/_bundle` 或旧 consumer。选择唯一原行 SHA、保留原 raw 字典，actual started/exact/date/strong row anchors 检查。

`consume_reviewed_career_record(*, packet, source_raw, reviewed_raw, expected_review_sha256, expected_row_sha256, actor, code_sha, dry_run)` 全参数可运行，packet 明确为原字节。完成真实输入重建后返回 `prepared_noop`，无 actor/profile 锁、writer、消费审计和记录写入，亦不宣称具备这些功能。它是指定 RED stub；完整事务/权限/回放行为由下面测试驱动实际 GREEN。

命令有 dry-run/commit 互斥、全部已审参数；通过原安全 FD/captured-input 读取0700目录/0600文件，不提供 record-review/fetch/publication。command 实际 `git rev-parse HEAD` 核对 `--code-sha`，不把声明视为真实执行证明；正式 command 测试窗口需 git 可用及只读正确 Git metadata，Git 缺失/路径不可解析不能当业务 RED。

## 两条指定真实 RED

新类 `stable.test_horse_career_record_from_review.ReviewedCareerRecordConsumerTests`：

1. `test_legacy_writer_preserves_explicit_eligibility`：真实旧 upsert 创建 record，refresh DB 后断言 `eligibility_text='3yo+'`、min age3/open ended/无issues。当前 writer 缺 key 导致实际字段为空应形成精确业务 FAIL；不手工 ORM 填字段。GREEN还断言后续 payload 缺 key 不清空。
2. `test_create_replay_and_original_legal_link_same_record`：实际有效独立 sidecar/adapter/planner/source/profile baseline 完成重建，stub 后实际记录0，断言0→1应形成业务 FAIL；该方法后半完整定义已审 GREEN 的创建、零写重放、原合法补连同PK及补连后创建重放。

必须两条均为 FAIL、无 ERROR，且失败点分别是实际字段/正式记录；不接受 import/parser/signature、fixture/cache/H02/admission/code SHA/隔离环境错误作 RED。先核 prerequisite，再正式执行一批两方法，不重复运行或删断言换通过。其余方法已落，但 RED窗口不执行全类/并发；待真实 RED封存后 GREEN 及 ROOT 另派资源验证。

## GREEN 合同已落测试

测试 setup 使用原 HKJC synthetic fixture 的独立内存拷贝；复制原 legal-binding setup（真实 policy loader/admission、ORM source/enrollment/binding），删去原 writer种记录和 eligibility手工补洞。初始目标没有赛绩，已有私有名称/owner/官方总数9等保护 sentinel，并有非空下游合法绑定。active staff 是真实 User。

现有其他方法覆盖：scope/profile/source SHA/H02/version/baseline/私有/手工锁/current actor、缓存过期、既存非本角色记录拒收；nonstarter及矛盾started、ignore/dry-run真实writer回滚；真实写后writer/save/DB issues/candidate/log/expiry故障全事务rollback；OP/L/NEWCOMER原属性；私有文件权限与commit后BrokenPipe；相同输入真实PG等待后单消费；staff/active两种撤权先提交拒绝、消费持actor锁则真实撤权等待且后续replay拒绝；实际锁等待跨真实UTC TTL拒绝。

同步屏障仅暂停真实writer/持锁事务，不替换锁/权限/writer成功路径。定点故障回调先调用实际 writer/save；隔离历史时钟仅用于普通 synthetic tests。TTL并发测试关闭历史时钟，source时间用实际UTC，等待数据库blocking证据后实际跨6秒TTL，lock_timeout15秒，不能把timeout伪装成TTL。测试控制连接只读查 pg_stat_activity，两个业务连接实际锁/写，因此 GREEN 并发需至少3个连接的资源上限。每个 future/屏障有界并释放连接；时间循环最长8秒。

## 隔离窗口请求与源码封存

只提供未运行的 runtime settings/manifest/request，ROOT 分配原隔离窗口后执行。settings 要求 explicit A045 开关、独立PG/test库名，禁外网/调度/自动发布，LocMem cache，conn_max_age0。不得连生产或启动既有业务任务。ROOT绑定实际固定源码 SHA/tree 与 manifest/hash，不由此文档授权执行。

RED方法只需普通窗口；full GREEN要允许两个业务PG连接加一个只读控制连接。ROOT沿既有 window runner/resource flock 收集runner PID/结果/真实failure/readback/释放证明；本线不自行创建或运行Docker/PG runner。环境需 `A045_TEST_CODE_SHA=<fixed A045 commit>`，strict request将此值绑定sidecar。准备阶段仅AST/signature/字节比较/diff-check，无 Django import、collect、PG 或测试执行。

GREEN前必须修复 service 完整合同而不是把 `prepared_noop` 解释为成功；尤其 mandatory User NO_KEY_UPDATE→profile→candidate/record、锁内current权限及等待后TTL、同事务真实writer/postchecks/审计、zero-write replay/raw SHA、独立scope和publication保护。旧 writer改动仅条件含key写eligibility，不改模型/UI/task/补连/来源权限。


## H01 fixture 前置修订（未执行）

原候选 `79c381c457db814425775bec818074e06033792f` 的 request 只有 identities，没有 H01 layers，导致原 `_prepare` 的 profile_exists/public_state 门禁拒绝，创建方法到不了指定业务 RED。该候选和原 runtime 保留为历史准备证据，不算有效 RED。

本次仅补测试 request 的真实 H01 layer：target_key 使用实际 profile PK，存在性真实 ORM 查询，确认当前 profile 为 DRAFT/READY 且未 hidden，再声明 unpublished；source 原字节已在 fixture 中故 cache=present；未建立 staging 则明确 unknown；starts 从该 profile 实际 started records 查询，incomplete_modules 保持未知，不编造完整度。另对实际 H02 decision 的 profile_exists=True/public_state=unpublished 做前置断言。原 guard/admission/service/command/writer 和两条指定业务断言均不变。

新 packet、H01 inventory、H02 plan、review sidecar SHA 仍在 request 中按真实修订 snapshot 重建，不沿用旧摘要。另建修订 runtime 清单；不改原 runner/settings 适配，ROOT 正在核定精确运行前置。仍未 import Django、运行 PG、执行 RED 或 GREEN。
