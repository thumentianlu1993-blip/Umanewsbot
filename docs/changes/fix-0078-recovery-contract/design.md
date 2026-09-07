# 0078 发布与恢复合同：工程设计

## 1. 设计选择

采用有限、显式的 0078 合同扩展，保留普通回滚关闭和历史 0077 协议。拒绝两种捷径：全仓替换 0077 → 0078；由“最大迁移号”自动批准未来 migration。

实现复用既有部署锁、backup_db.sh、drain/health、preflight 和 one-shot。0078协调逻辑集中在
deploy/release_0078.py，共享校验集中在server/stable/services/release_0078_recovery.py；
原方案中的两个producer脚本合并进同一协调脚本，不增加通用状态机或独立迁移owner。
release_id直接使用原admission SHA，不增加另一套ID分配机制。下文所说producer/intent职责
均由这两份文件承担；既有schema/handoff/管理命令只接入所需字段。

## 2. 0078 迁移事实与 catalog

0078 依赖 0077，仅新增 stable_externalhorse.profile_snapshot。Django JSONField(default=dict, blank=True) 在 PostgreSQL 的预期是 jsonb、NOT NULL，完成 ADD COLUMN 后没有持久数据库 default；Python default 与 DB default 不能混同。实施时在隔离 PG16 从真实 0077 升级采集 catalog，确认后冻结 fixture。

- 0078 未记录：snapshot 列必须不存在；出现列却未记录属于漂移，不能 --fake。
- 0078 已记录：列必须唯一存在、jsonb、NOT NULL、无 identity/generated 属性、无持久 default。
- 既有 0077 identity/namevariant 表、列、约束、索引和序列仍执行原校验，不能用 snapshot 检查替代。
- 先读取 recorder/pg_catalog，再进行 ORM 业务审计；连接错误仍传播，不能转成 ok。
- 0078 migration 文件保持逐字节不变。5 秒 lock_timeout、5 分钟 statement_timeout、atomic 和 forbid_reverse 均作为回归条件。

新增窄函数 validate_externalhorse_profile_snapshot_catalog_contract，挂在既有 catalog validator 后。若现有 collector 不含该列或 generated 属性，补采精确列证据；不扩大为全库内容扫描。

## 3. 状态与动作矩阵

新合同目标固定 stable.0078_externalhorse_profile_snapshot，记录 exact migration 文件清单及内容 hash。不同动作的可接受起点必须在一张显式表中定义并由 schema、handoff 和 completion 共用。

| 当前状态 | 新候选允许动作 | migration plan / 结果 |
| --- | --- | --- |
| 稳定 0078，无在途 marker | deploy / manual-release | 空计划；完整 catalog 验证后才收口 |
| 稳定 0077，无在途 marker | deploy | 仅 0078；必须新备份绑定和关闭态 handoff |
| 当前 0078 发布在途，live 仍 0077 | 同一发布的 forward-resume | 仅 0078；原 candidate、原备份、原 intent，不建立新 deploy |
| 当前 0078 发布在途，live 已 0078 | 同一发布的 forward-resume / complete | 无 DDL；完成 static/intent，验证后恢复服务 |
| 任意 live，有 marker 但发起新的 deploy/普通 manual-release | 拒绝 | 不抢占/删除/覆盖旧意图 |
| 旧 0077 artifact 或 0076/更早 live | 新 0078 合同拒绝 | 使用固定旧控制版本恢复到稳定 0077后重新准备新包 |
| 0079、未知、分叉、catalog 漂移 | 拒绝 | 不停服、不迁移；已在关闭窗口则继续关闭 |
| 任意状态的普通 rollback / reverse | 拒绝 | 恢复需独立精确备份流程 |

新 schema 分支只接受表内状态。保留旧世代函数/fixture 的明确目标语义；不通过把 FINAL_LEAF_SET 改成 0078 让旧 marker 获得新权限。旧协议控制镜像已固定时不修改其磁盘 artifact；本候选不自动接管旧在途流程。

当前生产据文档已在 0078，因此本修复的实际发布预计无 DDL。0077→0078 分支用于完整验证与后续恢复兼容，不在当前生产重复执行 migration。

## 4. 新 0078 handoff 与备份绑定

新 handoff 使用独立版本 migration-history-repair-preflight/v5，显式包含 target_leaf_set 与 migration_contract_sha256。v4 历史 payload 不允许因补默认值晋级为 v5。

为本候选的两种发布增加窄的 release-0078-verified-backup-recovery/v1 manifest。目录 runtime/migration_history_repair/release-0078-recovery/<release_id>/。operation 明确为 upgrade 或 same-schema；同版本证明准确写 source=target=0078，不冒充跨越迁移。复用现有安全读写、SHA、权限和 no-clobber helper；不重命名旧 release-0077-recovery/v1 文件或赋予其新含义。

manifest 绑定：

- 原始 admission handoff SHA、candidate commit/image ID；
- release_id、operation、数据库 identity；source leaf 精确 0077（upgrade）或 0078（same-schema），target leaf 均精确 0078；
- 迁移清单及 hash、backup 绝对路径/大小/SHA；
- pg_restore --list 的成功结果、TOC digest 与条目数量；
- 文件 owner、0600 模式、目录可信链、无 symlink。

同版本 0078→0078 也必须经过实际 producer/consumer。deploy.sh、deploy_lowcost.sh 和 manual_release.sh 的新0078分支统一调用release_0078.py。新发布准备在固定release_id下由既有backup_db.sh生成新路径的备份；producer复验来源DB、source leaf、文件身份、实际字节SHA和TOC后生成manifest。重试只能复用同一release_id/原始admission/candidate的已验证备份，不能补造新的origin SHA。

消费者至少包括 run_application_release.sh（第一条 stop 前）、run_release_tasks.sh 与 in-container verifier（第一条写动作前）、manual_release.sh 和 resume_migration_history_repair.sh。全部重读相同可信 manifest 及原始字节 SHA；数据库/operation/source/target/candidate/image 不同、备份文件替换、另一次发布证明、只传路径没有证明都拒绝。manual-release 若在完整0078且服务已由外部停止，可在任何 release-task 写动作前新建本次证明与“原本停止”的服务意图；若有既有意图，则必须走同发布恢复入口，不能另建。

顺序：

1. 持有既有部署锁，固定 release_id、candidate/image 和只读 admission；新备份及 manifest 全部验证后冻结。
2. 在第一条stop之前，release_0078.py将仅授权继续关闭和复验的不可变发布意图持久落盘并复读验证。失败则禁止stop。该意图本身不授权迁移。
3. 排空并停止本次受影响应用 writer；每次重试读取实际服务状态，原始恢复意图不因部分停止而改写。
4. 全部停止后生成 bound closed-state handoff，数据库 identity、原始 artifact 和备份绑定必须一致。重试仍以第一次 admission 为 origin，新的 closed artifact 只作为该 origin 的追加证据。
5. 单一 one-shot owner 再校验 closed-state handoff，才创建/确认既有 DDL recovery marker 并执行迁移。发布意图与 DDL marker 的权限不同，不得拿 prepared 意图或 admission-only 直接迁移。
6. exact0078 catalog/空计划 → collectstatic → schema/static completion；发布意图仍保持活动。
7. Web healthy 后按原始意图恢复服务、验收队列和开关，最后才完成发布意图。schema completion 不等于服务已恢复。

普通发布 0078 的失败也保存同世代 intent；完成证据只能在 exact 0078、空计划、正确 catalog 下产生。静态文件阶段失败时不得重复 DDL或提前启动 worker。

传输的新 release_0078_* 字段需同时接到 host wrapper、compose one-shot env、管理命令参数、artifact verifier；只增加 producer 没有 consumer 不算完成。路径可以带空格，必须作为独立 argv 传递；不得沿用未引用的字符串拼接传参。

## 5. 恢复、重放与旧世代边界

继续使用既有受信任 JSON、token/lease、no-clobber、文件 inode/device 和完成收据机制。新增的 host 发布意图是既有 DDL marker 外围的停服恢复依据，不产生第二个 migration owner，也不拥有绕过 closed-state verifier 的写入权限。扩展字段时同步 create/verify/ensure/complete/resume 的校验。

- 不可变发布意图固定在 runtime/migration_history_repair/release-0078-recovery/<release_id>/intent.json；由唯一可信 active pointer 阻止新的发布接管。它绑定 schema generation=0078、source/target leaf、operation、candidate/image、数据库、origin handoff路径/SHA、必需的backup manifest路径/SHA、全部受影响服务与业务开关的原始恢复意图、最初锁token摘要。首次创建和active pointer发布都须在stop前成功且复读；本次恢复重新获取新部署锁，原token只作provenance，不能要求已释放的旧lease继续有效。
- live 停在 0077 时，只有该发布持有的 intent + backup manifest 可重新执行 0078；新候选或新镜像不能接管。
- live 已为 0078 时，原发布意图仍阻止新发布。DDL marker可按原协议归档为schema完成receipt，但发布意图不能因此消失；重复完成沿原receipt幂等返回，不重复迁移或更换备份。
- 文件替换、inode 变化、candidate/DB/SHA 不同、缺字段均失败关闭。
- 旧 v4/0077 artifact 和旧 completion receipt 仍由旧控制镜像解释；新入口报明确不兼容原因，不重写旧文件。
- 首次新候选发布前必须无旧在途 marker/control state；若有，发布包暂停，按旧版本恢复。此限制不能被“当前容器健康”代替。

实际恢复入口统一扩展 deploy/resume_migration_history_repair.sh。新0078分支必须在其原有“要求DDL marker”的检查之前路由，接收已冻结的 RELEASE_0078_INTENT_PATH/SHA（以及其release_id）；验证原候选、镜像、当前DB和备份后取得新锁，按以下表恢复。旧调用仍走旧marker/provenance分支，不猜测或转换。

| 持久状态/失败点 | 新入口的行为 |
| --- | --- |
| 备份证明已写、intent/active pointer未完成，尚无stop | 用原release_id、原admission和已验证证明恢复prepare；补齐并验证intent/pointer后才允许第一条stop；不创建新deploy或重签origin |
| prepared intent有效，部分服务已停止 | 复读实际状态，完成drain/关闭，不把当前已停止状态覆盖原始服务意图 |
| 全部已停，closed handoff未写/写失败 | 从原intent补生成新的closed artifact；验证0 writer、DB/source一致，origin不变 |
| closed已写，DDL marker未发布或发布失败 | 重验closed状态；在同一发布绑定下创建DDL marker，然后才进入one-shot |
| migration失败，live0077 | 同candidate/manifest继续仅0078迁移；无fake、无换镜像 |
| migration已提交，live0078；static/marker completion失败 | 复用原marker或已归档receipt，验证空计划，补齐static/完成证据 |
| schema/static completion已完成，服务尚未全部恢复 | 校验schema receipt和exact0078，继续原服务恢复意图；不再次迁移、不视作新发布 |
| 所有服务验收已通过，发布完成receipt未写/活动指针未清 | 原release_id幂等补完成receipt，校验所指对象身份后清属于自己的指针；不删除别人的意图 |

第一行恢复允许通过同一入口提供原release_id/原备份证明路径和SHA进入prepare续跑；只在证明绑定了原admission且确认没有该发布stop发生时成立。若prepare记录不能证明边界或service状态不符，失败关闭，不靠“marker不存在”推断未停服。两份不可变artifact创建与指针发布中断须可通过文件身份/no-clobber复读完成，不得盲目覆盖。

所有新发布入口（标准、低成本、manual）在任何服务动作前检查active pointer；同发布重试由上述唯一入口继续。不可变原意图与closed/完成证据共同描述阶段，不依靠进程退出码推断已完成。服务成功证据由受锁的coordinator从真实Compose状态生成并复验，不接受调用者一个success=true替代。

## 6. 回滚校验器与模拟允许分支

将回滚白名单格式推进到下一明确版本，固定 required_migrations 包括真实 0078、依赖与 SHA，final_schema_leaf 为 0078；保留：

- generic_code_rollback_allowed=false；
- recovery_mode=forward-only-verified-backup-restore；
- reviewed_targets=[]；
- reverse_migration_allowed=false；
- verified_backup_restore_required=true。

正常生产策略必须在 checkout/build/retag/stop 之前给出“0078 普通代码回滚禁用，需精确备份恢复”的拒绝。上限/内容检查仍保留在独立模拟批准测试分支中，不能因默认禁用就删除。

REVIEWED_TAIL_PATHS 不再用 [-2:] 暗示“最后两条”；显式列出仍需核验的 0076、0077、0078，避免新增 0078 后漏掉 0076。
测试 fixture 可启用独立模拟 retained-schema 模式来验证 OID、blob、路径全集、防嵌套、锁和控制镜像行为，但该批准只能写入临时 fixture，生产文件不能产生真实或伪造 reviewed target。

## 7. 备份恢复的实际证明

不新增自动灾难恢复按钮，不在修复发布中执行生产 restore。继续使用现有 restore_db.sh 的事务恢复实现，补充 runbook 与隔离 PG16 演练：

- 首选保留 0078 schema，发布前 exact 0078 dump + exact compatible image/config 一起恢复。
- 若确需恢复到 0077，目标是恢复整个 0077 备份和认识 0077 的镜像；不是 migrate stable 0077。此操作丢弃恢复点之后的业务变化，必须在未来发布包中明确数据损失窗口。
- 不能把 M1 之前的备份称为含有修复后全部赛果的当前恢复点。
- 演练用自己创建的隔离数据库、合成新闻/赛事/马匹和非空 profile_snapshot；不下载或使用生产 dump。
- 先对照备份 SHA/TOC，再真实 restore 到新的空隔离目标，验证 recorder、catalog、JSON 内容、表计数和关联、目标镜像读取。
- 对已有较新 schema 的库执行 --clean 并不保证清除备份里不存在的较新对象；回退世代时恢复到新空库/实例后切换，避免遗留 snapshot 列。本次不加入自动删库能力。
- 中途失败保持目标隔离，不切换连接或启动 writer。

## 8. 文件责任和改动边界

| 责任域 | 预计文件 |
| --- | --- |
| schema/catalog | server/stable/services/historical_calendar_release_b_schema.py |
| handoff/intent | historical_calendar_release_b_handoff.py；create/verify_historical_calendar_release_b_handoff、ensure/complete/verify_historical_calendar_*recovery 管理命令 |
| host/one-shot | deploy/deploy.sh、deploy_lowcost.sh、run_historical_calendar_release_b_preflight.sh、run_application_release.sh、run_release_tasks.sh、docker/run-release-tasks.sh、manual_release.sh、resume_stopped_release.sh、resume_migration_history_repair.sh |
| 备份与发布意图 | deploy/release_0078.py与server/stable/services/release_0078_recovery.py；复用既有锁、备份和one-shot，旧0077 producer/协议保持原意 |
| 回滚 | deploy/verify_rollback_target_migration.py、reviewed_release_b_rollback_migrations.json、rollback.sh、rollback_lowcost.sh、resume_rollback_control_state.sh及必要 control-state绑定 |
| 测试 | test_single_migration_owner.py、test_migration_history_repair.py、test_migration_history_repair_postgres.py、新 0078 manifest/catalog/恢复测试 |
| 文档 | current_state、deploy_runbook、rollback_guide、backup_recovery、test_baseline_failures_20260907；必要时 decisions/project_status |

实现前按引用扫描确认所有 consumer。不能机械改动所有 0077 字样：旧迁移名、旧协议版本、source leaf、历史证据和负例必须保留。

## 9. 资源、幂等与失败

- 同版本修复无新增业务查询或 Celery 任务；catalog 查询数量有界，不加载马匹 JSON 全表。
- 0078 DDL 的5秒锁等待/5分钟语句超时按既有迁移保留，PG16实测锁超时和原子回滚。
- 新 manifest 文件大小沿既有上限约束，不含密钥或原始业务 payload。
- 锁失败、备份验证失败、candidate 漂移在停服前终止；停服后失败保持关闭和恢复意图。
- 不消费/清空/迁移 race_live，普通及 race_sync_v2 队列只按既有 drain 恢复意图。
