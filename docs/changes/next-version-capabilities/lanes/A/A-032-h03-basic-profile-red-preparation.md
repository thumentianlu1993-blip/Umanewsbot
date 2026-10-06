# A032：H03 基础档案业务 RED 准备

任务 `A032-H03-BASIC-PROFILE-IMPLEMENT-001`，固定集成 base `2c72521c55b6cdc24f7650d172b48079cbff969a`，新树 `codex/a032-h03-basic-profile`，旧 A 树完整保留。输入为原 R `4164a5f15bbfd33dd26ca81b0ef2023263178f3e` 已核的 `7c0eb503` A031 最终方案；移入同字节报告，不改已审范围。当前仅准备可执行 RED，不声称实际 RED、GREEN 或 H03 完成。

## 目标与当前边界

一个已有未公开、已核强身份 profile，单 HKJC 合成原件经 adapter→H02 再进入真实候选模型/既有 writer，七字段写入及人工锁/审计/回滚。只读发布门槛，不发布；不取真实源、不改身份、中文名、履历、共享模型/视图/settings/catalog或B翻译面。新增服务目前只有完整签名的零写占位入口，返回 blocked/not_implemented；这是 RED 缺失能力基线，非业务实现。真实 PG 资源尚未分配；不运行 DB 或用 SQLite替代，不启动 Docker/构建/新磁盘。原指令覆盖既定 G1；当前不触发 G2/G3。

## 接口和最小 RED

入口 `apply_basic_profile_from_cache` 全部 keyword 输入：snapshot、candidate、raw_bytes、expected_sha256、ref、source_ref、entity_versions、as_of、max_age_seconds、expected_updated_at、actor。输出 status/published；之后实现依 A031 补完整 before/after、锁字段和只读 gate。可信 expectedSHA/当前H01绑定仍由调用方提供，本轮仅合成数据，不冒真实来源认证。

最小 RED ID：
`stable.test_horse_basic_profile_from_cache.BasicProfileFromCacheTests.test_persists_seven_fields_and_json_safe_date_without_publication`。

测试先在真正隔离 PG 建 actor/TermEntry/draft profile，用现有 adapter 与 H02 验证 reusable 合成候选，再调用正常导入且签名完整的占位入口；首个业务断言是数据库 country 必须由空变为 AUS。占位入口未写，因此预期 AssertionError：`H03 must actually persist seven basic fields`。导入/fixture/签名/依赖/迁移/连通/资源失败一律不算 RED。实际失败日志、exit、固定SHA和完整ID需 ROOT 窗口执行后保存；取得真实 RED 后才写实现。

## test_cases 与 mutation

| ID（同模块，方法尾名） | 待验证业务断言 | 捕获 mutation |
| --- | --- | --- |
| persists_seven_fields_and_json_safe_date_without_publication | 七字段/date真实保存，candidate JSON/date ISO/APPLIED/默认confidence0，一候选一次审计；状态/中文名/TermEntry/身份/血统/career不变 | no-op、字符串日期直接赋值、越界写入或自动发布 |
| existing_date_diff_is_json_safe | 当前已有date与候选date均能持久化JSON diff | 忽略diff日期转换 |
| original_request_replay_after_real_field_change_is_zero_write | 首次字段真实改变updated_at后，完整原请求含旧baseline重投 already_applied，profile/candidate/log零写 | 先baseline拒绝或去掉消费key去重 |
| new_key_old_baseline_is_blocked | 新key旧baseline拒绝且零写 | 忽略baseline/旧输入自动重取基线 |
| consumed_key_changed_content_is_blocked | 同key异原件SHA拒绝 | 只看key不核摘要 |
| field_lock_preserves_manual_owner | 人工owner保留、其余字段写入 | 忽略field lock |
| module_lock_consumes_once_without_overwrite_after_unlock | 全模块不改，但消费一次；解锁不偷偷重用已消费版本 | 忽略module lock或解锁后重复应用 |
| flat_identity_key_is_insufficient / identity_drift_still_blocks_consumed_replay | 只认current verified keys，安全校验先于幂等返回 | name/flat key代替强身份或先幂等跳过安全 |
| public_or_hidden_target_is_blocked | 公开/隐藏拒绝 | 只读eligible误当发布或允许公开字段更新 |
| tampered_candidate_and_bytes_are_blocked | H02候选/原bytes篡改零写 | 不复算候选/原件SHA |
| duplicate_verified_key_on_other_profile_blocks | 局部fixture同key另一profile阻断 | 只看目标自身不检查局部冲突 |
| log_failure_rolls_back_profile_and_candidate | 实际writer日志失败整片回滚，无孤儿 | outer atomic缺失或日志在事务外 |
| existing_writer_is_used | 正向真实保存并调用已有apply_data_candidate一次 | 私建第二套业务writer |
| BasicProfileCacheConcurrencyTests.second_identical_request_waits_then_returns_already_applied | 第一位在既有writer内暂停，pg_stat_activity实际Lock等待，释放后第二位already_applied，仅一candidate/log | 无行锁、baseline优先、重复候选 |

当前14项状态/持久化测试＋1项独立并发，共15项，无skip。其余A031边界（不存在/hidden_at、READY、同namespace矛盾、候选create/apply异常、过长/清空字段、只读gate结果形状等）沿已审计划，在对应行为实现前补定向RED；不是把第一项RED当全部行为已覆盖。模块收集及合成输入纯检查可离线执行，不运行setUp/业务DB。并发显式三连接：观察者+两worker；使用现有writer模块属性调用，方便故障注入和真实锁等待观察；worker连接finally关闭，暂停有10s上限。

## ROOT 排队的最小 PG 执行材料

runtime提供 `run_allocated_pg_tests.py`，只读固定clean Git SHA。必须提供ROOT资源 manifest：allocation_id/owner=ROOT/synthetic_isolated=true/host/port/database_name（a032_前缀）/test_database_name（a032_test_前缀）/user/password_env（A032_前缀）。凭据只在本地环境中，不进入报告/manifest/日志。此manifest是资源绑定，不是新增人工门禁。驱动不读取app.settings/.env，不启动服务，使用现有迁移、memory Celery与dummy cache，单执行进程；ROOT预建专用测试库并控制keepdb后的清理。资源真实性、Linux egress只允许指定PG、已有镜像/依赖与清理证据由ROOT固定；manifest字段本身不证明隔离。这里未分配或调用任何PG。

第一窗口仅上面的一个RED ID。ROOT可用已存在依赖镜像/执行器，固定树只读挂载，命令为：

```text
<已有Linux Python> <runtime>/run_allocated_pg_tests.py --tree <固定树> --expect-sha <RED_SHA> --allocation-json <ROOT本地manifest> --label stable.test_horse_basic_profile_from_cache.BasicProfileFromCacheTests.test_persists_seven_fields_and_json_safe_date_without_publication
```

申请预算（不是allocation）：现有隔离PG专用测试数据库1个、测试执行进程1个，首RED最多2连接（管理/测试）；后续并发最多3连接。墙钟总600秒**包含最后60秒清理**，驱动540秒触发异常/关闭连接，ROOT外层600秒硬截止并核清理；迁移/准备超过预算即失败，不扩大到4GiB新build。最大选集15项，不跑全stable；PG现有磁盘/内存余量由ROOT确认，不声称2GiB控制已证明。资源排队与B互斥由ROOT协调。没有合格窗口只停准备，禁止伪报RED或提前实现。

## ownership 与停止点

本提交仅移入最终A031输入、新占位service、独立tests、独立合成fixture、本A报告；runtime驱动和封存不改共享文件。合成原件源自旧hong_kong fixture的独立副本，仅source.url替换为HKJC合法形状，旧时间保持，career/其他URL仍合成示例；独立expectedSHA由测试计算，原fixture不改。实际业务RED待ROOT资源，当前只有静态/无DB准备验证。提交后交ROOT排队并停，不自动实现、不push/PR/merge/deploy，无subagent/modelCLI/reset/旧任务复跑。

准备验证结果：AST解析、正常import和15 ID收集通过；独立合成原件adapter→H02 reusable通过（禁止DB/network guard启用），source_time仍为2026-07-18，原fixture与最终A031输入字节保持。workflow contract及其4项文档测试、git diff --check通过；没有执行任何业务test setUp/保存/回滚/并发。额度起止9%已用、91%剩余。旧A树HEAD仍7c0eb503、clean；RED准备固定提交不是“RED已失败”证据。
