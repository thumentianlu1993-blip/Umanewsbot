# 全局赛马资料最终完成证据合同

日期：2026-08-31（Asia/Shanghai）
状态：本地只读设计；生产赛事窗口未释放
副作用：0 TRA 请求、0 生产连接、0 数据库写入、0 服务或 registry 变更

## 结论

现有 `audit_current_graded_horse_export_completion.py` 只能证明一个 candidate batch 与两份
`PROPOSED_NOT_APPROVED` proposal 的成员守恒，输出也固定为 `AUDITED_INCOMPLETE`。它不能证明本 change 的全量目标：

- 全部 32 个 bulk 与 65 个 pre-2005 targeted stable ledger 已合并且 occurrence 100% 覆盖；
- 全部 zero-search enrichment 批次已经完成；
- 每个 provider `hrs_*` 的 identity 与 module review 已由独立 reviewer 批准；
- 每匹马已经由未回滚的 production apply receipt 覆盖，且当前数据库状态仍与最终 receipt 一致；
- 每个 canonical profile 的资料、生涯履历和公开状态符合产品合同；
- 对应公开页面在 production apply 后被独立读取并通过内容验收。

因此旧 audit 必须继续保留为“当前单批次诊断”，不得改名或解释为全局完成证明。

## 四层最终证据

### 1. 全局分母与 provider identity

权威输入是 exact merged stable ledger v2 及其 global coverage：

- merged source set 恰为 32 个 provider-native bulk stable + 65 个 provider-native targeted stable；
- 每个 target occurrence 恰好覆盖一次；
- unique provider horse set 以 `hrs_*` 为唯一机器主键；
- coverage、zero-search plan 与 execution ledger 必须回绑相同 horse/occurrence 集合。

名称、译名、`HorseProfile.pk` 或 candidate 文件路径都不能替代 `hrs_*` 分母。

### 2. 全量 review approval

每个 enrichment batch 必须同时具有：

- exact candidate batch；
- identity proposal 及独立发布的 identity approval；
- module proposal 及独立发布的 module approval；
- identity approval apply receipt 与未反向恢复状态；
- reviewed research/package/release identity。

proposal 的 `PROPOSED_NOT_APPROVED`、candidate 的 `review_required`、staging apply 或 dry-run 均不计为批准。
最终聚合必须按全局 plan 的 batch 顺序重验全部 child，拒绝跳批、孤儿 child、跨批重复 `hrs_*` 和成员漂移。

### 3. canonical DB inventory 与 production receipts

新增的只读 inventory producer 以 exact merged stable ledger 为分母，在数据库中逐个核验：

- `HorseExternalIdentity(source=the_racing_api, namespace=horse, external_id=hrs_*)` 唯一且为 `verified`；
- 对应 identity review receipt 为 applied、未 reverse，且当前 identity/name-variant after-state 仍与 receipt 一致；
- identity 指向唯一 canonical `HorseProfile`；
- profile 当前仍是 full-profile/complete-career/zero-gap，且有完整逐场记录；
- profile 被一个未 reverse 的最终 production apply receipt 覆盖；
- 对该 profile 只验证时间上最后一个有效 receipt 的 live after-state，避免把合法后续 apply 误判为早期 receipt 漂移；
- receipt 保留 apply plan、source batch、region、ordinal、reviewed artifact、package、release、preflight 与 state SHA；
- 输出 profile ID 与 public path，作为第四层独立页面读取的固定输入。

inventory 是数据库只读快照，不做 HTTP 请求、不发布 profile、不修改 receipt，也不把“页面待验收”误报为完成。
若任何一匹马缺身份、缺 canonical profile、缺最终 receipt、receipt live state 漂移或 profile contract 不满足，仍可输出
带 blockers 的审计 artifact，但状态必须是 incomplete。

### 4. production public-page verifier

公开页验收必须在最终 apply 后由独立只读运行生成，逐个绑定第三层 inventory 的：

- inventory manifest SHA；
- `provider_horse_id + profile_id + public_path`；
- fetch URL、HTTP status、fetch time、response body SHA；
- 页面唯一 canonical profile 身份；
- 基础资料、血统、生涯履历和主胜鞍模块的必要内容存在性；
- 分页履历的计数/页面覆盖；
- 页面无 404、500、登录跳转或其他 horse 的内容串线。

200 只能证明可达，不能单独证明内容正确。public verifier 也不得触发 P0 sync、completion adapter、赛事同步或数据库写入。

## 最终 completion audit 判定

只有下列集合完全相等并全部通过时，才允许生成 `AUDITED_COMPLETE`：

```text
merged stable hrs_* set
= global review approved hrs_* set
= identity applied and not-reversed hrs_* set
= production inventory receipt-covered hrs_* set
= public verifier passed hrs_* set
```

同时必须满足 target occurrence coverage=100%、所有 plan batch COMPLETE、无 active execution/claim、无 receipt reverse、
无 database/profile blocker、无 public-page blocker。任一层缺失时输出必须是 `AUDITED_INCOMPLETE` 或 safe-stop，不能按比例
或抽样升级为完成。

## 2026-08-31 实现状态

- `prepare_racing_api_global_review_aggregate` 已实现：在 identity apply 前重放 exact candidate、identity
  proposal/approval、module proposal/approval，并冻结逐马 identity artifact/module approval SHA。
- stable denominator loader 要求 exact 97 个唯一 source stable identities；13 马 pilot 或任一较小 source set 会在
  review aggregate/inventory 前被拒绝，不能仅凭三方小集合自洽升级。
- `load_complete_racing_api_global_review_aggregate` 已实现：apply 后重新打开冻结 bytes 和全部 approval child，
  但不错误重算已被合法 apply 改变的 pre-apply DB snapshot。
- `audit_racing_api_global_completion` 已实现：严格加载 review aggregate、canonical inventory 与 merged public
  verification，逐马核对两类 approval lineage，唯一发布 `AUDITED_COMPLETE`。
- 受影响 binding/final 链 `116/116`；真实全量 artifact 尚不存在，故实现通过不代表本 change 完成。

## 当前门禁

- event 956 的自然 result/public/correction 验收仍占用生产赛事窗口；
- 不 acquire shared lock、不停 Beat、不连接生产、不写数据库、不触碰 canonical/reference registry；
- `3bac…a6da` 与 `740a…cff2` 属不同 registry 身份，继续严格分离；
- 2C+8G 只改善容量余量，不自动释放赛事业务门禁；
- 当前允许的实现仅为本地 schema、只读 inventory producer、synthetic tests 与文档。
