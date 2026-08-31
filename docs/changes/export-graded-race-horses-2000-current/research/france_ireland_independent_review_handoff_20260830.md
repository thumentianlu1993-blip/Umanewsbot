# 法国/爱尔兰真实样本独立审核交接（2026-08-30）

## 1. 当前结论与执行边界

法国 Westover 与爱尔兰 Economics 的真实 TRA 响应已经形成两份零写 P0 candidate、只读 identity census、
identity review proposal 和 module review proposal。当前结论固定为：

`FR_IRE_REVIEW_HANDOFF_READY_PROPOSALS_NOT_APPROVED_NO_PRODUCTION_ACTION`

本交接只让独立审核人能够复核和形成决定，不代表批准。生产在
`2026-08-30T01:41:35Z` 因 `MemAvailable=1496692 kB < 1572864 kB` 已 fail-closed；在 rollout owner 明确给出
新的安全窗口和 canonical registry SHA 前：

- 不发布 identity/module approval；
- 不执行 identity dry-run/apply、module build-research 或 P0 production apply；
- 不 acquire shared deployment lock，不修改 shared canonical，不发起 UK/USA TRA 请求；
- 本地法国/爱尔兰 proposal 不并入 production registry。

实现者没有填写 reviewer decisions，也没有把机器建议当成人工批准。审核顺序必须是：先确认 identity
disposition，再审核 profile/pedigree/race_record/major_wins；即使两层都获批，也仍需独立的生产 backup、dry-run、
G3、apply receipt、verifier 与页面抽检。

## 2. 不可变输入与精确哈希

私有审计根：

`/Users/mentianlu/.codex/umanews-four-region-p0-candidate-audit-20260830.ZqQCYw`

全部 proposal 文件当前权限为 `0600`。审核前必须在原目录重新运行 `shasum -a 256`；任一字节变化都拒绝旧
proposal，不通过复制 marker、改时间戳或重算哈希继续。

| 对象 | SHA-256 | 状态 |
| --- | --- | --- |
| `france-westover-p0-candidate.json` | `64dafd20f7589fb5d7428516d8ec22a38714bb49cdc2ae61a2ed2b8a3c574263` | `review_required`，0 DB writes |
| `ireland-economics-p0-candidate.json` | `81afe3287b43a866926c28e76cce729d89a4b9c02159bd18d4286f92da652e7e` | `review_required`，0 DB writes |
| identity `proposal-manifest.json` | `b9c2b6f71c76c0e3e28b0b1d6ad6756b1812adcec50048b6721e45f12ac2a826` | `PROPOSED_NOT_APPROVED` |
| identity `review-rows.jsonl` | `854660cc980d013133d38a0e451f96809833e9e283050baf2c2d693246f0f260` | 2 rows |
| identity `decision-template.jsonl` | `e41aca4c617bb152627c70b29203a7feb49a00a34056344f05215f3a34371d4c` | 机器模板，不是 reviewer decision |
| module `proposal-manifest.json` | `e9ff268918ee4b7a35cc7cd34874000e27f16fab8fbbef95a9898b3192c520a5` | `PROPOSED_NOT_APPROVED` |
| module `review-rows.jsonl` | `73b9a64d6ed8930475a5b63acd9478b7a537943ab497bab8a36b56fb2942712f` | 2 horses / 20 records |

identity proposal 的 source manifest set SHA 为
`929f6e0fa5b040ff90d3cc59517e3cf2e29e0ec8eecbe669e2126054a139a846`；逐马 source manifest 为
`0208b4961089f31cb6e91aebe97ad98c6701a986c90b707ae43a70d9133a8214` 与
`8eff6078bda8e50dc6a437e16f308202b9c85a5990548f80934ac483bf8b3a43`。

## 3. Identity 审核账本

### 3.1 Westover

- provider ID：`hrs_26036913`；staged ExternalHorse/alias ID：`60/60`；当前 canonical identity、official
  claim 和 candidate profile 均为空。
- source display：`Westover (GB)`；出生日期 `2019-04-24`；性别 `H/horse`；父 `Frankel (GB)`；母
  `Mirabilis (USA)`。
- resolver：四字段匹配、无冲突字段，disposition=`create_new_candidate`；机器建议仅为 `create_draft`。
- 目标 occurrence：法国 `rac_10988900`，`2023-07-08`，G1，实际完赛并获胜。
- target Pro response SHA：
  `787058127f533c1ef0eadcec3ee0078ed2406752ce97402142d21c6dafcff965`。

审核人必须确认当前库不存在同一实际马匹的 canonical profile，尤其不能仅因英文名没有命中就直接新建；DOB、
sex、sire、dam 任一不一致都使用 `leave_unresolved`，而不是强行 `create_draft`。

### 3.2 Economics

- provider ID：`hrs_37860606`；staged ExternalHorse/alias ID：`148/148`；当前 canonical identity、official
  claim 和 candidate profile 均为空。
- source display：`Economics (GB)`；出生日期 `2021-03-01`；性别 `C/colt`；父
  `Night Of Thunder (IRE)`；母 `La Pomme D'Amour (GB)`。
- resolver：四字段匹配、无冲突字段，disposition=`create_new_candidate`；机器建议仅为 `create_draft`。
- 目标 occurrence：爱尔兰 `rac_11309415`，`2024-09-14`，G1，实际完赛并获胜。
- target Pro response SHA：
  `8b59a28b6eaa821b026674aa20f130fbaab6519986ca40be57dbf5dcb36a8015`。

TRA search 同时披露过一匹澳大利亚同名马，采集器只把其 results 当作 occurrence 消歧 probe，未写入本候选的
`source_evidence` 或 career。独立审核必须用 `GB + 2021-03-01 + Night Of Thunder + La Pomme D'Amour`
确认目标身份，不能用名称相等消除跨国同名冲突。

### 3.3 Identity 决定文件

审核人应把 `decision-template.jsonl` 复制到独立、私有、普通文件后再编辑；不得改 proposal/candidate。两行的
`proposal_row_sha256` 分别为：

- Westover：`6b62390092ba0b96d1ece9dacc8a9c2aa0495ef668a990cf9646f3a728276188`；
- Economics：`f1b74d7bd7d062ff4261f709e28cccf4d0507c09d8e1b265b00de3d0aac6d921`。

允许的保守选择：

- 已确认没有既有同马 profile，且四字段完整一致：`create_draft`；
- 发现唯一、强证据一致的既有 profile：从最新 staging/DB 状态重建 proposal 后再选择 `bind_existing`；
- 仍有重复或字段疑点：`leave_unresolved`；
- 当前两行都没有既有错误绑定，因此不能使用 `reject_binding`。

每行必须填写可审计的 `review_notes`；如果使用二级证据，保存普通 HTTPS 来源、抓取时间与 payload SHA，不得只写
“已核对”。决定文件产生后单独计算 SHA，由项目所有者对 proposal manifest、rows、decisions 三个完整 SHA 作
精确批准。当前没有这样的批准。

## 4. Module 与逐场履历审核账本

两份 candidate 的 `provider_profile_complete/page_profile_complete/provider_career_complete` 均为 true，
`missing_or_conflicting_page_fields=[]`。这只表示 TRA 分页和字段合同闭合；在 module approval 前，原候选仍必须
保持 `record_authority_status=count_aligned_records_unverified`、`career status=partial`，不得手改为 verified。

| 马 | provider results SHA | provider starts / rows | nonstarter / gap | overseas starts |
| --- | --- | ---: | ---: | ---: |
| Westover | `64c9c29e05faae38e31986c06e7781b8488ca0c7b3d4a7dc782ac7c2d7966aae` | 13 / 13 | 0 / 0 | 5 |
| Economics | `bea7169780e8557efb38ecfedbc8ce91a72801647f316d43d3561b3afeb10a07` | 7 / 7 | 0 / 0 | 2 |

### 4.1 Westover 的 13 条 started records

| 日期 | race ID | 赛事 / 地区 | 名次 |
| --- | --- | --- | ---: |
| 2021-08-05 | `rac_10256025` | British EBF Maiden Stakes / UK | 1 |
| 2021-09-17 | `rac_10292425` | Haynes, Hanson & Clark Conditions Stakes / UK | 2 |
| 2021-10-18 | `rac_10317879` | Silver Tankard Stakes (Listed) / UK | 2 |
| 2022-04-22 | `rac_10498514` | Classic Trial (G3) / UK | 1 |
| 2022-06-04 | `rac_10455211` | Derby (G1) / UK | 3 |
| 2022-06-25 | `rac_10371868` | Irish Derby (G1) / Ireland | 1 |
| 2022-07-23 | `rac_10565594` | King George VI And Queen Elizabeth Stakes (G1) / UK | 5 |
| 2022-10-02 | `rac_10566803` | Prix de l'Arc de Triomphe (G1) / France | 6 |
| 2023-03-25 | `rac_10870782` | Dubai Sheema Classic (G1) / Middle East | 2 |
| 2023-06-02 | `rac_10865062` | Coronation Cup (G1) / UK | 2 |
| 2023-07-08 | `rac_10988900` | Grand Prix de Saint-Cloud (G1) / France | 1 |
| 2023-07-29 | `rac_10948665` | King George VI And Queen Elizabeth Stakes (G1) / UK | 2 |
| 2023-10-01 | `rac_10935912` | Prix de l'Arc de Triomphe (G1) / France | 2 |

### 4.2 Economics 的 7 条 started records

| 日期 | race ID | 赛事 / 地区 | 名次 |
| --- | --- | --- | ---: |
| 2023-11-03 | `rac_11058437` | British EBF Novice Stakes / UK | 4 |
| 2024-04-20 | `rac_11224421` | Newbury Maiden Stakes / UK | 1 |
| 2024-05-16 | `rac_11224863` | Dante Stakes (G2) / UK | 1 |
| 2024-08-15 | `rac_11369969` | Prix Guillaume d'Ornano (G2) / France | 1 |
| 2024-09-14 | `rac_11309415` | Irish Champion Stakes (G1) / Ireland | 1 |
| 2024-10-19 | `rac_11350027` | Champion Stakes (G1) / UK | 6 |
| 2025-10-18 | `rac_11700182` | Champion Stakes (G1) / UK | 8 |

审核人须逐行确认 `started`、race ID/date/name/region/grade、finish position 与同一个冻结 results response 的
SHA 绑定。module proposal 当前机器建议四模块均 approve、confidence 95；这只是建议，不能替代逐行核对。

## 5. Profile 与二代血统证据

| 马 | 页面字段 | 值 |
| --- | --- | --- |
| Westover | country / colour / sex | GB / b / horse |
| Westover | breeder / owner / trainer | Juddmonte Farms Ltd (Gb) / Juddmonte / Ralph Beckett |
| Westover | 二代父系 | Frankel -> Galileo / Kind |
| Westover | 二代母系 | Mirabilis -> Lear Fan / Media Nox |
| Economics | country / colour / sex | GB / ch / colt |
| Economics | breeder / owner / trainer | Copgrove Hall Stud / Isa Salman Al Khalifa / William Haggas |
| Economics | 二代父系 | Night Of Thunder -> Dubawi / Forest Storm |
| Economics | 二代母系 | La Pomme D'Amour -> Peintre Celebre / Winnebago |

父母 Pro response SHA：

- Westover：`hrs_5344171` =
  `14327954a1f71696202676182b3d181ddbaf0a024b102d51896e15692272f6a0`；`hrs_4223863` =
  `ae16a7764fdcbc1c0dd51ed820aa59f7977fb538b9a3e44c689c44e1e93c3e7b`；
- Economics：`hrs_5876514` =
  `3e34b03f319278e90ec5a94c1fcaf4b707ac8cee055e99e1b78aaeff97d3dd56`；`hrs_5492767` =
  `588f790dd9d8376bd0d47559a1199e082a54b396ec726fc0e3100a76aaadb7c4`。

trainer/owner 是 provider 当前或最近观察值，不是全生涯逐时点权威；中文名、正式本地名、简介和 canonical
所属地区仍为本地审核/unknown。TRA 是受许可的数据提供方而非四地赛事官方 authority；module approval 只能把
冻结的 source records 提升为本批受审资料，不能声称逐场均经赛事主办方官方核验。

## 6. 必须拒绝旧提案的条件

出现以下任一情形，独立审核必须停止并从最新冻结状态重建：

1. candidate、proposal manifest、rows、decision template 任一 SHA 不一致或路径变成 symlink/非普通文件；
2. ExternalHorse、alias、已有 HorseProfile、identity/official claim 状态与 review rows 快照不同；
3. Economics 的澳洲同名马证据进入目标 `source_evidence`/career，或目标四字段不能唯一确认；
4. 13/7 条 career 守恒变化、出现未解释分页/gap/nonstarter，或逐行 results SHA 不再等于表中冻结 SHA；
5. target occurrence 不再唯一匹配 Westover `rac_10988900` / Economics `rac_11309415`；
6. parent profile 不是声明的 `hrs_*`，或 payload SHA 漂移；
7. reviewer、时间、决定来源为空，或实现者试图把 recommendation、自测/replay、`PREPARED` marker 当批准；
8. rollout owner 尚未给出安全窗口/canonical SHA，却尝试 publish、build-research、apply 或并入 registry。

## 7. 批准后仍需经过的独立门禁

当且仅当独立审核与项目所有者对完整 SHA 作出明确批准后，才可在新的私有输出目录 publish identity/module
approval。publish 仍应是 `network_requests=0 / database_writes=0`。之后依次需要：

1. identity approval dry-run；如需 identity apply，另取数据库写授权、备份、receipt verifier；
2. 从获批 module proposal build reviewed research/authority，并绑定 approval manifest SHA；
3. 生成 mapping、reviewed P0 artifact、exact package/release 和独立 release approval；
4. fresh custom-format PostgreSQL backup，并用 `pg_restore --list` 验证；
5. 现场 maintenance preflight、逐批精确 G3、零写 dry-run、apply receipt/verifier 与页面抽检。

当前这些步骤均未获批准、未执行。identity/module proposal 的 replay 只证明确定性，不替代独立审核；identity
replay 的新时间戳 manifest `7ca11781556529dceb27c97f71f70337f4c2e0b4220e1089467789d473943f5f`
不能替换原审核目标 `b9c2b6f7...a826`。
