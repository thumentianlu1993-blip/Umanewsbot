# PR245 固定候选 G2 交付完成版

完成状态：2026-10-07，固定 PR245 的 source/package review、正式 full CI、完整报告和候选外受信 verifier 已通过，ROOT 已独立核验分母与资源清理。PR 仍为 OPEN_DRAFT；可交付“只合并”对象，尚无合并或生产发布动作。本文件作为 ROOT 向用户提交的固定只合并交付对象。0081 的精确生产部署/恢复包仍未完成，不能据此称为发布 ready 或生产验收。

## 固定交付对象

| 对象 | 精确值 |
| --- | --- |
| PR | https://github.com/thumentianlu1993-blip/Umanewsbot/pull/245 |
| head | `c6ed21a434d41bb0721987437a4d7f7663eb7be2` |
| base | `90f73d8093df00827a7ec78cc41dc3d3b91730c0` |
| 已受验 PR merge | `d6ec8cf3dd54def3fa08a079d15956b3d77a1265`，parents 精确为上述 base/head |
| tree | `3dd1df7a03a542a5537b96d1b06249c03d74a5e9`，head 与已受验 merge 一致 |
| 新 full | run `37601589319`，attempt `1`，event `pull_request`，workflow `.github/workflows/affected_tests.yml` |
| source review | `428521118c653e9da9d456ac3dfe8a9450de7b4dab3ab85a07f886bf5bc3cd43`，承接功能审 `004c65c86c65474f2803aaa64b9907f8031b979bba2c6d2a23ea0cacf37f75ab` |
| package review | `52101ff4f7386919a1a701bf3e97ba459527f717a7d992a369ee9ebae3d9b02b` |
| A053 package seal | `aa2118c40ed03932a41f590a553ab258e9d1188a76ff8ffca353529f7c22607e` |
| 受信 verifier | 原版 SHA `7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d`；固定新版 SHA `e2503487d773c2a3c1c7cc4020d5c27777b7662e3c561c0688e31da311b22a04`；patch SHA `3a81ec55e6dd2103e1cea73a8c2ec6552d9e615278a55d9f480f4ab32c02185e`；结果 verified，收据 SHA `0b6272afb46df33683ad9c3ff13539669de1c741b58f2966b3d50dc4ddb04b59` |

最终远端合并 commit 尚不存在，不能把 GitHub 的受验 merge ref 称为已经合入 main。ROOT 完成交付时须用实际合并结果验证上述 head 与 tree 的关系；若基线发生变化，以真实状态确定原证据能否继续适用，不隐式替换受验对象。

## 实际业务改进及用户可见范围

### 私有已审单行赛绩

对于私有香港马匹资料，受控调用方可以用已冻结的 packet、HKJC cache、独立单行 review 及原行 SHA，消费一条“日期精确、实际起跑”的赛绩。命令 `horse_career_record_from_review` 要求明确 `--dry-run` 或 `--commit`，以及输入根、review 根、输入 SHA、行 SHA、实际代码 SHA 和 actor ID。它不取新来源，也不自动调用生产入口。

成功 commit 的实际持久化包括：一条正式赛绩、原 APPLIED candidate/消费凭据、operation log，以及既有 profile 派生计数的相应更新，全部同一事务；返回 `published=False`。权限、私有身份、手工锁、TTL、实际源证据和写后 readback 失败均拒绝或整体回滚。ignore 不消费；dry-run 经过实际 writer/审计/readback 后回滚；同一输入重放不重复建记录。后续合法赛事补连后，可以按原记录与 link receipt 重放，保持赛事关联。

公共 writer 的两行修正让 payload 显式提供的 `eligibility_text` 写入赛绩，缺少该 key 时保持原值。这会影响调用该 writer 的既有路径，并非仅影响新增 CLI；完整回归已覆盖当前候选。原始来源属性和赛绩事实的保护保持。

本 PR 没有新增后台按钮、前台页面、HTTP API 或定时任务。当前用户能直接看到的网页变化没有新增实现；业务收益是受控私有资料维护能力及正确保留赛绩条件。独立 review sidecar 不等于已经接入生产审核签名/权限体系，不据此宣称完整 H02/生产马匹补录工作流上线。

### 离线受管只读 step

B 线增加独立持久化读预算与 step：先提交读槽和 reservation，再在自建事务/锁之外读取有限 Article 源片段，最后事务内校验并提交可重放结果。固定逻辑名为 `source_excerpt:1`，读预算上限 2，结果上限 8192 字节。缓存重放要求精确 envelope/参数/版本/epoch/来源绑定；未知执行保留已占槽，不重读、不接管 token，撤权后不披露或提交结果。

“只读”指业务来源材料的有限 SELECT；预算计数、reservation、结果账本本身会写数据库。当前入口依赖私有 offline scope 和封闭 reader，未接 task/provider/API/UI/生产权限体系，也不提供任意 SQL/URL/调用方 source ID。不能把这次交付称为生产工具调用或完整 M01/M02 功能开放。

### 测试交付的技术改进

正式 executor/worker 将 Git archive、文件 mode/blob、tree、原 commit 和实际 Git HEAD 绑定后，再提供已核验的代码 SHA。新增两个业务模块已归入 Django profile。历史 0078/0079 测试夹具的精确后继文件集合加入 0081，恢复原历史摘要；生产发布/recovery/rollback guard、原摘要常量和 allowlist 保持，真实当前完整迁移目录仍被历史合同拒绝。

## 验证证据与分母

| 口径 | 数量/事实 |
| --- | --- |
| 原 PR244 完整基线 | 6777 个唯一 ID，旧映射完整保留 |
| 新业务方法 | A 10 + B 19 = 29，均由实际 Django profile 执行 |
| 新技术方法 | 正式源码绑定 10 + 历史 fixture 3 = 13，Python profile 执行 |
| 当前完整实际分母 | 6777 + 29 + 13 = 6819；48 份 batch report |
| profile | Django 6020 / Python 750 / release-postgres 49 |
| 原业务目标 42 | A 19（10 新 + 9 旧）+ B 23（19 新 + 4 旧）；已包含上述 29，不再次相加 |
| 必须完整覆盖 55 | 原 42 + 新 13，全部已执行，零 skip/failure/error/xfail/unexpected success |
| 完整报告结果 | failure/error report IDs 0；trusted core report validation `passed` |
| 旧 skip/alias | 原 10 runtime skip 的 ID/原因一致，原 9 collection skip 与 321 aliases 一致 |
| ROOT actual collect | 6819，收据 SHA `97805b5ad377fc5b163e0ebd3f09f1894210c96893bc003d20ad476dc6ece81f` |
| 新 CI actual plan | SHA `af99357df1facc25f43e9d60845950f6035f98fbb2425cac19564da100c293ed` |
| 新 evidence ZIP | artifact `11474337782`，SHA `bf995acea83348531b3d03725252eeac47f0398dcbd24a74672aea771c5301f9` |
| 新 test-image artifact | `11474427460`，API digest `c21ec1efffece0c1bea570cdb19ffd5cc9e5392e2ebb6f0bb3c6c817cba0c9e7`；A 未本地下载 |

旧 run `37593926987` attempt1 的失败原件保留：6816 分母、166 个失败报告 ID（含 76 参数化 subtest 项）对应 115 个实际方法。新 run 是新 head 自然触发的执行，未 rerun 旧 attempt。历史源码说明中的“未 push/待执行”等内容是各卡当时快照；本完成版及 A054 收据提供后续实际状态，不改写原封存记录。

## 合并和发布的真实影响

| 影响项 | 只合并此固定 PR | 若后续发布此候选 |
| --- | --- | --- |
| 共享主线 | 纳入精确 head 对应变更；实际合并 commit/tree 由 ROOT 核验 | 需另有精确运行 commit/image，不能以受验 merge ref 当作已发布版本 |
| 迁移 | 仓库增加 `0081_managed_readonly_steps`，合并本身不执行迁移 | 两个 CreateModel，无 RunPython/RunSQL/回填；依赖 `0080_translation_retry_budget`，0080 已在 base 源码，但生产是否已应用本卡未查。生产待迁移链必须现场确定 |
| 配置 | 无 settings、`.env`、Compose 或 feature flag 文件变化 | 无新增配置值/功能开关；必须核现场原有效配置，不能默认旧值正确 |
| 服务 | 不改变生产进程 | 应用镜像需包含新代码；web/worker/beat/相关在运 worker 的版本、排空、停启和恢复范围由既有部署协调器及冻结运行意图确定。测试 impact image 不是生产应用镜像 |
| 生产数据 | 无生产动作 | 执行 0081 会写 schema/migration history；没有自动业务回填。调用 A `--commit` 会创建正式赛绩及审计；调用 B 会写账本。本完成版未包含任何生产业务调用/批量写入/抓取/发送 |
| 自动化/公开行为 | 没有新 UI/API/task/provider 接线 | 不会自动开放只读工具、开启 enforce/race-live/自动发布或对外发送；不改变现有来源权限 |
| 验证 | source/package review、full 与受信 verifier 均已通过；ROOT 完整分母/独立清理已核验 | 仍需精确生产镜像、schema plan/DDL、应用 check/health/worker、现有公开业务面和数据保护验证，现阶段无生产观测 |
| 回滚 | 若需撤回主线变更，保留审计历史，按真实 main 组织后续代码修订；不涉及生产 DB | 新增 0081 与旧精确 schema/摘要合同不兼容，不能直接调用旧 0078/0079 rollback 或默认旧镜像能容忍两张新表。须有受审恢复合同、备份/还原和新写入处理边界；本卡未验证 |

**现有发布限制**：`release_0079_recovery.TARGET_LEAF` 固定为 `stable.0079_multisource_race_enrollment`，历史迁移内容合同按精确 SHA 拒绝漂移。A052 只修测试目录复制，没有增加 0081 的生产 DDL owner/发布/恢复准入。当前不存在由本 PR 提供、可直接执行的 0081 精确发布包；不能把生产 guard 的正确拒绝当作需要绕过的检查。

因此，当前技术证据已闭合，可供 ROOT 提交“只合并”交付对象。若选择合并并发布，ROOT 还需先把针对真实环境的前向 schema 与恢复合同、commit/image、备份、配置指纹、服务意图、验证和回滚做成同一个具体可审核发布包。这里是执行包未完成的技术事实，不新增人工确认点，当前提交只合并选择。

通用授权仅引用仓库根 [AGENTS.md](/Users/mentianlu/.codex/worktrees/a052-historical-migration-fixture-fix/umanews/AGENTS.md) 的 G2/G3；本完成版不复制门禁原文或增加确认点。

## 实际受信核验与资源释放

ROOT 在独立 1800 秒窗口使用本次 CI 的实际 test image 重收集，核验 fixed base/head/merge/tree/run/attempt、source/package/verifier provenance、artifact 和完整 6819 分母。实际退出码为 0，耗时 417.516684 秒，delivery receipt 状态 `verified`，summary `passed`。这次重收集是交付 verifier 的实际行为，不是重跑业务 full 或旧失败 attempt。

ROOT 独立清理记录核验 PID 6482/6484/6491 与 runner PGID 消失、精确 owned 容器消失、docker ps 空、共享 FD 可重新获取（mode0600/dev16777231/ino33552870），127 个包 seal 输入保持。A 本线只读取并拷贝上述证据，没有启动测试、PG、Docker 或锁。

| 实际收据 | SHA256 |
| --- | --- |
| trusted delivery | `0b6272afb46df33683ad9c3ff13539669de1c741b58f2966b3d50dc4ddb04b59` |
| ROOT independent cleanup | `0c76bafb1aafac281e8405b96b77d01af672f702343a899f6f08e95dfef6c371` |
| ROOT denominator audit | `d7d660550e8e62e5d758892bff455bdf0bdc99103a4bcff47c2658b3af6ee9c2` |

完成凭据保存在本 runtime 的 trusted-delivery-receipt.json、ROOT-cleanup-verification.json、ROOT-denominator-audit.json。原 A055 草稿及 7 项封存保持，原 pending 状态只代表当时事实。

当前没有用户 G2 决定、实际合并收据或生产发布收据。发布方案仍需针对真实环境完成上述 0081 前向 schema 与恢复合同及精确运行包；不得将“只合并”交付扩大为生产业务写入或部署。

既有证据：[A054 handoff](/Users/mentianlu/.codex/runtime/a054-pr245-fixed-head-formal-full-001/final-handoff.json)、[报告 audit](/Users/mentianlu/.codex/runtime/a054-pr245-fixed-head-formal-full-001/report-audit-receipt.json)、[A053 包](/Users/mentianlu/.codex/runtime/a053-final-candidate-formal-package-rebind-001/preparation-receipt.json)。
