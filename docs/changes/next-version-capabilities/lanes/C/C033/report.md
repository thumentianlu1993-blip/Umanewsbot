# C033：第二批小切片隔离集成准备

2026-10-06，C033-SECOND-SLICE-INTEGRATION-PREP-001。固定基线为 PR240 head `2c72521c55b6cdc24f7650d172b48079cbff969a`，PR240 原树/分支/候选保持。新树 `/Users/mentianlu/.codex/worktrees/c033-second-slice-integration/umanews`，分支 `codex/c033-second-slice-integration-prep`。已完成获准 A032+B037+C032 的精确装配和最小测试登记；最终整体仍待原 R 集成 review 及正式测试。共享主线/生产动作继续按根 AGENTS.md，本任务没有 G2 授权。

## 已批准来源与装配

ROOT 交接的批准状态：A032 head `e775ad2deb9ce94b1c9f2dbc2cb52d2ba32b27a0`、原 R 1676d7e8 批准、25 项隔离 PG 通过；C032 head `bae98e7e8e7d17167f16f4cb165ef444452c635e`、原 R 70fcf693 APPROVED_LOCAL_CODE、五项隔离 PG 通过；随后 B037 head `a8b182bd51ad9d2358f8c0164e2f53f06c2f63bc`、原 R `2e1868bf6bb90abac00530908d909cc22914dd60` B037-R01 CLOSED / APPROVED_LOCAL_SLICE，受测 `ef50b1c74d043fc80877db393814fec6fc052be2` 47 项 PG 通过，原 63 项来源证据保留。最后 B 两文档相对受测 SHA 为 docs-only。C033 核两份 ROOT 指定 B handoff/R receipt 原 hash 精确匹配；不重跑业务或自签审核。

使用 `cherry-pick -x` 仅迁入 base 后确切十六个源提交：

| 来源 | 原提交 | 本树提交 |
| --- | --- | --- |
| A032 RED 准备及已审 A031 计划 | 73758be2 | 104e1e65 |
| A032 最小实现 | f3bcf547 | 70bfe4a3 |
| A032 迁移种子计数/PG Lock 证据测试修正 | 6c36cf4e | b3cf66bd |
| A032 docs-only GREEN 交接 | e775ad2d | fa2c5387 |
| C031 已审 U04 首片计划 | 46d564a0 | e898180b |
| C032 五项 RED 准备 | 0828a238 | 7b8defd5 |
| C032 最小模板实现 | 111941f0 | db076d3b |
| C032 docs-only GREEN 交接 | bae98e7e | 5bd4fad3 |
| B037 五项 RED 准备及 B036 计划 | a4022503 | 0a6a4268 |
| B037 领取/终态/通知最小实现 | bb572df2 | c8bb70e4 |
| B037 边界/PG 并发测试 | 9498edf1 | 26623fea |
| B037 原 63 项验证文档 | 956717ba | d8fc8777 |
| B037-R01 锁等待跨截止 RED | 5b703193 | 8fd753b1 |
| B037-R01 精确 PG 阻塞者观察修正 | 029c050d | 598c2e6b |
| B037-R01 取得锁后重新核实际截止 | ef50b1c7 | b3bd6ec6 |
| B037-R01 docs-only 47 GREEN 交接 | a8b182bd | b840ac73 |

A+C 先装配至 `5bd4fad3b320bfd2bb28a175d7fdf74e15028adf`，B 获批后完整链装配至 `b840ac73db18617711bb3eb1f51fcda18433186b`；没有仅迁入最后 docs-only 漏掉实现/修复。A 六文件+B 八文件+C 五文件共十九 source blob 逐字等于各最终获准树，无路径重叠/冲突；十六 source SHA 无重复，没有 ROOT 历史台账或重复 PR240 来源。装配使用有 PID/线程/SHA/资源域/时间记录的 FD flock，随后自动释放。A034 不属于本批。

## 最小映射登记

登记前固定 assembly 的 selector 实际拒绝新 H03 fixture/service/test 三路径。准备新增 `horse_basic_profile_cache` domain，唯一 label `stable.test_horse_basic_profile_from_cache`，profile django；AST 声明 25 项，与 ROOT 的来源 PG25 集合规模一致，本轮不作 native/正式 collector 声明。

该 domain 依赖既有 horse_cache_reuse、horse_publish、horse_page：涵盖实际引用的 H01/H02/strict cache validator、既有 candidate apply/发布边界和公开读取。合成 hkjc_synthetic.json 是行为输入，精确映射 domain；新 ORM/transaction writer 服务精确加入 high_risk，保持与现有持久化服务相同保守准入。C032 五新方法已由既有 HorseProfilePageMvpTests 所有权覆盖，无新模块或重复登记。

B 接入后 selector 实际拒绝新 `test_translation_claim_fence.py`，随后将其整体 label/profile django 登记到既有 news_translation。AST 25 项；既有 `test_translation_failure_recovery_change` 22 项沿原整模块覆盖，不缩成三个截止测试，不改变正式分母。A25+B25+C5 合计 55 新声明方法，仅 AST 静态计量，不冒正式 collector 实际集合。

只修改本新树必要 catalog/rules 及本 C 报告；登记提交为 3c345ba1。十二执行/装载/验证/工作流控制逐字等于 base；旧 domain/依赖/tests/profiles/owners 覆盖全部保留，docs 白名单、symbol 映射、module_initialization_full、skip 与 dedicated_batch 完全不变。未知邻接 service/fixture/test 仍 fail closed。A/B/C 业务代码未修写，他线树未动。

## 最终静态结果与正式计划

- 十九 source blob / 十六来源提交对齐、55 新方法 AST、JSON、现有 validate_catalog、十二控制相等、旧覆盖/白名单保持、未知邻接拒绝：PASS。
- A+C 阶段原 34 合同通过；B 与其登记后最终 `python3 -m unittest scripts.tests.test_test_impact scripts.tests.test_impact_evolution`：34 tests / 5.918s / OK，完整原 stdout/stderr 封存，仅映射合同，不是业务测试。
- `git diff --check`：PASS。现行 selector mode=full，316 labels，保持原准入；未执行 full，不把 labels 当实际测试数。
- 原证据 `/Users/mentianlu/.codex/runtime/c033-second-slice-integration-prep-001/`：两装配 resource、两 mapping-before、A-C-static-contracts.json、final-static-contracts.json、最终 mapping-contract-tests-final.log、registration-plan.json 及最终 final-plan.json/evidence-index.json。后两文件绑定本报告提交后的精确最终 HEAD/tree/hash，避免文档自引用；完整来源文件和 commit 映射在 final-static-contracts.json。

最终整体固定后先交原 R 集成 review，再由 ROOT 安排正式资源，不推送、不创建 PR。建议下一步仅官方 collect-only：固定最终 SHA/tree/plan，同受信现有镜像 fcf8cdaf，无 build/pull；一个容器 2 CPU / 4 GiB / pids256 / tmpfs3GiB / network none / non-root / readonly / capdrop ALL / NNP，600 秒 collector + 30 秒 cleanup。正式 canonical 数/profile/分片从新 collector 获取，不能把 PR240 或三片历史窄诊断搬作新 tree 的正式收据；取得集合后 ROOT 再决定本机预算或现有 GitHub full CI。没有授权新窗口，C033 不启动 DB/Docker。

H03 仅已验证私有基础资料旁路，不代表真实来源许可、完整全局身份或 H03 整卡；U04 仅搜索空态首片，不代表 H07/R03 全局新鲜度、读取失败和 L05 聚合已完成。QQ 停用文案、后台改造继续延期，原 C027 演示和 PR240 候选保持。正式 collect/full、最终组合独立原 R review 与发布交付均待 ROOT 排程，本轮业务测试/容器/真实读取为零。
