# TRA 马匹身份 proposal、精确审批与 split/reject 审计

日期：2026-08-30

## 1. 结论

`racing-api-horse-p0-candidate.v1` 到既有 identity apply 之间的人工审核缺口已在本地关闭：

1. 可从一批不可变 candidate 生成 `PROPOSED_NOT_APPROVED` 审核目录；生成过程只读数据库、零网络、零写库。
2. 审核人编辑逐行 decision template 后，publisher 会重新读取原 candidate、重算 resolver 结果，并复核
   ExternalHorse、HorseProfile、现有 identity、TRA source-display alias 的快照；任一文件、行或数据库状态漂移
   都会停止。
3. 只有绑定 exact proposal manifest、review rows 和 reviewer decisions SHA 的 approval 才能被既有
   `apply_reviewed_identity_artifact` 消费。
4. `reject_binding` 会保留 provider row，将错误 TRA identity 标为 `rejected`，并解除该 TRA 英文 alias 与
   canonical HorseProfile 的绑定；receipt 保存 exact before/after，可在 after-state 未漂移时恢复。

这只是离线代码与审核合同完成，不表示已有真实 TRA candidate、身份已落表或生产 apply 已获批准。

## 2. Proposal 合同

输入必须逐个提供 candidate 普通文件路径和 exact SHA-256。每个 candidate 必须：

- schema 为 `racing-api-horse-p0-candidate.v1`、`source_name=the_racing_api`、`database_writes=0`；
- provider ID 为合法 `hrs_*`，并唯一解析到当前 ExternalHorse；
- 内含的 `identity_decision` 与当前只读 resolver 重算结果逐字段一致；
- 至少有一条同 `hrs_*` 的 TRA `/pro` 或 `/standard` HTTPS 响应证据；
- 有且只有一条与当前 provider 展示名一致的 staged `source_display` alias。

生成目录以 `PREPARED` 最后发布，包含：

- `review-rows.jsonl`：逐马 candidate path/SHA、source manifest、ExternalHorse 快照、resolver disposition、
  candidate profile 快照、当前 identity/alias 状态、profile response SHA 和建议 action；
- `decision-template.jsonl`：审核人可编辑 action、HorseProfile ID、说明、override 理由和二级证据；
- `proposal-manifest.json`：绑定 rows/template/candidate 集合与 SHA；
- `PREPARED`：绑定 exact manifest/rows SHA。

同一 provider ID 或同一 candidate 被重复加入批次时失败关闭。名称不作为唯一身份键。

## 3. Approval 合同

Publisher 同时要求：

- exact proposal manifest SHA；
- exact review rows SHA；
- reviewer decisions 普通文件及 exact SHA；
- 已存在的 reviewer username、带时区 approval timestamp、非空 decision source reference；
- proposal 与 decisions 一一对应，ordinal、provider ID、proposal row SHA 不可改写。

发布前会从 candidate 路径重新读取 exact bytes，并重算数据库快照。即使 candidate 未变，只要候选
HorseProfile、ExternalHorse、identity 或 alias 在 proposal 后发生变化，也不能沿用旧审批。

成功目录以 `COMPLETE` 最后发布，包含 `approved-decisions.jsonl`、`identity-review.json`、
`approval-manifest.json` 和 `COMPLETE`。Publisher 不创建 identity、alias、HorseProfile 或 receipt，固定为
`database_writes=0`。

## 4. 四种审核 action

### `bind_existing`

- 必须选择一个现存 HorseProfile；
- 默认只能选择 resolver 已展示的 candidate profile；选择范围外 profile 时必须提供至少 20 字符的明确理由
  和至少一条 HTTPS + payload SHA 的二级证据；
- provider identity 已为 `rejected` 时，必须显式 `rebind_rejected=true`，并再次满足理由和二级证据门禁；
- apply 同事务把唯一 TRA identity 标为 `verified`，并把 staged TRA source-display alias 绑定到同一 profile。

### `reject_binding`

- 只能拒绝 proposal 时确实存在、且正绑定到所选 profile 的 `observed/verified` identity；
- apply 将 identity 标为 `rejected`，保留 evidence/payload/reviewer/time，并把 TRA alias 的
  `horse_profile_id` 置空；
- 不删除 ExternalHorse、HorseNameVariant 或 provider ID，也不回滚已经混入 HorseProfile 的其他字段；后者
  必须使用单独资料修复包。

### `create_draft`

- 只允许 resolver disposition 为 `create_new_candidate`；
- identity review 服务自身不创建 HorseProfile，只记录审核决定；draft 创建仍须走既有 P0 mapping/release
  链，避免出现第二套 canonical 写入实现。

### `leave_unresolved`

- 不选择 profile，不更改 identity 或 alias；
- 若整批 artifact 进入 apply，只产生批次审计 receipt，不把 unresolved 马误报为已绑定。

## 5. Receipt、回放与撤销

正式 apply 仍要求 artifact SHA、reviewer 一致，并受命令层
`--allow-write + RACING_API_IDENTITY_WRITE_ENABLED=true` 双门控制。每个实际变更行保存 identity 与 alias 的
exact before/after；只读 action 也记录 unchanged state。apply/reverse 在单批事务内锁定 TRA
`ExternalDataImportLock`，active staging run 存在时拒绝；publisher 批准后 identity 或 alias 的状态漂移也会
在实际写入前拒绝。

- replay：同 artifact 已应用且 after-state 未漂移时返回零写；
- verify：逐行读取当前 identity/alias，对比 receipt after-state；
- reverse：先全批验证 after-state，再仅恢复实际变更行；后续合法修改会阻断撤销；
- `reject_binding` 的 reverse 可恢复原 verified identity、验证时间、reviewer、notes 和 alias 绑定。

## 6. 日港跨语言去重作用

该链不会因 TRA 英文名与 JRA/JBIS 日文名或 HKJC 中文名不同而创建第二匹马。resolver 先使用 verified 本地
ID 或 DOB + sex + sire + dam 四字段生成待审 crosswalk candidate；proposal 把本地 profile 快照和 TRA
`hrs_*`/英文 alias 一并冻结。只有显式批准并 apply identity 后，重生成的资料 candidate 才会变成
`bind_verified_external_id` 并进入后续 module review。

同名、译名、罗马字相似度都不能绕过 provider ID、官方本地 key、四字段冲突和多候选阻断。

## 7. 命令顺序

以下仅为命令合同，路径和 SHA 必须来自当次冻结 artifact；生产执行还需要独立写窗口和授权。

```bash
python manage.py manage_racing_api_horse_identity_review \
  --prepare-proposal \
  --candidate /private/path/horse-a-candidate.json \
  --candidate-sha256 <candidate-sha256> \
  --output-dir /private/path/identity-proposal

python manage.py manage_racing_api_horse_identity_review \
  --publish-approval \
  --proposal-dir /private/path/identity-proposal \
  --approved-manifest-sha256 <proposal-manifest-sha256> \
  --approved-rows-sha256 <review-rows-sha256> \
  --decisions /private/path/reviewer-decisions.jsonl \
  --decisions-sha256 <decisions-sha256> \
  --approved-by <reviewer> \
  --decision-source-reference <review-reference> \
  --approved-at <timezone-aware-iso8601> \
  --output-dir /private/path/identity-approval

python manage.py manage_racing_api_horse_identity_review \
  --dry-run \
  --artifact /private/path/identity-approval/identity-review.json \
  --expected-artifact-sha256 <artifact-sha256> \
  --reviewer <reviewer>
```

## 8. 本地验证与剩余门禁

- identity models/resolver/review 组合：`36/36`；
- identity review 专项新增后：`20/20`；
- 加入 staging/profile-candidate/module-review 的相邻组合：`59/59`；
- 覆盖 proposal/approval 零写、candidate/row/profile 漂移、重复 provider、跨语言 resolver、published artifact
  apply 前 identity/alias 漂移、TRA source lock、reject/split、receipt verify/replay/reverse、unresolved no-op
  和命令层写门。

尚未完成：

- 当前没有真实 TRA credential，Montjeu 16 GET 零写 proof 未执行；
- 没有真实 targeted candidate，因此本轮没有发布真实 identity proposal/approval；
- 没有 production staging、backup、dry-run、identity apply、module review、canonical apply 或页面 verifier；
- 完整 stable suite 仍有历史失败，不能用本专项通过替代全量绿色结论。
