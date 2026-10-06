# A034：已有赛绩补连 RED 准备与测试设计

任务 `A034-H03-CAREER-LINK-RED-PREP-001`。固定 base `44f79a62d9071b20382bc4b42dc19775fe7d2f10`；原 R `2fd93bfdb009b2a5612a7c68d2524109d9065c00` 已关闭 A033-R01，仅 APPROVED_PLAN_ONLY（ROOT 派单状态）。目标仅准备正常导入、完整签名、无读写占位入口、独立合成 fixture 和五组业务 RED。现有指令覆盖本地准备；G2/G3 未触发。未证明实现、真实 RED 或真实来源可接入。

## 当前状态、边界与依赖

- 入口 `stable.services.horse_career_record_link_from_cache.apply_career_record_link_from_cache` 接收 A032 的完整 H01/H02/cache 参数及 selected_row_sha、record/event/source/binding PK、expected_binding_manifest_sha256、record baseline；固定返回 blocked/career_link_not_implemented，不读 DB/文件、不调用 writer、不改输入。未连接 views/tasks/公开入口。
- 只新增上述 service、独立测试、`fixtures/h03_career_link/hkjc_synthetic.json` 和本 A 报告。保留他线；不改 A032/shared models/settings/views/migration/catalog/B/C/历史 fixture。测试运行时 override_settings 仅隔离测试进程及临时 policy 路径，不修改共享配置或开启网络。
- fixture 是 A032 原件的独立合成副本，明确补 provider/external_race_id/external_horse_id/operator/namespace/venue_key/精确日/slot/timezone；PU 仍为实际出赛，另一 WV 行不消费。合成模型已有 profile、赛绩、event、source identity、enrollment/binding；它们不证明现实审批/许可或真实赛事基线。
- setUp 经真实 canonical policy 文件 loader/parser、真实 binding_admission_reason(capability=racecard, check_runtime=False) 核空 reason；从不 mock admission/loader。现有两基础 flags 仅在合成模型/route 中模拟已存在合同，所有测试运行网络/scheduler 开关关闭。H01/H02 真实函数复算 reusable，校验失败是 fixture error，不是 RED。
- 用既有 writer 创建合成未关联赛绩，显式准备其现有 eligibility_text=3yo+ 后调用原 normalizer；该字段不在 legacy writer 的管理字段中，不改 writer。旧 normalization 必须无 issue，外部身份/raw/source refs 与被选原行对应。
- 未来实现应通过模块调用共享 writer，故故障/并发注入在真实 `horse_race_records.upsert_race_record` 接缝，返回值是 RaceRecordUpsertResult，内存 issue 检查在 `.record`；不得以错把结果对象当模型制造 RED。初始模型 clock 固定，首次业务调用推进一秒，避免冻结时间掩盖 updated_at 变化。

## 五组 canonical IDs 与验收/mutation

共同前置：正常导入且完整签名；ROOT 分配的隔离 PostgreSQL；全部 fixture 合同自检成功。每组先要求真实 record.event_id 从 NULL 变成本 event PK；这是占位的预期业务失败。负向、故障和并发组的该正向探针在 savepoint 中回滚，再验证本组反例，不把探针写入混作计数。当前未运行任何组。

| 精确 canonical ID | 验收与捕获的 mutation |
| --- | --- |
| stable.test_horse_career_record_link_from_cache.CareerRecordLinkFromCacheTests.test_existing_record_link_preserves_facts_and_only_derives_counters | 同 PK/条数，原成绩/idempotency/raw/source refs 不变；只关联及 canonical/normalization 元数据，linked=1/unlinked=0/实际出赛=1；source 总数/authority/公开/术语/赛事/结果/绑定不变，candidate APPLIED/confidence=0 和 log 各一次。捕获重复 create、默认空投影清字段、误公开/来源升级 |
| stable.test_horse_career_record_link_from_cache.CareerRecordLinkFromCacheTests.test_original_baseline_replay_and_changed_binding_input | 首次有实际 profile 时间变化，原完整请求和原 baseline 重投 already_applied，所有持久字段（含 normalized_at）、audit/条数零写；同 key 换 binding SHA/selected row SHA 拒绝。捕获 baseline 优先、重复 writer/normalizer/audit、输入漂移 |
| stable.test_horse_career_record_link_from_cache.CareerRecordLinkFromCacheTests.test_identity_contract_expiration_and_revocation_fail_closed | 已存在合同 flags/review/terms/期限/registry/撤销、slot/operator/namespace、binding state/schema/manifest/identity digest、enrollment paused/retired、跨年/日期、人工模块锁/public/hidden/马身份反例逐项零写；缺强字段、旧 cache as_of + 新 live clock 到期及 policy 文件 SHA 漂移拒绝。捕获名字/年份 fallback、漏锁/身份/现有合同、伪离线许可 |
| stable.test_horse_career_record_link_from_cache.CareerRecordLinkFromCacheTests.test_post_write_failures_issues_and_expiration_roll_back_all | 原 writer 实际被调用且写后才注入 writer/candidate/log 失败；内存 issue、仅持久 issue、写后时间过期都整片回滚 profile/record/candidate/log；不可凭无异常视成功。捕获半关联、孤儿、遗漏内存/持久后验、只 preflight 判有效期 |
| stable.test_horse_career_record_link_from_cache.CareerRecordLinkFromCacheTests.test_two_identical_requests_observe_pg_lock_then_one_consumption | 同 profile 两完整请求，第一在 writer 持锁暂停；真实 pg_stat_activity wait_event_type=Lock 且 pg_blocking_pids 指向第一连接，打印 A034_PG_LOCK_EVIDENCE；第一 applied、第二 already_applied，candidate/log 各一次。捕获缺事务/profile 锁/去重，不声称旧 writer 全局线性化 |

范围/性能上限：每调用一 profile/一已有赛绩/一绑定；不新建或批量消费其他行，不接受 result_id；无 Celery/迁移/自动任务改动。busy/约束歧义与现有共享 writer 保守规则延续 A033，既有回归覆盖；SQLite 不替代锁/rollback证据。错误与 fixture 自检失败必须原样报告，不记为业务 RED。占位可能使五组都在共同正向断言失败；这仅证明入口尚缺补连行为，后续反例在 GREEN 才会走到，不能宣称它们已实测。

## 运行计划与资源申请

先静态检查、提交固定 SHA、封存源码/fixture/测试 IDs 后交 ROOT。尚无 A 的 PG 窗口，禁止本地主机 PG、SQLite 冒充、Docker 启动或 DB 测试。申请沿 A032 已用的 ROOT 官方无网络固定镜像和八个固定测试控制文件，独占有 owner/heartbeat/可释放锁的 bounded 窗口：2 CPU、4 GiB、256 PID、3 GiB tmpfs、非 root/read-only source/cap-drop/NNP；600 秒总窗含末 60 秒清理，540 秒止测。镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905` 仅为拟复用，不表示已核当前镜像或获分配；由 ROOT 重新绑定镜像/controls/窗口 manifest，禁止 build/pull/自制 PG 驱动。

建议第一分配只跑上表第一 canonical ID（正常 Django 导入/完整签名/真实 fixture setup，预期一次 FK 业务 assertion failure，0 error/skip）。ROOT 核有效 RED 后再按授权跑其余四组、随后另卡 GREEN；未核 RED 不实现 GREEN。官方 collector/runner 的实际 ID 必须与静态表一致；不把 AST 数量当收集证据。失败若来自 setup/parser/签名，先仅修测试/fixture并交新 SHA，不实作 service。

拟受影响回归（GREEN 后按 ROOT 固定清单分批，单批最多200项）：`stable.test_horse_basic_profile_from_cache`、`stable.test_horse_cache_reuse`、`stable.test_horse_source_cache_reuse_adapter`、`stable.test_horse_target_inventory`、`stable.test_p0_horse_career_history`；binding基础合同相邻 `stable.test_race_multisource_identity` 与 `stable.test_race_multisource_jra.MultisourceRebindTests` 由 ROOT 判断固定现有精确方法范围，禁止继承导致隐性全模块扩大。所有官方要求的 core 保留。新增路径尚未写 catalog，需 ROOT/C 处理正式映射或精确专用窗口授权；unknown 不改作空选集/偷偷全量，本轮不修改 catalog。

## 验证与交接状态

本轮仅 Python AST/JSON、入口真实普通 import/签名/固定 blocked/零输入变更静态核验、共享文件与 base hash 对比、工作流契约/4项文档测试及 diff 检查。未启动 Django fixture/DB、未执行业务测试/官方 collector、未分配资源；无真实 RED、GREEN、实现交付、push/PR/合并/生产/真实源/付费/消息/权限变化。占位可逆地新增且未接入现有运行流，回退本次新增文件即可撤销准备；无需迁移/服务发布。

额度开始12%已用/88%剩余，最近13%已用/87%剩余；每5分钟核验，<=1%停止、每批目标<=3%。固定提交/runtime与静态 ID 清单交 ROOT；A 等待精确 PG 窗口。
