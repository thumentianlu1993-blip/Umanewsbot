# P0 马首批来源就绪度审计（2026-07-18）

## 结论

首批五地区各 10 匹已全部确认纳入，并已完成一次性只读研究解析与人工审核工作簿。但“研究
解析成功”不等于“资料已完整”：本节表格记录 7 月 18 日当时只有日本 10 匹同时完成资料、
二代血统和完整生涯的历史快照，严格整体完成度当时为 `10/50`。后续最终 v2 已清零字段和
数量缺口，严格完整度为 `40/50`；美国 10 匹仍因逐场官方性待确认而阻断。本次研究及后续
v2 收口均没有写生产数据库。

| 地区 | 7 月 18 日 10 匹结果 | 13 项硬字段 | 履历状态 | 当时主要缺口 |
| --- | --- | --- | --- | --- |
| 日本 | `10/10` 解析 | `130/130` | `199` 次实际出赛 + `1` 次退赛，来源缺口 `0` | 无 |
| 中国香港 | `10/10` 解析 | `80/130` | `372` 次实际出赛 + `3` 条未出赛，来源缺口 `4` | 出生日期、育马者、父父/父母/母母、4 场履历 |
| 英国 | `10/10` 解析 | `80/130` | `412` 次实际出赛，`18` 场结果状态待补 | 产地、育马者、父父/父母/母母、旧记录状态 |
| 法国 | `10/10` 解析 | `80/130` | `250` 次实际出赛，`12` 场结果状态待补 | 产地、育马者、父父/父母/母母、旧记录状态 |
| 美国 | `10/10` 解析 | `90/130` | HRN `197` 条可见履历，Equibase 官方总数未知 | 毛色、父父/父母/母母、官方完整履历总数 |

## 证据

- 结构化研究结果：
  `runtime/horse_profile_completion/research-50-parsed-20260718/p0_horse_research_50.json`
  当时登记 SHA-256
  `1c15b3c3338cdb9e8fe853d66a6a88c277c2f7afccd1b106349bab8ed640e5ba`。该同名路径后来被
  后续研究步骤覆盖，旧字节未保留、不可复验；当前路径 SHA-256 为
  `7a02bbe0f66177fd813626aa03ea98a190c2b11e227a96aab056ad17c3bb2f6c`，不得作为本次旧产物
  的替代证明。
- 人工审核工作簿：
  `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核.xlsx`
  当时登记 SHA-256
  `584e7493d9c53726616fc18ad03144262dfa418b6940c4fba23aa67c7a09044b`。该同名路径后来由
  7 月 19 日最终工作簿替换，旧字节未保留、不可复验；当前路径 SHA-256 为
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`。
- 最终冻结 v1 审计基线为
  `runtime/horse_profile_completion/pedigree-research-20260719/p0_horse_research_50_enriched.json`
  （SHA-256 `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`）和上述无 `-v2`
  工作簿（SHA-256
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`）。两者字节保持不变。
- 当前可复验结果已升级为
  `runtime/horse_profile_completion/pedigree-research-20260719/p0_horse_research_50_enriched_v2.json`
  （SHA-256 `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`）和
  `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核-v2.xlsx`
  （SHA-256 `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`）。
- v2 不再只是新增来源 ID。`reviewed_parent_identity_evidence.json`（SHA-256
  `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b`）把 `116` 条已审核
  pedigree evidence 解析为 `55` 个唯一父母来源身份，全部 `source_identity` 均包含马名、
  父名、母名和出生年；旧 legacy method 已清零。
- `reviewed_parent_birth_year_evidence.json` 是单独的 approved artifact，SHA-256
  `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`，
  `reviewed_by=codex_manual_source_review`。它不表示项目负责人逐字段提供或审核了 55 个出生年。
- v2 还包含 1 个显式同名纠错：Netkeiba `000a02bd3f` 是 1925 年 Balko，只留在 v1；
  Kentucky Wood 的父系改为 Racing Post `595446` 的 2001 年 Balko，父母为 Pistolet Bleu /
  Ella Royale。纠错前后身份和原因均保留在审计元数据中。
- 日本：<https://www.jbis.or.jp/horse/>
- 中国香港：<https://racing.hkjc.com/en-us/local/information/selecthorse>
- 英国：<https://www.britishhorseracing.com/racing/horses/>、
  <https://www.sportinglife.com/racing/profiles/horse/1014215>
- 法国：<https://www.ifce.fr/ifce/sire-demarches/donnees-sire/listes-de-chevaux/>、
  <https://www.france-galop.com/fr/content/nomination-stud-book-identification-fee>
- 美国：<https://www.equibase.com/profiles/Results.cfm>、
  <https://prodv2.nyra.com/saratoga/racing/entries/?day=2026-07-11&limit=entries&race=10>

## 来源结论

1. 日本继续以 JBIS 作为资料、二代血统和完整生涯主来源。
2. 中国香港以 HKJC 为本地资料/履历主来源，出生日期、育马者和完整三代血统按产地进入官方
   Stud Book；澳洲马优先 Australian Stud Book。
3. 法国 Geny 本次仍返回 HTTP 429。本批使用逐马确认身份的 Sporting Life `Full Form`；
   长期字段补全应使用 IFCE SIRE / France Galop，而不是依赖解除 429。
4. 英国 Sporting Life 可提供履历和部分资料；产地、育马者和完整三代血统需 BHA /
   Weatherbys / Racing Post 等第二来源。
5. 美国先从 Equibase/NYRA 官方赛事页取得 refno、父母、出生日期、产地和育马者。HRN 只在
   父、母、出生年份一致后提供备用履历；Cornishman、Gigante、Movin' On Up 已证明只按
   马名 slug 会误配。Equibase 官方总出赛数未取得前，不得把 HRN 可见行数标记为完整生涯。

## 执行规则

1. 本次 10 匹研究解析不等于正式批次完成；每个缺口都继续按字段/履历维度显式保留。
2. 自动第二来源只能补空，冲突立即阻断。
3. 人工字段补录必须双人审核并保留直接 URL；不得补写生涯。
4. 完整生涯必须由逐马主来源证明来源总实际出赛数和全部逐场核心证据。
5. 单马复验同时通过资料完整度与生涯完整度后，才可扩大到该地区 10 匹。
