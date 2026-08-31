# 英法爱旧历史产物复用审计（2026-08-29）

状态：`AUDITED_REFERENCE_ONLY`。本报告只确认旧缓存中有哪些可追溯赛事与实际出赛记录可以作为
The Racing API targeted-horse 路径的外部 anchor；不代表 target ledger 已完成，不代表 TRA 已返回，也
不代表任何数据库已写入。

## 1. 结论

现有旧产物不能覆盖本 change 的英、法、爱全量分母，但有一批可复用的逐场结果证据：

| 地区 | 本次 target rows | 哈希审计后精确命中 occurrence | 需 alias 复核 | 补赛替代提案 | 精确命中+替代 result rows |
|---|---:|---:|---:|---:|---:|
| 英国 | 3,194 | 186 | 11 | 1 PREPARED | 1,691 |
| 法国 | 1,890 | 115 | 0 | 0 | 742 |
| 爱尔兰 | 1,957 | 0 | 0 | 0 | 0 |
| 合计 | 7,041 | 301 | 11 | 1 PREPARED | 2,433 |

`2,433` 是逐场 result row 数，不是 canonical horse 数。精确行加补赛提案仅按大小写折叠马名得到
1,810 个文本值，不能
拿它做跨国、跨语言或同名马去重。

英国精确命中的 186 场包括 flat 80、jumps 106；G1 184、G2 2。法国精确命中的 115 场包括
2023 年 70 场、2026 年截至旧抓取时点 45 场；flat 70、jumps 45；G1/G2/G3 为 29/22/64。

爱尔兰在旧版 approved inventory 中没有独立 region，文件名中的 `irishracing` 只是 provider recipe
标签，不能解释为爱尔兰赛事已经覆盖。因此爱尔兰 1,957 个 target rows 仍需从 HRI/其他受审结果来源
建立 held occurrence 和 winner/runner anchor。

## 2. 审计对象和证据身份

目标账本（跨年份 series 消歧修复后）：

- root：`/Users/mentianlu/.codex/umanews-target-seriesfix-20260829.L1aF64/output`
- ledger rows：12,047
- ledger SHA-256：`f04a7d5886c91de9c300598cd9d752b48960342ca6d334bdb75c2e3edef69481`
- marker：`PREPARED`
- manifest SHA-256：`c3675dd1349d3de7864f986cf101a5fdb5daa352ce533e6da4b7dc102719bf19`

新版与旧版 12,047 行按除 `series_key/target_key/source.cache_path` 外的全部事实字段比较为零增删；仅
226 行身份键发生规范化，其中英国 139、美国 87。9 个范围 blocker 的 key 集合和 canonical payload
SHA-256 `dedf39dff4fb4a342dd3737fa7d096e7c9d641598dd5847ec7f5558e9495d9d1` 均未改变。

旧英国 bundle：

- root：`runtime/historical_plan_exports/detail-import-bundle-uk-sportinglife-v8`
- bundle manifest SHA-256：`3c6a4d11106c2b490876d63f0719b71d6fde9d7c7bc9c8937736d26a0e28831c`
- scope：198；records 197；gap 1
- 独立 audit manifest SHA-256：
  `e943c2b65ff946eceff828f6eb851490d2b3f1aef15c3ad17cfca5730efded4f`

旧法国 bundles：

- base root：`runtime/race_event_crawl_runs/france-zeturf-residual-20260716/import-bundle-v1`
- base manifest SHA-256：`feb9a7f1795571e22d76223f50ab72579a85b95081fe88533c56de0dd0efb6a5`
- base audit manifest SHA-256：
  `f819e6e5e5d26894efa9b3e744b768939a57a6914d47b831db5f35bb0c956fb2`
- correction root：
  `runtime/race_event_crawl_runs/france-zeturf-residual-20260716/corrections/import-bundle-v1`
- correction manifest SHA-256：
  `26d9885d7b1a9eb103c4b50b826a1d923d53fca0d89ead867e1c3930b67f161b`
- correction audit manifest SHA-256：
  `aa4f85dc758238f3d583dd33c5663355ca123379d1dd131928c4846c0d38fc9c`

审计工具逐一校验 manifest/chunk/candidates/source-cache 的 path、size 和 SHA-256，要求 result 与 runner
模块都声明 complete、有马名、结果中存在 position=1 anchor，并按
`region + year + series_key` 恰好命中一个 target。它不做 fuzzy matching，也不访问网络或数据库。

## 3. 英国待复核项

11 场都能从 source URL 和年份辨认出稳定系列，但旧 key 与当前 TJCIS key 不同，所以没有静默合并：

| 旧 key | 建议当前 key | occurrence 数 | result rows |
|---|---|---:|---:|
| `GBR_CORONATION_CUP` | `united-kingdom-coronation-cup` | 4 | 29 |
| `GBR_ASCOT_GOLD_CUP` | `united-kingdom-gold-cup-ascot-flat-20-turf` | 2 | 25 |
| `GBR_CHELTENHAM_STAYERS_HURDLE` | `united-kingdom-stayers-hurdle-cheltenham-jumps-3-jumps` | 5 | 57 |

合计 11 场、111 个 result rows。接受 alias 后，旧英国包的 197 场结果总数将恢复为 manifest 声明的
1,794；但接受动作必须绑定新 target manifest SHA，不能沿用本次 PREPARED audit。

### 3.1 2015 Finale Juvenile Hurdle 已有替代证据，但仍未签署

旧 Sporting Life 2015-12-27 页面确实不是赛果：`ride_count=11` 但 `rides=[]`，不能把 11 匹 declared
当 actual starters。进一步只读核验得到：

- RTE 2015-12-26 报道明确说明次日整个 Chepstow meeting 因积水取消；
- Internet Archive CDX 找到 Sky Sports 完整赛果的 2019-07-17 capture；
- 存档赛果明确为 2016-01-09 14:20 Chepstow、Grade 1，共 8 匹实际起跑：1–7 名加 1 匹 PU；
- 冠军为 `Adrien Du Pont (FR)`，可作为 targeted-horse winner anchor。

PREPARED artifact：

- root：`/Users/mentianlu/.codex/umanews-finale-wayback-seriesfix-20260829`
- manifest SHA-256：`c099fd08ad112de66c921e01ad2bfef340722736e21598a697ffc0be2c59cf9e`
- proposal SHA-256：`f4d438eeaa0d3bebfdd88bdd808e64f9beb7257ad9d437612872ffc16abacff3`
- Sky archive cache SHA-256：`78128e00020879f0f916038e679d280e21c313f001715a1fb9897df22bd1638d`
- RTE cache SHA-256：`dbd563a91c8e76d80964e7d6988e9aa6042a7ad4e5d0e42e67ac883dad60ed2f`
- target ledger 仍为 PREPARED，`cross_year_evidence.review_status=prepared`，所以没有生成 runnable seed。

新提案通过显式 `--reuse-source-dir` 对旧 source manifest、URL、size、SHA 和非符号链接路径逐项复核，
再把相同 bytes 写入独立新 root；全程零网络。两份 source payload SHA 与旧提案完全相同，只有新缓存
manifest/root、target artifact 绑定和生成时间改变。

编译器现只允许 `local_date.year=edition_year+1` 的下一年补赛，而且必须绑定原定日期、实际日期、
取消/延期原因、可信 HTTPS 来源缓存 SHA、reviewer 与带时区 reviewed_at；无 override、日期漂移、同年
滥带 override 都拒绝。正式审核后该 occurrence 应保存 `edition_year=2015 / local_date=2016-01-09`。

若 11 个 alias 与本提案均审核通过，英国旧 scope 为 198 场、1,802 条 actual result rows、1,284 个
大小写折叠马名文本；英法合计 313 场、2,544 条 result rows、1,856 个马名文本，仍都不是 canonical
horse 数。

## 4. 如何转成不受 bulk 12 个月窗口影响的 TRA 任务

复用策略不是对旧包中的 2,425 个名字逐个立即查 profile，而是每个 occurrence 先选择一个有名次证据的
冠军 anchor：

1. 外部结果页提供 `horse name + exact date + race/course + grade/discipline + finish position=1`，并保存
   源文件 SHA；第三方证据标为 `human_reviewed_reference`，不冒充官方。
2. 调用 `/v1/horses/search?name=...` 只做候选召回；不选搜索第一条。
3. 对所有同名候选调用 `/v1/horses/{id}/results`，由目标 occurrence 唯一匹配选出 TRA horse ID。
4. 该 career 结果中的目标赛返回同场完整 runners；排除 non-runner，保留完赛、F/PU/UR/DNF/DSQ 等
   实际起跑状态。
5. 对同场得到的所有唯一 `hrs_*` 再做 Pro→Standard profile、父母 profile 和完整 career enrichment；
   content-addressed pool 按 horse/race/HTTP payload 去重。

因此现有 301 个精确 occurrence 加上 1 个 PREPARED 替代 occurrence 最多先需要 302 个 anchor seeds，
若 11 个 alias 审核通过则为 313 个；不是 2,544 个搜索任务。当前单 seed
最坏请求上限仍按已冻结公式计算；Montjeu proof 配置为 16 GET。真实批次必须先用账号 entitlement 和
候选分布小样本重算，不得直接按 `301 × 16` 当成必然消费或成功数。

新增 `build_targeted_seed_ledger_from_legacy_audit.py` 已验证会拒绝本次 PREPARED target。只有 target
artifact 为 reviewed `COMPLETE`、audit 重新运行并绑定新 manifest 后，才输出可执行 seed ledger。

## 5. 不能复用为最终事实的部分

- Sporting Life/ZEturf 是可信参考来源，不替代 TRA provider identity 或主办方官方 finality。
- 旧 `runners` 模块可能包含赛前 declared/non-runner；actual starters 只先取 complete results 中的实际
  结果行，最终仍由 TRA position code 再守恒。
- 旧 bundle 的 target IDs 属于旧 approved inventory，不能直接写入当前 target 或生产 RaceEvent。
- 旧 source URL、马名、场名和 source horse ID 都不能单独成为 canonical horse/race identity。
- 2026 法国 45 场只是截至旧抓取时点的已完成子集，不代表 2026 年度结束或全年度 complete。

## 6. 下一步

1. 先关闭 9 个当前范围 source conflicts，发布新的 reviewed COMPLETE target ledger。
2. 对上述三个旧 bundle 重跑哈希审计；审核 11 个英国 alias，并签署/纳入 2015 Finale 跨年提案。
3. 由新 COMPLETE audit 生成 313 个候选 occurrence winner seeds；先跑 Montjeu 和四地区小样本，确认实时
   OpenAPI fingerprint、账号额度、候选数、历史分页深度和字段非空率。
4. 英国用 BHA schedule/result reference 补齐未覆盖 occurrence；法国用 France Galop held programme/
   result evidence 补齐；爱尔兰从 HRI 独立建立全量 occurrence，不复用英国 region。
5. 每场 TRA race 恢复后做 target/race/actual-starter 守恒，再进入 profile/parent/career 和 identity
   staging；所有 canonical/生产写入继续受独立 backup、dry-run、apply receipt 和 verifier 门禁。

本次 series 修复、三份旧 bundle 重审、冻结缓存复用、Finale 重绑和 target 差分审计的纯离线相邻组合
为 `59/59`；没有
Racing API 请求、数据库写入、提交或部署。
