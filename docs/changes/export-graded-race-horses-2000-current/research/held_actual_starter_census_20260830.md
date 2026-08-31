# reviewed-held actual-starter census（2026-08-30）

## 结论

350 条 reviewed-held occurrence 已生成逐场实际出赛名册，共 `3,192` 个“马匹 × 目标赛事”槽位，另有
`94` 条明确 `withdrawn/NP/non-runner` 被排除。该结果修正了旧 occurrence 中“只有数字名次的 result
name set 被称作 actual starters”的口径：PU、F、UR、BD、未列数字名次等已经实际起跑的马必须保留。

本产物仍不是稳定马匹身份总账：`provider_horse_id` 全部为空，同名不合并，Sporting Life/ZEturf 的
`source_runner_key` 也明确不是 The Racing API `hrs_*`。下一步必须用目标 occurrence 的日期、场地、赛事、
名次/状态在 TRA 中完成逐场 reconciliation，取得 provider horse ID 后才能跨场去重和导出 profile/career。

## 固定输入

- reviewed COMPLETE target：
  `/Users/mentianlu/.codex/umanews-target-reviewed-complete-20260829.9WzJJH`
  - manifest `a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f`
  - ledger `de5aabfb70257ba65d407cbf05f431595180ef475d0efd768438dca7b17b4264`
- reviewed-held consolidation：
  `/Users/mentianlu/.codex/umanews-reviewed-occurrence-consolidation-v2-20260830.wJIln5`
  - manifest `71c4454e4d6a6023bdd1bcb15940e928bc1be075f5b66ed966d34ec838be07cd`
  - held ledger `7bfe5a6994a331c3b562340e14b09ebff6607a2c47aa049c25bab3e6cfca821f`
- Finale Wayback owner approval：
  `/Users/mentianlu/.codex/umanews-finale-wayback-approved-20260829.BrzUG0`
  - approval manifest `cdd0d9400a22a537b56244f88eaa7bcfc3d131a64e8045edbe1b477e597e238e`
  - approved actual starters `a6e89f3c750ef01bb125cf1e21e663e4d263de796c77f059c210361b60da9005`

所有 350 份 source cache 均重新验证 regular non-symlink、HTTPS host、path、size 与 SHA。运行没有访问
网络、数据库或生产环境。

## 语义规则

### Sporting Life（197 场）

使用 post-race `rides` 的语义状态，而不是只取数字名次：

- `declared` 且有名次、`pulled_up`、`fell`、`unseated_rider`、`brought_down`、`did_not_finish`、
  `refused`、`disqualified`：实际出赛；
- `withdrawn/nonrunner`：排除；
- `unknown`：整场失败关闭。

得到 `1,949` 个实际出赛槽位，排除 `78` 个退赛条目。全部旧数字名次马名仍在新集合中，没有丢失冠军
或已审结果行。

### ZEturf（81 场）

旧冻结 HTML 不含后来 parser 要求的 canonical/data-race-code 页面标记，不能冒充新页面身份 proof；因此
本轮只在 reviewed URL + payload SHA 已获 held 绑定的前提下，重验 URL 日期、标题日期并调用 legacy runner
parser。`.non-partant` 或 `(NP)` 排除，其他 post-race runner 为实际出赛。

得到 `669` 个实际出赛槽位，排除 `16` 个 NP。未列 arrival 数字名次的 runner 保留为
`actual_starter_result_unclassified`，不猜测具体未完赛原因。

### France Galop（71 场）

官方公报内 `actual_starter_count == len(starters)` 的 71 场全部守恒，共 `566` 个槽位。数字名次保留为
finished；`ARR` 规范为 pulled_up；原始行末 `tbé` 规范为 fell；`–/J/unknown` 等无法进一步分类的结果状态
仍保留为 `actual_starter_result_unclassified`。这里的“结果状态未分类”不等于“是否出赛未知”，因为每行
已由 organizer-official actual-starter list 证明实际起跑。

### Sky Sports Wayback（1 场）

只消费 owner-approved occurrence 与 8 行 exact output；1–7 名和 PU 全部纳入，得到 `8` 个槽位、0 退赛。
held occurrence 必须与 approval 输出逐事实一致，任何 SHA 或行数漂移失败关闭。

## 产物与计数

权威 PREPARED root：
`/Users/mentianlu/.codex/umanews-held-actual-starter-census-v1-20260830.q8BroW/artifact`

- manifest SHA：`32b12aa76f912647d74d9a612afe1e49a3af51e9c2551812126922e303273233`
- census SHA：`5916ed2691407b50ced2adb8dbd8f5facb99fbe22e8cc1668304b530d3b4c056`
- target summary SHA：`262cc0380b2870b4f345296e9c36a3917b84f7e12fe31385b079ad6475f39eb9`
- marker SHA：`e54c4c367134f2297abae2865d76c8c368c3757fcee9f0a1ab701f4f43e30165`

| 维度 | 数量 |
| --- | ---: |
| held targets | 350 |
| actual-starter occurrence slots | 3,192 |
| exact name strings（仅召回，不是身份） | 2,321 |
| excluded withdrawals | 94 |
| GB slots | 1,957 |
| France slots | 1,235 |
| G1 / G2 / G3 | 2,220 / 197 / 775 |
| flat / jumps | 1,682 / 1,510 |

状态分布：finished `2,841`、result-unclassified `171`、pulled_up `119`、fell `48`、unseated_rider `8`、
brought_down `3`、did_not_finish `1`、refused `1`。

共有 `534` 个 exact name string 出现在两个或更多 target，单个 exact name 最多出现 12 场。这只说明需要
跨场 identity reconciliation；既不能按名称合并，也不能因此认为是不同马。

## 验证

- 新增专项测试 `7/7`：非完赛保留、NP/withdrawn 排除、unknown fail-closed、France official 非数字结果、
  同名不合并、source payload 漂移、Wayback exact approval 绑定；
- 加入下游批准链 reconciliation 专项后，完整 `runtime/research` 回归 `365/365`，py_compile 与
  `git diff --check` 通过；argparse/OpenAPI
  safe-stop 文本为预期负例；
- 第二个空输出目录全量重放，manifest 与两份 JSONL 逐字节一致；
- 350 份 target summary 与 3,192 行 census 按 target 重新分组守恒；
- `provider_horse_ids_assigned=0`，网络请求 `0`，数据库写入 `0`，production 变更 `0`。

## 后续门禁

1. 该 PREPARED census 不能直接进入 profile batch 或数据库；
2. 先完成 proof-only G2、fresh 双主机 exclusive-account proof 与已批准 Montjeu N1；
3. 37 条 held winner seed extension 仍需真实独立审核，批准后重新生成 exact batch G3；
4. targeted-horse 找到目标 race 后，用 TRA runner `hrs_*` 回写每个 occurrence slot；未知/歧义保持 gap；
5. 全部 `hrs_*` 守恒后才跨场去重，计算 profile/parent/full-career 的真实请求上限。

离线 reconciliation 工具已补齐：它验证 census 3,192 行/350 target 与 held seed proposal 350 条 seed-target
binding 守恒，并要求未来 independently approved COMPLETE seed artifact 对 exact proposal/output/decision/seed
set 的完整绑定，再等待真实 COMPLETE stable-runner ledger。场内名称去国别后双向唯一只生成
`requires_review` candidate；同名、未匹配、count mismatch、target 元数据漂移、NR/unknown 都失败或进入 review。
专项 `8/8`；当前 approved seed 与 stable-runner ledger 均不存在，因此没有生成真实 proposal，也没有任何
`hrs_*` 绑定事实。

后续批准/规划合同也已离线实现：zero-gap publisher 只有在 3,192 slots、TRA occurrences、unique candidates
全部守恒且 review/count/unmatched 为 0 时，才接受独立 exact-SHA decision 并发布 COMPLETE bindings；stable-ID
planner 再同时绑定该 approval 与 exact stable ledger。稳定 ID 阶段明确 `search_requests_per_seed=0`，默认
最多 201 results pages、2 次 profile、两个 parent 各 2 次，共 207 GET/马，最多 5 马/批。execution G3 scope
因此不含 `horse_search`。新增专项 `10/10`、完整 research `375/375`；当前仍没有真实 approval、batch plan、
网络请求或数据库写入。
