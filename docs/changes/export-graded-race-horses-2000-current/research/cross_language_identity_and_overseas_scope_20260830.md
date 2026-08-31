# TRA 跨语言身份与海外远征参赛范围补充设计

日期：`2026-08-30`

## 结论

目标赛事地区和马匹所属地区必须是两个字段：本批只允许英国、法国、爱尔兰、美国的合资格赛事，
但实际参赛马可以属于日本、中国香港、澳大利亚、德国、中东等地区。不能用马匹所属地区过滤参赛马，
也不能因为日本马或香港马在海外使用英文名而新建第二个 `HorseProfile`。

跨语言匹配固定为两步审核：

1. TRA 英文档案按出生日期、规范性别、父、母四项强事实召回本地 `HorseProfile`；目标马名称不参与唯一
   决定。父母文本为日文时，可用已链接父/母 profile 的官方拉丁别名做精确等值比较，不使用音译相似度。
2. 只有该 profile 已带地区相符且已验证的 JRA/JBIS/netkeiba/NAR 或 HKJC identity key 时，才产生
   `bind_official_local_crosswalk_candidate`。该状态仍是零写候选，必须先经独立 identity review 建立
   `hrs_*` 与英文 source alias；重新生成候选成为 `bind_verified_external_id` 后，才可进入资料、生涯和
   major-wins 模块审核。

四字段任一明确冲突即 `blocked_strong_conflict`；相同四字段命中两条 profile 即
`ambiguous_strong_match`；未验证的本地 key 不能提升为官方 crosswalk。所有这些分支均
`database_write_allowed=false`。

## 海外远征 scope 合同

每个 profile candidate 现保留 `target_scope`：

- policy 固定为 `2000–2020 G1；2021–当前 G1/G2/G3`；
- event region 只允许 `united_kingdom/france/ireland/united_states`；
- 每个 occurrence 必须有唯一 `rac_*`、实际日期、等级和实际出赛状态；
- home horse region 可以是 Japan/Hong Kong/Australia/Germany/Middle East 等受支持值；
- module review 会重验 target scope，不能靠把 home region 改成四地区来绕过范围。

完整生涯中的非目标地区赛事可以进入 staging；已知 AUS/GER/UAE 等 code 映射到扩展地区，其他格式合法的
provider code 保留 raw 并落为 `other` race region。若马名国别后缀没有单独地区枚举，目标马的 operational
cohort 回退到受审目标赛事地区；已知 `(JPN)` / `(HK)` 等后缀仍优先，以便启用本地 identity namespace。

## 与 1999 Montjeu proof 的关系

1999 凯旋门只用于证明“外部来源给出名字 -> `/horses/search` -> `hrs_*` -> Pro profile + full horse
results”的单马路径不受 `/results` 默认 12 个月窗口限制。它不属于 2000–当前正式批量 scope，因此不会
通过本批 `target_scope` 的落表候选门禁。当前 N1 已获最多 16 GET、零数据库写入授权，但运行进程仍未注入
TRA 用户名/密码，所以没有真实响应、没有数据库写入，也不能把离线 fixture 当作 proof 成功。

## 验证

- identity resolver：日文 JBIS、繁中 HKJC、日文父母 + 官方拉丁别名、未验证 key、双 profile 歧义、
  亲本冲突均有回归测试；
- identity review：跨语言 local candidate 无 manual override 时仍可在显式审核后建立 TRA verified ID；
- profile candidate：日本马参加英国目标赛时保留 `home=japan / target=united_kingdom`；
- module review：日本 home region 可进入四地赛事批次，但未经 identity review 的 local candidate 被拒；
- policy：1999 G1 与 2020 G2 均被正式批量 module review 拒绝。

相关四模块组合当前为 `38/38`。这些测试只证明本地合同，不代表真实 TRA 请求、staging apply、canonical
apply、生产部署或页面验收完成。
