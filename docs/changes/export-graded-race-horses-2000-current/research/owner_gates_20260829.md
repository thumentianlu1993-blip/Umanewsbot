# 四地区分级赛参赛马回填：当前需要项目所有者决定的门禁

日期：2026-08-29（Asia/Shanghai）

本清单只收敛需要项目所有者或独立审核人的决定。技术实现、测试通过或研究者建议都不能代替这些决定；
不同门禁分别授权，任一批准都不连带授权生产写入、公开发布或其他门禁。

## 当前执行状态

- R1：已由项目所有者批准重绑定 proposal；approval manifest/review SHA 为
  `6e0116c9e17130a2f1d9b1db1b7625e390f7a588f1b92fc365794e7318e04ddb /`
  `994713c77eec1f4abaf245f28f1324999eaa7289995ed971f4b30065f1e4f235`。已生成 12,048 行
  reviewed COMPLETE target，manifest/ledger SHA `a130d11a…903f / de5aabfb…4264`。
- R2：旧绑定已失效；项目所有者已重新批准 manifest/rows SHA
  `5f66e5c91f31e59ab30cafa5a0c6f846f5c32fec43e499505fc2af1610b4708f /`
  `b4ac644ff907ff87e03f5caabd4686d8c880ddd6535c57e2c227d0fe668b99bc`。批准产物 manifest SHA
  `76f2fcb011f940fc35d559cba78da1c33e5204d7a164cad4d76d9943277a22ee`。
- R3：旧绑定已失效；项目所有者已重新批准 manifest/proposal SHA
  `4c2f1f41fac66e5b67bd20eb1102a09311d135451b004a0ec710e582d035f10e /`
  `5d6c50aba69c4aad54b88d9ca75ff3124d2ba2eb476c517b43dbb54bd2b884f7`。批准产物 manifest SHA
  `cdd0d9400a22a537b56244f88eaa7bcfc3d131a64e8045edbe1b477e597e238e`。
- N1：已批准最多累计 16 GET、零数据库写入 proof；2026-08-30 已在 fresh proof 下执行。首次 edge-blocked
  search 消耗 1 GET，固定 User-Agent 后重跑消耗 2 GET；search/results 均 200，但 provider career 无唯一
  1999 Arc occurrence，按 `provider_partial` safe-stop。累计 `3/16`、数据库写入 0，未调用 profile/parent。
- 2026-08-30 项目所有者再次确认 R1 九项与 N1；现有 R1 approval/COMPLETE target/seed SHA 只读重验均无
  漂移，不重发重复 approval，也不扩大到 B2、24 批或数据库 apply。
- B2：四地区 4 匹样本 proposal 已生成，尚未批准；必须等待 N1 成功后，再审核爱尔兰/美国 occurrence
  binding 与精确 manifest/ledger。

下文 R1/R2/R3 的早期 SHA 仅保留审批演进记录；不得继续作为当前执行绑定。

## R1：9 个 series/year 来源冲突

建议采用冻结提案的 9 项 disposition：

- 2000/2001 France：各补一届 Prix de l'Abbaye G1；
- 2000 USA：接受实际举行 96 场 G1，不按计划摘要补造两场；
- 2008 USA：删除 Hollywood Futurity 重复别名，Frank J. De Francis 标记未举行；
- 2022 USA：Bed o' Roses G3 改 G2；
- 2023 USA：补 Dueling Grounds Derby G3；
- 2025 France：接受 France Galop 明细 28/23/63；
- 2026 France：删除 Penelope G3；
- 2026 USA：未举行的 Cougar II/Californian 不进入参赛分母。

预期 series/year inventory：`12,047 -> 12,048`。这不是 held occurrence 或参赛马数。

审核绑定：

- package manifest：
  `a44b8bbd19b9e298e2288c1dd6c9f6801197171afe84222513e2677d9e24b08e`
- proposal：
  `c1d62b529e423b5498787a9ac12eb9f3332426aa580d579012cf1f39c3a129d3`
- blocker payload：
  `dedf39dff4fb4a342dd3737fa7d096e7c9d641598dd5847ec7f5558e9495d9d1`
- 详细证据：[source_conflict_review_proposal_20260829.md](source_conflict_review_proposal_20260829.md)

批准语义：只允许生成独立、SHA-bound 的 source conflict approval 并重建 target；不授权 TRA 网络或数据库
写入。若任一 SHA/9-key 集合漂移，批准自动失效。

## R2：英国 11 场旧 series alias

建议接受三个精确 migration：

| 旧 key | 当前 key | 场次/实际出赛席位 |
| --- | --- | ---: |
| `GBR_CORONATION_CUP` | `united-kingdom-coronation-cup` | 4 / 29 |
| `GBR_ASCOT_GOLD_CUP` | `united-kingdom-gold-cup-ascot-flat-20-turf` | 2 / 25 |
| `GBR_CHELTENHAM_STAYERS_HURDLE` | `united-kingdom-stayers-hurdle-cheltenham-jumps-3-jumps` | 5 / 57 |

审核绑定：

- manifest：`3081e7cb5a8e50874a53ed1882e4379251e692b871dd6b7a4b794316530b25de`
- proposal：`a49cab78fe23a164e83f22489fa4745818188ae544e9f80a38c2cd7751ca9423`
- generator：`b706bf025bdef074a65b973f088d38aa20e39773591652158caf4ff624578abd`
- 详细证据：[legacy_occurrence_alias_proposal_20260829.md](legacy_occurrence_alias_proposal_20260829.md)

批准语义：只承认这 11 场旧冻结结果与当前 target 的 exact-series 关系；不批准新的 Sporting Life 批量
抓取，不连带批准 Finale 跨年补赛，也不在 target 仍 PREPARED 时生成 runnable seed。

## R3：2015 Finale Juvenile Hurdle 跨年补赛

建议接受：原定 `2015-12-27` Chepstow 赛日因积水取消；该届赛事于 `2016-01-09 14:20` 补赛，G1，
8 匹实际出赛（1–7 名 + PU），冠军 `Adrien Du Pont (FR)`。

审核绑定：

- manifest：`c099fd08ad112de66c921e01ad2bfef340722736e21598a697ffc0be2c59cf9e`
- proposal：`f4d438eeaa0d3bebfdd88bdd808e64f9beb7257ad9d437612872ffc16abacff3`
- Sky cache：`78128e00020879f0f916038e679d280e21c313f001715a1fb9897df22bd1638d`
- RTE cache：`dbd563a91c8e76d80964e7d6988e9aa6042a7ad4e5d0e42e67ac883dad60ed2f`
- 详细证据：[legacy_occurrence_reuse_audit_20260829.md](legacy_occurrence_reuse_audit_20260829.md)

批准语义：只允许形成下一自然年 occurrence override；不把原 racecard 的 11 匹声明当实际出赛，不授权
TRA 网络或生产写入。

## N1：Montjeu 1999 Arc 真实 TRA proof（已执行，provider partial）

建议批准精确零数据库写入 proof：

- host：仅 `api.theracingapi.com:443`；
- paths：Montjeu search、候选 full results、唯一候选 Pro/Standard、最多两个父母 Pro/Standard；
- 明确排除 `/v1/results`、racecards 和其他接口；
- 总预算最多 `16 GET`、无额外 retry reserve、全账号不超过 `4 req/s`；
- 要求 fresh exclusive-account proof；401/403/429/schema/身份/分页/预算任一异常 safe-stop；
- 输出只有 response cache、request ledger、normalized artifact 和 manifest，`database_writes=0`。

固定 seed SHA：`d642f8ea5c64f6d1b7166aba6bb4ba9bba5f3776b38d8fd68f77f5e280290814`。
完整命令与验收：[g3_montjeu_proof_20260829.md](g3_montjeu_proof_20260829.md)。

执行结果：search 解析出唯一 exact-name/country candidate `hrs_3521238`，其 horse results 为 200，但未形成
唯一目标 occurrence；失败 manifest SHA `15500f14…a65`。批准语义继续只覆盖本 proof，不批准四地区批量、
External staging apply、canonical apply、生产写入或发布，也不授权修改 seed 后继续调用 profile。

原批准语义：只批准本 proof，不批准四地区批量、External staging apply、canonical apply、生产写入或发布。
执行还要求 `RACING_API_USERNAME/RACING_API_PASSWORD` 通过受控环境或 0600 secret 注入；不得在聊天、命令
参数、日志或 artifact 中出现。

## 后续仍需单独决定

上述四项即使全部批准，仍需：

1. 先根据 proof 证明账号 Pro、historical bulk、North America entitlement 和真实字段合同；
2. 审核四地区样本 manifest
   `8e28dffb8bc4c62630c80d466db9409c3174f1eed1b76f732d2bab6f8556538f` 与 seed ledger
   `c7e90af9b2c962650e58580efa1fa89f7b40b73957d511dd45e3e9d9873e7eb9`；其 request ceiling 为
   `64 GET`、数据库写入为 0，且 N1 成功前不能执行；
3. 从 reviewed COMPLETE target/held occurrence/horse census 计算四地区批量 G3；当前 313 个冠军锚点
   只形成 24 批初步定位计划，不是最终 actual-starter census；
4. 对每批 identity/module review 形成独立签名；
5. 每个生产 apply 窗口单独执行 backup、dry-run、release approval、apply 与 verifier。

当前不请求也不推定第 2–5 项授权。
