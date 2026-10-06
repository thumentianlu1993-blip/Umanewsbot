# C036 第三批局部能力离线集成准备

任务 C036-THIRD-SLICE-INTEGRATION-PREP-001。ROOT 授权从 C033 固定 `6793f9f2461d1382349dcc8075a7e92dea85a8ed` 独立装配 A034/B039 获审局部能力及必要方案文档；本候选仅做来源、映射及静态验证，待原 R 独立审核，再由 ROOT 分配正式收集。没有 C036 业务执行、collector、容器/PG、push、PR、合并或生产动作。门禁统一引用根 AGENTS.md；G1 当前范围已覆盖离线准备，G2/G3 尚无动作。

## 固定来源与真实状态

- A034 final `a19c436f49dababe828b46ecd9a242f17e40a9f4`，差分 base `44f79a62d9071b20382bc4b42dc19775fe7d2f10`。ROOT 绑定原 R `ca118aa960a609922f4b1aee81fdfb3e7c38eacf` APPROVED_LOCAL_SLICE；receipt SHA256 `9ec7343eb76e8b72651cc8200949fc58514e36e004d7977a67871fc9e8ec326f`。来源证据为 5 新入口 GREEN + 23 既有精确回归。仅已有单条赛绩 event 补连，强身份与现有 binding、完整字段投影、同 key 重放及事务回滚；未建立新来源权限、赛果归属、跨年补全或完整 career 能力。
- B039 final `322b07e9a50568ef963304dfe3d4693c77f1cf93`，差分 base C033 `6793f9f2`。ROOT 绑定原 R `fb8baef62d64cfe08bfe70bea143a8ce836a9947` APPROVED_LOCAL_SLICE；receipt SHA256 `08bdf4e83ed31a5f169dbff05842a29bbfdceebf5ef9888bc9d1ec5248d14530`。来源证据为 3 真实 RED→77 GREEN；新增 30 个 checkpoint 方法及既有 25 claim-fence +22 recovery 均纳入。只在原 claim/deadline 内保存完整翻译结果并零 provider 调用恢复，不代表可靠 outbox、跨轮费用准入或保证自动恢复已完成。
- 两份来源 handoff 的“待原 R”字段是原审核前历史状态；不改写来源文档，以 ROOT 单独绑定的原 R verdict 为后续状态依据。
- C035 手动 full 与 C037 PR241 merge gate 属 C033 候选，不能作为本 C036 业务通过证据；本候选不改变其 SHA/tree。A035 不在本范围。

## 装配与责任边界

独立树 `/Users/mentianlu/.codex/worktrees/c036-third-slice-integration-prep/umanews`，分支 `codex/c036-third-slice-integration-prep`。完整 cherry-pick -x A034 的 6 提交修复链、B039 的 5 提交链，以及 A033 两个方案提交和 B038 一个方案提交，共 14 个来源提交；A032 已在底座，不重复导入其祖先或 ROOT 历史。

来源 A034 5 文件、B039 5 文件无重叠；两份必要方案使来源文件合计12。每个文件均与指定最终 source 的 Git blob/字节一致，完整14 source→assembled commit 映射封存在 runtime static-contracts.json；无冲突、无来源代码技术修复。C 仅负责 catalog/rules 及本整合报告。

映射登记提交 `641a25f1`：

1. 新 domain `horse_career_link_cache`，label `stable.test_horse_career_record_link_from_cache`、django profile。新 ORM service 精确路径和合成 fixture 登记；service high-risk 直接要求 full。依赖 H03 basic/H02 cache/H01 target、horse_publish/page、既有 P0 career writer 和 race_data_sync_admission；fixture 改动沿同域覆盖，不泛化邻近未知路径。
2. 新 `stable.test_translation_result_checkpoint` 登记 news_translation/domain/tests/django profile。原 translation_recovery/tasks 已为高风险 full，保留原控制与全部旧域覆盖。旧 B037 25/B recovery22/M01 和全部 core/full 标签未缩减。
3. old catalog 每个 domain 标签、dependency/test/profile/owner均保留；allowed_skips、dedicated_batch_modules、旧 high-risk、symbols、module_initialization_full 及12受信 controls 保持。未知邻近 service/fixture fail closed。

## 已完成验证与限制

- 34 项 test_test_impact/test_impact_evolution 离线契约检查实际通过，5.988秒；无 Django/数据库/真实第三方访问。
- AST直接声明新增35 canonical IDs（A034五组方法、B039三类共30方法），全部映射 django。这里只证明声明与映射，不证明实际 collector 集合、子例数量或执行通过。
- 12 source blob/bytes、14 -x 来源、12 controls、原 core/full/skip/专属分批/符号/初始化规则、未知邻居、来源文档引用检查通过；workflow contract PASS、git diff --check通过。
- 固定最终整体后生成正式full静态计划与 SHA/digest，保存到专用 runtime；实际 count/batches 仍待原 R 审核后正式 collector，不能用静态35推算或宣称实际6703。
- 原获审局部 GREEN 仅为来源证据；未重跑、未把 C033 的正式结果借作本整合候选 full 结果。

runtime `/Users/mentianlu/.codex/runtime/c036-third-slice-integration-prep-001` 保存 static-contracts.json、34检查原始log、最终计划、固定Git和evidence-index。下一步 ROOT→原 R 审核此完整固定候选；如有 source 冲突或 finding 需改来源实现，先报告 ROOT，在原 R 上下文处理。未获 collector 资源分配前不启动。
