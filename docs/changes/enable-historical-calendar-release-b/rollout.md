# 历史赛历 Release B Rollout

## 1. 工作区与基线

- worktree：`/Users/mentianlu/.codex/worktrees/release-b-historical-calendar/umanews`
- branch：`codex/release-b-historical-calendar`
- 初始基线：`origin/main@1cdd066b80861520f60515d3912c0f0a8283b0eb`
- 当前集成基线：`origin/main@832cc07465a73f2e59947e00e65482b64d39d027`
- Release A 证据 worktree 保持独立，未提交的 evidence-only 文档不复制进本分支。

2026-08-02，未提交候选已 fast-forward 集成上述当前基线。主线占用 `0068`–`0070`，因此
Release B 唯一迁移顺延为依赖 `0070` 的 `0071_historical_calendar_release_b`；部署 preflight、
rollback、测试与本文档均已同步。集成后 SQLite `0070→0071→0070→0071`、专项 `29/29`、
相邻完整性/部署组合 `170/170` 通过；真实 PostgreSQL 与完整 stable 本轮未重跑。旧 reviewer
fingerprint 因主线集成失效，必须对当前完整 diff 重新只读审核。

同日 reviewer session `019fc318-431e-7771-aa79-bf01a9fdb992` 的三个 P1 已限定修复：候选 graph
不认识的生产 `stable.*` applied migration 不再从 leaf 计算中静默丢弃；post-state verifier 对
overlay/ORM `superseded_at` 使用同一 UTC 微秒表示；apply 在写最终状态前以完整 manifest SHA
绑定临时 event/path identity，并先将 scope 内 event 从 series/edition 唯一键解除。三项直接 RED
分别为错误 `ok=true`、`release_b_post_apply_verification_failed` 和 SQLite/PostgreSQL 即时 unique
冲突；修复后直接 SQLite/部署 `6/6`、Release B 专项 `33/33`、真实 PostgreSQL三项 `3/3`，
Release B + Release A 完整性 + 部署合同最终组合 `176/176`。

## 2. 已验证生产基线

- Release A image：
  `sha256:cd57a7a8a2bba6c7efc7bd99b95b350b57af72db4f98f673a61a97399d047624`
- migration：`stable.0067_historical_calendar_release_a` 已应用，pending plan 为零。
- `9867 events / 9867 canonical paths / 81 mismatch / 0 receipt / 0 active gate`。
- flags：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、
  `HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
- v1 census：
  `/opt/umanewsbot/runtime/historical_race_calendar_repair/census-20260801T005900Z`；manifest SHA
  `f45b888b78bf38f65c6ed7fdec8b22a79858ebb09fc60af349b1086b53705b46`，action scope SHA
  `5c142a9221f2ee775a6ce01e0866bb6cf963f5cd439f871a2318336d1598d461`。

## 3. 只读探索结论

- 81 mismatch 分布为香港 80、英国 1，共 14 个 series。
- 12 个香港 series 存在相同 series/local_date 的双 event 边界。
- v1 candidate 中 67 个 candidate 自身也是 mismatch，证明多数为连续链而非独立 duplicate。
- mismatch event 的非零依赖为：runner `823`、result `803`、data candidate `162`、HorseP0Source
  `176`、HorseIdentityConflict `782`；不能批量删除或无 ledger 重挂。
- 至少一个香港 series 同一自然年有两场不同日期赛事；英国 event `19602` 为
  `edition_year=2015 / local_date=2016-01-09` 候选。

上述仅为设计输入，没有修改生产数据库。

## 4. 阶段

### B0：设计与审核

- 建立 spec/design/test/tasks/rollout。
- 方案 reviewer APPROVED 后记录评审结论；后续动作按根 `AGENTS.md` 执行。

### B1：测试先行与本地实现

- 已取得 migration、series planner、artifact、apply/rollback、preflight 与性能 RED，并实现
  `0071`、v2 series action 和 exact rollback；生产保持零写入。
- 修订前 SQLite 相邻回归 `75/75`、真实 PostgreSQL组合 `24/24`；首轮实现 review 修订后专项
  SQLite `45/45`、部署编排 `117/117`、真实 PostgreSQL组合 `28/28`。
- 50k event + 50k target、500 mismatch/100 series prepare 首轮暴露 event×relation N+1，
  `137.67s` 后中止；改为 scope 级按 relation 批量枚举后为 `13.40s`。绑定 preflight 后的
  forward/reverse DDL 为 `0.086s/0.076s`。
- 两份 Compose、Django check、migration drift、compile/diff check 已通过；完整 stable 为
  `4043 / 26F / 133E / 77S`，包含范围外/环境问题，未表述为全绿。临时 PostgreSQL 容器与性能
  artifact 已删除。

### B2：代码审核与交付

- 首轮实现 reviewer session `019fb9a4-86fa-7ca1-b4cc-e5c558258dbc` 为原生 read-only，提出
  `4 P1 + 2 P2`；实际 applied migration leaf、重复等价性、target 审计与字段范围、published
  canonical path、artifact no-replace 已全部修订并补测试。待修订后最终只读复审。
- 第二轮 reviewer session `019fb9b1-f74c-78b0-92c5-6bc7532291be` 提出 `3 P1 + 2 P2`；rollback
  image label、active inventory lookup、supersession manifest 自绑定、canonical link 精确集合与
  多 duplicate star topology 已修复。修订后为 SQLite `47/47`、inventory + deploy `159/159`、
  PostgreSQL `30/30`，待第三次最终只读复审。
- 第三轮 reviewer session `019fb9bc-b0c8-7c03-afce-f0359f710765` 提出 `2 P1 + 1 P2`；通用
  rollback 已拒绝 pre-0071 target，imported target 强制 event，series identity collision 改用
  edition year。相关组合 `168/168`（另 1 skip），待最终复审清零。
- 第四轮 reviewer session `019fb9c9-1bd5-7b30-b1a8-fce75de79fc7` 提出 `1 P1 + 2 P2`；B→B
  rollback 已改用目标 image forward preflight，生成的 review template 与 parser 同构，模型拒绝
  supersede 已有 dependents 的 target。真实 PostgreSQL Release B `26/26`；SQLite/deploy 组合
  唯一 error 为测试 image 缺少 `git`，当前待最终复审。
- 后续 reviewer session `019fb9d8-1ee0-7db3-b28f-7a0651a5cef2` 提出 `2 P1`；duplicate identity
  已加入 `source_refs` SHA，equivalent duplicate 必须是 draft、解除 series 且使用确定性 tombstone
  slug。直接回归 `14/14`，待复审清零。
- 最新 reviewer session `019fc318-431e-7771-aa79-bf01a9fdb992` 提出 `3 P1`；未知 applied
  migration、supersession 时间表示和 series/edition 中间唯一冲突均已按上述范围修复。当前 diff
  仍须回到同一 reviewer session 限定复审，旧 fingerprint 不可发布。
- 用户在最新成功 review 后单独授权 commit/push/PR/部署。

### B3：Release B 关闭态部署

- 写前备份、冻结 Release A image；构建候选 Release B image 后保持旧服务原态，由绑定候选
  commit/image、当前 `0070` leaf 和目标 DB identity 的 candidate one-shot 在停服务/DDL 前运行
  forward schema preflight，并保存 count/rows SHA，随后才可进入 release orchestration。
- 验收 schema/code；不得运行 v2 census、approval 或 apply。

### B4：后续数据阶段

- v2 census、人工 overlay、生产 apply/verifier 和 Release C 分别授权。

## 5. 发布检查

- Release B image 只有 `0071`，没有 Release C migration。
- migration 前只读 preflight 来自候选 image 的受控 one-shot，并在应用停服前证明 non-null
  `(series, edition_year)` 和 active target 新约束兼容；异常或未知状态不调用
  `run_application_release.sh`，旧服务状态不变。
- Release B 的前置条件是 v1 census/artifact 已冻结且 schema preflight 通过；81 个 natural-year
  mismatch 无需在部署 B 前清零，因为 B 不执行数据修复。
- 无 historical runner、repair apply、相关 import/reconciliation/P0/race-live writer 占用 scope。
- 保存数据库备份、当前 image、migration leaf/plan、容器与 flags。
- 两份 Compose、Django check、真实 PostgreSQL migration 和 review fingerprint 通过。
- deploy/rollback 均必须提供已核对的 `EXPECTED_PRODUCTION_DB_IDENTITY_SHA256`；缺失时在停服务前
  fail closed。

## 6. 回滚

| 检查点 | 回滚 |
|---|---|
| B0/B1 本地 | 丢弃本 worktree diff |
| B3 migration 前失败 | 保持 Release A，不触碰数据库 |
| B3 `0071` 已应用 | 通用 rollback 仅允许仍包含 `0071` 的目标；回到 pre-0071 必须另行审批停服、reverse preflight、反向 migration 与旧 image 恢复，不能由通用脚本猜测执行 |
| B4 data apply 后 | 禁止直接反向 `0071`；先 exact ledger rollback/verifier 或恢复已验证备份 |

## 7. 非授权声明

创建与审核本 change 不授权 commit、push、PR、部署、生产 v2 census、maintenance、数据 apply、
历史联网、马号补抓或 Release C。

## 8. 方案审核

- 独立 reviewer session：`019fb93f-3e25-7e71-ac5a-333b1695a8c8`。
- 首次启动头为 `sandbox: read-only`，但采样前持续收到外部 503，WebSocket 降级 HTTPS 后仍在
  有界重试结束时失败，没有生成 findings 或 verdict。
- 同 session 的 CLI resume 不支持显式 sandbox 参数，恢复启动头显示 `danger-full-access`；主线程
  立即发送中断，reviewer 未读取或修改仓库。
- 替代只读 reviewer session：`019fb946-ae91-7a21-b455-29ce02766fd7`；启动头已验证为
  `sandbox: read-only`。
- 首轮结论为 `REVISE`：4 个 P1 分别涉及 reverse migration 兼容性、canonical link ledger 分类、
  target supersession 强合同和停服前 schema preflight；1 个 P2 要求脱敏的 81→14 守恒 fixture。
- 第一轮限定复审关闭 P1-1/P1-2/P1-3/P2-1，仅 P1-4 要求明确 preflight 的候选 image 执行身份；
  修订为 candidate one-shot 后，同一会话第二轮限定复审关闭 P1-4。
- 最终结论为 `VERDICT: APPROVED`，无开放 finding。该结论及当时的执行状态仅作为历史证据；
  当前人工确认规则以根 `AGENTS.md` 为准。
