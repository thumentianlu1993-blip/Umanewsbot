# 部署运行手册

## 2026-08-20 race-data-sync R0 发布边界（仅本地实现，未授权部署）

1. 当前生产真实 migration leaf 仍以线上只读核验为准；本候选代码把目标 leaf 扩展为
   `stable.0074_race_data_sync_r0_control_plane`。部署前必须重新核对 exact merge SHA/image、migration plan、
   PostgreSQL catalog、数据库备份可恢复性及全部 `RACE_DATA_SYNC_*` 开关为 false/空集合；不得把本地测试
   结果当作生产已应用证据。
2. 新服务 `race_sync_v2_worker` 只消费 `race_sync_v2`。标准 application/manual release 必须在停止任何服务前
   probe 它；若原本运行，则与普通 worker 分别 drain、停止、写入独立 frozen intent，并只在目标 compose
   catalog 仍存在该服务且恢复合同通过时恢复。probe 或 drain 失败即停止发布并保持后续零执行。
3. `resume_stopped_release.sh` 必须同时读取并交叉验证 race-live 与 race-data-sync 两份 intent 的 action/phase；
   任一可信 pre-contract marker 为 `switching`，即使 sibling 缺失/损坏也必须全局拒绝；两个可信 marker 不一致
   同样保留文件并拒绝。`rollback_pre_single_owner.sh` 在 checkout/build 前也必须 probe/drain/stop 新 worker，
   但目标旧镜像不含该服务时不得恢复到旧 catalog。
4. 普通 Release-B schema rollback 目标必须能通过 `0074` catalog/allowlist 合同。任何 pre-0074 目标都是独立
   跨 schema 恢复：需要新的 reviewed reverse/restore 方案、停服边界与备份证明，不能通过放宽 allowlist 或
   手工 fake migration 绕过。
5. 关闭态部署即使成功也只安装控制面：provider task 仍为 fail-closed placeholder。联网、schedule/racecard/
   result apply、public/correction、enrollment apply 分别需要新的精确授权；不得一次性开启，也不得复用遗留
   `race_live` 队列的历史积压。
6. `RACE_DATA_SYNC_FUTURE_DISCOVERY_ENABLED` 默认必须为 `false`。未来启用只读 proposal 前，standing policy
   必须是绝对路径、普通非 symlink 文件、UTF-8 duplicate-key-free JSON，且
   `RACE_DATA_SYNC_FUTURE_STANDING_POLICY_SHA256` 与原始字节完全一致；image commit 必须是精确 40 位 Git SHA。
   当前 task 只在 `race_sync_v2` 返回 census/manifest proposal，不持久化 artifact、不执行 enrollment apply。
7. `RACE_DATA_RAW_MAX_COMPRESSED_BYTES`、`RACE_DATA_RAW_MAX_UNCOMPRESSED_BYTES`、provider/region 日 bytes/request、
   root high/low water、min-free、cleanup rows/bytes 与 hold alert 的默认值均为 `0`。关闭态部署必须保留这些值；
   在 G2 通过 live disk 与约 45GB 备份的 sizing proof 前，严禁只打开 network 或填任意占位正数绕过门禁。
8. reverse disenrollment 必须使用同一受审 commit 生成的限时 exact manifest，apply 前重算 event/source/route/
   owner/enrollment baseline；成功只释放 tracking、checkpoint 与 `data_sync` owner。不得删除来源证据或任何
   observation/revision/audit，也不得把 reverse 当作公开数据回滚。
9. `0074` 的 reviewed migration SHA 必须是
   `21670e7731456a33e473fd97cb43ca72545477aa600ea594c6c071c4dd2d54eb`；preflight 必须同时核对精确列
   type/nullability/default、状态集合、generation/state-shape CHECK 和 `data_sync` owner 集合。任一
   `CHECK(TRUE)`、任意额外放宽的 `OR`、错误 default 或 nullable/type 漂移都必须停止发布。
10. pre-contract rollback state 的 `phase` 只允许 `pre-switch`、`switching`、`image-switched`（兼容旧的
    `frozen` 读取）。`pre-switch` 退出可恢复旧 worker；`switching` 必须保留 intent 并人工判定镜像状态；
    `image-switched` 不得把新 sync service 启动到不含该 service 的旧 catalog。
11. 首次 enrollment 或 claim 前必须以当前 Slice A roster 重新解析 provider/region/identity namespace/全部
    data kind，并匹配 registry/contract/proof/host/path/budget。legacy transfer 还必须验证 15 分钟内 runtime
    receipt、两个队列 `message_count=0/active_claim_count=0`、精确 commit/expiry 和 projection baseline。
    apply 只接受 `RACE_DATA_SYNC_LEGACY_TRANSFER_APPROVAL_SHA256` 绑定的 canonical approval 文件；approval
    必须在 manifest 生成后、expiry 前产生，并逐字绑定 manifest/receipt raw SHA。任何调用者提供的裸布尔值
    或同一调用方自签 SHA 都不是发布证据。
12. 当前本地候选验证为 `566` 项通过、2 项按环境跳过；这只证明关闭态代码候选，不是 production migration、
    联网、自动 enrollment、赛事字段写入或 worker 启动授权。同一独立 reviewer 的 `VERDICT: APPROVED` 也只
    覆盖该默认关闭 R0 边界。

## 2026-08-17 York race_datetime 与备份/OSS/Nginx 运维收口

1. event `946–953` 的生产时间写入以 manifest
   `0b89c6c9082174190a0b121410b0da5e4bd3bd680ea6f8339db9b7b37e3ef24a` 为唯一输入；写前 backup
   SHA 为 `62770ed9…1111`，apply/verify 均为 `event_count=8 / field_change_count=16`。完整证据见
   `docs/changes/lifecycle-enforce-full-cohort/race_datetime_york_report_20260817.md`。
2. 写后只读 lifecycle prepare 返回 `8 included / 8 required / 8 ready / 1 batch`，四表指纹前后不变。
   该输出只能作为后续 enrollment G3 输入，当前严禁直接 promotion/enforce；lifecycle/race-live 保持关闭。
3. 生产 `.env` 当前 `BACKUP_TARGET=oss`，但旧 endpoint DNS 解析失败；以标准香港 endpoint 只读访问时
   bucket 为 `0 objects`。在新备份链路部署并完成真实上传/远端大小复核前，不得删除
   `/opt/umanewsbot/backups` 中任何历史恢复点。
4. 新 `backup_db.sh` 应输出 custom `.dump`、SHA 和 TOC；low-cost 使用 Compose db，RDS 使用隔离
   postgres client。`BACKUP_TARGET=local` 必须覆盖 `.env`，避免 release rollback snapshot 被迫上传。
   OSS 路径使用受审 web image 内的 uploader，成功标准包含远端对象大小一致。
   canonical/active `.env` 还必须显式保存 allowlisted `COMPOSE_FILE` 与真实
   `EXPECTED_COMPOSE_PROJECT`；low-cost 所有 Compose 调用经 wrapper 绑定 project，RDS promotion
   的 archive 二次复核使用隔离 `postgres:16`，不得调用不存在的 `db` service。
5. Nginx 候选文件 SHA `a506e857…b9c` 与当前生产挂载文件逐字一致。发布时仍须先备份 mounted config，
   执行 `nginx -t`，仅在通过后 smooth reload；禁止 `docker compose down` 或无必要重启 Nginx。

## 2026-08-17 PR #105 lifecycle G2 关闭态发布证据

1. 发布 revision 为 `93cfd240b9ba7e95caf79bf54e9c6d089885f11c`，image 为
   `sha256:06885466d50171d0853997844106ed45a5ab5c65a314ba2f4947a60683885904`；备份 SHA-256 为
   `e6741b7aa896dc2255a7ba1de372f5de6f85f6639b4333cac0de1b47bd0a7893`，回滚 tag 为
   `umanewsbot:rollback-pre-pr105-20260817`。
2. migration leaf `0073`、plan `0`，唯一 release task 实际 no-op；web/worker/Beat 同 revision/image，
   lifecycle `false/off`，race-live scheduler/monitor false 且 worker 未运行。
3. legacy 186/187 canary 第一次 disarm 为 `disarmed`，第二次为 `replay`；mid/after evidence 同 SHA，
   control 为 inactive，公开赛事状态和 transition 未改。外围 evidence verifier 的字段存在性误判与首次
   census 宿主/容器路径误判均已如实保留，后续只读重验/新目录重跑通过。
4. 7 天 census 为 `9867 inspected / 0 included`，未生成 registry，四张 lifecycle 表前后指纹一致；因此
   promotion dry-run 不适用，下一步不能直接启用 G3，须先取得未来赛事可信 `race_datetime`。
5. 完整路径、SHA、偏差与验收见
   `docs/changes/lifecycle-enforce-full-cohort/g2_release_report_20260817.md`。

## 2026-08-16 过期 legacy lifecycle canary 的关闭态 disarm

1. 先确认 web/worker/Beat 同一受审 revision/image，lifecycle 为 `false/off`、legacy/registry env roots 为空、
   race-live scheduler/monitor 为 false 且 race-live worker 未运行；在共享部署锁内停止 Beat、drain 并停止 worker。
2. 逐字节核对旧 manifest raw SHA、approved commit 和 event IDs；只调用
   `verify_race_event_lifecycle_enforce_canary --phase inactive --disarm`。过期例外只影响 manifest loader，DB
   mutation 仍执行完整 frozen cohort 与关闭态校验。
3. 紧接着用相同 artifact 再运行一次 `--phase inactive --disarm`，必须返回幂等 `outcome=replay`；不能用
   不带 `--disarm` 的普通 verify，因为它必须继续拒绝过期 runtime。恢复 worker/Beat 后再跑 host-wide
   false/off coherence。任一步失败均恢复服务、释放锁、保留旧 evidence，禁止继续 census 或 registry promotion。
4. 该动作不启用 lifecycle、不改变公开状态、不启动 race-live。只有 disarm、服务恢复与 coherence 全部通过后，
   才进入 G2 生产只读 census/dry-run。
5. 若旧 applied 证据是 `scheduled -> finished / time_t_plus_30` 单边，只有其 task/source/canary metadata、
   generation 与 T+30 时间门禁全部匹配时，显式 disarm 才可按历史兼容路径消费；不得补造 running transition。
   首次 disarm 还须把 transition activation ID 与当前 active evidence 精确绑定；成功后同一 artifact 的第二次
   disarm 必须返回 `replay` 且零写。同一 artifact 的普通 verify/activate 仍须拒绝该单边。
6. census 的 included IDs 为空时，prepare 必须以 `status=no_candidates` 正常结束，保留 canonical census 与
   enrollment plan、不生成 registry；此时 promotion dry-run 记为“不适用”，不能伪称已经验证 promotion。

## 2026-08-16 0073 migration 已应用但 completion 合同失败的恢复步骤

1. 该状态不是 migration 失败：先核对 recorder leaf 为 `stable.0073_lifecycle_enforce_registry`、无 pending
   migration、共享锁已释放、restricted marker 不存在；不得重做或 fake migration。
2. 若服务已停，可在共享锁内恢复现有 web/worker/Beat 以缩短中断，但必须保持 lifecycle `false/off`、
   legacy/registry runtime roots 为空、race-live scheduler/monitor 关闭且 race-live worker 不启动；这不等于
   新版本部署成功。
3. 修复包必须同时更新 forward/completion/initial-install/rollback leaf 合同、rollback migration allowlist
   与 0073 catalog verifier，并通过 migration-history、single-owner、rollback harness、shell syntax、Django
   check、migration drift 和独立 review。
4. 修复部署仍走标准 `deploy_lowcost.sh` 和唯一 release owner。因为 0073 已应用，migrate 应为 no-op；
   completion 必须在 PostgreSQL 上验证两个 registry 表、FK、唯一约束和关键索引后才允许重建服务。
5. 全部服务按同一新 revision/image 且 false/off 健康后，才继续 legacy canary disarm 和生产只读
   census/dry-run；不得借恢复动作启用 enforce 或 race-live。

## 2026-08-11 lifecycle full-cohort 发布边界（尚未授权执行）

1. 当前生产仍为 event `186,187` 双赛事 canary；event 186 的 T/T+30 已验收，不能据此直接把 IDs 扩成长
   列表。新 registry 代码尚未合并或部署，以下仅为审核中的运行合同。
2. G2 发布包必须绑定最终 reviewer fingerprint、merge SHA/image、migration `0073`、canonical/active env
   filtered hash、旧 canary artifact/raw SHA/approved commit/activation ID、数据库备份与 rollback image。
3. 共享锁内先停止 Beat，按冻结节点身份 drain worker 后停止 worker；只有 writer 静默后才创建并校验
   custom-format DB 备份。随后切 false/off、清空 legacy/registry roots、重建 web 并验证，使用旧 artifact
   自己的 approved commit 完成 legacy disarm。任一步失败后续零执行，race-live 始终不启动。
4. 关闭态部署新代码和 `0073` 后先执行只读 census。缺 control 的 eligible IDs 必须先按 strict-v2 <=20
   场批次 enrollment；registry promotion wrapper 每次只写 <=100 场并循环到完整，partial registry 不可
   activation。caller 的 membership SHA/count 必须与 artifact 和 DB 同时一致。
5. mode switch 接受 promotion 后严格 `Beat=stopped` 的 registry admission；在 web 仍为 false/off、worker/Beat
   已停时 activation。若同 artifact 已 active，则完整校验并复用数据库 activation ID；写两份 env、重建
   web/worker、四元 coherence 和 active verify 全过后，Beat 最后启动。任何失败收敛 false/off。
6. 首档只允许未来 7 天且有 T 的最多 20 场；至少一场真实完成新 registry T/T+30 后才可扩大到 30 天。
   无时间赛事须另做当地次日真实验收，之后才可申请 full_eligible G3。每档发现范围外/重复 applied、旧 root
   claim、锁等待、env/DB 漂移、HTTP/worker/Beat 异常或 race-live 启动，立即 false/off 并保留审计。

## 2026-08-10 PR #98 部署与新 candidate 的精确 G3 入口

1. 当前生产 application revision 为 `127d4833da89e4a8f6b1b9a93bbaec1e65119528`，image 为
   `sha256:37f84597d96a59d48b0e18f567eda399a8bce6bcd1e05241fdb46e6633838852`；迁移 leaf `0072`、
   flags closed、HTTP/writer/lock/log verifier 通过。代码部署备份 SHA 为 `793c51ad…10ff8`。
2. 全新 candidate 为 `d95b580b1d97fb61cbbebe4ae60640ccfccab6e1dcd649ed824ef0215d5a418a`，artifact 为
   `f74c116f63ff1bc561edac10a3a49f3c0643a13a079ec40b13fd5806d266ce0c`；旧 candidate/release/
   approval/G3 禁止使用。新 candidate 当前仅为 `pending_independent_release_approval`，不得直接 apply。
3. G3 获批后先重新核对 exact revision/image、candidate/artifact SHA、7 项 binding、writer/lock/queue 和
   16 blocker 冻结，再生成绑定新 candidate 的全新 release manifest/approval。随后创建 fresh 写前 DB
   备份，进入 maintenance，停止 beat 并安全 drain worker；不得强杀常规任务。
4. manifest-bound dry-run 必须精确得到 profile create `0`/update `32`、race create `180`/update `230`/
   existing `12`、P0 source `32`、module audit `128`。任一 snapshot、动作数、多解或 artifact row 重复解析
   漂移均停止，禁止进入 commit。
5. apply 后完整 verifier 必须证明 planned remaining 全零、422=421 started+1 nonstart、98 major wins 只来自
   `won`、逐马 official count 守恒、source_refs 合并、16 blocker 未进入范围；首次发布只检查
   `8307/45666/45738`。全部通过后才推进 ledger；本次不启动 `full_network`。
6. 独立审查的自定义 230-row DB 重放未完成，不得写成通过。现有动态证据是生产 `prepare-release` 内置
   `_simulate` 成功；正式 dry-run 仍必须重新执行且是唯一写前动态准入。

## 2026-08-10 PR #97 后续日本场地/距离表示修复发布规则

1. PR `#97` 已按 merge SHA `afe0856da2d2ebbd615898b93c4adb3a5f410978` 闭锁部署，生产 image
   `sha256:bd8b12060237ec226f57d7d70e753b632cfb11870a10e29a14df8fca186119c0`，部署备份 SHA
   `7fb1bd2e…e185`；migration/服务/HTTP/queue/flag verifier 通过，未执行 production apply。
2. 新 image 的 `--prepare-release` 在零业务写入阶段因 `3中京8`/`中京` 与 `芝2000`/`2000m` 未等价
   停止。该命令失败不允许手改 state、ledger、candidate、artifact 或旧 approval，也不允许重放旧 G3。
3. 后续补丁必须先通过真实表示正例、不同场地/距离负例、多解阻断、核心 apply/career、邻接 completion
   及 PostgreSQL 首次/重复提交测试，再经独立只读审查。发布仍使用独立 clean release、精确 merge SHA、
   fresh 代码部署备份和全部高风险开关关闭状态。
4. 新 revision verifier 通过后，才可对原受审 research/mapping/authority 输入重新执行 prepare-release；
   期望逐 profile merged-start 守恒，旧 candidate 应由内置 supersede 账本流程失效，不得覆盖旧文件。
5. 新 candidate/artifact/release 生成后必须核对 32 identity、16 frozen blocker、逐模块审核、履历动作、
   source/audit 和首次发布范围，并完成独立 artifact 审查；随后停下申请绑定全新哈希与动作范围的精确 G3。

## 2026-08-10 batch-0001 r2 首次 apply fail-closed

1. 恢复点：`pre-batch0001-r2-g3-20260810T065248Z.dump`，SHA
   `6404536a31369b7bbd2c69ba85dfecb07c4da121c6732f6e4119a74c831438ae`、TOC `1308`；release manifest
   SHA `46b7951db33524105e7ab0b7008f3bc16a314a5c40a31ee8ebbcfb187b15cd33`。
2. 当前 candidate 对 `インターポーザー` 计划新增 JBIS 11 条，但 profile `45661` 已有 Netkeiba 完整
   11 条同场履历；跨来源 canonical 未等价，写后触发 `start_count_mismatch/gaps/needs_review` 并回滚。
3. 回滚守恒：target records `243`、major wins `0`、P0 sources `50`、completion runs `11`、成功 apply
   logs `12` 均不变；三个 draft 仍为 draft，batch/execution ledger 均仍为 `prepared`。
4. 禁止重试当前 candidate/release，禁止手改 ledger 或清除既有履历。下一候选必须先实现并测试跨来源
   同场等价与逐 profile merged-start-count dry-run 门禁，独立复审、闭锁部署后重新生成全部 SHA。
5. worker/beat 已恢复，默认 queue `0`；关闭态 race-live backlog `7543` 未触碰。`full_network` 未启动。

## 2026-08-10 batch-0001 r2 candidate 与精确 G3 门禁

1. 四模块 bundle 已冻结：research `e9a3e93a…81643`、mapping `69ba9f10…6ba7`、authority
   `670932e6…d136`；`32/32 bind_existing`，profile ID 唯一，`16` blocker 继续冻结。
2. release candidate SHA 为 `fc7962c3e337945b70303fbe1868bd7f100c5ff3437296356cfc0955f487e16e`，
   commit artifact SHA 为 `9d2a1e32efbe658f10989771d26c4627a48f395cf99a629a73c2432491c39c16`，
   production snapshot SHA 为 `1bb55ec97fe5439c96c010b2fa163f666b46a13b9fedf1677761c510782dfbe4`。
3. 精确动作范围：profile update `32`、race record create `410`、update `0`、existing `12`、P0 source
   upsert `32`、module audit `128`；首次发布尝试仅限 draft profile `8307/45666/45738`。
4. 未取得绑定上述 SHA、动作范围和 publish scope 的 G3 前，禁止 `--commit`。获批后仍先做 fresh
   custom-format DB 备份、锁/queue/writer 复核、进入 maintenance，再以精确 candidate SHA、独立
   `approved_by` 和 active superuser executor 执行。任一 snapshot drift 确定性停止。
5. commit 后须核对 planned remaining 五字段全零、422 条履历守恒、98 条主胜鞍来自胜出履历、三个
   draft profile 的实际发布结果和完整 HTTP/writer verifier；全部通过后才能推进 ledger 并处理下一批。

## 2026-08-10 participant batch-0001 r2 release draft 桥接

0. PR `#93` 已按 merge SHA `25ea0df188f323e1a24a78f781bab6a27bf0ac73` 部署到
   `/opt/umanews-release-25ea0df1-PR93-20260810/umanewsbot`；image 为
   `sha256:4a8667b91122b2b616cd13b721d666a2be345998277932e0c683a1096a9cc19f`，Release B preflight SHA 为
   `278224b57e901fac31115611ee677d83bf973748c90bffe60fb64e64933049e3`。发布前备份为
   `/opt/umanewsbot/backups/db/pre-pr93-code-deploy-20260810T030655Z.dump`，SHA-256
   `42beceff5fc6aaa85635d3b960595cb0a89ec7b62c15f178b85bcdac27091659`、TOC `1308`；回滚 image tag
   为 `umanewsbot:rollback-pre-pr93-20260810`。

1. 闭锁部署后保持本批 profile network、production apply、P0 automatic first publish、race-live 与
   `full_network` 数据动作关闭；既有新闻运营自动化不属于本批开关，不因该部署改值。先复核 production
   revision、容器 image、writer/queue/lock、HTTP health 与 migration leaf；本命令本身不访问网络或数据库。
2. 只对 execution ledger 中精确 active `prepared` 的 batch 执行：

   ```bash
   python manage.py bridge_p0_participant_release \
     --batch-index <participant-batches-root>/batch_index.json \
     --execution-ledger <participant-execution-root>/execution-ledger.json \
     --completion-manifest <r2-output>/p0_horse_completion_batch_manifest.json \
     --candidates <r2-output>/p0_horse_completion_candidates.jsonl \
     --output <participant-execution-root>/batch-0001-japan-0001/release-draft-r1
   ```

   期望为 `occurrence_count=50`、`unique_identity_count=32`、
   `deduplicated_occurrence_count=2`、`blocked_occurrence_count=16`、
   `module_review_status=pending`、`database_writes=0`。任一值不同都停止，不继续 bundle。
3. 核对 `artifact/participant_source_binding.json` 精确绑定 completion SHA
   `2cf2c634ec3a63ebf36e456ba8ddced814fdcd6897cec737853ee0b6decc04b8`、review manifest SHA
   `f910082db6e649c8aed07648e8488da99e0e5deabd2451621cb617bdeed47f12` 和当前 batch index/ledger；
   32 行 research identity 必须唯一。输出目录已存在时命令拒绝覆盖，重建必须使用新目录。
4. 在用户明确批准 32 个 identity 的 profile/pedigree/race_record/major_wins 四模块且 16 blocker 继续冻结
   前，禁止执行 `p0_horse_completion_batch --bundle`。批准后才以 active superuser reviewer 生成新鲜只读
   production mapping snapshot；映射冲突则返回人工处理，不进入 release candidate。
5. `--prepare-release` 之后仍需独立 release approval 和精确 G3。生产 apply 前执行 fresh 写前备份、服务
   排空和 maintenance；只有 verifier `planned_remaining` 五字段全零后，execution ledger 才可从
   `prepared` 依次推进到 `released -> applied -> verified`，随后才允许 ordinal 2。
6. 本次 production draft 固定在 PR90 权威 evidence root 的
   `participant-execution-2025-6c357985-r1/batch-0001-japan-0001/release-draft-r1`。精确 batch SHA 为
   `5e17bcd1781671fc7dcbfa4f02e3d0a219f504d7cbfb9a9dc7ebc934294e794c`，combined candidates SHA 为
   `77cdb63b621d1e081de2a667732b0a1a7f26d1c3559c0f97fd33ae1f099fa6aa`，source-binding SHA 为
   `0e3d269a6222f47ed01adade185202da0273c9b5a9c57366fd5fda21dac4456b`。生产绝对路径参与 binding，
   不得用本地 `/tmp` replay 的 batch/source-binding SHA 替换这组生产身份。

## 2026-08-09 reviewed official-results package 发布前验证

1. 仓库相对 package 固定为
   `runtime/research/reviewed_packages/2025-official-results-433-r2`，summary SHA 固定为
   `7ddc901ff50f09376799865c541345239f65df06cbcf256b1134bca63bd28d5b`。目录只能包含三份 JSON。
2. 合并前从仓库根直接执行：
   `python runtime/research/validate_official_graded_race_package.py --package-dir runtime/research/reviewed_packages/2025-official-results-433-r2 --summary-sha256 7ddc901ff50f09376799865c541345239f65df06cbcf256b1134bca63bd28d5b --year 2025`。
   返回值必须为 0，且输出 `catalog=433/collect=87/gap=346`。
3. 冻结 parser replay receipt SHA 为
   `1f5656d25e9ec990eee13173303b5e128bf885132174ebeb46a64056c4feb105`：87/87 场、790 starters、
   cache identity/starter count/top 3 全匹配；独立审核为 `APPROVED`、无 P0-P2。
4. 本 package 仍不授权生产回填、澳洲网络验证、official-results 采集或 `full_network`。澳洲 346 场
   保持 `evidence_gap`，直至取得外部许可或用户明确批准本轮只处理非澳洲 87 场。

## 2026-08-09 2025 official-results 新目录与重跑门禁

1. 旧 `404` queue 来自未修复 index 的 TJCIS；旧 `399` queue 虽修复 index，仍错误把澳洲跨年赛季
   当作自然年。两者及其 reviewed mapping/manifest/gap/summary SHA 均禁止复用。新守恒必须是
   Australia `346` + Germany `42` + Middle East `45` = `433`。
2. 澳洲目录只能从冻结的 Racing Australia 两份相邻赛季 Group/Listed 官方文件生成，并核对
   `G1/G2/G3 = 77/97/172`。结果 URL 可由同一 meeting page 复用，但 manifest 必须携带非空
   `source_race_name`、正整数 `distance` 和 `grade`；parser 选不到唯一比赛即确定性停止。
3. Qatar display URL 仍是受审身份入口，runner 派生到 `api.qrec.gov.qa` 数据 URL。bootstrap 只允许
   QREC 官方主页、`_app-*.js`、固定 token endpoint 和进程内缓存；不得冻结或提交 token。Saudi
   `Place = -` 只在完整 JCSA participant row 中解释为 `did_not_finish`。
4. 合并/部署前须通过目标套件、完整 `runtime/research`、真实澳洲页面 smoke、冻结 PDF/XLSX 视觉核验
   与独立代码审查。部署后先从具备访问能力的受控环境验证澳洲 `346` 条候选和逐场选择器，再生成
   source-revision 精确绑定的 reviewed mapping/三文件包。
5. PR `#86` 的合并和部署是新的 G2；生产回填、official-results 网络采集与 2025
   `full_network=true` 仍分别需要新鲜 G3。当前 CDN `403` 不允许被记成采集成功或用旧缓存代替。

## 2026-08-09 德国 official-results parser 发布前门禁

1. 德国官方结果表可能在 participant rows 后包含一个 `colspan` 单格投注/时间摘要。候选 parser 只
   跳过未同时映射到 `position` 与 `horse` 的不完整 row；不得把 `placing()` 的未知状态异常改成跳过。
   该 provider 的 `Pl. = -` 仅在完整 participant row 中规范为 `did_not_finish`，因为官网 starter 汇总
   明确把它计入实际 starter 且非 `Nichtstarter`；该规则不得扩到其他 provider。
   ERA 的完整文案 `Did Not Finish` 是受控通用非完赛状态；仍须用未知完整状态反例证明 fail-closed。
2. 合并前至少复跑 `runtime.research.test_official_graded_race_sources`，并用冻结的真实 2025 德国结果页
   证明 starter rows 可解析且摘要行未进入结果。部署后才可重新开始 official-results 正式 runner；
   旧生产 revision 上该错误是确定性的，不按临时网络 checkpoint 重试。
3. 本修复无 migration、配置或数据写入。发布与后续 G3 数据动作仍是两个独立门禁；代码部署本身不
   授权生产回填或 `full_network=true`。
4. TJCIS 整本 PDF 同时存在 `Pt IV—INDEX` 与 `Part I - INDEX` 标题；两者都必须清空上一页 country
   context。修复前生成的 2025 catalog/review queue 不得局部删行复用，必须从冻结 PDF 全量重建并重算
   catalog set/review SHA，再重新执行逐 provider 守恒审查。

## 2026-08-09 migration 0072 首次发布 STOP 与恢复

1. PR `#83` merge SHA 为 `eb1e221f2791948616c3a72f0e45183d72fdc350`；隔离 release 固定
   `/opt/umanews-release-eb1e221f-GR20260809/umanewsbot`，候选 image 为
   `sha256:ca19687a91c481e19aa51d774a432c9b770cae66bd4ba6092d126c776c8bf5ee`。
2. 写前 dump 为
   `/opt/umanewsbot/backups/db/pre-2025-completion-g2-20260809T064812Z.dump`，`415467279` bytes、
   mode `0600`、TOC `1308`、SHA-256 `9f836669…b60f42`；旧 image 回滚标签为
   `umanewsbot:rollback-pre-2025-completion-g2-20260809T064812Z`。
3. 首次发布在 Celery `active/reserved/active_confirm=0/0/0` 后应用 `0072` 成功，但 completion
   发现 preflight 最终叶仍硬编码 `0071`，以 `migration.state` drift 确定性停止。不要删除
   `django_migrations` 行、伪造 artifact 或手工跳过 completion。
4. 安全恢复：确认 deployment lock 已释放、`0072` recorder 精确一行且候选 image/revision 正确，
   只从同一 release `up -d --no-deps web` 并等待 healthy，再恢复 worker/beat；复核所有高风险 flags
   为 false、writer/lock 为零和 HTTP healthz。保留 race-live-state 文件供后续正式 release 重用。
5. 代码修复必须把 schema target、allowed forward states、restricted final/intermediate states、
   completion verifier 与 host leaf allowlist 一起推进到 `0072`。修复合并部署前，当前状态只能记为
   “服务恢复、migration 已应用、正式 release completion 未通过”。
6. 普通 `rollback.sh` / `rollback_lowcost.sh` 及其 markerless retry 必须要求 live leaf `0072`，目标
   image 必须同时携带 allowlist 中受审 `0071` 依赖与精确 `0072` migration。旧回滚标签
   `rollback-pre-2025-completion-g2-*` 不含 `0072`，只能结合本节写前 dump 走另行审批的数据库恢复，
   禁止作为普通 code-only B→B rollback 目标。

## 2026-08-09 八地区 2025 正式研究 workflow 新门禁（尚未部署）

1. `full_network=true` 必须提供仓库相对的 official result 三文件包目录和 `summary.json` 精确 SHA；
   三文件固定为 `official_result_manifest.json`、`official_result_gaps.json`、`summary.json`。目录、文件
   或任一 catalog/review/manifest/gap/package SHA 漂移均在联网前拒绝。
2. 正式 DAG 为 `official_results` 与旧 `races -> profiles[0..3] -> merge_profiles -> finalize` 并行。
   official runner 逐 provider 限域，保留 response cache/checkpoint；临时网络错误返回 `75`，确定性
   manifest/parser/identity 错误返回 `1` 并禁止 fresh fallback。
3. 续跑仍使用精确 `source_run_id/source_attempt/source_stage=races|profiles`。official artifact 只要
   来源 run 存在就总是恢复；旧分支按 source_stage 恢复，单个 workflow run 内不循环重试。最多六次
   dispatch 属于外部监控授权，不写入 YAML 自循环。
4. 只有两个分支均成功才上传 `completion-bundle-0`；bundle manifest 绑定旧七文件、official final
   三文件和固定 staging 中 reviewed package 三文件的逐文件 SHA；自由输入目录不直接传给 artifact
   uploader。该 bundle 仍是研究证据，不连接 Django、不写生产，
   也不构成后续 profile apply 的 G3。

## 2026-08-09 Release B 精确 G3 apply/verifier 与 2025 正式 run 收口

1. 本次唯一授权绑定 production revision `75294a4dea51538962741ec6c0835dc3090558ff`、reviewed
   manifest `89387fab38f4c2a435c3b009802907a6b9710547354b38f91c3057546f41e96b`、action scope
   `d7052d4392c027522ffde7c14955c98a2bc4ebfa99714c8681237c0ab65900bd`。
2. 写前备份为
   `/opt/umanewsbot/backups/db/pre-release-b-data-apply-path-staging-20260808T172850Z.dump`，
   `413103571` bytes、mode `0600`、TOC `1308`、SHA-256
   `af6aa018da8a14311de4ad86801e729af1c7b9fe40bcb1adca050c0d868a832a`。进入 maintenance 前 writer
   census 为零，并先安全排空 Celery。
3. approval SHA 为 `f5df52d3320aae1c611f652fbcd5e41a438c73b43be346f8ed6fca5f4de55ecf`；maintenance
   evidence SHA 为 `840d87a8c5319fb09047d702fb4592a82a4c956a2b1ee582b11a525a8dfdc661`。首次 apply 调用因
   `historical race backfill is disabled` 在写入前拒绝，receipt 仍为零；该命令合同要求 one-shot
   apply 进程自身显式设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`。只对精确 manifest-bound
   进程注入该环境变量，不修改全局 `.env`，随后 apply 成功。
4. receipt `#1` 为 `verified`；rollback artifact 的 SHA-256 为
   `acb1fc2b2dee46f979517d496be1f81169c27fa56a4be6042ae8e97b7be3342c`，并已持久化到
   `/opt/umanewsbot/backups/release-state/release-b-reviewed-path-staging-20260808T172107Z/`。
   独立 verifier 返回 `errors=[]`，result SHA 为
   `f71c2bc93dc5ff93a7b12ef81518958e9c79ba5ecf65b17e39e30927ebadf0ac`；manifest-bound active
   canonical links 为 `12`。
5. maintenance gate 已退出，active gate=`0`；worker/beat 已恢复，Django check 与内外
   `http://.../healthz/` 为 ok，相关全局 flags 保持 false。443 当前拒绝连接；验收仍以仓库既定的
   HTTP-only 生产入口为准，不把该检查写成 HTTPS 成功。
6. verifier 通过后 fresh dispatch 2025 `full_network=true`，run `31269803408` 首轮全部 job
   success。最终 artifact `31269803408-1-finalize-0`（ID `9025592068`）digest 为
   `sha256:ef8bbc107379413aa2e2ca8ed0dc144759fb7b3578b4d15746b421b923477535`。
7. `summary.json` 为 `outcome=partial`：1063 races、9292 participants、4965 horses；AU/DE/Middle
   East 均 `classification_incomplete`，且存在名称/profile 确定性缺口。因此不把 workflow success
   表述为八地区数据完整，不使用临时网络 checkpoint 重试规则重复相同输入；本次消耗 `1/6` runs。

## 2026-08-09 Release B path staging 修复发布与新 G3 检查点

1. PR `#80` merge commit 为 `75294a4dea51538962741ec6c0835dc3090558ff`；隔离 release 为
   `/opt/umanews-release-75294a4d-RBPATH-20260809/umanewsbot`，生产 image 为
   `sha256:1894484989084e61ced236eec93a30fd0b963b7ee946ad8ee8bd8e15357e413d`。部署后 revision
   label/runtime、Django check、migration 零计划、HTTP health、Celery 空队列和关闭开关均通过。
2. 部署前 custom-format dump 为
   `/opt/umanewsbot/backups/db/pre-release-b-path-staging-20260808T171241Z.dump`，`413003730`
   bytes、mode `0600`、TOC `1308`、SHA-256
   `67d087b977f016c6404adf059f0ae98115af8d4a76c2a11126ebf63bfc3569d6`；旧 image 回滚标签为
   `umanewsbot:rollback-pre-release-b-path-staging-20260808T171241Z`。
3. 新 census 持久目录为
   `/opt/umanewsbot/backups/release-state/release-b-census-path-staging-20260808T172022Z`，manifest
   SHA 为 `e626c8b48b5231890b0f1d4ac06f4fa22ee595fb9502d6aaead69f1169d070ec`。review overlay SHA 为
   `083610c50097dea568d8c948654f28fe38200806ca9bd3006ff558bcea6f5883`。
4. 新 reviewed 目录为
   `/opt/umanewsbot/backups/release-state/release-b-reviewed-path-staging-20260808T172107Z`，manifest
   SHA 为 `89387fab38f4c2a435c3b009802907a6b9710547354b38f91c3057546f41e96b`，action scope SHA 为
   `d7052d4392c027522ffde7c14955c98a2bc4ebfa99714c8681237c0ab65900bd`；目录 `0700`、文件
   `0600`。14/177/12/12/12/165/12/2 静态审计及所有 collision=0 门禁通过。
5. 当前 receipt=0、批准范围 canonical link=0、active maintenance gate=0。未生成 approval 或
   maintenance evidence；取得绑定上述精确 SHA 的 G3 前，禁止 apply/verifier 和 2025
   `full_network`。旧 manifest `c9e9b222…1e4c64` 永久禁止重试。

## 2026-08-09 Release B 数据 apply 确定性 STOP 检查点

1. 执行 manifest `c9e9b222…1e4c64`、approval `245baaf3…a2420`、maintenance evidence
   `ba8711b2…dcc3b4` 均已冻结；写前 dump SHA 为 `91a38cf2…e17aa`。
2. apply 因 `uq_race_public_path_event_canonical` 在 path 轮转的瞬时中间态失败；错误发生在 receipt
   创建和 rollback artifact 生成前，外层事务已回滚。不得用手工 SQL、禁用 constraint、改 overlay
   顺序或直接重放命令绕过。
3. 安全恢复必须验证 receipt=0、active link=0、mismatch=81、原 action scope 不变、gate exited，
   再启动 worker/beat 并核验 Celery、writer census 与 healthz。本次这些条件全部成立。
4. 后续只允许发布“临时 path 全部 legacy”最小修复及轮转回归测试；重新部署后必须重新生成 census、
   reviewed manifest、approval、maintenance evidence 和写前备份。本次 artifact 不可直接重试。

## 2026-08-09 官方结果身份修复发布与新 census 检查点

1. PR `#77` 的 merge commit 为 `55d41b5f84f072e11862fa14213cecc027708719`；生产 release 目录为
   `/opt/umanews-release-55d41b5f-RBID-20260809/umanewsbot`，image 为
   `sha256:c9f0a89fbb3a28f135a0dd32546b609164b89d845c6181483eb553ddbd249ef4`。
2. 数据库恢复点
   `/opt/umanewsbot/backups/db/pre-release-b-identity-20260809T003400Z.dump` 为 `412641242` bytes、
   mode `0600`、TOC `1308`、SHA-256
   `629a5495010d564da6c8233e887becebdb08d7d31d73ea0503bb48cdd381de70`；旧 image 保留为
   `umanewsbot:rollback-pre-release-b-identity-20260809T003400Z`。
3. preflight 文件在
   `runtime/migration_history_repair/preflight/before.tYCLRdVx/preflight.json`；文件 SHA 与 JSON 内嵌
   canonical artifact SHA 是不同口径，发布绑定值必须使用内嵌
   `09262ebbdb2ffad4ca46112b19d972cf725754d4d6fae1156c946b5b5828f602`。
4. 新 census 持久目录为
   `/opt/umanewsbot/backups/release-state/release-b-census-official-identity-20260808T164124Z`，目录
   `0700`、文件 `0600`。manifest/census/review template/summary SHA 分别为
   `85978b9b…2a13`、`4902f3b8…4472`、`937c4cf3…0bc`、`41a1c116…2552`。
5. census 后仍保持历史写入、历史网络、race sync/live flags 为 false，claimed review 为 0。未取得
   绑定新 manifest 的 G3 前，禁止生成 approval、进入 maintenance、执行 apply/verifier 或启动 2025
   `full_network`。

## 2026-08-08 Release B 正式发布与 v2 census STOP 检查点

1. 过期 scheduled-review claim 必须先按冻结 before/停机证据/备份/独立 approval 的一次性事务收口；
   本次最终 `39/43/44/45/46/47/48 -> noop`，reason code 为 `stale_claim_reconciled`，after SHA 为
   `1e24890db5f744aa2381f7621daf51e38d5343c0944a6a65198e7f9a42ceeb8d`。禁止改用 scheduler 不认识的
   自定义终态，也禁止在 SQL commit 后才检查 after 路径。
2. 本次迁移恢复点为
   `/opt/umanewsbot/backups/db/pre-release-b-after-stale-reconcile-20260808T131400Z.dump`，精确
   `411796037:600`、TOC `1304`、SHA
   `1f6b276bc139377af93709f80cb8b64d6c026022789b2e1c6651adea582b8d1b`。回滚 image tag 为
   `umanewsbot:rollback-pre-release-b-after-stale-reconcile-20260808T131400Z`。
3. 正式 release 目录固定 `/opt/umanews-release-4e3ffa8d-MR3-20260808/umanewsbot`；handoff SHA
   `62300fbfdcc4c5ac16505067dad4fa5a68bfddcdb1e22e2ef90ceebdf51bb5f4`。worker drain 必须为唯一节点
   active/reserved/active_confirm 全 0。`0068/0069/0071` 已应用，当前 prod image 为
   `sha256:e2102ff87e465c4904b1db470ddfa3e3679dfe681bd63a405c6922954fe7afe1`。
4. v2 census 原始文件必须从 web 容器的非持久 `/app/runtime` 立即复制到宿主 mode `0700/0600`
   证据目录；本次持久目录为
   `/opt/umanewsbot/backups/release-state/release-b-census-v2-20260808T132000Z`。四个 SHA 见
   `docs/changes/repair-production-migration-history/production_census_v2_review_20260808.md`。
5. 本次 overlay gate 为确定性 STOP：12 个 duplicate boundary 的 official HKJC result URL、核心赛事、
   runner/result 相同，但完整 source refs 因相邻 TJCIS catalog 不同而 identity SHA 不同。不得标记
   `distinct` 绕过，也不得手工伪造 `equivalent`。在 duplicate equivalence 合同经代码修复、测试、
   独立 review、部署并重新生成 census 前，禁止 approval、maintenance、apply/verifier 和 2025
   `full_network`。

## 2026-08-08 migration history repair 只读审计检查点

生成或复核 reviewed-static baseline 时，唯一入口为：

```bash
python manage.py generate_migration_history_production_audit
```

该命令只支持 PostgreSQL，在 `REPEATABLE READ READ ONLY` 事务内复用 preflight 的
`collect_live_production_audit()`，stdout 为单行 canonical JSON。禁止再用 raw SQL tuple、手写字段
拼接或 nested FK list 生成 SHA。输出需经独立 review 后才能更新候选 image 内
`production_audit.json`；命令本身不修改该文件。当前版本必须为
`migration-history-repair-production-audit/v2` / `named-object-scalar-fk/v1`，并精确绑定 ID/FK 列表和
time bounds。缺项、多项、错序或版本漂移均停止，不能删除字段后继续。

2026-08-08 首次修复发布重试由旧 positional/nested-FK baseline 在任何停服和 migration 前阻断。
恢复后生产继续运行旧镜像 `sha256:b1fecc…341a`，recorder 为 `0067+0070`，内外 healthz 正常；新备份
`backups/db/pre-migration-repair-20260808T073557Z.dump` 为 `411053136` bytes、mode `0600`、TOC
`1297`、SHA-256 `e12ee97cfd1db3a67571e2e525cea8bb050d939ef26450d12b0d5acd8fc2cb6d`。
新 generator 在只读容器中于 `2026-08-08T11:41:07.525084Z` 输出 v2 payload；此证据仍需 commit、
独立 review 与重新发布门禁，不能直接复用失败 handoff 或绕过 preflight。

1. 生产 recorder 为 `0067` 与 `0070`；`0070` applied at
   `2026-08-02 05:07:24.615789+00`，receipt 表随后写入 7 条正式记录。
2. receipt 表的 11 列、PK、approved SHA unique、operation-log unique/FK、varchar pattern index 与
   owned sequence 均存在；7 条 receipt 的 operation log 与 JSON 类型校验通过。
3. `stable_raceeventfieldchange` 不含 `0068` 的 11 个新增字段/observation FK；`0069` 的
   `race_field_change_decision_valid`、`stable_race_field_change_append_only` 与
   `stable_reject_race_field_change_mutation()` 均不存在。
4. 当前候选修复只允许把 graph 恢复为 `0067→0068→0069→0071` 与
   `0067→0070→0071`。禁止删除/插入 recorder、`--fake`、重建非空 receipt 表或跳过精确 preflight。
5. 实现后的候选 preflight 必须同时验证 recorder/schema/forward plan 与 receipt row digest；允许的
   发布前 leaf set 仅为 `{0070}`、`{0068,0070}`、`{0069,0070}`，发布后仅 `{0071}`。
6. 受审 baseline 完整值位于
   `docs/changes/repair-production-migration-history/production_audit.json`。第一次 preflight 必须
   在 repair leaf 精确比较 expected DB identity 与数据 baseline，并生成 mode `0600` no-clobber artifact；`{0071}` B-to-B
   只冻结本次 live baseline。服务全部停止后、migration 前必须消费同一路径/SHA再次核验。
   restricted marker 必须由 Python canonical verifier 校验 owner/mode/parent、candidate/artifact 与 live
   初始 `{0070}`、candidate/action/original artifact/DB identity，不能用 shell grep 解析。关闭态 verifier
   后、任何 migration 前必须在同一锁和 one-shot 内 durable 写入 intent，紧接着 migrate；禁止依赖
   migrate 失败后事后补写。partial-state 只能在固定旧镜像兼容 smoke 通过后进入受限恢复。
   普通 deploy 不硬编码 `{0070}`；manual 与 resume 必须在自己的新锁下生成 fresh handoff。resume
   旧 artifact 只作 marker provenance。normal deploy 的同镜像 flow 可在 migrate 后直接完成 marker；
   rollback 必须依次由 pinned control image 执行 `migrate-verify`、exact target image 执行 collectstatic、
   pinned control image 执行 `complete-intent`，之后才允许 health/startup。target collectstatic 前后都要
   证明 tag 的 image ID 等于 artifact candidate ID；失败保留 active marker/control-state 供精确续跑。
   partial leaf 对普通 deploy/manual/rollback 必须 fail closed；仅 marker-bound `forward-resume` 可进入。
   active marker 遇到 exact `{0071}` 仍阻断普通 deploy/manual/rollback，只允许同 candidate 的
   `forward-resume` 幂等完成 transition，不得把任意 final state 视为安全。
   `0069` decision check 必须是 PostgreSQL 实际生成的
   `decision = '' OR decision = ANY(ARRAY[四个业务值])` 精确完整表达式；只允许括号、空白与 type cast
   表示差异，额外值、缺值、错列或逻辑改变都 fail closed。同名 guard function 必须只有一个无参数
   signature，任何 overload 都 fail closed。
   production audit 必须以唯一最小文件复制到候选 image 的
   `/app/docs/changes/repair-production-migration-history/production_audit.json`，与代码 `AUDIT_PATH`
   一致；禁止复制整个 docs。`0071` 两个 partial unique predicate 必须完整 canonical 等值，不能
   以字段 substring 通过 `AND false`、`OR true` 或换列逻辑。
   rollback 取得 deployment lock 后必须在任何 fetch/checkout/build/image 变化前检查 canonical
   marker path、owner、mode 与 no-symlink；存在或 trust 异常都停止，且不得改变 marker provenance。
   rollback 必须从本次 fresh artifact 提取并导出 DB identity。
   completed transition 使用固定可信 parent 内的 active→transition→completed 两次原子 rename，持续
   持有首次认证 fd 并逐边界核对 dev/inode/owner/mode；禁止 path unlink。active+transition 冲突、
   伪造 slot 或 replacement 均停止并保留现场；第一次 rename 后从 transition 续跑，第二次后以绑定
   SHA 的 completed receipt 幂等确认。两次 rename 必须分别使用 Linux
   `renameat2(RENAME_NOREPLACE)` 或 macOS `renameatx_np(RENAME_EXCL)`；不可用或 destination 并发出现
   都 fail closed 且不覆盖任一文件。required/not-required mode 必须来自同一受信任 handoff artifact；
   ensure 输出的 device/inode 必须原样传给 completion，required marker 丢失或同内容换 inode 均不得
   启动服务。final forward-resume 仍使用 reviewed-static 7-row audit。
   attempt mode 的启用信号是精确 artifact 内实际存在的 SHA-bound 字段，不是进程环境中碰巧残留的
   同名变量。旧/non-Release-B retry 或 artifact 尚不存在时必须局部清理陈旧值并保持原 release、
   race-live frozen intent 与 `resume_stopped_release` 语义；artifact required 与环境冲突时在停服务前拒绝。
   B→B rollback 必须在 checkout 前保存当前 v2 control scripts/image。目标 build 后先另存 target tag，
   `umanewsbot:prod` 保持目标 image；control one-shot 只能通过 mode `0400` Compose override 绑定 immutable
   control image ID，禁止把 control image retag 为 production。保存脚本生成绑定 target commit/image ID/
   DB identity/lock 的 artifact；目标 pre-v2 helper 不得生成或消费 artifact。one-shot 前写 mode `0600`
   control-state，失败后仅精确 forward-resume 可复核同一 control/target/compose 并重试，成功后转
   completed。`resume_stopped_release.sh` 遇 active/transition 必须在任何服务探测/启动前拒绝并提示改走
   forward-resume；active control-state 同样阻断，completed receipt/state 不阻断。
   若失败 handoff 的 `recovery_intent_mode=not-required`，禁止创建伪 marker；只能使用失败日志给出的
   `$CONTROL_DIR/resume-rollback-release.sh`，并显式传入原 target commit/image。该入口验证 state mode/
   owner、初始 artifact/lock-token SHA、HEAD、prod/target/control image、脚本与 override；错误 target
   零服务动作，重试失败保留 state，成功后转 completed。`required` 仍只走 migration-history
   forward-resume。通用 B→B wrapper 对 `SCHEMA_PREFLIGHT_DIRECTION=reverse` 在 Compose 前拒绝；
   reverse migration 必须走另行审核的跨 schema procedure。
   control-state 必须为 `rollback-control-state/v1` canonical JSON，`state_sha256` 覆盖 preflight、
   application release、release tasks、专用 resume、state creator 与 Compose override 的 path/mode/bytes
   SHA。resume 在取 lock 前及 lock 内分别以 nofollow parent fd/openat/fstat 验证；任何文件同 mode
   内容变化、symlink/path replacement、缺项/多项或 state SHA 漂移都必须在 Git/Docker/Compose 前退出。
   completed receipt 文件名必须为
   `restricted-recovery-control.completed.<target-oid>.<initiating-artifact-sha>.<state-sha>.json`。禁止退回
   target-only 命名。completion 用 no-clobber hard-link 发布、fsync parent、删除 active、再次 fsync；
   active+completed 仅同 inode/state 可收口，completed-only 同 attempt 重放不得改变 inode/bytes。
   retry 命令必须同时提供 `EXPECTED_ROLLBACK_INITIATING_ARTIFACT_SHA256` 与
   `EXPECTED_ROLLBACK_CONTROL_STATE_SHA256`；入口只接受 exact attempt receipt，不按 target glob。
6. 普通 deploy/rollback/manual-release 在取得 deployment lock 后先运行
   `python3 deploy/ensure_migration_history_repair_runtime.py`，再运行 marker gate。初始化器以 nofollow
   dirfd 创建缺失 repair root 为 `0700` 并 lstat/fstat 复验。`resume_stopped_release.sh` 禁止创建；
   repair root 缺失、symlink、owner 非当前用户或 mode 非 `0700` 时，即使目录无 child 也必须停止且
   不启动任何服务。
7. `HISTORICAL_RUNNER_INITIAL_INSTALL=true` 仅用于已有健康 web/db/redis 上、runner trace/table/role
   不存在且 `django_migrations` 不含 `stable.0070/0071` 的首次纳管。该精确分支执行原受审
   migrate→collectstatic one-shot；不得创建 Release B handoff。未设置 flag 的 pre-0070 state 仍必须在
   v2 preflight 停止；0070 repair 不得设置该 flag 绕过。
8. 旧 image partial-state smoke 必须为 web/worker/beat 创建一次性非超级只读 role：撤销应用 schema
   DML、CREATE、database TEMP 与非系统函数执行，设置 role default read-only。启动服务前必须由旧
   image 自身连接并打印/断言 exact `current_user` 与 `transaction_read_only=on`，再在 savepoint 中向
   `django_migrations` INSERT 并证明数据库拒绝。管理员使用 `BEGIN READ ONLY` 对 recorder 与关键全行
   digest 做前后复核；不得以 `pg_stat_user_tables` 或五表 count 作为零写证明。三个容器须持续 running，
   日志不得出现 write rejection、traceback、ERROR 或 CRITICAL。
9. Release B schema check 必须先完成 recorder + pg_catalog object/column/type contract。输出
   `receipt_audit_safe=false` 时不得执行 live receipt audit；检查 JSON 中 `drift_paths`，例如
   `0070.table_presence`、`0070.columns`、`0070.column_semantics`。CLI 非零应为 JSON 后的
   `CommandError`。若是连接断开/timeout/`OperationalError`，按数据库运行故障处理，不得改写成 schema
   drift 或继续发布。
   新 lock/new artifact 可再次回滚同一 target，active canonical state 仍阻断并发 attempt。
7. 最终实现与独立审查状态为 `VERIFIED`；精确旧生产镜像在 PostgreSQL 16 的
   `{0068,0070}` 与 `{0069,0070}` 两态 compatibility gate 均已 GREEN。该技术结论不等于发布授权；
   截至本记录检查点仍不得直接重试 Release B、v2 census、回填或 full-network。
8. 通用 `rollback*.sh` 在 checkout/build 前必须运行
   `deploy/verify_rollback_target_migration.py --target-oid <40-hex-oid>`。该门禁用 `git show` 分别读取
   目标 `0071` 与 `0072` 原始内容，并与 `deploy/reviewed_release_b_rollback_migrations.json` 中两份
   required migration 的 exact SHA/dependencies 同时匹配；`0071` 可为受审 legacy/repaired 版本之一，
   `0072` 必须为受审终态。文件仅存在、placeholder、改依赖或改 operation 都不合格。新增兼容版本
   必须单独审核完整 migration bytes、最终 schema 兼容性与 rationale 后才能更新 allowlist。
9. PostgreSQL preflight 对 receipt 表要求 constraint/index 完整集合精确相等；看到
   `0070.constraint_set` 或 `0070.index_set` 必须作为确定性 schema drift 停止。不得删除不明对象后
   直接续跑；先核对对象来源和预期 migration。该查询限定四张显式用户表，不扫描 system/TOAST。
10. rollback split phase 中，control run 必须携带 `RELEASE_TASK_PHASE=migrate-verify` 或
    `complete-intent`；二者均不得调用 collectstatic。中间 target run 必须使用仅覆盖 `web.image` 的
    临时 Compose override 执行 `python manage.py collectstatic --noinput`，从而复用基础 Compose 的 static
    volume。该命令失败、目标 tag ID 不符或完成阶段失败时禁止任何 `up`；按 control-state 指示使用
    markerless 专用 retry 或 migration-history forward-resume，不要手工补跑 control-image collectstatic。

## 2026-08-08 Release B 首次生产尝试失败与恢复检查点

1. 发布代码已合并为 `main@ba9c0f00`，但生产仍运行旧镜像 `sha256:b1fecc…341a`；不得把 PR
   merge 表述为部署成功。
2. 前置恢复点为
   `backups/db/pre-release-b-prereq-832cc074-20260808T020900Z.dump`，大小 `408607125`、
   mode `0600`、TOC `1304`、SHA-256 `e0cd6899…5cab`；旧 image tag 为
   `umanewsbot:rollback-pre-release-b-prereq-20260808T020900Z`。
3. 生产 `django_migrations` 的精确异常是：`0067_historical_calendar_release_a` 已 applied，
   `0070_horse_identity_evidence_commit_receipt` 也已 applied，但 `0068`、`0069` 不存在。
   当前主线中 `0070` 依赖 `0069`，因此任何知道当前 graph 的 Django release task 都会在迁移前
   抛出 `InconsistentMigrationHistory`。
4. 禁止直接删除 `0070` 记录、手工插入 `0068/0069`、使用 `--fake`、改 migration dependency
   或恢复整库备份来猜测修复。下一任务必须先只读证明 `0068/0069/0070` 对应 schema/table/index/
   constraint/receipt 的真实存在状态，再设计精确 forward repair 与 rollback。
5. 本次失败后旧 image 已重新 tag 为 `umanewsbot:prod`，受审 resume 入口已恢复
   web/worker/beat/nginx，内外 HTTP healthz 正常。release lock 不存在；不可信 race-live intent
   只记录并跳过，不得人工改内容后恢复。
6. migration history 修复完成并取得新授权前，Release B preflight、`0071`、v2 census/overlay/
   maintenance/apply/verifier 和 2025 full-network workflow 全部保持停止。重试必须从新的数据库
   备份、候选 image 和完整 preflight 开始，不能复用本次半途状态。

## 2026-08-01 历史赛历 Release B 候选发布门禁

> 以下是本地候选的未来操作合同，不是部署授权。当前未 commit/push/PR/deploy，也未运行生产
> v2 census 或数据 apply。

2026-08-09 当前发布迁移终态固定为 `0072_add_extended_racing_regions`，直接依赖
`0071_historical_calendar_release_b`；`0071` 继续作为受审的单向中间态。候选 preflight 只接受
`0070`、`0071` 或 `0072` 这三个明确阶段，正式完成与 B→B rollback 的目标 image 必须以 `0072`
为精确 leaf；wrapper 列出中间态仅用于受保护的 forward resume，不把它们视为最终成功。

1. deploy 前必须取得并人工核对目标生产数据库 identity SHA，导出
   `EXPECTED_PRODUCTION_DB_IDENTITY_SHA256=<64位小写sha256>`；缺失或格式错误时停服务前失败。
2. deploy 构建同时带 OCI revision label 和 runtime `UMANEWS_RELEASE_COMMIT` 的候选 image，随后
   运行 `run_historical_calendar_release_b_preflight.sh`。commit、image ID、DB identity、
   `0070/0071/0072` 中唯一受支持的 applied leaf 和 forward 冲突必须全部通过，之后才调用 release
   orchestration。leaf
   必须从目标库 `django_migrations` 的实际 applied 状态计算，不得使用候选镜像 migration graph
   冒充目标数据库状态。目标库存在任何候选 graph 不认识的 `stable.*` applied node 时必须输出
   `migration_graph_known=false` 和精确 node 列表并失败；不得把未知 node 过滤后继续计算“合法” leaf。
3. 通用 `rollback*.sh` 只接受以 `0072` 为精确 leaf 且同时通过 `0071`/`0072` 双 migration 字节合同
   的目标，即只执行当前 schema 的 B→B rollback；pre-0072 目标在 checkout/停服务前 fail closed。
   B→B checkout 并构建目标 image 后，以目标 commit/image
   运行 forward preflight，再进入 release orchestration；不得运行 reverse preflight，因为合法的
   B-only 数据形态本就可能不兼容旧约束。回到 pre-0072 必须另行审批停服、reverse preflight、
   反向 migration 与旧 image 恢复流程，不得根据 receipt 缺失或“尚未 apply”猜测兼容。
4. Release B 关闭态部署按顺序应用至 `0072` 并验证 schema/code；不得调用 `--prepare-v2`、
   `--apply-v2` 或启用 historical write/network flags。81 mismatch 保持不变是预期。
5. 后续另行授权的数据阶段依次为 `--prepare-v2`、人工 overlay、`--prepare-reviewed-v2`、独立 v2
   approval、maintenance/live gate、`--apply-v2`、`--verify-v2`。回滚只接受同 receipt 的
   no-replace artifact 和 `--rollback-v2`，post-state 漂移时停止。

## 2026-07-31 历史赛事赛历完整性 Release A 未来发布门禁

> 本节是仓库候选的未来发布门禁，不是部署授权或生产执行记录。当前没有 commit、push、PR、
> 部署、生产只读 census 或生产写入授权。

1. Release A 候选必须固定到经独立代码 review 通过的精确 commit/image；migration graph
   只允许新增 `0067_historical_calendar_release_a.py`。若出现 Release B series/edition
   约束或 Release C non-null/自然年 check migration，立即停止，不得合并发布。
2. 发布前分别验证标准 RDS `docker-compose.prod.yml` 与低成本本机 PostgreSQL
   `docker-compose.prod.lowcost.yml` 的 config。两种模式都必须保存 schema/数据备份、
   当前 commit/image、migration leaf/plan 和回滚 image；不得改变现有数据库模式或把一种
   Compose 的验证冒充另一种。
3. 运行聚焦 Django/collector、Django check、`makemigrations --check --dry-run`、migration
   graph/漂移和 `git diff --check`。当前完整 `stable` 基线为
   `3989 tests / 25 failures / 54 errors / 72 skipped`，包含测试子进程缺少 `python` PATH、
   Redis 不可达、时效测试、旧 CSV 门禁和 migration-owner guard；发布前必须重新冻结并比较
   失败集合，不能报告“全绿”，也不能用该基线豁免本 scope 新失败。
4. Release A 只部署 nullable `edition_year`、canonical path registry 回填、repair receipt、
   target supersession 和兼容代码。migration 后核对 `0067` 单一 leaf、pending plan 为零、
   registry 每个既有 event 恰有一个 canonical path，并验证历史重点、超过 40 条的
   `year/q` 前后分页、legacy 301、canonical sitemap 与当前年运营重点回归。
5. Release A 部署不得自动运行 `repair_historical_race_calendar_integrity`，不得生成生产
   census、创建 legacy 修复路径、改香港/其他地区 event/target，也不得启动联网 collector。
   生产全地区 prepare 是后续独立只读阶段，仍需明确授权和全 scope artifact SHA。
6. 若 Release A 应用代码异常，优先恢复冻结旧 image/commit；nullable 字段、registry 和 receipt
   表保留，不做自动反向删除。若 `0067` 数据回填或 schema 本身异常，停止写入并由人工选择经
   审核的反向 migration 或部署前备份恢复，不能只 checkout 旧代码猜测兼容。
7. 生产 census 完成且冲突清零后，Release B 才可作为独立 change 创建、review、授权和发布；
   数据 apply 还需精确 approval/actor/action scope、maintenance/freeze 与备份。独立 verifier
   通过后才允许创建 Release C。每一阶段分别记录实际 commit/image/schema/artifact/receipt，
   前一阶段成功不自动授权后一阶段。
8. 后续获批的数据 apply/rollback 必须先用
   `repair_historical_race_calendar_integrity --enter-maintenance` 创建绑定精确
   manifest SHA、action scope SHA 和 actor 的数据库 active gate，再提交相同 identity 的
   apply/rollback；JSON maintenance evidence 不能替代 live gate。完成独立 verifier 后才可用
   `--exit-maintenance` 退出。gate 不匹配、已退出或存在第二个 active gate 时一律停止。
9. 发布前必须确认年份写入校验和 repair classifier 都调用
   `race_event_years.validate_authority_url()`；不得恢复 classifier 私有 URL 解析。用合法 HTTPS
   path/query 与 fragment、HTTP、credentials、非 URL 样本复验：非法证据必须保持
   manual/block，不能进入 action。当前 `76/76` 只属于本地聚焦证据，仍需绑定新 reviewer
   fingerprint 后才可用于发布判断。

## 2026-07-31 年度参赛马 workflow 的 443 诊断与恢复

1. 若 checkpoint 停在 `https://umafans.run/sitemap.xml`，先区分“宿主映射 443”和
   “Nginx 已监听 TLS”：同时核对宿主 listener、Compose publish、容器内 `nginx -T`、
   证书 subject/issuer/dates，以及 HTTP/HTTPS 的真实请求结果。
2. 本次生产证据为宿主 80/443 均由 Docker publish，但容器生效配置只有 `listen 80`；
   HTTP sitemap 为 200，HTTPS 握手 EOF。现有 IP 自签名证书不能作为域名 TLS 完成证据。
3. 修复候选将年度研究 workflow 的 races base URL 固定为 `http://umafans.run/`。
   发布后首次 full-network 必须不传 source 三元组，从 fresh checkpoint 开始；此前 6 次
   HTTPS run 的 artifact 只保留作失败证据，禁止改写 queue、ledger 或 progress 后续跑。
   如传地区 manifest，其中每个 exact race URL 也必须是当前 HTTP sitemap URL；HTTPS
   manifest 与 HTTP run identity 不同，必须在运行前以来源证据重新生成并审核 SHA。
4. fresh run 仍遵守最多 6 次有界 workflow run、每次精确 checkpoint 的既有操作边界。
   暂时网络错误可从同 scheme、同代码、同年份和同 manifest 的精确 artifact 恢复；
   identity/config/schema/4xx 等确定性错误立即停止并一次性报告。
5. 本轮没有部署应用、改 Nginx、启用 443、替换证书或写生产数据。若另行推进 HTTPS，
   必须走独立证书与 Nginx 发布方案、回滚和域名 TLS 验收，不能与研究采集续跑混合。
6. 发布证据：修复提交 `1fd83de4` 经 PR `#53` 合并为 `main@cd42cb4d`；默认离线
   dispatch `30575216646` success，tests job `17s`。artifact
   `30575216646-1-synthetic-checkpoint-0` 为 `12959` bytes，digest
   `sha256:3ea2ad2795db806549128033d839e58e5a027b78604539056abedef8029296f8`。
   本次 `full_network=false`，因此 races/profiles/merge_profiles/finalize 网络 jobs 均按设计
   skipped；这只证明离线部署成功，不是 2025 正式数据 artifact。

## 2026-07-30 race-live P0 已完成关闭态发布与五轮观察

1. stdout final fix 只把 machine snapshot 改为 `manage.py shell --no-imports -c`，
   parser 不放宽；同一 reviewer 限定复审为 `APPROVED`。用户针对冻结指纹授权后，
   `INDEX_TRANSITION_OK`，commit `24a49c2a` 经 PR `#47` 合并为
   `main@be1c89bf`，生产仓库 fast-forward 到该版本；既有 `12` 个 deploy 脚本
   mode-only 差异原样保留。
2. 生产重新完整执行 `prepare`：普通 worker 在 `active=0 / reserved=0` 后停止，
   historical runner preflight 为 `migration_safe`，Django check 与两次 migration plan
   `0/0` 通过。rollback tag
   `umanewsbot:rollback-race-live-p0-20260730T043615Z` 指向上一候选
   `sha256:17562c52...acea7`；最终候选为 `sha256:c3197503...b5f5`，脚本返回
   `CANDIDATE_READY`。
3. `start-beat` 基线为
   `celery=0 / race_live=6574 / selector=0 / monitor=6574`。五轮 `celery` 为
   `36/35/30/28/30`；`race_live=6574 / selector=0 / monitor=6574` 每轮不变。
   每轮三应用 image 一致、普通 worker 隔离与 ping 正常、race-live worker 未运行、
   healthz 正常，Beat 日志不含两个关闭态目标。
4. 脚本外终验：生产 HEAD=`be1c89bf`，web/worker/beat 均使用
   `sha256:c3197503...b5f5`；Beat running，`race_live_worker=Created`，
   flags/schedule closed，队列为 `celery=23 / race_live=6574 / selector=0 /
   monitor=6574`，最近十分钟目标 Beat 日志计数 `0`。容器内、本机和两个正式 HTTP 域名
   healthz 均为 `200`；OneBot running，最近 15 分钟无 OOM。
5. 临时 `/swapfile-umanews-p0-20260730` 仍启用，总量/空闲量均为
   `2097148 KiB`，终验 `MemAvailable=1576148 KiB`；swap 未移除。全程没有清理、
   迁移、消费或重放历史 `race_live=6574` 积压。

## 2026-07-30 race-live P0 部分部署停在安全检查点，修复待复审/重新授权

> 当前状态：初始实现 `611c6aab` 已经 PR `#46` 合并为 `main@7cd144ab`，生产已完成
> `prepare`，但 `start-beat` 在真正启动 Beat 前因 machine snapshot stdout 被 Django
> auto-import banner 污染而 fail closed。Beat 仍 exited，发布未完成。本地 final fix 尚未
> review、提交、合并或部署；必须复用同一 reviewer 限定复审并重新取得发布授权。

本 P0 针对仓库现有低成本
`docker-compose.prod.lowcost.yml` 拓扑提供唯一验收入口：

```bash
cd /opt/umanewsbot
./deploy/deploy_race_live_p0_closed.sh prepare
# 保存并审核 CANDIDATE_READY 证据，确认 Beat 仍停止后，才可进入下一阶段
./deploy/deploy_race_live_p0_closed.sh start-beat
```

该脚本不替代标准 RDS 的 `docker-compose.prod.yml` 部署模式；标准 RDS 与低成本本机
PostgreSQL 两种仓库模式继续保留。若实际生产目标不是上述低成本拓扑，必须停止并另行适配、
测试和 review，不得猜测脚本可以跨 Compose 模式使用。

### 本次生产运行事实

1. 只读预检：Compose `5.1.2`；scheduler/monitor/runner 为
   `false/false/disabled`；`race_live_worker=Created`；首次
   active/reserved/scheduled 均为 `0`，`celery=0`。`race_live` 从 `6055` 增至
   prepare 前 `6574`，均为 `monitor_race_live_sla_task`。
2. 首次资源门禁以 `MemAvailable=867284 KiB / SwapFree=0 KiB` 返回 NO-GO。经用户额外
   授权，创建并启用 `/swapfile-umanews-p0-20260730`（`2 GiB`、mode `0600`），没有写入
   `/etc/fstab`；普通 worker 在空闲时优雅重启，临时停止的 OneBot 已恢复 running。
3. 生产仓库从 `4221affa` fast-forward 到 `7cd144ab`；原有 `12` 个 deploy 脚本
   mode-only dirty 差异保留。
4. `prepare` 成功：drain active `2→0`；旧 image
   `sha256:7d730634...8774` 的 rollback tag 为
   `umanewsbot:rollback-race-live-p0-20260730T030255Z`；候选 image 为
   `sha256:17562c52...acea7`。两次 migration plan `0`，候选 settings closed，
   web/worker/nginx 和内外 healthz `200`；Beat exited，race-live worker 仍为 `Created`。
5. `start-beat` 的启动前 queue snapshot 收到
   `105 objects imported automatically (use -v 2 for details).`，严格 parser 拒绝后
   非零退出；没有执行 `up beat`，五轮观察未开始。失败后 OneBot running、Beat exited，
   `race_live=6574`，未清理、迁移或消费队列。

### 当前续跑门禁

- 生产当前 candidate image 不含 stdout final fix，禁止直接再次运行 `start-beat`；
- 禁止在生产热补丁脚本，禁止手工 `up beat`；
- 本地 fix 必须先由同一 reviewer session 限定复审，再针对已审内容重新取得发布授权；
- 授权后生产必须拉取已审 final fix，重新执行 `prepare` 构建并验证精确最终 image；不能复用
  `sha256:17562c52...acea7` 冒充最终候选；
- 新 `prepare` 成功并保存证据后，才运行 `start-beat`，完成全部五轮后验才可宣告发布完成；
- `race_live=6574` 是保留的历史 monitor 积压，不得为续跑而清空、迁移或消费。

临时 swap 不是仓库永久配置，也未写 fstab。后续移除必须单独授权，并在无构建/重启负载时
先确认内存足以承受 `swapoff`；只有 `swapoff /swapfile-umanews-p0-20260730` 成功并验证
`swapon` 已无该条目后，才可删除该文件。不得把重启后未自动启用解释为文件已经删除。

### 绝对禁止

- 未取得最新成功代码 review 后的当前任务发布授权前，禁止运行上述生产命令；
- 禁止原样运行 `deploy_lowcost.sh` 发布本 P0；这不是对其他常规低成本发布的全局禁用；
- 禁止启用 scheduler、monitor 或 runner，禁止启动 `race_live_worker`；
- 禁止清空、删除、迁移、消费或重放 `celery`/`race_live` 历史消息；
- 禁止用脚本直接执行 `manage.py migrate --noinput`；候选待应用 migration 必须精确为
  `0`；
- 禁止在 `/opt/umanewsbot` 生产根启用 `RACE_LIVE_P0_TEST_MODE`、测试 sentinel、fake path
  或 `P0_FAKE_*` 覆盖；脚本会拒绝这类输入。
- 禁止跳过 final fix 的限定复审和新发布授权，禁止直接热补丁或手工启动 Beat。

### `prepare` 门禁与状态

1. `PRE_STOP_PREFLIGHT` 只读核对 `.env` 中三个值精确为
   `RACE_LIVE_SCHEDULER_ENABLED=false`、
   `RACE_LIVE_MONITOR_ENABLED=false`、
   `RACE_LIVE_RUNNER_MODE=disabled`，并核对当前 image、Compose/Beat 状态、仓库与 Docker
   数据目录磁盘、最近 15 分钟 OOM。任一项未知即 no-go。
2. 资源门禁要求仓库和 Docker 数据目录各至少 `6 GiB` 可用；要求
   `MemAvailable >= 1536 MiB`，且当 `SwapFree < 1024 MiB` 时要求
   `MemAvailable >= 2048 MiB`。停普通 worker 后、构建前必须再次通过资源门禁。
3. 停止 Beat 后必须实际确认其为 stopped，才进入 `BEAT_STOPPED`。对进入命令时仍为
   running 的 Beat，stop 命令失败或 no-op 都不能被解释为成功；pre-stop 失败不调用
   build/up，并报告 Beat 进入命令前的真实 running/stopped/unknown 状态没有被本命令改变。
   Compose 状态为 `restarting/paused/unknown` 或无法唯一解析时不属于停止证据。
4. Beat 停止后才允许 drain 并停止普通 worker。stop 命令返回后先复核实际状态；若命令非零
   但 worker 已经停止，必须先记录 worker 已停，再由失败 trap 恢复普通 worker并保持 Beat
   停止。模糊状态不得继续构建。确认后才可建立 rollback image tag、运行历史 runner
   preflight 和受控构建 web。P0 脚本不执行 nginx pull，不改变当前本地 nginx image。
5. 候选 image 先通过 Django check，并使用 migration graph 只读取得待应用数量；该数量在
   候选 web 启动前必须两次精确为 `0`。查询失败或非零时禁止启动候选 web；脚本自身不执行
   migrate，现有 `start-web.sh` 的 migrate 调用只能在第二次零计划确认后作为 schema no-op
   发生。
6. 候选容器必须重新解析三个关闭态值和 `CELERY_BEAT_SCHEDULE`，确认
   `select-due-race-live-events`、`monitor-race-live-sla` 均不存在；然后只启动并验证
   web、普通 worker和 nginx；nginx 使用当前本地 image
   `--force-recreate nginx` 并通过 healthz。普通 worker 隔离必须从 PID 1 的
   `/proc/1/cmdline` 证明 queue 选项只出现一次且精确为 `--queues=celery`；逗号多队列、
   前缀近似、重复 queue 参数或分离式多队列值均 no-go。
7. 成功状态为 `CANDIDATE_READY`：Beat 与 `race_live_worker` 均继续停止。进入
   `BEAT_STOPPED` 后的任一失败都必须再次确认 Beat 未运行；候选 web/普通 worker 不健康时
   只允许用本窗口 rollback tag 恢复旧 web/普通 worker，不自动启动 Beat。

### `start-beat` 门禁与验证

1. 再次验证三个关闭态值、候选 schedule 不含两个目标 entry、web/普通 worker 健康、
   `race_live_worker` 明确停止，并复核普通 worker PID 1 queue 唯一精确；
2. 使用 `manage.py shell --no-imports -c` 保存两个队列长度及 selector/monitor task
   计数基线；stdout 必须只含 machine snapshot，格式不可确认即在 `up beat` 前 fail closed，
   parser 不跳过或容忍任何 banner；
3. 只有全部通过后才单独执行 Beat 的 `up -d --no-deps`，并核对 Beat 与 web/普通 worker
   使用相同 image。启动后连续执行五轮后验；
   每轮复核 Beat/web/普通 worker 为 running、race-live worker 仍明确停止、三服务 image
   与候选一致、healthz/ping 和 PID 1 queue 正常，保存队列长度与目标 task 计数，并检查从
   本次启动时间起的 Beat 日志不含两个目标 entry/task；
4. 任一轮服务状态、镜像、health、worker queue、目标 task 计数或 Beat 日志异常，都立即
   停止并复核 Beat 为 stopped，保留已完成轮次证据；仍不清队列、不启动
   `race_live_worker`。只有五轮全部通过才可成功返回。

### 初始 review、部分部署与 final fix 本地证据

首次 review 的五项 actionable finding 已分别落实到当前候选实现：

1. 普通 worker 部分停止后不会因 stop 非零遗漏恢复；
2. `restarting/paused/unknown` 不会被当作 worker 已停止；
3. 普通 worker 以 PID 1 参数验证唯一精确 `--queues=celery`；
4. start-beat 内置连续五轮后验，任一轮异常立即停止 Beat；
5. 完整 stable 与同
   `HEAD=78719a467a2eceb57572b484a906cb78761badf8` 干净 worktree 比较。

同一 reviewer 限定复审 session `019faecf-f5fe-7900-be8d-95998bcb6b42` 已确认上述五项
全部关闭，但新增 P1：`pull nginx` 会改变可变镜像，而现有 rollback 没有 nginx 镜像级
恢复，故 verdict 为 `REVISE`。该 P1 已按真实 RED/GREEN 最小修复：脚本不再 pull nginx，
不改变当前本地 nginx image；启动阶段仍以该 image `--force-recreate nginx` 并执行
healthz 检查。

初始修复已形成 commit `611c6aab` 并通过 PR `#46` 合并到 `main@7cd144ab`。生产
`prepare` 成功，但 `start-beat` 在启动 Beat 前暴露 Django auto-import banner 污染 queue
snapshot stdout；严格 parser 正确 fail closed。

本地 final fix 只把该 machine snapshot 调用改为
`manage.py shell --no-imports -c`，没有放宽 parser。当前已复跑四组聚焦：
`stable.test_race_live_sla_monitor`、`RaceLiveCeleryIsolationTests`、
`RaceLiveWorkerDeploymentContractTests` 和
`stable.test_race_live_p0_deployment_contract`，结果为
`64/64 / 57.693s / exit 0`，其中部署合同
`33/33 / 56.236s / exit 0`。Django check 为 exit `0`；
`makemigrations --check --dry-run` 输出 `No changes detected`；`sh -n` 和
`git diff --check` 均为 exit `0`。这些证据不能冒充 review 通过或发布授权。完整 stable
候选的既有基线为
`3830 tests / 216.643s / 26 failures / 148 errors / 72 skipped / exit 1`，基线为
`3790 tests / 167.124s / 26 failures / 148 errors / 72 skipped / exit 1`；原始唯一
headings 均 `174`、规范化失败方法均 `153`，双向差集均 `0`。该证据表示本 scope 新增失败
标识为 `0`，不表示完整 suite 全绿。逐行规范化清单见
`docs/changes/harden-celery-p0-admission/full_stable_failure_baseline.txt`。

### 回滚

本 change 无模型、migration 或业务数据变化。回滚候选代码前先停止并确认 Beat 已停，再使用
`prepare` 保存的旧 image/tag 恢复 web 与普通 worker，验证 healthz 和 worker 只消费
`celery`。P0 不 pull 或替换 nginx image，因此 nginx 继续使用进入窗口时的本地 image，
失败恢复不依赖不存在的 nginx 镜像级 rollback。旧代码会恢复无条件周期投递，所以回滚后
Beat 必须保持停止，直到恢复本 P0 候选或存在另一个经审核的生产者止血方案；三个 race-live
flags 和 `race_live_worker` 继续关闭，数据库和历史队列均不恢复、不改写。

本次生产 rollback tag 为
`umanewsbot:rollback-race-live-p0-20260730T030255Z`（旧 image
`sha256:7d730634...8774`）。当前 Beat 已退出，因此若在 final fix 发布前决定回退应用，
必须保持 Beat stopped，使用该 tag 恢复 web/普通 worker并重新验证内外 healthz；
`race_live=6574` 不清理。临时 swap 的停用/删除是独立资源维护动作，不与应用 rollback
捆绑，仍需单独授权和上述 `swapoff` 验证。

本节记录的是仓库预期，不是生产执行回执。真实发布完成或失败后，必须按 evidence-only
规则追加生产 SHA、image、rollback tag、阶段、资源、migration plan、schedule、队列计数、
health 和实际回滚结果，并复用同一代码 reviewer 会话审核证据 patch。

## 2026-07-29 赛事日历默认日期窗口生产部署记录

1. PR `#43` 合并为 `main@c8508b4e`（实现 `64dff42c` + main 合并 `f5642138`）；合并时
   `origin/main` 已推进 PR `#42`，冲突仅 `docs/current_state.md`/`docs/project_status.md`
   顶部追加位置，保留双方条目解决；`views.py` 自动合并干净。合并树复测 62/62 通过。
2. 发布门禁：用户针对冻结 fingerprint（approved content hash `632eb5258c…b66e57`）
   明确授权；staging 前重算指纹内容零漂移、`review_release_transition.py index` 返回
   `INDEX_TRANSITION_OK`。
3. 生产 `/opt/umanewsbot` `git pull --ff-only`：`8440b897 -> c8508b4e`。写前恢复点
   `.env.backup.pre-race-calendar-20260728T200132Z`（0600）与回滚镜像
   `umanewsbot:rollback-pre-race-calendar-20260728T200132Z`（旧 prod = `02f2f7d16df1`）；
   无迁移、无配置变更、无业务数据写入，按轻量代码发布先例未做数据库备份。
4. `./deploy_lowcost.sh` 一次通过：drain=0、`No migrations to apply`、collectstatic
   1/130/360；新镜像 `umanewsbot:prod`=`b7b797467022`；未复现上次的 SIGKILL 与
   nginx 持续 502（仅在 web 重建窗口有一条瞬时 502，已随 healthy 恢复）。
5. 验证：6 容器 Up（web healthy）、check 0 issues、`migrate --plan` 空、内外 healthz 200；
   `/races/` 日期栏 11 个实际比赛日、当天 2026-07-29 唯一锚点（`today anchor` +
   `aria-current="date"`）、28 卡；显式 cursor/year/q 200 且无锚点脚本；390px/1440px
   浏览器正常、徽标 42×42；web/worker 日志无 error。
6. 回滚：`git reset --hard 8440b897` 重跑 deploy 脚本或恢复上述 rollback 镜像 tag；
   不恢复数据库。完整证据见
   `docs/changes/fix-race-calendar-default-date-window/release_report.md`。

## 2026-07-29 赛事新闻质量治理生产部署记录

1. PR `#42` 合并为 `main@8440b897`（实现提交 `497590e0` + main 合并提交 `7ad0994a`）；
   合并时 main 已占用 migration `0060–0062`，本组迁移顺延为 `0063–0066`。
2. 生产 `/opt/umanewsbot` `git pull --ff-only` 至 `8440b897`；镜像
   `umanewsbot:prod`（build ID `02f2f7d16df1`）；celery drain 归零后停 worker，
   web 重建，`migrate` 依次应用 `0063_add_term_mapping_evidence`、`0064_add_race_news_exposure`、
   `0065_add_exposure_constraints`、`0066_add_term_consistency_manifest`，全部 OK。
3. 异常与处置：部署脚本在 collectstatic 前被 SIGKILL（`exit 137`，2 vCPU/4 GiB 主机内存
   压力）。已手动补跑 `collectstatic --noinput`（0 copied / 131 unmodified / 360 post-processed）
   并 `up -d --no-deps worker beat nginx`；随后首页 502，原因为 nginx 缓存旧 web 上游 IP
   （web 重建而 nginx 未重建），`restart nginx` 后恢复。
4. 部署后验证：`migrate --plan` 空、Django check 通过、6 容器全部 Up、
   `TERM_CONSISTENCY_ENABLED/ENFORCE=False`、`RACE_NEWS_EXPOSURE_ENABLED=False`、
   shadow 均为 `True`；本地与公网首页/healthz 均 200。
5. 当前为 shadow 观察阶段；enforce 开启、历史术语修复 apply、历史曝光回填 apply
   均需按下方灰度顺序逐项独立授权。

## 2026-07-28 最近赛事赛果定时审核生产发布记录

1. 发布前没有 import lock、STARTED import 或 RUNNING historical batch；数据库备份
   `/opt/umanewsbot/backups/db/pre-scheduled-race-result-review-20260728T004929+0800.dump`
   为 `262544260` bytes，SHA-256
   `6edc1c6b7057f1be2ab622d570816890958edf7e67557b38b8dc95ff2c9b2205`，
   `.env` 备份同 timestamp，另保留 rollback image
   `umanewsbot:rollback-pre-scheduled-race-result-review-20260728T004929_0800`。
2. PR `#39` 首次部署严格保持新开关关闭；migration `0062` 成功、route registry 可读、
   四张治理表为 0，disabled smoke、healthz 和 Celery ping 通过。
3. 首次启用后的 catch-up 在联网前因 JSON 序列化失败。止血顺序是停止 Beat、关闭总开关
   和网络开关、核对业务基线与治理表均未变化；不得删除或改写生产数据来绕过错误。
4. PR `#40` 窄修后重新执行完整关闭态部署，再次通过 disabled smoke 后启用。当前生产
   HEAD `ca22c9fa6389984cf38f6cbb9f8c6179e7249798`，image
   `sha256:0cb2e1787fadfb742d3733db3a53e0d08035c22d98d71779dd874bb4a06def65`。
5. 首次受控 run `26` 为 `notified`，bundle
   `07e7f22374bbc09a85df441f87da1cd0228f5431a8f9378a8f1e578bbecf4d47`；
   delivery 为 1，重复 wrapper 为 `already_claimed`。业务基线仍为
   `RaceEventResult=92223`、finished `9419`、scheduled `443`。
6. Beat schedule 是 `30 6,18 * * *`、timezone `Asia/Shanghai`；Codex automation
   `umanews` 执行同一生产 wrapper。回滚/止血先暂停 automation、停止 Beat并关闭总开关，
   不得仅依赖其中一个入口。
7. 当前 13 个目标全部 `route_missing`。在来源身份 discovery 修复并通过独立验证之前，
   正常运行可以发送 blocker 审核包，但不得将其解释为已取得赛果，也不得执行 apply。

## 2026-07-27 event 80 非完赛解析修复的后续发布顺序

1. 仅发布通过独立只读复审的精确提交；部署时保持 race-result apply、historical network、
   race-live scheduler/monitor/runner/lifecycle 与 publication policy 全关闭，不改当前 P0
   URL 发现开关状态。
2. 部署后先运行 Django check、迁移漂移、容器镜像/commit 与内外 healthz 验证；不得把代码
   部署解释为联网 prepare 或赛果写入授权。
3. 取得新的有界联网 prepare 授权后，复用冻结 40 场 scope、expected-target/source-map
   SHA 和现有 source cache 重跑。必须重新核对请求 `<=75`、manual-only 请求 `=0`、
   candidate 数 `=40`，并确认 event 80 为 17 条连续数值名次加 #5 `中止/pulled_up`，
   `result_order_complete=true`；不得给 #5 补造第 18 名。
4. 新 candidate/approval/review manifest SHA 必须重新生成。只有独立 verifier 证明
   40/40 accounted、`blocker=0`、精确 create/update/delete 与 owner 分流后，才可向用户
   请求绑定这些 SHA 的生产写入授权。

## 2026-07-27 event 426 时间修正与联网 prepare 记录

1. 写前确认 event `426` 为 `EDDIE READ S.`、`local_date=2026-07-26`、
   `timezone_name=America/Los_Angeles`、`race_datetime=null`、赛果 `0`。事务使用
   `select_for_update()` 和身份/CAS 检查，仅写
   `race_datetime=2026-07-27T01:10:00Z` 与审计日志。
2. 写前与回执位于
   `/opt/umanewsbot/runtime/race_result_recovery/event426-time-fix-20260727T060100Z/`，
   SHA-256 分别为 `ce8e5fb9…1d53`、`59627477…c74`，权限 `0600`。
3. 新 inventory 为
   `/opt/umanewsbot/runtime/race_result_recovery/inventory-20260727T060200Z.json`
   （file `327e8c16…0aa3`、manifest `d569534a…cfda`）。plan 为
   `race-result-recovery-prepare-20260727T060300Z.plan.json`（`b70ce2c2…f21d`）。
4. plan 阶段保持 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；prepare 仅在 one-off
   容器临时设置 historical enabled/network 为 true，常驻 `.env` 和四应用容器均保持 false。
   实际请求 `12/75`，manual-only 自动请求 `0`。
5. combined candidate SHA-256 为 `033fc60d…489c`，仅含 4 场 JRA 官方赛果。Sporting Life
   和 ZEturf 因 scheduled 状态过滤而空跑，TOBA 为 403；不得继续到 apply。修复后必须创建新
   immutable run，不覆盖 `prepare-20260727T060300Z`。
## 赛事新闻质量治理 部署配置（2026-07-29 已上线，shadow 观察中）

### 新增配置项（.env）

```bash
# 术语一致性
TERM_CONSISTENCY_ENABLED=false
TERM_CONSISTENCY_SHADOW=true
TERM_CONSISTENCY_ENFORCE=false

# 赛事新闻曝光
RACE_NEWS_EXPOSURE_ENABLED=false
RACE_NEWS_EXPOSURE_SHADOW=true
RACE_NEWS_SECOND_SLOT_DELAY_MINUTES=15
RACE_NEWS_HOMEPAGE_MAX=2
RACE_NEWS_QQ_TARGET_MAX=2
```

### 新增 Migration

- `0063_add_term_mapping_evidence` — 新增 `TermMappingEvidence` 表
- `0064_add_race_news_exposure` — 新增 `RaceNewsExposure` 表及约束/索引
- `0065_add_exposure_constraints` — exposure slot/delivery CheckConstraints
- `0066_add_term_consistency_manifest` — 新增 `TermConsistencyManifest` 表（dry-run manifest 持久化与 rollback）

注：合并时因 main 已占用 `0060–0062`（race reference / scheduled result review），本组迁移由
原 `0060–0063` 顺延为 `0063–0066`，依赖链挂到 `0062_add_scheduled_race_result_review` 之后。

### 部署验证

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py test stable.test_race_news_exposure stable.test_public_term_consistency -v2
python manage.py test stable.test_editorial_headlines stable.test_english_term_context_gates stable.test_term_gate_reprocessing -v2
```

### 灰度顺序

1. 部署 schema + 代码，所有新开关关闭
2. 开启术语 consistency shadow → 审核冲突和 unresolved
3. 开启新闻 exposure shadow → 审核一个完整赛事窗口
4. 术语 enforce → 新文章 canonical 门禁
5. 首页 exposure enforce → 验证首页/赛事详情完整性
6. 测试群 QQ enforce → 观察至少两个自然窗口
7. 历史术语 repair dry-run → 人工审核 → 独立授权 apply
8. 历史 exposure 回填 dry-run → 独立审核 → 单独授权 apply

### 紧急回滚

```sh
# 关闭 enforce，保留审计
# 术语
TERM_CONSISTENCY_ENFORCE=false
# 曝光
RACE_NEWS_EXPOSURE_ENABLED=false
# 不删除 migration 和审计表；旧 exposure 保留
```
## 日本重赏 P0 身份补证的未来生产边界（2026-07-25 方案）

- 2026-07-25 task 1.1 只读盘点使用生产 HEAD `9b58bfd437f58dede0de5d11d64537e2e68e214e`
  的现有 web 容器执行 ORM 聚合；没有外部来源请求。写前/写后计数均为
  `RaceEvent=9867 / Runner=100132 / Result=91904 / HorseP0Source=57393 /
  HorseProfile=46318`。
- 聚合 artifact 位于
  `docs/changes/bootstrap-p0-horse-identity-evidence/artifacts/production-readonly-20260725/`；
  `summary.json` SHA-256 为
  `66d6415941810436ce9e657621f45c6f710ddf39e142a5e56cc67cf270ce086c`，
  `report.md` SHA-256 为
  `c3fe77fcfa83389fd5ed7897f178ec565a84496aea97cee90b89e2e31928dcc3`。
- 当前任务清单进度为 `26/38`，候选池、JRA/NAR 上下文解析、三套 provider、网络预算/
  缓存/恢复、A/A+ 共识、完整 prepare artifact、请求账本、审核 xlsx、不可变 approve event、
  唯一 receipt 和严格 replay verifier 已完成；真实 prepare 候选保存完整 commit 冻结选择字段，
  approve 要求内嵌 candidate/blocker 与已哈希 JSONL sidecar 规范字节一致。旧 JBIS/JAIRS
  新命令路径已移除，身份补证 `46/46` 通过。分支已同步 `origin/main@9b58bfd4`，receipt
  迁移为 `0058` 并依赖当前
  合并叶 `0057`；`0057 → 0058 → 0057 → 0058` 往返迁移、Django、迁移漂移、两份 Compose
  config、durable artifact 五件套和 diff check 均通过。
- 正式 commit/verify 命令必须带精确批准 SHA、独立批准人及
  `--confirm-approved-artifact`。身份补证 `46/46`，公开履历分页、旧 P0 批次及其余相关主链
  组合回归 `551/551` 已通过；新命令与服务无 JBIS/JAIRS 引用。
  首轮明确代码 review 的 6 项 finding 已修复；完整范围原生 review 新发现的两项 P1 也已修复，
  原生 reviewer 会话已确认两项 P1 关闭且无直接相关 actionable finding。2026-07-26 发布前
  `origin/main` 新增 HRN 修复及其发布证据，本分支在未 staging/commit 状态下安全同步到
  `0aeb0ed7`；合并后身份模块 `46/46`、相关主链 `551/551`、Django、migration drift、
  Compose 和 diff check 通过，须对该最新组合版本完成同会话复审并重新取得发布授权后才能提交。
  当前未迁移生产、未触网、未写生产。
- 部署后常驻 `web/worker/beat/race_live_worker` 的马匹网络开关仍保持 false。真实 PoC 只在
  另获当次触网授权后，由一次性容器按显式 20 匹清单运行；JRA、NAR、Netkeiba 分 host 限速，
  429、访问拒绝或异常访问提示立即停止，结束后立即恢复网络 false。
- 首次 PoC 不写数据库，必须 20/20 产生 pass/partial/稳定 blocker、未知异常为 0、至少 1 匹
  pass，且请求账本闭合。通过后才能另行授权首批最多 100 匹 prepare。
- 第二层每匹最多访问赛事索引、赛事详情、马匹档案各一个 JRA/NAR URL；每 URL 最多三次尝试，
  单匹总计最多 6 个不同 URL/18 次传输，官方链最多 3 个不同 URL/6 次传输，同 provider
  重定向也计入预算。外国出生或转籍抽样线索不得写入 `training_evidence`，必须由官方档案
  另行确认日本训练身份。
- prepare 仍只生成 qualification、candidate、blocker、source evidence、请求账本和 xlsx。
  正式写入必须先备份并绑定精确批准 SHA；commit 只填三个仍为空且未锁定的身份字段，任一漂移
  整批回滚，公开状态与履历不变。
- 未来 JRA-VAN 通过 Windows 节点离线导出 `horse_identity.jsonl` 与 manifest；生产 Linux
  只做无网络 SHA/版本/清单校验，不为 Windows 节点开放数据库直连。

## task 5.4 最终生产执行记录（2026-07-24）

- 精确提交 `044f3d57f4f3bb75eac31f0567917132e5ae5cff`，生产镜像
  `sha256:01f0fd3466873b0a1c44bb7ad4ab5d64d4a8f0e2e9d8a5a6df84a27dfad8861d`。
  `web/worker/beat/race_live_worker` 均使用该镜像且马匹网络为 false。
- candidate/artifact/release SHA 分别为 `6dc853a2b5581de3af241fca81fb76d0f48bcea600abcb7c231206d229a69f9b`、
  `b1e123fa77387505a1380b6ae932712117c68aa8aef502deb66b149d25838863`、
  `8c6f2dc8d88abce2d432b3e3d174611dedbba2f5a04f174e17d1376365c1511d`。
- 写入前先停止 beat，并通过既有 drain 等待 active/reserved、`celery` 和 `race_live` 队列归零。
  正式恢复点为
  `backups/db/pre-p0-task54-write-20260724T030415Z.dump`，大小 `239995794` bytes，
  SHA-256 `3f0c71122e62f6fc6940d4c142ea542653b4a7980c63723b953a87f5807fea6e`，
  `pg_restore -l` 通过；环境备份为
  `.env.backup.pre-p0-task54-write-20260724T030415Z`。
- commit 成功并写入 1,490 records、244 audits、61 P0 source、1 completion run；61 profiles
  只更新不新建，61 个已公开对象进入 frozen exclusion，发布 0。重复相同 commit 返回冻结结果，
  planned remaining 全 0，所有相关表计数不变。
- 回归结果：61 匹 strict complete、61 个公开详情页 200、healthz 与日本马匹列表 200、四应用
  network false；确认后已恢复 beat。该批次已完成 `commit:japan` 与 `publish:japan`；
  本次执行没有再 prepare 新 candidate，也没有用 retry-publish 扩大公开范围。

## task 5.4 空胜绩修复后的恢复顺序（待 review 后发布授权）

1. 只部署通过独立 review 的精确修复提交；保持宿主及
   `web/worker/beat/race_live_worker` 的
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。本修复不需要触网。
2. 保留旧 candidate `8ef0f718...`、release `5320c33c...`、artifact 和 ledger，不删除、不覆盖、
   不手工改状态。新代码只在 v2 发布链路因缺少当前完整度策略版本而拒绝旧候选；历史 v1
   artifact 继续兼容可信 v1 dry-run，但任何 v1 commit 都在数据库写入前拒绝。
3. 使用原冻结 bundle 执行新的 `--prepare-release`，核对 artifact/candidate 都包含
   `completion_policy_version=p0-horse-full-profile-completeness.v2`，并重新记录完整 SHA、
   bindings、expected actions 和 publish scope。
4. 最新独立 review 成功且指纹不变后，请求当前任务发布授权。review 前的持续授权或预授权
   不替代该门禁。
5. 获得 review 后发布授权，再部署精确提交并重新 prepare-release。若预计动作仍为
   61 profile updates、1,490 record creates、61 source upserts、244 audits，且公开范围仍为
   61 already-published / 0 attempt，才可生成正式批准；任一对象、数字或公开范围扩大都停止。
6. 另做写前数据库/.env 恢复点，再运行带新 candidate SHA 的 commit。成功后核验
   completion run `+1`、records `+1490`、audits `+244`、profiles/sources/公开净增与 candidate
   一致，并重复网络 false、容器、healthz、马匹页和幂等复验。

## task 5.4 首次 commit fail-closed 记录（2026-07-24）

- 命令绑定 candidate
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`、
  reviewer ID `1`、`approved_by=mentianlu` 与 `--confirm-reviewed-artifact`。
- 写前备份：
  `backups/db/pre-p0-task54-20260723T203347Z.dump`（238,795,564 bytes、SHA-256
  `082e91d5e9d01ef5e04e8d7d3e16118eab8ae09ad2548b13378d49f23254c2ec`）和
  `.env.backup.pre-p0-task54-20260723T203347Z`。
- 正式 manifest/批准账本已生成，release SHA 为
  `5320c33c44d387b14e827b109353ffe5068d997bd9c62d9df903cb5de91e0c90`；DB apply 在
  `イエローマジック is not strict complete after apply:
  ['major_wins', 'review.reviewer', 'review.reviewed_at']` 处失败。
- 事务回滚后马匹业务表、completion run、OperationLog 与公开计数全部不变，state 无
  commit/publish stage。不要手改 artifact、添加虚假胜场、删除 release/ledger 或用 retry-publish。
  同 candidate 只有在代码语义未变且完整门禁可满足时才允许幂等重试；若修复完整度语义，应部署
  新受审版本、重新 prepare-release 并取得新 candidate SHA 授权。

## task 5.3 生产执行记录（2026-07-24）

- 精确版本：`4972a6b2eb35167d5783f5c37908b8b3d190160d`；部署镜像：
  `sha256:eed9a3d3b4116644488e85929f475fa06a1072c30f40502b96b62a644fff8ea8`。
  `deploy_lowcost.sh` 不会自动重建 `race_live_worker`，本次按既有要求额外执行
  `docker compose -f docker-compose.prod.lowcost.yml up -d --no-deps --force-recreate
  race_live_worker`，最终四应用镜像一致。
- 恢复点：`.env.backup.pre-p0-task53-20260723T201151Z`；
  `backups/db/pre-p0-task53-20260723T201151Z.dump`（238,713,659 bytes，SHA-256
  `341210bceff05064c1828914338aa82dc166773a605a3154cc54547f7f2522d8`）；
  `umanewsbot:rollback-pre-p0-task53-20260723T201151Z`。
- 持久化批次必须使用容器绝对路径
  `/app/runtime/horse_profile_completion/batches/p0batch-20b59bda0608/batch_manifest.json`。
  `/app/server/runtime` 在当前镜像中不是该宿主挂载点；相对 `runtime/...` 会在任何写入前报
  combined candidates unreadable，不得以复制文件绕过，应改用上述已绑定的绝对路径。
- bundle 为 61 匹；candidate/artifact SHA 分别为
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe` /
  `1abbf475927c1e4391ab1ce851b3cd28958da2ec65641c28ec4f49e9608c4894`。
  重复 prepare-release SHA 不变且账本不增长。当前不得执行 commit；task 5.4 需新授权。

## P0 prepare-release 并发排障补充

- `prepare-release` 无论从 command 还是 public service 调用，都必须先取得 batch execution lock，
  再取得 state serial lock。不得以 direct service、临时 shell 或脚本绕过此顺序。
- 若同 batch commit 或 abandon 正在执行，prepare-release 会等待完整 execution window 退出，并在
  获锁后复读 manifest/state。终态为 committed 或 abandoned 时应零写拒绝。
- 排障时保留 lock 文件、candidate 目录、state 和 ledger；不得删除 lock、并行重跑或手工修改
  终态证据。异常拒绝后应核对 candidate 文件集合及 state/ledger bytes 未被该调用改变。

## P0 completed commit 重放核验补充

- task 5.4 成功后如需普通重复 commit，必须确认 candidate、artifact、release、commit/publish
  checkpoint 与 committed completion run 均完整，且账本中恰有一个精确匹配 batch、region、
  artifact、发布计数/IDs 和 frozen exclusions 的 v2 `auto_first_publish` 成功事件。
- 合法重放只返回冻结结果，不执行 production dry-run、DB apply 或 publish，也不修改 state、
  ledger、completion run/source/audit/task log 与业务表。
- publish 账本缺失、重复或不匹配时命令会提示 manual audit。此时停止操作，保全 batch 目录、
  state、ledger、数据库计数和日志证据；不得手工补写 ledger/checkpoint，也不得用普通 commit
  代替 `--retry-publish`。publish 未完成或失败仍只走显式 retry 门禁。
- `prepare` 与 commit 对同 batch 共享 execution lock；生产排障不得删除 lock 文件或并行绕过。

## task 5.3 无写入发布候选操作手册（待取得精确版本部署授权）

前提：

1. 只部署经过最终原生 review 的精确集成提交；生产 `.env` 与所有在线应用继续保持
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`。本步不需要网络，不得覆盖为 true。
2. 使用已人工确认的 `p0batch-20b59bda0608`，仅纳入 61 个无 `failure_reason` 的完整对象；39 个
   blocker 必须保持排除。先核对原 xlsx SHA 仍为
   `bee158e6d70c099c550102df6f9221b2d6bbb5fb75697d50a06d6d87b61cbc9f`。
3. 执行前后记录 `HorseProfile`、`HorseP0Source`、`HorseRaceRecord`、
   `HorseProfileCompletionRun`、`OperationLog`、`TaskExecutionLog`、`TermEntry`、`TermAlias`
   计数，以及日本公开马计数；task 5.3 要求全部不变。

执行顺序：

```bash
python manage.py p0_horse_completion_batch \
  --bundle <p0_horse_completion_batch_manifest.json> \
  --region japan \
  --reviewer-id <active-superuser-id>

python manage.py p0_horse_completion_batch \
  --prepare-release <p0_horse_completion_batch_manifest.json> \
  --region japan \
  --reviewer-id <active-superuser-id>
```

验收并停步：

- 保存并展示 release-candidate 文件路径与 SHA、commit artifact SHA、batch/combined/research/
  mapping/authority/production snapshot 全部 bindings、expected actions、existing/create-new
  publish scope 和 frozen exclusions。
- `approvals_ledger.jsonl` 只允许新增幂等 `release_candidate_prepared`，不得出现本 candidate 的
  `release_approved`；不得生成 v2 release manifest。
- 核对 61 个 reviewed 对象与 candidate scope 精确一致，39 个 blocker 为 0 命中；重复
  `prepare-release` 必须字节一致、SHA 不变。
- 至此立即停止。不得传 `--approved-by`，不得执行 `--commit` 或 `--retry-publish`。将精确
  candidate SHA、预计写入和自动首发清单交给用户；task 5.4 必须取得针对该 SHA 的新授权。

task 5.4（本轮不执行）的入口必须同时包含：

```bash
--release-candidate-sha256 <用户批准的精确 SHA> \
--approved-by <独立批准人> \
--confirm-reviewed-artifact
```

任何 bundle、mapping、生产 profile 状态、candidate、artifact、账本或 manifest 漂移均 fail
closed，重新 prepare-release 并重新授权；不得手工改 state/ledger 绕过。

## task 5.2 精确提交一次性联网执行记录（2026-07-23）

- 本次执行前，受审目标 `5eec316f...` 与生产 HEAD 已从共同父提交分叉。强制切换会回退并行
  已上线功能，合并则会产生不同于授权对象的新 SHA，因此本次没有改动生产分支。服务器通过
  `git archive <target>` 导出精确 tree，构建了带
  `org.opencontainers.image.revision=<完整目标 SHA>` 的专用镜像；在线服务保持生产 HEAD 和
  既有镜像不动。
- 本次专用容器加入生产 Compose network、复用 `.env`，仅覆盖
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true`，并把宿主
  `runtime/horse_profile_completion` 挂载到 `/app/runtime/horse_profile_completion:rw`。
  宿主 `.env` 全程保持 false，该镜像未用于重建 web/worker/beat/race_live_worker。
- 本次依次执行 select、100/100 地区与唯一 provider identity 检查、approve、批准后 SHA validate
  和 `prepare --allow-network`；只生成 cache/checkpoint/artifact/xlsx，未继续 bundle、commit 或
  自动首发。
- 本次证据：镜像 `sha256:e543065c...`、批次 `p0batch-20b59bda0608`、批准 SHA
  `51ac349e...`、300 请求/0 cache hit、61/100 完整；xlsx SHA `bee158e6...`。执行后确认专用
  容器不存在，宿主及四应用 network=false，生产 HEAD 未变，马匹和公开计数未变，healthz 通过。
- 本次回滚面为停止一次性容器；容器正常退出并删除后，其联网能力随即撤销。由于在线镜像和
  `.env` 均未替换，本次没有为关窗重建公网服务。执行前 `.env`、数据库 dump 和在线镜像 tag
  均已保留；发现的在线应用既有镜像差异只记录证据，本次 P0 批任务未改动。
## 2026 赛事系列身份只读审核工具与正式审核包（2026-07-23）

1. 用户在最终原生只读 review 通过后授权提交、推送、部署只读工具并生成正式生产审核包。
   审核内容经 index transition 锁定后提交为
   `17d7757aec764755394339400eb2523eae896fa5`，任务分支和 `main` 均已推送。
2. 生产从 `15645b05` fast-forward 到 `17d7757a`，运行 `deploy_lowcost.sh`。无 migration；
   Django check 和命令 help 通过，web/worker 镜像均为
   `sha256:5a3dd28b846954837ade517e5d85aa2bba3b4651d322876f950f0cdfcda45e44`，HTTP
   `/healthz/` 返回 `{"status": "ok"}`。
3. 以生产 HEAD 作为不可变参数运行 `review_2026_race_series_identities` 导出模式。正式快照时间
   `2026-07-23T02:44:23.655795+00:00`，计数为 1,085 total、684 已关联、226 唯一名称匹配、
   11 同名多候选、162 无名称匹配、2 未举办；五分类计数与探索基线一致，异常 0，
   `blocks_decisions=false`。当前未记录 identity-set digest，不能据此排除集合等量替换。
4. 主机持久化目录为
   `runtime/race_series_identity_review/formal-20260723T104700+0800/`。web 的 `/app/runtime` 未挂载，
   因此导出后立即用 `docker cp` 把同一目录复制到主机；禁止只保留在可重建容器内。
5. 文件 SHA-256：manifest `9d0df5da1e942f77bbabe9df7c84a921ea9325564ce821ab5f17ebf2f13eee47`；
   review.csv `afa06b10cb1d3a7ade13e95f6d18385379a2813458fe61f34ce98440770be1cf`；
   review.json `951ef701c21f994de1f584530b8cca2eec9ae7b1a3f3858aaf5ddc59d447b0aa`；
   review.xlsx `c4e09f8bc0d5a5dc912d6b57efb79173d69f9fb70ce057a9d9f6a1526d30c80b`；
   snapshot.json `1073fa0bbaf6a2b3e3dfa1217fe1afe0b01a80796e47552a182524b0d27ae98a`。
6. 五文件已复制到本地审核目录并逐文件复核相同 SHA；六张工作表均实际导入、渲染，公式错误
   扫描为 0。本阶段未运行 build-decisions、prepare、apply 或 commit 模式，没有生产业务数据写入。
   人工定稿工作簿不等于数据 apply 授权；后续仍需精确 decisions/manifest 复审和新的写入授权。
## 2026 赛历赛事中文名补齐生产执行记录（2026-07-23）

1. 生产当时快进到 `6167b6c0` 并执行 `deploy_lowcost.sh`；无迁移，HTTP `/healthz/`
   返回 200。这是已发生的发布记录，不是本轮重新部署。
2. 定稿 CSV 进入生产后，基于生产实时 before 构建 manifest，与定稿零漂移。写前备份
   `backups/db/pre-translate-2026-race-names-20260723_012307.dump` 大小为 232,399,205 bytes，
   SHA-256 为 `cdcc751ed852019830721ddea0894afe04c0fcf7f7c5223921ca947c66edd04c`，
   `pg_restore -l` 得到 1018 项。
3. 同一 manifest（SHA-256
   `b9f1e8b73e84da9df141a78081a1da2ba29d727539f12ce2fb708a95df4375c8`）单事务写入
   `written=573`；OperationLog batchId 为
   `d2e2b203d9c3e67f683650c397ed6af038c17123d9c54cf71bdb302b784ce673`；
   `--verify` 返回 `{"ok": true, "written": 573, "veto": 0}`。
4. 发布时保留的核验包括 DB 全量复扫、五地区赛历卡片和 4 场详情页。spec 要求
   详情页跨地区抽查至少 5 场，因此现存证据少 1 场，不能把该数量项记为通过。本轮只做
   HTTP 公网抽检：`/healthz/` JSON 正常，2026 赛历抽样标题为中文；这不是发布时的第 5 场。
   HTTPS 在本地代理链路握手失败，本轮未验证 HTTPS。
5. web 容器内的定稿与 manifest 临时文件已清理；本地
   `/tmp/translate2026-manifest-production.json` 当前也不存在。保留的是上述 SHA、执行结果、
   OperationLog batchId 和发布报告，不得将临时 manifest 文件本体记为现存。
6. 治理证据缺口：历史 Claude Code「等价复审」不是现行规则要求的 Codex 原生只读
   review；用户授权的 `bd03b100` 与最终部署的 `6167b6c0` 不同，缺少集成版本的
   合格复审及其后新授权证据。生产结果虽然成功，但不能因此追认该治理门禁。
7. 详细记录：`docs/changes/translate-2026-race-display-names/release_report.md`。

## publish_ready 积压治理部署与灰度（2026-07-23，历史清单已收敛，新 24 小时观察中）

### 0. 本次实际执行证据

- 2026-07-23 舍弃动作部署：生产从 `3d573583` fast-forward 到
  `HEAD=7a6f30d8708c0560ba2120c44fd640ff35a7ea3e`；web/worker/beat/race_live_worker 统一为
  `sha256:fa2fdf9bb952…`。恢复点为 `.env.backup.publish-ready-discard-20260723_001049`
  （SHA-256 `467b6398…`）和 `backups/db/pre-publish-ready-discard-20260723_001049.dump`
  （SHA-256 `d6f6e342…`、`pg_restore -l` `1018` 项）。Django check、迁移、镜像一致和 healthz 通过。
- 21 篇 decisions 与 pending manifest ID 集合精确相等；pending 快照漂移 0。批准文件为
  `runtime/news_integrity/publish-ready-legacy-discard-approved-20260723_001547.json`，manifest SHA
  `860fbec26c8982515f11ab888637a915e1a0b9fbdbd113475ced48e616932bb9`、文件 SHA
  `83e396a8ffc2…`。首次 apply `discarded=21 / skipped=0 / refreshed=0`，重放
  `already_applied=21`；最终 21/21 三层 ignored 且审计匹配，公开 0、QQ 0。
- 部署后先停 beat 消化到期任务，celery/race_live 队列清零且 active/reserved 排空；备份
  `.env.backup.publish-ready-observation-20260723_002152` 后重新启用五地区。运行进程实际读取
  `enabled=true`、五地区 allowlist、24h、limit 200；开启时英国实时 1、美国实时 5、其他实时 0、
  五区 backlog 0、healthz 200。新观察期为 `2026-07-23 00:22:19` 至
  `2026-07-24 00:22:19 Asia/Shanghai`，heartbeat 为 `publish-ready-24-restart`。
- 初次部署代码：生产 `HEAD=8bbf7a2551296177da6556029e325db57bd369cc`；web/worker/beat/race_live_worker
  统一使用 `sha256:251706abb947b7292b36e2ac24285f9d75661031c2cbdcba3259539792b5b0cb`。
- 恢复点：`.env.backup.publish-ready-20260722_172001`（SHA-256 `7af509d6…`）；
  `backups/db/pre-publish-ready-20260722_172001.dump`（`230492618` 字节、SHA-256
  `4aac6117…`、`pg_restore -l` `1017` 项）；旧镜像标签
  `umanewsbot:rollback-pre-publish-ready-26eb03e3-20260722_172001`。
- 迁移：`0053_newsarticle_publish_ready_at` 已应用；nullable 列与
  `news_region_ready_at_idx` 存在；21 条历史 ready 均未回填。`makemigrations --check`、
  Django check、Celery 两节点、容器内和公网 HTTP `/healthz/` 通过。
- 关闭态只读预览：日本实时 8、英国实时 2、其他 0；五区积压加载均 0；
  `WindowCandidateDecision 25937→25937`、`QuotaLedger 440→440`。
- 香港直开：实际进程读取
  `MULTIREGION_PUBLISH_BACKLOG_ENABLED=true`、allowlist `hong_kong`、limit `200`。
  `17:45 / 18:00 / 18:15 / 18:30` 窗口 `50846 / 50881 / 50905 / 50931` 均为
  `succeeded / realtime=0 / backlog=0 / published=0`，四窗口候选决策和地区配额写入均 0；
  公网 healthz、抓取/stale、队列、资源与关键异常日志验收通过。
- 四窗口通过后已将 allowlist 扩为
  `japan,hong_kong,united_kingdom,france,united_states`，Web/Worker 实际读取一致。
  扩区后只读预览为日本实时 9、英国实时 1、其他 0，五区积压均 0，零决策/配额写入。
  `18:45` 首个五区自然窗口五条记录均 `succeeded`，日本 9/英国 1 条实时候选
  全部 `hard_gate_blocked`，selected 0、积压决策 0、地区窗口配额账本 0、全站小时配额
  `1/60`；Celery 两节点和公网 healthz 正常。当时进入首轮 24 小时观察，未完成前不标记
  change 生产收口；该轮后续被并行部署打断，见下一条。
- 首轮 24 小时观察从 `2026-07-22 18:45` 开始，期间 13 篇新鲜候选正常公开，最大 selected
  ready 年龄 `0.625h`，无过期/legacy 稿误选或公开；约 `23:00` 被并行 P0 容器重建打断。
  本任务已按批准顺序关闭积压开关并恢复运行态，旧 heartbeat 已删除；该段只能作为增量证据，
  不计为连续 24 小时通过。
- 历史 dry-run：主机持久化文件
  `runtime/news_integrity/publish-ready-legacy-20260722_173639.json`，内部 manifest SHA-256
  `b72ddc927a3f334762a69a4384755aff40704a71aa4877ca4aa5ecbdfa52faac`，文件 SHA-256
  `a125647ac6a751c269bf52ad24e6d33443a542d87eb2b0d3ecaddec1ab28534c`；原 dry-run 数据库写入 0。
  这 21 条现已按上方 approved manifest 全部 `discard_ignored`。web 容器未挂载通用 runtime，
  因此审核文件均通过 `/tmp` 处理后立即 `docker cp` 到主机受控目录，不得只留在可重建容器内。

### 1. 部署前和迁移

1. 核对生产 Git HEAD、四应用容器 image ID、迁移末端和所有相关开关；停止 beat、排空
   active/reserved，备份 `.env` 和 PostgreSQL custom dump，并验证 SHA-256 与
   `pg_restore -l`。
2. 部署 `0053_newsarticle_publish_ready_at`。该迁移只增加 nullable 字段和组合索引，不回填
   历史文章。部署后先保持：

```dotenv
MULTIREGION_PUBLISH_BACKLOG_ENABLED=false
MULTIREGION_PUBLISH_BACKLOG_ALLOWED_REGIONS=
MULTIREGION_PUBLISH_BACKLOG_AUTO_HOURS=24
MULTIREGION_PUBLISH_BACKLOG_REVIEW_HOURS=72
MULTIREGION_PUBLISH_REALTIME_SCAN_LIMIT=200
MULTIREGION_PUBLISH_BACKLOG_SCAN_LIMIT=200
```

3. 运行 Django check、migration drift、Celery ping、`/healthz/`、首页和五地区页；确认最近自然
   抓取产生的新 ready 文章具有 `publish_ready_at`，历史 NULL 数没有被迁移改变。

### 2. 只读预览和单地区四窗口

候选预览只调用 `build_candidate_pool`，不创建窗口决定和配额：

```bash
$COMPOSE exec -T web python manage.py shell -c '
from django.utils import timezone
from stable.services.publishing_windows import build_candidate_pool
p=build_candidate_pool("hong_kong", now=timezone.now())
print(p.summary); print([(a.id,p.channels[a.id]) for a in p.articles[:20]])
'
```

预览无异常后只开启一个地区，例如中国香港：

```dotenv
MULTIREGION_PUBLISH_BACKLOG_ENABLED=true
MULTIREGION_PUBLISH_BACKLOG_ALLOWED_REGIONS=hong_kong
```

重建 web/worker/beat 后连续观察 4 个发布窗口。逐窗口核对
`ProductionWindow.result_payload.candidate_pool`、`WindowCandidateDecision.payload` 中通道/年龄/截断，
以及地区窗口上限 5、全站小时配额、公开页和 QQ；任何过期稿被选中、查询无界、配额变化或错误
上升时立即把总开关改回 false 并重建相关容器。

四窗口通过后可把 allowlist 扩到五地区，但不得修改既有发布配额。随后连续观察 24 小时。

### 3. 历史候选审核 manifest

生成命令零数据库写入且拒绝覆盖文件：

```bash
TS=$(date +%Y%m%d_%H%M%S)
PENDING="/app/runtime/news_integrity/publish-ready-pending-${TS}.json"
$COMPOSE exec -T web python manage.py reconcile_publish_ready_backlog --output "$PENDING" --limit 100
```

审核决定另存为 JSON 对象，键为 article ID，值只能是 `keep_manual`、
`revalidate_refresh_ready` 或 `discard_ignored`。默认省略的文章全部 `keep_manual`。
`discard_ignored` 沿用后台忽略语义，同时设置 workflow/review/automation 三层 `ignored` 和
`ignored_at`，并在 `decision_reason.publish_ready_recovery` 记录 reviewer、manifest SHA、动作和
执行时间；它不会删除文章。封印 reviewer 和新 SHA：

```bash
REVIEWED="/app/runtime/news_integrity/publish-ready-reviewed-${TS}.json"
$COMPOSE exec -T web python manage.py reconcile_publish_ready_backlog \
  --seal-review "$PENDING" --decisions /app/runtime/news_integrity/decisions.json \
  --reviewer '<审核人>' --output "$REVIEWED"
```

只有用户确认逐篇决定和封印 SHA 后才可 apply：

```bash
$COMPOSE exec -T web python manage.py reconcile_publish_ready_backlog \
  --apply-manifest "$REVIEWED" --expected-sha256 '<64位SHA>' --confirm-apply --limit 100
```

apply 后必须独立核对：刷新/舍弃数、漂移/阻断数、`published_to_web_at` 新增 0、QQ delivery
新增 0；刷新稿只进入正常发布窗口，舍弃稿不再进入候选池。同一 manifest 应重放一次验证
`already_applied` 幂等结果。当前 21 条历史候选已由用户明确确认全部舍弃，仍须以原清单快照
零漂移为前提执行。

### 4. 回滚

- 首选止损：`MULTIREGION_PUBLISH_BACKLOG_ENABLED=false` 并重建 web/worker/beat；实时 3 小时通道
  和原配额继续运行。
- `0053` 是 additive schema，代码回滚时保留字段和索引最安全；不得为回滚清空
  `publish_ready_at`。只有恢复旧数据库备份时才整体回退迁移。
- manifest apply 可以刷新资格时间或按明确授权标记 ignored。若某批准动作需撤销，必须以逐篇
  人工工作流重新审核；不得批量删除新闻、公开记录或 QQ 账本。

## 新闻索引和遗留 CrawlJob 操作手册（2026-07-22）

### 已执行的索引修复

- 目标：`public.stable_newsarticle_public_slug_46694cb6`，普通非唯一、非约束 B-tree。执行前 HEAD `559cec7aca35d7eb49b463aa52e49c93d8af9a52`，PostgreSQL `16.14`。
- 备份：`.env.backup.news-index-repair-20260722_135849`；`backups/db/pre-news-index-repair-20260722_135849.dump`（`229947588` 字节，mode `600`，SHA-256 `07d2ebd67f1a3c5ec1fb9ddaf93f554639980425dde87c4b19d0cc54a9ae2fb1`，`pg_restore -l` `1017` 行）。
- 停 beat，等 worker 无 active/reserved 后停 worker，确认无活动写入；以 `lock_timeout=30s`、`statement_timeout=5min` 执行 `REINDEX INDEX public.stable_newsarticle_public_slug_46694cb6`。不得 drop index、改 slug 或删文章。
- 写后验收：`indisvalid/indisready/indislive=true`；事务回滚写入探针通过；事务内临时安装 `amcheck`、`bt_index_check(..., true)` 通过后 rollback；netkeiba latest 真实抓取 task `5dc8dac8-8b46-49bc-8122-d2e6c21bec49` 成功。
- 并行 P0 马匹部署重建 db/web 后曾因 Nginx 旧上游出现 `502`。恢复时未回退对方提交，而是恢复 worker/beat/race_live_worker、reload Nginx，并核对 web/worker/beat/race_live_worker 均为镜像 `sha256:f48f6523525e…`。任何后续 web 重建都必须同步 reload/recreate Nginx 并验收 HTTP。
- 从约 `14:23` 重新计时 60 分钟；`15:23` 最终快照为 CrawlJob `77 success / 0 failed / 0 started`，CrawlJob、TaskExecutionLog、db/worker 日志同类索引错误均为 `0`；真实新增文章 `2` 篇，其中日本稿 `9572` 正常公开，英国稿 `9573` 进入人工复核；索引 valid/ready/live，公网 HTTP healthz/首页/五地区入口均 `200`。历史 stale started 仍为 `32`，索引修复门禁 PASS。

### 代码部署后的只读审计与遗留收敛

生产操作必须显式使用 low-cost Compose 文件；裸 `docker compose` 会读取默认文件，可能把 `race_live_worker` 重建为旧的独立镜像：

```bash
COMPOSE="./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml"
```

1. 只读审计：

```bash
$COMPOSE exec -T web python manage.py audit_news_production_integrity --hours 24
```

2. 生成 dry-run manifest（拒绝覆盖已有文件，不写 CrawlJob 或 NewsSource）：

```bash
TS=$(date +%Y%m%d_%H%M%S)
MANIFEST="/app/runtime/news_integrity/stale-crawl-${TS}.json"
$COMPOSE exec -T web python manage.py reconcile_stale_crawl_jobs \
  --stale-minutes 60 \
  --output "${MANIFEST}"
```

3. 审核 `jobs[]`、`activity_evidence`、`recommended_action` 和 stdout 的 `manifest_sha256`。Celery inspect 无回应、有无法映射的抓取任务、或生产窗口租约有效时必须停止，不能把“没回应”当成“没任务”。
4. 仅对审核过的同一 SHA 文件有界 apply：

```bash
$COMPOSE exec -T web python manage.py reconcile_stale_crawl_jobs \
  --apply-manifest "${MANIFEST}" \
  --expected-sha256 "<64 位 SHA-256>" \
  --confirm-apply \
  --limit 100
```

apply 会逐行加锁，只处理仍为 started、started_at/source 未漂移且无活动证据的记录。禁止绕过 manifest 手工批量 UPDATE。代码回滚时保留已修复索引和已收敛终态，不得把 failed 批量改回 started；索引物理错误复发时立即停写并使用备份在隔离库恢复验证。

### 本次代码部署与遗留收敛结果

- 部署前恢复点：`.env.backup.news-integrity-deploy-20260722_152904`（`8193` 字节、mode `600`、SHA-256 `7af509d60ca60f2cf232959d2e779388917a688c3a3210bbb5d70445bda668de`）；`backups/db/pre-news-integrity-deploy-20260722_152904.dump`（`230252800` 字节、mode `600`、SHA-256 `810b07829c36c551722168b0a76ab1efc65b7bbd367ddcab6f0741c6b7b5807a`、容器内 `pg_restore -l` `1017` 项）。
- 生产 fast-forward 到 `7ff968c0557300c1240f13a3d6feae3a8df3085d`，镜像 `sha256:712a5da8b408…`。部署后 Django check、无迁移漂移、Celery 两节点和 HTTP 七入口通过。
- 验收时发现一次裸 `docker compose up race_live_worker` 读取默认文件，使该容器短暂使用旧镜像 `sha256:111dbe46…`；在宣告通过前用 `$COMPOSE up -d --no-deps --force-recreate race_live_worker` 纠正，最终四应用容器镜像一致，期间公开页面持续 `200`。后续禁止对生产服务使用裸 Compose。
- 清单 `/app/runtime/news_integrity/stale-crawl-20260722_153609.json`，SHA-256 `c4cc4f4975a6246131cd91bf2772aaaeb36d85344fbb02fc6223467567230ea0`；`32/32` 条活动证据完整且建议收敛，apply 后 stale started `32→0`。文章 `9547→9547`、公开 `1640→1640`、QQ delivery `629→629`，来源最近状态 SHA-256 均为 `8dca4a423a80b84f4dca456f95cc9a225a8d21632d2c90146b6847285fb86bb8`；幂等重放 updated `0`，随后 dry-run `0` 条。
- 代码上线后满 60 分钟最终快照：`61 success / 0 failed / 0 started`，新稿 `1`、stale started `0`、迟到终态标记 `0`、新索引错误 `0`、应用/数据库异常日志 `0`；修复前错误仍在 24h 历史而已退出 2h 当前窗口。新闻索引 P0 只在 `15:33` 留下同一次 `4` 渠道记录，后续半小时调度未重复，6h 冷却生效。四应用容器统一 `sha256:712a5da8b408…`，Celery 两节点与 HTTP 七入口通过；生产验收 PASS。
## 2026-07-23 netkeiba 第二轮返修与首批重开门禁

旧批 `p0batch-e5cee174ba05` 已完整 prepare，但只 `27/100` 完整、`73/100` 阻断；该批
只作证据，**不得 bundle/commit，不得手改 state.json，也不得在解析器修复后直接重跑同一
approved manifest**。blocked staging 也记为候选成功，且旧解析器未进入 canonical cache
版本，直接 resume 会跳过旧结果。

本轮生产发现与处置：

- `62` 个 `抹消` 标题为解析器缺陷；修复后状态/性别/毛色仍须分别精确验证。
- `10` 个部分 expected identity 为既有完整期望锁的预期阻断，须字段级报告，不得放宽锁。
- Haru Aube 的水沢空着顺行没有足够官方证据判为出赛或取消，继续
  `partial_career` blocker。
- `NETKEIBA_PARSER_VERSION` 同时进入 adapter/candidate fingerprint 与 netkeiba
  canonical payload。日本 netkeiba cache 缺版本或版本不符必须视为 miss；JBIS 和其他
  地区 cache 语义不变。

后续生产必须拆成独立门禁：

1. 最新 code review 通过并冻结精确版本后，重新取得部署/触网授权。先备份并部署；保持
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，只验 HEAD、镜像、Django check、
   容器、Nginx、日志和 healthz，不触网、不写马匹资料。
2. 取得该版本触网授权后进入串行窗口：停相关 worker，开启并在执行容器确认网络开关；
   abandon 旧批，再重新 select/approve 日本批次并 prepare 到 xlsx。要求
   `unexpected_adapter_error=0`、已支持结构系统性 blocker=0；剩余失败字段级报告。
3. prepare 成功或异常后立即以 finally 语义恢复 `.env` 与执行容器内
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`，启动 worker/beat/race_live_worker，
   验证日志、healthz；不得把网络窗口跨到人工 xlsx 复审。
4. 用户人工复审 xlsx 后才生成完整子集 bundle，再执行无写入 `--prepare-release`，冻结
   candidate SHA、commit artifact、预计写入和自动首发清单；此步不写库、不公开，也不生成
   `release_approved`。
5. 用户针对精确 release-candidate SHA、完整子集、预计写入与自动首发范围重新授权后，才执行
   带 `--release-candidate-sha256 <sha> --approved-by <name>
   --confirm-reviewed-artifact` 的 commit；核验 v2 release 反向绑定、幂等复验、
   auto_first_publish、OperationLog、`/horses/?region=japan` 与徽章。失败只允许在同一冻结 scope
   上走 `--retry-publish`。禁止绕过 batch wrapper 直接并发调用 standalone v2；即使使用
   standalone dry-run/commit，也必须由代码自动进入同一可重入 execution lock，并在未落库时
   复验 current batch manifest/combined 的真实 SHA。
6. commit 后重复终验网络开关为 false、全部 worker、日志、healthz 与 `/horses/` 200。

重复执行同一 candidate 的普通 `--commit` 只允许做数据库幂等复验：若 publish stage 已
completed，返回首次冻结的 publish checkpoint/report，禁止重新调用发布；若 publish stage 缺失、
未完成或含 errors，普通 commit 必须拒绝，唯一恢复入口是显式 `--retry-publish`。不得通过重复
commit 利用后续人工降级或 gate 放宽重新公开对象。

2026-07-23 已完成一次安全恢复：备份 `.env.backup.p0-network-disable-
20260722T180903Z`，重建 web 使容器设置为 false，重启 Nginx；web healthy，内外 healthz、
`/horses/` 均为 200。该恢复不代表返修代码已经部署。

最新主线集成返修验证基线：修复重放到 `origin/main@0dcdbdab`；集成候选的精确提交、
content hash 与 fingerprint 以最终 base review 报告为准，不在提交正文中写入会因 amend
自失效的 SHA。P0 聚焦
`285/285`，Django check、`makemigrations --check --dry-run`、旧规格流程 strict/all `37/37`、
`git diff --check` 均通过。完整 `stable` 为 `2741` 项、`21 failures + 70 errors + 57 skipped`；
临时干净工作树中的同一 `origin/main` 基线为 `2726` 项且失败/错误/跳过计数完全相同，差异
仅为本专项新增 15 项测试。首次
全量运行多出的 2 个错误文本兼容失败已通过保留旧错误前缀并追加字段明细修复，之后聚焦与
全量均已复跑。首次独立 review 发现的 stale cache 覆盖 P1 已增加 sidecar lock、原子替换
与并发回归。集成版本最终 base review 以 base `0dcdbdab`、HEAD `15645b05`、content hash
`d3a26c24db0f80afc2acb023d88cc9829fc6a9338022f08e7605f67a399342c7`、fingerprint
`43313e311d5e2ccf87da9d2829c7d6cacfe6f96fd962821be1db35d981822441` 通过，随后取得绑定
该精确版本且明确保持网络关闭的部署授权。

task 5.1 生产部署证据（2026-07-23）：

- 部署前 `.env` 备份 `.env.backup.pre-netkeiba-repair-20260722T192208Z` 为 `8554` bytes、
  mode `0600`、SHA-256 `fd647e0970c5139f1f82ab70fe02f0c02bb2919be5b2ae7d48bf8b4a5e9b5b35`。
  数据库恢复点 `backups/db/pre-netkeiba-repair-20260722T192208Z.dump` 为 `232930440`
  bytes、mode `0600`、SHA-256
  `af96e506b1315bae23e63ce42ecf70c89d1c5fb14179e1eebe383e2d73f4c0b6`，`pg_restore -l`
  为 `1018` 项。回滚标签 `umanewsbot:rollback-pre-netkeiba-repair-20260722T192208Z`
  指向旧镜像 `sha256:69ed2bd9f3f7ecc581c2caba4704bd7b1764fc02af6a2663b78f599217b23696`。
- 生产 fast-forward 到 `15645b054ff1c4057b1463d3382892cbe4c68106`；构建新镜像
  `sha256:07f46301e77eb64cdd4899fee8a1b66d4b3ad5c79b5f5847e15a9ac985f176ef`。先停 beat，
  Celery 两节点 drain 到 `active=0/reserved=0` 后切换；web、worker、beat、
  race_live_worker 最终全部运行该镜像。无迁移，collectstatic 完成，Django check 无问题。
- `.env` 及四个应用容器的 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK` 均为 `false`，Django
  setting 为 `False`，parser version 为 `netkeiba-parser.v2`。宿主与容器 adapter SHA-256
  均为 `444c62a709454f576cdd818e858fc07c3d24df1884ebc3de72794a05adfe744e`。
  内部 healthz/日本马匹页、公开域名 healthz/日本马匹页及 www healthz 均为 200；两个
  Celery worker 响应，近期日志无 error。公开马保持 `2797`、日本 `2463`。本步没有执行
  prepare、没有触网、没有马匹资料写入；task 5.2 仍需新的独立授权。

task 5.2 首次触网执行证据（2026-07-23；**验收失败，禁止进入 5.3**）：

- 前置恢复点：`.env.backup.pre-p0-task52-20260722T193712Z`（`8,554` bytes、mode
  `0600`、SHA-256 `fd647e0970c5139f1f82ab70fe02f0c02bb2919be5b2ae7d48bf8b4a5e9b5b35`）；
  `backups/db/pre-p0-task52-20260722T193712Z.dump`（`232,970,028` bytes、mode
  `0600`、SHA-256 `8aecbce162f56f4938078eeb3d94ef7660048b78bc8e42e8db37208827f0c4a2`、
  `pg_restore -l` `1,018` 项）。
- 生产必须显式配置以下持久化容器路径，禁止依赖 `/app/server` 工作目录的相对默认值：
  `HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR=/app/runtime/horse_profile_completion/batches`、
  `REVIEW_OUTPUT_DIR=/app/runtime/horse_profile_completion/review`、
  `CACHE_DIR=/app/runtime/horse_profile_completion/cache`、
  `BUDGET_DIR=/app/runtime/horse_profile_completion/budget`。
- 正式批 `p0batch-5802d72da799` 批准 SHA
  `204fa275e618fa59eba491c8ce786f9f8c1e73f9ca02d3e5d92c8b35aa9125b8`；prepare 为
  `45 complete / 55 blocked / 300 requests / 0 cache hits`。xlsx SHA-256 为
  `34e849ebd7850a6969d59a0070c881630d467e85857b2816b86edcdbe6f908f9`。该批已
  abandon 留证，不得 bundle/commit。
- 验收失败分层：`20 title_status`（真实页面省略状态）、`32` 个 expected identity
  三字段缺失、`2 partial_career` 分类错误、`1 incomplete_career_history`。parser v3
  返修已在修正真实 validator 包装路径 P1 后通过独立 review；仍须冻结精确版本并取得新
  部署/触网授权，不得在 v2 批次上 resume。
- finally 已验证：宿主、四应用容器和 Django setting network=false；worker/beat/
  race_live_worker 恢复，web healthy、Celery 两节点响应、Django check、HTTP healthz 与
  日本马匹页通过，公开计数不变。后续人工 xlsx 复审和 task 5.3 均不得基于此失败批启动。

## netkeiba 客户端日本批次历史补充（2026-07-22；触网步骤已由上节替代）

在「P0 BASIC 层自动首发操作手册」基础上，首个日本批次重跑时按本节执行：

以下只保留解析与审核口径；凡涉及网络开关、服务暂停/恢复和 prepare 顺序，均以上一节
“第二轮返修与首批重开门禁”为准，不得沿用本历史段落的旧窗口假设。

1. 部署含 netkeiba 客户端的构建后，日本候选有 netkeiba key（2,462 匹）走 ID 直取
   （马匹页 + 战绩页 + 血统页 3 页，每候选预算 4），无 key 候选保持 JBIS 检索；
   8s 限速保持不变，但 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true` 只能在另行授权的
   prepare 短窗口内启用，并须在 prepare 成功或异常后立即恢复、验证为 false，不能跨到
   人工审核阶段。
2. prepare 重跑同一 select 会生成新批次（原 `p0batch-37fad126d645` 已 abandon）；
   复核 xlsx 时关注：netkeiba 候选 `candidate_source_name=netkeiba`、外部 ID 与
   key 一致、四字段来自页面；`ambiguous_identity` 应基本消失，残余失败按
   `partial expected fields`（候选带部分四字段期望值导致锁收紧）单独如实计数。
3. 页面解析失败（`netkeiba_profile_structure` 等）属预期 fail closed，进 blocker
   池等结构适配，不得在运维侧手改 payload。
4. 其余阶段（approve → validate → prepare → xlsx 复审 → bundle → commit → 核验
   自动首发 → `--retry-publish` 恢复路径）与首发手册一致。

## P0 BASIC 层自动首发操作手册（publish-p0-horses-basic-tier，2026-07-22）

本节是批次自动首发与存量批量发布的标准操作顺序。公开门槛：名称 + 五地区 +
（verified identity key 认可 namespace，或父/母/出生日期三字段齐全）；verified
身份只来自身份回填 commit 或人工批准批次 commit。人工 opt-out：在 profile 的
`manual_lock_flags` 写入 `"auto_publish_blocked": true`（shell 逐匹设置，设置后
任何自动/批量通道都不会发布该马，解除时删除该键）。

1. 前置：备份；停 beat/worker（OOM 先例窗口）；首个触网批次只在另行授权的 prepare
   短窗口内设置 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true` 并重启执行进程；prepare
   成功或异常后立即恢复并验证 false，再启动 worker，不得等待人工复审。
2. 首个日本滚动批次：select → approve → validate → prepare `--allow-network`
   （可断点续跑）→ 人工复审 xlsx → bundle → commit `--confirm-reviewed-artifact`。
   commit 复验通过后自动首发本地区马（含批次新建马），输出 `auto_first_publish`
   计数。核验：OperationLog 有逐匹记录、台账有 `auto_first_publish` 条目、
   `/horses/?region=japan` 出现新马并显示「资料补全中」徽章、抽样详情页 200。
3. 发布失败恢复：commit 报 auto first publish failed 时批次不会进入 committed
   终态；排查原因后用 `--retry-publish <manifest> --region <地区> --reviewer-id
   <id>` 只重跑发布步骤（要求复验已通过），成功后自动清理 state.errors 并推进
   终态。**不要用全量重 commit 恢复发布失败**（快照漂移检查会 fail closed）。
4. provenance 回填（一次性，本 change 部署后）：重跑 2026-07-22 已批准的三个
   身份回填 manifest 的 commit（`enrich_p0_horse_identities --commit <manifest>
   --approved-sha256 <sha>`，幂等），为已写入的 2,789 个 key 补写
   `horse_identity_verified_keys`；不重跑则存量 dry-run 候选为 0。
5. 存量发布：`publish_p0_horse_profiles --dry-run --regions japan,hong_kong
   --output-dir runtime/horse_profile_completion/publish-<date>` → 人工审候选
   与阻断直方图 → `--approve <manifest> --reviewer <name>` → `--commit
   <manifest> --approved-sha256 <sha> --reviewer-id <id>`（按地区 ≤500/事务，
   有逐匹错误时命令非零退出）→ metrics 前后对比。
6. 回滚：下线 = 后台逐匹转 hidden，不设批量下线；代码回滚不影响已发布状态。

## 赛事去让赛清理生产写入结果（2026-07-22）

1. 生产检出原为并行任务分支 `claude/p0-horse-batch-completion`（`88d25de0`，未推送）；待 P0 合并后 main 为 `cce280a7`（含两任务），生产 `git checkout main && git pull --ff-only origin main` 快进 37 个提交。注意：ff 检出会重置脚本执行位，需先 `chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh` 再部署（exit 126 Permission denied 即为该原因）。
2. `bash ./deploy_lowcost.sh`：无迁移，web/worker/beat 重建，`/healthz/` 200。
3. 写前备份 `backups/db/pre-handicap-cleanup-20260722_023308.dump`（228136448 bytes，SHA-256 `23fc73ee8277e2dfc936df1f1d217e7b85235409d70e85d5abf6a489e2a5176b`，`pg_restore -l` 1017 项通过）。
4. artifact 随 main 进入生产仓库（`runtime/artifacts/race-name-handicap-cleanup/20260721T154923Z/dry-run.json`，SHA `30d85d1a…`），`docker cp` 进 web 容器后执行 `clean_race_name_handicap_markers --commit`（artifact/备份 SHA + 授权信息）：`written=168`，batchId `23eddf04…`；`--verify` 返回 `ok=true`（168/1550/2）。
5. 前台抽检：赛历各视图与详情页无「让赛」残留；精英杯详情 `/races/2026/hkjc-2026-0621-18/` 200；首页与金杯详情 200。容器 `/tmp` 临时文件已清理。
6. 完整审核链与证据：`docs/changes/remove-handicap-markers-from-race-names/release_report.md`。

## P0 身份回填生产执行结果（2026-07-22）

1. 部署前：容器全健康、`manage.py check` 通过、无导入锁、内外 healthz 200、磁盘 38%。
   备份 `.env.backup.p0-identity-enrichment-20260721T163603Z` 与
   `backups/db/pre-p0-identity-enrichment-20260721T163603Z.sql.gz`（226MB，`gzip -t`
   通过，SHA-256 `23818ce02edd9ac07d53a3da8dd08398aa437fde4722ce8fd7c65a23a1d8c897`）。
2. 部署：git bundle 从 `88d25de0` 快进到 `349c822f`；重建
   `web/worker/beat/race_live_worker` 镜像（`umanewsbot:prod`）并 `up -d`，nginx
   一并重启；部署后 check 通过、51 迁移零漂移、内外 healthz 与 `/horses/` 200。
3. 缓存探针（生产 `/opt/umanewsbot/runtime`，17,022 个 HTML）：NAR 仅 4 页可解析
   （16 ID，覆盖率 0.02%）→ NAR 本期不启用；HKJC 重解析得 1,036 条唯一马 ID 证据。
4. dry-run → 用户批准 → commit：
   - 日本：2,462 applied / 0 skipped / 0 冲突；identity key 覆盖率 0% → 21.1%。
   - 中国香港：327 applied（58 → 385 匹带 hkjc key，覆盖率 7.9%）。
   - 法国：1,773 条 zeturf 证据合并进 4,097 条来源 `identity_evidence`（不生成
     key；commit 报告计为 skipped 因为 profile 字段无变化，属口径说明而非失败）。
   - 英国 6,342 匹已有 key 无新增；美国 0（HRN 仅 slug，按设计不回填）。
   - 生产 ExternalHorse 12,405 条 netkeiba 记录父母/出生日期全为空，本期无法
     回填四字段，日本候选仍不能过批次四字段锁；四字段需后续数据源专项。
5. 验证：重复 commit japan applied=0 幂等；重复 dry-run 候选 0、already_present
   2,462；`p0_horse_profiles --sync-sources --commit --region hong_kong` 后
   385 匹 key 与 4,097 条 zeturf 证据完好（合并保留修复生产实证）；滚动批次
   抽样 select（`p0batch-a4d8262eadc2`，已 abandon）日本前 100 匹 100/100 带
   netkeiba key（回填前首批 0/10）；最终容器全健康、公网 healthz 200。
6. artifact 目录：`runtime/horse_profile_completion/identity-enrichment-20260722/`
   （dry-run-japan / dry-run-hong_kong / dry-run-uk-fr-us / conflict-aggregation /
   nar_probe.json / evidence_hkjc.jsonl / verify-jp-hk）。

## P0 身份回填操作手册（enrich-p0-horse-external-identity，2026-07-22）

本节是离线身份回填（identity keys + 四字段）与冲突治理的标准操作顺序。全流程
零网络请求；命令为 `enrich_p0_horse_identities`，运行账号需能读取生产数据库与
artifact 目录。前置运维边界沿用既有先例：先备份、临时 swap、停 beat/worker，
串行执行，结束后恢复。

1. HTML 缓存重解析（可选证据源，离线）：
   `python runtime/tools/reparse_horse_identity_html_cache.py --namespace hkjc
   --cache-root <本地缓存目录> --output evidence_hkjc.jsonl --summary summary_hkjc.json`；
   NAR 必须先跑 `--probe` 只读覆盖探针，`files_with_matches=0` 或 `named_ids=0`
   时 NAR 证据源本期不启用（2026-07-22 本地缓存探针实测 0 命中，NAR 未启用）。
   缓存缺失时 summary 如实记录 `cache_missing_or_empty`，不得触网补抓。
2. 按地区 dry-run（默认不落库）：
   `python manage.py enrich_p0_horse_identities --dry-run --regions japan
   --output-dir runtime/horse_profile_completion/identity-enrichment-<date>-japan
   [--cache-evidence evidence_hkjc.jsonl --nar-probe nar_probe.json] --json`。
   artifact 含候选、冲突增量、证据源统计、`metrics_before` 与 SHA-256 manifest。
3. 人工批准：核对候选与冲突后
   `--approve <manifest> --reviewer <name>`，记录 `approved_sha256`。
4. 分批 commit：`--commit <manifest> --approved-sha256 <sha>`，按地区分批、
   单事务 ≤500 profile；commit 复检 manifest 重算哈希、artifact SHA、四字段
   漂移与同 namespace 矛盾，任何一项不满足即 fail closed。报告含
   applied/skipped/conflicts 与 `metrics_after`。
5. 重跑地区 P0 来源同步（先 sync 后回填的执行顺序固化为 sync → 回填 → 增量
   对账；`_upsert_p0_source` 会合并保留已回填的 identity 证据，不会抹除）。
6. 冲突治理（只读先行）：`--aggregate [--output-dir <dir>]` 输出分组统计与
   SHA-256 manifest；`--suggest-resolutions --output-dir <dir>` 生成裁决建议
   artifact；人工批准后 `--commit-resolutions <manifest> --approved-sha256
   <sha> --reviewer-id <用户ID>` 经既有 resolved 通道写回（`full_clean()`
   校验，只触碰 pending 记录，reopen 保护不变）。
7. 完成复核：重复 dry-run 应显示候选为 0、already_present 上升；
   `metrics_before/after` 对比按地区可采信比例变化；抽样核对滚动批次
   select 能选出带 identity keys 与四字段的候选。

## P0 滚动批次产品化生产部署结果（2026-07-21）

1. 部署前：容器全部健康，内外 `/healthz/` 200，磁盘 `37%`，无外部导入运行/锁。
   备份 `.env.backup.p0-rolling-batch-20260721_154508` 与
   `backups/db/pre-p0-rolling-batch-20260721.sql.gz`（224M，`gzip -t` 通过，
   SHA-256 `93ebe2f3da940a4f2daea3d3ef559cbd97cc2d3e6f380d99a5c0e03d989cf3c5`）。
   注意：手工 `pg_dump -U postgres` 在生产会产出 20 字节空 dump（role 不存在），
   必须使用 `.env` 中 `POSTGRES_USER=horse_news` 并在 exec 时注入 `PGPASSWORD`。
2. 部署：git bundle 从 `7ad6adeb` 快进到 `b3f44d86`；`docker compose -f
   docker-compose.prod.lowcost.yml build web worker beat` 重建镜像
   `680ed3a174eb`（含 openpyxl 3.1.5）并 `up -d`。
3. 部署后：`manage.py check` 通过、无迁移漂移、镜像内 openpyxl 可用、内外
   healthz/首页/horses/races/admin 均 200。**web 重建后 nginx upstream 短暂
   502，重启 nginx 恢复；后续部署把 nginx 一并纳入重启清单。**
4. smoke：批次命令 select/abandon 在真实队列验证通过（`ベリングブルー`，
   无 identity keys 按预期待身份补强）；未触网、未写马匹资料，生产
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false` 保持不变。

## P0 滚动批次补全操作手册（productize-p0-horse-batch-completion，2026-07-21）

本节是滚动批次（每地区默认 100 匹、单批合计不超过 500 匹）的标准操作顺序。
每批复审产物为 `HORSE_PROFILE_COMPLETION_REVIEW_OUTPUT_DIR/<batch_id>.xlsx`
单独文件；正式 commit 凭证是人工批准的精确 release-candidate SHA，candidate 反向绑定
不可变 JSONL/JSON artifact、预计动作与发布范围。全部写库动作按地区独立执行；state 文件窗口由
`serial-window.lock` 保护，正式批准到 DB/publish 全窗由 `execution-window.lock` 串行化。

1. 选批（只读，不写任何资料字段）：
   `python manage.py p0_horse_completion_batch --select --regions japan --json`
   生成 pending 批次 manifest 于 `HORSE_PROFILE_COMPLETION_BATCH_STATE_DIR/p0batch-*/batch_manifest.json`。
   无 `--regions`/`--profile-id` 且无显式 `--limit-per-region` 时命令 fail closed。
2. 批准批次构成（人工）：核对 manifest 的逐马身份快照与队列排序原因后
   `--approve <manifest> --reviewer <name>`；整匹排除用
   `--exclude-profile-id`（四个模块一起排除，进入 blocker/替补池）。
3. 抓取（可中断恢复）：`--prepare <manifest> --expected-sha256 <sha>`
   默认 cache-only；触网需要 `--allow-network` 且生产
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true`。中断或预算耗尽后重复同一命令即
   resume（`skipped_unchanged/retry_failed/rerun_input_changed` 决策矩阵）。
   请求经按地区持久账本 `budget/<region>.json` 与 per-host 限速；429/超时/5xx
   有限重试（默认 3 次、基数 30s）计入账本但不计 per-candidate 常量。
4. 人工复审：打开复审 xlsx（汇总/地区 sheet/异常抽样页），抽样核对重点字段。
5. 批准回写：`--bundle <manifest> --region <region> --reviewer-id <id>`
   （reviewer 必须是 active superuser），按地区生成 research v3、mapping
   decisions、authority manifest 并追加台账。美国地区滚动批次 fail closed，
   需独立批准 authority manifest（首批冻结批准不外推）。
6. 准备发布候选（零业务写）：`--prepare-release <manifest> --region <region>
   --reviewer-id <id>`。记录 candidate/artifact SHA、expected actions、publish scope；重复执行必须
   SHA 不变。此处停止并取得针对精确 candidate SHA 的独立授权。
7. 提交：`--commit <manifest> --region <region> --reviewer-id <id>
   --release-candidate-sha256 <sha> --approved-by <name>
   --confirm-reviewed-artifact`。approved-by 必须与 reviewer 不是同一人。execution window 内复验
   真实 candidate/当前输入/ledger，生成 v2 release manifest，再 dry-run → commit → 自动幂等复验
   （planned write 必须为 0，否则命令失败报警，不自动修补）。
8. 批次放弃：`abandon` 必须给出 reason；staging 与台账保留，禁止静默清理；已有 committed
   run/checkpoint/manifest 的批次不得 abandon。

内容修复（换马、改字段）必须另起新批次新 artifact；重 commit 必须使用同一
artifact 字节。生产主机为 2 vCPU / 4 GiB / no swap：禁止无地区全量执行，
禁止绕过批次上限。

行为变化注明（对首批 50 匹链路）：source client 现在默认启用瞬时失败重试
（`HORSE_PROFILE_COMPLETION_RETRY_MAX_ATTEMPTS=3`、退避基数 30s，Retry-After
上限 300s），per-candidate 预算改为按去重 URL 计数（重试不再消耗），
`run_reviewed_p0_horse_completion_batch` 的 client 批次上限由硬编码 10 改为
`HORSE_PROFILE_COMPLETION_REGION_BATCH_LIMIT`（默认 100）。首批链路正确性不变，
但瞬时失败候选的重跑会更慢；如需保持旧行为可在对应调用显式传
`retry_max_attempts=1`。

## P0 首批 50 匹生产提交与最终验收（2026-07-20）

1. 唯一生产输入为 artifact SHA-256
   `1d7885bed20704b743465a94f3c431533c52d37fa506b96b9e11d4de6bfb922d`
   和 trusted release manifest SHA-256
   `74be2ce42f425bbd24794fb9573ee8b71348f40b0ed6fc0af8599b167c575153`。
   首次成功报告保存在
   `runtime/horse_profile_completion/p0-production-release-20260720/production_commit_report.v1.json`，
   SHA-256
   `c12980dcfb8c397a12c3e8367ffad812768d33142164987bf0fc0e201ad566ff`。
2. 首次成功 commit 为：`25 create + 25 update` profile、`1439 create`
   race records、`50` P0 source upsert、`200` module audits、业务写入计数
   `1739`、严格完整 `50/50`。此前两次因在役同步窗口门禁失败的尝试均在同一事务内回滚；
   不得把失败尝试计入业务写入。
3. 首次成功前恢复点为
   `/opt/umanewsbot/backups/p0-horse-authorized-precommit-20260719T232115Z`；
   提交后元数据修复前恢复点为
   `/opt/umanewsbot/backups/p0-horse-postcommit-metadata-precommit-20260719T235117Z`。
   后者 dump 为 `209222446` bytes、SHA-256
   `82cc39ef3e453d2ba3db716485f7fcf960379401e1eddb9d3acc210b74a972ac`，
   `.env` SHA-256
   `e24208729cfba44fd71d9b2ed343dd93d3437d3f6fb80f3f459759523158b566`，
   权限均为 `0600`，`pg_restore -l` 为 `1017` 行。
4. 元数据修复执行 revision
   `8863f37a679e9196e0bf45b5473c0e9f6657487f` 的镜像 ID 为
   `sha256:e54c82251e67d707d8b71c1d60c46089f95e572a372e797b0eb8f082109e89c1`，
   source archive SHA-256
   `31b286b2d3462fa5f6cb7883c8716f7cdee4eda26852cbb675b48228755f019d`。
   证据归档后当前运行 revision 为
   `7ad6adebb366444aa03e6e766d66fe9a49a3e2f8`，镜像 ID
   `sha256:af880cd208198c1e2ab960d8f39bd60539bdafa422cfb98890d0befbd90ff862`，
   source archive SHA-256
   `eef8d6fe5b0b757d570278afd811004bbb5e3dfc8deff0cd4e57af48b0ff0d85`。
   旧镜像回滚标签为 `umanewsbot:rollback-pre-p0-audit-fix-20260720`。
5. 元数据修复 dry-run、commit、修复后 dry-run 分别保存在同目录的
   `idempotent_metadata_repair_dry_run.v1.json`、
   `idempotent_metadata_repair_commit.v1.json`、
   `post_repair_idempotent_dry_run.v1.json`，SHA-256 分别为
   `d7835546b2e3df0b207e33959956fc4d674b9f9837a34b53ad371c543dd16903`、
   `ac9e93cec2255b56aaf2af3e880b061e8714bc6ac525c81cbc849d7d2c3d372a`、
   `6872eaa8756d4ee75b26dd22b526755c35a0f6a8fc3923d00b7f136ca3463e40`。
   修复只更新 `7` 条同批 active `HorseP0Source.racing_region`；最终 dry-run
   `planned_metadata_reconciliations=0` 且其它 planned write 全为 `0`。
6. 最终数据库对账：`50` profiles、`1439` batch records、`1432` actual starts、
   `7` non-starts、`4` overseas starts、`0` started unknown、`200` module audits；
   P0 source 五地区各 `10`。全库 `RaceEvent=9867` 未变化。run summary 首次
   `database_write_count=1739`，`last_idempotent_verification.database_write_count=7`。
7. 最终运行验收：Django check、migration drift、内外 `/healthz/`、两个 worker
   ping/active/reserved、近期 traceback/critical/integrity 日志均通过。后台抽检待译马
   `Double Major` 显示原文、中文名待补和完整资料状态；其公开 URL 返回 `404`。
   本批 `published=0`，后续公开必须走 旧规格流程 6.7 的人工发布与公开页面验收。

## P0 Phase A 首次迁移回滚与二次门禁（2026-07-20）

1. 首次 Phase A 真实生产迁移在旧 `0049_horse_career_history` 内执行数据
   `UPDATE` 后创建索引时，被 PostgreSQL 以
   `cannot CREATE INDEX stable_horseracerecord because it has pending trigger events`
   拒绝。该原子迁移已完整回滚，生产没有应用 `0049`；旧镜像和旧服务已恢复。
2. 修复后的迁移链固定为：`0049` 只新增 career/profile/record 字段；`0050` 只执行
   `backfill_career_history_semantics`；`0051` 只新增三个索引和
   `uq_horse_record_canonical` 条件唯一约束；原 authority 迁移顺延为 `0052` 并依赖
   `0051`。四个迁移均保持默认原子事务，禁止以 `atomic=False` 绕过失败。
3. 本地 PostgreSQL MigrationExecutor 必须从主线 `0048` 预置真实
   `HorseProfile/HorseRaceRecord` 后前进到唯一 leaf `0052`，验证回填、索引、约束、
   authority 字段和旧完整度降级，并完成 reverse/forward 重放。
4. 二次 Phase A 已使用修复提交 `1ddeb25f` 完成：生产迁移唯一 leaf 为 `0052`，
   `check`、`makemigrations --check --dry-run`、静态资源和 HTTP `/healthz/` 均通过；
   candidate artifact 仍未获得生产写入权限，须继续经过 Phase B trusted manifest 门禁。

## P0 美国组合来源批准后的生产门禁（2026-07-20）

1. 当前必须分层读取：冻结 v2 SHA-256
   `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7` 仍为原口径
   `40/50`；独立批准 manifest
   `29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077` 派生的 v3
   `98a7019a400f10a4bf961d869f38f770e9e98afab76b557a3c784d4eff6e470e` 在研究层为
   `50/50`；生产数据库写入仍为 `0`。
2. 美国批准口径只覆盖当前冻结批次：HRN 主记录，Fort George 补充 Sporting Life +
   Racing Post，Equibase 用于官方总出赛数、身份和颜色对账。不得写成 Equibase 官方逐场
   履历，不得全局放宽 HRN 或 `count_aligned_records_unverified`。
3. 当前 production readiness report
   `8cc36106091708827852401927a791a5575f2d6d490d1a306297e450612ed2c5` 只是
   `static_schema_compatibility_check`；`safe_simulation_performed=false`、
   `commit_artifact_compatible=false`、`decision=blocked`、`database_write_count=0`。
   blockers 精确为 `not_horse_profile_completion_plan`、
   `missing_production_profile_ids`、`missing_production_reviewer_id`、
   `missing_commit_compatible_module_approvals`。
4. prepare 只能保持 pending；apply 必须绑定固定 v2 SHA、可信 manifest SHA、调用方显式 SHA
   与实际文件 SHA。记录、身份、来源、计数漂移或重复记录必须 fail closed。
5. 两阶段 release 顺序固定如下，任何一步失败即停止：
   1. **Phase A deploy（prepare-only）**：仓库 trusted release manifest SHA allowlist 保持空；
   2. 在生产只读查询 50 匹 profile snapshot，并生成 mapping decisions 与 candidate artifact；
   3. 下载并独立审核 candidate artifact，生成绑定 v3、authority、mapping、production snapshot、
      final artifact 和 executor reviewer 的 `p0_horse_production_release_manifest.v1`；
   4. 将该 release manifest 的精确字节 SHA 作为代码变更加入 trusted allowlist，完成独立复核后
      **Phase B deploy**；
   5. 对同一 artifact 与 release manifest 运行 formal `--dry-run`，确认零写入和全部 action；
   6. 核对生产 `HEAD`、容器、`/healthz/`、锁，完成数据库备份及独立校验；
   7. 停止会写 `HorseProfile`、`TermEntry`、`TermAlias` 的自动任务，或以运行日志和数据库会话
      明确确认 commit 窗口没有相关写入；
   8. 仅对已通过上述门禁的精确 artifact 执行 `--commit`。
6. Phase A 已在生产只读生成并复核精确产物：
   mapping SHA `f888cf89566aa54de0b3656d6eeba5a2cd4fde0ec6acef86f1b9638ae415c918`，
   production snapshot SHA `20e57170ffdc033e3fee30f6cfbc9e57fe535c07e5f729c19b8ac826537c8c4f`，
   candidate artifact SHA `1d7885bed20704b743465a94f3c431533c52d37fa506b96b9e11d4de6bfb922d`。
   日本 10 匹在役马另绑定 `2026-07-20` JBIS 实时总数复核证据 SHA
   `55c365ab3a7130c3b513fb1fa79b51bf4990872a0082b1bf34792df651c14990`。
   独立 release manifest SHA
   `74be2ce42f425bbd24794fb9573ee8b71348f40b0ed6fc0af8599b167c575153`
   是本次 Phase B 唯一 trusted 值；正式 dry-run 成功前仍为 **NO-GO**。

### P0 50 匹正式 mapping / artifact / apply 命令

以下命令只描述新能力。Phase A 的 prepare 可消费已批准 mapping decisions 生成 candidate；
`--dry-run/--commit` 都必须额外消费 independently approved release manifest，并且其文件 SHA
必须已进入仓库 trusted allowlist。本批 allowlist 仅包含
`74be2ce42f425bbd24794fb9573ee8b71348f40b0ed6fc0af8599b167c575153`。

mapping decisions 顶层必须为
`p0-horse-profile-mapping-decisions.v1`、`review_status=approved`，并包含
`research_v3_sha256`、按全部逐行 `database_mapping_snapshot` 计算的
`production_snapshot_sha256`、审核人/时间/decision reference。每行必须包含完整四字段
`identity`、`bind_existing(profile_id)` 或 `create_new`、`decision_evidence`、
`database_mapping_snapshot`、四个 required module 的 approved/confidence>=90 review，以及
`racing_career_status` / `records_synced_through` 的独立 `completion_decision`。bind 行还必须
携带精确 `profile_snapshot` 与名称/alias evidence；多名称命中必须列出全部 rejected profile
ID 和理由。
mapping 的 `reviewer_id` 必须对应 active staff/superuser；它负责映射审核。candidate artifact
中的 executor reviewer 必须是 active superuser。release manifest 的 `approved_by` 是项目负责人
外部决策，不得冒充或混同 DB executor。

```bash
python manage.py apply_reviewed_p0_horse_completion \
  --prepare \
  --research-v3 /absolute/path/p0_horse_research_50_enriched_v3.json \
  --authority-manifest /absolute/path/reviewed_us_career_source_authority_v1.json \
  --authority-manifest-sha256 29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077 \
  --profile-mapping-decisions /absolute/path/approved_profile_mapping_decisions.json \
  --reviewer-id 1 \
  --output /absolute/path/to/new-formal-artifact-directory
```

`--output` 必须不存在；成功后目录只包含
`reviewed_p0_horse_completion_artifact.json` 与 `manifest.json`，并报告两者 SHA。prepare
只读数据库且数据库写入为零；其 `release_status=candidate_pending_independent_release`，本身不
授权执行。

```bash
python manage.py apply_reviewed_p0_horse_completion \
  --dry-run \
  --artifact /absolute/path/reviewed_p0_horse_completion_artifact.json \
  --artifact-sha256 '<exact-lowercase-sha256>' \
  --release-manifest /absolute/path/p0_horse_production_release_manifest.v1.json \
  --release-manifest-sha256 '<trusted-exact-lowercase-sha256>'
```

dry-run 对 artifact、release manifest、v3、authority、mapping 各只读取一次普通文件字节，
同一字节同时用于 SHA 与 JSON 解析；symlink 和非普通文件直接拒绝。命令逐行复核 DB snapshot
与计划 action；`database_write_count` 必须精确为 `0`。报告中的 `commit_table_lock_plan`
仅说明 commit 将取得的锁，dry-run 自身不得执行阻塞式 table lock。

```bash
python manage.py apply_reviewed_p0_horse_completion \
  --commit \
  --artifact /absolute/path/reviewed_p0_horse_completion_artifact.json \
  --artifact-sha256 '<same-exact-lowercase-sha256>' \
  --release-manifest /absolute/path/p0_horse_production_release_manifest.v1.json \
  --release-manifest-sha256 '<same-trusted-exact-lowercase-sha256>' \
  --confirm-reviewed-artifact
```

commit 使用首次读取后保留在内存中的 payload，不重新打开输入。它必须在 Phase B、同一
artifact/release manifest 的成功 dry-run 和备份后执行。该命令不访问网络、不创建普通比赛
`RaceEvent`；任一 reviewer/profile/identity/record/source/action 漂移整批回滚。本批只将
artifact 明确认领的履历（含 unchanged）关联 completion run，不接管其它旧 NULL 履历。

PostgreSQL commit 在 `SERIALIZABLE` 事务开始后、任何 mapping snapshot 重扫或创建前，对
`stable_termentry`、`stable_termalias`、`stable_horseprofile` 取得
`SHARE ROW EXCLUSIVE` table lock，并在锁内重扫全部 50 匹四字段身份和 mapping snapshot。
取得 table lock 前，事务以 `SET LOCAL lock_timeout = '5000ms'` 将等待上限固定为 5 秒；
超过上限即整批异常、业务零写入并释放本批 session advisory locks，不得自动放宽或盲目重试。
该锁允许普通 `SELECT`，但会让这些表的 `INSERT/UPDATE/DELETE` 等待到整批事务提交或回滚；
因此会造成一次短时马档案/术语写入暂停。执行前必须停止相关自动补全、术语维护和后台批量写入，
或确认没有并发写会话；如果无法获得安静窗口则停止 commit，不应依赖锁等待硬顶上线流量。

## P0 马首批 50 匹生产提交前 NO-GO（2026-07-19）

1. 当前五地区研究产物为 `50` 匹、`1439` 条履历记录，已复算为 `1432` 次实际出赛和 `7` 次
   未出赛；法国、英国实际出赛未知赛果为 `0`，基础/三代血统硬字段和六项血统分别为
   `650/650`、`300/300`。缺少实际出赛与多采待去重均为 `0`；Fort George 已由补充结果页
   补齐为 `13/13` 次实际出赛。
2. 这不等于 50 匹可提交生产 artifact。严格完整状态为 `40/50`：日本、法国、中国香港、
   英国 `40/40` 达标；美国 `10/10` 仅完成 Equibase 官方总数与备用逐场数量对齐，逐场官方性
   仍待授权来源或人工 Full Charts/Lifetime PP 核验。HRN 正式请求和缓存复放还必须携带并
   命中马名、父名、母名、出生年份四字段身份；缺任一字段即 fail closed。
3. 审核工作簿
   `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核-v2.xlsx`
   含 `2050` 条逐字段证据，仅用于人工核验，不能传给 `complete_horse_profiles --commit`，
   也不能替代模块级审核 CSV、diff、source evidence manifest 或冻结 SHA。
4. 在 `50/50` 前不得执行 旧规格流程 `6.5/6.6/6.7`，不得批量写生产 `HorseRaceRecord`、
   创建普通比赛 `RaceEvent` 或公开马匹。补齐后先在最新集成版本重新生成正式 dry-run
   artifact，并重新执行完整回归与独立代码审查。部署迁移时还必须抽检原
   `career_history_status=complete` 且权威性未知的旧记录已降为 `needs_review`，原
   `complete_profile_full` 已同步降为 `complete_pedigree_2gen`。
5. 任何新生成或复放的 source cache 必须为 `p0-horse-source-cache.v2`，缓存自身马名/alias
   必须命中请求马，来源总数必须具备来源名、URL 和带时区核验时间。网络 transport 必须关闭
   自动重定向，仅允许实现登记的 JBIS、HKJC、Sporting Life、Geny、HRN HTTPS 主机；跨主机
   跳转、带凭据 URL、非 443 端口或超预算均立即停止。跨 provider 补全还必须让候选四字段
   身份与资料 payload 全部一致；数据库 evaluator、研究 JSON 和工作簿必须独立 fail closed，
   不得只信 cache 入口。官方明确零出赛时允许空记录列表，其它空列表仍阻断。总数 URL 必须
   通过 Django `URLValidator`；同 provider external ID 精确不一致也必须停止。
6. 审核 `ignore` 只记录本次建议不采用，不得撤销此前 APPLIED 模块证据；部署验收需同时覆盖
   “完整档案收到 ignore 后仍完整”和“conflict/pending 继续阻断”。日本重建必须跑授权离线
   replay 的 10 匹真实样本并复算数量，不能只检查最终冻结 JSON。第 4 名及以后必须落为
   `unplaced`；年份精度履历必须保持 partial；人工主来源、佐证来源和血统 URL 均须通过严格
   HTTP(S) 校验。
7. 自动补充来源合并前必须核对同源精确 external ID 或双方完整四字段身份。审核 apply 时总数、
   来源名、URL、带时区核验时间必须整组写入或整组清空，不得借用旧记录；cache 非空硬字段还要
   通过类型、出生年范围和 ISO 日期校验。研究摘要存在官方总数时必须以官方数对账。正式 dry-run
   验收应包含非法行级 URL、模块 URL、逐场 URL 和 `source_refs` URL 的阻断样本。
8. 父母实体查询中的唯一同名结果不得自动采用；external ID 必须按不透明原值比较。最终 v2
   JSON / parent identity manifest / workbook SHA-256 分别为
   `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7` /
   `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b` /
   `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。`116` 行审核证据解析为
   `55` 个唯一父母来源身份；全部 `source_identity` 必须含马名、父名、母名和出生年。
9. 父母出生年独立 approved artifact 的 SHA-256 为
   `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`，
   `reviewed_by=codex_manual_source_review`，不得记成项目负责人逐字段审核 `55` 个出生年。
   自动 Netkeiba 父母 URL 只允许精确 `https://en.netkeiba.com/db/horse/<id>/`，不得含凭据、
   端口、query 或 fragment。Kentucky Wood 的父系必须使用 Racing Post `595446` 的 2001 年
   Balko（Pistolet Bleu / Ella Royale）；Netkeiba `000a02bd3f` 是 1925 年同名马，只能留在 v1。
10. 冻结 v1 JSON / workbook SHA-256 为
    `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd` /
    `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`，v2 生成不得修改其字节。
    工作簿 builder 默认使用 v2 JSON、`-v2.xlsx` 和 `previews-v2`，环境变量覆盖配置；任何把
    frozen v1 workbook 或 previews 作为输出目标的运行必须拒绝。历史 APPLIED
    profile/pedigree 模块 URL 也要在最终完整度验收中通过严格校验。
11. 只有正式 dry-run 全部模块审核通过后，才向用户申请该准确版本的生产授权；随后按本手册核对
   生产 `HEAD`、容器、外部导入运行数与锁、环境备份、数据库备份和 `/healthz/`，任一失败即停止。

## P0 马审核批次受控网络入口门禁（2026-07-18）

1. 该入口只允许 `complete_horse_profiles --dry-run --p0-reviewed-candidates <csv>
   --p0-review-manifest <review_manifest.json> --p0-review-manifest-sha256 <sha256>
   --allow-network --region <region>`；`--commit`
   或不带审核 CSV/审核 manifest 的 legacy dry-run 使用
   `--allow-network` 必须拒绝。`HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true`、CLI flag 与
   `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256=<同一 sha256>` 缺一不可，direct service
   调用同样检查两个 setting 和显式 expected SHA。
2. 网络模式必须显式选择至少一个地区；未选地区只读既有 cache，cache 不存在则记录
   `network_disabled_cache_missing`。不得默认扩大到五地区，也不得新建绕过现有 source client
   的 HTTP 路径。
3. 每个选中地区整批只创建一个 client，每区最多 10 匹；单马请求预算为日本 `3`、香港 `1`、
   英国 `1`、法国 `2`、美国 `3`。单马失败只生成 blocker 并继续后续候选，不能放宽 source
   validator、身份、硬字段、二代血统或完整履历要求。
4. 每次运行使用冻结的 50 行审核 CSV、对应审核 manifest、外部批准的 manifest SHA 及全新空
   output directory。解析 manifest 和创建 source client 前，必须先核对 CLI expected SHA、
   服务端 setting 与实际文件字节 SHA 三方一致，再核对 `artifact_type/decision`、CSV
   basename、SHA-256、大小和 50 行；
   验收 manifest 必须包含 `network_allowed=true`、精确 `network_regions`、
   `review_manifest_input`，总体与逐地区
   `network_request_count/cache_hit_count/cache_miss_count`，并保持
   `read_only=true/database_writes=0`。缓存发布继续使用现有 no-clobber 原子路径；整批
   artifact 必须在同父目录 staging 中生成、校验并 `fsync` 后原子发布，失败不得留下半成品。
5. 当前只完成本地代码验证：真实来源的可预期 `P0HorseSourceBlocked` 归入
   `source_cache_or_adapter_error`，同时保留异常证据和实际请求数；其他异常仍归
   `unexpected_adapter_error`。复用的底层 client 必须由逐候选代理隔离计数，不得要求底层
   `last_request_count` 可写；fetch 前的 cache 错误必须为 `0`，fetch 后读取底层只读值。
   每匹 fetch 重置请求预算计数，但不得清空同一 client 的最后真实请求时间；失败后的后续候选
   也必须继续限速。JBIS 的 `**` 只有 `cells[12]` 规范文本精确为 `除外` 或 `取消` 时才映射
   为 non-start；赛事名、缺列和未知状态不得触发。Docker `--network none` 下
   transport 调用前必须记录请求尝试和 monotonic 时间，连接/TLS/读取异常仍计数并使下一候选
   继续限速。source-client `48/48（0.450s）`、四模块 `102/102（1.040s）` 通过，Django check、
   迁移无漂移、相关编译与 diff check 通过。
   日本首批首次运行是 `9/10`；修复后受控重跑和无网络复放均为 `10/10`。该结果只能说明
   日本样本完成，不得写成 `50` 匹完成。
6. task 4.2 继续未完成；香港、英国、法国、美国字段缺口和法国 429 仍需独立方案。同一独立
   reviewer 对本审计文字追加前的完整差异最终 `APPROVED`、无 actionable finding；approved
   HEAD 为 `c2c30aeed73619767c1ca6dfb440b43c8f824d11`，fingerprint 为
   `4dfaaaff01f38c5062a29a2225ac0f7fe8371d3ceccfd12e5182731cbaf99221`，reviewer stdout
   SHA-256 为 `0780293905b1c1cdd953a02bd2386c25902021709c9144b2c466bf93ad062631`，helper raw
   stdout SHA-256 为 `8a000524fd6228570e0ac2cb036d1d475e50701a3adb5806a5130cd91fbb632c`。
   旧 fingerprint 不覆盖本段随后追加的审计文字；本段准确性以追加后的限定只读复核为准。
   本节仍不授权新的真实批次、生产写库、commit、push、merge、部署或公开，后续每个真实地区
   批次仍需针对精确输入和版本取得新授权。

### 日本首批网络 dry-run、修复重跑与离线复放证据

- run 目录：
  `runtime/horse_profile_completion/p0-reviewed-japan-network-20260718-083707/`
- batch manifest SHA-256：
  `bf8dbda389e5ffc3b9efa1f361a8cbb7b8ad5392b2e1c11c86b25d8600db49e2`
- 首次结果：`9/10 complete`、`30 requests`、`9 个新生成 cache`、`0 cache hits`、
  `database_writes=0`。
- 唯一 blocker 为コントラポスト：来源实际为 `22 actual starts + 1 除外`，旧解析把该除外行计入
  实际出赛。
- 修复重跑目录：
  `runtime/horse_profile_completion/p0-reviewed-japan-network-rerun-20260718-091156/`；
  batch manifest SHA-256：
  `9682ceebddb53a796ff058bb79a3455e89a4ad03b01ddeed7beed947dd1106b5`。结果为日本
  `10/10 complete`、`9 cache hits`、`1 cache miss`、`3 network requests`、
  `database_writes=0`，其余四地区 `network_request_count=0`。コントラポスト保存
  `23` 条履历，实际出赛计数为 `22/22`，缺口 `0`。
- 无网络复放目录：
  `runtime/horse_profile_completion/p0-reviewed-japan-offline-replay-20260718-0913/`；
  batch manifest SHA-256：
  `472785d50e5e6e7343d1ec0285cc68921a12ca7303556fa58dd21ffcc1af22c2`。Docker
  `--network none` 下日本 `10/10 complete`、`10 cache hits`、`0 cache misses`、
  `0 network requests`、`database_writes=0`；cache 目录正好 `10` 个 JSON，无临时文件。
- 前述网络重跑和首次离线复放形成于审核 manifest 强绑定与整批原子发布修复之前，只作为来源
  抓取和解析证据。加固后复放目录：
  `runtime/horse_profile_completion/p0-reviewed-japan-hardened-offline-replay-20260718-094427/`；
  batch manifest SHA-256：
  `4834e9f9f47b67a57bb1c11ee7cdc0b8338673b7e96d575a56ef1e5164332ecb`。该次在 Docker
  `--network none` 中启用网络门禁模式，审核 manifest SHA-256 为
  `aa452fb27dcf77e7821782a6302504e7abe4cf600bd6da25e9c49e7f776213bf`，审核 CSV SHA-256
  为 `f36d2f3f71fccc90a7f498f4d1c021e1a6d4275450122de599bc4b8767e240fa`；日本
  `10/10 complete`、`10 cache hits`、`0 network requests`、`database_writes=0`，最终目录
  `8` 个文件且无 staging 残留。该次形成于外部冻结 SHA 信任锚修复之前，只是中间验证。
- 最终授权复放目录：
  `runtime/horse_profile_completion/p0-reviewed-japan-authorized-offline-replay-20260718-100440/`；
  batch manifest SHA-256：
  `96ebef63ae74fa787ff786b262cebebc252f6e3c536c2aa89fc920c8d8e91210`。Docker
  `--network none` 中 CLI `--p0-review-manifest-sha256`、服务端
  `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256` 与实际审核 manifest 字节 SHA 均为
  `aa452fb27dcf77e7821782a6302504e7abe4cf600bd6da25e9c49e7f776213bf`，清单记录
  `authorized_by_setting=true`；日本 `10/10 complete`、`10 cache hits`、`0 network requests`、
  `database_writes=0`，最终目录 `8` 个文件且无 staging 残留。

## P0 马真实页面兼容的发布前门禁（2026-07-18）

- 当前仅允许离线验证，不得把保存快照解析成功升级为真实网络、生产缓存或 50 匹完成证据。
  历史 `66/66` 是 scaffold；当前候选已在真正的 Docker `--network none` 中达到
  source-client `20/20`（`Ran 20 tests in 0.057s`）和四模块 `74/74`
  （`Ran 74 tests in 0.693s`）。Django check 无问题、`makemigrations --check --dry-run`
  为 `No changes detected`，两个 service 最终使用
  `PYTHONPYCACHEPREFIX=/tmp/pycache python -m py_compile ...` 退出 `0`，
  `git diff --check` 退出 `0`。
- 五地区首次真实探针基线为 `0/5`；修复后主会话执行的不落缓存、不写数据库新鲜探针为
  `1/5`。JBIS オーロラエックス为 `15 starts / 15 records`；HKJC 缺
  `birth_date/trainer_name/breeder_name`；Sporting Life 缺 `country/breeder_name`；
  Geny HTTP 429；HRN 缺来源明确 `Starts`。后续重试或补充来源仍须保持低频、限量、可审计，
  不得由单马探针直接扩大为 50 匹批量抓取。
- HKJC 的 `Race Index` 只写 `external_race_id`，不得合成赛事名；Sporting Life 不得从
  `sire/dam/damsire` 猜完整 pedigree；HRN 不得用年龄或表格行数猜出生年份/starts；法国
  429 不得绕过。缺失字段继续 blocker，交给补充来源或人工审核。
- cache 必须用同目录完整临时文件、`fsync`、`os.link(temp,target)` no-clobber；若目标已存在，
  重新读取并严格校验 canonical cache，再 normalize/return。不得持有锁跨网络，不得覆盖赢家
  cache，失败必须清理临时文件。
- 任务 4.2 仍未完成；日本首批已为 `10/10`，其他地区仍需真实缓存与补充来源/人工字段。
  在这些缺口与当前任务的新发布授权全部完成前，禁止 commit apply、生产写入或公开。当前实现已由同一独立
  原生 reviewer 定向复审为 `APPROVED`，但这一项通过不能替代其余门禁。

## P0 马已审核候选离线基线 dry-run

1. 输入必须是已冻结审核 CSV，严格满足五地区各 10、候选键唯一、全部 `reviewed=True`、`review_decision=confirm_batch_inclusion`。当前输入为 `runtime/p0_horse_candidates/production-reviewed-20260718-all-50-approved/p0_participant_sample_review.reviewed.csv`，SHA-256 `f36d2f3f71fccc90a7f498f4d1c021e1a6d4275450122de599bc4b8767e240fa`。
2. 只读基线命令必须在无网络容器运行，并显式提供审核 CSV、缓存和全新输出目录：

   ```bash
   python manage.py complete_horse_profiles \
     --dry-run \
     --p0-reviewed-candidates /app/runtime/p0_horse_candidates/production-reviewed-20260718-all-50-approved/p0_participant_sample_review.reviewed.csv \
     --cache-dir /app/runtime/horse_profile_completion/cache-empty-20260718 \
     --output-dir /app/runtime/horse_profile_completion/p0-reviewed-baseline-20260718-0500
   ```

3. 命令固定 `allow_network=false`，不得用它绕过地区来源客户端、限速、缓存或请求预算。输出目录非空时必须停止，不得覆盖已有 run。
4. 当前基线为 `50 processed / 0 complete / 50 blocked / 0 network requests / 0 database writes`，batch manifest SHA-256 为 `2028e03a8e5edaa386e101cd159406559192844c02a9979d363e1dbece571110`；日本和美国共 20 匹还包含身份补强 blocker。只有后续受控来源缓存完成且重新 dry-run 通过，才能进入模块人工审核。
5. 本节不授权生产 commit、自动首次公开或真实网络抓取。发布前仍需独立代码审核、最新用户授权、生产 HEAD/容器/health/锁/备份门禁和主线迁移冲突处理。

## P0 马生产只读候选提取结果（2026-07-18）
## P0 马候选提取与完整生涯门禁

1. 候选提取必须先以 `--extract-candidates` 运行到新目录，核对 `read_only=true`、五地区、九类等级、身份状态分布和 manifest SHA。
2. 提取阶段禁止 `--commit`、资料网络请求以及创建 `TermEntry`、`HorseProfile`、`HorseP0Source` 或 `HorseIdentityConflict`；执行前后核对相关表计数。
3. 日本、香港、美国缺 horse ID 时不得按同名自动合并；英国、法国 external ID 必须保留来源 namespace。
4. 完整生涯必须按马采集，不得从重点赛事总账反推，也不得为普通比赛强行创建 `RaceEvent`。
5. 资料 commit 仍需独立审核 artifact、写前备份和显式授权；本节不授权网络抓取、生产同步、履历写入或自动首次发布。
6. 集成到最新主线时，P0 migrations 必须顺接主线 race-live migration leaf，不得恢复历史并行 `0032/0033` 图。

## 五地区准实时 Beta Gate 修复生产发布（2026-07-20）

1. 发布身份：fingerprint
   `231f8a68707f4b946daf1d355f5848cd107e13bbfa6c1ed856a0de2a31b22b4d`，
   commit `58f00961f2cd9750d1285f7d6229494903e975a5`，tree
   `de529e244a3ad21a1c6d72fc50b254d37e080e20`，source archive SHA-256
   `1209353f4949c1fed7cbf58756e75e54f08c6bc0a8bdec996a7d1a2c78c43b08`。
   正式 AMD64 image ID 为
   `sha256:f9681a60f5072c39ae7cc66bad9881e719a7d24698050b4ae57858f94b310eef`。
2. 恢复点：
   `backups/db/pre-race-live-gate-58f00961-20260719T161644Z.dump`，
   `205,411,102` bytes、SHA-256
   `1aa9fc306a5a5039f835f873224f5c768be95265d8bd85674bba311f320404f1`，
   `0600` 且 `pg_restore -l` 通过；环境备份为
   `.env.backup.pre-race-live-gate-58f00961-20260719T161644Z`，SHA-256
   `e24208729cfba44fd71d9b2ed343dd93d3437d3f6fb80f3f459759523158b566`。
   旧 image tag 为
   `umanewsbot:rollback-pre-race-live-gate-58f00961-20260719T161644Z`，指向
   `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`。
3. filtered env 路径为
   `/opt/umanewsbot/runtime/race_live_rollback/race-live-gate-58f00961-20260719T161644Z/rollback.filtered.env`，
   SHA-256
   `cda13ce08c6a6d03ffcb4812cf1e1bc1d56fa7eae2244d7cf72330869811062e`。
   bundle manifest 位于同目录
   `bundles/race-live-gate-58f00961-20260719T161644Z/manifest.json`，SHA-256
   `e6e3e1ef848009903ab2a62ea77eba2a4e3d9289a8d93759eb9c9de7dd4609f5`；
   根目录/最终目录为 `0700`，env、manifest、report 和 sha ledger 均为 root-owned
   `0600`。
4. Beat 先停止，普通新闻任务自然排空；随后普通 worker 和 race-live worker 停止，
   `celery/race_live` queue 和 active claim 均为 0。maintenance dry-run/apply 后 event
   `924` 隐藏；同一 immutable image/env/manifest 的 one-shot 顺序
   `validate -> restore-policies-coarse -> validate -> restore-policy-event` 全部成功，
   最终 validator 通过，event 恢复 revision `2`、7 条结果和公开暂定标识。
5. `stable.0048_raceeventrunner_external_runner_identity` 已应用；web 健康后再重建普通
   worker/race-live worker，最后重建 Beat。四个 app service 的 image/revision 均与第
   1 项一致。scheduler/monitor=false、enabled regions 空、active claim/race-live queue
   为 0；HTTP 本机与公网 healthz、首页、赛事日历和 event `924` 详情均为 200。
6. 法国重验 run 为
   `runtime/race_live_racecards/production-racecard-france-733-735-gate-fix-20260719T163001Z`。
   成功 run 实际使用的 registry v2 digest 为
   `7aca49ff1df7573ebfe6a9e403eefca5c9e64d8ee18d8d3be383d67803db550a`；
   使用旧手册值 `60fcc081…ad402` 的首次调用在网络前被拒绝。成功 run 请求
   today/tomorrow 各一次，
   `matched=1/3 / blocker=racecard_not_found`，没有
   `racecard_schema_invalid`，也没有 manifest。report/requests SHA-256 分别为
   `f81cf27666f8e026db4dd30d107f500205366d96ef3c45bf373879e68d22d517`、
   `8c0a80775253b32ff6e3caa1d1e31244786c531116d5dad478d303977e197246`。
   本次未对该 run 执行 initializer；法国 events `733–735` 的
   tracking/control/allowlist 继续不存在。

## event 924 kill-switch 实际演练（2026-07-19）

1. 用户确认 event `924` 已错过的 promotion 后 15 分钟 probe 不追溯补证，改由下一场
   获准公开灰度赛事重新验收；本节不宣称该 SLA 已通过。用户另行明确授权 event `924`
   disable、公开隐藏验证和 restore。
2. 演练继续使用 bundle
   `/opt/umanewsbot/runtime/race_live_publications/event924-public-91cf50ad-20260719T042103Z`；
   宿主目录/文件仍为 `0700/0600`，disable SHA 为
   `d441e0a1f134847abd4ebf3cf39c55c41be46d587723528e98958faa30014949`，
   restore SHA 为
   `cf96afb6363ed7621c7a153234b075e8708b544907956ca1745503739065cf6c`。
3. disable 按 dry-run、`--apply --confirm-apply`、独立 `--verify` 顺序执行；三次均
   `ok=true`、event `[924]`、零网络请求。OperationLog `105224` 创建于
   `2026-07-19T05:14:25.394898Z`，event policy 从 `provisional_public v2` 变为
   `shadow v3`。
4. disable 后详情与日历 HTTP 均为 200。详情不再包含“冠军 · 暂定”“暂定赛果”“尚待
   官方来源复核”或“赛果已确认”；日历保留赛事入口，但 live result 前五摘要消失。
   数据库仍有 revision `2`、publication `1`、legacy result `7`、observation `2`、
   marker evidence `1`、resolved incident `1`。
5. restore 在 apply 前重新 dry-run，再执行 apply 和独立 verify；三次均
   `ok=true`、event `[924]`、零网络请求。OperationLog `105225` 创建于
   `2026-07-19T05:17:11.592720Z`，event policy 恢复为 `provisional_public v4`；
   shared global/UK/TRA policy 保持 v2，allowlist 仍为 event `924`、enabled、
   `provisional_public v2`。
6. restore 后详情恢复中文暂定标识和 1–7 顺序，日历恢复前五摘要，仍不显示“赛果已
   确认”。`/healthz/` 为 200；四个 app service scheduler 均为 false，tracking
   disabled、next poll null，`race_live/celery` queue 均为 0，live worker
   active/reserved 为空。演练没有触及其他赛事，最终保持 event `924` 暂定赛果公开。

## event 924 暂定赛果公开灰度生产实证（2026-07-19）

1. 用户在最新成功 review 后授权精确冻结版本；release commit 为
   `91cf50ad677a1b8c9b253528c9db98481fd1031a`，生产 image 为
   `sha256:700ea78698fb67de602fb7e5447b997610e24e64de29df4591e4bb9e476087ef`。
   `stable.0046` 已应用，四个 app service 的 OCI revision 均与 release commit 一致。
2. 写前 custom-format 备份：
   `/opt/umanewsbot/backups/db/pre-event924-provisional-public-20260719T040646Z.dump`，
   `202,483,514` bytes、SHA-256
   `a76c9d4788b36af08f64f4a9eddc90bc0a4ef4ecd239508bb5e40abffbe9e5be`；
   `0600` 且 restore list 有效。旧镜像回滚 tag：
   `umanewsbot:rollback-pre-event924-ebab4aa8-20260719T041339Z`。
3. `RACE_LIVE_PUBLICATION_ARTIFACT_ROOT=/run/race-live/publications`，只有
   race-live worker 持有 publication rw mount。QQ SMTP 使用 `smtp.qq.com:465 / SSL`，
   报警目标 `754652181@qq.com`；promotion 前真实测试邮件返回 `sent=1`。
4. BHA Results、event fixture/result 和 terms 均由 release operator 使用普通浏览器
   人工确认；未调用页面后端 API、脚本抓取或批量下载。官方结果为 Newbury `3:02pm`
   Hackwood Stakes，1–7 顺序与已存 provisional revision 一致。
5. bundle：
   `/opt/umanewsbot/runtime/race_live_publications/event924-public-91cf50ad-20260719T042103Z`。
   promotion SHA 为 `2fedb9d3…ec3ba`，disable SHA 为 `d441e0a1…14949`，restore SHA
   为 `cf96afb6…cf6c`；目录 `0700`、文件 `0600`、无 symlink。
6. promotion dry-run/apply/verify 均 `ok=true`、event `[924]`、零网络请求；commit time
   为 `2026-07-19T04:37:17.201536Z`。四层 policy 和 allowlist 已到 v2，revision `2`
   published，legacy result `7`，tracking disabled，scheduler false。
7. 首次 BHA receipt SHA 为 `955ac30b…23673`，私有截图 SHA 为
   `77b77a03…5a480`；dry-run/apply/replay verify 均为 `comparison=match`。incident `1`
   在 `04:40:32.495902Z` resolved，早于 `04:52:17.201536Z` due time，无告警邮件，
   页面继续 provisional。但截图 observed at 为 `04:19:39Z`，早于 `04:37:17.201536Z`
   promotion commit，故不能证明 promotion 后 15 分钟内的新浏览器 probe；该 SLA
   验收未完成。
8. 首次发布收口点的 HTTP 详情和日历均为 200，中文暂定标识、1–7 顺序、缺失字段和共同
   read gate 通过。当时 disable 只完成 dry-run；后续实际 disable/隐藏/restore 演练
   结果见上方专节。
9. 第一次等待 SMTP 配置期间恢复 Beat 时，Compose 因依赖配置重建了 db 容器；持久卷保持，
   db 恢复 healthy，随后 promotion dry-run 再次通过，未执行数据恢复。最终 historical
   preflight 为 `migration_safe`，历史 enabled/network false，tracking/allowlist universe
   均为 `[924]`，race-live queue 为空，HostBudget 保持 failures 0、lock version 22。
   本次发布已生效。第 8 项 kill switch 后续已经完成；第 7 项 15 分钟 SLA 按用户决定
   转入下一场获准公开灰度赛事重新验收。

## event 924 暂定赛果公开候选（2026-07-19，尚未授权发布）

本节是最新代码候选的发布前操作契约，不构成发布授权。只有未参与实现的 reviewer 完整
review 成功、记录精确 fingerprint/approved parent/content manifest，并取得该冻结版本的
新用户授权后，才可执行以下步骤。当前不得部署、生成生产 bundle、改 policy 或访问 BHA。

1. 保持唯一范围为 event `924`，核对 tracking/allowlist universe 均为 `[924]`、四层
   policy `shadow v1`、scheduler false、claim/queue/active/reserved/one-off 为空，
   observation `1`、result revision `2`、publication/legacy result/incident 为 `0`。
2. 停止 Beat 并排空相关 worker 后，创建 custom-format PostgreSQL 备份；验证 nonempty、
   `0600`、SHA-256 和 `pg_restore -l`。部署精确受审 image，应用 `stable.0046`；迁移只
   增加 nullable/default-empty 治理字段，不回填、不晋级。
3. 宿主先创建
   `/opt/umanewsbot/runtime/race_live_publications` 为 `root:root 0700`，设置
   `RACE_LIVE_PUBLICATION_ARTIFACT_ROOT=/run/race-live/publications`。三份 Compose
   只允许 `race_live_worker` 获得该目录 rw；web、普通 worker 和 Beat 不得获得永久挂载。
   同时配置 `RACE_LIVE_ALERT_NOTIFY_EMAILS`；默认安全复用既有运营 warning/翻译失败
   收件人，但生产必须显式核对非空目标，并在 promotion 前完成 SMTP 真实投递 preflight。
4. release operator 用普通浏览器人工确认受审 BHA Results 入口可用、route registry/
   terms 未过期。不得调用页面后端 API、脚本抓取或批量下载；官方结果尚未出现不阻止明确
   标注的暂定首发，但入口或 contract 已不可执行时停止。
5. 在 `race_live_worker` 内生成独占 bundle：

   ```bash
   python manage.py prepare_race_live_publication_transition \
     --event-id 924 \
     --approved-commit <release-commit> \
     --run-id <unique-run-id>
   ```

   审核输出目录 `0700`，promotion/disable/restore/report/SHA ledger 全部 `0600`；记录
   三份 manifest 的完整 SHA。实际命令前须确认管理命令帮助中的 artifact-root 参数与
   受审版本一致，不使用聊天中的推测路径。
6. promotion 必须按同一文件依次 dry-run、apply、verify：

   ```bash
   python manage.py transition_race_live_publication \
     --manifest <absolute-promotion-manifest> \
     --expected-manifest-sha256 <sha256> \
     --expected-approved-commit <release-commit>

   python manage.py transition_race_live_publication \
     --manifest <absolute-promotion-manifest> \
     --expected-manifest-sha256 <sha256> \
     --expected-approved-commit <release-commit> \
     --apply --confirm-apply

   python manage.py transition_race_live_publication \
     --manifest <absolute-promotion-manifest> \
     --expected-manifest-sha256 <sha256> \
     --expected-approved-commit <release-commit> \
     --verify
   ```

   verify 必须 `ok=true`，并报告 incident `open/overdue`；页面仍是 provisional，
   event finished、`result_confirmed_at=null`，1–7 顺序不变，tracking disabled，
   provider timing/hash/failure 字段不变，scheduler 仍 false。
7. 在同一维护窗口、promotion commit 后 15 分钟内，用普通浏览器读取 BHA 客观 marker/
   名次，并在安全私有目录准备仅含许可字段的 submission JSON；先运行
   `prepare_race_live_manual_official_evidence` 生成 `0600` receipt，再用
   `apply_race_live_manual_official_evidence` 默认 dry-run 和显式
   `--apply --confirm-apply`。命令必须提供 expected receipt SHA/approved commit；
   conflict 还必须提供预生成 disable manifest 的精确路径/SHA。默认 dry-run 与 apply
   共用 locked planner，必须返回预期 comparison/alert status 和
   `notification_side_effect_count=0`；若 stale revision、closed/missing incident、
   participant 或 policy/allowlist/disable CAS 漂移，禁止 apply。

   ```bash
   python manage.py prepare_race_live_manual_official_evidence \
     --input <absolute-0600-submission-json> \
     --run-id <unique-manual-run-id>

   python manage.py apply_race_live_manual_official_evidence \
     --receipt <absolute-receipt-json> \
     --expected-receipt-sha256 <receipt-sha256> \
     --expected-approved-commit <release-commit>

   # conflict receipt 的 dry-run/apply 还必须在同一命令追加：
   # --disable-manifest <absolute-disable-manifest>
   # --expected-disable-manifest-sha256 <disable-sha256>
   # 只在 dry-run、receipt 和可选 disable manifest 全部复核后：
   # 在同一命令末尾追加 --apply --confirm-apply
   ```

8. match 应只 resolve incident，页面继续 provisional；conflict 必须在同一事务收紧
   event policy 并立即隐藏；unavailable 不创建 official observation/marker，保持
   open/provisional。apply 的第一阶段必须原子提交 probe、该 receipt 的 `OperationLog`
   和 incident 级 `QUEUED NotificationLog` durable intent；只有第一阶段成功 commit 后，
   第二阶段才允许真实发送运营邮件并将 intent 写为 `SENT/FAILED`。必须核对
   `NotificationLog.status=SENT` 且 `alert_sent_at` 非空；若为 `FAILED`，
   `alert_sent_at` 必须为空，修复 SMTP/收件人后用同一 receipt 重放，直到 SENT。若进程在
   第一阶段 commit 后、delivery 前退出，重放必须复用已有 QUEUED intent 继续投递。
   主事务晚期写入/commit 失败时必须零 SMTP 且不残留 intent/probe/operation 部分状态。
   SENT 后，同 receipt 重放不得重复发信；具有新 observed/evidence 的另一 receipt 应继续
   推进 probe 并写新的 OperationLog，但同一 incident 不得重复发信。禁止用“调用 apply 后
   transaction rollback”模拟 dry-run。任何 mixed post-state、artifact/commit/registry/
   event/revision/participant 漂移都停止，不人工补写。
9. 无论 BHA 路线结果如何，都演练预生成 disable 的 dry-run；只有明确需要隐藏时才 apply。
   disable/restore 每一步执行前都重新 dry-run，不删除 observation/revision/publication/
   incident。结构性异常才考虑恢复发布前数据库备份。

发布后浏览器验收详情页与日历的共同 read gate、中文暂定标签、缺失字段、无缓存即时隐藏；
同时检查 `/healthz/`、容器 revision/image、Celery 队列、scheduler=false、资源和
tracking/allowlist universe。生产事实只能在部署完成后按 evidence-only allowlist 追加，
并复用本需求同一代码 reviewer 审核。

## event 924 有界单赛事 shadow 轮询结果（2026-07-18）

1. 授权范围只覆盖 event `924`，以数据库 `next_poll_at` 为唯一时钟，scheduler false、
   四层 policy shadow、不得扩展赛事或公开。执行前 tracking/allowlist 均为 `[924]`，
   observation/result/publication/incident 为 0。
2. 本轮恢复点为
   `/opt/umanewsbot/backups/db/pre-race-live-window-924-ebab4aa8-20260718T111221Z.dump`，
   `198,273,152` bytes、`root:root 0600`、SHA-256
   `efa68a76f7236f7454fe9119df601ff4f1e4fae9d2b8040fc09aa9cf28efd13b`；
   `pg_restore -l` 通过。
3. 临时控制循环不得调用全局 selector；每轮只查询 event `924`，到期后用 owner
   generation 1、TTL 120 秒领取单赛事 claim，并只投递到 `race_live`。首轮脚本把
   `RaceEventLiveClaimDecision.claimed` 误写成 `applied`，在 task 投递前失败；保留并复用
   已写入的 generation 2 active claim，在 TTL 内于 `11:33:50Z` 投递
   `a5e03b1a-6c7b-409b-ba16-096e575b63f4`。不得重新 claim；修正字段后继续。
4. generation 2–14 共 `13` 次 task 均为 `SUCCESS / pre_off_wait`，没有结果 API 请求。
   generation 15–18 分别在 `14:02:09Z`、`14:05:17Z`、`14:08:27Z`、`14:11:34Z`
   发出一个受 HostBudget 约束的请求，均为 `SUCCESS /
   the_racing_api_result_not_found`，checkpoint 按 3 分钟窗口推进。
5. generation 19 于 `14:14:40.843702Z` claim，task
   `9615a5f6-bc5c-4203-931d-32990b07432b` 在 observation 时间
   `14:14:42.301344Z` 返回 `processed=true / the_racing_api_shadow_applied /
   revision_id=2`。距预计开跑 `14:02:00Z` 为 `12` 分 `42.301` 秒。首个 shadow
   result 到达后控制循环立即退出；不得执行 next poll `14:24:42.301344Z`。
6. observation ID `1` 为 provisional、parser `the_racing_api_free_v1`、permission
   `licensed_api_automation`、parse warning `0`，normalized SHA-256 为
   `4d2fa8c03ad3ae735700bd72291f822ea53e75449f90f3ad568392e2995dccc2`。
   revision ID `2` 为 result revision no. `1`，supplemental authority、conflict none，
   `7/7` finished item 与 `1–7` 名次完整，evidence `1`，`published_at=null`。
7. 停止后 tracking 为 `provisional_result / shadow_applied`，claim 为空、failures 0；
   HostBudget failures 0、error 空、circuit 关闭。tracking/allowlist 仍只有 `[924]`，
   四层 policy 仍为 shadow；legacy result/publication/marker evidence/incident 均为 0。
8. `.env` 和 live worker 均为 `scheduler=false / runner=the_racing_api_free`；live queue、
   active/reserved、one-off 为 0。公网赛事详情和两个正式域名 healthz 均为 200，页面没有
   shadow participant 或赛果标识泄漏。本授权已消费，后续 probe、scheduler、其他赛事和
   公开均须新授权。

## event 924 TRA shadow runner 启动检查（2026-07-18）

1. 启动前确认 production tracking/allowlist 精确全集均为 event `924`，四层 policy 为
   shadow，owner generation 1，result/observation/publication/incident 为 0；
   `race_live` 队列和 worker active/reserved 为空。
2. 数据库恢复点为
   `/opt/umanewsbot/backups/db/pre-race-live-shadow-924-ebab4aa8-20260718T102543Z.dump`，
   `198,234,122` bytes、`0600`、SHA-256
   `bc06babe341e25a45ba097aaed157c7530994e06edebc497f612642d30676207`，
   `pg_restore -l` 通过。对应 `.env` 备份
   `/opt/umanewsbot/.env.backup.pre-race-live-shadow-924-ebab4aa8-20260718T102543Z`
   为 `0600`，与变更前原文件逐字节一致。
3. 运行配置只把 `RACE_LIVE_RUNNER_MODE` 设为 `the_racing_api_free`，保持
   `RACE_LIVE_SCHEDULER_ENABLED=false`；只重建 `race_live_worker`，image/revision/tree、
   secret ro、registry digest 与资源限制不变。首次定向 ping 在启动窗口内超时；容器无
   restart，随后节点 `celery@81ec88d9e165` 的 ping、active/reserved 正常。
4. 不得提前 claim。event `924` 在 `next_poll_at=10:32:21.495909Z` 后于
   `10:33:03.874928Z` 被精确 claim；owner generation 1、claim generation 1、TTL 120 秒。
   唯一 task `7ba0699c-02f1-4b7d-864e-ed5cb7127ff0` 只投递到 `race_live`，最终为
   `SUCCESS / processed=false / pre_off_wait`。
5. checkpoint 后 claim 释放，next poll 为 `11:33:04.049149Z`。HostBudget 四个关键字段
   无变化，故本次没有网络请求；result/observation/publication/incident 仍为 0，live
   queue、active/reserved 和 one-off 为空。
6. 只有 live worker 的 runner mode 已启用；web/普通 worker/Beat 当前仍为 disabled，
   所有服务 scheduler false。公网详情为 200 且没有 participant/result shadow 泄漏。
   scheduler 关闭时 next poll 不会自动触发；后续有界 event 924 shadow 轮询需新授权，
   不能借此打开全局 selector、扩大赛事或公开。

## event 924 initializer 生产结果（2026-07-18）

1. 用户授权的唯一输入为 event `924` 与 manifest SHA-256
   `ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`。
   执行前 checkout/OCI revision 为 `ebab4aa8…9992b`，image 为
   `sha256:4443a9c…55dc`；manifest/companion、event CAS、空历史租约、空 live queue 与
   scheduler false/runner disabled 全部通过。
2. 写前恢复点为
   `/opt/umanewsbot/backups/db/pre-race-live-init-924-ebab4aa8-20260718T100040Z.dump`，
   `198,147,827` bytes、`root:root 0600`、SHA-256
   `e57218e77a1457c2aca7053d962d09b38942d4ad7cd9534185713236a61370fe`；
   custom-format 且 `pg_restore -l` 通过。
3. one-off web 只读挂载完整获准 run；dry-run、单次
   `--apply --confirm-apply`、独立 `--verify` 均以同一 manifest/commit 执行，三次均返回
   `ok=true / error_count=0 / event_count=1 / participant_count=7 /
   replayed_event_count=0`。不得再次 apply；OperationLog ID 为 `105221`。
4. event 写后为 `scheduled / 2026-07-18T14:02:00Z / Europe/London 15:02`；
   projection control 为 `live / generation 1`，tracking 为 `racecard_ready` 且无 active
   claim。TRA source 为 approved supplemental，automation allowed；7 个 participant 与
   source identity、racecard revision 1 和 7 个 declared item 完整。
5. global/source/region/event policy 均为 shadow；allowlist 为 enabled、上限
   provisional public，但当前有效模式仍是 shadow。result pointer、legacy result、
   observation/evidence、result revision、revision publication、official marker/evidence/
   incident 全为 0，racecard revision 未发布。
6. 公网赛事详情为 200，只显示客观 `15:02`，不显示 shadow participant 或任何 live
   result badge。scheduler false、runner disabled、live queue/one-off 为 0，站内与公网
   HTTP healthz 为 200。后续若启动 event 924 TRA shadow runner，必须另行授权并保持公开
   模式不变；本次 initializer 授权不覆盖 runner、scheduler 或公开。

## event 924 退避重试 prepare 结果（2026-07-18）

1. 重试前 HostBudget 的 `next_allowed_at` 已过去，`consecutive_failures=1`、circuit 未开；
   event `924` 仍为 `2026-07-18 / NEWBURY / G3 / scheduled`，四个 app service 仍运行
   获准 image `sha256:4443a9c…55dc`，scheduler false、runner disabled、live queue 与
   one-off 为 0。
2. 用户授权范围内唯一有效联网 run 为
   `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-retry-20260718T093207Z`。
   today GB 为 `200 / 215,646 bytes / 1,425 ms / SHA-256 4b4385a7…9b1d`；
   tomorrow GB 为 `200 / 76,616 bytes / 1,184 ms / SHA-256 14364e39…6128`。
3. run 为 `completed=true / request_count=2 / blockers=[]`。manifest/report/requests
   SHA-256 依次为 `ee9d0d43…1432`、`96cb3acb…fdc2`、`cf45c566…d32`；目录 `0700`，
   三文件 `0600`，manifest 内 companion hashes 与宿主重算一致。
4. manifest 唯一事件为 event `924`、external race
   `rac_13000002795`、`2026-07-18T15:02:00+01:00`、`7` 匹 declared participant；
   审计无 raw、secret、credential、第三方 rating/comment 字段。
5. prepare 只更新 HostBudget 成功结果，没有写 event 或 live 业务事实。执行后赛事、
   runner、result 为 `9,867 / 100,132 / 91,897`，全部 live 事实表、policy/allowlist、
   queue 和 one-off 仍为 0；HostBudget 为
   `consecutive_failures=0 / last_error_code="" / circuit_open_until=null`，HTTP healthz
   为 200。
6. 成功 manifest 不是 initializer 授权。未取得对精确 manifest SHA
   `ee9d0d43ac52c1678ddce61dbd7c4a6b0c0630eb02d2dd6fd8e43cfc5fcd1432`
   的单独授权前，不得运行 initializer dry-run/apply/verify，不得启动 shadow、scheduler、
   runner 或公开。

## 英国 Group 后缀修复生产发布结果（2026-07-18）

1. 用户在最新成功 review 后授权的提交
   `ebab4aa8e4e855d644771584c010fa6b07b9992b` 已部署。tree 为
   `f9a04eccc5bbda31a2619f3642e32c51275f0cc2`，source archive SHA-256 为
   `75939622bb5a31b524fc7e339109c64565ef038f8ead1734d20905ece5a937b5`，生产 AMD64
   image 为 `sha256:4443a9c418dd696c7faa4afec0ae34551bceec2e85d6c917fa27de706fe155dc`。
2. 发布前 Beat 已停止，普通任务排空为 `active=0 / reserved=0 / confirm=0` 后才停止两个
   worker。数据库恢复点为
   `/opt/umanewsbot/backups/db/pre-racecard-grade-ebab4aa8-20260718T090735Z.dump`，
   `198,033,727` bytes、`0600`、SHA-256
   `17ba9ccbe0e28fe765f0f449c78452664f39f204011a1b8decb873240afd3db0`，
   `pg_restore -l` 通过。旧 image 回滚标签为
   `umanewsbot:rollback-pre-racecard-grade-ebab4aa8-20260718T090735Z`。
3. 镜像内 registry digest 为 `60fcc081…ad402`；Django check、migration check、model
   drift、racecard sync `20/20` 通过。部署后四个 app service 的 image/revision/tree
   一致；web/普通 worker/Beat 无 secret 或 racecard artifact，只有 live worker 保留
   `/run/secrets:ro` 与 `/run/race-live/racecards:rw`。内外 healthz 为 200。
4. `RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`，live queue、
   publication policy 与 allowlist 均为 0；赛事、runner、result 和所有 live fact 表守恒。
5. event `924` 的新 run 为
   `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-fix-20260718T091135Z`。
   today GB 为 HTTP 200，tomorrow GB 为 HTTP 429，因此只生成 blocker report/request，
   没有 manifest。report/request SHA-256 为 `3e37ecef…d91b` / `7c0ca959…d5d5`。
6. 该 run 不得进入 initializer，也不得手工复用 today 响应构造 manifest。若需要新 run-id
   退避重试，必须先取得显式联网重试授权；仍受每 run 最多两个请求、HostBudget 和完整
   today/tomorrow 成功门禁约束。

## 历史赛事批量公开与距离单位展示（2026-07-18）

1. 批量公开入口为 `python manage.py publish_historical_race_targets`，必须提供固定 scope 路径及其完整 SHA-256；先执行默认 dry-run，再显式 `--apply`，最后独立 `--verify-only`。scope schema 固定逐目标 ID 和 artifact SHA，命令不得从当前数据库动态扩张范围。
2. 写前必须生成 custom-format PostgreSQL 备份、计算 SHA-256 并通过 `pg_restore -l`。本轮基线为 `/opt/umanewsbot/backups/db/pre-historical-publication-8dec0076-20260718_041218.dump`，`195,414,204` bytes，SHA-256 `83a7524eb36bdb69e9cece8a749115022e9b94682b9dd37080df5756358a9d29`。
3. 本轮 scope 为 `/opt/umanewsbot/runtime/historical_publication/eligibility-20260718_031331/publication-scope-v1.json`，SHA-256 `c27491e4987a548a6c635c936b28211a1c0e2e1c8c0bd594b8467bfba539977a`，共 `8,867` 个目标。dry-run、apply、独立 verifier 均为 `8,867 / 0 errors`。
4. apply 只在单一进程中临时设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`，必须保持 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；成功后清理赛事列表和详情缓存。常驻环境不得为了展示已发布赛事而打开历史写门或网络门。
5. 浏览器验收至少覆盖日本、中国香港、英国、法国、美国各一场，检查列表、详情、出马表、赛果、历届和移动端横向表格；纯数字距离必须显示地区正确单位，已带单位值不得被二次追加。
6. 当前生产代码 revision `4af5e20a3c65ddad81bcf054f7fd1cb1f8d0dfde`、tree `32928369f7c20c74425902ba3d13932d7a0c0043`，四个 app 服务统一运行 image `sha256:111dbe46ba7a7024632ba2ca7c57c387b19ab39861f0147421a0245d08c38d7a`。回滚标签 `umanewsbot:rollback-pre-distance-display-20260718_0444` 保留上一历史公开镜像。
7. 当前生产磁盘可用约 `1.6 GiB`，低于 historical runner 的 `5 GiB` 硬门槛。禁止在生产进行重型抓取、解析或镜像构建；后续抓取继续使用本地 Docker，生产只接收紧凑 artifact 的串行 apply。

## 准实时赛事赛果首次生产发布结果（2026-07-18）

1. 已发布 revision `4f11b2273fd167c69d54b338a4e627a77dd010c2`、tree `277cb10ad56aee9a3156fa2b1632dd73377054c8`、source archive SHA-256 `e957e748b82b4933eeaab2f5721185e42e6f4e58b9e552ee10cfabace11ca2d5`。生产 app image 为 `sha256:c2b9e15e037406808bef1edbbef888728a8f0d6ae40c47418c6cd4e414803966`；web、普通 worker、Beat 和 `race_live_worker` 的 image/revision/checkout 一致。
2. 写前备份为 `/opt/umanewsbot/backups/db/pre-realtime-race-results-4f11b227-20260718_034437.dump`，`195,161,786` bytes、权限 `0600`、SHA-256 `f81a11ece1b75f5ff680e445b71b910ea453ee1fc26eeb24ac8df030daf72a01`，`pg_restore -l` 通过。环境备份为 `/opt/umanewsbot/.env.backup.pre-realtime-4f11b227-20260718_034437`；回滚标签 `umanewsbot:rollback-pre-realtime-4f11b227-20260718_034437` 指向 `sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`。
3. `stable.0033` 至 `stable.0045` 已应用；check、migration drift、镜像聚焦 `13/13`、registry digest 和无 secret 检查通过。迁移没有隐式创建 live 行，赛事/runner/result 总量保持 `9,867 / 100,132 / 91,897`。
4. secret 已安装到 `/opt/umanewsbot/runtime/secrets/the-racing-api-free.env`，验收时为 `root:root 0600` regular file；`.env` 验收值为 `RACE_LIVE_SCHEDULER_ENABLED=false`、`RACE_LIVE_RUNNER_MODE=disabled`。
5. 生产 proof `/opt/umanewsbot/runtime/race_live_source_proofs/production-proof-20260718_035358` 已对 3 个固定 Free 端点取得 HTTP 200；请求元数据 SHA-256 为 `421a3d7976fbaee0e5c2ed20caaf8fa7b7647895fed6e2666971248ecbb6fc59`。它只是只读来源证据，不是 shadow 初始化 artifact。
6. 本次没有生成 shadow manifest：从 `2026-07-18` 起的 `428` 条 future event（英国 `72`）均无 `race_datetime`，而初始化器要求 aware 时间与既有 event 精确匹配；scheduler/runner 因此保持关闭，live 业务行保持为 `0`。
7. web 容器重建后，Nginx 的静态 upstream 仍指向旧容器 IP并短暂返回 502；本次重启 Nginx 后重新解析 `web:8000`，内外 HTTP healthz 恢复 200。

## AI 赛事身份决定生产执行结果（2026-07-18）

1. 用户批准的业务范围保持为 manifest `cf5e220e9c0a0c7b2daeb7ef5030ed3243059ec9bd36ba5e6e2390c0d89a0147`、actions `9622460e82dc4d3449bf693bf2e7e107e43684c5b5dbf518bc700a4a24f53da1`、approval `f02b0e4c11a605fe3d4f818856d699a8979c12b9884d04d93ed32adbb44b0584`。
2. 首次 apply 在 PostgreSQL 行锁阶段因 nullable outer join 被数据库拒绝。事务、prepared verifier、总量和 OperationLog 证明业务零写入；失败尝试没有 rollback ledger，空 result 文件只保留为失败时间证据。
3. 锁查询技术修复进入 `main@f396d04837c7161a351b920737ac030911dec3e3`，tree `f9bef70b59f2ee0dfa0bbd2a78c5c2c316e45d45`，source archive SHA-256 `fd0c66acb2cef161746e2b2d851106ac12ba475abdab0b5107f2871a1e557d72`。两次构建 image ID 均为 `sha256:63cdfc131ebb4152f4f56740fe6f94f806f33139b9496f15679b184457397329`；镜像内 check、迁移漂移、生产 PostgreSQL 只读锁 smoke 和限定复审通过。
4. 最终写前备份为 `/opt/umanewsbot/backups/db/pre-race-series-identity-f396d048-20260718_014337.dump`，`194,307,039` bytes、权限 `0600`、SHA-256 `640791685f14d82cd8a47a9c83ce2b6fb4a361e8edafa824c9c2e6338c892707`，`pg_restore -l` 通过。即时回滚标签为 `umanewsbot:rollback-pre-f396d048-20260718_014256`，环境备份为 `/opt/umanewsbot/.env.backup.pre-f396d048-20260718_014256`。
5. 正式 apply result 位于 `runtime/race_series_identity_review/prepare-8b9b9755-20260717_205349/apply-result-f396d048-20260718_014604.json`，SHA-256 `20fb046276e633ba9c682fc62ec865dca41acff2ce6bccd5ad74256fb02b3365`。rollback ledger 同目录，SHA-256 `0a37af374fc06a2e19cb70360c1a512389f066d99f6927c079c76cc4389531e5`；独立 postapply verifier SHA-256 `dbc76f0ea5d6b5d3b1a3e7b6fc30290df440f47c4f48d10827394b55837a7a3b`。
6. 写入结果为 `228 positive / 24 negative pairs`，John C. Harris event `507` 为 `turf`，OperationLog ID `96353`。`events/runners/results` 保持 `9,867 / 100,132 / 91,897`，linked targets 为 `9,103`，relations 为 `228`；事务内和独立 verifier 均无错误。
7. web/worker/beat 已统一到新镜像，迁移无变化；内外 HTTP healthz、worker ping、active/reserved、Redis 队列和近期日志通过。`RACE_EVENT_HISTORICAL_PUBLIC_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
8. 若需要业务回滚，必须先停止 beat、排空 worker，并同时提供上述 manifest、approval、rollback ledger 及其精确 SHA；若任一相关 target/event/series 在 apply 后发生漂移，自动 rollback 会拒绝，必须先人工审计。

## AI 赛事身份决定生产执行门禁（2026-07-17）

1. 唯一允许进入下一步的代码基线为 `8b9b97552a6cb8b4b4690dc6f8b1a1d4233991e5`，代码 tree 为 `ab1f58af54381e72c7c277f03a59a29676618dae`；工作簿 SHA-256 为 `d93286e9e61ccf41770fe607740a972d025c8a00b2deb1d4a4f1890954852492`。部署前重新核对主线只包含文档追加或该精确代码，不得夹带产品行为变化。
2. 正式生产 artifact 为 `/opt/umanewsbot/runtime/race_series_identity_review/prepare-8b9b9755-20260717_205349/artifact`。manifest SHA-256 必须为 `cf5e220e9c0a0c7b2daeb7ef5030ed3243059ec9bd36ba5e6e2390c0d89a0147`，actions SHA-256 必须为 `9622460e82dc4d3449bf693bf2e7e107e43684c5b5dbf518bc700a4a24f53da1`；prepared verifier 必须保持 `ok=true / error_count=0`。
3. 当前 `approval.json` 为 pending。取得用户对上述代码、manifest 和 actions 的明确发布授权后，才由生产用户 `admin` 填写 approved 状态、时间和 manifest SHA，并记录 approval 文件自身 SHA；不得沿用此前 reconciliation 的空动作 approval。
4. 发布前确认 historical runner、live lock、running batch 和历史 one-off 均为空；构建并部署精确 AMD64 镜像，核对 web/worker/beat 的 image、revision、服务器 checkout 和容器内命令一致。本变更无迁移，仍需运行 Django check 和迁移漂移检查。
5. apply 前创建新的 custom-format PostgreSQL 备份，核对文件非空、权限、SHA-256 和 `pg_restore -l`。随后以正式 artifact 运行 dry-run 和 verifier；任何数据库 baseline、artifact 或 approval SHA 漂移都停止。
6. 只允许单个串行 apply。预期动作是 `228` 个正向身份关联、`24` 个唯一负向系列对和 `1` 个字段修复；工具内部整批事务、数据库锁和逐对象锁必须生效。不得删除系列，不得改变公开状态、赛事状态、runners 或 results。
7. 写后 verifier 必须为 `ok=true / error_count=0`，并逐项证明目标关联、系列归属、`MERGED_INTO`、双向禁止合并规则和 John C. Harris 草地修复。保存 OperationLog、rollback ledger、最终 summary、manifest 和 approval SHA。
8. 全程保持 `RACE_EVENT_HISTORICAL_PUBLIC_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。写后复核 healthz、队列、事务和错误日志，再单独决定是否继续原 reconciliation 关联。

## 赛事正式目标与公开赛程关联发布门禁（2026-07-17）

1. 以最新成功代码 review 后用户明确批准的 commit 构建 AMD64 镜像；切换前核对 revision、tree、source SHA 和两次构建 image ID，不复用旧分支镜像。
2. 部署前停止 historical runner 并确认无 historical live lock/running batch；本变更无迁移，不需要为只读审计停止新闻 worker/beat。
3. 先使用新命令生成一个不存在的生产 artifact 目录，默认只读。核对 `classification_counts`、三层分母、东海锦标 2026、全部冲突和 `review.html`，不得直接使用 pending approval 写库。
4. artifact 目录拒绝覆盖；manifest 中四个文件路径与 SHA 必须精确匹配。审批文件必须独立填写 `status=approved / approved_by / approved_at / manifest_sha256`，并记录 approval 自身 SHA。
5. apply 前生成 custom-format PostgreSQL 备份，核对非空、权限、SHA-256 和 `pg_restore -l`；随后再次运行 verifier，数据库 baseline 漂移即停止。
6. apply 必须同时提供 expected manifest SHA 与 expected approval SHA。命令只串行采用 `exact_link`，整批单事务，先预检 rollback ledger；任一 identity、状态、artifact 或 ledger 失败时整批不写。
7. 写后 verifier 必须证明 target/event/detail/visibility/status 数量守恒，所有 approved exact links 已关联，冲突未写入。保留 rollback ledger 和 SHA；若关联后发生生命周期或详情变化，禁止自动 rollback。
8. 部署和数据 apply 全程保持 `RACE_EVENT_HISTORICAL_PUBLIC_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。

### 本次生产执行结果

1. 用户批准的 revision 为 `213a818c2845fd29a2afe742ea8d11f653269d9e`；两个独立 AMD64 构建 image ID 均为 `sha256:f3b2d4625322e7f96554288d4b710723ff9d01323dd3be654bcbc2ba0281a9d9`，tree `799f77db3f253e524f5f0095ed07a4fe9c8cd058`，source archive SHA-256 `c15bec6853266cd61c4852380ff1f6613cfe4bc9e1614ad3a5272d1edf9eb92a`。生产 web/worker/beat 与服务器 checkout 已统一到该 revision。
2. 生产 Compose 使用 service-specific image tag，且把宿主 `/opt/umanewsbot/server` bind mount 到 `/app/server`。只更新 `umanewsbot:prod` 或只替换镜像都不够；本次硬门禁分别发现容器仍使用旧 service tag、以及新镜像代码被旧宿主 checkout 覆盖，均在业务写入前停止。后续同类部署必须同时核对实际 service image ID、服务器 Git HEAD 和容器内管理命令可见性。
3. 有效恢复点为 `/opt/umanewsbot/backups/db/pre-race-reconcile-213a818c-20260717_015716.dump`，SHA-256 `7958873ff243f5a3c1bb85075f74fa0daec6a040f33688b31f63db71e1eb0e3b`，custom-format 且 `pg_restore -l` 通过；环境备份为 `/opt/umanewsbot/.env.backup.pre-213a818c-20260717_015716`，上一镜像保留回滚标签。
4. 只认显式挂载 `/opt/umanewsbot/runtime:/app/runtime` 后生成的 artifact：`runtime/race_event_reconciliation/prod-213a818c-mounted-20260717_021203`。manifest SHA-256 为 `5caee7d0ed093605aede28c2834d3acf8a75f9f20e2d88679924c3670f3c6a51`，verifier `ok=true / error_count=0`；此前未挂 runtime 的一次性容器产物不可见，已作废且没有写库。
5. 本次分类为 `already_linked=8875 / identity_conflict=46 / missing_event=21537 / status_conflict=459 / exact_link=0`。approval SHA-256 为 `f22f5e0704fd1b30c19134d1450669fe09418cf93dbe955dc7a205160ab47938`，内容仍为 `status=pending`。由于没有 exact link，不得为了完成流程而签署或运行空 apply；先完成系列身份审核并重新生成 manifest。
6. 审核输出位于 `outputs/race_event_reconciliation_20260717/`：Excel SHA-256 `834dd2dea4e2d8bac69c98ab580577bd7c7a8f8741d7949d310a0b586d0eb089`，HTML SHA-256 `0f9efbe80136597d20db701859daae1127b9124e96f1dddefe4192b76faeb7a3`，详细 JSON SHA-256 `aa0800963a01f7578c590d959d4423379d296e42f9e438c8693d02544073beed`。跨地区同名候选必须直接排除；同地区重复系列由产品审核确认合并、独立或沿革关系。
7. 收口时无 historical one-off，历史 enabled/network 均为 false，历史公开未开启；HTTP healthz 正常。普通新闻 worker 正在处理自然 crawl，不属于本次历史任务；生产可用磁盘约 `3.6 GiB`，低于 `5 GiB` historical crawl 门槛，禁止在生产继续重型抓取。
## 准备中：准实时赛事赛果（当前禁止执行生产步骤）

本节只固化候选发布顺序和回滚契约，不构成发布授权。TRA provisional 核心链和赛前
racecard/off time 增量已在本地实现；最终代码 review 和用户在该 review 后的发布授权
尚未完成，因此仍不得部署本增量、运行生产 prepare/initializer、启动调度或打开公开模式。

### 2026-07-18 本次生产执行结果

1. 发布提交为 `6646302b80c90cf406075516ab4812f2f4ebee18`，四个 app service 的实际 image ID
   均为 `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`；
   web/普通 worker/Beat 没有 secret 或 racecard artifact 挂载，只有
   `race_live_worker` 拥有 `/run/secrets:ro` 和 `/run/race-live/racecards:rw`。
2. 数据库恢复点为
   `/opt/umanewsbot/backups/db/pre-racecard-6646302b-20260718_105233.dump`，SHA-256
   `6bdda3152cb3ee6a92fc774989dde7fc94614149066e01e4bb746d85fb9f7882`，
   `pg_restore -l` 通过。回滚 tag 为
   `umanewsbot:rollback-pre-racecard-6646302b-20260718_105233`。
3. production prepare run 为
   `/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-20260718T030337Z`；
   目录 `0700`，`report.json/requests.jsonl` 均为 `0600`。两个固定 GB endpoint 均为
   HTTP 200，但 event `924` 返回唯一 blocker `racecard_not_found`。
4. blocker run 没有 `manifest.json`，因此本次未执行 initializer dry-run/apply/verify。
   report SHA-256 为
   `bd7a19f8867df38e21e88ae2db465f9b6c5be30ad3b520e6b7fa988c9f5ae46a`，request ledger
   SHA-256 为 `78fef17cc843d8f83588a716dffc7fab0de56a740b88edc2a5510e0b99afcf2d`。

### 候选发布顺序

1. 固定最新成功 review 的 parent、完整 fingerprint 和 content manifest；确认待发布 tree 与之逐字节一致。
2. 生成精确 event allowlist/ownership handoff：逐 event 记录旧 owner/new owner、owner generation、无 active historical runner/lease/checkpoint、source registry digest、共享 host 预算和资源窗口。任何未知项停止。
3. 先做数据库备份及恢复可读性验证，再部署最新受审镜像。本增量没有 migration；仍须运行
   `manage.py check`、`showmigrations stable` 和 `makemigrations --check --dry-run`，确认
   当前上界仍为 `stable.0045`。部署代码时保持 scheduler/runner/public policy 全关。
4. TRA secret 继续只存在于 `/opt/umanewsbot/runtime/secrets/the-racing-api-free.env`，
   宿主文件必须为生产用户所有的 `0600` regular file。候选镜像内 registry 固定为
   `/app/runtime/policies/race_live/source_registry_the_racing_api_free.json`，SHA-256
   必须更新为
   `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`；
   旧 SHA `1d801e95...fa32` 不得用于新 prepare。
5. 创建宿主 `/opt/umanewsbot/runtime/race_live_racecards`，要求 `root:root 0700` 且祖先
   不含非系统 symlink。`.env` 新增
   `RACE_LIVE_RACECARD_ARTIFACT_ROOT=/run/race-live/racecards`；三份 Compose 只让
   `race_live_worker` 同时拥有 secret ro 与 artifact rw，web/普通 worker/Beat 均无永久
   挂载。先用 `docker compose config` 和容器 mount inspection 验证，再重建服务。
6. 对显式英国 event ID 运行受控 prepare。该步骤对 RaceEvent/runner/result/live
   业务事实零写入，但会 bootstrap/更新 `RaceLiveHostBudget` reservation/outcome；最多
   两个 TRA 请求。审核完整 run 目录及三文件 SHA 后，才可用 schema v2 默认 dry-run、
   apply、verify 初始化单地区 shadow。
7. 连续两个真实赛日满足 identity、字段、延迟、队列和资源门槛后，才可另行 review/授权精确赛事 `provisional_public`；`official_public` 必须再有官方来源 marker 和复核证据。任何扩大都使用精确 event allowlist，不使用随机百分比。当前单 event runner 尚无当天响应 cache，同 host 多赛事必须保持保守 batch cap，不得通过提高并发绕过 1 RPS。

### racecard prepare 与 schema v2 初始化

以下命令只在最新成功 review 后取得用户发布授权、完成代码部署与备份后执行。先核对容器
OCI revision 等于受审 commit、镜像内 registry SHA 等于上述新值，并确认 scheduler false、
runner disabled、historical runner/receipt/lease/checkpoint 和 live queue 全部为空。

prepare 只能从 one-off `race_live_worker` 执行，必须显式列出本批英国 event ID。下面的
coverage/terms/official evidence digest 与有效期必须替换为当次已审核值；policy
`valid_until` 不得晚于 registry 的 `2026-08-16T16:00:00+00:00`：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  race_live_worker python manage.py prepare_race_live_racecards \
  --event-id <event-id> \
  --region-code gb \
  --run-id <run-id> \
  --secret-env-file /run/secrets/the-racing-api-free.env \
  --registry-file /app/runtime/policies/race_live/source_registry_the_racing_api_free.json \
  --expected-registry-sha256 60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402 \
  --approved-commit <release-commit> \
  --coverage-proof-digest <coverage-proof-sha256> \
  --terms-evidence-sha256 <terms-evidence-sha256> \
  --policy-valid-until <aware-datetime> \
  --official-verification-route bha_manual_verification \
  --official-verification-route-version bha-manual-v1 \
  --official-verification-evidence-sha256 <official-evidence-sha256> \
  --official-verification-valid-until <aware-datetime> \
  --confirm-real-network
```

只接受输出目录
`/opt/umanewsbot/runtime/race_live_racecards/<run-id>`；目录必须为 `0700`，其中
`manifest.json/report.json/requests.jsonl` 必须为 `0600`。blocker run 没有 manifest，
不得初始化。成功 run 逐项核对：两个固定 GB 路由、请求间隔、response SHA、赛事/赛场
精确匹配、London 日期/时间、participant ID/number/draw/jockey、无 raw/secret/禁止字段，
以及 manifest 内 companion SHA 与宿主重算值一致。

schema v2 manifest 顶层新增
`registry_valid_until/requests_sha256/report_sha256/official_verification_evidence_sha256`；
event 新增旧时间、expected status/local date/timezone、source off time/response SHA；
participant 新增 barrier/jockey。`approved_commit` 必须等于实际部署的 40 位 OCI revision。

initializer 从 one-off web 执行，但只临时只读挂载获准的完整 run 目录，不挂 secret 或
artifact root。默认命令为 dry-run：

```bash
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps \
  -v /opt/umanewsbot/runtime/race_live_racecards/<run-id>:/run/race-live/artifact:ro \
  web python manage.py initialize_race_live_events \
  --manifest /run/race-live/artifact/manifest.json \
  --expected-manifest-sha256 <manifest-sha256> \
  --expected-approved-commit <release-commit>
```

备份和 dry-run 审核均通过后，才允许同一固定镜像、同一文件和同一参数追加：

```bash
--apply --confirm-apply
```

apply 成功后立即以同一输入改为：

```bash
--verify
```

verify 必须返回 `ok=true / error_count=0`；后台逐 event 核对 London 时间、owner
generation 1、无 active claim、policy 全为 shadow、allowlist cap 为 provisional、
racecard revision 未发布，并确认 observation/result revision/publication/incident/
`RaceEventResult` 全为零。apply 可精确重放但不得新增行或日志；不同 manifest、companion
漂移、过期 policy/registry、event CAS 漂移、人工锁、既有赛果或 partial 初始化均 fail
closed。初始化完成后仍保持 scheduler false、runner disabled，直到单独 shadow 启动检查。

### 验收与回滚

1. 验收必须覆盖 `/healthz/`、web/news worker、`race_live` worker、Beat selector、普通/live queue 隔离、admin 只读面、赛事级 CAS kill switch、公开 badge、shadow 零泄漏、数据库锁等待和 host circuit；40 场赛事日历的公开读取门必须继续满足 `<=12` 查询自动化硬门禁，禁止退回逐 event resolver。
2. 首选回滚为 mode 全局 `off`，再停 selector、停 `race_live` worker；不 purge Redis，不重建 DB/Redis，不触碰 historical runner/runtime/checkpoint。保留 observations/revisions/publication/OperationLog 审计。
3. 错误投影只允许在 owner generation 和 current pointer CAS 下切回同 event/kind 的 last-known-good revision并重建；不得删除 revision 或 observation。结构异常才进入独立数据库恢复窗口。
4. migration 回退只在尚未写入 live observation/revision/publication/incident 数据且已通过备份恢复门禁时使用；`0045 -> 0032` 的测试往返不能替代生产判断。admission/authority/marker/incident 表一旦存在审计数据，默认采用向前修复或整库备份恢复，不用反向迁移销毁证据。

## 已完成：第一期 1998–2026 历史赛事正式详情总账收口

### 审批产物与生产写入证据

1. 正式详情范围为 `8032 = 6534 complete + 1491 evidence gap + 7 not_due`，生产验收为 `6534 events / 70314 runners / 65227 results / 6534 winners`。日本、中国香港、法国 hard 范围完整；英国历史 hard 为 `708 complete + 45 evidence gap`；英国新正式为 `94 complete + 1 gap + 4 future`，美国新正式为 `195 complete + 1 future`。英国、美国历史 G2/G3 按已批准的 best-effort 政策收口。
2. France 14 场 manifest 为 `7e8f29066bccae965ade8736e071189155cb8245e92309f07bf23bfa67f50eeb`，结果为 `132 runners / 122 results / 14 winners`；专用写前备份 `/opt/umanewsbot/backups/db/pre-france-zone-turf-7e8f2906-20260716_2204.dump`，SHA-256 `ed7e189796d2d8d87c27874ecbab796db99829322e5cf9cfb388db9b362b60a9`，replay/verifier 均为 `errors=0`。
3. UK 6 场 bundle 为 `fd3438beaeabbf15ed365069707cea982221a444716161d66a30e74bc2a0a081`，结果为 `46 runners / 40 results / 6 winners`，状态为 `40 declared + 4 pulled_up + 2 withdrawn`。dry-run plan `490400342fe30e4fe291691d7cc61801d42f025663cb25245d4d5793c122560e`；apply2 plan/state `473495fbb70c22823d29471aa436d52a343596c23562043a42aff35c3dbdabbb` / `ca51bb347c4313a0bfeee645cc7fe9f33013da09713d2acbee02f69c0e688f0f`；replay plan/state `5e1b5895d217b2f265cc9455b35679e566ebd7f922dedae3caf80bdc349070b1` / `cc5d9d149fbfe20a3796a9b6bf62e75e233448939f4b1ce6799ac9fffbade6ba`。
4. UK 场地修正 manifest `662be6d37e55fda7b3b2d620ddc61fe0ba2bc0291270d4bd7439ae8a4c0da903`，script SHA-256 `1ac34051d5c8a72294364b1f4d5b524c55d81e393c1188edcb12fbd0a508407c`；apply 与两次 verifier 均为 `4/4`。
5. UK 6 场与 gap 裁决统一写前备份为 `/opt/umanewsbot/backups/db/pre-uk-six-gap-659b46ca-20260716_230344.dump`，`189338143` bytes，SHA-256 `c5006b15bee22dd17d0d6fb7913f7c376a0799eeb37f3d6dc42b9199444c1410`，权限 `0600`，mtime `2026-07-16 23:04:32 +0800`，`pg_restore -l` 通过。备份门禁：`pg_dump` 进程必须同步退出，文件 mtime/size 在复核窗口内稳定后，方可计算 SHA-256 并运行 `pg_restore -l`；不得把仍在写入的中间文件 identity 记为最终备份。
6. gap/not_due resolution manifest 为 `d529126840a6d3c6ffb1abc0a426d3ac796d36f9df72a50dcc06b34e0af9c90f`；`1498` 条 resolution 已 apply，并经两次独立 verify，生产对应 `1498` 条唯一 `OperationLog`。原因分布为 `1467 source_unavailable + 31 identity_review_required`，最终按到期状态归入 `1491 gap + 7 not_due`；target `53349` 的日期为 `2026-09-05`，target `53418` 为 `2026-07-26`。
7. 最终 v5 目录为 `runtime/race_event_crawl_runs/final-detail-coverage-ledger-v5-20260716`，manifest SHA-256 `692b089b0d18b08899571702cb57ff3dadbca144a2dce4c4e6b3d7c15e6584ea`，ledger SHA-256 `833995952fc444fd39c40934802cc7306cc7dd354c4f57db5bd725fc66a48fe9`，review 为 `approved`。global verifier 为 `8032 checked / errors=0`。

### 生产运行态与验证

1. `prod` tag、web、worker、beat 均运行 image `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab`，OCI revision 为 `6b596befa0eea9ef0ba45acbb5384195829cc144`。本次无迁移；Django check 通过，`umafans.run` 与 `www.umafans.run` 的 HTTP `/healthz/` 均为 `200`，worker ping 成功，收口日志无 error。
2. formal 范围保持 `published=0 / featured=0`；`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，无 historical runner、无 running batch。第一期数据写入完成不构成公开授权，历史公开继续关闭。
3. 已删除未使用的旧 `umanewsbot` tags，只保留当前镜像与即时 rollback；可用磁盘由 `2.6 GiB` 增至 `4.0 GiB`。该值仍低于 `5 GiB` crawl floor，服务器未来 crawl 为 no-go，不得降低门槛；重型抓取继续使用本地 Docker，生产只接收审核后的紧凑 artifact。

### 回滚与回滚后验证

1. 即时代码回滚标签为 `umanewsbot:rollback-pre-6b596bef-20260716_233842`，指向 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`；切换前环境备份为 `/opt/umanewsbot/.env.backup.pre-6b596bef-20260716_233842`。回滚前先停止 beat，并等待 worker active/reserved 到达安全边界；不得强杀活动任务，也不得重建 DB/Redis。
2. 将上述 rollback tag 重新绑定为 `prod` 后，仅以 `--no-deps` 重建 web/worker/beat。本次没有迁移，普通代码回滚不恢复数据库；只有确认本次详情或 resolution 写入造成数据损坏时，才使用 `/opt/umanewsbot/backups/db/pre-uk-six-gap-659b46ca-20260716_230344.dump` 进入单独数据库恢复窗口。恢复 `.env` 也只在确认环境文件漂移时执行，不覆盖当前凭据。
3. 回滚后必须重新核对 web/worker/beat image ID 一致，运行 Django check，确认两个正式 HTTP 域名 `/healthz/` 均为 `200`、worker ping 成功、日志无 error；再次确认 formal `published=0 / featured=0`、历史 enabled/network 均为 false、无 runner/running batch。若数据库已恢复，还必须重跑 v5 global verifier 并取得 `8032 checked / errors=0` 后才能结束窗口。

## 已完成：英国 Sporting Life 增量详情包

正式候选输入为 `/opt/umanewsbot/runtime/historical_race_detail_import/detail-import-bundle-uk-sportinglife-v8`；本地原件为 `runtime/historical_plan_exports/detail-import-bundle-uk-sportinglife-v8`。顶层 manifest SHA-256 为 `3c6a4d11106c2b490876d63f0719b71d6fde9d7c7bc9c8937736d26a0e28831c`，bundle identity 为 `2392a69c7cf1b03812422cf11b3c5ed73a181e719ca6309d79283812c735cb50`。

1. 固定范围为 `198 = 197 complete + 1 gap`，只含英国；完整记录为 `2027 runners / 1794 results / 197 winners`。historical chunk 为 `194` 场，chunk manifest `8fedabea94e348a3cbbdd960b2456ccb4864429fae7ce9588667fb82ad615543`；current-year-due chunk 为 `3` 场，chunk manifest `be156a8fd60f71f3f317d8bac6aa83c88067db30c4b653098b814c4f853d752d`。
2. 用户已按 commit `2a7352c8` 和本节 bundle manifest 明确授权；approval 于 `2026-07-16T09:33:54Z` 签署。historical approval SHA 为 `6a0240453cf19d681365a7add59ff2ea254fff5dfaee3ca6722495450ca87aec`，current-year-due approval SHA 为 `93bf1143460450015365f85fa7d2c3aae2a479180ccf69c953e9622d1fac06b1`。
3. 来源包已由当前生产镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473` 在 `--network none` 下只读复核通过。上传归档 SHA-256 为 `dfd676f2ed3bc947f26bd81cdc8bbfff5f070de3971b3105c429a9177d0e085a`；解压后归档已删除，manifest/identity SHA 与本地一致。
4. 写前 custom-format 备份为 `/opt/umanewsbot/backups/db/pre-uk-sportinglife-v8-apply-700a2a96-3c6a4d11-20260716_093456.dump`，`175094189` bytes，SHA-256 `a942e2dad092bdf0af9e0546030a73c75dfeebb1c89ee888d704e8244d7f0d6c`，权限 `0600` 且 `pg_restore -l` 通过。
5. `detail-dryrun-700a2a96-3c6a4d11` 对两个 chunk 全量 dry-run 通过：historical 为 `194 / 1989 / 1762`，current-year-due 为 `3 / 38 / 32`，格式为 targets/runners/results；bundle receipt 保持 0。
6. 首次 apply run 因根目录仍为已完成 dry-run checkpoint，在业务步骤前以 `runtime/database checkpoint mismatch` fail closed，receipt 仍为 0。将 dry-run 状态按 run ID 归档后，使用 `detail-apply2-700a2a96-3c6a4d11` 从头串行执行 2/2 receipts；不得把这次事故解释为允许删除 checkpoint 后重试。
7. `detail-replay-700a2a96-3c6a4d11` 随后完成 2/2 replay，逐目标 verifier 为 historical `checked_count=194/error_count=0`、current-year-due `3/0`。最终精确得到 `197 events / 2027 runners / 1794 results / 197 first-place winners`，basic/runners/results 全部 complete；全部保持 `draft`、`published=0`、`is_featured=false`。
8. 收口时 runner 容器为空、preflight 为 `migration_safe`，web/worker/beat 恢复到同一生产镜像和 revision，HTTP 内外 healthz 正常。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false` 和历史公开开关保持关闭；生产只处理了紧凑 artifact，没有运行 Sporting Life 抓取或重型解析。

## 已完成：历史详情 source bundle 正式导入

正式输入为 `/opt/umanewsbot/runtime/historical_race_detail_import/detail-import-bundle-v1`；本地原件为 `runtime/historical_plan_exports/detail-import-bundle-v1`。顶层 `manifest.json` SHA-256 为 `dfb86ee85b103688fe1521b07f44ee8f36669d25e85ff3ac2b580a66b38e14d9`，范围为 39 个正式 package、`4930 = 4652 complete + 278 gap`，完整目标包含 `51191 runners / 48413 results`。

1. 发布身份固定为 review fingerprint `943602458bd6975bff1a0bb6bb47ad8e3dde605796a10103461def91a723892a`、content `a353f2f8179432cb807601bf574039db578b265dda2bf3c9d5f9777e1c1b748f`、revision `700a2a961516464ecf93deb0f43a751718efaaca`。正式 AMD64 image ID 为 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`，tree `0708ce3ef34f64549dd8483c9d7400302052c79e`，source archive SHA-256 `20ff51d1f2d6220fba3b0a01615e5366f57605de6e579b6ab222bc70eef597d3`；两次独立构建 image ID 一致。回滚标签 `umanewsbot:rollback-pre-700a2a96-20260716_1036` 指向切换前镜像。
2. 本次部署显式把 `umanewsbot-web:latest`、`umanewsbot-worker:latest`、`umanewsbot-beat:latest` 绑定到批准 image ID，并使用 `docker compose ... --no-build`。此前一次普通 `docker compose up` 启动了服务器构建，发现后立即停止并清理，未产生数据库写入。
3. 首次 run `detail-dryrun-700a2a96-dfb86ee8` 在第 13 个 chunk 因 `stable_raceevent_series_key_6e15e445` 物理 tuple overlap 失败，整个事务回滚且 receipt 为 0。修复前备份为 `/opt/umanewsbot/backups/db/pre-raceevent-index-reindex-700a2a96-20260716_104953.dump`，`151565133` bytes，SHA-256 `43cbfb4faec810a133805f7622f306a1cf44f143891e1235924ff7e85bd48947`，`pg_restore -l` 通过；随后执行两次 `REINDEX INDEX CONCURRENTLY stable_raceevent_series_key_6e15e445`。
4. 索引修复后，本次没有续跑失败点，而是以新 plan 完整执行 `detail-dryrun2-700a2a96-dfb86ee8`，20/20 chunks、4652 targets、51191 runners、48413 results 全部通过且无业务写。正式 apply 前又生成 `/opt/umanewsbot/backups/db/pre-detail-apply-700a2a96-dfb86ee8-20260716_110915.dump`，`151570907` bytes，SHA-256 `6c7d8f326c4c6a10f685a7be1a0625027cf6732729bcbc6904eba3aa45964b54`，权限 `0600` 且 `pg_restore -l` 通过。
5. `detail-apply-700a2a96-dfb86ee8` 已完成 20/20 receipts；`detail-replay-700a2a96-dfb86ee8` 随后完成 20/20 replay。最终逐目标 verifier：4652 events、51191 runners、48413 results、4652 winners，地区为 France `15`、Hong Kong `19`、Japan `1586`、United Kingdom `171`、United States `2861`；`module_errors=0`、`basic_errors=0`、`missing_sources=0`、`missing_dates=0`。
6. 4652 场全部为 `draft + incomplete + is_featured=false`，published 为 0。basic/runners/results 模块已完整；事件级 `data_quality_status=incomplete` 和草稿状态原样保留，草稿 URL 返回 404。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
7. 收口时 web/worker/beat image ID 一致，Celery active/reserved、Redis queue/unacked、historical runner 均为空，HTTP 首页与 healthz 为 200。web 更新后曾因 Nginx 保留旧容器 IP 出现 502，本次重启 Nginx 后恢复；DB/Redis 未重建。生产可用磁盘约 `4.5 GiB`，低于既有 historical crawl 的 5 GiB 门槛，本次没有启动新的生产 crawler。

## 2026-07-16 France runner v2 本地真实网络 smoke 阻断记录

1. 计划执行单目标 `france / 48498` 的 `discover -> cache -> parse -> validate -> package`，仅授权本地 Docker；固定镜像为 `sha256:e55b8b08bcd5848625a8c1d0fa5abd710783ed3be6fddaf245860ccbc9e55fa8`，不得访问生产或数据库。
2. 独立 run root 与共享 host lock 已创建在 `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/`。现有 descriptor 的不可变 mounts/outputs 仍指向 `runtime/historical_plan_exports/detail-crawl-1998-2026-v2/smoke/`，因此 launcher 在创建容器前以 `mount contract mismatch for run` 拒绝。
3. 本次安全终态：真实请求 `0`、缓存字节 `0`、stage artifact `0`，无 checkpoint、request log、package manifest 和残留容器；`cache / parse / validate / package` 均未启动。空 run root 与 host lock 保留，不执行清理删除。
4. 恢复条件：由计划生成侧重新生成并审批绑定独立 run root 和共享 host lock 的 descriptor，保持相同 target、固定镜像、来源白名单和两次请求预算；不得使用软链接、手工改 descriptor 或切换到 plan root 运行目录。新 descriptor 就绪后从 `discover` 重新执行并逐阶段验收。

## 2026-07-16 Japan runner v2 本地真实网络 smoke 阻断记录

1. 计划执行单目标 `japan / 50556` 的 `discover -> cache -> parse -> validate -> package`，仅授权本地 Docker；固定镜像为 `sha256:e55b8b08bcd5848625a8c1d0fa5abd710783ed3be6fddaf245860ccbc9e55fa8`，不得访问生产或数据库。
2. 独立 run root `runtime/historical_detail_crawl_runs/detail-crawl-1998-2026-v2-smoke/japan` 与同级共享 host lock 已创建。现有 descriptor 的不可变 mounts/outputs 仍指向 plan root 下的 `smoke/run/smoke-japan-50556` 与 `smoke/host-locks`，因此 launcher 在创建容器前以 `mount contract mismatch for run` 拒绝，退出码为 `2`。
3. 本次安全终态：真实请求 `0`、缓存字节 `0`、stage artifact `0`，无 checkpoint、request log、package manifest 和残留容器；`cache / parse / validate / package` 均未启动。空 run root 与共享 host lock 保留。
4. 恢复条件：由计划生成侧重新生成并审批绑定独立 run root 和共享 host lock 的 descriptor，或经明确审批改用 descriptor 原批准路径；不得手工修改 descriptor。新 descriptor 就绪后从 `discover` 重新执行并逐阶段验收。
5. 本次没有生产变更、数据库写入或业务 artifact，因此无需生产回滚；重新运行前验证固定镜像 identity、descriptor SHA、空容器状态和授权路径。

## 阻断中：batch006 生产 runner 事故恢复

1. 首次 France verify 在无网络、无赛事业务写入阶段执行重型 PDF 解析后，生产 SSH 持续出现 `Connection timed out during banner exchange`。在可信主机恢复前，不执行 retag、Compose、容器重启、runner resume、数据库备份或赛事 apply。
2. 恢复后第一步只读检查并停止遗留 `umanews-historical-runner`：保留日志与 artifact，核对 `HistoricalBatchRun`、live lease、`pg_stat_activity`、idle transaction、Redis/Celery、web/worker/beat image identity、磁盘和内外 healthz。任一身份或数据库健康异常先回滚/修复，不继续批次。
3. 禁止在生产重跑 France Galop PDF 或逐场扫描。所有重解析在本地固定镜像完成并生成 cache manifest、summary、candidate SHA；生产只运行已验证 artifact 的 lightweight verifier。
4. apply 仍逐阶段串行：日期 dry-run -> 独立 custom-format 备份并 `pg_restore -l` -> 日期 apply/verifier -> 重新导出 target identity -> 详情来源 dry-run/备份/apply/verifier -> 最终详情 dry-run/备份/apply/verifier。任一阶段不可与新闻维护或其他生产窗口并发。
5. 历史公开、常驻网络和常驻写入保持关闭；只有全部 1998-2026 正式总账达到 complete 或 evidence gap 后，才进入最终统一人工审核与公开开关决策。
6. 本地多 worker 抓取可显式设置同一个 `RACE_EVENT_CRAWL_HOST_INTERVAL_ARTIFACT`，同时让每个 shard 使用自己的 `RACE_EVENT_CRAWL_REQUEST_BUDGET_ARTIFACT`；host 文件必须位于共同受控根。生产 runner 会清除 host interval 变量，除非后续通过独立设计把共享父挂载纳入 plan 身份与 checkpoint。

## 执行中：batch006 正式流水线部署与运行

生产部署阶段已完成：`main@ccfee75fdff6fab7238b19484ba0489c2848dd50`、AMD64 image `sha256:e86c2339a6e690e801df2426a5edb408cbedf4c7eddd8cfd08011ed659ef773d`、tree `0c8fb1d65eea121a51366584a84749c7d2e3d88f`、source SHA-256 `635fa8a01b5c4685c66650355938af4930d8bebc90a9ece144fd76a2f1fa0d19`。写前备份 `pre-main-ccfee75f-20260715_122039.dump` 为 `141448192` bytes、SHA-256 `898c9a4ab3a06847023d189aed830553cbe733bf4c8e92a4ed636dd8231fa55f`，`pg_restore -l` 通过；回滚 tag 为 `umanewsbot:rollback-pre-ccfee75f-20260715_122039`。runner provisioning、crawl 最小权限、apply 无公网出口、两步暂停/恢复及最终空容器/空锁门禁通过，web/worker/beat 镜像一致，公开及常驻历史开关仍关闭。以下第 2-7 项继续作为 batch006 运行门禁。

1. 已完成 `formalize-historical-batch-crawl-pipeline` 的完整 stable、真实 PostgreSQL READ ONLY、旧规格流程 strict/all、迁移漂移、shell/diff、零问题 review、双构建和生产强化 smoke；后续若代码变化，必须重新执行同一门禁并生成新镜像身份。
2. batch006 只接受现有冻结身份：1061 targets，法国/香港/日本/英国/美国 `250/61/250/250/250`；manifest `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`、selection `b9a3ad6556cfd03e9a57874bec763f75ad4c45e7642751140cb063f1d0553637`、approval `a119e3bcfd3bc8940cf8b792e246e462b405c292b77f2996739b435c9185d835`。任一字节漂移停止，不重新生成审批掩盖漂移。
3. 使用 `build_historical_batch_crawl_plan --descriptor <tracked-artifact>/descriptor.json --shard-id <region-NN> --output-dir <new-empty-dir>` 为每个 shard 原子生成 `scope.json`、`runner-plan.json`、stage manifest 和 summary。每个 shard 只能包含一个地区、最多 250 targets/请求；runner plan 必须使用镜像内 `/app/runtime/tools`，不得指向 `tmp/`、artifact 子目录或宿主脚本。
4. 每个 crawl shard 使用独立 artifact 根、请求账本、source-cache manifest、runner state 和 checkpoint。启动前执行资源 preflight，生产可用磁盘至少 5 GiB；网络阶段 `network=true/write=false`，写入阶段 `network=false/write=true`。暂停、失败或恢复时不得删除或缩小账本/cache 以重获额度。
5. date/detail merger 只读取冻结输入和 source-cache manifest，输出 `complete.jsonl + gaps.jsonl + manifest.json + summary.json`。输出目录必须不存在；工具在同父目录构建临时目录，fsync 完成后一次 rename。来源冲突、不完整碎片和暂不可得进入带证据 gap；无证据遗漏、人工补证漂移、非法时间、非 HTTPS 来源或 cache SHA/size 漂移停止当前 shard。
6. 每一写入阶段先生成独立 custom-format 数据库备份并记录 bytes/SHA/`pg_restore -l`；先 dry-run，再 apply。写后立即运行 `verify_historical_race_batch_stage --stage date|detail-source|final --artifact-dir <merged-artifact> --output <new-report.json>`。报告必须 `error_count=0`、published=0；verifier 不得连接网络或创建 HistoricalBatchRun。
7. 少量身份/来源歧义写入统一 gap/review ledger 后继续其他 shard，不逐条等待用户。整批结束时才汇总 complete/gap、逐地区 events/runners/results、来源、冲突及待审项；全过程保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false` 的常驻服务配置和历史公开关闭。

## 2026-07-15 新闻统一镜像切换与存量重跑记录

1. 最终新闻代码 revision 为 `bdc0eeff78e111d7fa8a697cbb3557888f864fb8`，正式 AMD64 image ID 为 `sha256:c975a4faf979a1f78cdb203b810d4f5726aca114175007fc01c176044f13841c`。错误 revision 标签的 `sha256:427e1f733115d487981ee131da4ed6d75a681c1b690aa21978a00897616206d8` 禁止部署。
2. 写前备份 `/opt/umanewsbot/backups/db/post-news-final-pre-unified-bdc0eeff-20260715_033227.dump` 为 `140310729` bytes，SHA-256 `3e93fd9dba4fb80d3b415a2f97fce1d02337054d6afeb14a725b859cf67a5a74`，数据库容器内 `pg_restore -l` 通过。回滚 tag `umanewsbot:rollback-pre-unified-bdc0eeff-20260715_0335` 指向切换前镜像。
3. 切换遵循安全边界：beat 停止、正文 one-off 退出、TranslationRun started 和 NewsArticle translating 为 0、Celery active/reserved/Redis queue 可解释后，才以 `--no-deps` 更新 web/worker/beat。不得重建 DB、Redis、historical runner 或共享网络。
4. Sponichi 遗留队列仅在证明 Redis 中恰好是 79 条相同文章 ID 的旧 `process_article_automation_task` 后，通过 WATCH 校验并删除；审计 artifact 为 `sponichi_stale_automation_queue_cleanup.json`，SHA-256 `bf2fde83e050d70c44799a217e922054d7dc727a80701806d26ecbaddee3e92f`。不得将这一做法扩展成通用清队列操作。
5. 最终必须核对：三服务 image/revision 一致、healthz 和 PostgreSQL 正常、正文 one-off=0、TranslationRun started=0、NewsArticle translating=0、Celery active/reserved/queue=0、历史锁与事务=0、近 10 分钟无 error/traceback/fatal。
6. 历史开关继续保持 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。当前可用磁盘约 3.0 GiB，低于 5 GiB 门槛；不得因新闻窗口交还而启动 batch006。

## 待执行：多地区归属 V3 第二候选生产只读验收

1. 第一候选的 72 小时 `all_articles` run 虽然 `scope_complete=true` 且 Gold `qualified=true`，但人工检查 27 条主地区变化和 5 条 `needs_review` 后发现 7 类明确错标，结论为 no-go。不得复用该 run 批准 Shadow。
2. 第二候选必须包含对应真实反例测试，并通过专项、完整 stable、真实 PostgreSQL 250 篇性能、Django check、迁移漂移和 旧规格流程 strict/all。构建必须固定 main revision/tree/source SHA，AMD64 至少两次构建得到同一 image ID。
3. 生产保持 mode `off`、相关地区查询 false。使用第二候选连接生产库执行只读 `--scope all_articles --hours 72`，写入全新 artifact 目录；不得覆盖第一轮报告，不得开启门禁验证，不得 commit 归属。
4. 重新评估同一份保守对账后的 Gold，并人工检查新 run 的全部主地区变化、全部 `needs_review` 和分地区稳定样本。明确复核普通单词实体、赛果标题、正文首段赛场、日本当前成就/海外梦想、机构全名嵌套赛事词和正文历史背景六类边界。
5. 只有第二轮 Gold 仍满足主地区/precision/recall/扩散门槛，且人工清单无明确错标，才可部署代码并从 `off` 切到 `shadow`。Shadow 计时从生产配置实际启用且健康验收通过时开始，修复前 run 不计入 24 小时。

## 已部署：独立 historical runner 与 batch006 单地区 250

1. 迁移 `stable.0031_historical_batch_runner` 已在生产应用；首次 initial-install 门禁已经消费，不得再次使用。写前备份为 `/opt/umanewsbot/backups/db/pre-main-8741de98-20260714_185105.dump`，SHA-256 `f5126ea6f69dbfbc11dc40f0c85cf1dbf05a6e2c7c678e2ccf123ea46b10073e`，`pg_restore -l` 通过。后续部署一律走普通 runner preflight。
2. 后续 deploy/rollback 只能走 `historical_runner_preflight.sh`：active run 会收到 pause request，必须等 step/事务安全结束并进入 paused；超时直接停止部署。普通脚本先停 beat，再由 `wait_for_celery_drain.sh` 要求所有 worker 可响应且 active/reserved 均为 0，之后才停 worker；排空失败时 beat 保持停止并中止部署。脚本只允许 `--no-deps` 更新 web/worker/beat/nginx，不得 pull/start/stop/recreate DB、Redis、runner 或 networks。初次 DB/Redis/shared network 只能显式设置 `CONFIRM_INFRASTRUCTURE_BOOTSTRAP=create-db-redis-network` 后单独运行 `bootstrap_infrastructure.sh`。
3. migration 后使用 `provision_historical_runner.sh` 幂等创建 `umanews-historical-runner-db` internal 网络和 `umanews-historical-runner-egress` 网络，只把既有 DB 以 alias `db` 接入 internal 网络；control role `historical_runner_control` 仅可 SELECT/INSERT/UPDATE Run/Lock、SELECT/INSERT RunEvent，不得 DELETE 审计事件或访问业务表。密码文件必须为 0600。
4. `historical_runner.sh start` 只接受完整 `sha256:<64>` image ID 和匹配 OCI revision。artifact 挂载到 `/app/historical-runtime`；owner token 与 phase env 必须分别位于 `/opt/umanewsbot/runtime/historical_runner_secrets/<run_id>.token` 和 `<run_id>.<phase>.env`，真实路径不得落在 artifact，且均为 0600。phase env 不得包含重复键且只含 allowlist，`POSTGRES_APPLICATION_NAME=umanews-historical-runner:<run_id>:<phase>`。crawl/verify 必须使用 `historical_runner_control`，apply 必须通过宿主 `HISTORICAL_RUNNER_APPLY_ROLE` 显式绑定既有业务写入角色，两者不得相同。
5. crawl phase 设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`、`ALLOW_NETWORK=true`，使用 control role并连接 egress/internal 两网；apply phase 设置 enabled=true、allow_network=false，只连接 internal 网络并使用批准 importer 凭据。任何 phase 均不得复用常驻 `.env`，apply env 不得含翻译、OSS、OneBot、SMTP 或其他 API 密钥。
   - crawl env 必须显式设置请求预算 `1..250`、source cache `1..2147483648` bytes、磁盘底线至少 `5368709120` bytes。启动脚本会在 `docker create` 前读取 `df -Pk`；空间不足直接停止，禁止降低底线绕过。
   - Django runner 会再次校验同一边界，并覆盖子进程的 `RACE_EVENT_CRAWL_*`：请求间隔固定 1 秒，请求账本为 `<artifact>/runner-request-budget.json`，cache 根目录为 artifact，manifest 为 `<artifact>/runner-source-cache-manifest.json`。正式启动后应检查这些文件路径，不得看到 `/tmp` 或 artifact 外路径。
   - 请求账本和 cache manifest 的存在状态、大小、SHA 会保存在 `runner-state.json` 与数据库 checkpoint 顶层。暂停后不得手工删除、改小或预建这些文件；任何漂移都会把 run 转为 blocked，必须保留现场审核，不能通过新建 run 规避已经消费的请求额度。
   - runner 取得双锁后会在首个 crawl step 前保存资源基线；step 可控失败时会在释放锁前刷新失败时身份。若宿主强杀导致无法收尾，恢复必须因基线漂移 blocked，先审计现场，不得删除账本重跑。
   - `python_tool` 还必须位于生产赛事工具显式白名单。新增脚本即使已经进入镜像和 tool manifest，也必须先更新 runner 白名单与回归测试；看到 `Python tool is not approved for historical batches` 时不得临时改 plan 运行无关脚本。
   - 若 plan 使用 `orchestrate_race_event_crawl`，其 AdapterRunner 必须继续写上述父级账本和 manifest。adapter 自己的 policy 只能把请求/cache 调低或把间隔/磁盘底线调高；运行后若在 adapter 子目录出现新的 `request_budget.json`，视为门禁回归并停止批次。
6. 启动后运行 `historical_runner_smoke.sh crawl|apply`，验收容器不超过 2 CPU/2 GiB/256 PID、只读根目录；crawl 更新 `stable_raceevent` 必须权限失败但控制表可读，apply `SELECT 1` 必须成功而到 `1.1.1.1:443` 必须失败。再验收双锁、心跳、status JSON、暂停/恢复、日志轮转与 checkpoint，不以“容器 running”代替成功。子进程原始流只进入 256 MiB `/tmp` tmpfs，结束后脱敏写入 `runner-logs`；失败状态必须保留脱敏诊断尾部。
7. stale takeover 只有租约过期、旧容器不存在、`pg_stat_activity` 无 `umanews-historical-runner:<run_id>:<phase>`、runtime/DB checkpoint 完全一致时才可执行。必须在宿主设置固定 image/run/phase/artifact/token/env 变量及 `HISTORICAL_RUNNER_TAKEOVER_ACTOR/REASON` 后运行 `historical_runner.sh takeover`；脚本实际检查旧容器不存在，并以 internal-only 一次性容器只读挂载 artifact，核对固定 `/app/historical-runtime/runner-state.json`。不得直接调用管理命令伪造 `--container-absent`，也不得传入内容相同的替代 checkpoint。任一条件缺失均停止，不删除 lock、不盲目重跑未 checkpoint 的 apply step。
8. `status/preflight` 从普通 web 容器执行时看不到宿主 artifact，`checkpoint_matches=null` 只表示未挂载，不能用来批准接管；接管必须走上一步的宿主只读挂载探针。batch006 selection 已生成 `1061` 场，法国/香港/日本/英国/美国为 `250/61/250/250/250`，与既有有效批次零重叠；manifest SHA-256 `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`。资源门禁补丁完成新镜像、生产至少 5 GiB 可用空间和强化 smoke 前，不得启动正式 crawl。全过程保持常驻历史 enabled/network false、published 0。
9. 资源门禁最终候选固定为 `umanewsbot:main-84217c56-amd64-20260714-2220`，image ID `sha256:2e8bd05f5c138a8dfd5d5012c5ecfc811422fef2ec3ae5cbe4ed2ed45b28b31e`，revision `84217c56a3c483d9ff08029729f16c11bd1f42ad`，tree `61341c7e3256ec417d243a809254afd91acab6b2`，source archive SHA-256 `aee41ac51b5347d5a1c146074079fed49e1b23dc08518ddeef36405fe6d406af`；两个独立源码上下文构建 ID 一致，镜像内 check、migration drift、runtime 专项 `239/239` 通过（跳过 1）。过渡候选 `82fa4a3f/sha256:01397d15...` 缺少最新归属反例修复，`sha256:119f59e3...` 的 revision 标签不是有效 Git 对象，二者均禁止部署。镜像内 runtime 专项须从 `/app` 运行；生产 Compose 静态契约文件按设计不在运行镜像中，该测试只能在完整源码树执行。部署前仍须重新 fetch 最新 main、核对候选 revision 未落后，并取得新闻维护窗口的明确交接。
10. 2026-07-15 最终部署使用包含生产工具根补丁的 `main@c4087e6c`，image ID `sha256:5eb6471c8c1e96c90198e519c4d02f1b74316d6a13dbc93e9b63c0981ad22600`，tree `95f7ba384c791e16b7f401dfca9adb744bbb4ed0`，source archive SHA-256 `5051285c4bc8b5daa1355eec5be433f95d7193e8302126e3bfb359309672aec7`；旧镜像回滚标签为 `umanewsbot:rollback-pre-c4087e6c-20260715-0610`。写前备份 `/opt/umanewsbot/backups/db/pre-main-c4087e6c-20260715_060549.dump` 为 `141446379` bytes，SHA-256 `60331b0840a98e00370f2a5c10724d2e0e9ee370724ac572be8b0cd54781e341`，`pg_restore -l` 通过。
11. 部署后重新执行 provisioning、crawl/apply 隔离、40 秒 step 暂停/恢复与工具根拒绝 smoke。artifact 子目录 `/app/historical-runtime/batch-006` 不能自声明为 tool root；拒绝必须发生在创建 `HistoricalBatchRun` 前。apply 的旧 Python smoke plan 现在按设计被“仅允许审批感知管理命令”拒绝，网络/角色隔离使用相同容器参数的短时 apply 容器验证，不能把旧 plan 强行加入白名单。
12. 收口状态以 `manage_historical_batch_runner preflight --json` 返回 `migration_safe` 为准；web/worker/beat 必须为同一 image，worker consumer 保持取消、beat 保持 `Created`，常驻历史 enabled/network false、published 0。2026-07-15 收口可用空间为 `7856596 KiB`。batch006 正式 plan 仍须绑定 selection、manifest、审批、image 和 tool SHA，并将 1061 个目标按单 run 请求预算不超过 250 分片；禁止把 batch005 `tmp/` 脚本复制进 artifact。

## 2026-07-14 batch005 250 场正式导入记录

1. batch005 使用固定生产镜像 `sha256:954673cc74049d4b882e492ec29b072aba01aeb1a3ae440cc85415209c8a2f8a` 完成；所有历史管理命令均为显式 `docker run --rm`，没有使用 Docker Compose，也没有重建 DB、Redis 或共享网络。
2. 日期 artifact manifest `0bedb2ad10d71bc3c22f11b4c42b5ee70708a50c9359b6f661739baff242c861`，详情来源 manifest `c629b5f7e6485f81b7a0a5bcc7252947eddef1a85674d124c9853828a60fcaf7`；两阶段 check/apply 均为 250/250。详情来源 apply 后重新导出 event input，最终候选 `269c65e646b11be0a1edef70c8c088e5b4b9a2b0a69527ca0efc6242cb84d6e3` 为 250 scopes / 0 gaps，dry-run 通过。
3. 三份 custom-format 写前备份均通过 `pg_restore -l`：日期写前 `/opt/umanewsbot/backups/db/pre-batch005-date-20260714_052929.dump`，SHA-256 `34ca0038ff8795929384b287ea34a7615c2a057b1d49ab10d1eaf6a161c57d2f`；详情来源写前 `pre-batch005-detail-source-20260714_055621.dump`，SHA-256 `0fbf2eb9915ed9e7f52aca515353135527772ea2c4b981cb20241c2d474999b3`；最终详情写前 `pre-batch005-final-20260714_055856.dump`，SHA-256 `82908208d5a32f751c1b7c258c54e3ac66993798d27b66ff6d1405393a10ffa9`。
4. 写入前因自然新闻窗口已有 active 任务，先停止 beat，再让 active 任务自然结束；随后暂停 worker 的 `celery` consumer，仅保留 Redis 队列，确认 active/reserved 为空后写入。不得终止正在执行的新闻任务，也不得清空队列。
5. 最终 apply 250/250，验收为法国 `50/414/327`、香港 `50/482/469`、日本 `50/714/710`、英国 `50/489/433`、美国 `50/484/425`，格式为 `events/runners/results`；error 0，250 场全部 draft。
6. 写后先使用 `celery -A app control add_consumer celery` 恢复 worker 消费，再启动原 beat 容器；web/worker/beat 镜像一致，healthz 正常，历史常驻写入/网络开关 false，无遗留 historical one-off。生产累计 `1291 imported / 29626 pending`、`13507 runners / 12167 results`、published 0。
7. batch006 前必须先部署并验收独立 historical batch runner 和每地区 250 场新口径。runner 部署不得使用会重建 DB/Redis 的 Compose 操作；必须具备固定镜像、独立锁/心跳/checkpoint、资源限制、普通部署隔离、迁移安全暂停，以及抓取与落库权限分离。
## 2026-07-14 多地区归属 V3 单审与性能验收口径

- PostgreSQL 性能验收必须使用带真实来源关联的 250 篇文章和当前量级术语/alias，不能使用 `source_config=NULL` 的空 fixture。当前基准规模为 17,474 条术语、21,240 条 alias、38,806 个索引候选和 17 个来源；通过值为 5 SQL、1.66–2.14 秒、约 49 MiB RSS。
- 单审 Gold Set 使用 `evaluate_multiregion_attribution_gold --provisional`；该参数允许一位审核人的标签进入分母，但不豁免有效样本 150、五个运营地区各 10、跨地区 20 和质量门槛。生成归属 dry-run 时必须同时传 `reprocess_multiregion_attribution_gates --single-review-gold --gold-labels <csv> --dry-run ...`，否则单审标签按严格多人审核口径视为未决。
- 生产归属资格 dry-run 必须额外传 `--scope all_articles --hours 72`，并且不得传 `--limit`。只有输出 `scope_complete=true` 时，全部 `primary_change_ids`、`needs_review_ids`、`locked_skip_ids` 和 `review_sample_ids_by_region` 才构成完整人工清单。默认 `gate_candidates` 仅用于术语门禁补跑，不得作为 Shadow 上线证据。
- `all_articles` 默认不执行逐篇发布门禁，`validation_skipped_ids` 应覆盖全部候选；只有显式传 `--include-gate-validation` 才产生 `validation_passed_ids/validation_blocked_ids`。后续按 manifest commit 时只回填归属，不修改文章门禁、重新入榜时间、发布状态或 QQ 交付。
- dry-run 已持久化但 stdout 报告中断时，使用 `export_multiregion_attribution_run --run-id <id> --manifest-sha256 <sha> --output <new.json>` 原子重建，不重复运行推断。输出文件必须是新路径；`missing_article_ids/drifted_article_ids` 必须全部进入人工清单，非空时不得直接 commit。
- 单审 Gold 因正文清理发生 SHA 漂移时，先从原 Excel 审核表生成只读 review snapshot，再执行 `reconcile_multiregion_attribution_gold --labels <old.csv> --review-snapshot <snapshot.csv> --output-dir <new-dir>`。只接受 `auto_refreshed`，任何 duplicate、title/source/body/inference blocker 均保留旧 SHA 并从有效分母剔除；不得手改 SHA。
- France Galop 部署后先运行只读 source probe，样本必须同时有真实页面日期、`published_at_verified=true` 和非空 evidence；随后自然抓取纠正文章时间。禁止用当前抓取时间批量回填旧文。
- `scope_complete=false` 的 `all_articles` run 会在 commit 入口被强制拒绝；人工复核以 `review_checklist_ids` 对应的 outcome 为准，outcome 内含标题、来源 URL、来源站点、发布时间、before/after、证据、置信度和状态。
- 当前待切换候选：main `7f0827ad941452524062d478940c85bdfddf4a59`，tag `umanewsbot:main-7f0827ad-amd64-20260714-1707`，image ID `sha256:6ad16e368d7934777a689e537c70618a6321c3466d02f304116e2f61ae2af9a1`。必须先等待 `news-translate-20260713-r3` 自然退出并重新确认 one-off、TranslationRun、Celery active/reserved、归属/外部导入锁均为空；不得在文章正文/指纹仍变化时生成 72 小时 manifest。
- 单审文件必须保留 `reviewer_roles=reviewer_a` 和 `adjudicated=false`，不得复制 reviewer B。多人审核发生冲突时仍必须裁决。空白未选择行不进入分母，明确 `exclude` 单独留档。
- 通过 Gold Set 只允许把生产从 `off` 切到 `shadow`。shadow 至少运行 24 小时，必须复核全部主地区变化、全部 `needs_review`、各地区随机稳定样本和错误日志；未完成前禁止 `enforce`。
- shadow 验收通过后，第一阶段只对新文章 enforce，`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 继续保持关闭；再观察至少 24 小时后才讨论网页/测试 QQ 群相关地区查询。
- Gold Set 每次新增来源、调整规则、发现 shadow 误判或形成运营争议后都应新增版本，并记录输入 SHA、审核来源、规则/术语版本和前后指标。当前 159 条已满足 `150/10/20` 覆盖及全部质量门槛，只允许从 `off` 进入 shadow；不可据本节直接开启 enforce 或相关地区查询。
- 相关地区首发门槛为 precision `>=95%`、recall `>=50%`、过度扩散 `<=1%`。recall 代表漏标：线上短期低于 50% 时记录告警、冻结下一阶段，不自动关停；precision 跌破 95%、出现明显错标或过度扩散超标时，立即关闭相关地区查询并评估退回 shadow。

## 2026-07-14 DB/Redis 意外重建与新闻索引恢复

- 事故入口：生产只读命令误用 `docker compose run --rm -T web`，导致 DB/Redis 依赖容器被重建。以后只读排查统一使用 `docker exec umanewsbot-web-1 ...`；不得将 `compose run` 当作无副作用命令。
- 发现索引异常后的顺序固定为：停止 beat -> `celery control cancel_consumer celery` -> 等 active 清空 -> 停 worker -> 完整 `pg_dump | gzip` 并执行 `gzip -t`/SHA-256 -> 强制顺序扫描查重 -> 在单事务内迁移重复行外键与审计记录并删除冗余行 -> `REINDEX TABLE CONCURRENTLY stable_newsarticle` -> `VACUUM (ANALYZE, VERBOSE) stable_newsarticle`。
- 本次权威备份：`/opt/umanewsbot/backups/db/pre-newsarticle-dedup-reindex-20260714_020918.sql.gz`，`156642923` bytes，SHA-256 `f37ff4835fe13d4c2a016beac433940ef995677e690711dc68ca59f42b149a9e`。恢复后必须确认 identity 重复为 0、17 个索引全部 valid/ready、worker active/reserved 与 Redis 队列可解释。
- 恢复服务时先只启动 worker 消化事故前保留队列并验证一条真实文章写入；队列与 active 清空后再启动 beat。随后至少验收一个完整 15 分钟窗口的来源抓取、五地区发布、QQ、数据库/worker 日志和三个公网 `/healthz/`。
- 本次 `02:15` 窗口 17 个来源全部 succeeded，发布/QQ 各五地区全部 succeeded，美国发布 1 篇；索引重建后无重复键或索引页错误。若再次出现任一索引结构错误，立即重新冻结生产写入并从上述备份分支排查，不做第二轮在线试错。
## 2026-07-14 日文赛马翻译与固定格式部署及回归

1. 最终提交为 `873845dacb1cec0353ed9b9834417a1a00cc6311`；干净 `git archive` SHA-256 为 `2c00bf5bee4e824d5bd3cb408af942b5a255dd88f30de1b24436cab289ec3e09`。正式 tag 为 `umanewsbot:main-873845da-amd64-20260714-1248`，AMD64 image ID `sha256:d3f602de4459158bc372e45bb35f3730a7be21f284dfea32de5535681bd6d791`，revision/archive 标签均已核对。
2. 候选 PostgreSQL `jp-translation-db-b7dab422` 上无待迁移、Django check 和迁移漂移通过，关联 `84` 项测试通过；生产切换前 Redis queue、worker active/reserved、外部导入、归属和术语重处理 live run 均为 0。候选验收完成后已删除该数据库容器。
3. 写前备份为 `.env.backup.pre-873845da-20260714_124940` 与 `backups/db/pre-873845da-20260714_124940.dump`；数据库文件 `134234023` bytes、SHA-256 `413718143809a09686ea18710a4cd8b8f9a9f7643fb6b769cee5daf23ca485a6`，通过数据库容器内 `pg_restore -l`。回滚 tag `umanewsbot:rollback-pre-873845da-20260714-1254` 指向旧镜像 `sha256:b14844ee027a7902db2ed22c9b310e8240dd2d84f822d2785a28799271e3a1a2`。
4. 切换时保持 beat 停止，只用最终 `prod` 镜像执行 migrate、Django check 和 `makemigrations --check --dry-run`，再以 `--no-deps` 重建 web/worker。目标文章和随机样本全部通过后才以同镜像重建 beat；最终三服务 image ID 必须完全一致。
5. 目标 `8304/8299/8298/8291/8290/8288/8287/8283/8276/8219/8212` 必须核对普通词零残留、固定格式、完整未知马名、内部占位符、状态、发布时间、人工字段和 QQ 次数。生产实际 QQ 基线为 `8298/8288/8283` 各 1，其余 0；任何新增均为阻断。
6. `8287` 的随机模型重译若被门禁拒绝，不得降低门禁。当前公开稿基于成功 run `8613`，只在事务内精确替换两处“类型类型”和一处“公开级级别”，恢复 translated 状态并记录 `article_translation_boundary_repaired`；失败 run `8622` 继续保留审计。随后运行不带重译的 `reprocess_article_entities --article-id 8287 --commit --json` 重建实体 provenance。
7. 随机回归固定记录 `8337/8366/8356/8307/8367`；`8367` 的 tags 与 machine tags 均不得包含“出走”。最终验收使用 HTTP：healthz、首页、后台及 11 篇详情均为 `200`；HTTPS 尚未启用，不属于本 change 入口。Redis queue、active/reserved 为空，近 15 分钟无 fatal/traceback，历史写入/网络开关 false、历史 published 0。
8. 回滚先停 beat 并排空 worker，将 `umanewsbot:rollback-pre-873845da-20260714-1254` retag 为 `prod`，再重建 web/worker/beat。代码回滚保留新增术语数据；只有确认生产数据损坏时才恢复上述 custom-format 数据库备份。

## 2026-07-14 新闻实体语境修复部署与回归

1. 最终上线提交为 `dc1e5ec584e47ea9d28998f76454d105836b3f0a`，源码 archive SHA-256 `f2eec61f6d2211a76e4456f6b9cbfc3e55a5b610829162b4a68b6039aae6ffe1`；正式镜像 tag 为 `umanewsbot:main-dc1e5ec5-amd64-20260714-075837`，image ID `sha256:5b06821610f0d2214cb24692e58beac4ffda731ddb84674a8855b2a1d4dbb470`。
2. 生产写入前备份 `.env.backup.pre-main-624dd5b9-20260714-071014`；数据库 `backups/db/pre-main-624dd5b9-20260714-071014.dump` 为 `133370327` bytes、SHA-256 `21cdce21f52ded3b48e7c083f2f536eb694130f71ad6a1e38e067620f817fa75`，`pg_restore -l` 通过。回滚 tag 为 `umanewsbot:rollback-pre-624dd5b9-20260714-071014`。
3. 候选镜像必须先通过 Django check、迁移漂移、实体目标测试和完整回归；切换时暂停 beat、等待 worker active/reserved 和 Redis queue 清空，按 web、worker、beat 顺序恢复，并确认三个服务的完整 image ID 一致。
4. 存量修复只使用 `reprocess_article_entities` 的显式文章 ID：先 dry-run，再逐篇 `--commit`；需要修正文译文时使用同步强制重译，随后再次 dry-run 和 `validate_rewrite`。每轮必须保存 before/after，核对 `workflow_status`、`published_to_web_at`、QQ delivery、人工标签及 `MANUAL/REMOVED` 关联完全不变。
5. 本次修复 `8086/8212/8221/8283/8288/8290/8291/8309/8317/8318/8330`；11 篇保持原公开身份及 QQ 次数。随机样本 `8390/8388/8386/8385/8383/8380` 最终 dry-run 无增删差异，最终 worker 新处理的 `8393/8394` 也通过实体解析和发布校验。
6. 上线后以 HTTP 运行态验收：`umafans.run` 与 `www.umafans.run` healthz、首页、后台登录和 11 篇详情均为 `200`。HTTPS 尚未启用，不作为本 change 验收入口。最终 Redis queue、Celery active/reserved 均为空，近 15 分钟 web/worker/beat 无 error/traceback；历史写入/网络开关为 false、归属模式为 off、历史 published 为 0。
7. 若需回滚，先暂停 beat 并排空 worker，将 `umanewsbot:rollback-pre-624dd5b9-20260714-071014` retag 为 `prod` 后重建 web/worker/beat；本 change 无迁移，只有确认实体重处理造成生产数据损坏时才恢复数据库备份。

## 2026-07-14 国际新闻正文边界修复部署与回归

1. 最终上线提交为 `514af8a22aec18f01cf0193344ae3b7a45c4dbc4`，Git tree `b62a80cc34b2b65c47f6dd7d541c455d04a0ef5c`。使用 `git archive` 独立构建上下文，archive SHA-256 `507b95c9b3e3ab66b67e4813b6b4814d2e4bc3d6cb2aae6abc7ad357322ad039`；缓存/无缓存双构建的 `/app` manifest 一致，SHA-256 `2ada2d84788d048fcfd86d589762c2b159256d1a884581ac819a614aacf92aea`。
2. 正式镜像 `umanewsbot:main-514af8a2-amd64-20260714-050736`，image ID `sha256:954673cc74049d4b882e492ec29b072aba01aeb1a3ae440cc85415209c8a2f8a`。切换前 worker active/reserved、外部导入 run/lock 均为空；候选镜像 Django check、迁移漂移和正文边界 27 项测试通过。
3. 最终切换前备份 `.env.backup.pre-main-514af8a2-20260714-051127`；数据库 `backups/db/pre-main-514af8a2-20260714-051127.sql.gz` 为 `158552943` bytes，SHA-256 `9fc72efba29ee8d32c9709665809d259ca49e47a217c43626c99b084d99d4b0a`，`gzip -t` 通过。旧镜像回滚 tag 为 `umanewsbot:rollback-pre-514af8a2-20260714-051127`，image ID `sha256:5d7c09bd25fbb45999f2e8109995736f93f4d3011e37299033cae4773e4968c1`。
4. 将候选 retag 为 `umanewsbot:prod` 后，依次执行 migrate、Django check、`makemigrations --check --dry-run` 和 collectstatic，再只重建 web/worker；四篇目标文及五篇抽检文回归完成、worker 清空后，以同一镜像重建 beat。最终 web/worker/beat 镜像 ID 和 revision 一致。
5. 旧版“dry-run 后直接追加 `--commit`”流程已失效。历史文章源正文修复必须先取得针对精确文章集合和动作的单独授权，并在已验证备份和安全窗口后按以下 fail-closed 流程执行；本文档只定义操作步骤，**不自动批准任何历史重处理**。

   先用显式 ID 保存 dry-run JSON；变量名不得复用系统 `HOME`，目录已存在时必须停止：

   ```sh
   set -o errexit -o nounset -o pipefail -o noclobber
   umask 077

   ARTICLE_IDS=(8086 8267 8316 8318)  # 本章已记录的精确目标全集
   RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
   ARTIFACT_DIR="/app/runtime/news_integrity/article-content-boundary-${RUN_TS}"
   DRY_RUN_JSON="${ARTIFACT_DIR}/dry-run.json"
   APPROVED_MANIFEST="${ARTIFACT_DIR}/approved-manifest-v2.json"
   MANIFEST_SHA_FILE="${APPROVED_MANIFEST}.sha256"
   COMMIT_JSON="${ARTIFACT_DIR}/commit.json"
   ARTICLE_ARGS=()
   for ARTICLE_ID in "${ARTICLE_IDS[@]}"; do
     ARTICLE_ARGS+=(--article-id "${ARTICLE_ID}")
   done

   mkdir "${ARTIFACT_DIR}"
   python manage.py repair_article_content_boundaries "${ARTICLE_ARGS[@]}" \
     > "${DRY_RUN_JSON}"
   jq -e '.mode == "dry_run" and (.articles | length > 0)' "${DRY_RUN_JSON}" >/dev/null
   SOURCE_SITE="$(jq -er '
     ([.articles[].source_site] | unique) as $sources
     | if (($sources | length) == 1)
          and (($sources[0] | type) == "string")
          and (($sources[0] | length) > 0)
       then $sources[0]
       else error("dry-run 必须精确只包含一个 source_site；混合来源必须分批")
       end
   ' "${DRY_RUN_JSON}")"
   ```

   到此必须停止并人工审查同一份 `dry-run.json`。每个 `articles[]` 行直接与该 `article_id` 绑定提供：

   - `before_body_start_excerpt` / `before_body_end_excerpt` 与 `after_body_start_excerpt` / `after_body_end_excerpt`：修复前后正文的首尾短摘要，**不是完整正文**；
   - `before_length` / `after_length` / `length_delta`、正文前后 SHA-256、`original_content_html_sha256`、解析选择器和清理计数；
   - `workflow_status` / `translation_status` / `automation_status`、`effective_body_layer` / `effective_body_sha256`；
   - `manually_edited_fields`、`has_rewrite_body`、`published_to_web_at`、`qq_delivery_count`。

   人工审查以这些已绑定同一 ID 精确集合的字段为准，逐篇核对来源、修复前后首尾、长度/哈希、当前有效正文层、人工/改写标记、状态、公开时间和 QQ delivery；不再依赖另一个未定义查询。未明确决定为 `repair_source_body` 的文章不得进入 manifest。审查通过后，从该 dry-run 的每行只提取固定 schema v2 字段，并在生成前核对精确来源与 ID 集合。v2 除 raw 正文外，还必须绑定 commit 将持久化的标题、normalized 正文和 parse metadata；旧 schema v1 不得继续使用：

   ```sh
   REQUESTED_IDS_JSON="$(printf '%s\n' "${ARTICLE_IDS[@]}" | \
     jq -Rsc 'split("\n") | map(select(length > 0) | tonumber) | sort')"
   EXPECTED_COUNT="${#ARTICLE_IDS[@]}"

   jq -e --arg source_site "${SOURCE_SITE}" \
     --argjson requested_ids "${REQUESTED_IDS_JSON}" \
     --argjson expected_count "${EXPECTED_COUNT}" '
       (.mode == "dry_run") and
       (.articles | length == $expected_count) and
       (($requested_ids | unique | length) == $expected_count) and
       (([.articles[].article_id] | sort) == $requested_ids) and
       (all(.articles[];
         .source_site == $source_site and
         .body_parse_status == "ok" and
         (.updated_at | type == "string" and length > 0) and
         (.original_content_html_sha256 | test("^[0-9a-f]{64}$")) and
         (.before_body_sha256 | test("^[0-9a-f]{64}$")) and
         (.after_body_sha256 | test("^[0-9a-f]{64}$")) and
         (.after_title_sha256 | test("^[0-9a-f]{64}$")) and
         (.after_body_normalized_sha256 | test("^[0-9a-f]{64}$")) and
         (.after_parse_metadata_sha256 | test("^[0-9a-f]{64}$"))))
     ' "${DRY_RUN_JSON}" >/dev/null

   jq -S --arg source_site "${SOURCE_SITE}" '
     {
       schema_version: 2,
       source_site: $source_site,
       articles: (
         .articles
         | map({
             article_id,
             decision: "repair_source_body",
             updated_at,
             original_content_html_sha256,
             before_body_sha256,
             after_body_sha256,
             after_title_sha256,
             after_body_normalized_sha256,
             after_parse_metadata_sha256
           })
         | sort_by(.article_id)
       )
     }
   ' "${DRY_RUN_JSON}" > "${APPROVED_MANIFEST}"

   jq -e --arg source_site "${SOURCE_SITE}" \
     --argjson requested_ids "${REQUESTED_IDS_JSON}" '
     .schema_version == 2 and
     .source_site == $source_site and
     (([.articles[].article_id] | sort) == $requested_ids) and
     (all(.articles[];
       .decision == "repair_source_body" and
       (.after_title_sha256 | test("^[0-9a-f]{64}$")) and
       (.after_body_sha256 | test("^[0-9a-f]{64}$")) and
       (.after_body_normalized_sha256 | test("^[0-9a-f]{64}$")) and
       (.after_parse_metadata_sha256 | test("^[0-9a-f]{64}$"))))
   ' "${APPROVED_MANIFEST}" >/dev/null

   MANIFEST_SHA256="$(sha256sum "${APPROVED_MANIFEST}" | awk '{print $1}')"
   printf '%s  %s\n' "${MANIFEST_SHA256}" "${APPROVED_MANIFEST}" \
     > "${MANIFEST_SHA_FILE}"
   sha256sum --check "${MANIFEST_SHA_FILE}"
   ```

   `after_parse_metadata_sha256` 的算法固定为：只取将写入 `translation_metadata` 的
   `body_parse_status/body_selector/body_cleaning`，使用 UTF-8
   `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))` canonical JSON 后计算
   SHA-256。不得改用默认 JSON 空格、ASCII escape 或包含其他临时字段的摘要。

   必须先保存并人工审核 `dry-run.json`、`approved-manifest-v2.json`、`.sha256` 和实际 SHA 值，确认 manifest 中的 ID 精确等于授权全集后，才可执行写入。commit 必须同时传入 manifest 文件和已审核 SHA：

   ```sh
   sha256sum --check "${MANIFEST_SHA_FILE}"
   python manage.py repair_article_content_boundaries "${ARTICLE_ARGS[@]}" \
     --commit \
     --manifest "${APPROVED_MANIFEST}" \
     --manifest-sha256 "${MANIFEST_SHA256}" \
     > "${COMMIT_JSON}"
   jq -e '.mode == "commit"' "${COMMIT_JSON}" >/dev/null
   ```

   命令会在单一事务中锁定全部 ID，重新解析并校验 `source_site`、`updated_at`、
   `original_content_html_sha256`、`before_body_sha256`、`after_body_sha256`、`after_title_sha256`、
   `after_body_normalized_sha256` 和 `after_parse_metadata_sha256`；文件 SHA、schema、ID 集合、缺字段或任一
   逐篇输入/输出漂移时命令必须失败，整批零写入、零 OperationLog。原文层 commit 不会自动批准翻译、改写、
   重新公开或 QQ 发送；后续层须根据人工正文/机器改写情况另行审核和授权。每批仍要比对
   `workflow_status`、`published_to_web_at` 和 `QQPushDelivery`，禁止重复公开或群发。
6. 本次目标 `8086/8267/8316/8318` 均保持已发布和原发布时间，QQ delivery 为 0；随机样本 `8306/8311/8326/8331/8336` 最终保存正文与当前重解析逐字一致，状态 `ok`、无博彩/链接/编辑注/页脚噪声。已发布 `8326` 保持 `2026-07-13T17:47:04.152562Z`，QQ delivery 为 0。
7. 回归通过内外 `/healthz/`、首页、后台登录、`/news/8086/`、`/news/8267/`、`/news/8316/`、`/news/8318/`、`/news/8326/` 和近 200 行 web/worker 日志；Celery active/reserved 为空。若回滚，先停 beat 并排空 worker，将 `umanewsbot:rollback-pre-514af8a2-20260714-051127` retag 为 `prod` 后重建 web/worker/beat；本次无迁移，只有确认数据损坏时才恢复数据库备份。

## 2026-07-14 batch004 250 场正式导入记录

1. 运行镜像保持 `sha256:87c435cfc50344d0ca94f46e44d4bea97ab11361f88f7c708b6457331aee78ec`；本批没有 build、retag、recreate 或 restart，所有管理命令均使用显式 `docker run --rm`，禁止 Docker Compose。
2. 日期 artifact manifest `30ff2c0fe14e4d6ce7d9ee7123d882d99838853e381627b552b9b0ac19dd2ea0`，批准并 apply 250/250；五地区各 50，日期、event 和直接来源 250/250，published 0。
3. 详情来源 artifact manifest `cf5bfdc1cc8c6c82732d6485e1815f582a47d057010e4d1c0214ec3103fd46a8`，check/apply 250/250。来源 apply 后重新导出 event input；最终候选 SHA-256 `ddd1f8256cef0b17aabc33ea66f7a0638a2d6498c2d23342daff8835b10a5156`，250 scopes / 0 gaps，dry-run 通过。
4. 详情来源写前流式备份 `pre-batch004-detail-source-apply-20260714_031200.sql.gz` 的首次校验发生在进程未结束时，曾报截断；最终文件 `128991200` bytes，`gzip -t` 通过，SHA-256 `dbe05660aaae9e1957c21b84d714c3340a81a3a59aedef4dcf5f99caae5509e5`，可用于回到来源 apply 前。最终详情写前另有 `/opt/umanewsbot/backups/db/pre-batch004-detail-import-20260714_0325.dump`，`129830849` bytes，SHA-256 `e50bd095bfa141ea0f05bf77fda68a508808dcddac4cbacb8fdb4ce3860e758a`，`pg_restore -l` 通过。
5. 最终详情 apply 250/250，写后为 `2563 runners / 2311 results`、500 applied candidates、250 import logs，重复非空马号和重复名次均为 0。NSA target `74171` 因官方 PDF 不给马号，允许 8/7 条空 `horse_number`，不得补造号码。
6. 批次后累计 `1041 imported / 29876 pending / 0 ready`，250 场全部 draft，历史 published 0。常驻写入/网络开关 false，无 one-off，三个公网 healthz 为 `ok`。
7. batch005 前必须由生产协调线程从含 `main@614f810e` 的干净 tree 构建并切换 AMD64 镜像；历史线程不得自行重建或重启生产。切换后再生成下一标准批次，并继续传入既有排除 snapshot。

## 2026-07-14 已耗尽地区进度门禁交付要求

- 交付前必须确认代码包含 `eligible_pending_by_region` 与 `progress_guard_regions`，并通过历史批次专项、完整 `stable`、Django check、迁移漂移和 旧规格流程 strict。该修复无迁移、无新环境变量，不改变常驻历史开关。
- 生成下一标准批次时仍必须传入所有既有 gap 的 `--exclude-selection-snapshot`。审核 summary 时同时核对：`remaining_pending_by_region` 仍包含待审排除项，`eligible_pending_by_region` 已扣除排除项，`progress_guard_regions` 只列本批后仍有可抓目标的地区。
- 若两个或以上 `progress_guard_regions` 的 prospective accounted 差超过 100，命令必须失败；恰为 100 可继续。某地区抓空或仅剩显式排除项时可退出比较，但不得据此修改其 expectation/resolution 或从总账删除。
- 代码已合入 `main@614f810e`，尚未部署。必须从最新 main 的干净 tree 构建可复现 AMD64 镜像，由生产协调线程完成镜像切换和健康验收后，才可用于后续批次 artifact；不得从本地分支直接执行生产写入。

## 2026-07-13 后续标准批次既有选样排除门禁

- 旧 batch003 与 batch002 重叠 4 个 pending gap，必须删除或隔离，禁止审批、抓取或写入。新批次只允许由包含本门禁的已提交 AMD64 镜像生成。
- 生成时追加 `--exclude-selection-snapshot /workspace/runtime/historical_race_batches/2016-2025-batch-002-20260713/selection_snapshot.json`；如还有其他仍含 pending gap 的旧批次，可重复传入该参数。不得手工摘取或改写 snapshot。
- 命令成功后必须核对：五地区各 50、与所有排除 snapshot 的 target ID 交集为 0、manifest 中存在 `excluded_selection_snapshot_NNN` 文件身份、复制件逐字节一致、summary 的 `excluded_pending_by_region` 与已知 gap 相符，且 `remaining_pending_by_region` 未扣除排除 gap。
- 当前实现仅在本地通过 42 项聚焦测试、完整 `stable 1157` 项、Django check、迁移漂移和 旧规格流程 strict/all；尚未部署。部署前先提交并同步 main，再交付可复现 AMD64 镜像；本门禁不要求重启常驻 web/worker/beat，可由协调线程批准后仅用于一次性只读批次生成。
- 全程保持生产常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false` 和历史公开关闭；本步骤不得执行生产数据库写入。

## 2026-07-13 2016–2025 第二标准批次 246 场日期与详情导入

- 运行镜像固定为 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`；revision `d8b65fe7d63e913cf826d02a74cdebaec60351ce`，Git tree `fda256535ae3b9f435cf8c7b069ff26d04503d99`。本批不得重建或重启生产容器。
- 日期 artifact：manifest `9ed3b713...02e68`，批准 246、gap 4。写前备份 `pre-band-2016-2025-batch002-date-apply-20260713_164248.sql.gz`，`150494499` bytes，SHA-256 `379f86de...b7c7`；apply 后 246 target 为 ready、246 event 为 finished/draft、published 0。
- 详情来源 artifact：manifest `ae9d20aa...b44d9`，check/apply 均为 246。写前备份 `pre-band-2016-2025-batch002-detail-apply-20260713_165007.sql.gz`，`124141632` bytes，SHA-256 `0b0423ae...9540`。来源 apply 后必须重新导出 event input，不得继续使用旧 target SHA 的导入包。
- 最终详情候选：`detail-package-v3/packaged_candidates.jsonl`，SHA-256 `735ec0dacafd9c388adb678b93ab402e45f991cb0e143c89a6fe067e606fc459`，246 scopes / 0 gaps，dry-run 通过。最终写前备份 `pre-band-2016-2025-batch002-candidate-import-20260713_165304.sql.gz`，`124218014` bytes，SHA-256 `a22967b6...0545`；apply 246/246 成功。
- 写后必须运行逐 target 验证脚本，核对候选与实际 runners/results、马号、名次、applied candidate 来源名/URL、module 状态和 visibility。已验收各地区为法国 `50/424/328`、香港 `50/463/453`、日本 `50/730/722`、英国 `48/464/417`、美国 `48/468/406`，error 0；历史累计 `541 imported / 5723 runners / 5143 results / published 0`。
- 一次性管理容器可以临时设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`；常驻 `.env`、web/worker/beat 必须继续为写入 false、网络 false。本批验收后无 one-off 容器，三应用容器镜像不变，HTTP 内外 healthz 正常，近 30 分钟错误扫描为空。
- 回滚按失败层级选择：日期或 materialize 错误用第一份备份；来源证据错误用第二份备份；来源正确但 runners/results 错误用第三份备份。恢复前先停历史 one-off，保留 artifact、source cache 和日志；恢复后重跑 target 状态、逐场详情、published=0、常驻开关和 HTTP healthz 验收。

## 2026-07-13 法港英 150 场字段校正与详情导入

- 字段 artifact：manifest `d6f6e29a...a2857`，候选 `59acc224...f50ac`；dry-run 为 150 scopes / 164 fields / 0 manual skip。写前备份 `pre-fr-hk-uk-field-corrections-20260713_134732.sql.gz`，`148521701` bytes，SHA-256 `30dc58d2...c94ce`，gzip 通过。
- 字段 apply 只在一次性管理容器临时设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`；写后核对 150 个 target SHA 改变、164 个字段/provenance、150 条目标日志和 1 条批次日志。常驻 web/worker/beat 设置未修改。
- 字段变化后旧详情候选 `38e05d...1950` 必须且确实被生产拒绝；重新导出候选 `a8fc8fbf...68da` 为 150 scopes / 0 gaps，法港英 runners/results 分别 `449/330`、`515/506`、`570/458`，150 个 URL 全局唯一，dry-run 通过。
- 详情写前备份 `pre-fr-hk-uk-detail-import-20260713_135954.sql.gz`，`148554120` bytes，SHA-256 `610c5407...f4db`，gzip 通过。apply 150/150 成功，写后逐 target 数量、candidate applied、source cache identity、马号/名次唯一性和 150 条导入日志全部通过。
- 最终生产历史为 295 imported、3174 runners、2817 results，295 个 pre-2026 RaceEvent 全部 draft，published 0；常驻历史写入与网络开关 false。150 个详情缓存 `38383091` bytes，大小/SHA `150/150` 通过。内外 healthz、Django check、容器和日志正常。
- 写后自然窗口：14:00 CST 的 17 个 crawl、5 个 publish、5 个 qq_push 均 succeeded；crawl seen/new/failed 为 `470/5/0`。publish 未发布且失败 0，零产出原因为 `hard_gate_blocked`、`no_ready_candidates`；QQ 未新增投递且失败 0，原因为 `already_sent`、`no_eligible_articles`。窗口后内外 healthz 正常，web/worker/beat 近 20 分钟错误扫描为 0。
- 回滚字段错误时优先使用字段写前备份；字段正确但详情错误时使用详情写前备份。恢复前先停一次性历史写入并记录当前 artifact/日志，不删除 source cache；恢复后重新执行 target、字段 provenance、详情计数和 published=0 验收。

## 2026-07-13 `main@df2732c3` 权威字段门禁镜像切换

- 目标镜像：`umanewsbot:main-df2732c3-amd64-20260713-1321`，image ID `sha256:27d5d51cbe2ae6d23cb99dc758da01addc2d5935504a950bbb8a2685bce2bf13`；两次构建一致，架构 `amd64`，revision `df2732c3b8ae47619728c52f54a95204f5d6b574`，Git tree `d2ce464b80ec595f82dc19a531c982429bb639af`，源码归档 SHA-256 `441eb2acb5c061aae5d22671e82ddccfafb2cb08af62711b030c0031354d8d5d`。
- 切换前备份：`.env.backup.main-df2732c3-20260713_132757`；数据库 `backups/db/pre-main-df2732c3-20260713_132757.sql.gz`，`148455898` bytes，SHA-256 `87cc176658cd2e57fa72c703bc1446e1e1930147a875d82cfccab7470d964776`，`gzip -t` 通过。旧镜像回滚 tag：`pre-main-df2732c3-20260713-1327`，image ID `sha256:e7ab7af0061d7362ad0582224baffc79eda07bd6d8f6467bfa573f760853877d`。
- 切换流程：停止 beat，等待 worker active/reserved 清空，核对外部导入/术语重处理/多地区归属 live lock 为 0；新镜像先执行 migrate、Django check 和 migration drift，再强制重建 `web / worker / beat` 并执行 collectstatic。无新增迁移，无生产历史数据写入。
- 验收：三应用容器 image ID 一致，web healthy，`0029` 和 64 models 正常；新命令 `import_historical_race_event_field_candidates` 可发现。历史写入/网络常驻开关 false，归属 mode off，历史 published 为 0。内外 healthz、五地区首页、赛事/马匹/后台均通过；`13:30` 自然窗口抓取 5/5、发布 5/5、QQ 5/5 succeeded，日志无异常。
- 回滚：停止 beat 并排空 worker，把 `pre-main-df2732c3-20260713-1327` retag 为 `prod`，只重建 `web / worker / beat`。本次无数据库迁移，通常不恢复数据库；仅在后续字段写入造成确认的数据损坏时使用备份。

## 2026-07-13 `main@304ebdb6` 可复现镜像切换

- 目标镜像：`umanewsbot:main-304ebdb6-amd64-20260713-1230`，image ID `sha256:e7ab7af0061d7362ad0582224baffc79eda07bd6d8f6467bfa573f760853877d`，revision `304ebdb67562e655929d263a3af98b8f17905752`，Git tree `5dfef5c7d219e63cd0b156071c89508cb42543ce`，context SHA-256 `a77a271cde3d0d06e25f9075036de5fc99415e832f2da052c84bf40bf956a7b5`。两次构建 image ID 一致。
- 切换前备份：`.env.backup.main-304ebdb6-20260713_123828`；数据库 `backups/db/pre-main-304ebdb6-20260713_123828.sql.gz`，`148091210` bytes，SHA-256 `f61038e6a9e015f0eb0d59288029903911ebd55ed1acf600eabfb15a4c6ee126`，`gzip -t` 通过。旧镜像回滚 tag 为 `pre-main-304ebdb6-20260713-1240`。
- 生产主仓库快进时，未跟踪的旧版 `runtime/tools/package_historical_race_detail_candidates.py` 与新主线跟踪路径冲突。该旧文件仅缺少新 provider，无主线之外能力；原文件和 SHA 已保存在 `runtime/deploy/pre-main-304ebdb6-20260713_1239/`，再由跟踪版本接管。不得把备份旧版覆盖回工作树。
- 切换步骤：停止 beat，等待 Celery active/reserved 清空，核对外部导入、归属和术语重处理 run/lock 均为 0；将旧 `prod` 保留为回滚 tag，再把新镜像 retag 为 `prod`；用新镜像执行 migrate、Django check 和 migration drift，全部通过后 `--force-recreate web worker beat`，最后 collectstatic。
- 验收结果：三容器 image ID 一致，`0027–0029`、64 models、六个新历史管理命令通过；法国/香港/英国各 `50 ready`，历史公开为 0；关键新开关与历史网络开关继续 false。内外 healthz、首页、五地区 query filter、赛事/马匹页和后台跳转通过，日志无异常，新容器后自然窗口无 failed。
- `12:45` 自然窗口收口证据：当轮 8 个 due source 抓取全部 succeeded，publish/QQ 各 5 个地区窗口全部 succeeded；netkeiba 新着顺 `seen=116 / new=4`，4 篇全部 translated 且为 publish_ready。
- 回滚：先停 beat 并排空 worker，将 `pre-main-304ebdb6-20260713-1240` retag 为 `prod`，重建 `web / worker / beat`。数据库本次无新迁移，只有出现数据损坏时才使用上述备份恢复。

## 2026-07-13 组合镜像恢复后窗口验收口径

- 验收不得只看 ProductionWindow `status=succeeded`；必须同时核对来源级 `seen/new`、文章翻译/门禁/发布状态、QQ delivery、超时任务和容器日志。
- `coalesced_to_latest_crawl_window` 表示过期 bucket 的抓取被合并到最新窗口，不是来源网络报错。当前来源以上次完成时间滚动到期，beat 每 5 分钟检查，因此该原因会常态出现，15 分钟配置的实际间隔可为 15–20 分钟。判断积压应看来源是否超过 20 分钟仍无后续 succeeded，不能只看是否出现 coalesced。
- 2026-07-13 首次恢复验收：`11:15=8 succeeded + 9 coalesced`，`11:30=9 succeeded + 8 coalesced`，`11:45=17 succeeded`，`12:00=10 succeeded + 6 coalesced`；后一批 6 个来源已在 `12:15` succeeded，各来源无抓取失败。三窗口日本抓取新增 9，其他四地区为成功抓取但全部重复；网页发布日本 `3 + 2 + 0`，其他地区无 ready 候选，QQ 成功交付 1 条且零产出有明确原因。
- 运行健康查询应排除历史脏数据：当前库内有 28 条无对应运行任务的历史 `CrawlJob(status=started)`，判断当前卡死应以最近窗口、Celery active/reserved 和容器进程交叉确认。清理前先生成记录清单并备份，不直接删除。
- 本次发现翻译失败 `8208 / 8211 / 8215`：`8208` 为到期 transient timeout，`8211 / 8215` 为 incomplete response 且当前分类为 unknown。生产自动重试安全开关仍为 false，所以这三篇不会自行恢复；未完成小批验收和 SMTP 测试前不得为了清空失败盲目全局开启。

## 待实施：法国新鲜度与多地区归属上线门禁

- 对应 change：`fix-france-news-freshness-and-multiregion-attribution`。代码已按安全关闭模式部署过，以下仍是生产 dry-run、Shadow、enforce 与相关地区查询的有效上线约束；不得把“代码存在”视为功能已经启用。
- 部署前必须确认本地 HEAD、服务器 HEAD、tracked/untracked 文件、Nginx 运行配置、数据库备份及 `web/worker/beat` 当前环境变量；部署后再次核对三个服务读取一致配置。
- 首次部署必须设置 `MULTIREGION_ATTRIBUTION_MODE=off`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`、`TRANSLATION_AUTO_RETRY_ENABLED=false`，不得因迁移成功自动开启行为。
- 开启 shadow 前必须完成至少 150 篇版本化 Gold Set、五个运营地区各至少 10 篇、跨地区至少 20 篇、生产快照 SHA 校验、全部质量阈值和独立的 250 篇 PostgreSQL 性能验收；任何单地区 no-go 都应阻止继续灰度。
- enforce commit 必须引用成功 dry-run 的 run ID 与 manifest，检查文章、人工锁定、规则、术语和 gold 版本漂移；部分失败使用同一 run/manifest resume，不新建无关批次。
- 回滚顺序：先关闭相关地区查询，再把归属 mode 降为 shadow 或 off，再关闭翻译自动重试；保留运行账本用于审计。只有数据库结构或数据损坏时才使用部署前备份恢复。
- 验收必须覆盖 `/healthz/`、首页、五地区页、文章详情、运营后台、worker/beat 日志、来源/翻译/门禁/窗口/网页/QQ 分层计数，以及单文章单次公开和单群单次交付。

## 2026-07-12 英文术语门禁受控发布与 TDN France 旧库存清理

- 发布前备份：`backups/db/pre-term-gate-publish-20260712_182052.sql.gz`，约 `110M`，SHA-256 `0edfbf7cae1a23ce71cb2d8de3b5d1d4b85c276daf1504f3971fac90c618144c`。
- 锁定 run/manifest 提交后恢复香港 `7`、英国 `3`、美国 `9`、法国 `5`，自然窗口共公开 `24` 篇；不得手工伪造未来窗口。
- 复核发现法国 5 篇来自修复前污染批次 `CrawlJob#9408`，官方日期均超过来源 3 天新鲜度。清理前追加备份 `backups/db/pre-term-gate-stale-cleanup-20260712_185347.sql.gz`，约 `100M`，SHA-256 `a16f85f74d2d1d9de44debbf54f1bf096cff2ad2ce0a17f448ba259e6738a118`。
- 清理范围不是只撤回 5 篇公开文章，而是将 `CrawlJob#9408` 全部 20 篇统一设为 `workflow_status=withdrawn`、`automation_status=manual_review_required`，清空 `published_to_web_at`，写入 `withdrawn_at`、`decision_reason.tdn_france_stale_cleanup` 和操作日志，避免待审核旧文再次进入补跑。
- 最终公开 19 篇，QQ 交付 `0`；`NewsSource#21` 保持 `enabled=true / production_approved=true`，因为修复后的新抓取已能读取真实日期并过滤旧文。
- 常驻 `web/worker/beat` 必须继续保持 `ENGLISH_TERM_CONTEXT_MODE=shadow`，本轮不切全局 `enforce`。

## 2026-07-12 英文术语命中级上下文门禁 shadow 部署

- 生产提交：`f221c7df`；迁移：`stable.0028_term_gate_reprocess_runs`。
- 部署前备份：`.env.backup.english-term-context-20260712_171023`；数据库 `backups/db/pre-english-term-context-20260712_171023.sql.gz`，`109M`，`gzip -t` 通过，SHA-256 `8f1cb6d3380db6c92671348d60a1c1d1633939bc637a38bcc2bdc796116486e1`。
- 生产模式：`ENGLISH_TERM_CONTEXT_MODE=shadow`，`web/worker/beat` 必须一致。快速关闭时改为 `off` 并重建三个服务；未完成 24 小时观察前禁止 `enforce`。
- 100 篇基准事实：run `#6`，美国近 168 小时，候选 `100`，耗时 `7.5323s`、SQL `19`、RSS 增量 `36,503,552` bytes；索引 `1`，赛事实体/英文 alias/额外马名术语/重复语料预取 `2/1/0/1`；可恢复 `20`、仍阻断 `80`。
- 小批 dry-run：香港 run `#7` 为 `12/16` 可恢复；英国 `#8` 为 `3/20`；法国 `#9` 为 `6/13`；美国 `#10` 为 `9/20`。NFKC span 修复后法国 run `#11` 仍为 `6/13`，`Exactly` 命中文本与原文 span 已准确。所有 run 均为 dry-run，生产 `committed=0`、租约为空。
- 验收：最终本地专项 `81`、完整 `stable` `870`；生产 Django check、迁移、内外 `/healthz/`、容器日志、首页、新闻详情和后台未登录跳转通过。

观察命令：

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web \
  python manage.py shell -c 'from django.conf import settings; print(settings.ENGLISH_TERM_CONTEXT_MODE)'
docker compose -f docker-compose.prod.lowcost.yml exec -T web \
  python manage.py shell -c 'from stable.models import TermGateReprocessRun,TermGateReprocessLock; print(list(TermGateReprocessRun.objects.values("id","mode","status","statistics").order_by("-id")[:12])); print(list(TermGateReprocessLock.objects.values()))'
```

回滚只切配置即可：把 `ENGLISH_TERM_CONTEXT_MODE=off`，重建 `web/worker/beat` 并确认三个容器均读取 `off`。运行账本表保留审计，不回滚迁移、不删除 run。若必须恢复部署前数据库，使用上述 `pre-english-term-context` 备份。任何 commit 必须在 enforce 抽检通过后引用同一 dry-run 的 `--run-id` 与 `--manifest-sha256`，且先核对术语/设置/文章指纹无漂移。

## 2026-07-12 P0 马资料补全基础能力部署

- 生产提交：`ce676998`；部署前 `HEAD=31cc82c`。
- 迁移：P0 原开发编号 `0023` 因最新主干已有迁移而顺延为 `stable.0027_p0_horse_profile_completion`。
- 部署前检查：`web/worker/beat/db/redis/nginx` 正常；本地与公网 `/healthz/`、公网 `/horses/` 正常；`ExternalDataImportRun(status=started)=0`、导入锁 `0`、Celery active/reserved 为空，未发现历史回填进程；磁盘剩余约 `19GB`。
- 备份：`.env.backup.p0-horse-profile-20260712_162039`；数据库 `backups/db/pre-p0-horse-profile-20260712_162039.sql.gz`，`109MB`，已通过 `gzip -t`。
- 生产显式配置：`HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`、`HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`、`HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`、`HORSE_PROFILE_COMPLETION_BATCH_LIMIT=10`、`HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL=true`、`HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1`。
- 部署后：`0027` 已应用，`manage.py check` 通过；内外 `/healthz/` 返回 `200`，`/horses/` 返回 `200`，身份冲突 Django Admin 未登录跳转正常；容器健康，`web/worker/beat` 日志无 traceback。
- 数据抽检：`HorseRaceRecord=21`、非空幂等键 `21`、空键 `0`；新 P0 来源、身份冲突、补全 run 均为 `0`。
- P0 dry-run：`term_candidates=21596`、`major_race_candidates=992`；其中重点赛事含 runner `5096`、result `4572`。本次未执行 `p0_horse_profiles --sync-sources --commit`，避免绕过“五地区各 10 匹先人工跑通”直接全量写入数千匹马。
- 本地上线验证：最新主干定向 `104` 项通过，完整 `stable` `813` 项全部通过；Django check、迁移一致性、旧规格流程 strict/all、`git diff --check` 通过。

回滚代码可使用部署前提交 `31cc82c`；若需要恢复迁移前数据库，使用上述 `pre-p0-horse-profile` 备份。`0027` 新表和字段在代码回滚后可暂时保留不用，只有确认需要彻底恢复时才执行数据库恢复。
## 2026-07-13 美国Equibase六场补源与第一批45场完成

- 范围：美国Ack Ack、Iroquois、Davona Dale三个系列的2000/2012六届。
- 正式来源：Equibase官方单场standard PDF；date/source artifact manifest SHA-256为 `42c9ced9b8e41509853560efbde10a659059ff12f8ea26d602827ff452d49b46`，source-cache manifest SHA-256为 `d0ede01337e393d05a069d7be2ba3f87df795699a06fc113dbe47c3b1d34c49e`，请求账本SHA-256为 `2a90a32dd059f1c098f10be8e05daf86cb9d8aa29972a08f27be16e874e671a5`。
- 详情候选：`runtime/historical_first_acceptance_1998_2026/equibase-official-release-20260713/detail-package/historical_detail_candidates.jsonl`，SHA-256 `94b62febe849b9a0562e5ab641d87671ae3468a202355b5336a7f4405e8abe75`；dry-run为6 scopes，正式apply写入 `58 runners / 58 results`。
- 日期apply前备份：`backups/db/pre-equibase-us-date-apply-20260713_083026.sql.gz`，`120405132` bytes，SHA-256 `65da811725111da6c556d077118571da0d9bf5bed628d15c27ea7021052ad2e5`。
- 详情apply前备份：`backups/db/pre-equibase-us-detail-apply-20260713_083319.sql.gz`，`120406520` bytes，SHA-256 `ad547a575ac03de17d8314821b3111b30ef5151231f2c4d33e5fe263c99d09c1`。
- 两份备份均通过 `gzip -t`。写后第一批selection snapshot为 `45/45 imported`，共 `468 runners / 429 results`，历史published为 `0`。
- 部署镜像：`umanewsbot:equibase-20260713`，镜像ID `sha256:1d079975672300bdd42c9f9cdbbac86d63446529904aafb7044e50b5817f5d11`；回滚镜像 `umanewsbot:pre-equibase-20260713`。
- 长期开关继续为 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。单次管理命令只通过容器环境临时开启写入能力，不修改 `.env`；45场全部保持draft。
- 写后数据库约 `796 MB`；Django check、web健康、内外 `/healthz/`、web/worker/beat近10分钟错误日志均通过。

## 2026-07-13 法国历史详情补充来源与六场导入

- 范围：法国2012/2025的 Arc de Triomphe、Criterium de Saint-Cloud、Prix d'Ispahan，共6个历史目标。
- 来源 artifact：`runtime/historical_first_acceptance_1998_2026/detail-source-artifacts/france-zeturf-20260713/`，manifest SHA-256 `9062fc049ed8c1f7ff712dd5af7280a46348ab096cd8dd9d59f6fd80d9060c6f`。
- 详情候选：`runtime/historical_first_acceptance_1998_2026/detail-package-france-zeturf/historical_detail_candidates.jsonl`，SHA-256 `38c2aea7f704d828e92073373b2ef225372037b00790576d115ed5502cf4e392`。
- 来源写入前备份：`backups/db/pre-france-detail-source-apply-20260713_063352.sql.gz`，115M，SHA-256 `04d6322db1b407b675cc6d40302ad1afcb8ef94aa741cccb7e436843d84f8b70`。
- 详情导入前备份：`backups/db/pre-france-detail-import-20260713_063554.sql.gz`，115M，SHA-256 `8f13612d674031eed4287dfa5f4b6e9686a63db8767560f7a057201c38478c6d`。
- 两份备份均通过 `gzip -t`。来源 check 为6/6，详情 dry-run 为6 scopes；正式导入新增 `70 runners / 41 results / 12 applied candidates`。
- 写后首批状态：`33 imported / 3 ready / 9 pending`；36个历史RaceEvent全部为draft。`.env` 中 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，不得因单次 `docker exec -e` 写入而修改长期配置。
- 写后 Django check、本机/公网 healthz、容器状态和15分钟错误日志均正常。

## 2026-07-10 英文术语门禁上下文判定上线

- 本地 change：`classify-english-term-gate-context`。
- 工作树：`/Users/mentianlu/.codex/worktrees/audit-overseas-candidate-pool/umanews`。
- 范围：英文来源文章的术语保留门禁、旧 `core_term_missing` 候选完整重校验命令。
- 行为边界：
  - 普通英文词种子默认按普通词降级为 warning，不生成 `core_term_missing` blocker。
  - 只有 `wins / returns / runs / targets / entered` 等强动作上下文才把普通词种子保守维持为 blocker。
  - `race / jockey / trainer`、真实赛事结构词和未进入普通词种子的 horse term 继续按真实专名或保守缺失处理。
  - `reprocess_term_gate_blocked_articles --commit` 只对完整门禁通过文章调用 `apply_validation_outcome()` 并写 `ranked_revived_at`，不会直接公开发布文章。
- 本地上线前验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true ... manage.py test stable.tests.AutomationFlowTests...`：11 项目标测试通过。
  - `DB_ENGINE=sqlite ... manage.py check`：通过。
  - `旧规格流程 validate classify-english-term-gate-context --strict`：通过。
  - `git diff --check`：通过。
- 生产上线后第一步必须只读 dry-run，人工确认前不得执行 `--commit`。若在 `2026-07-10` 执行，`--hours 240` 足以覆盖北京时间 `2026-07-01 00:00` 以来数据；若推迟执行，需要增大 `--hours` 覆盖完整窗口。

```bash
cd /opt/umanewsbot
TS=$(date +%Y%m%d_%H%M%S)
OUT_DIR="runtime/multiregion_candidate_audit/reprocess_full_dryrun_${TS}"
mkdir -p "${OUT_DIR}"

for REGION in hong_kong united_kingdom united_states france; do
  docker compose -f docker-compose.prod.lowcost.yml exec -T web \
    python manage.py reprocess_term_gate_blocked_articles \
      --region "${REGION}" \
      --hours 240 \
      --dry-run \
      --json \
    > "${OUT_DIR}/${REGION}.json"
done
```

- dry-run 审核口径：检查四个 JSON 的 `summary.revalidated_to_publish_ready_count`、`summary.common_word_downgraded_count`、`summary.proper_term_blocker_count`、`outcomes[].english_term_classifications` 和 `outcomes[].proper_term_blockers`；对照本批人工审计投影，重点确认普通词旧 blocker 被清除、真实赛事/马名专名没有被普通词规则误放行。

### 生产执行记录

- 部署前生产 HEAD：`65988b0`。该提交含服务器侧已上线但尚未回主线的移动端马匹导航修复；上线前已在本地把 `production/main` 合并回 `origin/main`，避免部署时覆盖线上修复。
- 部署提交：`43898ff`。
- `.env` 备份：`.env.backup.english-term-context-20260710_030705`。
- 数据库备份：`backups/db/pre-english-term-context-20260710_030705.sql.gz`，已通过 `gzip -t`。
- 部署方式：`git pull --ff-only origin main` 从 `65988b0` 快进到 `43898ff`，随后执行 `bash ./deploy_lowcost.sh`。
- 迁移：无新增迁移，`migrate` 输出 `No migrations to apply`。
- 部署后状态：`web / worker / beat / db / redis / nginx` 正常，`web`、`db`、`redis` healthy，生产 `manage.py check` 通过，本地和公网 `/healthz/` 返回 `{"status": "ok"}`，首页返回 `200`，后台登录入口返回 `200`。
- 完整只读 dry-run 产物：`runtime/multiregion_candidate_audit/reprocess_full_dryrun_20260710_030944/`。
  - 香港：候选 `17`，可恢复候选 `3`，仍阻断 `14`，普通词降级 `9` 次，真实专名 blocker `33` 次。
  - 英国：候选 `37`，可恢复候选 `5`，仍阻断 `32`，普通词降级 `119` 次，真实专名 blocker `140` 次。
  - 美国：候选 `79`，可恢复候选 `22`，仍阻断 `57`，普通词降级 `1` 次，真实专名 blocker `366` 次。
  - 法国：候选 `13`，可恢复候选 `7`，仍阻断 `6`，普通词降级 `13` 次，真实专名 blocker `10` 次。
  - 合计：候选 `146`，可恢复候选 `37`，仍阻断 `109`，普通词降级 `142` 次，真实专名 blocker `549` 次。
- 本次仅执行 `--dry-run`，未执行 `--commit`，未恢复候选，未公开发布文章。后续 commit 前必须先人工抽检 dry-run JSON 中的 `english_term_classifications` 和 `proper_term_blockers`。

## 2026-07-08 马匹详情页 MVP 生产部署

- 本地 change：`horse-profile-page-mvp`。
- 部署提交：`2b28755 Add horse profile page MVP`。
- 工作树：`/Users/mentianlu/.codex/worktrees/race-detail-page/umanews`。
- 新增迁移：`stable.0022_horseprofile_horsefollow_articlehorselink_and_more`。
- 新增公开入口：`/horses/`、`/horses/<id>/`、`/horses/follows/`。
- 新增后台入口：`/admin/horse-profiles/`。
- 新增管理命令：
  - `generate_horse_profiles`：从 active horse `TermEntry` 生成草稿 `HorseProfile`。
  - `complete_horse_profiles`：生成全地区 P0 马资料补全 dry-run artifact，或应用已审核 artifact。
  - `scan_article_horse_links`：历史已发布文章马匹关联 dry-run / commit 回填。

### 生产执行记录

- 生产服务器：`/opt/umanewsbot`。
- 部署前 HEAD：`01c0b9b`。
- 部署后 HEAD：`2b28755`。
- 部署前检查：`docker compose -f docker-compose.prod.lowcost.yml ps` 正常，`manage.py check` 通过，本地 `/healthz/` 与公网 `/healthz/` 返回 `200`，`ExternalDataImportRun(status="started")=0` 且 `ExternalDataImportLock.locked_by_run_id` 为空。
- `.env` 备份：`.env.backup.horse-profile-page-mvp-20260708_040446`。
- 数据库备份：`backups/db/pre-horse-profile-page-mvp-20260708_040503.sql.gz`，约 `85M`，已执行 `gzip -t`。
- 生产 `.env` 已显式补入保守默认：
  - `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`
  - `HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`
  - `HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`
  - `HORSE_PROFILE_COMPLETION_BATCH_LIMIT=10`
  - `HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL=true`
  - `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1`
- 部署方式：`git pull --ff-only origin main` 从 `01c0b9b` 快进到 `2b28755`，随后执行 `bash ./deploy_lowcost.sh`。
- 迁移：`stable.0022_horseprofile_horsefollow_articlehorselink_and_more` 已应用。
- 部署后状态：`web / worker / beat / db / redis / nginx` 正常，`web` 与 `db / redis` healthy，`manage.py check` 通过。
- P0 草稿生成：`generate_horse_profiles` 创建 `21596` 个 `HorseProfile`，全部为 `draft`，`published=0`。
- 上线 smoke：
  - 本地 `/healthz/`、`/horses/`、`/horses/follows/`、`/admin/login/`、`/news/5738/` 均返回 `200`。
  - 草稿样例 `/horses/1/` 返回 `404`。
  - 未登录 `/admin/horse-profiles/` 返回 `302`。
  - Host `umafans.run` 的 `/horses/` 返回 `200`，公网 `http://umafans.run/healthz/` 与 `http://umafans.run/horses/` 返回 `200`。
- 历史新闻马匹关联 dry-run：`scan_article_horse_links --dry-run --limit 500` 返回 `created=0 updated=0 candidate=0 skipped_removed=0 skipped_manual=0`，原因是当前所有马匹仍为草稿，前台关联面无公开马匹可展示。
- 全地区补全 dry-run：artifact 已复制到宿主机 `runtime/horse_profile_completion/dry-run-20260708_041343/`，包含 `horse_profile_completion_plan.json`、`horse_profile_completion_review.csv` 和 `summary.json`。
  - 覆盖 P0 马 `21596` 匹。
  - `complete_pedigree_2gen=0`，`not_complete=21596`，`complete_ratio=0.0`，`not_complete_ratio=1.0`。
  - 失败原因：`no_external_match=15293`、`source_unavailable=6301`、`profile_only=2`。
  - 按地区 `france / hong_kong / japan / other / united_kingdom / united_states` 的 `not_complete_ratio` 均为 `1.0`。
  - 本次未执行 `--commit`；后续必须先人工审核 `horse_profile_completion_review.csv`，再使用 `--artifact --confirm-reviewed-artifact` 应用。

### 线上浏览器验收记录

- 时间：`2026-07-08`。
- 方式：先尝试 Codex 内置浏览器访问生产页，两次打开 `http://umafans.run/horses/` 超时；随后使用系统 Chrome headless 生成桌面 / 移动截图和 CDP 布局指标。
- 本地验收产物：`/tmp/umanews-horse-acceptance/`。
  - `horses-desktop.png`
  - `horses-mobile.png`
  - `home-desktop.png`
  - `home-mobile.png`
  - `follows-desktop.png`
  - `follows-mobile.png`
  - `horses.html`
  - `horses-search-region.html`
  - `home.html`
  - `news-5738.html`
- 公网 HTTP 复核：
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/horses/` 返回 `200`。
  - `http://umafans.run/horses/follows/` 返回 `200`。
  - `http://umafans.run/horses/1/` 返回 `404`，符合草稿不公开策略。
  - `http://umafans.run/admin/horse-profiles/` 返回 `302` 到 `/admin/login/?next=/admin/horse-profiles/`。
- Chrome 布局复核：
  - 桌面 `/horses/` 标题为“马匹资料”，包含搜索框、地区筛选和空状态；页面 `clientWidth=1440`、`scrollWidth=1440`，无页面级横向溢出。
  - 移动 `/horses/` 标题为“马匹资料”，导航 DOM 包含“首页 / 赛事日历 / 马匹 / 我的关注”，搜索框存在；页面 `clientWidth=390`、`scrollWidth=390`，无页面级横向溢出。
  - 移动首页导航 DOM 包含“马匹”和“我的关注”，页面 `clientWidth=390`、`scrollWidth=390`。
  - 移动 `/horses/1/` 显示 404 页，页面 `clientWidth=390`、`scrollWidth=390`。
  - `/horses/?q=test&region=japan` 保留搜索词 `test`，并正确激活“日本”地区筛选。
- 当前体验问题：
  - `/horses/` 空状态文案为“目前还没有已发布文章。”，语义应改为马匹资料。
  - 移动端顶部导航和地区筛选依赖横向滑动，功能可用但“马匹 / 我的关注”和最右侧“美国”入口不够显眼。
- 未覆盖项：
  - 生产当前没有已发布马匹，未在生产发布测试数据；因此未完整验收已发布马匹详情、关注按钮 POST、新闻详情马匹 tag 和关注新闻流。
  - 未持有 staff 登录态，后台审核列表 / 详情只验收到未登录跳转。
  - UmaNews 生产 SSH 只以 `root@47.239.167.86` 为准；其他项目服务器不属于本项目验收范围。

### 样本发布与最终前台验收记录

- 时间：`2026-07-10`。
- 服务器：`root@47.239.167.86:/opt/umanewsbot`，最终 `HEAD=65988b0`。
- 代码部署：
  - `34143ce`：修复 `/horses/` 空状态文案，并调整移动导航 / 地区筛选初版布局。
  - `d21d6ab`：继续收敛移动端导航和地区筛选裁切问题。
  - `65988b0`：移动一级导航改为两列 grid，确保“首页 / 赛事日历 / 马匹 / 我的关注”全部在屏内。
- 备份：
  - `.env.backup.horse-public-polish-20260710_010639`
  - `backups/db/pre-horse-public-polish-20260710_010639.sql.gz`
  - `backups/db/pre-horse-sample-profiles-20260710_011038.sql.gz`
  - `.env.backup.horse-mobile-polish-20260710_011811`
  - `backups/db/pre-horse-mobile-polish-20260710_011811.sql.gz`
  - 上述数据库备份均已执行 `gzip -t`。
- 样本数据：
  - `春秋分`：`/horses/13113/`，netkeiba 来源 `https://db.netkeiba.com/horse/2019105219/`，参赛履历 `10` 条，相关新闻人工关联 `5` 篇。
  - `北十字星`：`/horses/3873/`，netkeiba 来源 `https://db.netkeiba.com/horse/2022105102/`，参赛履历 `11` 条，相关新闻人工关联 `5` 篇。
  - 两匹马均为 `review_status=published`、`completeness_status=complete_pedigree_2gen`。
- 前台验收：
  - `http://umafans.run/horses/13113/` 显示春秋分基础资料、完整二代血统、主胜鞍、参赛履历和相关新闻。
  - `http://umafans.run/horses/3873/` 显示北十字星基础资料、完整二代血统、主胜鞍、参赛履历和相关新闻。
  - `http://umafans.run/news/7248/` 显示马匹 tag `春秋分`，点击进入 `/horses/13113/`。
  - 匿名关注 / 取消关注链路通过；关注后 `/horses/follows/` 显示春秋分及其关联新闻，验收后已取消关注，样本 `HorseFollow` 计数为 `0`。
  - `/horses/?q=croix&region=japan` 可命中北十字星，`/horses/?q=EQUINOX&region=japan` 可命中春秋分，英文大小写搜索正常。
  - Codex 浏览器移动 viewport `390x844` 复核 `scrollWidth=390`，四个一级导航入口和六个地区按钮坐标均在屏内。
- 生产健康：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check` 通过。
  - 本地容器和公网 `http://umafans.run/healthz/` 均返回 `200` / `{"status": "ok"}`。

### 生产部署前检查

1. 记录生产 `HEAD`：`git rev-parse --short HEAD`。
2. 检查容器：`docker compose -f docker-compose.prod.lowcost.yml ps`。
3. 执行 Django check：`docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`。
4. 检查本地和公网健康：`curl -fsS http://127.0.0.1/healthz/`、`curl -fsS http://umafans.run/healthz/`。
5. 确认外部导入没有运行：`ExternalDataImportRun(status="started")=0`，`ExternalDataImportLock.locked_by_run_id` 为空。
6. 备份数据库并执行 `gzip -t`。
7. 备份 `.env`，确认新增配置默认保守：
   - `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`
   - `HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`
   - `HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`
   - `HORSE_PROFILE_COMPLETION_BATCH_LIMIT=10`
   - `HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL=true`
   - `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1`

### 部署与迁移

P0 马资料补全专项上线前额外确认：

- `stable.0027_p0_horse_profile_completion` 会为自然键唯一的既有 `HorseRaceRecord` 回填幂等键；已有重复组保持空键，需先在 dry-run 报告中人工处理。
- 已审核 artifact 必须同时具备顶层 `reviewed`、行级 `reviewed=true`、有效 `reviewer_id`，以及 `profile/pedigree/race_record/major_wins` 四模块 `approved`；缺少来源 URL、低置信、未审核或冲突模块不得写主表。
- `p0_horse_profiles --sync-sources --commit` 只新增、刷新或恢复来源，不撤销历史来源；可配合 `--region` 做单地区同步。
- `p0_horse_profiles --sync-sources --commit --full-reconcile` 才是全地区完整来源对账，会把本轮不再成立的受管来源标记为 `revoked`；只应在重点赛事/出赛表/赛果导入完成且本地结构化数据为完整快照时执行，不能与 `--region` 同时使用。
- 队列排查可用 `--queue --profile-id <id>` 精确选择一匹或重复指定多匹；`--limit-per-region` 必须大于 0。
- 马匹自身 `racing_region` 不因海外参赛而修改；抽检跨地区样本时同时核对 `HorseProfile.racing_region` 和 `HorseP0Source.racing_region`。
- 抽检同场同名马时必须核对 `HorseP0Source.participant_key`：不同马号应为不同 `number:<horse_number>`，每个参赛键最多一条 active 来源；身份纠正应留下 revoked 旧行和 active 新行。
- 参赛记录后补马号时，普通增量同步后应确认旧 identity 键已迁移为 number 键且仍只有一条 active 来源；runner/result 两边马号冲突时应只产生 pending `HorseIdentityConflict`，不得生成 active P0 来源。
- 抽检同来源 identity 的同类型重复输入：两条 runner 或两条 result 使用不同马号时，应汇总为一条 pending 身份冲突，证据包含全部记录 ID 和马号，active P0 来源计数为 0。
- 解决马号冲突时必须同时填写 `resolved_profile` 和 evidence 候选内的 `resolved_horse_number`；下一次同步只允许选中马号产生 active 来源。抽检冲突成员 URL 完整保留，完全无 URL 的冲突仍在 pending 列表中。
- 跨来源自动归并数据库已有马时，必须完整且唯一命中经术语库归一的马名、父名、母名和出生年份；来源 ID 只能在自身命名空间内作为直接证据。
- 身份不确定时应生成 `HorseIdentityConflict(status=pending)`，即使尚无 `HorseProfile` 也必须关联候选术语和原始证据，不得写入马匹主表；全量对账不得撤销仍在输入中的待处理来源或仅临时缺少 URL 的来源。
- Celery Beat 每天 `09:20` 运行 `stable.tasks.notify_p0_horse_identity_conflicts_task`，复用 `MULTIREGION_OPS_NOTIFICATIONS_*` 通知配置。部署后应抽查任务日志、pending 冲突数和 `${DJANGO_ADMIN_URL}stable/horseidentityconflict/?status__exact=pending`。
- Django Admin 处理身份冲突时应填写 `resolved_profile` 与 `resolution_notes`，并将状态改为 `resolved` 或 `ignored`；系统自动记录 `resolved_by/resolved_at`。
- 人工执行完整资料 ready 前必须设置明确的 `HorseProfile.source_refs.p0_completion` 整匹马资料 URL；不能仅以单场赛果 URL 作为基础资料和血统来源。
- P0 artifact 和后台人工候选写入赛绩后，抽检 `HorseRaceRecord.idempotency_key` 非空；同一赛绩重复审核不得增加记录数，缺少 `source_name` 或 `source_url` 的候选必须保持 pending/冲突且不落主表。
- 后台手工新增/编辑赛绩也应抽检幂等键：重复提交不增加记录数，修改比赛名/日期/来源后键随之更新，若命中另一既有记录则页面提示冲突并保留原记录。
- 编辑 importer 生成的赛绩后，必须确认原 `source_refs/raw_payload` 未变化，操作日志包含字段 before/after；后台“在役待刷新”筛选应与 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS` 一致。
- 对含 external result/race ID 的赛绩执行人工改名后重跑相同 importer，确认幂等键仍为 external-ID 语义且记录数不增加。

```bash
git pull --ff-only origin main
bash ./deploy_lowcost.sh
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py showmigrations stable | grep 0027
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
```

期望：`stable.0027_p0_horse_profile_completion` 已应用，`manage.py check` 通过。

### P0 草稿生成

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py generate_horse_profiles
```

验收：

- 新增 `HorseProfile` 均为 `review_status=draft`。
- 公开 `/horses/` 不展示草稿。
- 任意草稿 `/horses/<id>/` 返回 404。

### 全地区资料补全 dry-run

先只生成 artifact，不写主表：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py complete_horse_profiles \
  --dry-run \
  --output-dir runtime/horse_profile_completion/dry-run-YYYYMMDD_HHMMSS
```

不传 `--limit` 时必须覆盖所有地区全部 P0 马；`--limit` 仅用于显式采样或拆批演练，不能用于最终全量验收。

必须复核输出：

- `horse_profile_completion_plan.json`
- `horse_profile_completion_review.csv`
- `summary.json`
- 全局和按地区完整二代成功率。
- 未补全占比和逐马失败原因。
- source URL、候选 diff、歧义和不可用来源原因。

人工审核 artifact 后，才允许 commit：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py complete_horse_profiles \
  --commit \
  --artifact runtime/horse_profile_completion/dry-run-YYYYMMDD_HHMMSS/horse_profile_completion_plan.json \
  --confirm-reviewed-artifact
```

### 历史新闻马匹关联回填

先 dry-run：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py scan_article_horse_links \
  --dry-run \
  --limit 500
```

确认候选和人工移除保护后再 commit：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py scan_article_horse_links \
  --commit \
  --limit 500
```

可按范围拆批：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py scan_article_horse_links \
  --commit \
  --article-from-id <START_ID> \
  --article-to-id <END_ID> \
  --limit 500
```

### 上线 smoke

- `/healthz/`：本地和公网均 `200`。
- 首页 `/`：返回 `200`，有关注 cookie 时展示“我的关注”模块。
- `/horses/`：返回 `200`，只展示已发布马匹。
- 样例 `/horses/<published_id>/`：返回 `200`，展示基础资料、二代血统、主胜鞍、相关新闻、相关赛事和关注按钮。
- 样例 `/horses/<draft_id>/`：返回 `404`。
- `/admin/horse-profiles/`：未登录跳转登录；staff 登录后可访问列表和详情。
- 新闻详情 `/news/<article_id>/`：只展示已发布且 `auto/manual` 状态的马匹 tag；候选、移除和未公开马匹不展示。
- 关注 POST 后 cookie 应为 `HttpOnly`、`SameSite=Lax`，数据库只出现 `token_hash`。

### 回滚

- 代码异常：回滚到部署前 git ref 后执行 `bash ./deploy_lowcost.sh`。
- 迁移异常：优先使用数据库备份恢复；如必须迁回，先确认没有新写入 `HorseProfile` / `HorseFollow` / `ArticleHorseLink` 数据。
- 补全误写：优先按 artifact 的 diff 和 `HorseProfileDataCandidate` 审计恢复字段；大范围异常使用部署前数据库备份。
- 公开入口异常：先将受影响 `HorseProfile.review_status` 批量改回 `hidden` 或 `draft`，再修代码。
## 2026-07-10 RaceEvent 赛事信息编排工具运行边界

本工具对应 旧规格流程 change `orchestrate-race-event-data-crawls`，第一版只服务 `RaceEvent*` 产品层赛事详情回填，不写 `ExternalRace*` / `ExternalHorse*`，不创建新闻文章，不触发翻译、自动发布或 QQ 推送。长期历史抓取必须手动分批或一次性容器执行，不加入 Celery Beat。

本地/生产通用阶段：

1. 校验并创建运行目录：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage plan`
   - 该阶段会在任何网络请求前生成不可随抓取结果缩减的 `<run_dir>/expected_targets.json`，并生成 `<run_dir>/review/expected_targets_review.csv`。快照绑定 plan SHA-256；清单为空、目标重复、正式 `RaceEvent` 缺失或恢复时 plan 已变化都会停止后续真实抓取。
   - 第一批真实抓取前必须人工查看 review CSV，逐行确认赛事中英文名、年份、地区、slug 和 `preflight_status=ready`。发现缺漏或错配时修改 plan / `RaceEvent` 后创建新 run，不得用实际抓到的候选反推或缩减应到范围。
2. 准备候选来源与 adapter 产物：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage prepare`
   - plan 未设置 `allow_network=true` 时，声明需要网络的 adapter 会被阻止。
   - `batch_size` 会限制单地区目标赛事年份数量；`rate_limit.max_requests` 与 `request_interval_seconds` 会由该 run 的全部网络 adapter 共同执行。累计状态保存在 `<run_dir>/request_budget.json`，失败请求也计数；artifact 损坏时停止请求，不重置额度。
   - 全部 adapter 成功后会生成 `<run_dir>/candidates/combined_candidates.jsonl`，同时保留每个 adapter 的原始、review 和归一化产物。
3. 覆盖审计：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage audit --series-mapping <series_mapping.json> --run-dir <run_dir>`
   - 未显式传 `--candidate-jsonl` 时默认审计 run state 中的 combined candidate；只有调试单独文件时才覆盖该参数。
   - blocker 包括 `missing_event_candidate`、`unexpected_candidate`、`missing_race_event`、缺模块、未审核 mapping、重复候选、source URL 一对多、manual lock、候选更不完整等。即使实际候选为零，也必须按独立应到清单逐项报缺，不能空跑通过。
4. Django dry-run：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage dry-run --run-dir <run_dir>`
   - 未显式传 `--candidate-jsonl` 时同样默认使用 combined candidate。
   - dry-run 仍会按 `year + slug` 查询 `RaceEvent`，因此深历史目标行缺失时必须先处理 seed review artifact。
   - 成功后固定生成结构化 `<run_dir>/dry_run.json`，其中 `status=passed`，并记录候选 JSONL 的绝对路径、大小和 SHA-256；`dry_run.txt` 只保留 importer 原始输出，不可单独作为 apply 证据。
5. apply-check：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage apply-check --coverage-audit <coverage_audit.json> --dry-run-artifact <run_dir>/dry_run.json --confirmations <confirmations.json> --production-evidence <production_evidence.json> --apply-scope <apply_scope.json> --candidate-jsonl <candidates.jsonl> --run-dir <run_dir>`
   - 只生成显式 apply 命令，不自动执行正式写入。
   - `coverage_audit.json`、`dry_run.json` 和待 apply JSONL 的 SHA-256 必须完全一致；候选在审计后有任何修改，都必须重新执行 audit 和 dry-run。旧审计产物缺少候选身份时会被阻止，不能通过显式传入另一份 `--candidate-jsonl` 绕过。
   - coverage 发现同一赛事不同模块使用不同来源或 source authority 时，会输出 `mixed_source_strategies[].strategy_sha256`；对应人工确认必须在 `mixed_source_strategy_sha256s` 中逐项列出这些哈希。
   - coverage 会输出 `actual_apply_scopes`。单一组合可继续使用顶层 `region/source/modules`；多组合必须在 `apply_scope.json` 中使用 `{"scopes": [...]}`，且每个实际组合都要有对应 confirmation。范围不完全一致时返回 `apply_scope_mismatch`，不会生成命令。
   - 全绿后生成 `<run_dir>/approved/candidates-<sha256>.jsonl`。显式命令只引用该绝对路径，并带 `--expected-sha256 <sha256>`；不得去掉哈希参数或改回普通 combined candidate 路径。
6. 中断恢复：
   - `python server/manage.py orchestrate_race_event_crawl --stage resume --state <run_dir>/state.json`
   - state 会记录每个 adapter 的输入指纹、必需输出路径/大小/SHA-256、成功/失败结果和恢复历史；只有输入未变化且全部必需输出仍存在、哈希一致时才会跳过。输出缺失、变化或旧 state 没有输出哈希时会重新执行 adapter。
   - audit 被 blocker 阻止后，可修正候选 JSONL 或 series mapping，再执行同一 resume 命令重跑 coverage audit；dry-run 和 apply-check 的成功/失败也会写入同一 state，resume 会使用保存的阶段输入依次重跑必要门禁。

生产 apply 前必须具备：

- coverage audit 无 blocker。
- `import_race_event_detail_candidates --dry-run` 证据通过。
- 首批“地区 + 来源 + 模块组合”人工确认记录。
- 候选记录均有合法 `source_authority`；adapter 候选中的 `adapter_key`、`source_provider`、地区、模块和权威等级与 manifest 一致；混合来源策略已按 coverage 输出的策略哈希人工确认。
- `actual_apply_scopes` 中每个“地区 + 来源 + 模块组合”均被 apply scope 和 confirmation 覆盖。
- approved candidate 文件存在，最终 importer 命令携带匹配的 `--expected-sha256`；执行时哈希不一致必须零写入失败。
- `ExternalDataImportRun(status="started")=0` 且 `ExternalDataImportLock.locked_by_run_id` 非空并指向 started run 的计数为 `0`；持久化但 `locked_by_run_id=None` 的空闲锁行不算活跃锁。
- `/healthz/` 本地与 Host 健康。
- 数据库备份路径和 `gzip -t` 结果。
- 数据库备份路径必须指向实际可读取的备份文件；仅填写字符串或伪造 `gzip` 状态无法通过 apply-check。
- 已有正式数据 diff/review 必须显式记录 `status=approved`，特别是会按模块整体替换的 `runners/results/history_winners`。

第一验收 fixture 位于 `server/stable/fixtures/race_event_crawl/first_acceptance_plan.json`，必须覆盖日本、香港、英国、法国、美国五地区少数核心赛事系列，并同时包含 `runners`、`results`、`history_winners` 三模块。来源权威等级矩阵位于 `server/stable/fixtures/race_event_crawl/source_authority_matrix.json`。

用户在第一批真实抓取前只需协助一次应到清单审核：Codex 提供实际 CSV 路径后，确认每行赛事中英文名、年份、地区和 slug 正确，并指出缺少或多出的赛事。请求上限、间隔、adapter 选择、候选哈希、coverage 和 apply 证据等技术项由工程侧负责；若用户未确认清单，第一批真实网络抓取不应开始。

## 2026-07-10 英法赛事详情生产复核与 Grand Prix de Saint-Cloud 历史冠军修复

- 生产服务器：`/opt/umanewsbot`。
- 生产预检：
  - `HEAD=65988b0`。
  - `web / db / redis` healthy，`worker / beat / nginx` 运行。
  - `python manage.py check` 通过。
  - `http://127.0.0.1/healthz/` 与 Host `umafans.run` `/healthz/` 均返回 `{"status": "ok"}`。
  - `ExternalDataImportRun(status="started")=0`，HKJC / netkeiba 导入锁为空。
- 复核结论：
  - 生产英法赛事详情已经正式导入，不需要重复 apply 整批规范 JSONL。
  - 英国：`sporting_life` runners/results applied `116 + 116`，`sporting_life_gap` runners/results applied `6 + 6`；`Jane Seymour Nov. Hurdle` 在线状态为 `cancelled`。
  - 法国：`zeturf` runners/results 已 applied；`GRAND PRIX DE SAINT-CLOUD` 当前正式出走表 / 赛果均来自正确 `R1C5` 页面，冠军为 `CALANDAGAN`。
  - 发现遗留污染：该赛事 `RaceEventHistoryWinner` 中 `2026` 年冠军仍来自早先误配 `R1C4` 的 `ZELMAN`。
- 修复流程：
  - 生成单场 JSONL：`grand_prix_saint_cloud_history_repair_20260710.jsonl`，只包含 `fr-france-galop-2026-0705-044` 的 `history_winners` 7 条。
  - 生产 dry-run：`events=1 modules=1 items={"history_winners": 7}`。
  - 写入前备份：`backups/db/pre-race-detail-gpsc-history-repair-20260710_025949.sql.gz`，约 `96M`，`gzip -t` 通过。
  - 正式 apply：`events=1 candidates=1 applied=1 items={"history_winners": 7}`，新增 applied candidate `2914`。
- 验收：
  - `RaceEventRunner=5096`、`RaceEventResult=4572`、`RaceEventHistoryWinner=5731`、`RaceEventDataCandidate=2914`。
  - `RaceEventDataCandidate(status="pending")=0`、`failed=2`。
  - `GRAND PRIX DE SAINT-CLOUD` 历史冠军 `2026` 已为 `CALANDAGAN`，source 指向 ZEturf `R1C5`。
  - 公网 `/races/2026/fr-france-galop-2026-0705-044/` 返回页面包含 `CALANDAGAN`，未再显示 `ZELMAN`。
  - 本地和 Host `/healthz/` 均返回 `{"status": "ok"}`。

## 2026-07-07 法国新闻源扩展与英文术语门禁地区过滤上线

- 本地 changes：`expand-france-news-sources`、`fix-english-term-gate-region-filter`。
- 部署提交：`bfc3445 Prepare France source expansion and English term gate fix`。
- 生产服务器：`/opt/umanewsbot`。
- 部署前状态：生产 `HEAD=538011e`，外部导入运行数 `0`、导入锁 `0`。
- 部署前备份：
  - 数据库：`backups/db/pre-france-source-term-gate-20260707_200124.sql.gz`，已执行 `gzip -t`。
  - `.env`：补法国来源发布白名单前分别备份为 `.env.backup.france-tdn-access-<timestamp>` 与 `.env.backup.france-tdn-canonical-access-<timestamp>`。
- 部署方式：
  - 生产机访问 GitHub HTTPS 超时，未能直接 `git fetch origin main`。
  - 本地生成 `/tmp/umanews-bfc3445.bundle` 并 `scp` 到生产机。
  - 生产机执行 `git fetch /tmp/umanews-bfc3445.bundle HEAD:refs/remotes/origin/main`、`git merge --ff-only refs/remotes/origin/main`，从 `538011e` 快进到 `bfc3445`。
  - 执行 `bash ./deploy_lowcost.sh`，镜像重建成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建。
- 基础验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`、Host `umafans.run` `/healthz/` 和公网 `http://umafans.run/healthz/`：均返回 `{"status": "ok"}`。
- 法国新来源验证：
  - 已执行 `sync_builtin_sources()`，生产内置来源数 `21`。
  - `tdn_france_broad` 只读探测 accepted：HTTP `200`、列表 `20`、详情样本 `5`、详情错误 `0`、重复 `0`。
  - 已启用 `NewsSource#21 TDN 法国宽关键词英文新闻`：`enabled=true`、`production_approved=true`、`effective_crawl_interval_minutes=15`。
  - 生产 `.env` 中 `MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES` 已加入 `tdn_france:access` 与 canonical 入库后的 `tdn:access`；`NEWS_SOURCE_POLL_ALLOWED_SOURCES=` 为空，表示抓取不额外限源。
  - 手动真实抓取验证入库 `4` 篇法国新来源文章，article IDs 为 `7250-7253`。为补生产配置而重启时中断了该人工抓取，`CrawlJob#9330` 已标记为 `failed`，`success_count=4`，错误说明为部署配置重启中断；这不是来源访问失败。
  - 文章 `7250-7253` 已完成补翻译和自动化重评，当前均为 `manual_review_required / pending_review`；`7250-7252` 因真实 `core_term_missing` blocker 转人工，`7253` 因总分 `69` 转人工。
- 英文门禁验证：
  - `reprocess_term_gate_blocked_articles --dry-run --json`：
    - `hong_kong`：最近 3 小时无可释放候选。
    - `united_states`：最近 3 小时无可释放候选。
    - `france`：最近 3 小时无可释放候选。
    - `united_kingdom`：有 `1` 篇候选，但重校验后仍被真实核心术语缺失阻断。
  - 本次未执行 `--commit`，因为没有因地区过滤修复可释放的近期误挡文章。
- 最终审计：
  - 容器内审计文件：`runtime/multiregion_audit/post-france-source-term-gate-final-20260707_202851.json`。
  - 法国来源：总数 `4`、启用 `3`、生产批准 `3`、paused/backoff 均为 `0`。
  - 法国文章：今日新入库 `4`、最近 24 小时 `4`、公开 `0`；workflow 为 `pending_review=29`，automation 为 `manual_review_required=29`，当前公开 0 的原因是正常门禁转人工，不是抓取或白名单失败。

### 21:00 线上回归复核

- 生产仓库：`HEAD=dcb9b90`。
- 容器：`web / worker / beat / db / redis / nginx` 均运行，`web` 与 `db / redis` healthy。
- 健康检查：`manage.py check` 通过；`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页和 `/admin/login/` 均返回 `200`。
- 配置：`MULTIREGION_PRODUCTION_WINDOWS_ENABLED`、抓取 / 发布 / QQ 子开关和 `NEWS_SOURCE_POLL_ENABLED` 均为 `true`；`MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES` 已包含 `tdn_france:access` 与 `tdn:access`。
- `tdn_france_broad` 只读探测：accepted，HTTP `200`、列表 `20`、详情样本 `2`、详情错误 `0`；重复率 `0.5`，原因是自然窗口已入库同批文章。
- 自然抓取窗口：`CrawlJob#9355` 已由生产窗口派发并仍在运行中，已通过 `source_config=21` 入库 `10` 篇法国文章，其中 `9` 篇已翻译、`1` 篇翻译中。Celery active 显示该 task 正在 worker 内运行，worker 日志持续出现 SiliconFlow `200 OK`，判断为单轮处理耗时偏长但仍在推进。
- 最近 90 分钟窗口：五地区发布和 QQ 窗口均为 `succeeded`；0 发布 / 0 推送原因均有记录，主要为 `no_ready_candidates`、`no_eligible_articles` 或 `already_sent`。
- 英文门禁重处理 dry-run：香港、美国无可释放候选；英国 `7242` 仍为真实 blocker；法国 `7250/7251/7252` 仍为真实 blocker。本次回归未执行 `--commit`。

### TDN broad 历史旧文事故与临时止血

- 发现问题：`tdn_france_broad` 抓入 2020、2022、2023、2024 年历史旧文，并因 `published_at` 被错误写为当前时间进入自动发布流程。
- 根因：TDN WordPress `search` API 返回相关性搜索结果，search item 不带 `date/date_gmt`；当前 adapter 在缺失日期时兜底为 `timezone.now()`，详情页解析也没有拿到真实发布时间。
- 已执行止血：生产 `NewsSource#21` 已设置 `enabled=false`、`production_approved=false`，并写入 `manual_pause_reason`，保留其他法国来源继续运行。
- 已确认受影响的已公开旧文：
  - `7255`：真实日期 `2022-03-21`。
  - `7263`：真实日期 `2020-04-07`。
  - `7264`：真实日期 `2020-03-16`。
  - `7265`：真实日期 `2020-03-13`。
  - `7271`：真实日期 `2024-11-08`。
- 修复方向：`tdn_france_broad` 必须用 search item 的 `id` 或 `_links.self` 二次读取 post API 获取真实 `date_gmt`，并丢弃超过生产新鲜度窗口的文章；修复和回归前不得重新启用 `NewsSource#21`。

### TDN broad 历史旧文修复上线

- 本地 change：`fix-tdn-france-search-date-freshness`。
- 部署提交：`ad587ce Fix TDN France search result freshness`。
- 生产服务器：`/opt/umanewsbot`。
- 部署前状态：
  - 生产 `HEAD=96fde81`。
  - `web / worker / beat / db / redis / nginx` 运行正常，`web` healthy。
  - `manage.py check` 通过，本地与公网 `/healthz/` 均返回 `{"status": "ok"}`。
  - `ExternalDataImportRun(status=started)=0`，外部导入锁 `0`。
- 部署前备份：
  - 数据库：`backups/db/pre-tdn-france-freshness-20260707_223913.sql.gz`，已执行 `gzip -t`。
- 部署方式：
  - 本地生成 `/tmp/umanews-ad587ce.bundle` 并 `scp` 到生产机。
  - 生产机执行 `git fetch /tmp/umanews-ad587ce.bundle HEAD:refs/remotes/origin/main`、`git merge --ff-only refs/remotes/origin/main`，从 `96fde81` 快进到 `ad587ce`。
  - 执行 `bash ./deploy_lowcost.sh`，镜像重建成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建。
- 修复内容：
  - `TDNFranceKeywordAdapter` / `TDNFranceBroadKeywordAdapter` 对 search item 缺失日期时，使用 `id` 或 `_links.self` 二次读取 post API 的真实 `date_gmt/date`。
  - 缺失真实日期的 search item 跳过，不再兜底为当前时间。
  - 法国 TDN search 来源只接受真实发布时间在 3 天新鲜度窗口内的文章，历史旧文写入跳过摘要。
  - 国际来源抓取任务会把 listing 阶段跳过写入 `CrawlJob` / `NewsSource.last_crawl_message`；纯旧文过滤不标记为来源失败。
- 生产清理：
  - 已将误发布旧文 `7255/7263/7264/7265/7271` 标记为 `workflow_status=withdrawn`、`automation_status=manual_review_required`，清空 `published_to_web_at`，写入 `withdrawn_at`、`decision_reason.tdn_france_stale_cleanup` 与 `editor_notes`。
  - 公网 `/news/7255/`、`/news/7263/`、`/news/7264/`、`/news/7265/`、`/news/7271/` 均返回 `404`。
- 重新启用：
  - `NewsSource#21 TDN 法国宽关键词英文新闻` 已恢复 `enabled=true`、`production_approved=true`，并清空 `manual_pause_reason`。
- 上线后验证：
  - 生产 `HEAD=ad587ce`，`manage.py check` 通过，容器正常，本地与公网 `/healthz/` 均返回 `{"status": "ok"}`。
  - 只读探测 `probe_international_news_sources --source tdn_france_broad --json` 返回 HTTP `200`，但当前 `status=deferred`、`deferred_reason=empty_sample`、`list_count=0`，原因是搜索结果经新鲜度过滤后没有可采样的新鲜文章。
  - 手动真实抓取 `CrawlJob#9445` 成功：`new_count=0`、`seen_count=0`、`skipped_count=80`，首条跳过原因包含 `stale_published_at`，`NEW_ARTICLES=[]`。
  - 结论：来源已重新打开，旧文不再入库；当前没有新稿是 TDN 搜索结果全部被新鲜度过滤后的正常结果。

## 2026-07-07 HKJC 日语 alias 合并与已发布文章术语回填工具

- 本地 change：`hkjc-ja-alias-article-backfill`。
- 新增服务层：`server/stable/services/term_maintenance.py`。
- 新增管理命令：
  - `merge_hkjc_ja_aliases`：生成/应用 HKJC horse 日语 alias 概念合并计划。
  - `backfill_article_terms`：生成/应用已发布文章字段级术语回填 diff。
- 数据库迁移：无。
- artifact 默认目录：`runtime/term_backfills/<operation>-<timestamp>/`。

### 生产执行记录

- 生产服务器：`/opt/umanewsbot`。
- 部署提交：先从 `b1ddb54` 快进到 `4bffbe6`，随后因文章回填 dry-run 性能问题补丁再次快进到 `a65c1ed` 并重建 `web / worker / beat`。
- 部署前备份：
  - `.env.backup.hkjc-ja-alias-backfill-20260707_184118`
  - `backups/db/pre-hkjc-ja-alias-backfill-20260707_184118.sql.gz`，已执行 `gzip -t`。
- 生产部署：
  - `git merge --ff-only origin/main` 后执行 `bash ./deploy_lowcost.sh`。
  - 无新增迁移，`web` healthy，`worker / beat / db / redis / nginx` 正常。
  - 生产保留既有 tracked 热补丁 `server/stable/templates/stable/public/race_detail.html` 中取消/延期状态展示；本次镜像重建前已恢复该热补丁，避免回退线上现有赛事详情表现。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://umafans.run/healthz/`：`200`。
  - 生产 HEAD：`a65c1ed`。
- HKJC alias 合并：
  - 首次 dry-run：`runtime/term_backfills/hkjc-ja-alias-merge-20260707_185042/`，容器内 artifact；summary 为 `candidate=112 skipped=0 scanned=112`，全部 `same_target_primary_owner`。
  - 正式 apply：`runtime/term_backfills/hkjc-ja-alias-merge-apply-20260707_185254/`，容器内 artifact；summary 为 `applied=112 skipped=0 unchanged=0`。
  - 重建后 post-apply smoke 已复制到宿主机：`runtime/term_backfills/hkjc-ja-alias-merge-postapply-smoke-20260707_192810/`，summary 为 `candidate=0 skipped=0 scanned=0`。
  - 数据库验收：`TermEntry(notes__contains="hkjc_ja_alias_merged_into_term_id=")=112`，HKJC active 日语 alias 数为 `268`。
- 文章字段回填：
  - 首次未优化 dry-run 在生产扫描中过慢，已终止；随后补丁 `a65c1ed` 预加载 alias map，避免文章字段循环内重复查 alias。
  - dry-run artifact 已复制到宿主机：`runtime/term_backfills/hkjc-ja-article-backfill-20260707_192910/`。
  - dry-run summary：`scanned_articles=713`、`matched_articles=7`、`planned_fields=29`、`skipped_fields=2`、`replacement_count=37`，耗时约 `4.8s`。
  - apply artifact 已复制到宿主机：`runtime/term_backfills/hkjc-ja-article-backfill-apply-20260707_192931/`。
  - apply summary：`updated_fields=29`、`skipped_fields=2`、`stale_fields=0`。
- `Kalamatianos / カラマティアノス` 抽检：
  - 生产 term `6443`：`Kalamatianos -> 欢快舞步`，`racing_region=japan`。
  - active alias：`Kalamatianos` (`en`, primary) 与 `カラマティアノス` (`ja`, alias)。
  - 文章 `7117` dry-run artifact 已复制到宿主机：`runtime/term_backfills/kalamatianos-article-7117-20260707_192945/`，summary 为 `planned=0 scanned=1`，因为文章字段已无残留原文。
  - `http://127.0.0.1/news/7117/` 返回 `200`，页面包含 `欢快舞步`。

### 生产执行前检查

1. 记录生产当前 commit、`docker compose ps`、`web / worker / beat / db / redis / nginx` 状态。
2. 执行 `python manage.py check`。
3. 检查 `http://127.0.0.1/healthz/` 和公网 `/healthz/`。
4. 确认 `ExternalDataImportRun(status="started")=0` 且外部导入锁为空。
5. 执行数据库备份并用 `gzip -t` 校验备份。

### HKJC 日语 alias 概念合并

dry-run 示例：

```bash
python manage.py merge_hkjc_ja_aliases \
  --racing-region japan \
  --output-dir runtime/term_backfills/hkjc-ja-alias-merge-YYYYMMDD_HHMMSS
```

如果使用人工准备的候选文件，候选 CSV/JSON 至少应包含 `target_term_id` 和 `source_text`：

```bash
python manage.py merge_hkjc_ja_aliases \
  --candidate-file imports/hkjc-ja-alias-candidates.csv \
  --output-dir runtime/term_backfills/hkjc-ja-alias-merge-YYYYMMDD_HHMMSS
```

复核 `merge_plan.json`、`merge_plan_review.csv` 和 `summary.json` 后，正式 apply 必须指定已审核 plan：

```bash
python manage.py merge_hkjc_ja_aliases \
  --apply \
  --plan-file runtime/term_backfills/hkjc-ja-alias-merge-YYYYMMDD_HHMMSS/merge_plan.json \
  --output-dir runtime/term_backfills/hkjc-ja-alias-merge-apply-YYYYMMDD_HHMMSS
```

apply 安全边界：

- 只自动处理 active 英文目标概念 + active 日语主术语 + 同 `term_type` + 同规范化 `target_zh` 的安全项。
- apply 前会重新检查当前 term/alias 状态。
- 若日语 source text 被其它 active 概念主原文或 active alias 占用，则写入 skipped，不在目标概念上创建重复 alias。
- 合并成功后，目标概念新增日语 alias，冗余日语主术语会停用，notes 写入 `hkjc_ja_alias_merged_into_term_id=<target>`。

### 已发布文章术语回填

推荐先使用 merge apply artifact 或明确 term id 生成 dry-run diff：

```bash
python manage.py backfill_article_terms \
  --merge-plan-file runtime/term_backfills/hkjc-ja-alias-merge-apply-YYYYMMDD_HHMMSS/merge_apply.json \
  --source-language ja \
  --limit 50 \
  --output-dir runtime/term_backfills/article-term-backfill-YYYYMMDD_HHMMSS
```

也可以明确指定 term/article 范围：

```bash
python manage.py backfill_article_terms \
  --term-id <TERM_ID> \
  --article-id <ARTICLE_ID> \
  --output-dir runtime/term_backfills/article-term-backfill-YYYYMMDD_HHMMSS
```

复核 `article_backfill_diff.json`、`article_backfill_diff_review.csv` 和 `summary.json` 后，正式 apply 推荐读取已审核 diff：

```bash
python manage.py backfill_article_terms \
  --apply \
  --diff-file runtime/term_backfills/article-term-backfill-YYYYMMDD_HHMMSS/article_backfill_diff.json \
  --output-dir runtime/term_backfills/article-term-backfill-apply-YYYYMMDD_HHMMSS
```

文章回填安全边界：

- 默认只扫描 `workflow_status=published` 且 `published_to_web_at` 非空的已发布文章。
- JSON artifact 保存完整 before/after 字段值，可用于字段级回滚；CSV 仅用于人工快速复核。
- 默认跳过 `manually_edited_fields` 中记录的发布字段。
- 不重新抓取、不重新翻译、不调用 AI 改写、不改变发布状态、审核状态、workflow 状态或 QQ 推送状态。
- `--apply` 若没有 `--diff-file`，必须显式提供 term 范围和 article/date/source/limit 过滤之一；无范围写入会被拒绝。

### 验收与回滚

- 合并后抽查后台术语搜索：英文名和日文名都应命中目标 HKJC 概念；被合并的日语主术语应为 inactive 且 notes 记录合并目标。
- 回填后抽查受影响文章前台页面和后台字段，确认只发生术语替换。
- 复查 `/healthz/`、summary 计数和 skipped/review 项。
- 如 alias 合并错误，按 apply artifact 删除目标 alias，并恢复源 term `is_active=true` 和必要 notes。
- 如文章字段替换错误，优先使用 `article_backfill_diff.json` 中的完整 `before` 值恢复；大范围异常时使用生产数据库备份。

## 2026-07-07 法国新闻源扩展与英文术语门禁修复待上线

- 本次待上线 旧规格流程 changes：
  - `expand-france-news-sources`
  - `fix-english-term-gate-region-filter`
- 代码范围：
  - 法国新增 `tdn_france_broad` 英文补充来源，默认 `enabled=false`、`production_approved=false`。
  - `probe_international_news_sources` 增加 `status/deferred_reason/http_status/final_url/parse_quality/query_errors/sample_errors`。
  - 国际来源抓取支持单篇详情解析失败跳过继续，全部详情失败时来源 / CrawlJob 标记为 failed。
  - 来源同步新增 `MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES=ja,en,zh-hant`，法语源不会被误批准生产。
  - 英文发布校验按文章地区 + 全局术语过滤，并对配置化高歧义英文词降级为 warning。
  - 新增 `reprocess_term_gate_blocked_articles` 受控重处理命令，不直接公开发布文章。
- 本地上线前验证：
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py test stable.tests.FranceNewsSourceExpansionTests ...`
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py test stable.tests.TermRegionFilterTests ...`
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`
  - `旧规格流程 validate expand-france-news-sources --strict`
  - `旧规格流程 validate fix-english-term-gate-region-filter --strict`
  - `旧规格流程 validate --all`
  - `git diff --check`
- 生产部署前检查：
  - `git rev-parse --short HEAD`
  - `docker compose -f docker-compose.prod.lowcost.yml ps`
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`
  - `curl -fsS http://127.0.0.1/healthz/`
  - 确认 `ExternalDataImportRun(status="started")=0` 且外部导入锁为空。
  - 执行生产数据库备份，并用 `gzip -t` 校验。
- 生产部署：
  - `/opt/umanewsbot` 执行 `git pull --ff-only origin main`。
  - 执行 `bash ./deploy_lowcost.sh` 重建 `web / worker / beat`。
  - 执行 `python manage.py sync_builtin_sources`，确认 `TDN 法国宽关键词英文新闻` 已写入 `NewsSource` 且默认未批准生产。
- 上线后验证：
  - `python manage.py probe_international_news_sources --source tdn_france_broad --json` 应返回 `accepted` 或明确 `deferred_reason`；若 `query_errors` 非空，记录部分关键词失败但不直接误判整体不可用。
  - `python manage.py reprocess_term_gate_blocked_articles --region hong_kong --dry-run --json`、`--region united_kingdom`、`--region united_states` 应输出候选、跳过和预计重校验结果，不直接发布。
  - `python manage.py audit_multiregion_news_production --json` 应能展示 `gate_issues`、`gate_blockers`、法国来源 parse failed/source no-new 等摘要。
  - `http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页、后台登录入口均应正常。
- 回滚：
  - 代码异常：回滚到部署前 git ref 后执行 `bash ./deploy_lowcost.sh`。
  - 法国新增来源异常：在后台或 shell 将 `tdn_france_broad` 对应 `NewsSource.production_approved=false` 或 `enabled=false`。
  - 英文门禁误放宽：临时清空或收紧 `MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS`，必要时回滚代码。

## 2026-07-06/07 HKJC / WP Stud 术语库最终清洗与生产导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=b1ddb54`。
- 本地产物：`runtime/termbase_seed/final-reviewed-import-20260706/`。
  - `seed_candidates_final.csv`：最终导入主表，共 `11257` 行。
  - `hkjc_japan_ja_aliases.csv`：HKJC 日本地区英文马名对应日文 alias，共 `907` 行，其中马名 `883` 行。
  - `japan_aliases_missing.csv`：仍缺日文 alias 的日本地区非马名条目，共 `123` 行，包含骑师 `93`、赛事 `30`。
  - `wpstud_horse_skipped_hkjc_alias_overlap.csv`：WP Stud HorseList 中因 HKJC 官方词条已覆盖而跳过的马名 `10` 行。
  - `repair_report.json`：清洗和导入统计。
- 输入来源：
  - HKJC overseas / QIDS 既有审核候选 `7691` 条。
  - WP Stud race / jockey / racecourse 既有审核候选 `1891` 条。
  - WP Stud HorseList 全量马名 `1866` 条，来源 `https://www.wpstud.com/Translation/Horse/HorseList.html`。
- 清洗规则：
  - 马名尾部国别后缀如 `(JPN)`、`(IRE)`、`(GB)` 不进入正式 `source_ja`，原始写法保留在证据中。
  - 带年份或替代名称的复合赛事名拆为独立术语，例如 `International Stakes` 与 `Benson & Hedges Gold Cup Stakes`。
  - `target_zh` 统一简体中文。
  - HKJC 官方主译名优先；WP Stud 作为社区来源、别名或佐证，不覆盖 HKJC 官方主译名。
- 清洗统计：
  - 去除马名国别后缀 `6481` 次。
  - 拆分年份赛事标记 `59` 次。
  - 去重 `254` 行。
  - 最终马名分布包括 `horse|en|japan=880`、`horse|ja|japan=531`，并覆盖英、法、美、香港和 other 地区。
- 本地验证：
  - 最终 CSV 质量检查：马名国别后缀 `0`、赛事年份标记 `0`、HTML entity 残留 `0`、空值 `0`。
  - 临时 SQLite `import_terms --dry-run`：总计 `11257`、新增 `11254`、更新 `3`、错误 `0`。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.TermbaseSeedDataPreparationTests --noinput`：通过，`21` 项。
- 生产导入前检查：
  - `web` healthy，`db/redis` healthy，`worker/beat/nginx` 正常运行。
  - `manage.py check` 通过。
  - `http://127.0.0.1/healthz/` 返回 `{"status":"ok"}`。
  - 导入前 `TermEntry=15321`、`TermAlias=15537`。
  - `ExternalDataImportRun(status="started")=0`，`ExternalDataImportLock.locked_by_run_id` 非空计数为 `0`。
- 备份：
  - `backups/db/pre-final-termbase-review-20260706_234427.sql.gz`，约 `75M`，`gzip -t` 通过。
- 生产文件：
  - Host 路径：`/opt/umanewsbot/imports/final-termbase-review-20260706/`。
  - Web 容器路径：`/tmp/final-termbase-review-20260706/`。
- 生产 dry-run：
  - `preview_summary`: 总计 `11257`、新增 `1169`、更新 `10088`、错误 `0`。
  - `import_result`: 新增 `1169`、更新 `10088`、跳过 `0`。
  - `repair_stats`: `horse_suffix_cleaned=6282`、`horse_suffix_deactivated_duplicates=94`、`race_year_cleaned_primary=119`、`race_year_deactivated_duplicates=9`、`race_year_split_created=68`、`race_year_split_existing=5`。
  - `alias_stats`: `alias_upserted=874`、`alias_deactivated_duplicate_ja_entries=27`、`alias_skipped_existing_alias_owner=27`、`alias_skipped_existing_same_language_entry=5`、`alias_skipped_conflicting_same_language_entry=1`。
  - `quality`: active 马名国别后缀 `0`、active 赛事年份标记 `0`。
- 正式导入：
  - 使用 `apply_final_termbase_repair.py` 在事务中先清理既有 active 脏词，再调用 `preview_term_import / commit_term_import`，最后应用跨语言 alias。
  - 正式导入结果与 dry-run 一致：新增 `1169`、更新 `10088`、错误/跳过 `0`。
- 导入后生产计数：
  - `TermEntry=16558`。
  - `TermAlias=19293`。
  - active `TermEntry=16428`。
  - `source_language=en/racing_region=japan/term_type=horse` 为 `880` 条。
  - WP Stud 日文马名 active 词条 `3235` 条。
  - active 马名国别后缀术语 `0`。
  - active 赛事年份标记术语 `0`。
  - `ExternalDataImportRun(status="started")=0`，导入锁为空。
- 抽样验收：
  - `A Bit Of Spirit` 为 active，中文 `点燃斗志`，别名含英文原文；`A Bit Of Spirit (IRE)` 无 active 词条。
  - `International Stakes -> 国际锦标` 与 `Benson & Hedges Gold Cup Stakes -> 宾臣暨赫捷仕金杯` 均为 active 独立赛事术语。
  - `A Shin Resume -> 荣进重启` 挂日文 alias `エイシンレジューム`。
  - `Dragon -> 腾龙` 挂日文 alias `ドラゴン`。
  - `Dynamic -> 鲜明新曲` 挂日文 alias `ダイナマイク`。
  - `Sophia -> 才情苏菲` 挂日文 alias `ソフィア`。
  - `ハーパー` 不保留 active 独立 WP Stud 词条，因为对应概念已由 HKJC 官方 row / alias 覆盖。
- alias 占用说明：
  - `26` 个 HKJC 日本马英文词条未直接新增日文 alias，是因为对应日文名已被生产中 existing `TermAlias` 或日文主词占用；其中大多数中文目标一致。
  - `Raijin / ライジン` 当前生产已有日文词 `ライジン -> 雷神`，本次 HKJC 英文主词为 `Raijin -> 霹雳雷公`，按冲突处理跳过 alias 合并。
  - `Scintillation / シンチレーション` 当前生产已有香港地区占用 `シンチレーション -> 灿惑`，本次 HKJC 英文主词为 `Scintillation -> 烁亮丽`，按 alias owner 占用跳过。
- 导入后验证：
  - `manage.py check` 通过。
  - `http://127.0.0.1/healthz/` 与 Host `umafans.run` 健康检查均返回 `{"status":"ok"}`。

## 2026-07-06/07 香港 HKJC 与美国 HRN 2026 出走表 / 赛果导入

- 生产服务器：`/opt/umanewsbot`，导入时 JRA 同着展示修复仍为 `web` 容器热补丁状态；后续容器重建前仍需通过 git 镜像部署固化。
- 香港官方来源：
  - HKJC 繁中日汇总页：`https://racing.hkjc.com/zh-hk/local/information/resultsall?Racecourse=<ST/HV>&racedate=YYYY/MM/DD`。
  - HKJC 繁中单场完整赛果页：`https://racing.hkjc.com/zh-hk/local/information/localresults?...&RaceNo=N`。
- 香港本地产物：`runtime/race_event_detail_imports/2026/hong-kong-hkjc-details-20260706/`。
  - `hkjc_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `hkjc_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计。
  - `sources/`：HKJC `resultsall` 与 `localresults` 页面缓存。
- 香港生成结果：
  - `19` 场 HKJC 当前已公开 2026 本地 G1/G2/G3。
  - `182` 条出走表。
  - `181` 条数字名次赛果。
  - `WV` 写入 `RaceEventRunner.running_status=withdrawn`，不进入 `RaceEventResult`。
  - 展示字段繁转简，原始繁中马名、骑师、练马师保存在 `source_refs`。
- 香港生产导入前备份：
  - `backups/db/pre-race-event-details-hk-2026-20260706_234317.sql.gz`，约 `75M`，`gzip -t` 通过。
- 香港生产 dry-run：
  - `{"dry_run": true, "events": 19, "items": {"runners": 182, "results": 181}}`。
- 香港正式导入：
  - `applied=38`、`candidates=38`、`events=19`、`runners=182`、`results=181`。
- 香港页面验收：
  - `/races/2026/hkjc-2026-0125-05/` 返回 `200`，显示董事杯冠军 `浪漫勇士`、完整出走表和赛果；`祝愿 / 阳光勇士` 同为官方第 `4` 名，完成时间均为 `1:33.18`。
  - `/races/2026/hkjc-2026-0621-19/` 返回 `200`，显示精英碟出走表中 `非惟侥幸` 为取消出走，赛果保留 `11` 条已确认名次。
- 美国范围来源：
  - TOBA 官方 2026 American Graded Stakes 表确定 Grade 1/2/3 已完赛范围和 `chart_url` / RaceNo。
  - Horse Racing Nation track-day 页面提供公开可访问出走表和可见结果顺序。
  - Equibase chart HTML/PDF 当前仍返回 `Pardon Our Interruption` 防护页，不能作为批量抓取来源。
- 美国本地产物：`runtime/race_event_detail_imports/2026/united-states-hrn-details-20260706/`。
  - `us_hrn_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `us_hrn_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计。
  - `sources/`：HRN date / track-day 页面缓存。
- 美国生成结果：
  - `195` 场 TOBA 已完赛 Grade 1/2/3。
  - `1710` 条出走表。
  - `1448` 条可确认赛果。
  - 马名展示字段剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。
  - HRN 对 Kentucky Derby / Oaks 等少量页面只公开出走表、不公开 payout / also-rans 结果块；本批不使用 TOBA `winner` 字段猜完整名次，因此这些场次暂不显示赛果。
  - 初次 apply 因 HRN HTML 重复渲染同一出走马导致 `(event, horse_number)` 唯一约束冲突；旧 pending 候选已标为 failed，生成器改为按 `horse_number + horse_name + horse_url` 去重后重跑。
- 美国生产导入前备份：
  - `backups/db/pre-race-event-details-us-hrn-2026-20260707_000230.sql.gz`，约 `75M`，`gzip -t` 通过。
- 美国生产 dry-run：
  - 修正版：`{"dry_run": true, "events": 195, "items": {"runners": 1710, "results": 1448}}`。
- 美国正式导入：
  - 修正版 apply 成功：`applied=390`、`candidates=390`、`events=195`、`runners=1710`、`results=1448`。
- 导入后生产详情总计：
  - `RaceEventRunner=3260`。
  - `RaceEventResult=2977`。
  - `RaceEventHistoryWinner=0`。
  - `RaceEventDataCandidate=992`、`AppliedCandidates=990`、`FailedCandidates=2`、`PendingCandidates=0`。
  - 美国详情行：`Runner=1710`、`Result=1448`。
- 美国页面验收：
  - `/races/2026/us-toba-2026-0108-001/` 返回 `200`，显示 Robert J. Frankel S. 冠军 `Paradise Lake`、出走表和赛果。
  - `/races/2026/us-toba-2026-0502-119/` 返回 `200`，显示 Kentucky Derby 出走表；因 HRN 未公开结果块，暂不显示赛果。
  - `http://umafans.run/healthz/` 返回 `{"status": "ok"}`。

## 2026-07-06 NAR 2026 地方/交流重赏出走表 / 赛果导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=b1ddb54`，且 JRA 同着展示修复仍为 `web` 容器热补丁状态。
- 官方来源：
  - NAR ダートグレード特设赛事页：`https://www.keiba.go.jp/dirtgraderace/2026/<race>/racecard.html` 或 `introduction.html`。
  - 出馬表：`https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?...`。
  - 競走成績：`https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?...`。
- 本地产物：`runtime/race_event_detail_imports/2026/japan-nar-details-20260706/`。
  - `nar_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `nar_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计和未公布出走表缺口。
  - `sources/`：NAR 特设页、出馬表页和競走成績页缓存。
- 生成结果：
  - `21` 场当前官方可用赛事。
  - `256` 条出走表。
  - `242` 条数字名次赛果。
  - `20` 场已完赛写出走表和赛果。
  - `2026-07-08` スパーキングレディーカップ仅官方已公布出走表，未有赛果。
  - `25` 场未来赛事仍停留在 `introduction.html`，未公布出走表，记录为 `racecard_not_published`。
- 状态处理：
  - `除外` 写入 `RaceEventRunner.running_status=scratched`。
  - `取消` 写入 `withdrawn`。
  - 空白着顺写入 `unknown`。
  - 只有数字着顺进入 `RaceEventResult`。
- 生产导入前备份：
  - `backups/db/pre-race-event-details-nar-2026-20260706_232856.sql.gz`，约 `75M`，`gzip -t` 通过。
- 生产 dry-run：
  - 结果：`{"dry_run": true, "events": 21, "items": {"runners": 256, "results": 242}}`。
- 正式导入：
  - `applied=41`、`candidates=41`、`events=21`、`runners=256`、`results=242`。
- 导入后计数：
  - `RaceEventRunner=1368`。
  - `RaceEventResult=1348`。
  - `RaceEventHistoryWinner=0`。
  - `RaceEventDataCandidate=233`、`AppliedCandidates=232`、`FailedCandidates=1`。
  - 当前详情表行仍全部属于日本地区。
- 页面验收：
  - `/races/2026/nar-dirt-2026-0701-20/` 返回 `200`，显示帝王賞冠军 `ミッキーファイト`、出走表、赛果和 `2:02.8`。
  - `/races/2026/nar-dirt-2026-0708-21/` 返回 `200`，显示スパーキングレディーカップ出走表，包含 `レクランスリール` 与 `アピーリングルック`，未显示赛果区块。
  - `http://umafans.run/healthz/` 返回 `{"status": "ok"}`。
  - `manage.py check` 通过。
- 剩余日本详情缺口：
  - JRA 未来 `66` 场未公布出走表 / 赛果。
  - NAR 未来 `25` 场仍为 `introduction.html`，未公布出走表 / 赛果。
  - 后续应按官方发布节奏刷新，不猜测名单。

## 2026-07-06 JRA 2026 已完赛重赏出走表 / 赛果导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=b1ddb54`。
- 官方来源：
  - JRA 2026 重赏列表：`https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`。
  - JRA 普通重赏结果页：`/datafile/seiseki/replay/2026/<id>.html`。
  - JRA G1 结果页：`/datafile/seiseki/g1/<race>/result/<race>2026.html`。
- 本地产物：`runtime/race_event_detail_imports/2026/japan-jra-details-20260706/`。
  - `jra_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `jra_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计。
  - `sources/`：JRA 结果页缓存。
- 生成结果：
  - `74` 场 JRA 已完赛中央重赏。
  - `1112` 条出走表。
  - `1106` 条数字名次赛果。
  - `取消=2`、`除外=2`、`中止=2` 不进入 `RaceEventResult`，但保留在 `RaceEventRunner.running_status`。
- 同着处理：
  - `RaceEventResult.finish_position` 当前有唯一约束，因此用于前台排序和数据库唯一位。
  - JRA 官方名次保存在 `source_refs.official_finish_position` 和 `source_refs.jra_finish_position_text`。
  - 前台详情页和日历页优先展示 `official_finish_position`，因此安田記念同着第 2 名会显示两匹第 `2` 名。
- 本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.RaceEventPageMVPTests --noinput`：通过，`17` 项。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`：通过。
  - `git diff --check`：通过。
- 生产导入前检查：
  - `web` healthy，`db/redis` healthy，`worker/beat/nginx` 正常运行。
  - 导入前详情表均为空：`RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=0`。
- 备份：
  - `backups/db/pre-race-event-details-jra-2026-20260706_224953.sql.gz`，约 `75M`，`gzip -t` 通过。
- 生产 dry-run：
  - 通过临时脚本 `imports/race-event-details-jra-2026-20260706/apply_race_event_detail_jsonl.py` 在 `web` 容器内执行。
  - 结果：`{"dry_run": true, "events": 74, "items": {"runners": 1112, "results": 1106}}`。
- 首次正式 apply：
  - 在 `オーシャンS` 遇到 JRA 同着，触发 `uq_race_result_event_pos` 唯一约束冲突后停止。
  - 停止时已有 `Runner=332`、`Result=316`、`Candidate=44`、`AppliedCandidates=43`、`PendingCandidates=1`。
  - 修正候选包后重新从头 apply，旧 pending 候选标记为 `failed`，错误说明为 `superseded by rerun after duplicate finish-position normalization`。
- 正式导入结果：
  - 第二次 apply 成功：`applied=148`、`candidates=148`、`events=74`、`runners=1112`、`results=1106`。
  - 导入后生产：`RaceEventRunner=1112`、`RaceEventResult=1106`、`RaceEventDataCandidate=192`、`AppliedCandidates=191`、`FailedCandidates=1`。
  - 宝塚記念：`runners=18`、`results=17`，冠军为 `メイショウタバル`。
  - 安田記念：`ワールズエンド` 与 `ガイアフォース` 均保留 `official_finish_position=2`。
- 前台展示热补丁：
  - 为立即正确展示同着名次，已将本地 `server/stable/views.py`、`server/stable/templates/stable/public/race_detail.html`、`server/stable/templates/stable/public/race_calendar.html` 复制到 `umanewsbot-web-1` 容器并重启同一容器。
  - 容器重建会丢失该热补丁；后续正式部署前必须先将这三处改动通过 git 提交/部署固化。
- 验收：
  - `http://umafans.run/healthz/` 返回 `{"status": "ok"}`。
  - `/races/2026/takarazuka-kinen/` 返回 `200`，显示 `メイショウタバル`、出马表、赛果和 `2:12.1`。
  - `/races/2026/jra-2026-0607-01/` 返回 `200`，`ワールズエンド` 与 `ガイアフォース` 在头部摘要和赛果表中均显示第 `2` 名，`ガイアフォース` 显示 `同着`。
  - `web` healthy，`worker / beat / db / redis / nginx` 正常运行。
- 剩余工作：
  - 继续补 JRA 未完赛场次的赛前出走表。
  - 继续补 NAR、HKJC、美国、英国、法国的出走表和赛果。
  - 在出走表和赛果稳定后，再开始导入历届冠军。

## 2026-07-06 英国 BHA Flat 2026 Group 赛事 OCR 导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=87319b4`。
- 官方来源：`https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Flat_Pattern_Listed_2026.pdf`。
- 本地产物：`runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/`。
- 解析方式：
  - BHA Flat 官方 PDF 正文页无可用文本层，普通 PDF 文本抽取为空。
  - 本次使用 `pdftoppm` 渲染详情页，再通过 macOS Vision OCR 生成 `flat_detail_ocr.jsonl`。
  - 赛事名、日期、场地和等级来自官方详情页 OCR；距离字段来自 OCR，明显残缺项已清空或人工清理，并统一保留 `data_quality_status=partial`。
  - 场地规则：Kempton Park / Lingfield Park / Newcastle / Southwell / Wolverhampton / Chelmsford City 或 OCR 含 `AWT` 时记为 `synthetic`，其他 Flat 赛事记为 `turf`。
- 范围：
  - British Flat Pattern and Listed Races 2026 中 `Group 1 / Group 2 / Group 3`。
  - 排除 Listed。
- 生成结果：
  - `138` 场；`G1=33`、`G2=42`、`G3=63`。
  - `finished=59`、`scheduled=79`。
  - `synthetic=6`、`turf=132`。
- 本地验证：
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py import_race_events --csv runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/race_events_united_kingdom_bha_flat_2026.csv --dry-run` 通过。
- 生产导入前检查：
  - `web` healthy，`db/redis` healthy，`worker/beat/nginx` 正常运行。
  - `RaceEvent=857`、`RaceEventAlias=2863`、`UK2026=65`、`UKFlatExisting=0`。
  - `TaskExecutionLog(task_name="import_race_events", status="started")=0`。
- 备份：
  - `backups/db/pre-race-events-uk-bha-flat-2026-20260706_222151.sql.gz`，约 `74M`，`gzip -t` 通过。
- 生产文件：
  - Host 路径：`/opt/umanewsbot/imports/race-events-uk-bha-flat-2026-20260706/race_events_united_kingdom_bha_flat_2026.csv`。
  - 注意：`imports/` 未挂载到 `web` 容器；已使用 `docker cp` 复制到 `web:/tmp/race_events_united_kingdom_bha_flat_2026.csv` 后执行管理命令。
- 生产 dry-run：
  - `docker compose exec -T web python manage.py import_race_events --csv /tmp/race_events_united_kingdom_bha_flat_2026.csv --dry-run` 通过。
- 正式导入：
  - `created=138 updated=0 aliases=414`。
- 导入后计数：
  - `RaceEvent=995`、`RaceEventAlias=3277`。
  - `UK2026=203`、`UKFlat2026=138`、`UKFlatVisible=138`、`UKFlatSynthetic=6`。
- 页面验收：
  - `/races/?tab=all&region=united_kingdom` 返回 `200`，可命中 `CORAL-ECLIPSE` 与“复合赛道”。
  - `/races/2026/uk-bha-flat-2026-0704-058/` 返回 `200`，显示 `CORAL-ECLIPSE`。
  - `/races/2026/uk-bha-flat-2026-0905-102/` 返回 `200`，显示 `UNIBET SEPTEMBER STAKES` 与“复合赛道”。
- 剩余缺口：
  - HKJC 尚未公开 2026/27 马季年末香港本地 G1/G2/G3 日期明细。
  - 英国 Jump 2026 年 10-12 月需要 2026/27 官方书或其他官方结构化来源。

## 2026-07-06 赛事日历 2026 NAR / 美国 / 英国 Jump / 法国正式导入

- 生产服务器：`/opt/umanewsbot`。
- 日本 NAR/交流ダートグレード批次：
  - 官方来源：`https://www.keiba.go.jp/dirtgraderace/2026/racelist/index.html`、`https://www.keiba.go.jp/pdf/uploads/20251110_01_01.pdf`。
  - 本地产物：`runtime/race_event_imports/2026/japan-nar-dirt-graded-20260706/`。
  - 范围：地方竞马场 JpnⅠ/JpnⅡ/JpnⅢ 与大井东京大赏典 GⅠ，共 `46` 场；排除已在 JRA 中央批次导入的中央场 G/J-G 赛事。
  - 生成结果：`JPN3=21`、`JPN2=12`、`JPN1=12`、`G1=1`；`finished=20`、`scheduled=26`；官方网页给出发走时刻 `22` 场，另 `24` 场时刻待定。
  - 备份：`backups/db/pre-race-events-japan-nar-2026-20260706_133705.sql.gz`，约 `73M`，`gzip -t` 通过。
  - 生产 dry-run：`python manage.py import_race_events --csv /tmp/race_events_japan_nar_dirt_graded_2026.csv --dry-run` 通过。
  - 正式导入：`created=46 updated=0 aliases=105`。
  - 验收：生产计数 `Japan2026=186`、`NAR2026=46`、`NARWithTime=22`、`NARPendingTime=24`；公网 `/races/2026/nar-dirt-2026-0701-20/` 显示帝王赏与 `20:05`，`/races/2026/nar-dirt-2026-1229-46/` 显示东京大赏典与“待定”。
- 复合赛道支持上线：
  - 本地提交并推送 `9dc9b4d Support synthetic race event surface`。
  - 新增 `RaceEventSurface.SYNTHETIC=synthetic/复合赛道` 与迁移 `stable.0021_alter_raceevent_surface`。
  - 本地验证：`RaceEventPageMVPTests` 14 项、`manage.py check`、`makemigrations --check --dry-run` 和 `git diff --check` 通过。
  - 生产部署：从 `40133ec` 快进到 `9dc9b4d`，`.env` 已备份为 `.env.backup.synthetic-surface-<timestamp>`，Docker build context 约 `878.5kB`；部署后 `web/worker/beat` 重建，`manage.py check` 通过，`showmigrations stable` 显示 `[X] 0021_alter_raceevent_surface`，生产 shell 确认 `synthetic 复合赛道`。
- 美国 TOBA Grade 批次：
  - 官方来源：`https://toba.org/graded-stakes/2026-races/`。
  - 本地产物：`runtime/race_event_imports/2026/united-states-toba-graded-20260706/`。
  - 范围：当前 TOBA 表内 Grade 1/2/3，共 `411` 条；排除 Listed `200` 条与其他非分级黑体 `12` 条。当前 TOBA 表解析为 `411` 条 Grade，而页面公告口径写 `410`，本次以当前官方表格行为准并在 `summary.json` 记录差异。
  - 生成结果：`G1=92`、`G2=136`、`G3=183`；`370` 条有日期并公开展示，`41` 条空日期或 `not run` 作为 draft 底表记录保留；surface 为 `dirt=222`、`turf=186`、`synthetic=3`。
  - 备份：`backups/db/pre-race-events-us-toba-graded-2026-20260706_134731.sql.gz`，约 `73M`，`gzip -t` 通过。
  - 正式导入：dry-run 通过后 `created=411 updated=0 aliases=1550`。
  - 验收：`USTOBA2026=411`、`USTOBAVisible=370`、`USTOBADraft=41`、`Synthetic=3`；`/races/2026/us-toba-2026-0321-068/` 返回 `200` 并显示 `JEFF RUBY STEAKS` 与“复合赛道”，undated draft 详情返回 `404`。
- 英国 BHA Jump 批次：
  - 官方来源：`https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Jump_Pattern_Listed_2526.pdf`。
  - 本地产物：`runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/`。
  - 范围：BHA 2025/2026 Jump Pattern and Listed 书中日期落在 2026 年 1-4 月的 Grade 1/2/3；排除 Listed、Premier Handicap 和 2025 年赛季内赛事。本官方书当前只能覆盖 2026 年 1-4 月，2026 年 10-12 月需等待 2026/27 官方书或其他官方结构化来源。
  - 生成结果：`64` 场，`G1=28`、`G2=36`、`G3=0`。
  - 备份：`backups/db/pre-race-events-uk-bha-jump-2026-20260706_214916.sql.gz`，约 `74M`，`gzip -t` 通过。
  - 正式导入：dry-run 通过后 `created=64 updated=0 aliases=192`。
  - 验收：`UKJump2026=64`、`UKJumpVisible=64`；`/races/2026/uk-bha-jump-2026-0313-042/` 返回 `200` 并显示 `Boodles Cheltenham Gold Cup Chase`、`Cheltenham` 与“障碍”。
- 法国 France Galop Groupe 批次：
  - 官方来源：`https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf`、`https://www.france-galop.com/sites/default/files/2026-01/groupes_listed_obstacles_2026_v4.pdf`。
  - 本地产物：`runtime/race_event_imports/2026/france-france-galop-group-20260706/`。
  - 范围：逐赛条件页中 `Groupe I / Groupe II / Groupe III`；排除 Listed。因 PDF 文字层存在 `CHANTILL Y`、`Prix Saint` 等抽取伪影，本批已做马场名修正并在 `source_refs.racecourse_parser_fix` 记录。
  - 生成结果：`173` 条，Flat `113`、障碍 `60`；`G1=37`、`G2=38`、`G3=98`。
  - 备份：`backups/db/pre-race-events-france-galop-group-2026-20260706_215904.sql.gz`，约 `74M`，`gzip -t` 通过。
  - 正式导入：dry-run 通过后 `created=173 updated=0 aliases=519`。
  - 验收：`FranceGalop2026=173`、`FranceFlat=113`、`FranceJumps=60`；`/races/2026/fr-france-galop-2026-0426-014/` 返回 `200` 并显示 `PRIX GANAY`、`ParisLongchamp` 与“草地”，`/races/2026/fr-france-galop-2026-0517-138/` 返回 `200` 并显示 `GRAND STEEPLE-CHASE DE PARIS`、`Auteuil` 与“障碍”。
- 导入后总计：
  - 生产 `RaceEvent=857`、`RaceEventAlias=2863`。
  - 2026 五地区计数：日本 `186`、香港 `20`、美国 `412`、英国 `65`、法国 `174`。
- 剩余缺口：
  - HKJC 尚未公开 2026/27 马季年末香港国际赛等日期明细。
  - BHA Flat 2026 官方 PDF 正文页文字层为空，需要 OCR 或找到另一官方结构化源后再补英国 Flat Group 1/2/3。
  - 英国 Jump 2026 年 10-12 月需要 2026/27 官方书或其他官方结构化源。

## 2026-07-06 赛事日历 2026 日本与香港正式导入

- 生产服务器：`/opt/umanewsbot`，当前导入时 `HEAD=c996621`。
- 导入前检查：
  - `web` healthy，`worker / beat / db / redis / nginx` 正常运行。
  - `ExternalDataImportRun(status="started")=0`。
  - `ExternalDataImportLock.locked_by_run_id` 为空。
- 日本 2026 JRA 中央重赏批次：
  - 官方来源：`https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`。
  - 本地产物：`runtime/race_event_imports/2026/japan-jra-central-graded-20260706/`。
  - 范围：JRA 中央 `G1/G2/G3/J-G1/J-G2/J-G3`，不含 Listed/Open 和地方交流重赏。
  - 生成结果：`140` 场，`G1=24`、`G2=38`、`G3=68`、`JG1=2`、`JG2=3`、`JG3=5`；`finished=74`、`scheduled=66`。
  - 备份：首次 `pg_dump -U postgres` 因生产库角色不是 `postgres` 失败且未写库；有效备份改用运行中的 `db` 容器执行 `pg_dump -U horse_news -d horse_news`，文件为 `backups/db/pre-race-events-jra-2026-20260706_113855.sql.gz`，大小约 `72M`，`gzip -t` 通过。
  - 生产 dry-run：`python manage.py import_race_events --csv /tmp/race_events_japan_jra_2026.csv --dry-run` 通过。
  - 正式导入：`created=139 updated=1 aliases=413`；`宝塚記念` 更新既有样例 `takarazuka-kinen`。
  - 导入后计数：`RaceEvent=144`、`RaceEventAlias=423`、`japan/year=2026` 为 `140` 场。
  - 前台验收：`/races/?region=japan`、`/races/2026/takarazuka-kinen/`、`/races/2026/jra-2026-1227-01/` 和 `/races/2026/jra-2026-0104-01/` 均返回 `200` 并显示基础资料。
- 香港 2026 HKJC 分级赛批次：
  - 官方来源：`https://racing.hkjc.com/zh-hk/international-racing/g2-g3-races/index`、`https://campaigns.hkjc.com/racing-event-hub/ch/`，并用 HKJC 本地赛果页补马场、距离和场地。
  - 本地产物：`runtime/race_event_imports/2026/hong-kong-hkjc-pattern-20260706/`。
  - 范围：HKJC 当前公开 2025/26 马季内、比赛日期落在 2026 年的香港本地 `G1/G2/G3`，共 `19` 场；不包含四岁马经典赛、Listed/Open、地区重赏，也不猜测尚未由 HKJC 公开 2026/27 日期的 2026 年末香港国际赛。
  - 生成结果：`19` 场，`G1=8`、`G2=2`、`G3=9`；全部为 `finished`；已过滤非单场赛事卡片 `沙田煞科日`。
  - 备份：`backups/db/pre-race-events-hk-2026-20260706_115242.sql.gz`，大小约 `72M`，`gzip -t` 通过。
  - 生产 dry-run：`python manage.py import_race_events --csv /tmp/race_events_hong_kong_hkjc_2026.csv --dry-run` 通过。
  - 正式导入：`created=19 updated=0 aliases=74`。
  - 导入后计数：`RaceEvent=163`、`RaceEventAlias=497`、`hong_kong/year=2026` 为 `20` 条，其中 `19` 条为本批 HKJC 官方源，另 `1` 条为既有香港杯样例。
  - 前台验收：`/races/?tab=all&region=hong_kong`、`/races/?tab=key&region=hong_kong&direction=past&cursor=2026-07-06`、`/races/2026/hkjc-2026-0125-05/`、`/races/2026/hkjc-2026-0426-13/`、`/races/2026/hkjc-2026-0114-03/` 均返回 `200` 并显示简体中文名、繁体原名、马场、距离、基础资料和出马表占位。
- 操作注意：
  - 生产主机 `imports/` 目录没有挂载到 `web` 容器；CSV 上传到 `/opt/umanewsbot/imports/...` 后，需要再 `docker cp` 到 `umanewsbot-web-1:/tmp/...` 执行导入命令。
  - HKJC 官方页当前未公开 2026/27 马季年底香港国际赛日期明细；后续应等官方赛期公开后再补 2026 年末香港 G1，而不是沿用样例日期。

## 2026-07-06 赛事马名后缀清洗与 Docker build context 修复上线

- 本地提交：
  - `3a25233`：记录日本/香港赛事导入，并在赛事候选资料应用层清洗马名末尾国籍后缀。
  - `b6cbe7c`：新增 `.dockerignore`，排除 `.git / .venv / runtime / imports / backups / napcat / logs / server/staticfiles / server/media` 等运行产物。
- 上线前本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.RaceEventPageMVPTests --noinput`：通过，13 项。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`：通过。
  - `git diff --check`：通过。
- 生产操作：
  - 首次部署 `3a25233` 前确认 `ExternalDataImportRun(status="started")=0`、导入锁为空，并备份 `.env` 为 `.env.backup.race-event-horse-suffix-20260706_115804`。
  - 首次构建因仓库没有 `.dockerignore`，Docker build context 持续增长到 `3GB+` 仍未进入构建；中断后确认旧容器仍正常、`web` healthy、`manage.py check` 通过。
  - 推送 `b6cbe7c` 后，生产从 `3a25233` 快进到 `b6cbe7c`，并备份 `.env` 为 `.env.backup.race-event-dockerignore-20260706_120450`。
  - 重新部署时 build context 降至约 `877.5kB`，镜像构建、容器重建、迁移检查和 collectstatic 均完成；`web / worker / beat` 已重建，`db / redis / nginx` 正常。
- 部署后验证：
  - 生产 `HEAD=b6cbe7c`。
  - `manage.py check` 通过。
  - 容器内 `_clean_race_horse_name("Calandagan (IRE)") == "Calandagan"`，`_clean_race_horse_name("Masquerade Ball（JPN）") == "Masquerade Ball"`。
  - 生产计数保持 `RaceEvent=163`、`RaceEventAlias=497`、`Japan2026=140`、`HK2026=20`。
  - 通过公网 Host 验收：`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/`、`/races/2026/hkjc-2026-0125-05/`、`/races/?tab=all&region=hong_kong` 均返回 `200`。

## 2026-07-06 赛事日历线上验收与示例审核包

- 生产服务器：`/opt/umanewsbot` 当前 `HEAD=c996621`。
- 线上验收：
  - 公网 `http://umafans.run/healthz/` 返回 `200`，内容为 `{"status": "ok"}`。
  - 公网 `/races/` 返回 `200`。
  - 公网 `/admin/login/` 返回 `200`。
  - `web` 为 healthy，`worker / beat / db / redis / nginx` 正常运行。
  - `manage.py check` 通过。
  - `showmigrations stable` 确认 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`。
  - `ExternalDataImportRun(status="started")=0`，导入锁为空。
- 生产赛事模块当前计数：
  - `RaceEvent=5`、`RaceEventAlias=10`。
  - `RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventDataCandidate=0`、`ArticleRaceLink=0`。
  - 五地区各 1 条样例赛事。
- 示例审核包：
  - 路径：`runtime/race_event_review_samples/japan-cup-2025-20260706/`。
  - 官方来源：`https://japanracing.jp/en/japancup/news_results/news2025/251130-02.html`。
  - 文件：`race_events_sample.csv`、`race_event_candidate_payload.json`、`source_official.html`、`README.md`。
  - 样例为 `2025 Japan Cup`，日本 `G1`，非 listed，非地区重赏；解析出基础资料 1 组、出走表 17 匹、正式完赛赛果 16 条。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py import_race_events --csv runtime/race_event_review_samples/japan-cup-2025-20260706/race_events_sample.csv --dry-run` 通过。
  - `race_event_candidate_payload.json` 已通过 JSON 格式校验。
  - 本次不写生产库；CSV 中 `visibility_status=draft`，等待人工审核后再进入小流量多次正式爬取。

## 2026-07-06 HKJC 术语种子抽取返修上线

- 本地上线提交：`4b6e840`（`Harden HKJC termbase seed extraction`），已推送 `origin/main`。
- 生产服务器：`/opt/umanewsbot` 从 `9b3bb86` 快进到 `4b6e840`。
- 上线前本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.TermbaseSeedDataPreparationTests --noinput`：通过，21 项。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`：通过。
  - `旧规格流程 validate --all`：通过，17 项。
  - `git diff --check`：通过。
- 上线前生产检查：
  - `ExternalDataImportRun(status="started")=0`。
  - `ExternalDataImportLock.locked_by_run_id` 当前为空。
  - `web / worker / beat / db / redis / nginx` 上线前均在运行，`web` 为 healthy。
- 备份：
  - `.env`：`.env.backup.harden-hkjc-termbase-20260706_043557`。
  - 数据库：`backups/db/pre-harden-hkjc-termbase-20260706_043557.sql.gz`，大小约 `71M`，已执行 `gzip -t` 校验。
- 部署命令：
  - `git fetch origin main && git pull --ff-only origin main`
  - `./deploy_lowcost.sh`
- 部署结果：
  - `web / worker / beat` 已重建并启动，`db / redis / nginx` 正常。
  - 服务器内 `/healthz/` 返回 `200`，内容为 `{"status": "ok"}`。
  - `manage.py check`：通过。
  - `showmigrations stable` 确认 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`。
  - 服务器内 `Host: umafans.run`：`/`、`/races/`、`/admin/login/` 均返回 `200`。
  - 本机经 `--resolve umafans.run:80:47.239.167.86` 访问公网 `/healthz/` 返回 `200`。
- 术语种子 smoke：
  - 命令：`python manage.py prepare_termbase_seed_data --source hkjc_overseas --input-dir stable/fixtures/termbase_seed --output-dir runtime/termbase_seed/harden-hkjc-termbase-smoke-20260706_045028`
  - 结果：`candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`。
  - 生产 shell smoke 已验证 HKJC/QIDS 同英文名、不同 `QIDSCode` 的加拿大马不会误合并：两个候选分别生成 `hkjc_overseas:horse:can001` 与 `hkjc_overseas:horse:can002`，地区均落为 `other`。
  - 本次未导入正式术语，生产计数保持 `TermEntry=15321`、`TermAlias=15537`。
- 后续注意：
  - 本次生产 Docker build 上下文已超过 `1.6GB`，主要来自服务器工作区运行产物；后续应补 `.dockerignore` 或隔离 `runtime / imports / backups / napcat` 等目录，降低构建时间与断线风险。

## 2026-07-04 赛事日历 MVP 与 HKJC overseas 术语种子 smoke 上线

- 本地上线提交：`f3c4c46`（`Add race calendar and HKJC overseas termbase seeds`），已推送 `origin/main`。
- 生产服务器：`/opt/umanewsbot` 从 `3aa22fb` 快进到 `f3c4c46`。
- 上线前本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable --noinput`：通过，442 项。
  - `旧规格流程 validate --all`：通过，17 项。
  - `git diff --check`：通过。
- 上线前生产检查：
  - `ExternalDataImportRun(status="started")=0`。
  - `ExternalDataImportLock.locked_by_run_id` 当前为空。
  - `web / worker / beat / db / redis / nginx` 上线前均在运行。
- 备份：
  - `.env`：`.env.backup.race-calendar-hkjc-overseas-20260704_182412`。
  - 数据库：`backups/db/rds_horse_news_race_calendar_manual_20260704_182458.sql.gz`，大小约 `63M`，已执行 `gzip -t` 校验。
  - 注意：首次尝试 `deploy/backup_db.sh` 时因脚本读取 `.env` 中 OSS 目标且临时 `postgres:16` 容器不在 Compose 网络内，产生 20 字节无效备份；该无效文件已删除。本次有效备份改用正在运行的 `db` 容器执行 `pg_dump`。
- 部署命令：
  - `git fetch origin main && git pull --ff-only origin main`
  - `./deploy_lowcost.sh`
- 部署结果：
  - `web / worker / beat` 已重建并启动，`db / redis / nginx` 正常。
  - `manage.py check`：通过。
  - `showmigrations stable` 确认 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`。
  - `collectstatic` 成功，公开 CSS 指纹更新。
- 赛事日历种子：
  - `python manage.py import_race_events --csv stable/data/race_events_seed_sample.csv --dry-run`：通过，将处理 5 条。
  - 正式导入结果：`created=5 updated=0 aliases=10`。
  - 生产计数：`RaceEvent=5`、`RaceEventAlias=10`、`ArticleRaceLink=0`、`P0/P1=5`。
- 线上路由验收：
  - 服务器内 `Host: umafans.run`：`/healthz/`、`/`、`/races/`、`/admin/login/` 均返回 `200`，未登录 `/admin/race-events/` 返回 `302`。
  - 赛事详情：`/races/2026/takarazuka-kinen/` 返回 `200`，包含“基础资料”和“出马表”区块。
  - 本机经公网 IP + `Host: umafans.run`：`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/` 均返回 `200`。
  - 本机环境中 `umafans.run` DNS 一度解析到 `198.18.0.181`，因此本次公网验收以 `47.239.167.86` + `Host` 头为准。
- HKJC overseas 术语种子 smoke：
  - 命令：`python manage.py prepare_termbase_seed_data --source hkjc_overseas --input-dir stable/fixtures/termbase_seed --output-dir runtime/termbase_seed/hkjc-overseas-deploy-smoke-20260704_183048`
  - 结果：`candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`。
  - 本次只生成人工审核工件，不正式导入 `TermEntry` / `TermAlias`。
- 后续注意：
  - 生产 Docker build 上下文超过 `700MB`，主要来自服务器工作区未跟踪的 `runtime / imports / napcat / backups` 等运行产物；后续应单独补 `.dockerignore` 或调整部署目录，降低构建时间和传输成本。
  - `deploy/backup_db.sh` 在当前生产 `.env` 下会被 `BACKUP_TARGET=oss` 覆盖，并且临时容器访问 Compose 内部 `db` 主机名失败；后续应修正为显式接入 Compose 网络或提供 db 容器备份路径，避免产生误导性空备份。

## 服务器信息记录方式

不要把敏感信息硬编码进仓库，但应按如下方式记录：

- 服务器公网 IP：记录在运维文档或受控密码库中
- 域名：记录在仓库文档中
- DNS 提供商：记录在仓库文档中
- ECS 地域与实例规格：记录在仓库文档中
- `.env` 实际值：只保存在服务器与受控密钥管理位置，不写入仓库

敏感信息包括但不限于：

- root 密码
- API Key
- OSS AccessKey
- `.env` 完整内容

## 域名、DNS、ECS、Nginx、Docker Compose、.env 的关系

- 域名：用户可见入口，例如 `umafans.run`
- DNS：负责把域名解析到 ECS 公网 IP
- ECS：承载 Docker 容器的主机
- Docker Compose：编排 `web / worker / beat / db / redis / nginx`
- Nginx：处理入口请求、静态资源、反向代理
- `.env`：决定 Django 与部署链路运行方式，如 Host、CSRF、SITE_URL、安全策略等

## 本轮修复时验证过的关键检查命令

### 服务器代码版本

```bash
cd /opt/umanewsbot
git rev-parse --short HEAD
```

### 查看 `.env` 关键项

```bash
grep -E '^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)=' .env
```

### 查看容器状态

```bash
docker compose -f docker-compose.prod.lowcost.yml ps
```

### 查看 nginx 容器中的真实配置

```bash
docker exec umanewsbot-nginx-1 sh -c 'cat /etc/nginx/conf.d/default.conf'
```

### 查看 web 容器中的真实环境变量

```bash
docker exec umanewsbot-web-1 sh -c 'env | grep -E "^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)="'
```

### 查看日志

```bash
docker logs --tail=120 umanewsbot-web-1
docker logs --tail=120 umanewsbot-nginx-1
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
```

## 以后遇到“HTTP 301 / HTTPS 400 / 域名不通”时的排查顺序

### 1. 先确认 DNS

- 本地 `nslookup`
- 必要时查公共 DNS
- 确认是否已解析到目标 ECS 公网 IP

### 2. 再确认服务器代码版本

- `git rev-parse --short HEAD`
- 不要假设服务器已经是本地最新 commit

### 3. 确认 `.env`

- 是否仍是旧域名/旧 IP/旧安全配置
- 是否包含正确的 `ALLOWED_HOSTS`
- `SITE_URL` 是否与当前阶段一致

### 4. 确认 nginx 运行态

- 不只看仓库里的 `nginx.conf`
- 必须进入 `nginx` 容器读取真实 `default.conf`

### 5. 确认 Django 运行态

- 进入 `web` 容器检查真实环境变量
- 再看 `web` 日志里是否有 `DisallowedHost`、CSRF、重定向等问题

### 6. 最后再看浏览器现象

- 浏览器现象只能说明“外部表现”
- 不能替代对 `nginx`、`.env`、容器环境变量、日志的核对

## 标准流程

### 备份 `.env`

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
```

### 检查 HEAD

```bash
git rev-parse --short HEAD
```

### 查看 nginx 容器配置

```bash
docker exec umanewsbot-nginx-1 sh -c 'cat /etc/nginx/conf.d/default.conf'
```

### 查看 web 环境变量

```bash
docker exec umanewsbot-web-1 sh -c 'env | grep -E "^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)="'
```

### 查看日志

```bash
docker logs --tail=120 umanewsbot-web-1
docker logs --tail=120 umanewsbot-nginx-1
```

## 新闻抓取健康排查

### 后台入口

日常先看业务后台：

- `/admin/` 工作台的“最近来源状态”
- `/admin/sources/` 来源管理列表

重点确认：

- 最近抓取时间
- 运行状态
- 最近结果摘要
- 是否显示“运行中”“运行超时”“成功无新增”“失败”或“长时间未运行”

“成功无新增”表示抓取任务正常执行，但本轮抓到的文章都已存在；这不等同于抓取失败。
“运行中”表示最新抓取记录已开始但尚未写入最终结果；如运行中记录超过 60 分钟仍未完成，后台会显示“运行超时”，需要检查 worker / beat 日志和对应 `CrawlJob`。
“长时间未运行”只用于仍启用的来源；停用来源不纳入该告警。

### 服务器查询

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import CrawlJob; from django.utils import timezone; [print(timezone.localtime(j.started_at).strftime('%F %T'), j.source.name if j.source_id else '-', j.status, j.success_count, j.fail_count, (j.error_message or '')[:120]) for j in CrawlJob.objects.select_related('source').order_by('-started_at')[:20]]"
```

### 当前内置抓取频率

- netkeiba 新着顺：每小时 `00` 分抓取，周日重赏时段另有高频补抓。
- netkeiba 访问量榜：每小时 `16` 分抓取第一页。
- netkeiba 注目数榜：每小时 `26` 分抓取第一页。
- JRA 官方新闻：每 12 小时扫描当前月和上月。

部署涉及抓取调度变更后，必须重启 `beat / worker / web`，并在连续一个小时内确认 netkeiba 新着顺、访问量榜和注目数榜分别按 `00/16/26` 分生成错峰 `CrawlJob`；周日重赏高频补抓分钟不得与访问量榜 / 注目数榜重合。

### JRA 日期解析验收

如 JRA 曾出现 `time data '5月31日' does not match format '%Y年%m月%d日'`，部署后可以手动触发或等待下一次任务：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py crawl_news jra
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import CrawlJob, NewsSource; source=NewsSource.objects.get(source_site='jra', source_mode='official'); print(source.last_crawl_status, source.last_crawl_message); print(CrawlJob.objects.filter(source=source).order_by('-started_at').values('status','success_count','fail_count','error_message').first())"
```

若单篇 JRA 详情页结构异常，预期行为是跳过该篇、继续处理同轮其他新闻，并在 `last_crawl_message` / `CrawlJob.error_message` 中留下“跳过 N 条”摘要；列表页、网络或数据库异常仍按整轮失败排查。

## 赛事日历 / 年度赛事页运维

### 后台入口

- 业务后台：`/admin/race-events/`
- Django Admin 兜底：`/django-admin/stable/raceevent/`
- 前台赛事日历：`/races/`
- 前台年度赛事详情：`/races/<year>/<slug>/`

### CSV 种子导入

样例文件：

```bash
server/stable/data/race_events_seed_sample.csv
```

本地或生产容器内导入：

```bash
python manage.py import_race_events --csv server/stable/data/race_events_seed_sample.csv --dry-run
python manage.py import_race_events --csv server/stable/data/race_events_seed_sample.csv
```

CSV 导入只创建或更新 `RaceEvent` 与 `RaceEventAlias`，不会创建新闻，不会触发 QQ 推送。

### 候选资料抓取

指定网站或人工缓存的候选资料应先写入 JSON，再进入候选池：

```bash
python manage.py fetch_race_event_candidates --event-id <race_event_id> --source json --payload-file /path/to/candidate.json
```

候选资料只写入 `RaceEventDataCandidate`，不会自动覆盖公开字段。运营人员需要在 `/admin/race-events/<id>/` 中按模块应用。

### 赛中字段只读调研

赛中字段调研只记录 URL、样例和失败原因，不写入公开赛事状态或赛果：

```bash
python manage.py research_live_race_fields --url https://example.com/race-page
```

### 停用 / 回滚边界

- 前台可通过从导航移除 `/races/` 入口或把赛事 `visibility_status` 改为 `hidden` 临时下线。
- 候选抓取命令不应配置为常驻调度；如来源异常，停止执行命令即可。
- `RaceEvent` 数据不影响新闻抓取、翻译、自动发布或 QQ 推送主链路。
- 人工移除的 `ArticleRaceLink(status=removed)` 是保护记录，不应批量删除，否则自动关联可能重新出现。

## 2026-06-25 三个运营改造 change 合并、部署与归档

### 合并范围

- `codex/fix-crawl-freshness-and-health`：抓取新鲜度、JRA 日期解析、来源健康摘要和 netkeiba `00/16/26` 分错峰调度。
- `codex/add-selection-term-quick-add`：后台候选详情页 / 文章编辑台原文选区快速加入术语库。
- `codex/add-selection-term-quick-add` 后续提交：新增术语成功后的 15 秒一次性浮层，可点击后仅将该术语应用到当前文章已有中文字段。
- 注意：`fix-crawl-health-running-and-schedule-stagger` 是抓取 change 的后续返修 旧规格流程 目录，随抓取 change 一并归档。

### 部署前检查

- 服务器部署前 HEAD：`268100d`。
- 服务器工作树：干净。
- 外部导入锁：`ExternalDataImportLock.locked_by_run_id=None`。
- 最近外部导入 run：`run_id=120` 等均为 `paused`，没有运行中的长导入。

### 部署步骤与结果

- 本地发布分支从 `origin/main` 合并两个代码分支后推送到 `main`，合并后提交为 `7f54f13`。
- 部署前备份 `.env`：`.env.backup.three-changes-20260625_003714`。
- 服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main`，从 `268100d` 更新到 `7f54f13`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移结果：`No migrations to apply`。
- `collectstatic` 结果：`0 static files copied`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://127.0.0.1/`：`200`。
  - 运行态调度确认：`crawl-netkeiba-latest-hourly=00`，`crawl-netkeiba-access=16`，`crawl-netkeiba-attention=26`，三者 `crawl_interval_minutes=60`。

### 归档结果

- `旧规格流程/changes/archive/2026-06-24-fix-crawl-freshness-and-jra-date-parse/`
- `旧规格流程/changes/archive/2026-06-24-fix-crawl-health-running-and-schedule-stagger/`
- `旧规格流程/changes/archive/2026-06-24-add-selection-term-quick-add/`
- `旧规格流程/changes/archive/2026-06-24-reapply-terms-after-quick-add/`
- 正式规格已同步：
  - `旧规格流程/specs/crawl-freshness-and-source-health/spec.md`
  - `旧规格流程/specs/termbase-and-race-priority/spec.md`
- 归档后 `旧规格流程 validate --all` 通过。

### 后续观察

- 抓取错峰的“连续小时自然生成 `CrawlJob`”仍需等待调度运行后确认；本次已确认代码和运行时 Celery Beat 配置加载为 `00/16/26` 分。
- 如外部马名数据导入重新启动，继续遵守“导入期间不执行 `git pull / build / up / deploy_lowcost.sh`”的互斥规则。

## 2026-06-26 国际赛马资讯扩展部署

### 部署前检查

- 本地提交 `5865e58` 已推送到 `main`，分支 `codex/expand-international-racing-coverage` 保留远端备查。
- 本地验证通过：
  - `DB_ENGINE=sqlite ... server/manage.py check`
  - `DB_ENGINE=sqlite ... server/manage.py makemigrations --check --dry-run`
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true ... server/manage.py test stable --noinput`：241 项通过
  - `旧规格流程 validate expand-international-racing-coverage --strict`
  - `旧规格流程 validate --all`
  - `git diff --check`
- 生产部署前发现 `/opt/umanewsbot/imports/run_horse_import_202504_to_202406_20260626_083946.sh` 正在连续执行 netkeiba 外部马名导入。已等待当前批次完成并确认 `ExternalDataImportLock.locked_by_run_id=None` 后再部署；外层导入脚本已停止，避免继续自动开下一批。

### 部署步骤与结果

- 部署前服务器 HEAD：`2f0c35c`。
- 部署前备份 `.env`：`.env.backup.international-coverage-20260626_103923`。
- 服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main`，从 `2f0c35c` 更新到 `5865e58`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移状态：`stable.0011_remove_termcandidate_uq_term_candidate_type_normalized_and_more`、`0012_termalias`、`0013_alter_newsarticle_source_site_and_more` 均已应用。
- `collectstatic` 结果：`0 static files copied`，`129 unmodified`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://127.0.0.1/`：`200`。

### 来源灰度与首轮观察

- 部署后手动执行 `sync_builtin_sources()`，生产已创建 20 个内置来源。
- 已启用第一版来源：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing latest/access`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation latest/access`。
- 生产 `probe_international_news_sources` 验证中，除 `BHA official` 返回 `403` 外，其余第一版来源均能解析真实样本；`BHA` 已停用，后续再评估是否需要换请求策略或放弃。
- 测试 QQ 群 `1026525240` 已配置允许 `japan / hong_kong / united_kingdom / france / united_states` 五个地区，继续沿用全局 `QQ_PUSH_SCOPE` / `QQ_PUSH_IMPORTANCE_STRATEGY`。
- 已手动触发 12 个新增来源抓取任务；首轮观察中 `Sponichi latest` 已完成并入库 `13` 篇新稿、`7` 篇重复稿，`Sponichi access` 与 `HKJC Racing News` 已开始执行，其他国际来源仍在 worker 队列中等待。

### 后续观察

- 继续查看 `/admin/sources/` 和 `CrawlJob`，确认 `HKJC / SCMP / Sporting Life / Sky / France Galop / TDN / Horse Racing Nation` 依次完成首轮抓取。
- 抽检英文稿的翻译、术语别名命中、外部马名识别、自动发布门禁和公开地区 tab。
- 等自然公开/榜单提升后观察 QQ 测试群是否按地区配置推送；如刷屏或质量不稳，优先停用单个 `NewsSource` 或调整测试群 `allowed_regions`，不需要回滚代码。

## 自动化运营 MVP 部署与验证

### 关键环境变量

自动化能力通过 `.env` 控制，建议生产首次部署时先关闭：

```bash
AUTOMATION_ENABLED=false
AUTO_REVIEW_THRESHOLD=75
MANUAL_REVIEW_THRESHOLD=45
AUTO_REWRITE_ENABLED=false
AUTO_PUBLISH_CONTENT_SOURCE=base_translation
HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention
HIGH_VALUE_WARNING_SCORE_THRESHOLD=90
AUTO_DUPLICATE_LOOKBACK_DAYS=7
AUTO_DUPLICATE_HIGH_THRESHOLD=0.86
AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72
AUTO_PUBLISH_BATCH_LIMIT=4
AUTO_PUBLISH_PEAK_BATCH_LIMIT=10
AUTO_PUBLISH_PEAK_DAY_OF_WEEK=6
AUTO_PUBLISH_PEAK_START_HOUR=13
AUTO_PUBLISH_PEAK_END_HOUR=16
AUTO_PUBLISH_INTERVAL_MINUTES=15
REWRITE_CONFIDENCE_MIN=60
AUTO_PUBLISH_REQUIRE_COVER=false
REWRITE_PROVIDER=fallback
REWRITE_MODEL=deepseek-ai/DeepSeek-V3
REWRITE_MAX_TOKENS=2600
REWRITE_TIMEOUT_SECONDS=90
AUTOMATION_ENABLE_EMAIL=false
AUTOMATION_NOTIFY_EMAILS=
AUTOMATION_WARNING_EMAIL_ENABLED=true
AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com
AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24
```

`refine-automation-publish-gates` 实施后，短期建议保持 `AUTO_REWRITE_ENABLED=false` 和 `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`，先用基准翻译稿跑自动发布门禁。真实恢复 AI 改写时，按现有 OpenAI-compatible / SiliconFlow 配置补齐 Key，将 `AUTO_REWRITE_ENABLED=true`，并将 `AUTO_PUBLISH_CONTENT_SOURCE=rewrite`、`REWRITE_PROVIDER` 设置为对应 provider。

### 部署步骤

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

如生产使用标准 RDS 方案，将 compose 文件替换为 `docker-compose.prod.yml`。

### 验证自动化字段与迁移

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NewsArticle, AutomationLog, NotificationLog; print(NewsArticle.objects.count(), AutomationLog.objects.count(), NotificationLog.objects.count())"
```

验证门禁字段、重复状态和普通词种子：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NewsArticle, TermEntry, WorkflowStatus; print(hasattr(WorkflowStatus, 'DUPLICATE'), NewsArticle.objects.exclude(gate_issues=[]).count(), TermEntry.objects.filter(notes__icontains='non_horse_common_word').count())"
```

### 灰度启用自动化

先把 `.env` 中 `AUTOMATION_ENABLED` 改为 `true`，再重启相关容器：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
```

### 手动触发单篇自动化验证

进入后台候选新闻详情页，点击“重新自动化处理”；或在服务器执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import process_article_automation_task; process_article_automation_task.delay(ARTICLE_ID)"
```

将 `ARTICLE_ID` 替换为已翻译文章 ID。

自动化门禁优化上线后，单篇验证重点查看：

- 后台候选详情页是否展示 blocker / warning / info。
- `warning` 是否仍允许文章进入 `automation_status=publish_ready`。
- 高度重复文章是否进入 `workflow_status=duplicate`。
- 中等相似文章是否转入 `workflow_status=pending_review`。
- 高价值来源文章是否在评分阶段放行，但不绕过 blocker。

### 自动发布批次验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import auto_publish_batch_task; print(auto_publish_batch_task.delay(limit=1))"
docker logs --tail=120 umanewsbot-worker-1
```

验证后台“已发布内容”列表、前台首页和文章详情页是否出现自动发布稿。

### 自动发布批量规则验证

生产默认规则：

- 常规时段：每 15 分钟最多自动发布 4 篇
- 每周日北京时间 13:00-16:00：每 15 分钟最多自动发布 10 篇

检查运行时配置：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web sh -c 'env | grep -E "^(AUTO_PUBLISH_BATCH_LIMIT|AUTO_PUBLISH_PEAK_BATCH_LIMIT|AUTO_PUBLISH_PEAK_DAY_OF_WEEK|AUTO_PUBLISH_PEAK_START_HOUR|AUTO_PUBLISH_PEAK_END_HOUR|AUTO_PUBLISH_INTERVAL_MINUTES)="'
```

检查任务按当前时间解析出的批量上限：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import _resolve_auto_publish_batch_limit; print(_resolve_auto_publish_batch_limit())"
```

### 异常通知验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import send_notification_task; send_notification_task.delay('rewrite_failed', {'title': '通知测试', 'article_id': 1})"
```

如果邮件未启用，后台日志中应出现 `NotificationLog(status=skipped, channel=email)`；如果邮件已启用，应出现 `sent` 或具体失败原因。

### 高价值 warning 邮件验证

`warning` 初期不阻断自动发布，但高价值文章出现 warning 时应发送或跳过并留痕：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NotificationLog; print(NotificationLog.objects.filter(type='high_value_warning').order_by('-created_at').values('status','target','error_message')[:5])"
```

如果 `AUTOMATION_WARNING_EMAIL_ENABLED=true` 但没有配置 `AUTOMATION_WARNING_NOTIFY_EMAILS`，应看到 `status=skipped` 且自动发布不被阻断。同一文章同一 warning 组合 24 小时内重复触发时，也应记录 skipped 去重日志。

### 2026-06-24 自动发布门禁优化生产上线结果

- 部署 PR：#4 `[codex] refine automation publish gates`。
- 生产提交：`42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 生产灰度策略：`AUTO_REWRITE_ENABLED=false`，`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`，高价值 warning 邮件发送到 `754652181@qq.com`。
- 迁移：`stable.0009_automation_publish_gates` 已应用。
- 健康检查：`http://umafans.run/healthz/` 与 `/` 均返回 `200`，`web` 容器 healthy。
- 验收查询：`WorkflowStatus.DUPLICATE=True`，首批非马名普通词种子数量 `14`，`python manage.py check` 通过。
- 部署日志曾出现一次字段已存在异常，原因为容器启动迁移与手工迁移并发；后续 `showmigrations`、`check` 和健康检查均正常。

### 自动化排障顺序

1. 先查 `.env` 中 `AUTOMATION_ENABLED`、`AUTO_REWRITE_ENABLED`、`AUTO_PUBLISH_CONTENT_SOURCE`、阈值、邮件配置和模型配置
2. 再查 `beat` 是否加载 `auto-publish-batch` 与 `detect-automation-anomalies`
3. 查看 `worker` 日志是否有评分、改写、校验、发布异常
4. 后台文章详情页查看 `AutomationLog`
5. 后台操作日志页查看 `NotificationLog`
6. 如果内容质量不稳，先关闭 `AUTOMATION_ENABLED`，不要急着回滚代码

## QQ 群自动推送部署与验证

### 关键环境变量

自动 QQ 推送默认关闭，生产首次部署建议保持：

```bash
QQ_PUSH_ENABLED=false
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
QQ_PUSH_MIN_INTERVAL_SECONDS=60
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_ACCESS_TOKEN=
ONEBOT_TIMEOUT_SECONDS=30
```

`QQ_PUSH_SCOPE` 支持：

- `high_value_only`：默认，仅推重点新闻
- `all_public`：推所有公开 URL 可访问且无 blocker 的已发布文章

`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 是本期唯一支持的重点新闻口径：仅 `netkeiba:access` 与 `netkeiba:attention` 文章会被视为重点新闻。

### 部署步骤

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 配置群目标

进入 Django Admin：

```text
/django-admin/stable/pushtarget/
```

配置 `name`、`group_id`，并将测试群设为 `is_active=true`。自动推送只看 `is_active`，`is_default` 仅用于手动推送默认群。

### OneBot 网关安全边界

OneBot API 不得公网裸露。推荐 Docker 内网访问：

```env
ONEBOT_BASE_URL=http://onebot:3000
```

如果临时映射到宿主机，只允许：

```yaml
ports:
  - "127.0.0.1:3000:3000"
```

不要使用公网 `0.0.0.0:3000:3000`。

### 灰度启用

确认测试群和 OneBot 网关可用后，把 `.env` 改为：

```bash
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
```

重启 worker / beat：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

### 验收命令

检查配置：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec worker sh -c 'env | grep -E "^(QQ_PUSH_ENABLED|QQ_PUSH_SCOPE|QQ_PUSH_IMPORTANCE_STRATEGY|QQ_PUSH_MAX_ATTEMPTS|QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS|QQ_PUSH_SENDING_STALE_SECONDS|QQ_PUSH_MIN_INTERVAL_SECONDS|ONEBOT_BASE_URL|ONEBOT_TIMEOUT_SECONDS)="'
```

查看交付记录：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import QQPushDelivery; print(QQPushDelivery.objects.order_by('-created_at').values('id','article_id','target_id','status','attempt_count','last_error_type')[:10])"
```

检查 OneBot 登录状态：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.services.onebot import BotPusher; print(BotPusher().is_online())"
```

预期返回 `(True, '')`。若返回 `onebot_offline` 或 `onebot_status_check_failed`，自动推送会暂停真实发送并记录错误摘要，不会调用 `/send_group_msg`，也不会增加 `QQPushDelivery.attempt_count`。

查看 worker 日志：

```bash
docker logs --tail=160 umanewsbot-worker-1
```

抽检公开文章 ID URL：

```bash
ARTICLE_ID=$(docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import NewsArticle, WorkflowStatus; article = NewsArticle.objects.filter(workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False).order_by('-published_to_web_at', '-id').first(); print(article.id if article else '')")
curl -I "http://127.0.0.1/news/${ARTICLE_ID}/"
```

预期 `/news/<article_id>/` 返回 `200`；非纯数字旧 `/news/<slug>/` 若能查到已发布文章，应返回 `302` 并跳转到对应 ID URL。QQ 自动推送消息中的 `阅读全文` 链接同样应为 `SITE_URL/news/<article_id>/`。

后台排查入口：

```text
/django-admin/stable/qqpushdelivery/
```

### 停用和回滚

最快停用方式：

```bash
QQ_PUSH_ENABLED=false
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

停用自动 QQ 推送不会影响公开网站、自动发布或后台手动推送。若 OneBot 网关异常，可先停掉 OneBot 容器或把目标群 `is_active=false`。

如果 NapCat 日志出现“登录态已失效，请重新登录”或 `/get_status` 返回 `online=false`，先按上面的停用方式暂停自动推送，再通过 NapCat WebUI 或新的登录二维码完成 QQ 重新登录。登录后必须重新执行 OneBot 在线检查、测试群短消息和 worker 环境变量检查，再恢复 `QQ_PUSH_ENABLED=true`。

## 专有术语候选发现灰度部署

## 正式术语库恢复与赛事等级修复部署

### 适用场景

用于修复正式术语库缺失、马名或比赛名翻译未命中、赛事等级识别不足导致自动评分偏低的问题。本流程覆盖：

- 正式术语 `race_grade` 字段迁移
- 术语候选池基础内容字段迁移
- 正式术语种子数据 dry-run 与导入
- 执行日 0:00 后候选新闻池批量验收

### 部署前备份

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
mkdir -p backups
docker compose -f docker-compose.prod.lowcost.yml exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backups/pre-termbase-race-grade-$(date +%Y%m%d_%H%M%S).sql
```

如生产使用标准 Compose 文件，将 `docker-compose.prod.lowcost.yml` 替换为 `docker-compose.prod.yml`。

### 部署与迁移

```bash
cd /opt/umanewsbot
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 术语导入 dry-run

默认种子文件位于容器内 `server/stable/data/terms_seed.csv`。先执行预检：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms --dry-run
```

确认输出中的错误数量为 `0`。若生产已经存在部分术语，默认 `upsert` 会显示更新数量；如需严格新增模式，可显式执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms --dry-run --mode create
```

### 正式导入术语

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms
```

如需导入本地整理好的 CSV，先上传到服务器，再复制进 `web` 容器可见路径后执行 dry-run 与正式导入：

```bash
cd /opt/umanewsbot
mkdir -p imports/terms-<批次>
scp <本地CSV> root@<服务器IP>:/opt/umanewsbot/imports/terms-<批次>/
docker compose -f docker-compose.prod.lowcost.yml exec -T web mkdir -p /tmp/terms
docker cp imports/terms-<批次>/<文件名>.csv umanewsbot-web-1:/tmp/terms/
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_terms /tmp/terms/<文件名>.csv --dry-run
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_terms /tmp/terms/<文件名>.csv
```

## 术语种子数据准备部署与验证

### 适用场景

用于上线 `prepare_termbase_seed_data` 管理命令和 HKJC/WP Stud 术语种子候选生成能力。该能力只生成本地审核文件，不直接写入 `TermEntry`、`TermAlias`、`TermCandidate`、`ExternalHorse` 或 `ExternalHorseAlias`。

### 部署步骤

本能力新增 Python 依赖，生产部署必须重建 `web / worker / beat` 镜像：

```bash
cd /opt/umanewsbot
cp .env .env.backup.termbase-seed-$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py migrate --noinput
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
```

### 生产 smoke 验证

先使用内置 fixture 生成一批不触网的候选文件：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py prepare_termbase_seed_data \
  --source hkjc \
  --source wpstud \
  --output-dir /tmp/termbase_seed_smoke
```

预期结果：

- `seed_candidates.csv`、`seed_conflicts.csv`、`summary.json` 均生成。
- 内置 fixture smoke 应生成 `10` 条候选和 `1` 条冲突。
- 命令不修改正式术语库、候选池、外部马名索引，也不派发翻译、自动发布或 QQ 推送任务。

### 本次执行记录（2026-07-04）

- 服务器 `/opt/umanewsbot` 从 `4323d32` 快进到 `e81733f`。
- 部署前备份 `.env`：`.env.backup.termbase-seed-20260704_012005`。
- 本次新增依赖 `opencc-python-reimplemented==0.1.7`，已重建并重启 `web / worker / beat`。
- 迁移结果：`No migrations to apply`。
- `python manage.py check`：通过，`0` issues。
- 生产 smoke：`candidate_count=10`、`conflict_count=1`、`incomplete=false`、`dry_run_error_count=0`，首条候选 `BEAUTY GENERATION`，末条候选 `ディープインパクト`。
- 健康检查：`http://127.0.0.1/healthz/` 与 `http://umafans.run/healthz/` 均返回 `200`。
- 本次只上线种子准备命令和审核文件生成能力，未导入正式术语，未写 `TermEntry`、`TermAlias`、`TermCandidate` 或外部马名索引。

### 第一批正式术语导入记录（2026-07-04）

- 导入文件：`/opt/umanewsbot/imports/termbase-seed-fixture-review-20260704_024950/seed_candidates.csv`。
- 数据库备份：`backups/db/pre-termbase-seed-import-20260704_030722.sql.gz`，已通过 `gzip -t`。
- dry-run：总计 `10` 条，新增 `8` 条，更新 `2` 条，错误 `0` 条。
- 正式导入：总计 `10` 条，新增 `8` 条，更新 `2` 条，跳过 `0` 条。
- 导入后计数：`TermEntry=2062`、`TermAlias=2068`；按原文语言分布为 `en=8`、`ja=2054`。
- 新增英文术语：`BEAUTY GENERATION`、`KA YING RISING`、`ROMANTIC WARRIOR`、`Hong Kong Cup`、`Zac Purton`、`John Size`、`Sha Tin`、`Declared Starter`。
- 首次导入时本批地区证据只保留在 `notes` 的 `region=hk`，未写入 `TermEntry.racing_region`；随后已执行地区补写 upsert。
- 地区补写备份：`backups/db/pre-termbase-seed-region-upsert-20260704_031950.sql.gz`。
- 地区补写注意：`racing_region` 必须使用模型合法值，例如 `hong_kong`、`japan`，不能使用短码 `hk`、`jp`。短码版本 dry-run 会被“地区不合法”阻断且不会写库。
- 地区补写结果：改用 `hong_kong/japan` 后 dry-run 为总计 `10` 条、更新 `10` 条、错误 `0` 条；正式 upsert 为更新 `10` 条、跳过 `0` 条。补写后分布为 `en/hong_kong=8`、`ja/japan=2`、既有旧日文术语空地区 `2052`。
- 导入后 `http://umafans.run/healthz/` 返回 `200`。

### WP Stud 第一批全量审核候选记录（2026-07-04）

- 本地审核目录：`runtime/termbase_seed/wpstud-full-review-20260704/`。
- 审核文件：`seed_candidates.csv`、`seed_candidates_with_region.csv`、`seed_conflicts.csv`、`summary.json`。
- 生成结果：候选 `210` 条、冲突 `0` 条、`incomplete=false`；全部为 `term_type=horse`、`source_language=ja`、`source_tier=community`、`requires_review=true`，中文译名已简体化。
- 带地区导入候选：`seed_candidates_with_region.csv`，统一设置 `racing_region=hong_kong`，用于描述香港或海外来港赛马候选。
- 生产导入文件：`/opt/umanewsbot/imports/wpstud-full-review-20260704/seed_candidates_with_region.csv`。
- 生产 dry-run 结果：总计 `210` 条，新增 `210` 条，更新 `0` 条，错误 `0` 条。
- 数据库备份：`backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，已通过 `gzip -t`。
- 正式导入结果：总计 `210` 条，新增 `210` 条，更新 `0` 条，跳过 `0` 条。
- 当前状态：已正式导入。本批是社区来源，后续若发现与 HKJC 官方译名冲突，应以 HKJC 作为主译名，WP Stud 作为别名或证据处理。
- HKJC 后续注意：真实 HKJC 页面当前可访问并返回 `200`；本地已补专用抽取路径，从 `selecthorse` 发现字母页、从字母页拿 `horseid + 英文名`，再抓繁中马匹详情页对齐中文名。小批命令应使用 `--limit-horses` 控制马匹详情页数量，并继续用 `--max-requests` 做硬上限。

### HKJC 真实页面术语种子小批 smoke（2026-07-04）

本地真实 smoke 命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --limit-horses 3 \
  --max-requests 10 \
  --request-interval-seconds 0 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-live-smoke-20260704
```

结果：

- `candidate_count=3`、`conflict_count=0`、`request_count=5`、`incomplete=false`。
- 请求链路为 `selecthorse -> selecthorsebychar?ordertype=A -> 3` 个 `zh-hk/local/information/horse?horseid=...` 详情页，全部返回 `200`。
- 生成样例：`AERIS NOVA -> 风再起时`、`AERODYNAMICS -> 友莹光`、`AWESOME FLUKE -> 非惟侥幸`。
- 本次只生成本地审核文件，未写正式术语库。生产执行时仍应先低频、带 `--limit-horses`，并在审核 CSV 后再走 `import_terms --dry-run` 与正式导入。

### HKJC 第一批正式候选抓取记录（2026-07-04）

本地低频命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --limit-horses 100 \
  --max-requests 130 \
  --request-interval-seconds 2 \
  --timeout-seconds 25 \
  --output-dir runtime/termbase_seed/hkjc-formal-review-20260704_100horses
```

结果：

- 审核目录：`runtime/termbase_seed/hkjc-formal-review-20260704_100horses/`。
- `seed_candidates.csv` 已直接包含 `racing_region` 列，HKJC 候选使用模型合法值 `hong_kong`。
- `candidate_count=100`、`conflict_count=0`、`request_count=103`、`incomplete=false`。
- 请求链路覆盖 `selecthorse`、`selecthorsebychar?ordertype=A/B` 和 `100` 个 `zh-hk/local/information/horse?horseid=...` 详情页，全部返回 `200`。
- 候选分布：`horse=100`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`。
- 抽检样例：`A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`。
- 临时 SQLite 迁移库导入预检：`import_terms --dry-run` 显示总计 `100` 条、新增 `100` 条、更新 `0` 条、错误 `0` 条。
- 当前状态：本批尚未导入生产正式术语库，也尚未部署 HKJC 抽取代码到生产。

### HKJC 主审核候选扩展批次（2026-07-04）

用户要求“多来一些，一起审核”后，已生成更大的 HKJC 主审核文件；该文件覆盖前一份 `100` 条小批，审核时优先使用本批：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --limit-horses 500 \
  --max-requests 560 \
  --request-interval-seconds 1.5 \
  --timeout-seconds 25 \
  --output-dir runtime/termbase_seed/hkjc-formal-review-20260704_500horses
```

结果：

- 审核目录：`runtime/termbase_seed/hkjc-formal-review-20260704_500horses/`。
- `candidate_count=500`、`conflict_count=0`、`request_count=509`、`incomplete=false`。
- 所有请求均返回 `200`，无 `failures`。
- CSV 抽检：`500` 条唯一英文马名，全部为 `term_type=horse`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`。
- 抽检样例：`A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`；末段覆盖到 `HYMNBOOK -> 北斗福星`。
- 生产 dry-run：总计 `500` 条，新增 `500` 条，更新 `0` 条，错误 `0` 条。
- 数据库备份：`backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，已通过 `gzip -t`。
- 正式导入结果：总计 `500` 条，新增 `500` 条，更新 `0` 条，跳过 `0` 条。

### HKJC 本地马 A-Z 字母拆批导入记录（2026-07-04）

全量无 checkpoint 抓取运行过久后，已新增 `--hkjc-letter` 参数并改为按 A-Z 字母拆批。每个字母段均使用如下模式：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews_hkjc_letter.sqlite3 CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --hkjc-letter <A-Z> \
  --max-requests 600 \
  --request-interval-seconds 0.15 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-formal-review-20260704_letter_<A-Z>
```

字母段生成结果：

- `A=60`、`B=54`、`C=103`、`D=43`、`E=32`、`F=70`、`G=87`、`H=56`
- `I=28`、`J=23`
- `K=42`、`L=68`、`M=84`、`N=33`、`O=12`、`P=72`、`Q=7`、`R=52`、`S=162`、`T=70`、`U=5`、`V=32`、`W=44`、`X=0`、`Y=14`、`Z=4`
- 所有字母段均为 `incomplete=false`、`failures=0`。

生产导入：

- `I` 批：生产 dry-run 总计 `28`、新增 `28`、错误 `0`；备份 `backups/db/pre-hkjc-letter-I-term-import-20260704_185212.sql.gz`；正式导入新增 `28`。
- `J` 批：生产 dry-run 总计 `23`、新增 `23`、错误 `0`；备份 `backups/db/pre-hkjc-letter-J-term-import-20260704_185400.sql.gz`；正式导入新增 `23`。
- `K-Z` 合并批：生产 dry-run 总计 `701`、新增 `699`、更新 `2`、错误 `0`；备份 `backups/db/pre-hkjc-letters-K-Z-term-import-20260704_191425.sql.gz`；正式导入新增 `699`、更新 `2`。
- `A-H` 合并复跑批：生产 dry-run 总计 `505`、新增 `5`、更新 `500`、错误 `0`；备份 `backups/db/pre-hkjc-letters-A-H-term-import-20260704_192843.sql.gz`；正式导入新增 `5`、更新 `500`。

导入后生产计数：`TermEntry=3527`、`TermAlias=3743`；`source_language=en/racing_region=hong_kong` 合计 `1263` 条，其中 HKJC 当前本地马英文术语 `1258` 条。`http://umafans.run/healthz/` 返回 `200`。

### HKJC 本地赛果回溯术语导入记录（2026-07-04）

本轮新增 HKJC 本地赛果术语抽取参数，用于按日期范围抓取 `en-us` / `zh-hk` 赛果页并对齐输出 `horse`、`jockey` 和 `race` 候选：

```bash
.venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 0 \
  --hkjc-skip-horse-details \
  --hkjc-local-results-start-date 2024-01-01 \
  --hkjc-local-results-end-date 2024-01-31 \
  --max-requests 260 \
  --request-interval-seconds 0.2 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-local-results-202401
```

实现细节：

- HKJC 赛日首页通常直接显示第 1 场，只给第 2 场之后的链接；生成器会根据同一赛日同一马场链接自动补抓 `RaceNo=1`。
- HKJC 下拉列表不会稳定覆盖 2024 年初旧赛日；生成器会把 landing 赛日与日期范围逐日探测合并去重，以支持 2024-01-01 起回溯。
- 补历史赛果时应使用 `--limit-pages 0 --hkjc-skip-horse-details`，避免每个月重复抓取当前本地马详情页。
- 单次网络异常会重试一次；最终失败才写入 `failures` 并标记 `incomplete=true`。
- 若 HKJC 双语页面都能访问但没有赛果主体表，生成器记录为 `skipped_races/local_result_not_available`，不导入空数据，也不单独阻断整月。

生产导入：

- `2024-01`：原始批次 `runtime/termbase_seed/hkjc-local-results-202401/` 因 `2024-01-24 ST Race 1` 繁中页一次超时而 `incomplete=true`；单日重跑 `runtime/termbase_seed/hkjc-local-results-20240124-retry/` 成功后，合并去重为 `runtime/termbase_seed/hkjc-local-results-202401-complete/seed_candidates.csv`。合并候选 `864` 条（`horse=761`、`race=79`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202401-complete/seed_candidates.csv`；dry-run 总计 `864`、新增 `710`、更新 `154`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202401-term-import-20260704_200627.sql.gz` 通过 `gzip -t`；正式导入新增 `710`、更新 `154`、跳过 `0`。
- `2024-02`：输出 `runtime/termbase_seed/hkjc-local-results-202402/seed_candidates.csv`，候选 `828` 条（`horse=736`、`race=68`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202402/seed_candidates.csv`；dry-run 总计 `828`、新增 `163`、更新 `665`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202402-term-import-20260704_201806.sql.gz` 通过 `gzip -t`；正式导入新增 `163`、更新 `665`、跳过 `0`。
- `2024-03`：输出 `runtime/termbase_seed/hkjc-local-results-202403/seed_candidates.csv`，候选 `883` 条（`horse=777`、`race=79`、`jockey=27`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202403/seed_candidates.csv`；dry-run 总计 `883`、新增 `137`、更新 `746`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202403-term-import-20260704_202942.sql.gz` 通过 `gzip -t`；正式导入新增 `137`、更新 `746`、跳过 `0`。
- `2024-04`：输出 `runtime/termbase_seed/hkjc-local-results-202404/seed_candidates.csv`，候选 `839` 条（`horse=740`、`race=68`、`jockey=31`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202404/seed_candidates.csv`；dry-run 总计 `839`、新增 `126`、更新 `713`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202404-term-import-20260704_204225.sql.gz` 通过 `gzip -t`；正式导入新增 `126`、更新 `713`、跳过 `0`。
- `2024-05`：输出 `runtime/termbase_seed/hkjc-local-results-202405/seed_candidates.csv`，候选 `842` 条（`horse=740`、`race=78`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202405/seed_candidates.csv`；dry-run 总计 `842`、新增 `113`、更新 `729`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202405-term-import-20260704_205324.sql.gz` 通过 `gzip -t`；正式导入新增 `113`、更新 `729`、跳过 `0`。
- `2024-06`：输出 `runtime/termbase_seed/hkjc-local-results-202406/seed_candidates.csv`，候选 `782` 条（`horse=697`、`race=62`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202406/seed_candidates.csv`；dry-run 总计 `782`、新增 `92`、更新 `690`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202406-term-import-20260704_210352.sql.gz` 通过 `gzip -t`；正式导入新增 `92`、更新 `690`、跳过 `0`。
- `2024-07`：输出 `runtime/termbase_seed/hkjc-local-results-202407/seed_candidates.csv`，候选 `647` 条（`horse=575`、`race=49`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202407/seed_candidates.csv`；dry-run 总计 `647`、新增 `74`、更新 `573`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202407-term-import-20260704_211425.sql.gz` 通过 `gzip -t`；正式导入新增 `74`、更新 `573`、跳过 `0`。
- `2024-08`：输出 `runtime/termbase_seed/hkjc-local-results-202408/`，逐日扫描 `32` 个请求，候选 `0`、冲突 `0`、失败 `0`、`incomplete=false`；本月无需生产导入。
- `2024-09`：输出 `runtime/termbase_seed/hkjc-local-results-202409/seed_candidates.csv`，候选 `626` 条（`horse=549`、`race=54`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202409/seed_candidates.csv`；dry-run 总计 `626`、新增 `62`、更新 `564`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202409-term-import-20260704_213327.sql.gz` 通过 `gzip -t`；正式导入新增 `62`、更新 `564`、跳过 `0`。
- `2024-10`：输出 `runtime/termbase_seed/hkjc-local-results-202410/seed_candidates.csv`，候选 `834` 条（`horse=735`、`race=75`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202410/seed_candidates.csv`；dry-run 总计 `834`、新增 `104`、更新 `730`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202410-term-import-20260704_214522.sql.gz` 通过 `gzip -t`；正式导入新增 `104`、更新 `730`、跳过 `0`。
- `2024-11`：输出 `runtime/termbase_seed/hkjc-local-results-202411/seed_candidates.csv`，候选 `850` 条（`horse=757`、`race=69`、`jockey=24`）。首次生成时 `2024-11-13 HV Race 7-9` 页面返回双语空壳赛果页，修复后重跑记录为 `skipped_races/local_result_not_available` 且 `incomplete=false`；生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202411/seed_candidates.csv`；dry-run 总计 `850`、新增 `97`、更新 `753`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202411-term-import-20260704_221006.sql.gz` 通过 `gzip -t`；正式导入新增 `97`、更新 `753`、跳过 `0`。
- `2024-12`：输出 `runtime/termbase_seed/hkjc-local-results-202412/seed_candidates.csv`，候选 `957` 条（`horse=832`、`race=78`、`jockey=47`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202412/seed_candidates.csv`；dry-run 总计 `957`、新增 `135`、更新 `822`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202412-term-import-20260704_222551.sql.gz` 通过 `gzip -t`；正式导入新增 `135`、更新 `822`、跳过 `0`。
- `2025-01`：输出 `runtime/termbase_seed/hkjc-local-results-202501/seed_candidates.csv`，候选 `913` 条（`horse=804`、`race=78`、`jockey=31`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202501/seed_candidates.csv`；dry-run 总计 `913`、新增 `73`、更新 `840`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202501-term-import-20260704_224151.sql.gz` 通过 `gzip -t`；正式导入新增 `73`、更新 `840`、跳过 `0`。
- `2025-02`：输出 `runtime/termbase_seed/hkjc-local-results-202502/seed_candidates.csv`，候选 `794` 条（`horse=703`、`race=60`、`jockey=31`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202502/seed_candidates.csv`；dry-run 总计 `794`、新增 `38`、更新 `756`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202502-term-import-20260704_225443.sql.gz` 通过 `gzip -t`；正式导入新增 `38`、更新 `756`、跳过 `0`。
- `2025-03`：输出 `runtime/termbase_seed/hkjc-local-results-202503/seed_candidates.csv`，候选 `914` 条（`horse=803`、`race=78`、`jockey=33`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202503/seed_candidates.csv`；dry-run 总计 `914`、新增 `30`、更新 `884`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202503-term-import-20260704_231134.sql.gz` 通过 `gzip -t`；正式导入新增 `30`、更新 `884`、跳过 `0`。
- `2025-04`：输出 `runtime/termbase_seed/hkjc-local-results-202504/seed_candidates.csv`，候选 `893` 条（`horse=782`、`race=78`、`jockey=33`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202504/seed_candidates.csv`；dry-run 总计 `893`、新增 `58`、更新 `835`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202504-term-import-20260704_232559.sql.gz` 通过 `gzip -t`；正式导入新增 `58`、更新 `835`、跳过 `0`。
- `2025-05`：输出 `runtime/termbase_seed/hkjc-local-results-202505/seed_candidates.csv`，候选 `920` 条（`horse=816`、`race=79`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202505/seed_candidates.csv`；dry-run 总计 `920`、新增 `38`、更新 `882`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202505-term-import-20260704_234206.sql.gz` 通过 `gzip -t`；正式导入新增 `38`、更新 `882`、跳过 `0`。
- `2025-06`：输出 `runtime/termbase_seed/hkjc-local-results-202506/seed_candidates.csv`，候选 `826` 条（`horse=741`、`race=63`、`jockey=22`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202506/seed_candidates.csv`；dry-run 总计 `826`、新增 `44`、更新 `782`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202506-term-import-20260704_235659.sql.gz` 通过 `gzip -t`；正式导入新增 `44`、更新 `782`、跳过 `0`。
- `2025-07`：输出 `runtime/termbase_seed/hkjc-local-results-202507/seed_candidates.csv`，候选 `675` 条（`horse=603`、`race=49`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202507/seed_candidates.csv`；dry-run 总计 `675`、新增 `19`、更新 `656`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202507-term-import-20260705_000915.sql.gz` 通过 `gzip -t`；正式导入新增 `19`、更新 `656`、跳过 `0`。

`2025-08`：输出 `runtime/termbase_seed/hkjc-local-results-202508/`，逐日扫描请求 `32` 次，候选 `0`、冲突 `0`、失败 `0`、`incomplete=false`，无需导入。
- `2025-09`：输出 `runtime/termbase_seed/hkjc-local-results-202509/seed_candidates.csv`，候选 `632` 条（`horse=560`、`race=49`、`jockey=23`）。`2025-09-21 ST Race 9-10` 页面返回双语空壳赛果页，记录为 `skipped_races/local_result_not_available` 且 `incomplete=false`；生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202509/seed_candidates.csv`；dry-run 总计 `632`、新增 `17`、更新 `615`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202509-term-import-20260705_002604.sql.gz` 通过 `gzip -t`；正式导入新增 `17`、更新 `615`、跳过 `0`。
- `2025-10`：输出 `runtime/termbase_seed/hkjc-local-results-202510/seed_candidates.csv`，候选 `882` 条（`horse=786`、`race=73`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202510/seed_candidates.csv`；dry-run 总计 `882`、新增 `41`、更新 `841`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202510-term-import-20260705_004245.sql.gz` 通过 `gzip -t`；正式导入新增 `41`、更新 `841`、跳过 `0`。
- `2025-11`：输出 `runtime/termbase_seed/hkjc-local-results-202511/seed_candidates.csv`，候选 `933` 条（`horse=826`、`race=81`、`jockey=26`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202511/seed_candidates.csv`；dry-run 总计 `933`、新增 `45`、更新 `888`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202511-term-import-20260705_010022.sql.gz` 通过 `gzip -t`；正式导入新增 `45`、更新 `888`、跳过 `0`。
- `2025-12`：输出 `runtime/termbase_seed/hkjc-local-results-202512/seed_candidates.csv`，候选 `912` 条（`horse=803`、`race=68`、`jockey=41`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202512/seed_candidates.csv`；dry-run 总计 `912`、新增 `42`、更新 `870`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202512-term-import-20260705_011812.sql.gz` 通过 `gzip -t`；正式导入新增 `42`、更新 `870`、跳过 `0`。
- `2026-01`：输出 `runtime/termbase_seed/hkjc-local-results-202601/seed_candidates.csv`，候选 `978` 条（`horse=875`、`race=78`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202601/seed_candidates.csv`；dry-run 总计 `978`、新增 `28`、更新 `950`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202601-term-import-20260705_013522.sql.gz` 通过 `gzip -t`；正式导入新增 `28`、更新 `950`、跳过 `0`。
- `2026-02`：输出 `runtime/termbase_seed/hkjc-local-results-202602/seed_candidates.csv`，候选 `930` 条（`horse=836`、`race=69`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202602/seed_candidates.csv`；dry-run 总计 `930`、新增 `18`、更新 `912`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202602-term-import-20260705_015108.sql.gz` 通过 `gzip -t`；正式导入新增 `18`、更新 `912`、跳过 `0`。
- `2026-03`：输出 `runtime/termbase_seed/hkjc-local-results-202603/seed_candidates.csv`，候选 `944` 条（`horse=838`、`race=81`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202603/seed_candidates.csv`；dry-run 总计 `944`、新增 `18`、更新 `926`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202603-term-import-20260705_020814.sql.gz` 通过 `gzip -t`；正式导入新增 `18`、更新 `926`、跳过 `0`。
- `2026-04`：输出 `runtime/termbase_seed/hkjc-local-results-202604/seed_candidates.csv`，候选 `975` 条（`horse=859`、`race=83`、`jockey=33`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202604/seed_candidates.csv`；dry-run 总计 `975`、新增 `41`、更新 `934`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202604-term-import-20260705_022703.sql.gz` 通过 `gzip -t`；正式导入新增 `41`、更新 `934`、跳过 `0`。
- `2026-05`：输出 `runtime/termbase_seed/hkjc-local-results-202605/seed_candidates.csv`，候选 `979` 条（`horse=873`、`race=80`、`jockey=26`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202605/seed_candidates.csv`；dry-run 总计 `979`、新增 `33`、更新 `946`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202605-term-import-20260705_024451.sql.gz` 通过 `gzip -t`；正式导入新增 `33`、更新 `946`、跳过 `0`。
- `2026-06`：输出 `runtime/termbase_seed/hkjc-local-results-202606/seed_candidates.csv`，候选 `844` 条（`horse=757`、`race=63`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202606/seed_candidates.csv`；dry-run 总计 `844`、新增 `20`、更新 `824`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202606-term-import-20260705_025830.sql.gz` 通过 `gzip -t`；正式导入新增 `20`、更新 `824`、跳过 `0`。
- `2026-07-01` 至 `2026-07-04`：输出 `runtime/termbase_seed/hkjc-local-results-20260701-20260704/seed_candidates.csv`，候选 `310` 条（`horse=265`、`race=21`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-20260701-20260704/seed_candidates.csv`；dry-run 总计 `310`、新增 `5`、更新 `305`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-20260701-20260704-term-import-20260705_030505.sql.gz` 通过 `gzip -t`；正式导入新增 `5`、更新 `305`、跳过 `0`。

导入后生产计数：`TermEntry=5948`、`TermAlias=6164`；`source_language=en/racing_region=hong_kong` 分布为 `horse=2479`、`jockey=70`、`race=1132`，另保留既有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`。`http://127.0.0.1/healthz/` 返回 `200`。HKJC 香港本地赛果已回溯到 `2026-07-04`；仍需继续 HKJC overseas 与 WP Stud 赛事/骑手缺口。

### HKJC overseas live dry-run 记录（2026-07-04）

本地低上限 live dry-run 命令如下；本次只触网读取 HKJC overseas 入口页并生成审核产物，不写正式术语库、不部署生产：

```bash
tmp_db="/tmp/umanews_hkjc_overseas_live_$(date +%Y%m%d_%H%M%S).sqlite3"
out_dir="runtime/termbase_seed/hkjc-overseas-live-smoke-$(date +%Y%m%d_%H%M%S)"
DB_ENGINE=sqlite SQLITE_DB_PATH="$tmp_db" .venv/bin/python server/manage.py migrate --noinput
DB_ENGINE=sqlite SQLITE_DB_PATH="$tmp_db" .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc_overseas \
  --allow-network \
  --limit-meetings 1 \
  --limit-races 1 \
  --max-requests 6 \
  --request-interval-seconds 3 \
  --timeout-seconds 15 \
  --output-dir "$out_dir"
```

结果：

- 审核目录：`runtime/termbase_seed/hkjc-overseas-live-smoke-20260704_174924/`。
- `candidate_count=0`、`conflict_count=0`、`skipped_races=0`、`request_count=1`、`dry_run_error_count=0`。
- 请求 `https://racing.hkjc.com/en-us/overseas/` 返回 `200`。
- `incomplete=true`，失败类型为 `render_fallback_unavailable`，原因是直接 HTML 中没有 Race Card 链接。
- 结论：当前代码能安全暴露 HKJC overseas 的 Next.js shell 边界，不会把空 HTML 当作成功空结果；如需稳定生成海外 Race Card 候选，下一步应补浏览器渲染缓存或解析 HKJC 前端 API，再重新执行小批 live dry-run。

### HKJC overseas QIDS 回溯与生产导入记录（2026-07-05）

本轮未部署新的生成器代码到生产；生成器在本地通过 HKJC QIDS GraphQL 抽取海外 Race Card 中英对照，产物审核后上传生产并使用既有 `import_terms` 导入。

本地生成范围：

- 日期范围：`2024-01-01` 至 `2026-07-04`。
- 月度目录：`runtime/termbase_seed/hkjc-overseas-qids-YYYYMM/`。
- 合并目录：`runtime/termbase_seed/hkjc-overseas-qids-merged-20240101-20260704/`。
- 合并结果：原始行 `11633`、候选 `7691`、冲突 `3`、`incomplete=false`。
- 候选类型：`horse=6481`、`jockey=847`、`race=363`。

生产导入：

- 生产文件：`/opt/umanewsbot/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`。
- 容器文件：`/app/server/runtime/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`。
- dry-run：总计 `7691`、新增 `7688`、更新 `3`、错误 `0`。
- 备份：`backups/db/pre-hkjc-overseas-qids-term-import-20260705_040238.sql.gz`，已通过 `gzip -t`。
- 正式导入：总计 `7691`、新增 `7482`、更新 `209`、跳过 `0`。

导入后发现当前 `import_terms` 的 upsert 身份是 `term_type + source_language + source_ja`，不会按 `racing_region` 拆分；同名国际骑师会被后导入来源更新地区。为保留香港本地赛果骑师地区，已执行 HKJC 本地骑师地区恢复：

- 恢复文件：`runtime/termbase_seed/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv`。
- 生产文件：`/opt/umanewsbot/imports/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv`。
- dry-run：总计 `69`、新增 `0`、更新 `69`、错误 `0`。
- 备份：`backups/db/pre-hkjc-local-jockey-region-restore-20260705_040950.sql.gz`，已通过 `gzip -t`。
- 正式导入：总计 `69`、新增 `0`、更新 `69`、跳过 `0`。

恢复后核验：

- `TermEntry=13430`、`TermAlias=13646`。
- HKJC overseas 官方来源计数：`7483`。
- `source_language=en/racing_region=hong_kong`：`horse=2479`、`jockey=69`、`race=1132`，另有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`。
- `http://127.0.0.1/healthz/` 返回 `200`。

注意：共享国际骑师当前只能作为同一个英文源术语存在，不能同时保留多个地区版本；这不会影响英文原文命中和中文译名应用，但地区统计需要按当前主记录解释。

### WP Stud 赛事/骑师/马场生产导入记录（2026-07-05）

本轮继续处理当前发现的 WP Stud 赛事、骑师和马场页面。WP Stud 属社区来源，导入时必须避免覆盖 HKJC 官方主译名。

本地生成：

- 缓存目录：`runtime/termbase_seed/source_cache_wpstud_extra_20260705/`。
- 输出目录：`runtime/termbase_seed/wpstud-race-jockey-racecourse-review-20260705/`。
- 来源：`Translation/Race` 目录下 `21` 个赛事页面、`Translation/jockey.htm`、`Translation/racecourse/RaceCourse.htm`。
- 完整候选：`2095` 条，冲突 `17` 条，`incomplete=false`。
- 完整候选类型：`race=1392`、`jockey=276`、`racecourse=427`。

生产完整 dry-run：

- 文件：`/app/server/runtime/imports/wpstud-race-jockey-racecourse-review-20260705/seed_candidates.csv`。
- 结果：总计 `2095`、新增 `1891`、更新 `204`、错误 `0`。
- 更新命中：`204` 条中 `199` 条命中 HKJC overseas 官方术语、`3` 条命中 HKJC 本地官方术语、`2` 条命中其他既有术语。
- 处理：生成 `seed_candidates_new_only.csv` 仅导入新增项，生成 `seed_candidates_skipped_existing.csv` 留作人工审核和别名决策依据。

过滤后导入：

- 过滤文件：`/opt/umanewsbot/imports/wpstud-race-jockey-racecourse-review-20260705/seed_candidates_new_only.csv`。
- 跳过清单：`/opt/umanewsbot/imports/wpstud-race-jockey-racecourse-review-20260705/seed_candidates_skipped_existing.csv`。
- dry-run：总计 `1891`、新增 `1891`、更新 `0`、错误 `0`。
- 备份：`backups/db/pre-wpstud-race-jockey-racecourse-term-import-20260705_072047.sql.gz`，已通过 `gzip -t`。
- 正式导入：总计 `1891`、新增 `1891`、更新 `0`、跳过 `0`。

导入后核验：

- `TermEntry=15321`、`TermAlias=15537`。
- WP Stud 新增英文社区术语计数：`1891`。
- WP Stud 全部相关术语计数：`2103`，包含此前已导入的 `210` 条日文马名社区术语和本轮 `1891` 条英文社区术语。
- `source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名、赛事、骑师和马场。
- `http://127.0.0.1/healthz/` 返回 `200`。

## 全球赛马数据库导入入口

香港、英国、法国、美国真实赛马数据库导入属于高风险生产数据操作，不能只凭本地 proof、fixture 测试或少量 dry-run 进入正式写库。

执行前必须先阅读并按顺序使用：

- `docs/global_racing_database_handoff.md`：当前 proof 边界和未完成项。
- `docs/global_racing_sync_manifest.md`：当前主树同步范围、已验证命令和防误用验证。
- `docs/global_racing_next_run_checklist.md`：下一轮按 HKJC -> UK -> France -> US 开跑的检查表。
- `docs/global_racing_full_crawl_runbook.md`：完整 plan-only、小批 dry-run、离线审计和 commit 门禁命令。
- `docs/global_racing_full_crawl_completion_audit.md`：完整目标完成判定和禁止误用证据。

生产写库前必须满足：

- 每地最新 60 天 `plan-only` 已保存。
- 具体批次执行前已使用 `render_global_racing_batch_command --plan-file ... --all-batches --output-dir ...` 或 `--batch N` 从 plan 文件渲染精确命令，并复核 `source`、`target_key`、`target_count`、`suggested_output_path`、`command_line` 和 `tee_command_line`。
- 每地所有 plan 批次均已小批 dry-run，且 `completion.is_complete=true`。
- 所有涉及马匹 profile 或等价详情字段已覆盖。
- `audit_global_racing_import_outputs --fail-on-incomplete` 输出 `commit_candidate_ready=true` 且 `blocking_reasons=[]`。
- 数据库备份、导入锁检查、健康检查和用户显式确认齐全。
- 写库后记录 `run_id`、表计数、coverage、请求数、失败摘要、锁释放、健康检查和回滚口径。

当前 `runtime/global_racing_import/proof-20260627` 只能通过 proof-only 审计；按 commit 候选口径会被正确阻断。不得把这组 proof JSON 当作最近 60 天完整抓取或生产写库依据。

### 核验正式术语

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import TermEntry; print(TermEntry.objects.count()); print(list(TermEntry.objects.filter(source_ja__in=['キタサンブラック','宝塚記念']).values('term_type','source_ja','target_zh','race_grade','aliases_ja')))"
```

期望：

- `キタサンブラック` 为启用马名术语，中文译词为 `北部玄驹`
- `宝塚記念` 为启用比赛术语，`race_grade=G1`

### 执行日候选新闻池批量验收

验收不只看单篇文章。按服务器当前时区执行日 0:00 后进入候选新闻池的全部文章检查：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py validate_candidate_news_since_midnight --format json
```

如需指定起点：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py validate_candidate_news_since_midnight --since 2026-06-09 --format json
```

逐篇确认：

- `terms` 中已有正式术语命中
- 未命中的马名和比赛名存在术语候选证据
- `race_grade` 与 `race_priority` 合理
- `score_total` 与 `review_mode` 不再出现明显低估

### 单篇文章重跑

如需重跑文章 `3961`：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import translate_article_task, process_article_automation_task, discover_term_candidates_task; article_id=3961; translate_article_task.delay(article_id); process_article_automation_task.delay(article_id); discover_term_candidates_task.delay(article_id)"
```

重跑后进入后台文章详情页核验中文标题、翻译元数据、自动评分原因和术语候选证据。

### 回滚方式

- 数据导入错误：优先使用后台停用错误术语，或用 `import_terms --mode upsert` 导入修正 CSV。
- 代码异常：回滚到上一 commit 并重启 `web/worker/beat`。
- 数据结构回滚：仅在确认无法通过停用术语或代码回滚恢复时，使用部署前数据库备份还原。

### 部署前配置

首次部署保持默认关闭：

```env
TERM_DISCOVERY_ENABLED=false
TERM_DISCOVERY_PROVIDER=rules
TERM_DISCOVERY_MIN_CONFIDENCE=60
```

执行代码部署、数据库迁移与检查：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d --build web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 单篇手动验证

在后台候选新闻详情页点击“重新发现术语”，或执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import discover_term_candidates_task; print(discover_term_candidates_task.run(ARTICLE_ID))"
```

检查后台“术语候选”列表，确认候选类型、上下文、来源文章、置信度、冲突信息和出现次数合理；接受一条测试候选后，确认正式术语库新增记录且操作日志完整。

### 逐步启用

1. 先保持关闭，抽查若干单篇手动发现结果。
2. 将 `TERM_DISCOVERY_ENABLED=true`，只重启 `web` 与 `worker`。
3. 每日抽检待审核候选，重点观察误报、跨类型冲突和证据增长。
4. 根据质量谨慎调整 `TERM_DISCOVERY_MIN_CONFIDENCE`，不要在未抽检时降低阈值。

### 监控与关闭

- 通过 `TaskExecutionLog(task_name=discover_term_candidates)` 查看任务成功与失败。
- 观察候选池每日新增量、拒绝比例、平均证据数量和正式术语冲突。
- 若误报或任务异常增加，将 `TERM_DISCOVERY_ENABLED=false` 并重启 `web` 与 `worker`；无需回滚迁移或删除候选数据。
- 不进行历史全量回溯，不允许绕过工作人员审核直接写入 `TermEntry`。

### 本次执行记录（2026-06-07）

实际部署时确认的若干细节，供后续运维复用：

- 连接方式：`ssh root@47.239.167.86`（公网 IP，端口 `22`，公钥认证）；部署目录 `/opt/umanewsbot`，compose 用 `docker-compose.prod.lowcost.yml`。
- 服务器 `git pull origin main` 走 HTTPS 远端，从 `7123e4e` 快进到 `e2e3e07`。
- **`web` 容器启动脚本会自动执行 `migrate`**：`docker compose up -d` 重建 `web` 后，迁移 `0006` 已在启动时应用，随后显式 `migrate` 会显示 `No migrations to apply`，属正常。
- 生产数据库名与用户均为 `horse_news`；迁移前快照命令：
  ```bash
  docker compose -f docker-compose.prod.lowcost.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backups/pre-0006-<时间戳>.sql
  ```
- 本次备份产物：`.env.backup.20260607_033207` 与 `backups/pre-0006-20260607_033207.sql`（74M）。
- 验证：`check` 0 issues；候选/证据计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`；`worker` 无报错。
- 本轮保持 `TERM_DISCOVERY_ENABLED=false`，未改 `AUTOMATION_ENABLED`（线上为 `true`）与 HTTPS。

## 公开首页资讯流生产部署（2026-06-22）

### 部署内容

- GitHub PR #1 `[codex] Upgrade public home info feed` 已从 draft 转为 ready，并合并到 `main`。
- merge commit：`e834f58`；实现提交：`1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`。
- 本次不包含数据库迁移、生产 `.env` 开关调整或 Compose 架构变更。
- 新增公开站点静态资源 `stable/public.css`，首页与详情页不再以后台 `console.css` 作为主要样式入口。

### 部署前状态与备份

- 服务器存在未跟踪 `.env.backup.*` 和 `imports/`，保留不清理。
- 服务器 tracked diff 仅为部署脚本权限位变化：
  - `deploy_lowcost.sh`
  - `deploy/deploy_lowcost.sh`
  - `deploy/docker/compose-wrapper.sh`
- 上述权限位变化是为了修复此前 `Permission denied`，内容无差异，部署时予以保留。
- 部署前 `.env` 备份：`.env.backup.20260622_140844`。

### 部署命令

```bash
cd /opt/umanewsbot
git fetch origin main
git pull --ff-only origin main
./deploy_lowcost.sh
```

脚本结果：

- 重建并重启 `web / worker / beat`。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 成功处理公开静态资源，生产首页引用 `/static/stable/public.2eec24723b45.css`。
- `web` 容器为 healthy，`db / redis` healthy，`worker / beat` up。

### 验证结果

```bash
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
curl -I http://umafans.run/static/stable/public.2eec24723b45.css
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=80 umanewsbot-web-1
docker logs --tail=80 umanewsbot-nginx-1
```

结果：

- `http://umafans.run/healthz/` 返回 `200`，响应体为 `{"status": "ok"}`。
- `http://umafans.run/` 返回 `200`。
- 首页 HTML 包含 `home-page`、`headline-card`、`news-card` 和“原站热度”。
- 首页引用 `/static/stable/public.2eec24723b45.css`，不再引用旧 `console.css`。
- `public.css` 可访问并包含移动端 `news-card`、`headline-card`、`-webkit-line-clamp` 和 390px 视口布局规则。
- 浏览器生产验收：
  - 桌面端：轻导航、主头条和热门模块显示正常。
  - 390px 移动端：普通新闻卡约 `128px` 高，右侧缩略图约 `104px x 78px`，首屏头条后可见 3 条普通新闻，无横向溢出。
  - 详情页：标题、封面、来源、公开详情结构和 `public.css` 引用正常，控制台无错误。

### 回滚方式

本次无数据库迁移。若公开首页出现严重问题，优先回滚代码与容器：

```bash
cd /opt/umanewsbot
git checkout 62a6a02
./deploy_lowcost.sh
```

如需保持 `main` 分支语义，优先在 GitHub revert `e834f58` 后服务器 `git pull --ff-only origin main` 并重新执行 `./deploy_lowcost.sh`。

## 移动端首页密度 follow-up 生产部署（2026-06-23）

### 部署内容

- GitHub PR #2 `[codex] Polish mobile public home density` 已从 draft 转为 ready，并合并到 `main`。
- merge commit：`04e2ee9`；实现提交：`b6e93b9`。
- 服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`。
- 本次不包含数据库迁移、生产 `.env` 开关调整或 Compose 架构变更。
- 主要变更是移动端 `stable/public.css` 首屏密度微调：收紧顶部与页面间距、头条图片比例从 `16 / 9` 改为 `16 / 7`、移动端隐藏头条摘要，普通新闻卡保持约 `128px` 高。

### 部署前状态与备份

- 部署前 `.env` 备份：`.env.backup.20260623_120201`。
- 服务器仍存在历史 `.env.backup.*` 与 `imports/` 未跟踪文件，保留不清理。
- 服务器 tracked diff 显示多个部署脚本权限位变化，属线上执行权限修正遗留，部署时保留不回滚。

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
./deploy_lowcost.sh
```

脚本结果：

- 重建并重启 `web / worker / beat`。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，生产首页引用 `/static/stable/public.9aaf4b105424.css`。
- `web` 容器为 healthy，`db / redis` healthy，`worker / beat` up。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check` 返回 `System check identified no issues`。

### 验证结果

```bash
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
curl http://umafans.run/ | grep public
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=80 umanewsbot-web-1
```

结果：

- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 首页 HTML 包含 `home-page`、`headline-card`、`news-card` 和“原站热度”。
- 首页引用 `/static/stable/public.9aaf4b105424.css`，不引用 `console.css`。
- `public.css` 可访问并包含移动端 `max-width: 599px`、`aspect-ratio: 16 / 7` 和摘要隐藏规则。
- 浏览器生产验收：
  - 390px 移动端：首页头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通新闻卡约 `128px` 高，右侧缩略图约 `104px x 78px`，首屏可见 4 条普通新闻，无横向溢出。
  - 详情页：公开详情结构、标题、封面正常，无横向溢出，控制台无错误。

### 回滚方式

本次无数据库迁移。若移动端首页密度出现严重问题，优先在 GitHub revert `04e2ee9`，然后服务器执行：

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
./deploy_lowcost.sh
```

如需临时直接回退到上一生产版本，可 checkout `e834f58` 后重新部署，但后续仍应通过 GitHub revert 保持 `main` 分支语义一致。

## 外部赛马数据导入运行手册

### 默认状态

外部赛马数据导入默认不运行：

```bash
EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false
EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false
```

Celery 任务 `stable.tasks.import_external_horse_data_task` 不加入默认全量 Celery Beat 调度，生产只能由人工明确触发。

### 生产执行前

1. 确认代码已部署并执行迁移。
2. 备份数据库。
3. 确认同一时间没有其他外部赛马数据导入任务运行。
4. 首次执行建议先不抓赔率，先只补 `entry/result/horse/history`。
5. 首次真实请求建议使用更保守限速：`8-10` 秒请求间隔，小批量执行。

### 依赖检查

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --check-dependency
```

### dry-run

dry-run 不写入外部数据表：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --year 2026 --month 5 --dry-run
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --race-id 202605310101 --dry-run
```

### 单月小批量真实导入

必须同时打开配置和命令参数：

```bash
EXTERNAL_HORSE_DATA_IMPORT_ENABLED=true
EXTERNAL_HORSE_DATA_ALLOW_NETWORK=true
EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS=10
EXTERNAL_HORSE_DATA_JITTER_SECONDS=2
EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN=10
EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN=30
EXTERNAL_HORSE_DATA_FETCH_ODDS=false
```

执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data \
  --year 2026 --month 5 \
  --allow-network \
  --max-races 10 \
  --max-horses 30 \
  --no-fetch-horse-detail
```

如需补单匹马，并且人工已知可信日文马名：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data \
  --horse-id 1000000000 \
  --horse-name マヤノライジン \
  --allow-network
```

### 验收查询

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --lookup-name マヤノライジン
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --stats-run-id <run_id>
```

重点看：

- `status`
- `failure_count`
- `coverage_stats.race_count`
- `coverage_stats.entry_count`
- `coverage_stats.result_count`
- `coverage_stats.unique_horse_id_count`
- `coverage_stats.unique_horse_name_count`
- `coverage_stats.missing_horse_id_or_name_count`

### 日志与停止

```bash
docker logs --tail=200 umanewsbot-web-1
docker logs --tail=200 umanewsbot-worker-1
```

如需停止：

1. 关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false` 和 `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
2. 停止正在执行导入的命令或 Celery worker。
3. 保留外部数据表记录，新表不参与主新闻链路，不影响前台发布。

### 2026-06-23 首次生产小批量结果

- 部署提交：`58a6e82`。
- `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- `stable.0008` 迁移已应用，`web` healthy，`/healthz/` 返回 `200`。
- `python manage.py import_external_horse_data --check-dependency` 返回 `keibascraper import ok`。
- dry-run 目标：`2026-05`，最多 10 场，预计 20 个请求。
- 真实导入参数：`2026-05`，最多 10 场，不抓赔率，不补马匹详情，请求间隔 10 秒 + 2 秒抖动。
- 结果：`run_id=1`，`status=paused`，成功 10 场，失败 0，因批量上限跳过 326 场。
- 写入：10 场比赛、151 条出走、143 条赛果、143 个唯一马 ID/马名索引。
- `2026-06-24` 已补充按月续跑逻辑：再次执行同一月份时会跳过已落库 race，只处理下一批未导入 race。
- 第二批续跑结果：`run_id=2`，已跳过首批 10 场，继续成功导入 10 场，失败 0；累计 20 场比赛、274 个唯一马 ID/马名索引。
- 第三批续跑结果：`run_id=3`，继续成功导入 30 场，失败 0；累计 50 场比赛、695 个唯一马 ID/马名索引，`/healthz/` 返回 `200`。
- 长循环导入中断记录：`run_id=4` 到 `run_id=8` 均成功；`run_id=9` 成功 7 场后进程退出码 `137` 中断，已标记为 `partial` 并释放导入锁。中断后累计 182 场比赛、2401 个唯一马 ID/马名索引，`/healthz/` 返回 `200`。

## 2026-06-25 外部马名索引识别链路生产部署

### 部署内容

- GitHub PR #6 `[codex] Use external horse aliases for name recognition` 已 squash merge 到 `main`。
- merge commit：`35b0866`。
- 服务器 `/opt/umanewsbot` 从 `817e1c8` 快进到 `35b0866`。
- 本次不包含数据库迁移或 `.env` 功能开关调整。
- 主要变更：
  - `ExternalHorseAlias` 接入文章马名识别、翻译保护、发布校验和术语候选发现。
  - 外部已知但无中文译名的马名在译文中原样保护，未保留时记录独立 `external_horse_not_preserved` warning。
  - `TermEntry` 仍作为正式中文术语库；外部马名索引不批量写入 `TermEntry`。

### 部署前状态与备份

- 部署前 `.env` 备份：`.env.backup.external-horse-alias-20260625_182936`。
- 服务器部署前只有 `.env.backup.*`、`imports/`、`napcat/`、`runtime/` 等未跟踪运行态文件；无 tracked diff。

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.external-horse-alias-$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
./deploy_lowcost.sh
```

### 验证结果

- `./deploy_lowcost.sh` 执行成功。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，`0 static files copied`，`129 unmodified`，`360 post-processed`。
- `web` 容器 healthy，`db / redis` healthy，`worker / beat` up。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- `http://127.0.0.1/healthz/` 返回 `{"status": "ok"}`。
- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 生产只读 smoke test：`ExternalHorseAlias=11521`；`recognize_horse_names("ロブチェンが出走", "ロブチェンは重賞へ向かう。")` 返回 `ロブチェン`，来源为 `external_alias`，外部 horse ID 为 `2023107089`。

## QQ Bot / OneBot 生产运行态配置（2026-06-24）

### 配置结论

- OneBot 网关：独立 Docker 容器 `umanewsbot-onebot-1`
- 镜像：`mlikiowa/napcat-docker:latest`
- 访问边界：
  - 宿主机仅绑定 `127.0.0.1:3000 -> 3000` 和 `127.0.0.1:6099 -> 6099`
  - 应用容器通过 Docker 网络别名 `http://onebot:3000` 访问
  - 不对公网暴露 OneBot API 或 NapCat WebUI
- 数据目录：
  - `/opt/umanewsbot/napcat/config`
  - `/opt/umanewsbot/napcat/qq`
- 机密文件：
  - `/opt/umanewsbot/runtime/secrets/onebot_access_token`
  - `/opt/umanewsbot/runtime/secrets/napcat_webui_token`

### 生产 `.env`

```env
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_TIMEOUT_SECONDS=30
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
QQ_PUSH_MIN_INTERVAL_SECONDS=60
```

`ONEBOT_ACCESS_TOKEN` 已写入生产 `.env`，但不得写入仓库文档。生产当前已将 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 用于测试群灰度，让后续自动推送只覆盖 netkeiba 访问量榜 / 注目数榜新闻。`QQ_PUSH_MIN_INTERVAL_SECONDS` 用于控制同一目标群两次自动发送尝试之间的最小间隔，避免批量补推或批量发布触发 QQ / NapCat 发送异常。

### 已配置群目标

- `PushTarget.group_id=1026525240`
- `name=UmaFans测试群`
- `is_active=true`

### 验证结果

- `docker ps` 显示 `umanewsbot-onebot-1` 正常运行。
- `ss -ltnp` 显示 `3000` 与 `6099` 均只监听 `127.0.0.1`。
- OneBot 直连测试返回 `{"status":"ok","retcode":0,...}`，消息发送到 `新闻测试(1026525240)`。
- Django 应用侧 `stable.services.onebot.BotPusher` 通过 `http://onebot:3000` 成功发送测试消息，返回 `retcode=0`。
- 重启 `worker / beat` 让它们读取新的 `.env`；Compose 同时按依赖短暂重建了 `db / web` 容器，但没有执行 `git pull`、没有 build、没有运行 `deploy_lowcost.sh`。
- 重启后 `web` healthz 返回 `{"status": "ok"}`，`web` 容器 healthy，`db / redis` healthy，`worker / beat` up。
- 2026-06-24 已部署 `add-qqbot-auto-push` 到 `main`，生产迁移 `stable.0010_qqpushdelivery` 已应用，`QQ_PUSH_ENABLED=true` 与 `QQ_PUSH_SCOPE=all_public` 已生效。
- 批量补推 126 篇存量公开文章时，`QQPushDelivery` 记录创建成功；NapCat / QQ 客户端返回 `EventChecker Failed ... 网络连接异常`，系统按 `send_failed` 记录并进入有限重试，未误标记成功。后续补推必须使用 `QQ_PUSH_MIN_INTERVAL_SECONDS` 或人工脚本限速。
- 2026-06-25 重新扫码登录 NapCat 后，Django 应用侧短消息和 `qq_auto_push_article_task` 自动任务链路均已成功发送到测试群。限速补推按 65 秒间隔成功发送 79 条交付记录；按当前验收口径，不再继续补推全部历史公开新闻，剩余历史失败记录保留在后台，不影响后续新发布文章自动推送。
- 2026-06-25 部署榜单重点推送后，生产已切换为 `QQ_PUSH_SCOPE=high_value_only` 与 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；本次不补推历史公开新闻，后续等待自然榜单新闻触发测试群推送。
- 2026-06-26 再次排查 QQ 推送停滞时，生产日志确认 NapCat 快速登录态失效；处理时先将 `QQ_PUSH_ENABLED=false` 并重启 `worker / beat` 暂停自动推送，用户重新扫码登录后，`BotPusher().is_online()` 返回 `(True, '')`，`/get_login_info` 显示 QQ `1577955464`，群列表包含 `1026525240`，Django 应用侧测试消息发送成功。随后恢复 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 并重启 `worker / beat`。本次不补推全部已发表新闻。
- 2026-06-26 OneBot 离线防护已部署到生产 `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`。部署后 `web` healthy，迁移无新增，`manage.py check` 通过，本地和公网 `/healthz/` 均为 `200`，worker 环境确认 QQ 自动推送仍开启；`BotPusher().is_online()` 返回 `(True, '')`，测试群部署验证消息发送成功，`message_id=1364343902`。

## 2026-06-25 榜单重点 QQ 推送与公开文章 ID URL 生产部署

### 部署内容

- `elevate-ranked-netkeiba-sources`：同一 netkeiba 新闻先被新着顺命中、稍后被访问量榜或注目数榜命中时，主来源可从 `latest` 提升为 `access` 或 `attention`；访问量榜和注目数榜不互相覆盖。
- `push-ranked-news-to-qq`：生产 `high_value_only` 改为按 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 判断重点新闻，本期只推 `netkeiba:access` / `netkeiba:attention` 且无 blocker 的公开文章；来源提升后的已公开文章会触发 QQ 自动推送编排。
- `use-article-id-public-urls`：公开详情主路径改为 `/news/<article_id>/`，旧非纯数字 slug URL 保留为 `302` 跳转入口，QQ 消息中的 `阅读全文` 不再包含标题全文。

### 部署前状态与备份

- 合并 PR：#8 `[codex] Implement ranked QQ push and ID article URLs`。
- 部署提交：`00e4bd4`。
- 服务器部署前 HEAD：`b0c986a`。
- 部署前确认无正在运行的 `ExternalDataImportRun(status="started")`。
- 部署前 `.env` 备份：`.env.backup.qq-ranked-idurl-20260625_191826`。
- 服务器部署前只有 `.env.backup.*`、`imports/`、`napcat/`、`runtime/` 等未跟踪运行态文件；无 tracked diff。

### 部署步骤与配置

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
cp .env .env.backup.qq-ranked-idurl-20260625_191826
```

生产 `.env` 已设置：

```env
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_MIN_INTERVAL_SECONDS=60
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_TIMEOUT_SECONDS=30
```

随后执行：

```bash
bash ./deploy_lowcost.sh
```

### 验证结果

- `./deploy_lowcost.sh` 执行成功，`db / web / worker / beat` 已重建，`nginx / redis` 正常运行。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，`0 static files copied`，`129 unmodified`，`360 post-processed`。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- 生产 worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 抽检公开文章 `ARTICLE_ID=5551`：`http://127.0.0.1/news/5551/` 返回 `200`。
- 抽检旧 slug URL 返回 `302`，`Location` 指向 `/news/5551/`。
- 本轮不补推全部已发表新闻；后续只等待自然榜单新闻触发测试群推送。

### 归档结果

- `add-qqbot-auto-push` 已归档为 `旧规格流程/changes/archive/2026-06-25-add-qqbot-auto-push/`，并创建正式规格 `旧规格流程/specs/qqbot-auto-push/spec.md`。
- `elevate-ranked-netkeiba-sources` 已归档为 `旧规格流程/changes/archive/2026-06-25-elevate-ranked-netkeiba-sources/`，并同步到 `旧规格流程/specs/crawl-freshness-and-source-health/spec.md`。
- `use-article-id-public-urls` 已归档为 `旧规格流程/changes/archive/2026-06-25-use-article-id-public-urls/`，并同步到 `旧规格流程/specs/public-home-info-feed/spec.md`。
- `push-ranked-news-to-qq` 已归档为 `旧规格流程/changes/archive/2026-06-25-push-ranked-news-to-qq/`，并同步到 `旧规格流程/specs/qqbot-auto-push/spec.md`。
- 前期废弃的空目录 `旧规格流程/changes/refine-ranked-news-push/` 已清理，避免 旧规格流程 active 列表出现无任务占位 change。
- 归档后 `旧规格流程 validate --all` 通过。

### 自动推送上线步骤

1. 合入并部署 `add-qqbot-auto-push`。
2. 执行迁移，确认 `stable_qqpushdelivery` 表存在。
3. 确认测试群 `PushTarget.is_active=true`。
4. 设置 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
5. 重启 `worker / beat`。
6. 发布或复用一篇公开文章触发自动推送，核对测试群消息、`QQPushDelivery` 和 worker 日志。

### 停用方式

停用自动推送：

```env
QQ_PUSH_ENABLED=false
```

停用 OneBot 网关：

```bash
cd /opt/umanewsbot
docker rm -f umanewsbot-onebot-1
```

## expand-international-racing-coverage 部署前运维说明

> 当前状态：本 change 仍在本地实现与验证阶段，尚未部署生产。本节用于后续部署前核对。

### QQ 群级自动推送配置

- `QQ_PUSH_ENABLED` 仍是总开关，只决定自动推送任务是否运行。
- `PushTarget.allowed_regions`、`PushTarget.push_scope`、`PushTarget.importance_strategy` 决定“推什么给谁”。
- 迁移会把已有 `PushTarget.allowed_regions` 回填为 `["japan"]`，保留旧的日本新闻推送行为；运行时若遇到空地区列表，也按兼容默认处理为仅允许 `japan`，不得默认推送全球新闻。
- `PushTarget.push_scope` 为空时回退到全局 `QQ_PUSH_SCOPE`。
- `PushTarget.importance_strategy` 为空时回退到全局 `QQ_PUSH_IMPORTANCE_STRATEGY`。
- 文章 `racing_region` 缺失或非法时，自动推送必须跳过，原因记录为 `region_missing`。
- 自动推送创建交付前会逐个目标群判断地区、范围和重点策略；不符合目标群配置的群不会创建新的 `QQPushDelivery`。

部署后建议核对：

```bash
python manage.py shell -c "from stable.models import PushTarget; print(list(PushTarget.objects.values('name','group_id','is_active','allowed_regions','push_scope','importance_strategy')))"
```

回滚/停用方式：

```env
QQ_PUSH_ENABLED=false
```

如果只想恢复旧日本新闻推送行为，可在 Django Admin 中把目标群 `allowed_regions` 设置为 `["japan"]` 或留空，并把 `push_scope / importance_strategy` 留空，让代码只在范围和重点策略上回退到全局配置。

### HKJC 外部数据导入命令

HKJC 导入默认 dry-run，不会写正式外部缓存表：

```bash
python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file /path/to/hkjc_sample.json
```

确认样本字段后再提交写入 External* 缓存表：

```bash
python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file /path/to/hkjc_sample.json --commit
```

提交写入仍是小样本受控导入：命令会按配置检查 `max_races / max_horses`，payload 超过上限时直接失败，不会静默截断或部分写入。遇到超限时应拆分样本文件后重新 dry-run，再提交。

HKJC 真实网络小样本相关配置保持保守值：

```env
HKJC_IMPORT_NETWORK_BASE_URL=https://racing.hkjc.com
HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8
HKJC_IMPORT_MAX_RACES_PER_RUN=20
HKJC_IMPORT_MAX_HORSES_PER_RUN=80
HKJC_IMPORT_MAX_REQUESTS_PER_RUN=200
```

真实网络 dry-run 可从单场或小范围 recent-days 开始，并记录请求边界：

```bash
python manage.py import_hkjc_external_data --race-id HK20260624HV01 --allow-network
python manage.py import_hkjc_external_data --recent-days 60 --limit-races 1 --limit-horses 1 --max-requests 10 --allow-network
```

生产最近 2 个月全量前，先用 plan-only 生成拆批计划。plan-only 只抓赛日和 race links，不抓单场结果或马匹详情：

```bash
python manage.py import_hkjc_external_data --recent-days 60 --limit-races 20 --max-requests 80 --allow-network --plan-only
```

plan-only 的每个 batch 会输出 `skip_races`，后续批次 dry-run/commit 必须带对应 offset，避免每批都从第一场重跑：

```bash
python manage.py import_hkjc_external_data --recent-days 60 --skip-races 20 --limit-races 20 --limit-horses 200 --max-requests 260 --allow-network
```

更推荐使用 plan-only 输出里的 `race_ids` 做精确批次。该模式只请求指定比赛页和涉及马匹详情页，不需要为后续批次重新扫描前置赛日页：

```bash
python manage.py import_hkjc_external_data --race-ids HK20260624HV02,HK20260613ST04 --limit-horses 200 --max-requests 260 --allow-network
```

2026-06-26 本地 plan-only 结果显示：最近 60 天 HKJC 下拉目标日期页 `28` 个；过滤 overseas simulcast 的 `S*` racecourse 后，本地香港 `HV/ST` 比赛为 `144` 场，按每批 `20` 场拆为 `8` 批。生产环境仍需重跑 plan-only，以生产当时页面为准。

`recent-days/date-range/race-ids` 输出中的 `completion` 是生产门禁字段：

- `completion.is_complete=false`：本次因 `limit-races`、`limit-horses` 或请求上限等原因只是小样本/拆批运行，不能当作最近 2 个月全量完成。
- `completion.stop_reason`：记录停止原因，例如 `limit_horses_reached`。
- `completion.meetings_found / races_imported / unique_horses_found / horse_profiles_fetched`：用于估算下一批请求量和生产 commit 风险。
- `race-ids` 批次没有 `meetings_found`，以 `race_ids / races_imported / unique_horses_found / horse_profiles_fetched` 作为审计字段。

隔离环境验证过的真实网络 payload 可以 commit，但生产执行前必须先备份数据库、检查单来源锁和 `started` run、跑 dry-run、取得用户显式确认：

```bash
python manage.py import_hkjc_external_data --recent-days 60 --limit-races 1 --limit-horses 1 --max-requests 10 --allow-network --commit
```

查询导入统计：

```bash
python manage.py import_hkjc_external_data --stats-run-id <run_id>
```

查询本地 HKJC 马名索引：

```bash
python manage.py import_hkjc_external_data --lookup-name "Lucky Star"
```

生产注意事项：

- 部署前必须确认没有正在运行的外部数据导入。
- 真实网络请求必须保持低频限速；扩大到最近 2 个月全量前，应先用 `--limit-races / --limit-horses / --max-requests` 分批 dry-run，确认请求量和字段覆盖。
- 生产最近 2 个月全量 commit 前必须记录备份路径、dry-run 结果、锁检查、健康检查和用户确认。
- 本 change 不创建比赛页、赛果页、马匹页；导入数据只作为外部缓存、马名识别和后续项目底座。
- 2026-06-26 生产第 1 批 full dry-run 曾在 HKJC 马匹 profile 补抓阶段遇到 `ReadTimeout` / TLS handshake timeout；该次为 dry-run，未写表，锁为空。随后已补 transient timeout retry：单请求最多 3 次，失败尝试会保留在请求证据中。长批次仍建议先 dry-run，失败后检查 `started_runs`、单来源锁和表计数再重试。

## 2026-06-26 HKJC 数据导入 readiness 与英法美 spike 生产部署

### 部署前状态

- change：`start-hkjc-data-import-and-global-spikes`
- 部署 commit：`b0361cf`
- 服务器部署前 HEAD：`4d09d25`
- 部署前 `.env` 备份：`.env.backup.hkjc-global-spikes-20260626_164045`
- 部署前只读检查：
  - `ExternalDataImportLock` 运行中锁：无
  - `ExternalDataImportRun(status="started")`：无
  - `web` 容器：healthy

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.hkjc-global-spikes-20260626_164045
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
bash ./deploy_lowcost.sh
```

### 部署结果

- 服务器 `/opt/umanewsbot` 已从 `4d09d25` 快进到 `b0361cf`。
- `bash ./deploy_lowcost.sh` 执行成功。
- 迁移显示 `No migrations to apply`。
- `web / worker / beat` 已重建，`web` healthy。
- `collectstatic` 完成：`0 static files copied`，`129 unmodified`，`360 post-processed`。

### 生产验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
curl -I http://127.0.0.1/healthz/
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json
```

结果：

- `manage.py check`：通过。
- `http://127.0.0.1/healthz/`：`200`
- `http://umafans.run/healthz/`：`200`
- `http://umafans.run/`：`200`
- HKJC 样本命令：dry-run 成功，`coverage_stats={"races":1,"entries":2,"results":2,"horses":2}`，`would_write_formal_tables=false`。

注意：第一次 HKJC smoke 使用了仓库根相对路径 `server/stable/fixtures/...`，容器内工作目录为 `/app/server`，因此返回 `FileNotFoundError`；已改用 `stable/fixtures/...` 重跑通过。这不是业务逻辑失败。

### 边界

- 该部署验证阶段没有执行 HKJC `--commit`；后续生产样本 commit 见下方单独记录。
- 本次生产没有启用英法美正式导入、Celery Beat 调度或生产命令队列。
- HKJC 真实网络 dry-run 当前最小 URL 构造返回 `404`，后续必须先确认稳定 JSON/API、页面脚本 payload 或 HTML 解析入口，才能进入真实网络 commit 设计。

### 归档同步

- 归档提交：`db0f3cc`
- 服务器 `/opt/umanewsbot` 已从 `b0361cf` 快进到 `db0f3cc`。
- `db0f3cc` 仅移动 旧规格流程 change 到 archive 并同步正式 spec，不包含服务代码变更；因此未重新 build 或重启容器。
- 服务器未安装 `旧规格流程` CLI，归档后的 `旧规格流程 validate --all` 在本地 worktree 执行并通过。
- 归档同步后 `http://umafans.run/healthz/` 和 `http://umafans.run/` 仍返回 `200`。

## 2026-06-26 HKJC 生产样本 commit

### 执行边界

- 本次只提交仓库 fixture：`stable/fixtures/hkjc/2026-06-21-race-date-sample.json`。
- 本次不是 HKJC 真实网络抓取；`--allow-network` 的稳定入口仍未确认。
- 本次不创建公开比赛页、赛果页或马匹页，只写 `External*` 外部缓存表和 `ExternalHorseAlias`。
- 本次不启用 Celery Beat 周期任务或后台持续导入队列。

### 备份

```bash
cd /opt/umanewsbot
mkdir -p backups/db
docker compose -f docker-compose.prod.lowcost.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > backups/db/pre-hkjc-sample-20260626_180646.sql.gz
gzip -t backups/db/pre-hkjc-sample-20260626_180646.sql.gz
```

结果：

- 备份文件：`backups/db/pre-hkjc-sample-20260626_180646.sql.gz`
- 大小：`42M`
- `gzip -t`：通过

### 预检查

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml ps
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c 'from stable.models import ExternalDataImportLock, ExternalDataImportRun, ExternalRace, ExternalRaceEntry, ExternalRaceResult, ExternalHorse, ExternalHorseAlias; print({"active_locks": [], "started_runs": [], "hkjc_counts": {"runs": ExternalDataImportRun.objects.filter(source="hkjc").count(), "races": ExternalRace.objects.filter(source="hkjc").count(), "entries": ExternalRaceEntry.objects.filter(source="hkjc").count(), "results": ExternalRaceResult.objects.filter(source="hkjc").count(), "horses": ExternalHorse.objects.filter(source="hkjc").count(), "aliases": ExternalHorseAlias.objects.filter(source="hkjc").count()}})'
ps -eo pid,args | grep "[i]mport_hkjc_external_data\|[i]mport_external_horse_data" || true
```

结果：

- 生产 HEAD：`5f92e4d`
- `web / worker / beat / db / redis / nginx`：运行中，`web` healthy
- HKJC 生产导入前计数：`runs=0`、`races=0`、`entries=0`、`results=0`、`horses=0`、`aliases=0`
- 无 HKJC 导入进程

### dry-run

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json
```

结果：

- `dry_run=true`
- `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}`
- `would_write_formal_tables=false`

### commit

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json --commit
```

结果：

- `run_id=1960`
- `status=success`
- `success_count=7`
- `skipped_count=0`
- `failure_count=0`
- `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}`

### 提交后核验

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --stats-run-id 1960
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --lookup-name "STELLAR EXPRESS"
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c 'from stable.models import ExternalDataImportLock, ExternalDataImportRun, ExternalRace, ExternalRaceEntry, ExternalRaceResult, ExternalHorse, ExternalHorseAlias; print({"locks": list(ExternalDataImportLock.objects.values("source", "racing_region", "locked_by_run_id", "acquired_at")), "hkjc_runs": ExternalDataImportRun.objects.filter(source="hkjc").count(), "latest_run": list(ExternalDataImportRun.objects.filter(source="hkjc").order_by("-id").values("id", "status", "success_count", "skipped_count", "failure_count", "target_type", "current_target_id")[:1]), "counts": {"races": ExternalRace.objects.filter(source="hkjc").count(), "entries": ExternalRaceEntry.objects.filter(source="hkjc").count(), "results": ExternalRaceResult.objects.filter(source="hkjc").count(), "horses": ExternalHorse.objects.filter(source="hkjc").count(), "aliases": ExternalHorseAlias.objects.filter(source="hkjc").count()}})'
curl -sS -o /dev/null -w "public_healthz=%{http_code}\n" http://umafans.run/healthz/
```

结果：

- `--stats-run-id 1960`：`status=success`，`success_count=7`，`failure_count=0`
- `--lookup-name "STELLAR EXPRESS"`：命中 `external_horse_id=HKH_STELLAR_EXPRESS`，`confidence=100`
- HKJC 正式外部表计数：`races=1`、`entries=2`、`results=2`、`horses=2`、`aliases=4`
- `ExternalDataImportLock` 中 HKJC 记录为未占用状态：`locked_by_run_id=None`，`acquired_at=None`
- 未发现仍在运行的 HKJC 导入进程

## 2026-06-27 全球赛马数据库能力确认上线

本次上线只发布四地赛马数据库“抓取能力可用”相关改造，不执行最近 60 天完整大量爬取，也不执行生产 `--commit`。

上线包必须从 `origin/main` 干净基线整理，避免把当前本地大工作树中的 QQ 推送、前台信息流、compose 端口或历史 archive 差异混入。必要范围限定为：

- UK / France / US importer 与管理命令
- `audit_global_racing_import_outputs` 离线审计命令
- `render_global_racing_batch_command` 只读批次命令渲染器
- 四地真实来源 fixtures、旧规格流程 `real-global-racing-data-ingestion` 规格/归档
- `docs/global_racing_*` 交接、runbook、审计和 proof 记录

上线后验收重点：

- `manage.py check` 通过
- 全球赛马目标测试通过
- `旧规格流程 validate --all` 通过
- `/healthz/` 返回 `200`
- `import_uk_external_data --help`、`import_france_external_data --help`、`import_us_external_data --help`、`audit_global_racing_import_outputs --help` 可用
- 生产不新增 `ExternalDataImportRun(status="started")`，不持有 `ExternalDataImportLock`

后续如果要完整抓取最近 60 天数据，必须新开执行窗口，先 plan-only，再小批 dry-run，再离线审计，最后经备份、锁检查、健康检查和用户显式确认后才允许讨论 `--commit`。

### 本次执行结果

- 提交：`93b7007 Ship global racing database import capability`
- 推送：`main` 从 `9ff667a` fast-forward 到 `93b7007`
- 部署：服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main` 后运行 `bash ./deploy_lowcost.sh`
- 迁移：`No migrations to apply`
- 容器：`web / worker / beat` 已重建，`web` healthy
- 验证：
  - `manage.py check` 通过
  - `http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`
  - `import_uk_external_data`、`import_france_external_data`、`import_us_external_data`、`render_global_racing_batch_command` 命令入口可用
  - proof-only 审计通过，`proof_ready=true`、`proof_blocking_reasons=[]`、`commit_candidate_ready=false`
  - `ExternalDataImportRun(status="started")=0`
  - HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`
  - 一次性 proof 审计容器已自动删除，无 `umanewsbot-web-run-*` 临时容器残留
- `http://umafans.run/healthz/`：`200`

### 恢复口径

如需要撤销本次样本写入，优先在维护窗口使用备份 `backups/db/pre-hkjc-sample-20260626_180646.sql.gz` 做整库恢复；不要只手工删除 `External*` 表行，避免遗漏 `ExternalDataImportRun`、`ExternalHorseAlias` 或锁状态证据。当前样本写入规模很小，且不参与公开前台或自动发布链路。

## 2026-06-30 HKJC 慢速真实 dry-run 启动

本次只执行香港 HKJC 真实网络 dry-run，不执行生产 `--commit`，不写正式表。

### 执行前检查

- 服务器：`/opt/umanewsbot`
- 代码：`7b6e51b`
- `docker compose -f docker-compose.prod.lowcost.yml ps`：`web/db/redis` healthy，`worker/beat/nginx` 运行中
- `ExternalDataImportRun(status="started")=0`
- HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`
- `http://umafans.run/healthz/`：`200`

### 最新 plan-only

```bash
cd /opt/umanewsbot
mkdir -p runtime/global_racing_import/hkjc-20260630
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps -T \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=160 \
  web python manage.py import_hkjc_external_data \
  --recent-days 60 \
  --end-date 2026-06-30 \
  --plan-only \
  --limit-races 20 \
  --max-requests 160 \
  --allow-network \
  > runtime/global_racing_import/hkjc-20260630/hkjc-plan-20260630.json
```

结果：

- `coverage={"meetings":29,"races":146,"estimated_requests_without_horses":176}`
- `batch_count=8`
- `first_batch.race_count=20`
- `last_batch.skip_races=140`、`last_batch.race_count=6`
- 该 plan 已不同于历史 `144` 场；不要直接沿用旧 `120/144` 停点。

### 小批慢速 dry-run

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps -T \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=100 \
  web python manage.py import_hkjc_external_data \
  --race-ids HK20260627ST02,HK20260627ST03 \
  --max-requests 100 \
  --allow-network \
  > runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json
```

结果：

- `dry_run=true`
- `would_write_formal_tables=false`
- `coverage_stats={"races":2,"entries":28,"results":28,"horses":28}`
- `completion={"is_complete":true,"stop_reason":"complete","race_ids":["HK20260627ST02","HK20260627ST03"],"races_imported":2,"unique_horses_found":28,"horse_profiles_fetched":28,"limit_horses":null,"max_requests":100}`
- 请求日志：`30` 条，全部 HTTP `200`

### 执行后复查

- `ExternalDataImportRun(status="started")=0`
- HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`
- 无 `umanewsbot-web-run-*` 临时容器残留
- `http://umafans.run/healthz/`：`200`
- `http://127.0.0.1/healthz/`：`200`

## 2026-06-30 HKJC 慢速 dry-run 延伸到 2024-07

本次按用户要求把香港 HKJC 慢速抓取窗口延伸到 `2024-07-01`。执行口径仍为 dry-run，不执行生产 `--commit`，不写正式表。

### 长窗口 plan-only

```bash
cd /opt/umanewsbot
mkdir -p runtime/global_racing_import/hkjc-20260701-to-202407
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps -T \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=600 \
  web python manage.py import_hkjc_external_data \
  --start-date 2024-07-01 \
  --end-date 2026-06-30 \
  --plan-only \
  --limit-races 20 \
  --max-requests 600 \
  --allow-network \
  > runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json
```

结果：

- 输出：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json`
- `race_count=1496`
- `batch_count=75`
- `request_count=254`
- `request_statuses={"200":253,"missing":1}`
- 最后一个 plan 批次覆盖 `2024-09-11` 与 `2024-09-08`；`2024-07-01` 至 `2024-09` 之间没有更早的本地 `HV/ST` HKJC 场次进入计划。

### 后台 worker

运行脚本：

```bash
/opt/umanewsbot/runtime/global_racing_import/hkjc-20260701-to-202407/run_hkjc_slow_dryrun_to_202407.sh
```

关键文件：

- PID：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.pid`
- 状态：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.state`
- 日志：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.log`
- 输出：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-mini-races-*-dryrun.json`

运行参数：

- 每批 `5` 场
- `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`
- `HKJC_IMPORT_MAX_REQUESTS_PER_RUN=140`
- 批次间暂停 `60` 秒
- 从状态 `2` 开始，跳过已完成的 `HK20260627ST02,HK20260627ST03` 两场证据

### 启动后证据

- `races=3-7/1496`：`completion.is_complete=true`，`coverage_stats={"races":5,"entries":67,"results":67,"horses":67}`，有 `1` 次 horse profile 初始 `ReadTimeout` attempt，但最终 `horse_profiles_fetched=67`。
- `races=8-12/1496`：`completion.is_complete=true`，`coverage_stats={"races":5,"entries":66,"results":66,"horses":66}`，`request_count=71`，`non_200_request_attempts=0`。
- 截至记录时 worker 已进入 `races=13-17/1496`。

### 监控命令

```bash
cd /opt/umanewsbot
OUT_DIR=runtime/global_racing_import/hkjc-20260701-to-202407
cat "$OUT_DIR/hkjc-slow-dryrun.pid"
cat "$OUT_DIR/hkjc-slow-dryrun.state"
tail -40 "$OUT_DIR/hkjc-slow-dryrun.log"
pgrep -af "run_hkjc_slow_dryrun_to_202407|import_hkjc_external_data"
docker ps --format "{{.Names}} {{.Status}}" | grep "umanewsbot-web-run" || true
```

停止 worker：

```bash
cd /opt/umanewsbot
kill "$(cat runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.pid)"
```

不要在 worker 运行时执行生产部署、重建容器或修改运行脚本的 `git pull`；需要同步文档时，先推 GitHub，等抓取暂停后再同步生产工作树。

## 多地区新闻常态生产灰度运行手册

本节只覆盖新闻来源常态抓取、自动发布灰度、地区运营观测和 QQ 群推送灰度；HKJC / UK / France / US 外部赛马数据库 importer 仍是独立受控导入，不进入新闻 Celery Beat。

### 启用前只读审计

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web \
  python manage.py audit_multiregion_news_production
```

如需留存基线：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web \
  python manage.py audit_multiregion_news_production \
  --output multiregion-news-baseline-$(date +%Y%m%d_%H%M%S).json
```

该命令只读查询 `NewsSource / CrawlJob / NewsArticle / QQPushDelivery / TermEntry / TermCandidate / ExternalHorseAlias`，不会创建 `CrawlJob`、`NewsArticle`、`QQPushDelivery` 或 `ExternalDataImportRun`。

### 灰度开启顺序

1. 备份 `.env`：

```bash
cp .env .env.backup.multiregion-news-$(date +%Y%m%d_%H%M%S)
```

2. 先只允许少量地区和来源进入通用轮询：

```dotenv
NEWS_SOURCE_POLL_ENABLED=true
NEWS_SOURCE_POLL_INTERVAL_MINUTES=30
NEWS_SOURCE_POLL_MAX_SOURCES=2
NEWS_SOURCE_POLL_ALLOWED_REGIONS=hong_kong,united_kingdom
NEWS_SOURCE_POLL_ALLOWED_SOURCES=hkjc_news:latest,scmp_racing:latest,sporting_life:latest,sky_sports_racing:latest
```

3. 自动发布默认仍保守。非日本地区只有显式配置后才允许自动发布：

```dotenv
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=hong_kong
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=hkjc_news:latest
MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS=hong_kong:1
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=hong_kong:3
MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD=50
```

4. QQ 灰度继续以群级 `PushTarget.allowed_regions` 为准。测试群可显式加入 `hong_kong / united_kingdom`，正式群不得因为 `QQ_PUSH_ENABLED=true` 自动接收新地区。

5. 重启 `worker / beat / web` 后观察至少一个自然调度窗口：

```bash
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
curl -I http://127.0.0.1/healthz/
curl -I http://umafans.run/
```

### 后台验收入口

- `/admin/regions/`：地区生产概览，查看今日新增、待翻译、翻译失败、待审核、自动发布、人工发布、公开数量、近期 QQ 交付和术语候选积压。
- `/admin/sources/?region=hong_kong`：按地区筛选来源健康，确认成功、成功无新增、运行中、运行超时、失败和长时间未运行。
- `/admin/` 首页与公开首页地区 tab：确认后台与前台状态一致。

### 停用和回滚

如任一地区出现来源异常、翻译质量异常、候选池积压或 QQ 推送异常，按风险从小到大收敛：

```dotenv
NEWS_SOURCE_POLL_ENABLED=false
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=
QQ_PUSH_ENABLED=false
```

也可只收窄某个群的 `PushTarget.allowed_regions` 为 `["japan"]`，或在后台停用具体 `NewsSource.enabled`。停用后重新执行只读审计并检查 `worker / beat` 日志，确认没有新的国际来源轮询和异常 QQ 交付。

## 2026-06-30 多地区新闻常态生产部署与归档

### 部署前互斥处理

- 部署前生产服务器 `/opt/umanewsbot` 运行 `main` 的 `7b6e51b`。
- HKJC 长窗口 dry-run worker 正在运行，`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.state=92`，并存在临时 `umanewsbot-web-run-*` 容器。
- 为避免部署与长任务重叠，已先停止 `hkjc-slow-dryrun.pid` 对应 wrapper，并停止临时 `umanewsbot-web-run-*` 容器。
- 暂停后复查：`ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`。

### 部署步骤与结果

- 本地实现提交 `62a0f9a` 已快进推送到 `main`。
- 生产 `.env` 备份：`.env.backup.multiregion-news-20260630_185150`。
- 服务器执行 `git pull --ff-only origin main`，从 `7b6e51b` 更新到 `62a0f9a`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移已应用：`stable.0014_multiregion_news_indexes`、`stable.0015_termentry_racing_region`。
- `collectstatic` 结果：`0 static files copied`，`129 unmodified`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。

### 验证结果

- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- `python manage.py showmigrations stable`：`0014`、`0015` 均为 `[X]`。
- `http://umafans.run/healthz/`：`200`。
- `http://umafans.run/`：`200`。
- `http://umafans.run/admin/login/`：`200`。
- `http://umafans.run/admin/regions/`：`302` 到 `/admin/login/?next=/admin/regions/`，路由存在且受后台登录保护。
- `python manage.py audit_multiregion_news_production`：只读审计可输出 `japan / hong_kong / united_kingdom / france / united_states` 五个地区；生产设置仍为 `NEWS_SOURCE_POLL_ENABLED=false`，非日本自动发布 allowlist 为空。

### 归档结果

- 旧规格流程 change：`operate-multiregion-news-production`。
- 归档目录：`旧规格流程/changes/archive/2026-06-30-operate-multiregion-news-production/`。
- 正式规格已同步：
  - `旧规格流程/specs/multiregion-news-production/spec.md`
  - `旧规格流程/specs/crawl-freshness-and-source-health/spec.md`
  - `旧规格流程/specs/automation-publish-gates/spec.md`
  - `旧规格流程/specs/qqbot-auto-push/spec.md`
  - `旧规格流程/specs/termbase-and-race-priority/spec.md`

### 后续注意

- 本次部署只上线能力与安全默认配置，不直接开启通用国际来源轮询。
- 如需继续 HKJC 长窗口 dry-run，应从 `hkjc-slow-dryrun.state=92` 对应进度恢复或重新渲染剩余批次；恢复前再次确认不与部署、重建容器或 `git pull` 重叠。

## 2026-06-30 多地区新闻生产开关开启

### 开启范围

按用户要求开启多地区新闻生产相关开关。本次只调整 `.env` 中多地区新闻生产配置，不恢复 HKJC 长窗口 dry-run，不修改数据库、翻译 Key 或 OneBot token。

备份：

- `.env.backup.enable-all-multiregion-20260630_203647`

当前生产配置：

```dotenv
NEWS_SOURCE_POLL_ENABLED=true
NEWS_SOURCE_POLL_INTERVAL_MINUTES=30
NEWS_SOURCE_POLL_MAX_SOURCES=12
NEWS_SOURCE_POLL_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states
NEWS_SOURCE_POLL_ALLOWED_SOURCES=
NEWS_SOURCE_POLL_RUNNING_TIMEOUT_MINUTES=60
NEWS_SOURCE_POLL_RETRY_STALE_RUNNING=false
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=hong_kong,united_kingdom,france,united_states
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=hkjc_news:latest,scmp_racing:latest,sporting_life:latest,sky_sports_racing:latest,sky_sports_racing:access,france_galop_news:official,tdn_france:latest,tdn:latest,horse_racing_nation:latest,horse_racing_nation:access
MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS=hong_kong:2,united_kingdom:2,france:1,united_states:1
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=hong_kong:5,united_kingdom:5,france:3,united_states:3
MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD=50
```

### 重启与验证

- 已重启 `web / worker / beat`。
- `manage.py check`：通过。
- `http://127.0.0.1/healthz/`：`200`。
- `http://umafans.run/healthz/`：`200`。
- `http://umafans.run/`：`200`。
- Django settings 确认 `NEWS_SOURCE_POLL_ENABLED=true`，地区与来源 allowlist 已按上述配置生效。

### 通用轮询 smoke

手动执行 `crawl_enabled_news_sources_task.run()` 后，选中并派发 `12` 个 due 来源：

- `sponichi:latest`
- `sponichi:access`
- `hkjc_news:latest`
- `scmp_racing:latest`
- `sky_sports_racing:access`
- `sporting_life:latest`
- `sky_sports_racing:latest`
- `france_galop_news:official`
- `tdn_france:latest`
- `tdn:latest`
- `horse_racing_nation:access`
- `horse_racing_nation:latest`

固定调度来源被正确跳过：

- `netkeiba:latest`
- `netkeiba:access`
- `netkeiba:attention`
- `jra:official`

当前 worker 并发为 `2`，因此 smoke 后先进入 active 的是两个 Sponichi 抓取任务，其余来源会随队列继续消化。

### 快速回滚

如国际来源抓取、翻译、自动发布或 QQ 推送出现异常，优先按以下顺序收敛：

```dotenv
NEWS_SOURCE_POLL_ENABLED=false
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=
QQ_PUSH_ENABLED=false
```

修改 `.env` 后重启 `web / worker / beat`，再执行 `audit_multiregion_news_production` 和日志检查。

## 2026-07-01 全部 旧规格流程 归档与生产部署

### 范围

- 归档 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send`。
- 同步正式规格到 `旧规格流程/specs/external-horse-data-import/`、`旧规格流程/specs/international-racing-coverage/` 及相关能力规格。
- 补齐 `ExternalDataSource` choices：`sporting_life`、`france_galop`、`geny_france`、`horse_racing_nation`。
- 新增并应用迁移 `stable.0016_alter_externaldataimporterror_source_and_more`。

### 本地验证

- `旧规格流程 list --json`：`changes=[]`。
- `旧规格流程 validate --all`：12 项通过。
- `DB_ENGINE=sqlite python server/manage.py check`：通过。
- `DB_ENGINE=sqlite python server/manage.py makemigrations --check --dry-run`：`No changes detected`。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py test stable --noinput`：362 项通过。
- `git diff --check`：通过。

### 生产部署

部署前检查：

- 服务器 `/opt/umanewsbot` 部署前 HEAD：`538a1a9`。
- `docker compose -f docker-compose.prod.lowcost.yml ps`：`web / db / redis` healthy，`worker / beat / nginx` 运行。
- `ExternalDataImportRun(status="started")=0`。
- `ExternalDataImportLock` 中 HKJC 与 netkeiba 均未占用锁。
- HKJC 长窗口 dry-run 未运行，仍按此前记录暂停在 `hkjc-slow-dryrun.state=92`。

备份：

- `backups/db/pre-archive-all-20260701_153301.sql.gz`
- `gzip -t`：通过。

执行：

```bash
cd /opt/umanewsbot
git fetch origin main
git pull --ff-only origin main
bash ./deploy_lowcost.sh
```

结果：

- 服务器已快进到 `8c83708`。
- `web / worker / beat` 已重建。
- 迁移日志确认 `Applying stable.0016_alter_externaldataimporterror_source_and_more... OK`。
- `collectstatic` 完成，`web` healthy。

### 生产验收

- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- `showmigrations stable`：`0016_alter_externaldataimporterror_source_and_more` 为 `[X]`。
- `ExternalDataSource.values`：`netkeiba / hkjc / sporting_life / france_galop / geny_france / horse_racing_nation`。
- `http://127.0.0.1/healthz/`：`200`。
- `http://umafans.run/healthz/`：`200`。
- `http://umafans.run/`：`200`。
- `http://umafans.run/admin/login/`：`200`。
- `http://umafans.run/admin/regions/`：未登录请求 `302` 到登录页；已登录浏览器可打开地区生产页。
- 浏览器验收：首页地区 tab 正常，香港/英国地区页可渲染已发布国际新闻，后台地区生产页显示五地区来源、今日新增、待审核、公开和 QQ 状态。

### 生产开关与来源状态

当前生产 settings：

```text
NEWS_SOURCE_POLL_ENABLED=True
NEWS_SOURCE_POLL_INTERVAL_MINUTES=30
NEWS_SOURCE_POLL_MAX_SOURCES=12
NEWS_SOURCE_POLL_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=hong_kong,united_kingdom,france,united_states
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=hong_kong:5,united_kingdom:5,france:3,united_states:3
QQ_PUSH_ENABLED=True
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
```

enabled 来源最近状态显示五地区均有来源记录，多数为 `success`。当前仅 `Sponichi 新闻ランキング` 最近一次为上游 `502 Bad Gateway`，其余日本、香港、英国、法国、美国 enabled 来源最近状态为 `success`。该 502 属于来源站点临时响应异常，不阻断本次部署验收。

## 2026-07-01 多地区新闻增量窗口部署注意事项

本节对应 旧规格流程 change `increase-multiregion-news-volume`。该变更包含新迁移和新 Celery Beat 项，部署后默认关闭。

### 部署前

1. 备份生产数据库和 `.env`。
2. 确认没有运行中的外部数据 importer、长窗口 dry-run 或手工导入任务。
3. 部署前本地必须通过：

```bash
DB_ENGINE=sqlite python server/manage.py check
DB_ENGINE=sqlite python server/manage.py makemigrations --check --dry-run
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py test stable.tests.ProductionWindowModelTests stable.tests.ProductionWindowServiceTests stable.tests.PublishWindowServiceTests stable.tests.QQWindowServiceTests --noinput
旧规格流程 validate increase-multiregion-news-volume --strict
旧规格流程 validate --all
git diff --check
```

### 默认关闭验证

迁移和重启后先确认以下开关仍为关闭：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_ENABLED=false
MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=false
MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=false
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=false
```

执行只读审计：

```bash
python manage.py audit_multiregion_news_production --output multiregion-window-audit.json
```

重点查看 `settings`、各地区 `sources.production_approved`、`sources.backoff_active`、`production_windows` 和 `quota_exhausted`。

### 启用顺序

建议按以下顺序启用：

1. 标记来源 `production_approved=true`，确认没有高风险或需长间隔来源被误纳入。
2. 设置 `MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states`。
3. 开启总开关和抓取窗口，观察最近 4 个抓取窗口。
4. 开启发布窗口，观察最近 4 个发布窗口，每地区每窗口应为 `0-5` 篇，0 篇必须有 `reason_summary` 或候选决策原因。
5. 开启 QQ 窗口，观察最近 4 个 QQ 窗口，每地区每窗口最多 3 篇，保底文章不应自动 QQ。

### 快速回滚

优先使用分链路回滚：

```dotenv
MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS=true
MULTIREGION_ROLLBACK_DISABLE_PUBLISH_WINDOWS=true
MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS=true
MULTIREGION_ROLLBACK_DISABLE_OPS_NOTIFICATIONS=true
```

如需完全关闭新窗口：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_ENABLED=false
```

QQ 限流或 OneBot 异常时优先关闭：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=false
QQ_PUSH_ENABLED=false
```

## 2026-07-02 多地区新闻增量窗口生产上线记录

本节对应 旧规格流程 change `increase-multiregion-news-volume`。

### 部署前检查

- 生产目录：`/opt/umanewsbot`。
- 部署前 `HEAD=80454c6`，`origin/main=b7b0ce0`；上线修复后最终运行 `HEAD=9e97e8c`。
- 外部数据导入锁检查：`hkjc / netkeiba` 均无占用者；未发现运行中的 HKJC/global racing/import 进程。
- 备份：
  - `.env.backup.multiregion-volume-20260702_040811`
  - `backups/db/pre-multiregion-volume-20260702_040811.sql.gz`
  - `gzip -t`：通过。

### 部署与迁移

执行：

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
bash ./deploy_lowcost.sh
```

结果：

- 迁移已应用：
  - `stable.0017_majorraceevent_productionwindow_quotaledger_and_more`
  - `stable.0018_alter_notificationlog_type`
- `web / worker / beat` 已重建并运行。
- `docker compose -f docker-compose.prod.lowcost.yml ps` 显示 `web` healthy，`db / redis` healthy。
- `manage.py check`：通过。
- `http://127.0.0.1/healthz/`：`200`。
- `http://umafans.run/healthz/`：`200`。

### 启用开关

启用前备份 `.env`：

```text
.env.backup.enable-multiregion-volume-20260702_041242
```

当前生产窗口配置：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states
MULTIREGION_PRODUCTION_WINDOW_DAILY_MINUTES=15
MULTIREGION_PRODUCTION_WINDOW_MAJOR_RACE_MINUTES=5
MULTIREGION_PRODUCTION_WINDOW_LOOKBACK_HOURS=3
MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15
MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5
MULTIREGION_PUBLISH_REGION_WINDOW_MIN=1
MULTIREGION_QQ_REGION_WINDOW_MAX=3
MULTIREGION_OPS_NOTIFICATIONS_ENABLED=true
MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID=1026525240
```

当前 16 个启用新闻源均已标记 `production_approved=true`。活跃 QQ 目标为 `UmaFans测试群`，群号 `1026525240`，允许 `japan / hong_kong / united_kingdom / france / united_states`。

### 上线中修复

首次真实抓取窗口暴露问题：`crawl_production_sources_window_task` 把 Celery `AsyncResult` 直接写入 `ProductionWindow.result_payload`，触发 `Object of type AsyncResult is not JSON serializable`。

处理：

1. 临时设置 `MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS=true`，避免 beat 继续制造失败抓取窗口。
2. 修复代码，将异步派发结果序列化为 `{"task_id": "..."}`。
3. 新增测试 `test_crawl_window_serializes_async_dispatch_result`。
4. 验证：
   - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ProductionWindowServiceTests stable.tests.PublishWindowServiceTests stable.tests.QQWindowServiceTests stable.tests.MultiRegionNewsProductionTests --noinput`：51 项通过。
   - `DB_ENGINE=sqlite python manage.py check`：通过。
   - `git diff --check`：通过。
5. 提交并部署 `9e97e8c Fix crawl window async dispatch payload`。
6. 恢复 `MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS=false`。

### 生产验收结果

- 默认关闭验证：启用前抓取、发布、QQ 三条窗口任务均返回 `disabled`。
- 生产资格审计：五地区生产窗口开关为开启；批准来源数为日本 6、香港 2、英国 3、法国 2、美国 3。
- 20:15 抓取窗口：15 个 due 来源被派发；最终 14 个成功，1 个失败。
  - 失败来源：`Sponichi 新闻ランキング`
  - 失败原因：上游详情页 `502 Bad Gateway`
- 20:15 发布窗口：
  - 香港：发布 1 篇。
  - 美国：发布 3 篇。
  - 日本、英国、法国：`no_ready_candidates`。
- 20:30 发布窗口：
  - 美国：发布 1 篇。
  - 日本、香港、英国、法国：`no_ready_candidates`。
- 20:15 QQ 窗口：
  - 美国：生成并发送 2 条 delivery。
  - 日本、香港、英国、法国：`no_eligible_articles`。
- 20:30 QQ 窗口：
  - 美国：`already_sent`。
  - 日本、香港、英国、法国：`no_eligible_articles`。
- Celery inspect：`active/reserved` 为空。
- ops 摘要通知：`NotificationLog #13051`，channel=`qq`，target=`1026525240`，status=`sent`。
- 浏览器验收：
  - `http://umafans.run/` 首页正常展示 20:15 窗口新发布的香港和美国文章。
  - `/?region=hong_kong`、`/?region=united_states`、`/?region=japan` 可展示对应地区新闻。
  - 英国、法国地区页可正常渲染，当前本轮无新 ready 候选。

### 继续观察项

- 因上线时间为后半夜新闻低峰，用户确认跳过继续等待 20:45 及后续自然窗口；最近 4 个自然窗口口径改为次日继续验证。
- `Sponichi 新闻ランキング` 当前失败为上游 `502`，如连续失败达到阈值会进入来源 backoff；必要时可在后台单来源暂停或降频。
- `TDN 美国新闻` 每轮最多 20 条列表且详情请求超时为 15 秒，单轮耗时可能偏长；如持续占用 worker，可另起优化将每轮详情数量做成配置或拆分任务。
- 生产构建上下文约 425MB，紧急修复发布时镜像构建前置上传较慢；后续应优化 `.dockerignore`。

### 2026-07-02 白天自然窗口复核

- 生产代码：`a122130`，`origin/main` 同步到同一提交。
- 容器状态：`web / worker / beat / db / redis / nginx` 均运行；`web` 与 `redis / db` healthy。
- 健康检查：
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://umafans.run/healthz/`：`200`。
  - `http://umafans.run/`：`200`。
  - 抽检 `/news/6374/`、`/news/6426/`、`/news/6368/`：均 `200`。
- Celery：`inspect active reserved` 返回空，无积压任务。
- 开关配置：抓取 / 发布 / QQ 生产窗口均为 `true`；允许五地区；日常 `15` 分钟、重要赛事 `5` 分钟；发布每地区每窗口 `1-5` 篇；QQ 每地区每窗口最多 `3` 篇；当前没有地区处于重要赛事升频窗口。
- 最近 6 小时窗口结果：
  - 发布窗口：五地区各 `24` 个窗口。非零发布为美国 `04:30` 1 篇，日本 `04:45` 2 篇、`05:30` 4 篇、`06:30 / 08:15 / 09:45` 各 1 篇；所有非零窗口均未超过 5 篇。
  - 0 发布原因：其余发布窗口均为 `no_ready_candidates`。
  - QQ 窗口：五地区各 `24` 个窗口。实际发送 6 条，美国 3 条、日本 3 条，目标均为 `UmaFans测试群(1026525240)`；其余窗口为 `no_eligible_articles` 或 `already_sent`。
  - 抓取窗口：`succeeded/completed=260`，`skipped/coalesced_to_latest_crawl_window=109`，后者符合停机 / 延迟恢复时只补最近窗口的设计。
  - 来源状态：16 个 `enabled=true` 且 `production_approved=true` 来源最新抓取均为 `success`；`TDN France Galop 关键词英文新闻` 和 `TDN 美国新闻` 仍显示已过期 `backoff_until`，但最新抓取窗口已成功完成，当前不影响运行。
- 结论：白天最近几个自然窗口满足本期诉求：五地区窗口按 15 分钟节奏产生，发布 / QQ 上限未突破，0 结果有明确原因，生产服务和队列健康。

### 2026-07-02 11:07 最新窗口按地区拆因

- 复核口径：最新 4 个发布窗口（`10:15 / 10:30 / 10:45 / 11:00`，CST）+ 发布候选 3 小时回看。
- 五地区最新 4 个发布窗口均为 `succeeded / no_ready_candidates`，均未发布新文章。
- 日本：
  - 最近 4 个发布窗口共有 `18` 条候选决策，全部为 `blocked / hard_gate_blocked`。
  - 主要原因：部分文章翻译失败；部分文章进入 `manual_review_required`；高分候选中存在 `core_term_missing` 和轻微数字缺失提示。
  - 结论：日本不是新闻源无内容，也不是抓取整体失效；主因是抓到的候选未通过自动发布门禁或需要人工处理。
- 中国香港：
  - `HKJC Racing News` 与 `SCMP Racing` 最近 3 小时抓取均成功，最新消息分别为 `新增 0，重复 5`、`新增 0，重复 4`。
  - 最近 3 小时没有新入库香港文章，也没有发布候选。
  - 结论：主因是来源没有新稿，只有重复旧稿。
- 英国：
  - `Sporting Life Racing`、`Sky Sports Racing 新闻`、`Sky Sports Racing Top Stories` 最近 3 小时抓取均成功，最新消息为新增 0、重复旧稿。
  - 最近 3 小时没有新入库英国文章，也没有发布候选。
  - 结论：主因是来源没有新稿，只有重复旧稿。
- 法国：
  - `France Galop 英文新闻` 最近抓取成功，新增 0、重复 20。
  - `TDN France Galop 关键词英文新闻` 在 `08:25-09:05` 出现过 `525` / read timeout，`10:10` 已恢复成功，`failure_streak=0`，最新消息为 `新增 0，重复 20`。
  - 最近 3 小时没有新入库法国文章，也没有发布候选。
  - 结论：当前主因是来源没有新稿；早间 TDN 短暂失败已恢复，不是最新窗口 0 发布主因。
- 美国：
  - `Horse Racing Nation 新闻` 与 `Horse Racing Nation Trending` 最近抓取成功，新增 0、重复旧稿。
  - `TDN 美国新闻` 在 `08:25-09:05` 出现过 read timeout，`10:10` 已恢复成功，`failure_streak=0`，最新消息为 `新增 0，重复 20`。
  - 最近 3 小时没有新入库美国文章，也没有发布候选。
  - 结论：当前主因是来源没有新稿；早间 TDN 短暂失败已恢复，不是最新窗口 0 发布主因。

## 多地区归属与英文门禁上线检查

适用 change：`support-multiregion-news-attribution-and-english-gates`。

上线前：

1. 备份生产数据库。
2. 确认待部署代码包含迁移 `stable.0023_multiregion_news_attribution`，并依赖已上线的 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more`。
3. 本地或 CI 需通过：
   - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`
   - `.venv/bin/python server/manage.py makemigrations --check --dry-run`
   - `.venv/bin/python server/manage.py test stable.tests.MultiRegionAttributionAndGateTests stable.tests.IngestionSourceElevationTests stable.tests.InternationalSourceMetadataTests stable.tests.MultiRegionNewsProductionTests stable.tests.TermRegionFilterTests stable.tests.QQAutoPushTests stable.tests.QQWindowServiceTests stable.tests.PublishWindowServiceTests --keepdb`
   - `旧规格流程 validate support-multiregion-news-attribution-and-english-gates --strict`
4. 如本地没有 `.env`，`docker compose ... config` 可临时复制 `.env.example` 为 `.env`，校验后立即删除。

上线后：

1. 执行迁移并确认：
   - `.venv/bin/python server/manage.py showmigrations stable | grep 0022`
2. 先 dry-run 重算近期英文门禁文章：
   - `.venv/bin/python server/manage.py reprocess_multiregion_attribution_gates --region france --hours 6 --dry-run --json`
   - `.venv/bin/python server/manage.py reprocess_multiregion_attribution_gates --region united_kingdom --hours 6 --dry-run --json`
   - `.venv/bin/python server/manage.py reprocess_multiregion_attribution_gates --region hong_kong --hours 6 --dry-run --json`
3. 抽样确认 `old_regions / new_regions / inferred_regions / attribution_locked / attribution_applied / blockers` 符合预期后，再按地区小批量 commit。人工锁定文章应保持 `attribution_applied=false`，且 `new_regions` 代表 commit 实际会使用的地区；`scanned_count / candidate_count / has_more_candidates` 用于判断是否需要继续分批，`--limit` 按有效候选数量计算。commit 只恢复候选，不直接发布。
4. 验收公开页：
   - `/`
   - `/?region=france`
   - `/?region=united_kingdom`
   - 抽样文章详情页确认地区标签显示多个地区。
   - 确认主地区单独显示且关联地区不会排在主地区之前；文章编辑页取消全部关联地区后可保存为空。
5. 验收窗口审计：
   - `audit_multiregion_news_production --json` 中确认 `primary_total / related_visible_total`、发布 0 原因、QQ 0 原因正常。
6. 回滚时可先设置：
   - `MULTIREGION_ATTRIBUTION_ENABLED=false`
   - `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`
   - 必要时收窄 `MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`

`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 必须同时让公开地区 tab、公开列表卡片/文章详情地区展示、发布窗口、QQ 窗口和文章发布后的 QQ 即时任务只使用主地区；关联地区数据不删除。验收回滚配置时至少用一篇“英国主地区 + 法国关联地区”文章确认：法国群返回 `region_not_allowed`，首页卡片和文章详情不显示法国关联地区。

迁移回滚一般不建议删除 `NewsArticleRelatedRegion` 表；代码回滚后该表可闲置，不影响旧主地区逻辑。

### 2026-07-02 15:10 最近 2 小时窗口复核

- 复核口径：`13:15` 至 `15:00` 自然窗口，服务器时区 CST。
- 发布窗口：五地区每 15 分钟均生成窗口且状态为 `succeeded`；本时段网页发布 `0` 篇，原因均为 `no_ready_candidates`。
- QQ 窗口：五地区每 15 分钟均生成窗口且状态为 `succeeded`；本时段 QQ delivery `0` 条，原因均为 `no_eligible_articles`。
- 抓取窗口：最近 2 小时新入库 `8` 篇，按地区为日本 `5`、香港 `1`、英国 `2`、法国 `0`、美国 `0`；其中日本存在翻译失败稿，其他候选多为 `manual_review_required / pending_review`，未达到自动发布条件。
- 来源状态：16 个生产批准来源中 14 个最新抓取为 `success`；`TDN France Galop 关键词英文新闻` 与 `TDN 美国新闻` 在 `15:02` 各出现一次 read timeout，`failure_streak=1`，属于同一上游站短时超时。
- 结论：窗口调度、发布和 QQ 链路正常运转；当前 0 发布不是系统停摆，而是候选未通过自动发布资格或来源暂无新稿。后续可改进 `WindowCandidateDecision.payload`，在 `hard_gate_blocked` 时写入更具体的 blocker 明细，降低排障成本。

### 2026-07-03 00:13 今日窗口复核

- 复核口径：`2026-07-03 00:00` 至 `00:13`，服务器时区 CST；因刚过零点，今日目前只有 `00:00` 一个自然窗口。
- 抓取窗口：五地区均成功。日本 `5` 个来源新增 `0`、重复 `274`；香港 `2` 个来源新增 `0`、重复 `9`；英国 `3` 个来源新增 `0`、重复 `42`；法国 `2` 个来源新增 `0`、重复 `40`；美国 `3` 个来源新增 `1`、重复 `47`。
- 新入库文章：美国 TDN 新闻 `article_id=6500`，标题 `Book'em Danno Day Scheduled For July 17 At Monmouth Park`，已翻译，当前 `manual_review_required / pending_review`，未自动发布。
- 发布窗口：五地区均 `succeeded`，网页发布 `0` 篇，原因均为 `no_ready_candidates`；日本有 `2` 条 blocked 候选、英国 `4` 条、美国 `4` 条。
- QQ 窗口：五地区均 `succeeded`，delivery `0` 条；日本 / 美国原因 `already_sent`，香港 / 英国 / 法国原因 `no_eligible_articles`。
- 来源状态：16 个生产批准来源最新抓取均为 `success`，前一日 TDN France / TDN 美国 read timeout 已恢复。
- 结论：今日首个窗口调度正常，暂无发布不是系统问题；需要继续等更多自然窗口累积样本。

### 2026-07-03 复核 2026-07-02 全日窗口

- 复核口径：`2026-07-02 00:00-24:00`，服务器时区 CST。多地区生产窗口昨日从 `04:00` 开始有账本，因此实际覆盖 `04:00-23:45` 共 `80` 个 15 分钟窗口起点。
- 发布窗口：
  - 五地区各 `80` 个窗口，全部 `succeeded`，无 `failed / partial`。
  - 窗口发布：日本 `37` 篇、香港 `1` 篇、美国 `10` 篇、英国 `0`、法国 `0`。
  - 非零发布窗口均未超过每地区每窗口 `5` 篇；0 发布主因是 `no_ready_candidates`。候选决策中日本 `576` 条、香港 `45` 条、英国 `68` 条、法国 `11` 条、美国 `157` 条为 `hard_gate_blocked`。
- QQ 窗口：
  - 五地区各 `80` 个窗口，全部 `succeeded`，无 `failed / partial`。
  - 窗口派发：日本 `3` 条、美国 `5` 条，香港 / 英国 / 法国为 `0`；无 failed delivery。
  - 昨日 `QQPushDelivery` 记录按创建时间统计为日本 `15` 条、美国 `9` 条，全部 `sent`；窗口内较多 `already_sent` 表示推送记录已由发布触发链路创建并发送，不是 QQ 失败。
- 抓取窗口：
  - 抓取窗口无 `failed`。按窗口 payload 统计新增：日本 `79`、香港 `5`、英国 `11`、法国 `1`、美国 `28`。
  - 日本出现 `7` 次榜单唤醒，说明 `ranked_revived_at` 链路已有生产命中。
  - `coalesced_to_latest_crawl_window` 为恢复 / 延迟场景下只补最近窗口的预期跳过；昨日也记录了 Sponichi 上游 `502`、TDN read timeout / 525 等上游短时异常，但最终截至 `2026-07-03 00:13`，16 个生产批准来源最新状态均为 `success`。
- 文章口径：
  - 昨日新入库：日本 `93`、香港 `6`、英国 `13`、法国 `1`、美国 `37`。
  - 昨日按 `published_to_web_at` 统计公开：日本 `38`、香港 `1`、美国 `13`、英国 `0`、法国 `0`；该口径包含窗口外或已存在文章后续公开，因此与窗口直接发布数略有差异。
- 结论：昨日窗口健康。发布 / QQ 调度成功率为 100%，没有窗口级失败；发布量没有超上限，QQ 没有失败；主要限制是候选质量与门禁，英国 / 法国仍没有自动发布成功。

### 2026-07-03 地区归属错配只读审计

- 复核问题：当前文章地区完全按新闻源地区写入；用户提出两类更合理逻辑：
  - 第一种：新闻源地区与马 / 骑手 / 赛事任一实体地区一致时按新闻源地区；若实体全为另一地区则按该地区；若实体均非新闻源且互不相同，则按赛事、马、骑手优先级归属。
  - 第二种：马 / 骑手 / 赛事涉及多个地区时，文章应属于全部涉及地区。
- 当前字段状态：
  - `NewsArticle.racing_region` 与 `source_config.racing_region` 完全一致：`6598/6598`，现有逻辑确认为“完全按新闻源地区”。
  - 生产 `TermEntry.racing_region` 目前没有可用实体地区：马 `1884`、赛事 `153`、骑手 `2` 均为空地区。
  - `MajorRaceEvent` 当前为空。
  - 外部缓存实体地区主要只有日本：`ExternalHorseAlias` 日本 `12421` 条，香港 `4` 条；英法美外部马名 / 赛事 proof 尚未写入正式缓存表。
- 严格结构化审计结果：
  - 有明确实体地区证据的文章：`462/6598`，且全部为当前日本文章。
  - 按第一种逻辑推断错配：`0`。
  - 按第二种逻辑推断单地区不完整或错配：`0`。
  - `2026-06-30` 以来：`544` 篇中有实体地区证据 `214` 篇，错配 `0`。
  - `2026-07-02`：`150` 篇中有实体地区证据 `49` 篇，错配 `0`。
- 限制与风险：
  - 上述 `0` 是“当前结构化数据能证明的下限”，不能说明真实业务没有错配。
  - 非日本文章的 `translation_metadata.terms / recognized_horse_names` 当前基本为空；英文来源中出现的 `Yutaka Take / Japan Cup / Forever Young / Royal Ascot / Arc` 等实体，没有稳定地区识别。
  - 关键词粗扫发现 `1213` 篇疑似跨地区提及，其中 `2026-06-30` 以来 `231` 篇、`2026-07-02` `60` 篇；该口径噪声较高，只能作为后续设计实体地区识别的参考线索。
- 结论：当前没有结构化证据显示已入库文章违反第一种或第二种逻辑，但这是因为实体地区识别底座不足。若要真正按第一种或第二种逻辑运行，需要先补齐马 / 骑手 / 赛事地区维表与英文别名识别，再把文章从单 `racing_region` 升级为“主地区 + 涉及地区集合”或等价索引。

### 2026-07-02 榜单唤醒未发布文章上线准备

- 变更：`revive-ranked-news-for-publish`。
- 状态：已完成、归档并部署生产。
- 数据库迁移：新增 `server/stable/migrations/0019_newsarticle_ranked_revived_at.py`，为 `NewsArticle` 增加 nullable/indexed `ranked_revived_at` 字段；历史文章默认 `NULL`，不回填。
- 部署记录：
  - 本地提交 `a774672` 已推送到 `origin/main`，服务器 `/opt/umanewsbot` 从 `a122130` 快进到 `a774672`。
  - 部署前备份 `.env`：`.env.backup.ranked-revival-20260702_145529`。
  - 部署前数据库备份：`backups/db/pre-ranked-revival-20260702_145529.sql.gz`，已执行 `gzip -t` 校验。
  - 执行 `bash ./deploy_lowcost.sh` 成功，`web / worker / beat` 已重建，`db / redis / nginx` 正常。
  - `showmigrations stable` 确认 `[X] 0019_newsarticle_ranked_revived_at`。
  - `manage.py check` 通过；生产 shell 确认 `NewsArticle.ranked_revived_at` 为 `null=True db_index=True`，`revive_article_after_ranked_source_elevation` 可 import。
  - `http://127.0.0.1/healthz/` 返回 `{"status":"ok"}`，`http://umafans.run/healthz/`、首页和 `/admin/login/` 均返回 `200`。
  - Celery `active/reserved` 为空，`web / worker / beat` 近 80 行日志未见 traceback/error。
- 后续观察：
  1. 观察最近发布窗口的 `WindowCandidateDecision.payload.ranked_revival`、翻译重试任务、重新评分结果和 QQ delivery。
  2. 当新着顺旧稿后续进入榜单时，确认未发布文章走“重试翻译 / 重新评分 / 发布窗口候选”链路，而不是直接发布或直接 QQ 推送。
- 回滚边界：如需回滚代码，`ranked_revived_at` 字段可留存不用，不影响旧逻辑；如需删除字段，后续单独做清理迁移。

### 2026-07-11 赛事历史抓取证据链验收步骤

1. 先运行 plan 阶段，检查 `<run>/expected_targets.json` 和 `review/expected_targets_review.csv`；不得直接修改应到 JSON。
2. 审核无误后编辑固定的 `review/expected_targets_approval.json`，把 `status` 设为 `approved`，填写 `approved_by / approved_at`，并保持其中 `expected_targets_identity.sha256` 与当前文件一致。
3. 只有审批通过后才允许网络 prepare。确认 `<run>/input/events_<region>.csv` 仅包含该地区本次计划目标；不要把工作区共享 `events.csv` 复制进 run 目录代替生成文件。
4. coverage 必须无 blocker；重点检查 `series_needs_review`、`empty_<module>`、`source_url_missing` 和应到/实到差异。
5. apply-check 前准备真实数据库 gzip 备份。工具会完整读取并解压校验，手工写 `backup_gzip_test=passed` 不能替代真实文件。
6. 每个实际 `region + source + modules` 确认记录必须包含 `status=approved`、`confirmed_by`、`confirmed_at`；coverage、dry-run、当前应到清单和批准候选的 SHA-256 必须一致。
7. 只执行 apply-check 生成、带 `--expected-sha256` 的 importer 命令。任何 blocker 出现时重新生成相应证据，不得手改 apply-check 结果绕过。

本轮只完成本地实现与测试，未执行生产赛事抓取或写入。多地区新闻迁移编号为 `stable.0023_multiregion_news_attribution`，部署时必须先确认 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more` 已应用。

第六轮返修补充：

- prepare 会比较当前 `RaceEvent` 与批准快照中的完整 adapter 输入。出现 `changed after approval` 时不要修改快照或 CSV，应删除本次未执行的 run artifact，重新运行 plan 并重新审批。
- importer 的候选保存和 apply 已整批事务化；命令失败后应先确认本批候选和正式赛事数据均未变化，再修正输入重跑。
- 混合来源策略确认必须由 `status=approved` 且带批准人、批准时间的记录提供；pending 记录中的策略 SHA 不生效。
- 当前仍按手动单进程方式执行同一 run，不要同时启动两个 prepare/resume。`--expected-sha256` 保持兼容性可选，但规范批量流程仍只使用 apply-check 生成的命令。

### 2026-07-11 赛事编排与多地区归属灰度部署记录

- 发布提交：`38974f1`；部署前生产提交：`de4bb78`。
- 环境备份：`.env.backup.multiregion-orchestration-20260711_034313`。
- 数据库备份：`backups/db/pre-multiregion-orchestration-20260711_034313.sql.gz`，约 `101M`，`gzip -t` 通过。
- 迁移：`stable.0023_multiregion_news_attribution` 已应用，`NewsArticleRelatedRegion=0`，未回填旧文章。
- 灰度开关：`MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`。
- 五地区只读验收 artifact：`runtime/deployment_acceptance/multiregion-20260711_0352-enabled-dry-run/`。命令仅对子进程临时设置两个开关为 true，没有修改 web/worker/beat 的运行配置。
- 验收结论：英文门禁继续保留 blocker，没有候选被直接发布；但法国样本 `7031` 被推断为英国主地区，日本样本也出现改为中国香港，且部分样本关联三至四个地区。归属产品口径未通过，不得开启生产开关或执行 commit。
- 赛事编排命令已部署并通过 `--help` smoke；本次未运行网络 prepare、未执行赛事 apply。
- 部署后：六个容器正常，Django check 通过；本地和 Host `/healthz/` 正常；首页、法国/英国地区页、后台登录均为 `200`；web/worker 近 15 分钟未见 error/traceback。

后续启用前必须先完成：

1. 产品确认主地区是否允许被弱实体信号覆盖，以及赛事、马、骑手、来源之间的优先级。
2. 产品确认关联地区上限，避免普通文章一次进入三至四个地区池。
3. 修正规则后重新执行五地区真实文章 dry-run，并人工抽检 `old_regions / new_regions / blockers`。
4. 五地区均通过后才修改 `.env` 开关并重建 web/worker/beat；仍先保持 `--commit` 禁止，观察自然新稿后再决定历史回填。

### 2026-07-11 赛事编排归档与归属短路热修复上线

- 生产发布提交：`6e2cc92`；本次更新前生产提交：`87ac1b2`。
- 上线前停止 beat 防止继续派发，确认没有运行中的外部数据导入；停止旧 worker 后不 purge Redis 队列，使未确认任务由新 worker 恢复处理。
- 环境备份：`.env.backup.orchestration-hotfix-20260711_093556`。
- 数据库备份：`backups/db/pre-orchestration-hotfix-20260711_093556.sql.gz`，约 `102M`，`gzip -t` 通过。
- 执行 `bash ./deploy_lowcost.sh` 成功；无新增迁移，`stable.0023_multiregion_news_attribution` 保持已应用。web、worker、beat 已按新镜像重建，db、redis、nginx 正常。
- 上线过程中发现归属功能关闭时 `apply_article_attribution()` 仍先执行完整术语扫描，造成两个 crawl worker 子进程长时间高 CPU。提交 `6e2cc92` 将功能关闭和人工锁定场景前置短路；本地完整 `stable` 测试 `591` 项通过。
- 生产只读验证使用现有文章调用 `apply_article_attribution(save=False)`，并 mock `infer_article_attribution()`：结果为 `attribution_disabled` 且 mock 未被调用。worker CPU 后续降至约 `0.04%`；抓取积压已处理，Celery reserved 为空，仅观察到正常术语发现任务；近 10 分钟日志无 traceback/error。
- 外部数据导入锁表保留 `hkjc / netkeiba` 两条来源记录，但 `locked_by_run_id` 和 `acquired_at` 均为空，不是持有中的锁；运行中导入为 `0`。
- 接口验收：本机与公网 `/healthz/`、`/`、`/?region=france`、`/?region=united_kingdom`、`/races/`、`/admin/login/` 均返回 `200`。
- 浏览器验收：应用内浏览器真实打开首页、法国频道、英国频道、赛事日历和后台登录页；页面标题、地区导航、新闻列表、赛事表格和登录控件均正常渲染。
- 生产开关继续保持 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`。`support-multiregion-news-attribution-and-english-gates` 的五地区产品抽样仍未通过，任务 `9.6` 不得勾选；本次未执行 `reprocess_multiregion_attribution_gates --commit`，也未执行赛事网络 prepare/apply。

### 2026-07-11 第一批赛事应到清单

- 生产 run：`runtime/race_event_crawl_runs/first-acceptance-race-event-crawl-20260711/`。
- 本地审核副本：同路径同步到本地工作区，运行产物由 `.gitignore` 排除。
- 审核 CSV：`review/expected_targets_review.csv`；审批文件：`review/expected_targets_approval.json`。
- 范围：日本、香港、英国、法国、美国各 1 场已完赛核心赛事，三模块均为 `runners / results / history_winners`。
- 结果：`expected_targets=5`，五地区齐全，全部 `preflight_status=ready`；审批状态为 `pending`。
- 本次 `allow_network=false`，只执行 `plan`，没有网络请求、候选生成或数据库赛事详情写入。
- 原 fixture 中香港杯、凯旋门和简短肯塔基德比种子包含未来赛事或空壳展示行；本批改用生产中已完赛且已有三模块基线的正式赛事行，以便后续验证抓取差异和覆盖保护。
- 用户确认 CSV 中赛事原名、中文名、年份、地区和 slug 前，不得批准应到清单或进入网络 `prepare`。

首批 prepare 前镜像检查：

- `Dockerfile` 必须把 `runtime/tools` 复制到 `/app/runtime/tools`，并让 `/app/server/runtime` 符号链接到 `/app/runtime`；Django 与 AdapterRunner 必须看到同一个 run 根目录。`.dockerignore` 只放行工具目录，仍排除 plans、runs、抓取缓存和其他 runtime artifact。
- 部署后同时检查 `/app/runtime/tools/race_event_request_budget.py` 和 `/app/server/runtime/tools/race_event_request_budget.py`，并逐项检查 plan 中注册 adapter 的脚本存在，再恢复 network run。
- 该检查只确认执行文件可用，不代表允许绕过应到审批、请求预算、coverage、dry-run 或 apply-check。

首批网络抓取 v2 与 v3 处理：

- v2 prepare 共生成 9 条 adapter 候选，请求计数 `49/60`；coverage 为 `blocked`，完整地区为香港、英国、法国，日本和美国不完整，因此未运行 dry-run、apply-check 或正式写入。
- 日本阻断原因是 `prepare_jra_race_detail_candidates.py` 以前按列表序号绑定结果页。单赛事子集会误取 JRA 全年列表第一场，本次把日本德比错配成中山金杯。修复后必须按 `original_name / aliases` 在列表行文本中唯一匹配；零个或多个匹配都直接失败。
- 美国采用明确的混合来源策略：HRN 提供参赛名单，Equibase PDF 提供正式赛果，TOBA 年度分级赛页面提供历届冠军。TOBA 线上 2023-2026 页面当前返回 403，v3 使用此前已成功抓取并留存的同源原始页面；不得手工拼写候选数据。
- v3 与用户批准的五场应到清单逐字段一致，只新增 `us_equibase_results` adapter。prepare 前复用缓存后仍须重新生成候选、运行 mixed-source coverage audit，并确认五个地区的 `runners / results / history_winners` 全部完整；审计未通过时继续禁止 dry-run 和写库。
- adapter 镜像 smoke 不只检查脚本文件存在和 `py_compile`；还要逐项 import 非主应用依赖。Equibase PDF adapter 需要 `pdfplumber==0.11.9`，生产镜像必须通过 `python -c 'import pdfplumber'` 后才允许 resume。
- v3 空缓存重抓在法国探测阶段用尽 `60/60` 请求预算，HRN 因此先生成空候选；不提高预算，改为补入此前留存的同源 HRN 日期页和 Churchill Downs 赛场页。resume 后 HRN 得到 24 匹参赛马且无新增请求，再继续 Equibase 和 TOBA。
- mixed-source coverage 中，声明了模块但 `items=[]` 的候选不得与另一条非空候选形成 `duplicate_candidate`，也不得覆盖非空候选做现有数据完整度比较或 apply scope；如果该模块没有任何非空替代来源，仍必须报告 `empty_<module>`。本规则用于 HRN 空赛果与 Equibase 18 条正式赛果组合。
- 法国 Wikipedia 历史 adapter 在请求预算耗尽后产出空文件时，使用同一历史批次留存的 `source_wiki_search_prix_de_diane_longines.json` 与 `source_wiki_page_prix_de_diane.html` 恢复；仍由原 adapter 重新解析，不直接复制候选 JSONL。
- 当前 adapter canonical query 为 `Prix de Diane`，原搜索缓存请求为同赛事 `Prix de Diane Longines`；保留原文件并以完全相同 SHA-256 建立 `source_wiki_search_prix_de_diane.json` 缓存别名，两个原始证据一并留存。
- aggregate 生成正式 `combined_candidates.jsonl` 时必须剔除显式 `items=[]` 模块；若一条记录剔除后没有模块，则整条不进入 combined 文件。每次该规则变化后必须重新计算 candidate identity、coverage 和 dry-run，不得沿用旧 apply-check 证据。
- `candidate_less_complete` 不只比较行数，还必须逐模块比较关键字段非空数量；候选总行数相同但会把已有练马师、骑手、完赛时间等字段覆盖为空时，同样阻断 apply 并在 blocker 写入 `field_completeness_regressions`。
- JRA 重赏年度列表不含练马师和完赛时间；`jra_history_winners` 必须依赖同批 `jra_detail`，用当届冠军赛果补齐这些字段并保留 `current_result` 来源。第一批真实缓存 smoke 应确认 2026 日本德比历史冠军为 `ロブチェン / 杉山 晴紀 / 2:22.7`。
- 第一批最终证据：候选 SHA-256 `2dd40a141219f7fd39799b7f586efb862f2332e8e037e4091f46c88bee48eac5`；coverage `passed / 5/5 / blocker=0`；dry-run `events=11 / modules=15 / runners=75 / results=64 / history_winners=47`；请求数 `60`。正式 apply 前必须取得八个实际地区/来源/module scope 的人工确认、法国和美国 mixed-source strategy SHA 确认，以及字段 diff review 批准。
- 2026-07-12 用户确认后 apply-check 通过，八个 scope、两个 mixed-source strategy、候选/coverage/dry-run 身份和数据库备份均一致；锁定候选命令执行 `candidates=15 / applied=15`。写前目标计数 `75 / 64 / 46`，写后 `75 / 64 / 47`，最新 15 个候选全部 applied。备份：`backups/db/pre-first-race-crawl-apply-20260712_000116.sql.gz`，约 `105M`，SHA-256 `48a87f2d8941ba09ab24076d4813b27d0729b2c8e3a7b5752a6a3144b8eb703f`，`gzip -t` 通过。

### 2026-07-11 国际新闻门禁与产量验收

- 最近 24 小时英文新稿 `50`、公开 `15`、存在 `core_term_missing` 的文章 `25`。普通词降级已有生产命中，但错误登记为 `horse` 的普通词会被 `horse_term_without_common_seed` 强制判为 proper noun，仍可误挡发布。
- 最近 24 小时地区新增/公开：日本 `114/21`、香港 `3/0`、英国 `12/2`、法国 `1/0`、美国 `34/13`。所有启用来源最新抓取均成功；香港/法国低产主要是有效新稿不足、翻译失败和门禁待审核，不是全局抓取调度停摆。
- 当前启用且生产批准来源数：日本 `6`、香港 `2`、英国 `3`、法国 `3`、美国 `3`。法国宽关键词 TDN 源最近 24 小时新增 `0`，At The Races 法国源仍关闭；后续国际扩源尚未落地。
- 禁止直接在生产批量执行 `reprocess_term_gate_blocked_articles`：本次发现 `--limit 5 --dry-run` 仍会长时间占用单核。若需复验，先在代码侧优化术语匹配/缓存和候选边界，在隔离环境做性能测试，再使用生产只读小样本。
- 本次误启动的重处理进程已全部终止，web CPU 恢复、`/healthz/` 返回 `200`。验收过程中并行赛事 adapter 部署重建 web/worker/beat，17:15 抓取窗口短暂中断后继续排空；该部署不改变上述 24 小时新闻验收结论。
# 2026-07-12 赛事名称中文展示与出马表排序上线

- 部署提交：`d071952`。
- 产品行为：赛事详情、历史冠军和赛事日历赛果中的马名/骑师名精确命中 active 正式术语主原文或别名时展示中文译名；未命中保留原文。出马表按马号自然升序，缺号回退闸位，赛果仍按完赛名次。
- 本地验证：赛事页目标测试 `23` 项、完整 `stable` 回归 `612` 项、Django check、迁移漂移、旧规格流程 严格校验和 `git diff --check` 全部通过。
- 部署前生产 HEAD：`8fbc6c6`；外部导入、外部锁和抓取中任务均为 `0`，内外 healthz 正常。
- `.env` 备份：`.env.backup.race-display-20260712_002533`。
- 数据库备份：`backups/db/pre-race-display-20260712_002533.sql.gz`，约 `105M`，已通过 `gzip -t`；SHA-256 为 `99994e84d3154dd9d4c1503b96688cd24bf7e00d9ad13aca02a965a69d64a8c0`。
- 部署方式：生产 `git pull --ff-only origin main` 快进到 `d071952`，执行 `bash ./deploy_lowcost.sh`；无新增迁移。
- 部署后：`web / worker / beat / db / redis / nginx` 正常，web/db/redis healthy；Django check、内外 healthz、`/races/` 和日本德比详情均通过，近 5 分钟日志无 traceback/error。
- 数据抽检：英国马名 `13/13`、骑师 `9/13` 命中；美国马名 `2/18`、骑师 `11/18`；法国马名 `1/7`、骑师 `0/7`；日本德比马名 `1/18`、骑师 `0/18`。日本当前页面大量原文属于术语库覆盖缺口，不应通过页面层临时翻译解决。

## 2026-07-12 历史赛事回填安全门禁

- 默认配置必须保持：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
- 保守预算默认值：单 run 请求预算 `250`、source cache 上限 `2147483648` bytes、启动前最小剩余磁盘 `5368709120` bytes。plan 只能声明更小或相等的请求/cache 上限，磁盘不足时 fail closed。
- 离线 plan 命令可在功能关闭时执行：`python server/manage.py build_historical_race_inventory --catalog-jsonl <catalog.jsonl> --timeline-jsonl <timeline.jsonl> --output-dir <artifact-dir>`。它只生成审核文件，不写数据库、不发网络请求。
- 官方 source cache 先使用 `python server/manage.py parse_historical_race_catalog --source-manifest <manifest.json> [--source-manifest ...] --output-dir <candidate-dir>` 离线生成 `catalog_candidate.jsonl` 和 `series_timeline_candidate.jsonl`；manifest 必须绑定 provider、支持年份、source URL、cache SHA-256 和 parser version，输出目录必须为空。`server/stable/fixtures/historical_race_catalog/` 只是解析测试摘录，禁止作为生产完整目录审批依据。
- inventory commit 必须使用既有 artifact，禁止边生成边写：`python server/manage.py build_historical_race_inventory --artifact-dir <artifact-dir> --approval <artifact-dir/approval.json> --commit`。执行前必须人工核对 conflict=0、review、summary、manifest SHA 和 approval 的批准人/时间。
- 首次部署只允许空模型与只读工具：先备份数据库，执行迁移和 `manage.py check`，检查旧赛事 URL/页面，再检查只读总账后台。不得在同一步开启历史功能、网络或提交总账。
- 网络 prepare 还必须同时满足：功能开关开启、网络总开关开启、plan `allow_network=true`、应到 artifact 已批准、共享请求预算有效、source cache/磁盘预检通过。任一条件缺失不得启动 adapter。
- 代码、全量测试、clean review、生产迁移和 2026 mapping 已完成；后续逐年目录和历史详情仍必须继续遵守本节门禁。
- 用户已授权在上述准备门禁全部通过后自主执行生产抓取和落库。执行期间可临时开启功能/网络开关；每批完成或中止后必须恢复 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，并确认历史年度赛事没有被意外公开。
- `RACE_EVENT_PUBLIC_CACHE_SECONDS` 默认 `300` 秒，生产 `RACE_EVENT_CACHE_URL` 应指向共享 Redis（建议独立 DB，例如 `redis://redis:6379/2`）；测试使用 LocMem。赛事或历史总账状态变更会主动清理 sitemap 数量和赛事年份缓存，Redis 暂时不可用时回退数据库。部署迁移后须抽查 sitemap 分片数量、年份筛选，并确认 `race_event_visible_year_idx`、`race_event_sitemap_idx`、`race_result_official_event_idx` 已创建。

## 2026-07-12 历史赛事编排工具首次生产部署与 2026 mapping

- 部署提交：`c3b66a6`；生产从 `dc6e434` 快进，并执行 `bash ./deploy_lowcost.sh`。
- 部署前 `.env` 备份：`.env.backup.historical-race-backfill-20260712_044501`。数据库备份：`backups/db/pre-historical-race-backfill-20260712_044501.sql.gz`，`110878772` bytes，SHA-256 `524accd73e30e3d4a87ca4c974b06811edbf78f80b755cb55d86121eaaccffeb`。
- mapping 写入前备份：`backups/db/pre-2026-race-series-mapping-20260712_051047.sql.gz`，`111044004` bytes，SHA-256 `701b951aca74ba1a7dad5665eb4dd9f333bd2233aa0f275011a36ae132510453`。两份备份均通过 `gzip -t`。
- 迁移验收：`0024_historical_race_inventory`、`0026_historical_race_query_indexes` 已应用；三个目标索引存在。`manage.py migrate stable 0023 --plan` 已完整列出 reverse plan；真实恢复入口仍为 `deploy/restore_db.sh <backup>`。
- 初始 dry-run 为 `995` 场、`786` 自动批准、`209` 待审、`212` 冲突。完成日本/香港稳定 key 审核、美国重复空壳清理、英国 Gold Cup 合并及相似名称显式区分后，最终 artifact 为 `runtime/historical_race_inventory/mapping-2026-approved-20260712_051808/`，结果 `992/992 approved`、`0 review_required`、`0 conflict`。
- mapping commit 仅在一次性管理容器中设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`，未开启网络；首次结果 `series_created=992 / events_bound=992`，幂等复跑 `0/0`。常驻 web/worker/beat 从未开启历史功能。
- 写后验收：`RaceSeries=992`、2026 `RaceEvent=992`、已绑定 `992`、未绑定 `0`；日本 `186`、香港 `20`、英国 `202`、法国 `174`、美国 `410`。`HistoricalRaceEventTarget=0`，1984–2025 赛事及其公开数均为 `0`。
- URL 抽检：`/races/`、`/races/2026/gold-cup/`、日本德比、香港董事杯均返回 `200`。已合并的 BHA 重复地址 `/races/2026/uk-bha-flat-2026-0618-045/` 返回 `404`，其 slug 已作为主赛事别名保留，正式入口固定为 `/races/2026/gold-cup/`。
- 最终开关：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；共享页面缓存为 `redis://redis:6379/2`。容器正常，内外 `/healthz/` 为 `200`，近 10 分钟无 traceback/error。

## TJCIS 年鉴目录生产生成

1. 部署已 review 提交，确认生产镜像内 `python -c 'import pdfplumber, bs4'` 通过。
2. 设置独立 run 目录、请求预算 artifact、source-cache manifest 和磁盘预算。1998–2026 首次下载需要 2 个索引请求和 29 个 PDF 请求，但不得超过历史回填全局上限。
3. 仅在下载窗口临时开启两个历史开关，执行 `python runtime/tools/prepare_tjcis_ics_catalog.py --years 1998-2026 --output-dir <run-dir> --allow-network`。中断后用同目录追加 `--resume`，禁止手工替换缓存。
4. 对五个 `manifest_<region>.json` 运行 `parse_historical_race_catalog`，再用 `build_historical_race_inventory` 生成部分只读总账 artifact。核对每年五地区非零、平地自报总数一致、conflict/review/gap 和原始 PDF SHA。
5. `1998–当前` 可作为独立完整年代 scope 生成和批准 inventory manifest，并在该 scope 逐年五地区完整、来源/身份冲突清零后执行总账与详情 apply；不得把该批准外推为 `1984–1997` 已完成。
6. 无论成功或失败都恢复两个开关为 `false`，验证内外 `/healthz/`、当前赛事页、`HistoricalRaceEventTarget=0` 和 1984–2025 公开赛事数为 `0`。

### 2026-07-12 首次 TJCIS 执行记录

- 生产直连 TJCIS 超时，禁止继续盲目重试；本次采用同一工具本机受控抓取、生产离线 SHA 复验。原始目录为 `runtime/historical_race_inventory/tjcis-ics-1998-2026-relay-20260712/`，31 个 cache 文件全部验证通过。
- 最终成功年只有 `2016 / 2020 / 2021`；`summary.json` 中 25 个 `year_errors` 是后续修复入口，不得删除、改成 warning 或从完成率分母隐藏。
- v3 candidate/inventory 路径分别为 `tjcis-candidates-2016-2021-v3-20260712/` 和 `tjcis-inventory-partial-2016-2021-v3-20260712/`。`conflict_count=82`，因此 approval 保持空白，禁止执行 `build_historical_race_inventory --commit`。
- 本轮没有数据库备份，因为全程只读且未进入 commit；写后核验为 targets/pre-2026/public-pre-2026 全部 `0`。常驻开关始终 `false`，生产 HEAD `3dc8dff` 后继续健康。

### 2026-07-12 第二轮年度目录修复记录

- 修复后严格通过年份为 `2005 / 2007 / 2009 / 2012 / 2013 / 2014 / 2015 / 2016 / 2020 / 2021 / 2022`。
- `diagnostics/declared_count_reconciliation.json/csv` 记录 `22` 年、`31` 个地区/项目的正文显式行与页脚声明差异。该文件是来源核验输入，不是 approval；禁止依据差额自动增加或删除赛事。
- 页文本诊断缓存覆盖 1998–2026 全部 29 本 PDF，只用于快速差异定位。正式候选仍须绑定原 PDF 的 source-cache manifest、大小和 SHA-256。
- 当前不得运行 inventory commit 或历史详情抓取。先以地区官方年度目录核验差异，并在完整候选上生成身份 conflict/review 文件；涉及系列合并、拆分、前后继或同名异赛时必须交产品审核。
## 2026-07-13 法国新鲜度与多地区归属待部署清单

本节描述尚未执行的生产步骤。代码部署与迁移不得自动开启归属、相关地区查询或翻译失败重试。

1. 部署前记录生产 HEAD、工作区、容器、Nginx、Celery active/reserved、外部导入与锁、法国来源状态；备份 `.env` 和 PostgreSQL，并校验备份。
2. 显式保持 `MULTIREGION_ATTRIBUTION_MODE=off`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`、`TRANSLATION_AUTO_RETRY_ENABLED=false`，再部署代码并应用 `stable.0029_france_freshness_translation_attribution`。
   邮件接收地址设置为 `754652181@qq.com`；若生产缺少 SMTP/EMAIL_HOST 配置，则必须保持 `TRANSLATION_FAILURE_EMAIL_ENABLED=false`。只有 SMTP 配置完成且受控测试邮件成功后才允许开启。
3. 验证 `web/worker/beat` 使用相同安全配置，执行 `manage.py check`，检查迁移、容器、日志、内外 `/healthz/`、首页、五地区页和运营后台。
4. 对 TDN France 和 France Galop 执行只读 probe；France Galop 旧时间只先运行 `repair_france_galop_published_at` dry-run，保存 manifest、证据和漂移检查结果，不直接改库。
5. 使用真实生产文章建立至少 150 篇有效、五个运营地区各至少 10 篇、跨地区至少 20 篇的 Gold CSV；单审保留 reviewer A 来源，多人冲突必须裁决。配置非 `pending-review` 的 `MULTIREGION_ATTRIBUTION_GOLD_VERSION` 和该 CSV 的 `MULTIREGION_ATTRIBUTION_GOLD_SNAPSHOT_SHA256`，再执行 `evaluate_multiregion_attribution_gold --labels <csv> --provisional --json`。任一覆盖或质量门槛不通过即 no-go。
6. 使用 `reprocess_multiregion_attribution_gates --dry-run --single-review-gold --gold-labels <csv>` 生成绑定 Gold 指标的持久 run ID 与 manifest；人工审核主地区变化、全部 `needs_review` 和无依据扩散后，才允许对锁定 run 执行 commit。`pending-review`、无有效 SHA、有效分母/分地区/跨地区覆盖不足或指标 no-go 均会拒绝 commit。
7. 翻译失败先审核 `429/503/504/timeout` 清单，再小批开启 selector；确认不会直接公开文章或创建 QQ delivery。耗尽和人工重试入口必须可见。
8. 归属灰度顺序固定为：off 部署、shadow、仅新文章 enforce、网页和显式测试群相关查询、最近 72 小时受控回填、正式群。进入测试群阶段前，仅对指定 `PushTarget` 设置 `multiregion_test_enabled=true`；其余群保持 false，最终 `formal_groups` 阶段才扩大。每阶段记录指标并至少观察约定窗口。
9. 回滚先关闭相关地区查询，再把归属切回 `off`，最后关闭翻译自动重试；保留已写审计与 run，不用反向迁移删除证据。数据库异常时按备份恢复流程处理。
10. 至少验收 3 个日常窗口和 1 个可模拟的重要赛事窗口，按来源候选、翻译、归属、门禁、公开和 QQ 分层记录数量与零发布原因，完成后再更新状态文档并归档 change。

## 2026-07-13 `fix-france-news-freshness-and-multiregion-attribution` 安全关闭部署记录

1. 部署前生产 HEAD 为 `c998eb3f`；容器健康、Celery active/reserved 为空、外部导入和归属锁均为 0，法国来源 13/14/21 已启用且最近抓取成功。
2. 环境备份：`.env.backup.france-multiregion-20260713_041004`。数据库有效备份：`backups/db/pre-france-multiregion-20260713_041111.sql.gz`，SHA256 `a92e95fd8b10ceb7cd3721d4984d8f8d699b23edf6686615e289a12e6aa0c898`；恢复前必须再次执行 `gzip -t`。带 `.incomplete` 后缀的首次文件禁止使用。
3. 生产拉取 commit `badc10e028aa3c1f6f2984bbfad8c1e202101cdc`，执行 `docker compose -f docker-compose.prod.lowcost.yml build web`、`migrate --noinput`、`up -d --remove-orphans` 和 `collectstatic --noinput`；`stable.0029` 应显示 `[X]`。
4. 部署后必须从 `web / worker / beat` 三个容器分别读取 Django settings，确认 attribution mode/rollout 均为 `off`，相关地区查询、翻译自动重试和失败邮件均为 false，gold version 为 `pending-review`。
5. 健康验收以 `http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页、法国频道和新闻详情页为准；当前 HTTPS server 块仍注释，不能使用 HTTPS 失败判断本次应用部署失败，也不能对外宣称 HTTPS 已完成。
6. 只读来源探测命令：`python manage.py probe_international_news_sources --source france_galop_news --source tdn_france --source tdn_france_broad --limit 2 --json`。2026-07-13 验收列表数为 `20 / 4 / 12`，均 accepted，详情错误为 0；该命令只做网络与数据库重复检查，不写入文章。
7. 后续启用前先配置 SMTP 并测试 `754652181@qq.com` 收件，再建立有效 gold set、执行生产 dry-run 和人工复核；严格按 shadow、仅新文章 enforce、网页/测试群、72 小时回填、正式群顺序推进。任一质量门槛失败即停止扩大。
## 2026-07-13 历史赛事第一批详情生产写入记录

- 详情候选：`runtime/historical_first_acceptance_1998_2026/detail-crawl/historical_detail_candidates.jsonl`，27 场，SHA-256 `c999be2b2b0790837f8a6f5888e7068e775c783a57c6f8e7f3298e41e9b67a04`。写入前验证 `source_cache_manifest.json` 所列每个文件的相对路径、大小和 SHA。
- production dry-run 为 `scopes=27` 并通过。详情写入前备份为 `backups/db/pre-historical-detail-first-acceptance-20260713_055500.sql.gz`，约 139 MB，`gzip -t` 通过，SHA-256 `5f0f9d94406d55954b078339f2a3796556f6ffc98b47c43d6bf2d14bbccde9ff`。
- 正式写入只在单次容器命令临时注入 `HISTORICAL_RACE_BACKFILL_ENABLED=true`，不得修改常驻 `.env`：

```bash
docker exec -e HISTORICAL_RACE_BACKFILL_ENABLED=true umanewsbot-web-1 \
  python manage.py import_historical_race_event_candidates \
  --jsonl /tmp/historical-first-acceptance/historical_detail_candidates.jsonl \
  --expected-sha256 c999be2b2b0790837f8a6f5888e7068e775c783a57c6f8e7f3298e41e9b67a04 \
  --apply
```

- 写后核验：27 个 target 为 imported；香港/日本各 9 场、英国 6 场、美国 3 场；`Runner=297`、`Result=287`、`DataCandidate=54`，逐目标无条数偏差，27 条导入 OperationLog 存在。法国 9 场保持 ready，英国 3 场和美国 6 场保持 pending。
- 可见性与运行态：36 个已建 `RaceEvent` 全部 draft、published 为 0；常驻两个历史开关均为 `false`。内外 healthz 为 `ok`，服务容器正常，最近 20 分钟 web/worker/beat 无错误日志。
- 容量：详情缓存约 5.4 MB、38 个文件；当前数据库约 832 MB。本批核心新增 638 行和 27 条操作日志，现有索引及相关表规模未发现扩大批次 blocker。
- 回滚时先停止后续历史写入，确认目标 scope 未被后续批次修改，再按数据库恢复流程使用上述备份；不得只删除 runners/results 而保留 imported 总账状态。

## 2026-07-13 2016–2025 日美批次恢复记录

- 最近续跑备份为 `backups/db/pre-band-2016-2025-jra-us-resume2-20260713_014638.sql.gz`，大小 `117832357`，SHA-256 `f765240eecea8e1bc758dca7b73590c90f9bf8c8078ff3757d9c375328dfaf78`。
- 跨架构构建必须核验镜像 `Architecture`。本机 ARM64 镜像曾使 AMD64 生产容器 unhealthy，已即时使用预留镜像回滚；后续采用生产机原生 AMD64 构建。
- importer 按年度 scope 独立事务提交。中途失败时只查询仍为 `ready` 的目标，重新导出当前 target SHA、package 和 dry-run，不重放已 imported scope 的旧候选。
- Equibase 续跑必须通过重复 `horse_number` 和重复存储 `finish_position` 检查；退赛使用 `SCR-n`，并列名次保存在 `official_finish_position`。
- 最终核验为 98 个批准详情目标全部 imported，`Runner=1157`、`Result=1080`；healthz 正常，常驻历史功能和网络开关为 false。

## 2026-07-13 NSA 补齐与旧底座 P0 记录

- NSA 候选 `final_candidates_nsa.jsonl` 固定 SHA-256 为 `478e263ee1b2e07ca6ef3cba23c683549393400b263ae250eef9b15fa0c3a1ff`。生产 dry-run 为 2 scopes，备份 `pre-band-2016-2025-nsa-import-20260713_015750.sql.gz` 大小 `117926527` bytes、SHA-256 `9a34f879a98e0fd8bda27b426b81f009bf6fcef0ce882b031589fe7c8867f3bc`，正式写入新增 `15 runners / 14 results`。
- 写后标准批次日美 100 个目标为 `100/100 imported`、`1172 runners / 1094 results`；生产累计查询中的 `105 imported / 1221 runners / 1139 results` 另含第一批验收的 5 场美国赛事，不得混作本批分母。
- P0 触发条件：生产数据库已应用 `stable.0029`，但运行镜像来自未合入 main 的历史分支，netkeiba 新增报 `null value in column attribution_rule_version violates not-null constraint`。此时立即停止批量写入、镜像构建和容器重启，确认没有运行中的 one-off 事务，并把镜像恢复权交给生产协调线程。
- 兼容镜像构建门禁：合入最新 main；`showmigrations stable` 覆盖生产已应用叶节点；Django check 和 `makemigrations --check` 通过；历史、新闻新增、法国新鲜度、翻译恢复、多地区归属、P0 马匹组合测试通过；完整 stable 回归通过；构建 AMD64 后先报告镜像 ID，不直接重启生产。
- 本次兼容镜像已在 `/opt/umanewsbot-builds/merged-historical-main-20260713-1008` 独立上下文构建，tag 为 `umanewsbot:merged-main-historical-amd64-20260713-1008`，ID 为 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`。镜像标签记录 revision `0068715fceb0f629b5bfcb0c0b760427dfc6edc5` 和 source tree `e51e6992e57649445aeff2aa7f2a0c925f3c5c742771fceac13053459beceec6`；服务器与本机构建上下文哈希一致，镜像内 `0029`、历史详情服务和 NSA parser 存在，临时 SQLite check/migration drift 通过。
- 构建本身未 retag `umanewsbot:prod`、未修改 compose、未重启容器、未连接生产数据库。最终切换必须由生产协调线程执行，并在切换后重做新增文章、翻译、历史只读计数、三个服务 settings、healthz 和近期错误日志验收。

## 2026-07-13 兼容镜像切换后的历史批次恢复

- 当前生产固定镜像 ID 为 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`，回滚标签为 `pre-merged-main-historical-20260713-1015`。继续历史批次时禁止运行 build、retag、compose recreate 或服务 restart。
- 法港英 150 场在生产写入前必须保持以下顺序：同步只读证据包 -> normalize/build 日期 artifact -> 核对 `150 ready` -> 审批 -> 数据库备份及 `gzip -t`/SHA -> 日期 commit -> 重新导出 event input -> 打包详情 -> coverage/dry-run -> 第二份数据库备份 -> 详情 commit -> 逐目标及全局写后核验。
- 证据包必须为 150 条 provider、150 条 succeeded ledger、150 个唯一 URL 和 150 个逐文件大小/SHA 匹配的缓存身份；英国 Aintree Bowl/Hurdle 应分别为 race ID `850965/850966`。任一详情 URL 被不同 target 复用时立即停止。
- 整个过程保持 `RACE_EVENT_HISTORICAL_PUBLIC_ENABLED=false`；仅在单条命令需要时临时打开历史回填写入门禁，并在命令结束后恢复。生产 web/worker/beat 的常驻开关不得因一次性命令改变。
- 本批日期写入已使用 artifact manifest `e5ede9033485f59faac8d27c5371bd4749c17235119f4eea173cca07cc389b03` 完成 150 个 target；写前备份为 `backups/db/pre-band-2016-2025-fr-hk-uk-date-apply-20260713_122142.sql.gz`，大小 `121,994,037` bytes，SHA-256 `dae5869d58eb7e854d359f333e979b52647da75db667db930ff53d1cce5f521f`。详情写入因优先执行 Git 固化而暂停，不得越过新的源码提交/合并/可复现镜像门禁继续。

### 运行镜像被旧底座覆盖后的恢复记录

1. 症状：服务器 HEAD 为最新，但容器缺少 `0029` 和新增 settings；数据库已有 `0029`，新文章插入报 `attribution_rule_version` 非空约束错误。先检查 `docker inspect <web> --format '{{.Image}}'`、镜像内迁移文件和 `showmigrations`，不要仅执行 `git rev-parse HEAD`。
2. 紧急恢复：保留故障镜像 tag，确认 active/reserved/one-off 为空后，把已验证的 `pre-irishracing-20260713` 临时切回 `prod`，只重建 `web/worker/beat`，不重启数据库。恢复后用真实来源抓取验证新增文章和新字段。
3. 最终镜像：`umanewsbot:merged-main-historical-amd64-20260713-1008`，image ID `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4`；回滚 tag `pre-merged-main-historical-20260713-1015`。
4. 切换流程：先停止 beat，等待 worker active/reserved 和 one-off 清空；运行 `migrate --noinput` 确认无待迁移，再强制重建 `web/worker/beat`。完成后验证 image ID、`0027-0029`、64 个模型、归属/重试安全开关、历史管理命令、五地区页、后台、healthz 和最近日志。
5. 数据验收：恢复后的 netkeiba 抓取新增 3、重复 117；恢复阶段总计新增 9 篇且全部翻译完成，新文章 `attribution_rule_version` NULL 数为 0。任何后续镜像若重新出现 57 models 或不识别 `0029`，立即按故障镜像处理并回滚。
## 历史赛事权威字段批次部署门禁

- 生产执行 `import_historical_race_event_field_candidates` 前，运行镜像必须来自包含该命令的最新 `main` AMD64 构建，并记录 Git commit、tree/context SHA 和 image ID；禁止从未提交 worktree 或旧底座直接重建 `prod`。
- 先执行 `--dry-run --expected-sha256 <整文件SHA>`，核对目标数、逐字段 before/after、人工锁和零漂移；apply 前完成数据库备份、SHA-256 与 `gzip -t` 校验。
- apply 只临时启用 `HISTORICAL_RACE_BACKFILL_ENABLED` 的单命令环境，不修改常驻配置；结束后复核常驻历史网络/写入门禁和历史赛事 draft 状态。
- 字段 apply 后必须重新导出 event input 并重新生成详情候选。旧详情候选的 target SHA 应失败，不能为赶进度跳过重新 coverage、dry-run 和第二次写前备份。

## 2026-07-13 多地区归属 Gold Set 审核流程

1. 生成审核包必须保持归属与相关查询开关关闭，只读生产数据库，不执行归属 commit。推荐输出到 `runtime/multiregion_gold_review/<version>/`：

```bash
python manage.py prepare_multiregion_attribution_gold_review \
  --output-dir runtime/multiregion_gold_review/<version> \
  --gold-version <version> \
  --per-region 50 \
  --cross-candidate-target 75 \
  --candidate-pool-per-source 100 \
  --seed YYYYMMDD
```

2. 先校验 `manifest.json` 中的 SHA、250 个唯一 key/URL/input SHA、五地区各 50 和来源分布。`source_snapshot.csv` 与 `README.md` 不得编辑；正文审核包不得提交 Git。
3. 把 `reviewer_a.csv`、`reviewer_b.csv` 分别交给两位不同审核人独立填写。只编辑 README 列出的审核字段；地区值只允许 `japan / hong_kong / united_kingdom / france / united_states`，多个相关地区用英文分号分隔。
4. 两份审核完成后先合并，不带裁决表运行一次：

```bash
python manage.py finalize_multiregion_attribution_gold_review \
  --package-dir runtime/multiregion_gold_review/<version> \
  --output-dir runtime/multiregion_gold_review/<version>-finalize-1
```

5. 若输出 `adjudication.csv` 有冲突，由第三角色逐项填写 `resolved`、最终主/相关地区、理由、裁决人和 ISO-8601 时间，再带 `--adjudication` 运行到新的空输出目录。只有生成文件名为 `gold_labels.csv` 且报告 `structurally_qualified=true` 才表示结构合格；`gold_labels_draft.csv` 一律不得用于生产资格。
6. 将结构合格的 `gold_labels.csv` 放入版本化仓库数据目录，只提交不含正文的最终标签和必要说明。随后运行 `evaluate_multiregion_attribution_gold --labels <path> --json`；质量门槛任何一项 no-go，均不得开启 shadow/enforce。
7. 当前首包版本为 `multiregion-gold-v1-20260713`，manifest SHA-256 为 `1836a9d896ca5b6e09da6da7ed07a2fb3f66f0a02f387010fe4b56475bf5c1ea`。该包尚未双审，不能配置为生产有效 Gold 版本。

### 单审部分样本校准

当只有一位审核人或部分候选未选择地区时，必须显式使用单审模式；不得把空白行补成来源地区，也不得复制同一审核人作为 reviewer B：

```bash
python manage.py finalize_multiregion_attribution_gold_review \
  --package-dir runtime/multiregion_gold_review/<version> \
  --output-dir runtime/multiregion_gold_review/<version>-provisional-final \
  --provisional-single-review \
  --reviewer-file /path/to/reviewer_a_completed.csv

python manage.py evaluate_multiregion_attribution_gold \
  --labels runtime/multiregion_gold_review/<version>-provisional-final/provisional_gold_labels.csv \
  --provisional \
  --json
```

- `provisional_gold_labels.csv` 保留单审来源标记；自 2026-07-14 起，单审身份不再自动 no-go，但仍须满足相同覆盖与质量门槛，并通过 `--single-review-gold` 显式进入 dry-run。未完成 shadow 验收前生产 commit/enforce 仍禁止。
- 首次生产只读评估因 5 篇文章输入 SHA 漂移只纳入 154 条；随后以审核包冻结正文建立本地 SQLite 校准快照，恢复完整 159 条固定分母。旧规则在本地同分母基线为主地区 `81.76%`、相关 precision `6.67%`、recall `6.45%`。
- `multiregion-v3` 本地校准结果为主地区 `98.11%`，日本/香港/英国/美国 `100%`、法国 `90.91%`、other `60%`；相关 precision `100%`、recall `54.84%`，无依据变化 `1.89%`、过度扩散 `0%`。recall 缺口主要来自审核标签要求补入文章未提及的历史参赛地区，自动规则不得为追分猜测这些地区。
- 批量评估使用 17,474 个活跃地区术语、38,806 个索引候选；159 篇纯推断约 `0.8` 秒，完整 Docker 命令约 `2–4` 秒。索引只生成候选，最终仍调用原边界匹配器；生产 PostgreSQL 250 篇 SQL/RSS 基准仍须按任务 8.9/9.3 单独验收。
- 该批仍保留 `provisional_single_review` 审核来源，但 159 条有效样本、最少运营地区法国 11 条和跨地区 24 条已达到 `150/10/20` 首发覆盖；相关 precision `100%`、recall `54.84%` 及其他质量指标也已达标。它可以生成进入生产 Shadow 所需的 dry-run，但在生产 dry-run、至少 24 小时 Shadow 和全量变化复核完成前，`MULTIREGION_ATTRIBUTION_MODE` 仍须保持 `off`，相关地区查询保持关闭，不得直接 commit/enforce。
- 生产只读评估若意外启动多个全术语扫描进程，应立即停止并确认容器内外 one-off 均退出；本轮曾终止两个只读评估进程，未写数据库，后续校准全部切到本地冻结快照。
## 2026-07-13 `main@58786b91` 可复现镜像部署记录

- 构建上下文：`/opt/umanewsbot-builds/main-58786b91-20260713-1435`；revision `58786b91fba9c44054a6102055766824677bcbcb`，Git tree `5d8b7ccf775f6be7051c88e8f440b034ad02f4df`，source archive SHA-256 `184f05c39d3df5dd0bb1f410bdccda418ed3052964edea99b07faf22723fa07e`。
- 两次独立 AMD64 build 得到相同 image ID `sha256:c6a3670fdc42db9c0b8ded5772630ac1b0511b98a521ea7f4a9cbe7e25864691`；正式 tag 为 `umanewsbot:main-58786b91-amd64-20260713-1435`，生产 `umanewsbot:prod` 当前指向该 ID。
- 部署前 `.env` 备份为 `.env.backup.main-58786b91-20260713_143748`；数据库备份为 `backups/db/pre-main-58786b91-20260713_143748.sql.gz`，大小 `149,960,820` bytes，SHA-256 `9f29cd1a28b41761591a1966c68125c611a36290953cf0d845cdcead05891f27`，`gzip -t` 通过。回滚 tag 为 `pre-main-58786b91-20260713-1439`，对应旧 image ID `sha256:27d5d51cbe2ae6d23cb99dc758da01addc2d5935504a950bbb8a2685bce2bf13`。
- 切换前必须验证 origin/main、服务器 HEAD 与构建 revision 一致，外部导入、术语门禁、归属锁、worker active/reserved 均为空；停止 beat、排空 worker 后才允许 retag 和重建 `web / worker / beat`。某一步 shell 管道提前退出时，先确认是否已经 retag/recreate，不得盲目重放整段脚本。
- 切换后验收：三容器 image ID 一致；架构为 amd64；`stable.0029_france_freshness_translation_attribution` 已应用；64 个模型、Django check、五地区频道、赛事页、马匹页、后台和 healthz 正常；近期 web/worker/beat 日志无 ERROR、CRITICAL、Traceback 或 IntegrityError。
- 首个完整自然窗口为 `2026-07-13 14:45 CST`：crawl `17/17`、publish `5/5`、QQ push `5/5` 全部 succeeded，crawl seen `472`、new `3`；新增文章 `attribution_rule_version IS NULL=0`。发布和 QQ 的零产出原因均为当前门禁下的正常 `hard_gate_blocked`、`translation_retry_waiting`、`no_ready_candidates` 或 `no_eligible_articles`。
- 历史数据门禁：`HistoricalRaceEventTarget=30,917`，2026 年前 `RaceEvent=295`、`RaceEventRunner=3,174`、`RaceEventResult=2,817`，全部 `draft`、published `0`；常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false` 和 `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。一次性来源缓存或写入只在单命令环境中临时开启，命令结束后必须再次核对常驻值。

## 2026-07-13 第二标准批次日期工件重建门禁

- 二号批次 selection 为 250 个目标。当前最终来源包只包含 246 个可导入 held 目标，adapter 分布为 `jra=50 / equibase=48 / hkjc=50 / uk_sportinglife=48 / zeturf=50`；source URL、ledger 和 cache identity 必须均为 246 个且一一对应。
- 不得把四个缺口伪装成 held 候选：Brooklyn Stakes、Cougar II Stakes 保留 TOBA `not run` 审核项；Classic Handicap Chase、Dick Poole Fillies Stakes 保留 Sporting Life `ABANDONED` 证据，后续须通过正式 expectation correction 流程处理。
- 本段历史记录中的香港规则已被
  `docs/changes/repair-historical-race-calendar-integrity/` 废弃：
  `hong_kong_racing_season_spans_calendar_years` 不再是合法届次跨年原因，包含该原因的旧 artifact
  不得审批或 apply，必须重新 prepare。普通香港马季按实际比赛自然年建立 target/event；只有真实
  延期且有非废弃原因、权威证据和人工批准时，才允许 edition year 与公开自然年不同。英国来源
  距离仍可保留 `2m4f`、`3m21/2f` 等原文，解析结果必须拆成 mile/furlong/yard 组件，不能改写成
  裸数字或公制猜测。
- 当前生产镜像不含紧凑英制距离修复。必须先把修复提交并合入最新 main，运行完整组合回归，构建可复现 AMD64 镜像并按共享生产切换门禁部署；随后重新 normalize/build，预期结果才是 `246 candidate / 4 gap`。旧 `219/31` artifact 不得审批或 commit。
- 新 artifact 仍须经历 manifest 审批、数据库备份、`gzip -t`、SHA-256、dry-run、单命令临时写入开关、写后逐目标核验和常驻开关复核。详情候选必须在日期 apply 改变 target SHA 后重新导出并重新打包，公开展示开关保持关闭。

## 2026-07-13 `main@d8b65fe7` 不可变镜像切换记录

### 切换对象与回滚点

- 新镜像：`umanewsbot:main-d8b65fe7-amd64-20260713-1630`，image ID `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`，架构 `linux/amd64`。
- 镜像标签：revision `d8b65fe7d63e913cf826d02a74cdebaec60351ce`，Git tree `fda256535ae3b9f435cf8c7b069ff26d04503d99`，source archive SHA-256 `2b085d0226580295f9a844fbc92df48405cd9bb3b467786230fac8941fa60520`。
- 旧镜像：`sha256:c6a3670fdc42db9c0b8ded5772630ac1b0511b98a521ea7f4a9cbe7e25864691`，回滚标签 `umanewsbot:rollback-pre-d8b65fe7-20260713_163805`。
- 环境备份：`.env.backup.main-d8b65fe7-20260713_163805`。
- 数据库备份：`backups/db/pre-main-d8b65fe7-20260713_163805.sql.gz`，`124,020,905` bytes，SHA-256 `33f5ef3520e833a8cf343ca87831a7620c9cb80ba095e74c5cadb716d55ccfa2`，`gzip -t` 通过。

### 排空与切换顺序

1. 核对候选镜像 ID/架构、当前三容器 image ID、内外 healthz、外部导入/锁、one-off 进程及 Celery active/reserved。
2. 停止 beat，再次确认 active/reserved、外部导入和锁均为空；随后停止 worker，不 purge Redis 队列。
3. 将候选镜像 retag 为 `umanewsbot:prod`，使用一次性 web 容器执行 `migrate --noinput`、`check` 和 `collectstatic --noinput`。
4. 先重建 web/worker，等待 web healthy 和 worker ping；最后重建 beat，避免迁移或容器切换期间重复调度。
5. 核对 web/worker/beat 实际 `.Image` 均为新 image ID，再检查内外 healthz、首页、赛事页、Django check、常驻开关和近期错误日志。

### 备份脚本异常与本次回退

- 本次直接执行 `BACKUP_TARGET=local ./deploy/backup_db.sh` 失败：宿主机无法解析 Compose 内部主机名 `db`，随后宿主机 Python 因缺少 `oss2` 再次失败。该命令产生的同时间文件不得作为有效恢复点。
- 本次改用数据库容器内 `pg_dump`，由宿主机管道压缩到独立 `pre-main-d8b65fe7-*.sql.gz`，并强制执行非空检查、`gzip -t` 和 SHA-256 后才继续部署。
- 后续使用低成本 Compose 部署时，在修复备份脚本前必须验证备份命令退出码、文件非空和 `gzip -t`；不得仅凭脚本打印 `Backup created` 视为成功。失败时使用已验证的容器内 `pg_dump` 回退路径，不得跳过备份。

### 验收结果

- 无待应用迁移，Django check 通过；129 个静态文件复制并完成 360 项 post-process。
- web/worker/beat 均运行 `sha256:77eb1138...c3da0`；db、redis healthy，nginx 正常。
- 内部和公网 `/healthz/` 为 `ok`，公网首页和 `/races/` 为 `200`，worker ping 正常，Celery active/reserved 为空，近期 web/worker/beat 日志无 error/traceback/exception。
- `2m4f` 与 `3m21/2f` 的生产纯函数 smoke 分别得到 `2 mile + 4 furlong`、`3 mile + 2.5 furlong`，原始 `distance_text` 保留。
- 常驻历史写入/网络开关、多地区归属/相关地区查询开关均保持关闭；本次没有执行历史写入。

## 2026-07-13 batch003 生产续跑门禁

1. 先合入包含 NAR、Zone-Turf 和 ZEturf 实际缓存 URL 修复的最新 main；旧候选镜像 `sha256:9cd0b966...45bc1` 不得用于 batch003。
2. 在独立上下文构建两次 AMD64 镜像，核对 image ID、revision、Git tree 和 source archive SHA-256；只上报候选，不直接 retag、重启或写生产。
3. 首次只读 artifact 曾得到 `249 candidate / 1 gap`，但 Hampton 后续证据证明同届移师 Windsor 正常举办；该旧 artifact 已作废，唯一有效口径为 `250 candidate / 0 gap`。
4. Hampton 的 Warwick `ABANDONED` 不能用于 expectation correction；日期 apply 后通过独立权威字段 artifact 把实际场地改为 Windsor，并保留原页面为变更证据。
5. 日期 apply 前执行数据库备份、非空检查、`gzip -t` 和 SHA-256；仅对单命令临时打开写入门禁。权威字段 apply 后重新导出 250 个 materialized event input，禁止复用旧 target SHA。
6. 补充详情来源 artifact 必须接受并验证 `keiba_go_jp/nar` 与 `zone_turf`，apply 后再次导出 event input，再生成最终详情包、coverage 和 importer dry-run。
7. 详情 apply 前另做一份数据库备份。写后逐目标核对 runner/result 数、累计计数、OperationLog、draft/published 状态和三容器常驻开关；`RACE_EVENT_HISTORICAL_PUBLIC_ENABLED` 全程保持关闭。

## 2026-07-13 `main@3939992c` batch003 来源门禁镜像切换

### 镜像与恢复点

- 新镜像 tag：`umanewsbot:main-3939992c-amd64-20260713-1847`。
- Image ID：`sha256:87c435cfc50344d0ca94f46e44d4bea97ab11361f88f7c708b6457331aee78ec`，`linux/amd64`。
- Revision：`3939992c7d3753779fc34de81c595f5a34d7ed2b`；Git tree：`0464a1aae6f587e3ba021421ac84b44a3d9379dd`；source archive SHA-256：`a787391c84a4ba3bb22c2ab638f1e36453d3ff8869bb95aeb5001b1dd448bb21`。
- 环境备份：`.env.backup.main-3939992c-20260713_185140`。
- 数据库备份：`backups/db/pre-main-3939992c-20260713_185140.sql.gz`，`125,782,755` bytes，SHA-256 `21903cf8d9494ef6053414a34c2e2f6ab01406b9ffebcf56ff3fd10eedfc0967`，非空且 `gzip -t` 通过。
- 旧镜像回滚标签：`umanewsbot:rollback-pre-3939992c-20260713_185140`，指向 `sha256:77eb11385d1d23843d2e2bae96bc5b4da4453732edb567d46cb0cc0fb01c3da0`。

### 切换与验收

1. 预检发现两条 `crawl_news_source_task` active；先停止 beat，让任务自然完成。确认 active/reserved、外部导入、外部锁和历史 one-off 为空后才创建备份和停止 worker。
2. 使用数据库容器内 `pg_dump` 生成备份并完成非空、`gzip -t`、SHA-256 校验；未调用当前存在宿主机依赖问题的 `backup_db.sh`。
3. Retag 后使用一次性新镜像 web 容器执行迁移、Django check 和 collectstatic；结果为无待应用迁移、check 通过、2 个静态文件复制、127 个未变化、360 个 post-process。
4. 先重建 web/worker，确认 web healthy、worker ping；最后重建 beat。三容器实际 image ID 均为 `sha256:87c435cf...e78ec`。
5. 内部和公网 healthz 为 `ok`，公网首页和 `/races/` 为 `200`，近期 web/worker/beat 日志无 traceback/critical/integrityerror/exception。
6. `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，多地区归属和相关查询开关也保持关闭；本次未执行历史写入。
7. 切换完成后的旧预期曾为 `249 candidate / 1 gap`，后续已由 Hampton 移师证据修正为 `250 candidate / 0 gap` 并按独立 approval、备份、dry-run 与写后核验完成导入；旧 Hampton gap 不得恢复。

# Batch006 年度赛历 11 分片运行手册（2026-07-15）

1. 固定全批身份：1061 targets；manifest `62aca6ced7dcd9c7aecac510cfb65c1468ef54564d61df609cb60226d1b096e3`、selection `b9a3ad6556cfd03e9a57874bec763f75ad4c45e7642751140cb063f1d0553637`、approval `a119e3bcfd3bc8940cf8b792e246e462b405c292b77f2996739b435c9185d835`。任何 SHA 漂移都停止，不从当前数据库重新生成替代审批。
2. 按 11 个 scope 生成 selection/catalog 副本：FR `2023=120 / 2024=130`，HK `2016=35 / 2017=26`，JP `2022=88 / 2023=138 / 2024=24`，UK `2024=196 / 2025=54`，US `2024=83 / 2025=167`。核对全批 target 并集 1061、交集 0、每片不超过 250。
3. 每个 scope 先运行 tracked request builder，核对 source catalog、HTTPS host、parser/adapter、target coverage 和 manifest。共享 URL 只请求一次；若 ledger 跨年份复用，其 target references 必须等于 catalog 来源 scope 的精确并集。
4. cache stage 使用 historical runner `crawl` phase：`network=true/write=false`，按唯一 URL 计请求预算。默认任一请求失败即停；只有 descriptor 显式 `allow_partial` 且所有请求均形成 succeeded/failed 终态时才继续。不得把 failed 记为 complete。
5. parse stage 使用 runner `verify` phase：`network=false/write=false`、request budget=0、无 resource_limits。复制并绑定已完成 cache 的 manifest/ledger/全部成员，离线生成 provider rows、events CSV、gaps、summary 和 manifest；逐成员 checkpoint 后禁止新增、删除、替换或 symlink。
6. France Galop 解析同时消费平地 programme、障碍详细赛程和固定列分组汇总；汇总仅补缺，详细赛程优先。英国距离保留英制原文，法港日保留明确公制；不在编排层统一换算。
7. 每个 scope 要求 `complete + gap = scope` 且二者无交集。gap 记录来源/ledger/cache/target identity 后继续其他 scope；汇总时分别报告 accounted rate 与 data complete rate，日美零星缺口留到全量正式总账完成后统一审核。
8. 日期候选、详情来源、最终详情三阶段分别执行 dry-run；每次 commit 前独立创建并校验数据库备份，commit 使用 `network=false/write=true`，写后运行正式只读 verifier。任一 `error>0`、published>0、身份漂移或锁/事务异常即停止。
9. 全批收口核对 1061 targets、五地区 events/runners/results、gap 清单、OperationLog、runner/checkpoint、Redis/Celery/事务和 healthz。常驻 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`、`RACE_EVENT_HISTORICAL_PUBLIC_ENABLED=false`，直到用户统一审核并另行批准公开。
## P0 马人工补录 dry-run（2026-07-18）

人工补录 CSV 必须使用 `server/stable/services/p0_horse_completion_source_clients.py` 中 `MANUAL_SUPPLEMENT_CSV_FIELDS` 的精确列顺序。只有 `approved` 行会参与；其他审核状态会被忽略。批准行的录入人与复核人必须不同，且禁止 `career` 字段组。

```bash
python manage.py complete_horse_profiles \
  --dry-run \
  --p0-reviewed-candidates /path/to/p0_participant_sample_review.reviewed.csv \
  --p0-review-manifest /path/to/review_manifest.json \
  --p0-review-manifest-sha256 <frozen-lowercase-sha256> \
  --p0-manual-supplements /path/to/manual_supplements.reviewed.csv \
  --allow-network \
  --region united_kingdom \
  --cache-dir /path/to/cache \
  --output-dir /path/to/new-empty-output
```

运行前仍须同时开启服务端网络开关，并绑定相同的审核 manifest SHA。该命令只生成只读 dry-run artifact；不得因此执行 `--commit`。批次 manifest 必须出现 `manual_supplements_input`，并核对文件 SHA、`approved_field_count`、`candidate_count` 和 `outcome_summary`。canonical cache 不得包含任何人工 outcome、provenance、supplemental source 或 raw manual rows，并且 payload 必须是严格 JSON 类型；tuple/set、自定义容器子类、非字符串对象键、非有限浮点值、循环或超过最大深度均停止且不得留下目标 cache 或临时文件。形状检查必须先于复制，并通过 JSON round-trip 生成纯内置类型；独立 purity gate 与完整 validator 都必须在规范化后再次检查人工标记。自动多来源和人工补录合并 helper 也必须先规范化主 payload 与补充输入。磁盘 JSON 解码的深度异常必须归入 `source_cache_or_adapter_error` 并继续其他候选。读取失败不得删除、截断或改写原 cache，运行前后目录清单与逐文件字节应一致。人工内容只允许存在于本批工作副本。发布 staging 前必须证明每个批准字段恰有一个完整证据指纹一致且状态属于 `applied/already_applied/blocked/ignored` 的 outcome；缺失、重复、非法状态、证据漂移或无输入旧 outcome 均停止。

当前不要对中国香港、英国、法国或美国执行 10 匹网络批次。先逐地区完成来源修复和单马完整度复验；法国 HTTP 429、美国身份缺口、中国香港生涯赛名缺口均为停止条件。

## 2026-07-19 五地区准实时公开 Beta 待发布运行约束

本节是尚未发布候选的预期运行手册；在独立 review 和当前冻结版本授权前不得执行生产
命令。完整 gate、manifest schema 和 Docker one-shot 模板以
`docs/changes/five-region-race-live-public-beta/rollout.md` 为准。

1. 初次部署必须保持 `RACE_LIVE_SCHEDULER_ENABLED=false`、
   `RACE_LIVE_MONITOR_ENABLED=false`、`RACE_LIVE_ENABLED_REGIONS=`；部署代码不自动扩大
   event allowlist 或公开范围。
2. official authorization 和 broad scope apply 前停止读取这些设置的 Beat/worker，
   排空 `race_live` queue，并确认数据库所有 `RaceEventLiveTracking.active_attempt_token`
   为空；管理命令会在事务内再次 fail-closed 检查。
3. manual official receipt 没有 authorization 时只保存 staged immutable revision，
   provisional 页面不变；授权命令可在门禁齐备后发布该 staged revision，禁止重造 revision
   或手工改 current pointer。
4. release artifact 必须保存 reviewed release image 的完整本机 image ID、filtered env
   SHA、rollback manifest SHA 和旧 image。one-shot 只允许
   `/app/scripts/run_race_live_rollback_one_shot.py --command
   validate|restore-result|restore-policies-coarse|restore-policy-event`，不得引用 mutable tag。
5. rollback filtered env 只含 PostgreSQL 七项连接字段及受审固定安全值，精确包含
   `DB_ENGINE=postgres` 和
   `SECRET_KEY=fixed-race-live-rollback-validation-key`；env/manifest 均须 root `0600`
   普通非 symlink 文件。validator 使用 PostgreSQL read-only transaction。
6. emergency restore 全程保持四层 maintenance off：先恢复 dedicated provisional
   pointer/legacy/tracking，再只恢复 global/region/source，第二次只读校验后最后恢复
   event policy。失败时 event 继续隐藏。

## 2026-07-19 五地区准实时公开 Beta 代码层发布记录

1. 冻结 fingerprint
   `17a1b34321ee25f13f783c1fe24278bbacdab288f3a30281a981e4986158e0fa`
   对应 commit `85948707c7b2bf3c62a66b09b2ddb202adf2d1ee`。生产 reviewed
   release image ID 为
   `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`；
   旧 image ID 为
   `sha256:700ea78698fb67de602fb7e5447b997610e24e64de29df4591e4bb9e476087ef`，
   回滚标签为
   `umanewsbot:rollback-pre-five-region-race-live-85948707-20260719T111505Z`。
2. 发布前数据库 custom-format 备份路径为
   `backups/db/pre-five-region-race-live-85948707-20260719T111505Z.dump`，
   大小 `204,512,228` bytes，SHA-256
   `98833a3d9dd5ebd74eb5c7d46ac44caa9b3d5d9ab6e310ec02137fe612e79c89`；
   非空检查和 `pg_restore -l` 通过。`.env` 备份为
   `.env.backup.pre-five-region-race-live-85948707-20260719T111505Z`、权限
   `0600`。filtered rollback env SHA-256 为
   `cda13ce08c6a6d03ffcb4812cf1e1bc1d56fa7eae2244d7cf72330869811062e`。
3. 发布顺序为：历史 runner `migration_safe` 预检；停止 Beat；等待 Celery
   `active=0 / reserved=0`；停止两个 worker；备份；retag reviewed image；一次性 web
   容器执行 `migrate/check/makemigrations --check/collectstatic`；重建 web、普通 worker
   与 race-live worker；健康后最后重建 Beat。
4. `stable.0047_race_live_public_beta_controls` 成功应用。四个 app 容器 image/revision
   一致；Django check、worker ping、内部和公网 healthz、event 924、五地区
   `/races/?region=...` 页面和近期 traceback/critical/integrityerror 日志检查均通过。
   event 924 当前 revision ID、content SHA、7 条结果和 provisional 页面未变化。
5. 切换后必须继续保持
   `RACE_LIVE_SCHEDULER_ENABLED=false`、
   `RACE_LIVE_MONITOR_ENABLED=false`、
   `RACE_LIVE_ENABLED_REGIONS=`，直到逐地区自然赛程 proof 通过。当前 selector
   `claimed=0 / dispatched=0`，active claim、`celery` 和 `race_live` queue 均为 0。
6. 本轮来源探针只保存去标识元数据：Free 端点 3 个请求均为 200；法国 event
   733–735 因 coupled-entry 重复参赛编号触发 `racecard_schema_invalid`，日本
   80/81/185 与美国 420 为 `racecard_not_found`。这些是 fail-closed blocker，
   禁止据此开启对应地区或称其已公开上线。

### 2026-07-19 发布证据与 rollback readiness 补充

1. 来源 proof 目录：
   `/opt/umanewsbot/runtime/race_live_racecards/source-proof-free-20260719T112200Z`。
   `manifest.json` SHA-256 为
   `26af97b56781803de44e418b8693ca13e1fff61f653f44a4acffb27b78ae3bfe`；
   `requests.jsonl` SHA-256 为
   `98e513464736082176bfa91b7579e45326d7228653ad6ac8090e92890d69127a`；
   `summary.json` SHA-256 为
   `1369c0c27af746891bbfdf932010601e3e6def82eba749452cf1522e4de9db79`。
   三个文件均为 root-owned `0600` regular file；请求状态和集合计数必须以
   `requests.jsonl` 为证据，不得只引用 summary。
2. rollback artifact 目录
   `/opt/umanewsbot/runtime/race_live_rollback/five-region-race-live-85948707-20260719T111505Z`
   当前只有 `rollback.filtered.env` 和 `.sha256`，均为 root-owned `0600` regular
   file；没有 `manifest.json`。因此数据库/旧 image/环境回滚可用，但 frozen release
   image one-shot 的 result/policy business rollback 未就绪。

### 2026-07-19 rollback 门禁更正记录

- 冻结要求仍是 release artifact 在代码发布时保存 rollback manifest 路径和 SHA；
  本次实际未生成 manifest，故 Gate D
  未完整满足、release evidence closure 未完成。
- 当前只记录缺口并保持 scheduler/monitor false、enabled regions 为空；不得在
  evidence-only 通道把“发布前”改写成“promotion 前”。补救 manifest 的生成、SHA
  绑定和只读验证必须另走受审与授权流程。

## 2026-07-19 准实时 Beta Gate 修复候选运行手册

本节仅描述待审核候选；在成功代码 review、新 fingerprint 和该精确版本用户授权前，
不得在生产执行。

1. 候选镜像构建后、切换前，必须先确认 Beat/worker 已停、Celery active/reserved、
   `celery`/`race_live` queue、全库 race-live claim 均为空，且
   `RACE_LIVE_SCHEDULER_ENABLED=false`、
   `RACE_LIVE_MONITOR_ENABLED=false`、
   `RACE_LIVE_ENABLED_REGIONS=`。目标 event tracking 必须全关且
   `next_poll_at/token/expiry` 为空。
2. 对当前公开 provisional event 使用候选镜像生成 bundle：

   ```bash
   python manage.py prepare_race_live_rollback_bundle \
     --event-id 924 \
     --reviewed-release-image-id 'sha256:<64hex>' \
     --filtered-env-sha256 '<64hex>' \
     --approved-commit '<40hex>' \
     --run-id '<release-run-id>' \
     --output-root '/run/race-live/rollback'
   ```

   输出目录必须为 root-owned `0700`，且只含 root-owned `0600`
   `manifest.json`、`report.json`、`sha256s.json`。记录 manifest SHA 后，用同一
   approved commit 和完整 image ID 继续；禁止 mutable tag、复制后改写或覆盖同名
   run。
3. 先 dry-run，再用 manifest 内精确确认串进入 maintenance：

   ```bash
   python manage.py transition_race_live_rollback_maintenance \
     --manifest '<absolute-manifest-path>' \
     --expected-manifest-sha256 '<64hex>' \
     --expected-approved-commit '<40hex>'

   python manage.py transition_race_live_rollback_maintenance \
     --manifest '<absolute-manifest-path>' \
     --expected-manifest-sha256 '<64hex>' \
     --expected-approved-commit '<40hex>' \
     --apply \
     --confirm 'ENTER_RACE_LIVE_ROLLBACK_MAINTENANCE_924'
   ```

   apply 后四层必须精确为 maintenance snapshot，event 924 无缓存 read gate 必须
   隐藏；任一 scope、tracking、claim、settings、manifest 或 SHA 漂移即停止。
4. 只允许按
   `validate -> restore-policies-coarse -> validate -> restore-policy-event`
   使用受审 one-shot。合法状态依次为四层 maintenance、三层 restore/event
   maintenance、四层 restore；第二次 validate 失败时不得声称四层仍 off，也不得跳过
   validator 直接恢复 event。generated manifest 必须包含
   `expected_current_revision_id`；两个 validate 和两个 restore 阶段都必须保持
   scheduler/monitor=false、enabled regions 为空，并在任何 policy 恢复写入前核对
   current pointer。pointer 漂移时保持当前阶段原样并停止。
5. 四层精确恢复、event 924 同一 provisional revision/7 条结果重新可见后，才允许
   应用 `stable.0048` 并切换候选镜像。切换后继续保持全部新范围关闭，再对法国
   event 733–735 做一次有界 prepare；仅消除 `racecard_schema_invalid`，不等于授权
   initializer、shadow 扩大或公开 promotion。
6. migration 删除 legacy runner 的号码唯一约束并增加非空 external ID 条件唯一约束。
   旧镜像可读取 additive 列；若新版本已产生 coupled legacy rows，代码回滚时必须保持
   对应 event/地区 tracking 关闭并禁止旧动态 updater，完全撤销只能使用切换前已验证
   数据库备份。

## 2026-07-20 P0 马全范围来源生产写入记录

1. 写入前备份：
   `/opt/umanewsbot/backups/p0-horse-full-scope-precommit-20260720T063831Z`。
   dump SHA-256：
   `f773f5ec0a98974cc402b202cfe2f0eed91fc4f022e58a621f2c7b2b63b96378`；
   `.env` SHA-256：
   `e24208729cfba44fd71d9b2ed343dd93d3437d3f6fb80f3f459759523158b566`。
2. 禁止在当前 `2 vCPU / 4 GiB / no swap` 主机再次执行无地区
   `p0_horse_profiles --sync-sources --commit` 单事务。该路径已实证达到约
   `1.4 GiB` Python RSS 并触发整机 OOM。
3. 本次成功路径为先停 beat、worker、race-live worker，临时启用 `1 GiB` swap，再分别执行
   `--region france|hong_kong|united_kingdom|united_states|japan --commit`。
   五批输出保存在生产 `runtime/p0-horse-source-sync-*-20260720.json`。
4. 无五地区归属的 `7670` 条 translated horse term 仅调用与正式服务相同的
   `_find_or_create_profile_for_term` / `_upsert_p0_source`，每 `500` 条独立事务提交；
   不处理赛事、不修改身份门禁。
5. 完成后必须恢复三个 worker、删除临时 swap，并检查：
   `manage.py check`、migration 至 `stable.0052`、内外 `/healthz/`、有效来源分类总数、
   translated term 缺失来源数和身份冲突数。本次最终为 `56745` 条有效来源、
   `46318` 匹唯一 P0 马、translated term 缺失 `0`、待处理参与项冲突 `65042`。

## 2026-07-23 公开门户 P1–P3 生产发布记录

1. 发布提交：`bc7e2df047a20a997de1620688f1c7de4a5c52c4`；生产目录：
   `/opt/umanewsbot`；编排文件：`docker-compose.prod.lowcost.yml`。
2. 切换前确认生产 HEAD 为 `f0d3fbd6e71374b425e3bbae2041d47758270546`、Django check 和
   `/healthz/` 正常、运行中的 `ExternalDataImportRun(status=started)` 为 `0`。
3. 数据库恢复点：
   `backups/db/pre-portal-redesign-20260723_024424.sql.gz`，大小 `232004041` bytes，
   SHA-256 `9bdb7a53cde72c1302c86886415b5d59f4a088a5ae93e0325d34c8b0261fb6b2`；
   `gzip -t` 已通过。环境恢复点：`.env.backup.portal-redesign-20260723_024424`。
4. 使用 `bash ./deploy_lowcost.sh` 部署后，必须额外核对 `race_live_worker` image ID；该脚本本次
   没有重建此服务，已执行：

   ```bash
   docker compose -f docker-compose.prod.lowcost.yml \
     up -d --no-deps --force-recreate race_live_worker
   ```

5. 最终四个应用服务统一镜像：
   `sha256:69ed2bd9f3f7ecc581c2caba4704bd7b1764fc02af6a2663b78f599217b23696`。
   回滚时将代码恢复到上一个提交 `f0d3fbd6e71374b425e3bbae2041d47758270546` 并用同一低成本
   Compose 重建全部四个应用服务；本次无迁移，只有确认数据受损时才恢复数据库备份。

## 2026-07-24 HRN 新闻正文边界发布记录

1. PR `#12` 的任务提交为 `9fded052`，合并后的生产 revision 为 `0e4a3520`。发布前数据库恢复点为
   `backups/db/pre-news-body-boundary-20260724T015733+0800.sql.gz`，大小 `237423530` bytes，
   SHA-256 为 `250e81de23816d00c7c15d9fd354867d28521f56edca980786f7f557c4a4330d`；
   `.env` 恢复点为 `.env.backup.news-body-boundary-20260724T015733+0800`。
2. 发布前停止 beat，等待两个采集任务及下游术语/自动化任务自然完成；`active/reserved=0` 后停止
   普通 worker 与 race-live worker。外部导入运行数为 0。本次无 migration。
3. 首次 `deploy_lowcost.sh` 在新 web 已启动后，外层 `collectstatic` 与 web 启动脚本并发处理共享
   static volume，出现瞬时文件不存在。确认新 web 自身 collectstatic 成功且 healthy、migration 未变化后，
   单进程重跑 collectstatic 成功，再显式重建 `worker / beat / race_live_worker`。
4. 最终 `web / worker / beat / race_live_worker` 统一镜像为
   `sha256:36b9a75b854f9be0ccfb7beca164a69e9a5f79bab77b4bcd2f4cbb9f50356733`。
   Django check、migration drift、worker ping、内外 healthz、首页及新闻详情 HTTP 通过；队列为空，
   近 10 分钟四服务无严重错误。
5. 生产镜像只读解析 `9623` 的真实来源页得到 `.article-body / ok`，正文 9,355 字符，已知框架文本
   命中 0。自然 HRN job `27503 / 27504` 均成功但没有全新文章，因此 Gate A 的新稿翻译/公开验收
   尚未完成。重复抓取已清理 `9623` 原文层，但历史中文 `effective_body` 仍含污染；未运行历史 repair。

## 2026-07-24 英文单词型马名语境门禁 shadow 发布记录

1. 发布证据：受审 fingerprint
   `7ff685325de93578f0131a73746a50f23d627f5cd1dbb266f2afee372eb9aabd`，
   content hash
   `53d957ed41e6e0e5e0e68f4331cf9d0078a563129fbb9a995c845895f381a2cb`；
   review session `019f9252-e50c-7d30-8e49-d6765919a51d` 的 CORE 结论为
   `APPROVED`。本地完整矩阵 `333/333`、语言专项 `77/77`，Django、migration
   与 diff 检查通过。
2. Git 链路：release commit
   `1c34a00715aa3a0ac49153553622360afa10e049`，PR
   [#14](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/14)，merge/生产
   HEAD `2a3c249f4ffce2e97a2133f9a932234f74ec1e1e`。生产目录
   `/opt/umanewsbot` 从 `97a38cf5` 快进，执行 `bash ./deploy_lowcost.sh`；本次无
   migration。脚本重建 `web/worker/beat` 后，另行执行低成本 Compose 的
   `up -d --no-deps --force-recreate race_live_worker`。
3. 最终 `web/worker/beat/race_live_worker` 统一镜像为
   `sha256:316e4563b306ca70bde8e55a78c79d48de1ac8ca09d7259a8a7d0b4f5044c364`，
   web healthy。部署前 Celery active/reserved 为空；部署后两节点 ping 正常，仅自然
   netkeiba crawl 为 active，reserved 为空。外部导入 `started=0`、locks `=0`，宿主磁盘
   可用 `54G`。
4. 验证通过：Django check、`makemigrations --check --dry-run`、容器内 healthz、公网
   `umafans.run` 与 `www.umafans.run` healthz、首页和 admin login，HTTP 入口均为 200。
   生产配置仍为 `ENGLISH_TERM_CONTEXT_MODE=shadow`，因此部署只增加 shadow 分类与审计，
   不改变实际门禁。
5. article `9595` 只读验收使用进程内 override `enforce` dry-run：
   `workflow=published`、`automation=auto_published`、`horse_alert_codes=[]`；
   `Logician` 为 `confirmed_horse / needs_preserve=false`，`Africa/East` 为
   `common_word / needs_preserve=false`。该操作没有保存、重处理、通知或生产数据写入。
6. 回滚边界：若代码发布引发异常，须先取得独立回滚授权，再将生产代码恢复到
   `97a38cf5`，使用同一低成本 Compose 重建 `web/worker/beat/race_live_worker`，并复核
   四应用镜像一致、web healthy、Django check、migration drift、Celery ping 与内外 HTTP。
   本次无 migration、无历史 apply、无业务数据写入，正常代码回滚不恢复数据库。
   回滚期间及回滚后保持 `ENGLISH_TERM_CONTEXT_MODE=shadow`。
7. `shadow -> enforce` 是独立生产变更，必须重新明确授权并执行切换前后验证；deferred P2
   `fix-term-discovery-visible-occurrence-aggregation` 不在本次发布或回滚范围。

## 2026-07-24 赛事日历月份与移动端等级徽标发布记录

1. Git 与范围：
   - PR `#17` merge/生产 HEAD：
     `3772256e606e3f62081eecec162fecedbd1aa23d`。
   - 生产从 `438ab6a14f9665fd77318d8c12f8bc5a3ca63690` 快进；本次无 migration，
     不执行赛事、新闻或历史数据写入。
2. 发布前门禁：
   - Celery 两节点 active/reserved 均为空，外部导入 `started=0`、外部锁 `=0`；
     historical runner preflight 返回 `migration_safe`，宿主磁盘可用 `54G`。
   - 数据库备份：
     `backups/db/pre-race-calendar-responsive-20260724T173452+0800.sql.gz`，
     `242013429` bytes，SHA-256
     `2ed8f391b4b37e3590e22ad558ce6237a53ded073f6a5920aafacad8d8f4ce7f`，
     `gzip -t` 通过、权限 `0600`。
   - 环境备份：
     `.env.backup.race-calendar-responsive-20260724T173452+0800`，权限 `0600`。
3. 部署过程：
   - 首次 `deploy_lowcost.sh` 在构建前停止，因为旧 Compose 创建的 web 容器没有新版
     historical preflight 要求的 Docker health metadata，实际状态为
     `running / health=none`；当时内外 healthz、PostgreSQL `pg_isready`、Redis `PING`
     和 historical runner `migration_safe` 均已独立验证。
   - 按脚本第 19–28 行执行等价低成本 Compose 序列。新镜像构建成功后，drain 脚本因
     worker 已在备份阶段安全停止而无节点响应；使用部署前两次空 active/reserved 证据，
     从保持 worker 停止的下一安全步骤继续。
   - 强制重建 `web / worker / beat / race_live_worker`；无待应用迁移，collectstatic
     输出 `131 unmodified / 360 post-processed`。
4. 生产结果：
   - 四个应用服务统一镜像：
     `sha256:90c98db7eb048949507bbc3d335ed7b989dc9ce6dab1d3576a5242c2c4d10e49`；
     web healthy，两节点 Celery ping 正常，reserved 为空，beat 恢复后仅有自然新闻任务。
   - Django check `0 issues`，`makemigrations --check --dry-run` 为 `No changes detected`；
     外部导入/锁仍为 `0/0`，historical runner 仍为 `migration_safe`，近 10 分钟四服务
     无 traceback、critical、IntegrityError、exception 或 error。
   - `umafans.run`、`www.umafans.run` healthz、首页、`/races/`、`/admin/login/`
     均返回 HTTP 200；生产静态资源为 `public.e7932bf85b07.css`。
5. 真实浏览器验收：
   - 1440px：日期轴直接显示 `6月24日 / 6月28日 / 7月1日`，G1、G2、JPN1 均为
     `42×42px`，无横向溢出。
   - 390px：长赛事名换行且徽标保持 `flex: 0 0 42px`、水平垂直居中，页面无横向溢出，
     today 状态仍存在，浏览器控制台无错误。
   - 320px：抽检 G1、G2、JPN1 仍为 `42×42px`，页面 `scrollWidth=clientWidth=320`。
6. 回滚锚点：
   - 代码回滚父提交为 `438ab6a14f9665fd77318d8c12f8bc5a3ca63690`。
   - 旧 web/worker 镜像分别保留为
     `umanewsbot:rollback-pre-calendar-web-20260724T173452` 与
     `umanewsbot:rollback-pre-calendar-worker-20260724T173452`。
   - 本次无 migration 和业务数据写入；仅当确认数据损坏时才恢复数据库备份。

## 2026-07-26 HRN dialog 残留与机构译名发布、历史重处理记录

1. 发布身份：
   - PR `#22`，生产 revision
     `8cbee3e70bb1044248a18ed5521a1273d629d404`。
   - `web / worker / beat` 镜像：
     `sha256:02a83fbde219827ce5a49c633086057eb7d2957abb1e19c7b386205fc914c60e`。
   - 当前低成本运行态未包含 `race_live_worker` 容器，本次未启动或重建该服务。
2. 发布前恢复点：
   - `.env.backup.pre-hrn-residual-20260725T162001Z`，SHA-256
     `baef570546106ba5ec54f781b1c2f8e70ce14699b339d64a12d06cd7611632a3`。
   - `backups/db/pre-hrn-residual-20260725T162001Z.dump`，
     `250941179` bytes、mode `0600`、SHA-256
     `0ebd22ebdf419e8819545bb31ee97658ab43dc56ce82f95ca88fbd9fbd415296`，
     `pg_restore -l` `1062` 行。
   - 旧镜像标签：
     `umanewsbot:rollback-pre-hrn-residual-20260725T162001Z`。
3. 发布过程：
   - historical runner preflight 为 `migration_safe`，外部导入 `started=0`；
     正常抓取任务自然结束后 active/reserved 为空。
   - 生产从 `9b58bfd` 快进到 `8cbee3e7`，执行 `bash ./deploy_lowcost.sh`；
     无待应用 migration，collectstatic 成功。
4. 历史写入：
   - 每批 apply 前停止 beat，并由 drain 脚本取得 worker active/reserved 双快照为 0；
     apply 后立即独立 verify，再恢复 beat。
   - 冻结 36 篇结果：`12 applied / 18 translation_failed / 6 review_rejected`。
   - post-deploy inventory 另发现 8 篇旧正文只多 `Race Video / ×`，以独立 cohort
     `f70b56c3...e137` 处理并 `8/8 verified`。
   - 5 个批次均位于
     `/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/`；
     各目录内依次记录
     `candidate_manifest.json / approved_manifest.json / rollback/receipt.json /
     rollback/rollback_manifest.json` 的完整 SHA-256：
     - `apply-b3-01/`：
       `adc962890a5fcbdc415ec4fbcf6d2349a911c00eb0b801abfb5ac049428776c7 /
       6e9ef52957cc91245da8d9949d9f8a66f5d89f41d824b929a1880246efd453fa /
       6bb060584d90bddf0b69d9d990cb3ec40458f70c9e8f073375675d0583f96e2a /
       1388a8cb6aa65eae94b56c3564a6a93110e2a8c2a10fb117614986489bc6704a`。
     - `apply-b3-02/`：
       `09bac09c7b3b6f9455d607709da736dc011ef0156bc0c8d35a664fa0b2350019 /
       bca594b70d1d33e491375aeda12276d48610b8f8a0ed352e99f87bde6eb49e22 /
       23b01b5bca9dd86d9590be6d29e3352196be505e3fe4e14fa3e3c6e6c646daa0 /
       067c73e5fe6f149f4fb2924e392c8d0ba52d1d64d2dce5bcd71d062193d3e4ce`。
     - `apply-b3-03/`：
       `5df4d8468753b4e8975d341e3a6fe49c48e6c04ee4dbbf63095e673b996f0332 /
       4525089e4886f554acb29d84fe681b5776f9fb80d36433f2ca01ae473350a21a /
       6bae78c3dc3d9e93caf3fe114a4b710996b7fcc30df817aeec0b8b88cdae19ca /
       b69f23be9dd5a1854f7b51b8df4567044daa16fab97056cfddc5ec2d5812e6d3`。
     - `apply-term-retry-01/`：
       `c711e0caac96f737b29a51a3586fde68d9375394497974ef90110cf6e20dab7a /
       39f204d9dd10b192eed7c7626a5be9756f322e587ddfde968286ab5abf892130 /
       94d2657cbedb5e085389942175e3f9ac345c560ac24834e163e4816890f2adca /
       12dd25563f4612b4cb0ecf7de85e28044dc7b78d889888b77f51a82317295d15`。
     - `apply-discovered-dialog-01/`：
       `a049dc6eda61f31d71c4f5263952cc63768edc0e44b73d8fa0b1aa584cbeb794 /
       7520ee9bd9ee785253c0813fd8146377dffbb01f81c388232e9645a25e387b34 /
       73c5b5fac249563cdcf91fa5c46188658817e77a040ea0fd1094b7c9be19a95e /
       02a40848d33a9f265bd7c23198e29129a61deac4f824af309c8f950b4e52e062`。
5. 终验：
   - 282 篇 cohort SHA `3b297aaa...c0d` 未漂移；
     `source_clean 171 -> 183`、`source_changed 111 -> 99`、`source_blocked=0`。
   - 24 个证据文件递归 SHA 校验和 5 个 batch verifier 全部 `status=ok`。
   - 20 篇正文与当前解析器逐字一致；13 篇公开详情、首页及两个正式域名 healthz 均为
     HTTP 200；Celery active/reserved 为空。
   - 20 篇 QQ delivery、workflow 和公开时间写前/写后零漂移，不重发 QQ。
6. 总体 closure：
   `/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/hrn-residual-20260725-overall-closure.json`，
   SHA-256
   `ab0d93035afc593ccb5822323c2e27ffa1f48b53ec8c53030023cbcd21d33328`。
7. 回滚：
   - 单批业务回滚必须使用该批 rollback manifest + receipt SHA 做 CAS；
     当前数据库已被外部编辑时 fail closed。
   - 代码回滚使用上述旧镜像标签；本次无 migration，正常代码回滚不恢复数据库。
   - 仅确认本轮造成数据库级损坏时，才进入整库恢复窗口。

# 赛事生命周期自动更新发布入口（规划中，阶段 A 代码审查进行中）

精确方案见 `docs/changes/automate-race-event-lifecycle/rollout.md`。阶段 A 已实现，
56 项测试通过；当前代码审查进行中，未部署、未写生产。

## 2026-07-27 生命周期阶段 A 关闭态更新

阶段 A 后续已部署但显式关闭，生产 dry-run 已完成；shadow/enforce 未授权。恢复点和证据见
`docs/changes/automate-race-event-lifecycle/production_release_20260726.md`。

## The Racing API schema v2 proof runner 候选操作边界

- 当前候选新增 `run_race_live_source_proof --region <region>`；schema v2 缺失或非法 region
  必须在 transport 前失败。
- 在当前候选完成独立 review、冻结 fingerprint 并取得最多 3 请求的独立用户授权前，不得在
  本地或生产执行 `--confirm-network-proof`，不得读取/复制/输出 production secret。
- 获得联网授权后仍必须使用唯一 output 目录、精确 registry SHA、`--max-requests <= 3`，
  先核对 registry 有效期和 evidence 新鲜度；失败 artifact 也必须保留，禁止原目录重跑覆盖。

## 未来重点赛事赛前数据候选与 apply 边界（方案阶段）

- 当前没有可执行命令或已批准 artifact；不得根据
  `docs/changes/fetch-upcoming-key-racecards/` 直接抓取或写库。
- 后续实现必须保持：
  `inventory -> source cache -> immutable candidate -> dry-run/review -> approved SHA ->
  transaction apply -> independent verifier`。
- 抓取层禁止写 `RaceEvent`/`RaceEventRunner`；空表、局部表、身份/时间/许可冲突整场
  fail closed。第三方 racecard 不得标成 official。
- 本地/测试 apply 也需明确目标数据库与批次；生产 apply 必须另备份、冻结精确 SHA、字段 diff、
  影响行数和 rollback manifest，并等待用户对该批次授权。
- 本 change 不启用 Celery beat、race-live scheduler、monitor、公共发布或每日自动化。

## P0 官方出马页面 URL 文档（方案阶段）

- 候选宿主目录：
  `/opt/umanewsbot/runtime/upcoming_racecard_urls/`；容器目录：
  `/app/runtime/upcoming_racecard_urls/`。计划由 default worker 使用 bind mount 持久化，
  beat 只 dispatch，不需要写挂载。
- 候选产物为不可变 `generations/<id>/` bundle，由单一原子 `current` 相对 symlink 切换；
  人工固定读取 `current/latest.md`。manifest/JSON/Markdown SHA 不一致时视为不可接受，不能
  交给人工录入。
- 功能开关默认 false。未完成代码 review 和精确发布授权前，不得创建生产目录、修改 `.env`、
  部署、联网或启用 schedule。
- 发布候选应先验证 flag-off 的 `network_requests=0/file_writes=0`，再按 provider route
  独立启用；总任务开关不能覆盖 provider 的 `automation_allowed=false`。
- 回滚先关总开关，再恢复镜像/Compose。此链路不写业务数据库，正常回滚不需要恢复数据库；
  最后已验证文档默认保留供人工参考。
- 当前本地实现的 tracked registry SHA-256 为
  `d04ec36924fc120ea6a497634f2f7ae9b0e5831ccf9ecb731979c4e855ed3fe6`，六条 route
  均自动访问关闭。发布时若仅把总开关设为 true，验收必须明确
  `transport=0 / URL found=0 or only pre-existing preserved / 未启用 provider`，不得把
  “任务成功生成暂无文档”描述为抓取成功。

## P0 官方出马页面 URL 文档（provider route 上线候选）

- 当前候选 registry SHA-256：
  `c96f042941d38682ec3c77eb57b80f90d7810d69829543b82d6dcfee09819876`。
- 允许自动 transport 的精确全集仅为：
  - BHA `HEAD https://www.britishhorseracing.com/racing/fixtures/upcoming/`，同批去重上限 1；
  - Equibase `HEAD https://tvg.equibase.com/static/entry/RaceCardIndex{track}{MMDDYY}USA-EQB.html`，
    同批上限 2、同 host 最小间隔 5 秒。
- France Galop、JRA、NAR、HKJC 必须为 transport 0。HEAD 不 follow redirect、不读取 body；
  BHA 只显示“官方日期索引（需人工确认）”，不得称为精确单场 racecard。
- no-write proof：
  `docs/changes/schedule-p0-official-racecard-url-discovery/provider_no_write_proof_20260727_v3.json`，
  SHA-256
  `7e4886a8ff9f02a9c39ef1e8e3e414692ad61528e184dbadb2d4b3c37b9f4b94`。首次与 v2
  proof 均已被 supersede，仅保留审计，不得用于发布。v3 以联网前 fingerprint + 精确
  post-proof 文档 allowlist 解决 artifact 自引用，reviewer 必须确认 allowlist 外无变化。
- 发布前必须等待最新 code review 后的新授权。授权后先备份 `.env` 与镜像，创建
  `/opt/umanewsbot/runtime/upcoming_racecard_urls/`，保持功能开关 false 部署并完成 flag-off
  smoke；随后才可按精确 route 做单次生产验证并启用开关。任何代码/registry 变化都会使 proof、
  review 和授权失效。

## P0 官方出马页面 URL 文档（2026-07-27 生产发布记录）

1. 发布身份：
   - PR `#32`；
   - production/main：
     `cfba71518f1024d54cd5553b7f0bb35c780f5959`；
   - `web/worker/beat` image：
     `sha256:a11d072d8a8fc9cc268db996bc916751cea51fe0b7a7cdfc16b715ab0f3e4bf7`。
2. 恢复点：
   - `.env.backup.pre-p0-url-20260727T062445Z`，mode `0600`；
   - `backups/db/pre-p0-url-20260727T062445Z.dump`，mode `0600`，
     `259806424` bytes，SHA-256
     `5a02d4b2e2da1f9040920e046bf4bff75790c9dc5ee4a9aed82390acfd894e76`，
     容器内 `pg_restore -l` 通过。
3. 关闭态 smoke：
   - flag=false 时直接调用返回 `enabled=false`；
   - P0 `TaskExecutionLog 0 -> 0`；
   - `runtime/upcoming_racecard_urls` 子项 `0 -> 0`。
4. 启用与验收：
   - worker/beat flag=true；
   - Celery timezone=`Asia/Shanghai`；
   - schedule=`30 6,18 * * *`；
   - 两次受控运行各生成一代，`current` 指向
     `5868715fb4406b552132adf4e7a24372dba72253d20b25196ffc1368b2ce68db`，
     verifier 通过；
   - 两次运行均为 `future_expected=6 / orphans=5 / listing_reachable=3 /
     found=0 / not_available=8 / blocked=6 / errors=2`。
5. 当前降级：
   - BHA 三个日期索引可用；
   - Equibase DMR/CNL 从生产主机连接超时，固定记录
     `source_error/error_without_previous`；
   - 不切换为第三方 URL、不猜测成功，保留 06:30/18:30 低频自动重试。
6. 数据边界：
   - 新增 P0 `TaskExecutionLog=2`；
   - 两次运行范围内 `RaceEvent/RaceEventRunner/RaceEventResult/ExternalRaceEntry/
     ExternalRaceResult` 更新数均为 `0`；
   - 未启用 race-live、lifecycle、历史抓取、公开发布或 QQ。

### 2026-07-27 开关恢复与补跑事实

- 后续部署将 P0 开关恢复为 `false`，当日 `18:30` 调度未执行。用户授权后确认生产
  `5fed1a96` 的 P0 实现相对原发布版无差异、registry SHA-256 仍为
  `c96f042941d38682ec3c77eb57b80f90d7810d69829543b82d6dcfee09819876`。
- beat 暂停期间默认队列 `29 -> 0`，Celery drain 为
  `active=0 / reserved=0 / active_confirm=0`。`.env` 备份
  `.env.backup.pre-p0-reenable-20260727T114553Z` 为 `0600`，随后只恢复 P0 开关。
- worker 重建连带重建 db/web；业务表总数保持不变且健康检查通过后执行补跑。补跑成功，
  `TaskExecutionLog 2 -> 3`，generation 更新为
  `19679c03583afb492a873c3ff5dfbdc6495ed69cb8af5e9c99b9c91b5dcc8612`。
- 补跑统计为 `future_expected=6 / orphans=5 / listing_reachable=3 / found=0 /
  not_available=8 / blocked=6 / errors=2`；五张赛事业务表的运行窗口更新数均为 `0`。
- worker/beat 最终开关均为 true，调度保持 `Asia/Shanghai` 的 `30 6,18 * * *`；
  Django check、generation verifier 和内外 healthz 通过。beat 恢复后的默认队列快照为
  `37`，均为其他既有周期任务；未清理队列或追加 P0 运行。

## 2026-07-27 赛果缺口恢复发布前门禁

- 当前仅完成本地实现，禁止直接运行生产 inventory、联网 candidate prepare 或 apply。
- 发布前必须先完成独立原生只读代码审核，再针对精确 fingerprint 取得 release 授权；部署时
  保持恢复 apply、网络自动化、TRA public、scheduler 和 publication 开关关闭。
- 部署后先运行只读 inventory，冻结
  `59 event rows / 50 race groups / 40 missing / 9 duplicate groups / event 924 provisional`
  守恒。任何 ID 或计数漂移都停止，不通过调整分母继续。
- 联网 prepare 需要对精确 source map 的新授权，并受 `<=75` 请求、单请求 `<=30s`、
  cache `<=512 MiB` 约束；manual-only 官方 route 请求必须为 0。
- 生产 apply 需要 candidate/approval 双 SHA、逐场预计写入、canonical 映射、blocker=0、
  队列排空、备份和写前快照的再次授权。执行后逐地区立即 verify 与幂等重放；任一 CAS、
  ledger 或数据库身份不一致即停止。

## 2026-07-27 赛果缺口恢复关闭态部署与联网阻断记录

1. Git 与镜像：
   - PR `#28` release commit：
     `88cc4eafe4a7b5263aa2a6c30cd7d70978323989`。
   - merge/生产 HEAD：
     `dfbd24e10f5910580945f29fe19219b7d838730c`。
   - `web/worker/beat` 应用镜像：
     `sha256:35a53589e051c39806397fe8aec1e00f0bcbd1df9d0a9ffec29a72f35dc4d751`。
     race-live worker 已重建为同一镜像但保持 Created/停止。
2. 恢复点：
   - PostgreSQL custom dump：
     `backups/db/pre-race-result-recovery-20260726T200011Z.dump`，
     `257629113` bytes，SHA-256
     `682848bdb63edc43b809056fa3a5b1331ebca7f2f6e2cfae806208fa105c9efc`，
     mode `0600`，`pg_restore -l` 通过。
   - `.env.backup.pre-race-result-recovery-20260726T200011Z`，mode `0600`。
3. 关闭态：
   - `RACE_LIVE_SCHEDULER_ENABLED=false`
   - `RACE_LIVE_MONITOR_ENABLED=false`
   - `RACE_LIVE_ENABLED_REGIONS=`
   - `RACE_LIVE_RUNNER_MODE=disabled`
   - `RACE_EVENT_LIFECYCLE_ENABLED=false`
   - `RACE_EVENT_LIFECYCLE_MODE=off`
   - `HISTORICAL_RACE_BACKFILL_ENABLED=false`
   - `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`
   - 4 条 race-live publication policy 为 off，enabled allowlist 为 0。
4. 迁移与验收：
   - `stable.0060_raceeventproductcanonicallink` 成功，表记录为 0。
   - Django check 通过；公网 HTTP `healthz` 与 `/races/` 最终为 200。
   - Compose `create race_live_worker` 曾连带把 db 容器重建为 Created；PostgreSQL volume
     未删除。启动 db 并等待 healthy 后重启 web/worker/beat，`RaceEvent=9867`，页面恢复。
     后续禁止用未加 `--no-deps` 的 `compose create` 维护停止态 worker。
5. 只读 inventory：
   - 文件：
     `runtime/race_result_recovery/inventory-20260726T200544Z.json`。
   - 文件 SHA-256：
     `a4380f2b4bb5fafe96f7990e2bc0ef9e032a7d84e17718ebd0b091d5b60b267a`。
   - manifest SHA-256：
     `f3a4cb7f26bfac5db4312af3f3af46d9fe11f9e50d2241ef54d4606403dbed1b`。
   - 守恒：
     `59 rows / 50 groups / 40 missing / 9 duplicate-zero /
     9 duplicate-confirmed / 1 provisional(event 924)`。
6. 联网 prepare：
   - 在网络保持关闭的生产只读调用中，plan 校验 40 个冻结 ID 后，
     `expected_targets_from_plan()` 报 `expected_target_empty`。
   - transport 请求 `0`、manual-only 请求 `0`、candidate/source cache `0`、赛果业务写入 `0`。
   - 禁止绕过 runner。先修 recovery event-ID snapshot 和 JRA 受控请求输入，完成新一轮测试、
     独立 review、发布和联网授权后再执行。
# 2026-07-27 赛果恢复联网 prepare 阻断修复发布前门禁

- PR `#29` 已合并为 `main@e7dc1b20aa36b311ade2497b96a62b15451942d2`；当前修复分支为
  `codex/fix-race-result-recovery-prepare`，未发布、未部署、未触网。
- 修复版部署前必须取得最新独立代码审核和精确 release 授权。部署继续保持 race-live、
  lifecycle、historical network/apply、scheduler 和 publication 全关闭。
- 部署后不得沿用此前已消耗的联网授权。应先在网络关闭状态用冻结 plan 重新生成 40 条
  expected-target snapshot；plan 必须绑定 inventory 文件路径、文件 SHA 和内部 manifest SHA，
  同时必须携带当前批准的 `source_map_version` 并精确匹配 40 场 source map，再通过数据库
  drift verifier。随后核对 JRA/NAR 与 TOBA/Sporting Life 的 source-scoped CSV，
  审批 snapshot 后再取得新的有界联网授权。
- JRA 执行时必须同时出现共享 `request_budget.json` 和
  `control/jra_detail.request-state.json`/host-state 证据；总请求仍 `<=75`、单请求
  `<=30s`、间隔 `>=1s`、source cache `<=512 MiB`，每个 redirect 分别计数，manual-only
  请求数必须为 0。JRA scheduled 目标仅可通过 plan 注入的显式 recovery mode 读取。
- 任一 event 消失、地区/adapter input 漂移、request policy 摘要变化、来源交叉分片或预算账本
  缺失都停止，不得手工构造 snapshot、复用旧 approval 或直接运行 adapter。

# 2026-07-27 赛果恢复联网 prepare 阻断修复关闭态部署记录

1. Git 与镜像：
   - 修复提交 `00979dc443979ef0d982ae7776c3ff7dfb3d0572` 经 PR `#30` 合并为
     `main@e2ae3efe2349623dd60745bfef498af31d7d8d84`。
   - 生产 `web/worker/beat/race_live_worker` 统一镜像为
     `sha256:e0a2d3d6612841df64f2ab1b8ca8ff6a749f4b14c8f4e3173317a394250e61a3`；
     `race_live_worker` 通过 `up --no-start --no-deps --force-recreate` 更新后保持
     `Created`，未启动、未消费 race-live 队列。
2. 恢复点：
   - `backups/db/pre-race-result-prepare-fix-20260727T045500Z.dump` 为
     `259584695` bytes，SHA-256
     `3a2d1b91ac1610e42c272957a3055067b1a326b2f11c71a81c3ce099b97cbf5c`，
     mode `0600`，`pg_restore -l` 为 1127 项。
   - `.env.backup.pre-race-result-prepare-fix-20260727T045500Z` 为 mode `0600`。
3. 关闭态：
   - 四个应用容器均为 `RACE_LIVE_SCHEDULER_ENABLED=false`、
     `RACE_LIVE_MONITOR_ENABLED=false`、`RACE_LIVE_ENABLED_REGIONS=`、
     `RACE_LIVE_RUNNER_MODE=disabled`、`RACE_EVENT_LIFECYCLE_ENABLED=false`、
     `RACE_EVENT_LIFECYCLE_MODE=off`、`HISTORICAL_RACE_BACKFILL_ENABLED=false`、
     `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
   - 4 条 publication policy 均为 off。event 924 保留 1 条
     `max_mode=provisional_public` 的既有 allowlist；它在总 policy off 且 race-live worker
     停止时不生效，本次未改写历史授权记录。
4. 验收：
   - Celery 切换前 drain 为 `active=0/reserved=0`；无迁移，`0060` 保持已应用，
     `RaceEventProductCanonicalLink=0`，Django check 通过。
   - 公网 HTTP `/healthz/` 与 `/races/` 均为 200；HTTPS 仍拒绝连接，符合当前项目尚未完成
     HTTPS 接入的既有状态。近 15 分钟应用日志未发现
     traceback、critical、exception 或 error。
   - 本次未运行联网 prepare，`runtime/race_result_recovery` 没有部署窗口内新增文件，
     未生成 candidate/source cache，未执行赛果 apply 或其他赛果业务写入。
5. 下一门禁：
   - 先在网络关闭状态重建并审核精确 40 条 expected-target snapshot 与 source-scoped
     adapter 输入；之后必须取得新的有界联网 prepare 授权，旧授权不得复用。

## 阶段 B0.1 赛后内部参考源发布边界

Sporting Life、ZEturf、HRN 只允许进入 internal reference 链。正式实现后仍按下列独立门禁：

1. 先完成测试先行、实现、完整回归和独立代码 review；
2. 最新 review 后另取 commit/push/PR 授权；
3. 部署授权只允许新增 schema/code/one-shot 命令；不增加 Celery/Beat/task/queue/worker；
4. 部署时不得联网、record、改公开赛事、启动 lifecycle/race-live 或处理积压；
5. one-shot 网络 dry-run 需要新的联网授权，只写受限 cache/artifact；
6. 内部 record 需要新的业务写入授权，只写 reference run/payload/receipt；
7. 连续观察再单独授权，由每天逐来源的 manifest-bound one-shot collect/record 构成；
8. 不存在把内部参考 observation 公开或 apply 的部署步骤。

部署前还必须修复并 review 既有双重 migration 执行入口，确保只有一个进程执行
`migrate --noinput`。阶段 B0.1 若包含 additive migration，不得依赖容器重启从 `DuplicateTable`
恢复。

回滚顺序：停止后续 one-shot -> 确认当前命令已结束/中止且没有数据库事务 -> 必要时回滚镜像。
reference 审计默认保留；由于它不改变公开对象，禁止顺带批量回改 `RaceEvent`、runner/result、
revision、新闻或 QQ。

# 2026-07-27 赛果恢复补缺候选运行记录

- 正式关闭态 prepare：`/opt/umanewsbot/runtime/race_result_recovery/prepare-20260727T073643Z`，
  请求 `73/75`、最小间隔 `1.000064s`、source cache `14760016` bytes、manual-only 请求 0。
- 补缺批次：`/opt/umanewsbot/runtime/race_result_recovery/gap-prepare-20260727T075310Z`。
  event 185 使用 NAR 已发布 racecard/RaceMarkTable 生成 14 条结果；美国 12 场使用
  Sporting Life 生成 82 条结果，TOBA/Equibase 入口只由交互式浏览器结构化记录。
- review manifest SHA-256：
  `ebc84c098a802322eb455f98c6ca22a2161894d7d4954245a2f99e2380461f60`；
  40 场 review-only candidate SHA-256：
  `f40c04265bdb4de418fdc8c97cc4eea9c7329514100809222241391d1e0765b3`；
  完整排名 CSV SHA-256：
  `df3f547104f2e02f32f41e59c37f846c5ecd686f42b230965e7aedefb922447e`。
- 首版 `SHA256SUMS` 因误含自身而校验失败，未作为证据；排除自身的 `SHA256SUMS.v2`
  全部通过。两轮均未写业务数据库；web/worker/beat 的 historical network 与 P0
  discovery/scheduler 开关复核为 false，healthz 为 ok。
- review-only 合并包不得直接用于 audit/apply。必须先发布并部署
  `source_map_version=2026-07-27-gap-v2`，重新运行正式 bounded prepare，再进入人工官方
  route receipt、coverage audit 与 dry-run。
- gap-v2 已以提交 `787d6a1e` 推送至草稿 PR `#36`，但 PR 尚未合并；禁止将该未合并分支
  直接部署到生产。取得独立合并授权并合入 `main` 后，才能按本节关闭态边界执行部署。

## 最近赛事赛果定时审核发布边界

1. 首次部署保持 `RACE_RESULT_REVIEW_ENABLED=false`、
   `RACE_RESULT_REVIEW_ALLOW_NETWORK=false`，并清空 `RACE_RESULT_REVIEW_NOTIFY_EMAILS`。
2. 应用 migration `0062_add_scheduled_race_result_review` 后，核对 worker/beat 的
   `/app/runtime/race_result_review` 持久卷和 route registry 可读。
3. 关闭态 smoke 只验证 task 返回 disabled，要求 network/email/business write 均为 0。
4. Beat 是主调度；`deploy/run-scheduled-race-result-review.sh` 是固定备用入口，两者竞争同一
   数据库 schedule slot。
5. 首次启用、联网 prepare、邮件收件人和 apply 分别授权。apply 必须按默认 dry-run、写前备份、
   `--apply --confirm-apply`、独立 verify 的顺序执行。
6. 止血先关闭总开关；只停网络则关闭 network 开关；收件人为空时 fail closed。审核包与治理
   ledger 默认保留。

## 2026-07-28 `fix-single-migration-owner` 方案边界

当前 main 的标准/低成本 deploy 和两条 rollback 在 `up -d web` 后显式执行
`manage.py migrate --noinput`，而 `deploy/docker/start-web.sh` 也在 web 主进程内执行同一命令。
`up -d` 不等待容器启动脚本完成，因此这是两个可能并发的 migration owner，不是安全的串行重放。

已设计但尚未实现的收敛方式：

1. 唯一 owner 为 Compose `run --rm --no-deps web` 启动的容器内 release-task；
2. release-task 串行执行依赖等待、migrate 和 collectstatic；
3. web 常驻入口只做依赖等待、可选 seed 和 Gunicorn；
4. deploy/rollback 共享 host-local 排他锁、owner token 和 release orchestration；内部 wrapper
   缺当前 token 时零 Compose call，竞争失败者不能释放赢家锁；
5. 顺序固定为停 beat、冻结普通/race-live worker node 与运行态、完整排空并停普通 worker 和
   原本 running 的 race_live_worker、停 web、release、启动并等待 web healthy、再启动
   worker/beat/nginx，race_live_worker 只按原始 running 状态恢复；
6. migration、collectstatic 或 health 任一失败时，web/worker/beat/nginx/race_live_worker
   零启动；
7. 全新站点 greenfield bootstrap 不在本 change 范围；
   `HISTORICAL_RUNNER_INITIAL_INSTALL=true` 只表示已有健康 web/db/redis 上的 historical
   runner 首次纳管。既有环境手工 release 只有在 web/worker/beat/race_live_worker 全部可验证
   为非运行时才能执行，完成后也不启动服务；
8. 通用 rollback 只接受含 `release_contract_v1` 的目标 ref。首次发布回退到 pre-contract
   版本时保留新控制面 checkout，使用部署前冻结旧 image 的兼容桥，且不调用新 one-shot 或旧
   rollback 的显式 migrate；
9. rollback 的 forward migrate 不能当作 schema 回退；不兼容时使用已审核反向 migration
   或校验备份。

上述方案已于 2026-07-29 在隔离分支 `codex/fix-single-migration-owner` 实现（见下节），
尚未 commit/push，未部署、未连接生产。

## 2026-07-29 `fix-single-migration-owner` 实现与操作要点

实现落在 `deploy/`，聚焦合同测试 `stable.test_single_migration_owner`（117 项 = 97 项
re-baseline 基线 + 各轮 findings 新增）。

### 新入口与脚本

- `deploy/docker/run-release-tasks.sh`：唯一 migration/collectstatic 所有者。容器内
  依次 `wait_for_services.py`、`manage.py migrate --noinput`、`manage.py
  collectstatic --noinput`，`set -eu` 保证任一步失败后续零执行；不启动任何常驻进程。
- `deploy/run_release_tasks.sh`：受保护宿主 wrapper（内部入口，操作者不得直接调用）。
  要求 allowlist `COMPOSE_FILE` 与 `DEPLOYMENT_LOCK_TOKEN`，先 verify 部署锁再执行恰好
  一次 `compose run --rm --no-deps web /app/deploy/docker/run-release-tasks.sh`。
- `deploy/deployment_lock.sh acquire|verify|release`：host-local 排他锁（默认
  `/tmp/umanews-deployment.lock`）。`mkdir` 原子抢锁；元数据只含 PID、动作
  （deploy/rollback/manual-release/pre-contract-rollback）、UTC 时间、Compose 文件和
  token 的 SHA-256；锁目录已存在一律 fail closed，绝不自动清理；verify/release 均需
  token hash 匹配，非 owner 不能释放。遗留锁只能人工确认无部署进程后手工删除。
- `deploy/wait_for_compose_service_healthy.sh`：仅支持 web；只有精确 `true healthy`
  返回 0，`false *`/`unhealthy` 立即非零，absent/starting/inspect 错误每 2 秒重试至
  `SERVICE_HEALTH_TIMEOUT_SECONDS`（默认 300）超时非零；日志只含 service、容器 ID
  前 12 位和最后状态。
- `deploy/run_application_release.sh`：deploy 与 post-contract rollback 的共享编排。
  先冻结普通 worker 与 race_live_worker 的 container hostname/运行态（探测失败在
  任何停服前 fail closed），再 停 beat -> 排空（`EXPECTED_CELERY_WORKERS` 传入冻结
  节点集合，缺一即失败）-> 停 worker -> 原本 running 才停 race_live_worker ->
  停 web -> 单次 release task -> 启动 web -> 等待 healthy -> 启动 worker/beat/nginx
  -> 原本 running 才恢复 race_live_worker -> `ps`。
- `deploy/manual_release.sh`：既有环境手工恢复顶层入口。自行生成高熵 token 并
  acquire 锁（成功才安装 release trap；竞争失败者不触碰赢家锁）；web/worker/beat/
  race_live_worker 任一 running、restarting 或状态不可读即 fail closed（零 Compose
  `run`）；全部非运行才调用一次受保护 wrapper；完成后不启动任何服务。
- `deploy/rollback_pre_single_owner.sh <冻结旧 image tag>`：首次发布回退桥。不
  checkout 旧 ref；同一锁内停服/排空后 `docker tag <冻结tag> umanewsbot:prod`，只
  启动一个旧 web（旧 image 入口自行迁移一次），healthy 后恢复下游；
  `SCHEMA_COMPATIBLE_WITH_TARGET=false` 时在 image 切换前非零停止；绝不调用新
  one-shot 或旧 rollback 脚本。
- `deploy/release_contract_v1`：空 marker。通用 rollback 先把目标 ref 解析为不可变
  `TARGET_OID`（必须是单行 40 位小写十六进制，畸形输出在任何检查前非零），再对 marker
  与全部 9 个 v1 helper 逐一 `git cat-file -e "<OID>:<path>"`，任一缺失在任何
  checkout/停服前非零拒绝；checkout 也只使用该 OID。

### 修改的既有入口

- `deploy/docker/start-web.sh`：删除 migrate/collectstatic，保留 wait_for_services、
  可选 seed_admin 和 `exec gunicorn`。
- `deploy/deploy.sh` / `deploy/deploy_lowcost.sh`：保留 `.env` 检查、historical
  runner preflight（含 `--initial-install` 分支）、`pull nginx`、`build web`；在任何
  有状态动作前 acquire 锁（action=deploy，高熵 token，acquire 成功才安装 trap）；
  删除全部 `exec web ... migrate/collectstatic` 和直接 `up web`，改调
  `run_application_release.sh`。
- `deploy/rollback.sh` / `deploy/rollback_lowcost.sh`：空 ref usage 非零；acquire 锁
  （action=rollback）；`rev-parse --verify` 失败零停服零 release；解析出的不可变 OID
  必须通过格式校验（单行 40 位小写 hex）；marker 与全部 v1 helper 缺失在任何
  checkout/停服前非零拒绝；OID 校验通过后、`git checkout`（只 checkout 该 OID）前执行
  `historical_runner_preflight.sh`（此时既有 web 仍在运行，前置条件成立，无
  `--initial-install` 分支）；然后 build web、共享编排。
- `deploy/wait_for_celery_drain.sh`：新增可选 `EXPECTED_CELERY_WORKERS`（空格分隔
  container hostname，校验字符集后透传进 `compose exec` argv 的内嵌 python）；
  ping/active/reserved/active_confirm 快照必须完整包含全部 expected node，缺任一即
  非零；未设置时保持原行为。

### release 失败后的受审恢复路径

1. 先按失败矩阵定位并修复根因（依赖、migration、静态卷、镜像、healthcheck），禁止在未修复
   根因时盲目重试。
2. 需要重跑 schema/static 时：确认 web/worker/beat/race_live_worker 全部停止后执行
   `COMPOSE_FILE=<allowlisted> ./deploy/manual_release.sh`（一次性 release task，完成后
   服务保持停止）。
3. 只需恢复已停止的服务时：`COMPOSE_FILE=<allowlisted> ./deploy/resume_stopped_release.sh`
   （受审恢复入口，action=resume-release 共享锁；四服务全部确认停止才启动 web -> 等
   healthy -> worker/beat/nginx -> 按可信冻结意图恢复 race_live_worker；绝不调用 one-shot）。
4. 冻结意图文件 `${DEPLOYMENT_LOCK_DIR}.race-live-state` 为六字段绑定（state/node/
   compose_file/action/head/frozen_at_utc，mode 600）：编排/桥对任何绑定或可信性失败
   在任何 stop 前 fail closed；resume 对不可信文件只告警并跳过 race-live 恢复、核心服务
   照恢复。任何情况下遗留意图文件都只能人工核对后删除，脚本不自动清理不可信文件。

## Lifecycle shadow 纳管准备（实现通过复审，待代码发布）

- 生产纳管禁止使用 `--auto-discover`，也不手工拼 manifest。计划新增只读 prepare 命令，
  对明确 1–20 个 event IDs 生成 strict manifest v2 和 summary。
- 顺序固定为：关闭态部署 -> 生产只读 prepare/dry-run -> 精确 SHA 授权 -> `false/off`
  下 control apply/verify -> 第二次授权 -> `true/shadow` -> 至少 48 小时观察。
- apply 和启用不得在同一步执行。control apply 后，`RaceEvent.status`、transition、赛果、
  新闻和 QQ 必须仍为零变化；shadow 开启后也只允许 proposal/audit。
- v2 apply 自身必须确认严格 `false/off`；执行前另核对 Beat/普通 worker 同为关闭态、
  lifecycle active/reserved/有效 claim 为 0。v1 manifest 永久禁止 apply。
- 首批排除地区时区不符合合同的赛事。当前没有未来 `race_datetime` 样本，只能观察当地
  次日规则；running/T+30 必须在可信时间补齐后另行纳管。
- 紧急停止：设置 lifecycle `false/off`，重建必要 Beat/普通 worker，验证 scanner disabled。
  已排队任务在事务内复查开关并零写退出；保留 control/proposal，不删审计、不反改赛事状态。
- 完整方案见
  `docs/changes/prepare-lifecycle-shadow-enrollment/rollout.md`。本地实现、测试和最新 main
  整合复审已完成；用户仅授权 commit、push、创建 PR 并合并。生产 apply、生命周期启用、
  部署、迁移、联网 proof 和其他生产写入仍未授权；不得提前运行本节生产命令。

### 操作警示

- **forward migrate 不等于数据库回退**：共享 release task 只把目标代码已知 migration
  推到 forward head，绝不撤销较新的 migration；schema 不兼容时必须停在 release 前，
  由人工选择已审核反向 migration 或恢复部署前已校验备份。
- `HISTORICAL_RUNNER_INITIAL_INSTALL=true` **不是**全新站点 greenfield 安装能力，只是
  historical runner 首次纳管预检，前置要求既有健康 web/db/redis；无健康 web 时
  deploy 在任何迁移前 fail closed。
- release task、web 启动或健康等待任一失败时，worker/beat/nginx/race_live_worker
  零启动；按失败矩阵人工恢复，禁止用“临时把 migrate 加回 start-web”作为恢复方式。

## 2026-08-01 Lifecycle shadow 纳管准备关闭态部署实录

- 部署 revision：`6a185eaa35c9ea89211a33fa5a6cde81d76dbee3`；release 目录：
  `/opt/umanews-release-6a185eaa-069tQL/umanewsbot`；最终 image：
  `sha256:8ae8ce4e7ee4a08a1e3208cff06cbf2e89cd83aebe52587dbe117b621326d31b`。
- 数据库恢复点：
  `/opt/umanewsbot/backups/db/pre-lifecycle-shadow-enrollment-6a185eaa-20260731T211429Z.dump`，
  `371214432` bytes、mode `0600`、`pg_restore -l=1295`、SHA-256
  `98d9629615f68d747f54866e75f4b892453e9ccd18be9144e724176f8599dd05`。
- 环境恢复点：
  `/opt/umanewsbot/.env.backup.pre-lifecycle-shadow-enrollment-6a185eaa-20260731T211429Z`；
  旧 image rollback tag：
  `umanewsbot:rollback-pre-lifecycle-shadow-enrollment-6a185eaa-20260731T211429Z`。
- 目标 migration plan 为空。发布通过共享锁和单一 release-task owner；Beat 停止后先等待
  既有 `discover_term_candidates_task` 自然完成，未取消或强停任务。race-live 部署前未运行，
  因而没有恢复；发布后锁和可信意图文件均不存在。
- 三个常驻应用容器均核对 lifecycle `false/off`。关闭态 scanner 为
  `enabled=False / claimed=0 / dispatched=0`，control/transition/active claim 均为 0。
  HTTP healthz、`/races/`、worker ping、migration plan 和近 15 分钟错误计数通过。
- HTTPS 当前仍未启用；本次验收以仓库已完成的 HTTP 路径为准，不把 HTTPS 后续工作混入
  lifecycle 发布。下一步只读 prepare/dry-run、control apply、`true/shadow` 分别授权。

## 2026-08-01 首批近期赛事 `race_datetime` 生产修正实录

- 范围固定为 event ID `430/431/433/434/435/436/740/940`；manifest SHA-256 为
  `ad103cb19d62622a7f09436c047095460d2f5ad60c4aa9927d4dbbdaf8960886`，生产证据目录为
  `/opt/umanewsbot/runtime/operations/race-datetime-20260801T080504Z/`。
- 本次写前核验结果为 lifecycle `false/off`、目标 control/transition 为 0、目标无 manual
  lock、目标四个时间字段与 `updated_at` 精确命中 manifest CAS、既有字段 authority 为 0。
  dry-run 结果为 `events=8 / field_changes=23`；本次任一项漂移都会整批拒绝，实际未发生漂移。
- 写前 custom-format 恢复点：
  `/opt/umanewsbot/backups/db/pre-race-datetime-20260801T080504Z.dump`，`173009409` bytes、
  mode `0600`、TOC `1295`，SHA-256
  `96703a396885bb345f08b08b8b3a708bea65caab3fd7366e38d8aa6993c2f0ce`。
- apply 本次只执行一次，并在单事务内写入 8 场、23 条 field change、23 条 field authority
  和 1 条批次 OperationLog。写后已用同一 manifest 独立 verify，并直接读取数据库计数与逐场
  值；本次未用页面 200 代替数据库 verifier。
- 最终 HTTP 验收覆盖 `/healthz/`、`/races/` 与 8 个详情页，均为 200；每页包含预期举办地
  当地时间。web/worker/beat/nginx 保持运行，近 15 分钟相关 Traceback/IntegrityError 等为 0，
  部署锁不存在。生命周期仍关闭，未部署、迁移、创建 control、推进状态或启动 race-live。
- 本次已生成并校验上述 custom-format 恢复点；manifest 同时保存了每个字段写前/写后值。
  本次未生成或批准临时反向脚本，也未执行整库恢复。

## 2026-08-01 第二批近期赛事 `race_datetime` 生产修正实录

- event 范围为 `84/85/86/432/437/941/942/943`；canonical manifest SHA-256 为
  `4e2e342dcc8b7def3b04bbe7b3e8db36f4f94634119f37d1ee1f7f09919c6922`，证据目录为
  `/opt/umanewsbot/runtime/operations/race-datetime-20260801T133257Z/`。
- 生产归档工作树缺少仓库版 `deploy/deployment_lock.sh`。本次从已合并 `origin/main` 取得同一
  受审脚本，三端 SHA-256 均为
  `e9c0aa075bdee2642b96b91aae710562281d4807e4d59f0f76677a792d4ecb45`；脚本只临时放在
  `/tmp`，以 `manual-release` action 获取共享锁，完成后已删除，未修改生产仓库。
- 首次命令把容器目录误写为 `/app`，dry-run 在 Django 启动前失败；因 `tee` 管道未传播左侧
  退出码，命令继续进入只读 pg_dump。该精确进程树被终止后，数据库核对为 field authority
  `0`、OperationLog `0`，锁已释放；空 dry-run 日志与 `attempt-1-failure.txt` 保留为证据。
- pg_dump 在终止前已完整结束，写前取证快照
  `/opt/umanewsbot/backups/db/pre-race-datetime-4e2e342d-20260801T133257Z.dump` 经重新核对为
  `373005202` bytes、mode `0600`、TOC `1295`，SHA-256
  `9be6d50ca9433eda897e47e3aca7eefcf1cdaccbafaf2f7be4ccc2482c8adf77`。该快照完成后的
  锁释放到正式重试重新取锁之间，未取得其他生产写入者持续暂停的证据，因此本次未把它批准
  为可直接整库恢复点；manifest 已保存本批各目标字段的 before/after 值。
- 正式重试使用容器真实目录 `/app/server`，不再使用输出管道；dry-run、apply、verify 的末行
  JSON 均断言 manifest SHA、`event_count=8`、`field_change_count=19`。唯一一次单事务 apply
  写入 19 条 field authority、19 条 field change 和 1 条 OperationLog，verify 精确通过。
- 写后 lifecycle 为 `false/off`、control/transition 为 0，部署锁不存在。web/worker/beat/nginx
  正常，worker ping 为 1 node online，近 15 分钟相关错误计数为 0；赛事日历、healthz 和 8 个
  HTTP 详情页均为 200，页面逐场包含预期举办地时间。HTTPS TLS 握手仍为既有失败。
## Lifecycle 普通赛事 strict v2 纳管（待代码审核）

- `priority`、`is_featured`、`is_key_race` 只作为 manifest 审计快照，不得再作为 lifecycle
  资格门禁；published、scheduled、支持地区/IANA 时区、美国逐场 allowlist、local_date、
  manual lock、SHA/CAS、20 场上限、false/off apply 与 shadow-only 仍是硬门禁。
- 发布顺序必须保持 R0 关闭态代码发布 -> R1 只读 prepare/dry-run 并停 -> R2 exact-SHA
  false/off apply/verify 并停 -> R3 exact IDs/manifest/revision/window true/shadow。任何一步不得
  复用更早授权跨越下一停点。
- 24–48 小时是用户指定的 enforce 决策窗口，不代表未到期赛事已经跨过 T/T+30；逐场证据必须
  区分“已观察边界”和“尚未生产观察”。enforce 仍是独立 change。
- 若回滚到旧校验代码，先恢复严格 `false/off`；非重点 controls 完成受审暂停或 mode-off
  处置前禁止重新开启 shadow/enforce，且不得删除 proposal/transition 审计。
## 2026-08-02 Compose wrapper 执行位故障与门禁

- R0 标准/lowcost 直接执行图包含根 `deploy.sh/deploy_lowcost.sh`、内部
  `deploy/deploy.sh/deploy_lowcost.sh`、`deploy/docker/compose-wrapper.sh` 和
  `deploy/wait_for_celery_drain.sh`；六者必须以 Git mode `100755` 发布。`sh -n` 只证明语法
  正确，fake harness 的统一 chmod 也不能替代 raw Git checkout 可执行合同。
- 若部署在首个 preflight 以 `Permission denied` / exit `126` 失败，先确认 trap 已释放共享锁，
  并核对是否尚未进入备份、build、停 beat、drain、release task 或重启。禁止在 release 目录
  临时 chmod 后重试；应修复仓库 mode、增加 fake-Docker 直接执行测试并重新 review/授权。
- 修复后的部署仍从头执行全部 preflight、有效 custom-format 备份、旧镜像冻结、单一 release
  owner、web healthy 门禁和 `false/off` 验收，不得把首次早期失败当作已完成任何步骤。

## 2026-08-02 Lifecycle R0 执行位修复后关闭态部署实录

- 发布 revision：`2dba891fd0b4e5b5671d4a18ed30289e08febc96`；隔离 release 目录：
  `/opt/umanews-release-2dba891f-LDatiL/umanewsbot`；最终镜像：
  `sha256:24fc89cfd801f624c4c2e42bfb5654def6cf50785bda6f8a4d89bb9028c67b9f`。
- 恢复点：
  `/opt/umanewsbot/backups/db/pre-remove-lifecycle-key-race-gate-20260801T170915Z.dump`，
  `373763059` bytes、TOC `1288`、mode `0600`、SHA-256
  `285de333ac811363edf3377336e4f036a76a605d19b96a0d4a000c4c2a7edc7f`；旧镜像 tag 为
  `umanewsbot:rollback-pre-remove-lifecycle-key-race-gate-20260801T170915Z`。
- historical runner preflight 为 `migration_safe`。Beat 停止后 Celery 自然 drain 到
  `active=0 / reserved=0 / active_confirm=0`，再停止 worker/web；唯一 release task 报告无待
  应用 migration。web healthy 后才启动 worker/beat/nginx；race-live 前后均未运行。
- 三个常驻应用容器均为 lifecycle `false/off`，control/transition/active claim 为 0；scanner
  disabled smoke 为 `enabled=False / claimed=0 / dispatched=0`。迁移计划、worker ping、HTTP
  healthz/赛事页和 15 分钟错误日志均通过，发布锁和 race-live 意图文件不存在。
- 本次 R0 没有 control apply、赛事状态推进或 lifecycle 启用。后续 R1 只读 prepare/dry-run、
  R2 false/off apply 与 R3 true/shadow 仍需各自独立授权。
# 2026-08-02 生命周期 R3 队列路由故障恢复检查点

- 症状：scanner 返回 `claimed=2, dispatched=2`，但 proposal 在有界窗口内保持 0。
- 根因：`advance_race_event_lifecycle_task` 显式 route=`default`，生产普通 worker 只监听
  `celery`；Redis 同期观测为 `default=2`、`celery=0`。
- 已执行安全恢复：恢复 `.env` lifecycle `false/off`，重建 web/worker/beat，健康检查 200，
  赛事业务快照不变。旧 `default` 消息不得在本修复发布中 purge 或消费。
- 修复发布必须先关闭态部署。新的 R3 授权后，启用前须以实际 worker `active_queues` 确认
  无人消费 `default`；再启用 true/shadow，用 Beat 停止的手工 scanner smoke，先确认目标
  control generation 增长，再验证 `celery` 消费与 proposal 生成。

# 2026-08-02 生命周期队列路由修复关闭态部署实录

- 发布 `main@d5ae1d7e`，隔离目录
  `/opt/umanews-release-d5ae1d7e-8biMT2TI/umanewsbot`；最终镜像
  `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`。
- custom-format 恢复点
  `/opt/umanewsbot/backups/db/pre-lifecycle-queue-routing-20260801T192601Z.dump` 为
  `374107496` bytes、TOC `1288`、mode `0600`、SHA-256
  `a05e166259e646ffbc464bb900052b8d8f4f2a9d9b599c5396ae0315f2d8125d`；旧镜像和 `.env`
  均已冻结。
- 部署锁、historical preflight、Celery drain、唯一 release task、web healthy 门禁均通过；
  migration plan 为 0，race-live 未启动。
- web/worker/beat 为 `false/off`，advance route 和 worker active queue 均为 `celery`；16 controls、
  0 transitions/proposals/applied/active claims，关闭态 scanner 零 claim/dispatch。
- 两分钟观察后 `celery=0 / default=2 / race_live=7543`，HTTP 三项 200、应用错误 0、Nginx
  502 为 0、锁和 intent 均不存在。旧队列未处理，R3 仍需单独授权。
- 同期存在独立 P0 马身份 one-off prepare；它早于本次 release task、使用旧镜像，本发布未停止
  或删除。完整证据见 change 的 `release_report.md`。
# Race-data-sync 切片 A 关闭态部署前置（尚未授权）

- schema 入口为 additive migration `stable.0068_race_data_sync_pipeline_a_field_audit` 与
  PostgreSQL-only 可逆 guard `stable.0069_race_data_sync_pipeline_a_ledger_guards`；部署前必须先跑
  `showmigrations stable`、`migrate --plan`、备份/恢复点和旧代码兼容检查。当前未授权执行 migration。
- 以下开关必须保持默认关闭：`RACE_DATA_SYNC_ENABLED=false`，providers/regions/fields 均为空。
  本切片没有 Beat schedule；关闭态部署后 request、dispatch、field apply 必须为 0。
- 即使 legacy race-live 被单独打开，TRA racecard 的 schedule 变化也只允许生成
  `slice_c_required` field changes，不得改变 `RaceEvent` 的时间/状态；验收需核对 event/control 前后
  snapshot 与 `RaceEventFieldChange` ledger。
- 其余 provider adapter 当前为 `proof_required`。任何联网 proof、TRA Pro credential、2–4 场地区
  灰度、字段 apply、migration、服务重启都需要新的精确授权，不能随关闭态代码部署一起执行。
- Ireland 不在首发 cohort。直接 reconciliation admission 的 Ireland marker 复用仍是独立审核记录的
  非阻塞 follow-up；该门禁补齐并重新 review 前，Ireland provider/region 不得加入运行时 allowlist。
- 关闭态验收必须从真实 TRA race-live 入口证明 observation 之外的 runner/authority/applied ledger 为
  0；单独打开 provider、region 或 field 仍应零写。raw cleanup smoke 同时验证 held、路径漂移、越界、
  symlink 和并发一次性清理；回滚 0069 前须先确保没有依赖 append-only guard 的写入窗口。

# Lifecycle shadow 观察加固（2026-08-08 已合并，生产未部署）

- `deploy/verify_lifecycle_runtime_coherence.sh` 和 `deploy/switch_lifecycle_mode.sh` 已随 PR #72
  合并，但候选部署被 schema preflight 阻断；生产旧镜像仍不得把它们当作可执行入口。
- coherence 以宿主全量 running containers 为范围，验收 web/worker/Beat 的 project、working
  directory、image ID、release commit 和 lifecycle flags，并拒绝跨 project resident/one-off。
- mode switch 使用 `lifecycle-mode-switch` 共享锁和 Beat-last 顺序；任何失败只允许收敛到双 env
  与 web/worker `false/off`、Beat stopped。无法完成安全收敛时保留锁和证据人工接管。
- wrapper one-off 候选限定 canonical `run --rm --no-deps` grammar，已覆盖 Release B 的重复
  `-e VALUE` 调用。代码合并并完成关闭态部署前，该门禁不构成线上事实。
- 首轮 review 后 mode switch 进一步要求：脚本物理目录必须精确等于 expected release，生产
  canonical env 固定为 `/opt/umanewsbot/.env`；启用前先在共享锁内核验当前三服务为
  `running false/off`，全部 Compose mutation 显式绑定 expected project directory/name。旧 checkout
  或运行态漂移必须在文件、服务 mutation 前失败。
- 安全恢复的 coherence 若因跨 project resident 或 expected project running one-off 的 worker/Beat
  失败，须以宿主 census 逐 CID 严格核验 service/project/one-off/running 后，仅按精确 CID 尽力
  停止违规实例；禁止名称或宽 selector。枚举、inspect、stop 或最终 coherence 任一步失败均保留
  共享锁并人工接管，不得把 expected project 自身重建成功误报为宿主已收敛。
- 通用 `worker`/`beat` 名称不是 Umanews 身份。自动停止前还必须精确核验受控 Compose project、
  物理 release 目录组件边界、冻结 image ID 与 OCI revision；other-app、`umanews-evil` 等前缀
  混淆或任一身份缺失都不得 stop，只能保留锁交人工确认。
- 修复后 shadow 必须重新冻结未来日本+英国 2–4 场自然边界；不得以手工 scanner、已过期
  proposal 或本轮部署前的 observation 替代。enforce 不属于本 change。

# Lifecycle shadow 观察加固部署阻断检查点（2026-08-08）

- 发布目标 `main@c4ad7277`（PR #72）的候选镜像已构建，但 Release B schema preflight 在唯一 release task 前
  fail closed。禁止绕过：生产 recorder 当前为 `0067 + 0070`，缺少 `0068/0069`，main 另含 `0071`。
- 此检查点不允许 fake migration、直接修改 `django_migrations`、跳过 identity 或从候选镜像运行
  `migrate`。应另立生产 migration history 修复 change，完成设计、RED/GREEN、独立 review、恢复演练和
  精确授权。
- 阻断后恢复口径：在共享部署锁内把 `umanewsbot:prod` 指回冻结旧镜像，先 web healthy，再恢复
  worker/Beat/nginx；race-live 不恢复，lifecycle 双开关固定 `false/off`。恢复完成后核对 lock/one-off
  不存在、scanner 零派发、MigrationRecorder 原样、HTTP/worker/log/queue。
- 2026-08-08 实际恢复后 `default=2` 的两条 lifecycle 消息与部署前一致且无人消费；不得 purge、改投或
  启动 default consumer。`race_live=7543` 同样保持不动。完整证据见
  `docs/changes/harden-lifecycle-shadow-observation/release_report.md`；该证据由 PR #73 合并到
  `main@bcea5aa8`，只记录阻断与恢复，不代表生产部署完成。

# Release B PostgreSQL 引擎硬门禁

- 任何 handoff、artifact-only retry、intent ensure/verify/complete 或 release task 必须先得到结构化
  `database_vendor.expected=postgresql`、`actual=postgresql`；`database.vendor` drift 必须立即停止。
- historical initial-install 在 historical runner preflight、build 和停服务前读取既有 web 的
  `connection.vendor`；空值、SQLite、命令失败均停止，禁止以 `DB_ENGINE` 缺失解释为可继续。
- 候选 release task 在 wait-for-services 后、migrate 前再次执行 vendor command。该门禁无生产 bypass；
  `catalog.checked=false` 同样失败。失败后不得重试 migration，也不得把 artifact 校验成功当数据库验收成功。

# Historical initial-install 中断恢复

- initial-install 只允许 exact 0067 起点。候选 build 后、任何 stop 前必须创建 action=`initial-install`
  artifact；停服后的 release task 必须依次 verify artifact -> ensure required marker -> migrate。
- migrate 中断后不要重新运行 ordinary deploy，也不要重跑 initial-install flag；保持服务关闭，使用同一
  commit/image、原 artifact SHA 和 canonical marker 进入 `resume_migration_history_repair.sh`。
- resume 仅接受 0067/0070/0068+0070/0069+0070/0071 exact recorder leaf，并逐次复核当前 catalog、
  DB identity 与 marker origin。到 0071 但 marker 未完成仍属 recovery，必须先原子完成 marker 才能启动服务。

# Completion origin 核验

- completion 先验证 artifact、marker、candidate/image、DB identity 与 provenance，再比较两者的
  recovery origin；不允许操作员通过参数声明或覆盖 origin。
- origin=initial-install 时检查 final 0071 catalog、原始 legacy counts 和 `receipt_count=0`，不得运行
  7-row baseline；origin=migration-history-repair 时仍必须通过 reviewed-static，空 receipt 应失败。
- origin 不一致或任一原始 audit binding 缺失时保留 active/transition marker，不启动服务、不手工改 marker。

# Full migration history 与 pre-0071 legacy object 核验

- production preflight 必须先通过完整 `check_consistent_history`，再解释 leaf/plan；
  `migration.history_consistency` 一律在停服务和 release task/migrate 前停止，禁止补假 recorder row 绕过。
- pre-0071 event 必须是 0024 定义的 partial unique btree index：`stable_raceevent`、
  `(race_series_id, year)`、predicate `race_series_id IS NOT NULL`、`int8_ops/int2_ops`、valid/ready/live，
  且无同名 constraint。target 必须是 `stable_historicalraceeventtarget` table UNIQUE constraint 及
  同名无 predicate backing btree。任何同名替代对象都不算兼容。

# Rollback checkout/build 失败恢复与 control-state resume

- `rollback.sh` / `rollback_lowcost.sh` 在 checkout 前冻结原 HEAD OID、symbolic branch（若有）和
  `umanewsbot:prod` image ID。control-state 验签前的 build 或 target preflight 失败应看到脚本恢复原
  branch 或 detached HEAD、重新绑定原 image，并保持全部既有服务未 stop/up；任一恢复校验失败按失败处置。
- 一旦 `restricted-recovery-control.json` 已创建且通过当前 verifier，临时恢复 trap 即解除。此后不得手工
  checkout、重建、重标 prod tag 或运行普通 deploy；按报错给出的 exact pinned resume，或带原
  commit/image/artifact 的 `resume_migration_history_repair.sh` 进入同一 pinned 路径。
- 通用 resume 发现 control-state 时，首个可执行检查必须是
  `deploy/verify_rollback_control_state.py`。若 state 本身、parent、control dir、任一脚本/override 的
  owner/mode/SHA 或 symlink 状态异常，必须保持零 Git/Docker/Compose/lock 执行并保留现场，禁止 source
  JSON、grep 出路径后尝试绕行。

# 旧镜像 smoke 的 role authentication preflight

- 只读角色由 `psql \getenv smoke_password SMOKE_ROLE_PASSWORD` 接收随机密码，禁止恢复为
  `PASSWORD '$SMOKE_APP_PASSWORD'` 一类 shell-expanded SQL。角色创建前即安装 cleanup trap。
- 权限配置后先在 fixture DB 容器中以 `-h 127.0.0.1`、新角色和新密码建立 TCP 会话，并要求输出精确
  `<role>|on`。看到 `old-image-role-auth-verified` 后才进入 before-audit 与旧镜像 one-shot/daemon。
- 若此探针失败，确认日志中没有 `docker run`，保留脱敏 FATAL、清理临时角色后停止；不要启动旧镜像、
  不要放宽只读角色，也不要把该结果记录为 compatibility failure。

## 2026-08-08 固定旧镜像 gate 完成证据

- 已验镜像：
  `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73`（`linux/amd64`），
  由生产只读 `docker save` 后在本地精确导入；生产没有容器变更或数据库写入。
- 已验状态：PostgreSQL 16 `{0068,0070}` / 脚本 `0068-only`，以及 `{0069,0070}` /
  `0069-complete`。两者均完成 role auth/read-only/write-denied、check、web health、worker ping、beat、
  clean logs 与 before/after audited digest equality，脚本输出 passed。
- 两次 fixture 均已完整清理。前置 setup/auth 失败不得纳入 gate 统计；当前 compatibility 技术门禁
  GREEN，但执行 Release B 仍需重新核对最终 fingerprint、授权、备份、锁/队列/flags 与生产 preflight。

# Recovery provenance 环境隔离

- 启动普通 `deploy.sh`、`deploy_lowcost.sh`、`manual_release.sh`、`rollback*.sh` 或
  `run_historical_initial_install_release.sh` 时，入口必须先 unset
  `RESTRICTED_RECOVERY_PROVENANCE_ARTIFACT_SHA256`。不要从旧 shell、systemd 或手工命令复制该值。
- 只有 `resume_migration_history_repair.sh` 或已验签 control-state 的 required resume 可从原
  artifact 恢复 provenance。新 preflight 必须产生 `handoff_action=forward-resume`；host wrapper
  与容器脚本随后同时验证 action 与 SHA 形态，marker/handoff verifier 再核对真实绑定。
- 普通 action 即使继承合法格式的旧 SHA，也必须在停服/migrate 前清理；ensure 的 provenance 参数为空，
  completion 使用当前 `RELEASE_B_PREFLIGHT_ARTIFACT_SHA256`。若日志显示普通 action 携带非空
  provenance，立即停止，不得继续 migrate 或手工补 marker。

# Release B unique index owner 检查

- preflight 中两个 `0071` partial unique index 必须分别报告 owning schema 为当前 schema，且
  `table_name` 精确为 `stable_raceevent` /
  `stable_historicalraceeventtarget`。名称、columns、predicate 全部相同但表名不同仍是确定性 drift。
- 出现 `0071.uq_race_event_series_edition` 或
  `0071.uq_hist_target_active_series_year` 时，先核对 `pg_index.indrelid` 对应 relation；禁止通过
  在其他表创建同名索引、改 search_path 或手工补 recorder 继续发布。
- 修复或恢复测试对象后必须重新收集完整 catalog，合法两个 owner 均通过后才可继续其他发布门禁。
# 2026-08-09 2025 五地区 participant completion batch 运行手册

1. 本轮地区只允许 `japan,hong_kong,united_kingdom,france,united_states`；澳洲、德国和中东不得出现在
   batch index、network regions 或 production release manifest。
2. 生产只读 census 使用 `p0_horse_profiles --extract-candidates --year 2025 --actual-starts-only`，并将
   candidates、observations、summary、sample review 和 manifest 五文件下载到独立 artifact 目录后逐一
   验证生产 manifest 的大小和 SHA。本轮 candidates SHA 为 `59c0a4a9…0783`。
3. 用 `runtime/research/build_p0_participant_completion_batches.py` 生成单地区批次；index 必须守恒
   `7731 candidates = 156 batches + 0 exclusions`，最终 summary SHA 为 `80331699…f287`、全局 batch plan
   SHA 为 `79b479a1…a5b3`，并绑定生产 census
   manifest SHA `41b30c7a…3828`。任一 source、source manifest、CSV、region count、rank 或 actual-start
   漂移都必须在联网前拒绝。
4. 每次 network prepare 只对一个精确 review manifest SHA 以 one-shot 环境开启
   `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true` 与匹配的
   `HORSE_PROFILE_COMPLETION_REVIEW_MANIFEST_SHA256`；不得修改全局 `.env`，不得并行运行两个生产资料
   prepare。临时网络失败保留 cache 后按同一 manifest 续跑；确定性 identity/adapter 错误进入 blocker。
   prepare 前必须用 `runtime/research/p0_participant_execution_ledger.py --action claim` 绑定同一
   `batch_index.json`、下一 ordinal 与 review manifest SHA；随后必须严格登记 `prepared` completion、
   `released` mapping/release/G3 evidence、`applied` receipt 和 `verified` 写后零剩余 evidence。只有
   `verified` 才清除 active 并开放下一 ordinal；相同 active 身份允许精确续跑，跳批、重复已完成批次、
   不同 manifest 抢占和预生成 stale mapping 均拒绝。全部结束必须 `--action verify` 证明 156 批无遗漏。
   `planned_remaining` 必须精确包含 profile create/update、race record create/update、module audit 五键，
   值均为非布尔整数 `0`；missing/extra/空值/布尔/字符串一律拒绝。该合同已通过独立只读复审。
5. prepare 只生成资料、二代血统、完整生涯、由履历重算主胜鞍和审核 workbook，不写数据库。只有完整
   对象才能进入 module review、mapping snapshot 和 v2 production release candidate。
6. 同一匹马的弱 occurrence 可能跨批次重复；必须按 `prepare -> review -> prepare-release -> G3 apply ->
   verifier` 顺序逐批收敛，下一批 production mapping 在上一批 verifier 后重新生成。禁止预先批准多个
   stale `create_new` manifest 并行写入。
7. 正式 apply 继续要求 fresh 写前备份、零 writer/lock、精确 release candidate SHA、用户 G3、完整
   verifier 和默认关闭的全局高风险开关；本代码发布本身不包含 profile 网络或生产数据写入。

## participant 全阻断 attempt 的精确 retry

当 active ledger 已为 `prepared`，且独立审查确认该 completion 为同批全部阻断、零数据库写入，修复对应
确定性 blocker 后才允许执行：

```bash
python3 runtime/research/p0_participant_execution_ledger.py \
  --action retry \
  --index <frozen-batch-index.json> \
  --ledger <execution-ledger.json> \
  --batch <exact-batch-path> \
  --review-manifest-sha256 <exact-review-sha256> \
  --completion-manifest <current-all-blocked-completion-manifest.json> \
  --retry-reason deterministic_blocker_repaired
```

命令必须验证原 completion SHA 与 ledger 当前值一致、`database_writes=0`、`complete=0`、
`blocked=processed=expected row_count`；成功后旧 SHA 保留在 `prepare_attempts`，phase 回到 `claimed`。
不得删除 ledger、另建平行 ledger、覆盖旧 artifact，或对已 released/applied 批次使用 retry。续跑仍使用
同一 batch/review SHA、原 cache、空的新 output 目录、单一 one-shot 和数据库 read-only；新 completion
通过独立审查前不得进入 release/G3。

## 2026-08-10 batch-0001 精确 retry 实际证据

- 发布 revision：`0149eab88bb74521602e1fe73beb240bc7ddd919`；生产镜像：
  `sha256:71d56e74be554a329dfb147493fe8850220833fbd7ea3c85d713cbc8f8d1eb6a`。
- 写前备份：`pre-p0-identity-fix-0149eab8-20260809T2010Z.dump`，SHA-256
  `1fc928afd129e7631be8ba06a763f2a3c48e55aa46882dcb97173ad1bbd6525c`；`pg_restore -l` 通过。
- r2 必须复用 r1 cache，但输出使用独立 `network-prepare-r2/output`；one-shot 同时设置
  `PGOPTIONS=-c default_transaction_read_only=on`，且只有该容器临时设置
  `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true`。常驻服务开关不得改变。
- r2 completion SHA：`2cf2c634ec3a63ebf36e456ba8ddced814fdcd6897cec737853ee0b6decc04b8`；
  DB before/after evidence SHA 均为
  `18e0830076d7602c704b87dcf4be71ea800071ab81d736c8fe733740e67443c0`。
- 结果为 34 complete、16 fail-closed。14 个 HTTP 403、1 个歧义、1 个姓名不一致不得自动重试或进入
  mapping；34 项经人工模块审核前也不得生成 G3 写入授权。账本必须保持 ordinal 1 `prepared`，直到新的
  mapping/release/G3 明确授权链建立。

## batch-0001 r2 跨来源同赛失败后的恢复规则

1. candidate `fc7962c3…e16e` / artifact `9d2a1e32…9c16` 已发生确定性 strict-complete 失败，即使事务已
   完整回滚，也不得原样重试或沿用其 release approval/G3。
2. 发布修复前先确认本地定向、核心、相邻 completion 和 PostgreSQL 跨来源幂等测试通过；生产部署必须
   绑定精确 merge SHA，保持 horse/history/race-live/race-data 网络、调度、enforce 和 auto-publish 全关。
3. 部署 verifier 必须重查 revision/image/workdir、migration no-op/leaf 0072、服务健康、Redis/Celery、
   writer/lock/one-off 为零、内外 HTTP 和错误日志。部署本身不得执行 P0 apply 或 `full_network`。
4. 只能从部署后的新鲜只读生产快照重新生成 mapping、candidate、artifact、release manifest 和 expected
   actions；dry-run 必须逐马通过 merged started count 守恒。旧哈希不得复制到新 release。
5. 新 artifact 经独立审查后，重新提交精确 G3，范围仍须列明 profile/race record/P0 source/module audit/
   首次发布目标及冻结 blocker。fresh 写前备份、maintenance/drain、manifest-bound apply 和完整 verifier
   必须绑定同一新 release；只有 verifier 通过才推进 ledger，`full_network` 仍需按授权范围另行判断。

## Lifecycle enforce canary 受审入口（event 186/187）

代码部署本身不得自动执行以下动作。精确 G3 获批后，先用 prepare 命令只读生成两场 artifact 并核对
raw SHA、apply/runtime 期限、revision 与 DB 快照；再确保全局已通过 mode switch 收敛到 false/off。

关闭态 promotion 只能使用共享锁 wrapper：

```bash
COMPOSE_FILE=docker-compose.prod.lowcost.yml \
EXPECTED_COMPOSE_PROJECT=umanews \
EXPECTED_RELEASE_DIR=<exact-release-dir> \
EXPECTED_IMAGE_ID=<exact-image-id> \
EXPECTED_RELEASE_COMMIT=<40-hex> \
EXPECTED_CANARY_EVENT_IDS=186,187 \
MANIFEST_FILE=<host-manifest.json> \
MANIFEST_SHA256=<raw-sha256> \
DEPLOYMENT_LOCK_TOKEN=<high-entropy-token> \
./deploy/promote_lifecycle_enforce_canary.sh
```

wrapper 在锁内验证宿主 web/worker/Beat 均 false/off，将 no-follow、regular、≤1 MiB 且 SHA 匹配的
冻结字节经 stdin 传给 resident web；容器 command 还会在任何 DB 写入前把 manifest IDs 与 wrapper
传入的精确 `186,187` 再比较，并在写后再次验证关闭态。首次部署旧 resident 若尚无两项 canary env
键，false/off coherence 将“缺失”安全等价为空；重复或非空仍拒绝，后续 mode switch 会补齐空键。
随后 `switch_lifecycle_mode.sh` 的
`true/enforce` 路径必须使用同一 manifest/SHA/IDs/revision；它按 web→healthy→inactive verifier→
worker→runtime coherence→activate→active verifier→Beat 执行，不手工发 scanner，也不启动 race-live。

任何异常立即使用 `TARGET_LIFECYCLE_ENABLED=false`、`TARGET_LIFECYCLE_MODE=off` 的同一 mode switch
止写；off 路径不读取 manifest，并清空两份 env 的 canary SHA/IDs。不得直接调用 Django promotion/
activation command 绕过宿主 shared lock，也不得手工把其他 control 改成 enforce。

短暂切回 off 后如需在原 runtime window 内重新启用，同一 manifest 只允许 lifecycle 自身已产生的单向
状态/刷新字段进展；schedule、generation、enrollment、可见性、人工锁/暂停和 cohort 仍严格冻结，且每次
activation 必须产生新的 ID。范围外 enforce control 在 scanner claim 查询层即排除，不允许留下 TTL claim。

### 2026-08-10 双赛事 canary 首次生产执行证据

- production revision=`a7e3783ff7d188481cecd421cd2595f43e9a706b`，image=
  `sha256:afa0379f04d1ca8d0115f4ef724fdc9d08a4e34157682c2f657a6fd59f0f441f`，manifest raw
  SHA=`eacffda63284e25b59c3efa5815d138a562c10e86eec7fe5ed1ed41219d303fc`。
- 写前备份 SHA=`9265fd9e6619cee3d036f5db2da5eaecdede532694f5453338584c504a53a078`；promotion、
  active verifier、runtime coherence、scanner smoke、Celery/HTTP/日志验收均通过。
- 当前信任根精确为 event `186,187`，activation ID=`fb222bb1…010e`；race-live 保持关闭。逐时间点
  观察与完整路径见 `docs/changes/lifecycle-enforce-canary/release_report.md`。

## 2026-08-28 赛事数据全生命周期发布步骤（等待最终生产确认）

本节只描述发布顺序，不构成部署授权。必须先取得 PR 合并后的精确 revision/image 和用户最终确认。

1. 只读确认 production revision、三服务镜像、数据库版本、现有 lifecycle/race-live 控制面、queue、
   policy/registry 文件和全部 `RACE_DATA_SYNC_*` 环境变量；任何 unknown 均停止。
2. 完成 custom-format PostgreSQL 备份，记录 SHA-256，并以 `pg_restore --list` 验证可读。
3. 先以所有新增开关 `false`、全部容量 `0` 发布 web/worker/Beat，运行 migration
   `0075_race_data_source_priority_and_reported_position`；验证三服务 revision/settings 完全一致。
4. 运行 `manage.py audit_race_data_sync`，必须为 `would_write=false`，并核对 standing policy SHA
   `60fe9230ca0e97d69a8406118b5d346649239f3f0699efe9a1d0c63972e44ba4`、TRA registry SHA
   `24981f62e30e83e58fc82d4247560af35e4041b05857c287bd64430d0f2e2ecc`、`route_drift=[]`。
5. 先配置精确 provider/region/data-kind allowlist、host/request/event/enrollment/checkpoint/revision 容量，
   保持 network/apply/public/lifecycle/future discovery 关闭，再次审计。
6. 灰度顺序：scheduler + future discovery census -> network + time/racecard apply -> lifecycle apply ->
   result apply -> result public/correction apply。每一步分别检查 run terminal state、claim completion、
   provider 请求数、not-found/fallback reason、revision/projection 数、公开页和错误率。
7. 一级止损关闭总开关、future discovery、lifecycle 和全部 apply/public 开关；保留 revision/transition，
   不批量反向状态、不降级已确认结果。数据库 reverse migration 仅在单独授权、备份和审计保留确认后执行。

部署验收命令、dry-run 证据和已知官网 transport 边界见
`docs/changes/automate-race-event-lifecycle/race_data_lifecycle_implementation_20260828.md`。
