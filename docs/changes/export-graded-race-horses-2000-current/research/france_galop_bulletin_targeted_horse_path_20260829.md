# France Galop 公报到 Racing API 全场参赛马的定向链

## 结论

France Galop 官方 2026 flat/obstacle 公报已证明“外部官方冠军名 -> TRA 单马完整历史 -> 目标赛事全体
actual starters”具备可执行输入。当前发布包合计确认 71 场 G1/G2/G3、566 条实际出赛记录、411 个跨
discipline 去重马名；独立 audit 生成 71 个冠军锚点提案。由于上游四地区 target ledger 仍是 PREPARED，这些 seed 明确
`runnable=false`，本轮没有调用付费 TRA endpoint，也没有写数据库。

## 官方来源与读取边界

- 官方索引：`https://www.france-galop.com/fr/content/bulletins-officiels-valeurs`
- 首次受控批次：18 次 GET，间隔 1.25 秒，请求预算 20。
- 2026 flat：索引发现 16 个公报链接；缓存 14 个 PDF。
- 2026 obstacle：另一次受控读取为 17 GET；索引发现 16 个公报链接，缓存 14 个 PDF，第 1、15 期
  持久 404；随后全部重放为零网络。
- 官方索引中两个链接返回 404：
  - `https://www.france-galop.com/sites/default/files/2026-04/26plat05.pdf`
  - `https://www.france-galop.com/sites/default/files/2026-07/26plat12.pdf`
- 发布包重放为零网络；404 证据被持久保存，不把缺文件解释成赛事未举行。
- URL 只能来自索引；仅对 France Galop 同主机的 `http` 链接做确定性 `https` 升级，不猜文件名。
- `bis/ter` supplement 不进入常规期数；两位/四位年份和数字 revision suffix 均有解析合同。

France Galop 法律声明限制数据库的实质性抽取及超出正常使用的重复系统抽取。本工具面向经目标总账
限定的低频赛事证据和公报缓存，不将 France Galop 全站镜像成本地马匹数据库。正式扩大历史读取前仍需
复核具体授权与使用条款。

## 实际赛果解析规则

- PDF 双栏分别抽取，日期只来自页头或独立 meeting date，不读取正文中任意日期作为上下文。
- 目标必须精确匹配年份、赛事名、等级、距离和受审马场恒等；不开放通用 fuzzy 合并。
- `N partants` 是硬守恒；解析出的 actual starters 数必须完全一致。
- 等级行同时支持 flat 的 `(Groupe I)` 与 obstacle 的 `(Haies - Groupe I)`、
  `(Steeple-Chase - Groupe III)`，但只在紧邻赛事头的括号等级行识别。
- 换行负磅 `57 k, h, ...` 和 `(691/2 k), h, ...` 是上一匹马的续行，不得识别为新马。
- 数字名次和结果栏 `–` 都是实际出赛。
- `Certif. vétérinaire`、`Chev. retir.` 等非出赛状态排除。
- 历史 form 前缀最多移除 5 位数字；不得把 `3 2 1 Horse Name` 当作马名。
- 马名只是将来 TRA search 的 query seed，不是跨来源 canonical identity。
- series 默认场地与当届官方赛果实际场地分开保存。2026 Prix du Bois 的 France Galop 转场公告为
  `https://www.france-galop.com/en/node/9327`；官方实际 occurrence 在 Deauville，不覆写 target 的
  Chantilly 系列默认。

## 首个 AQPS 规则验证子集

| 日期 | 马场 | 赛事 | 等级 | Actual starters | 冠军 |
| --- | --- | --- | --- | ---: | --- |
| 2026-03-24 | Saint-Cloud | Prix Bango | G3 | 11 | Louisa Banbou |
| 2026-04-17 | Saint-Cloud | Prix d'Estruval | G3 | 12 | Lili Star |
| 2026-07-22 | Vichy | Prix de l'Union des AQPS du Centre-Est | G3 | 13 | Mabriska |
| 2026-07-24 | Le Lion d'Angers | Prix de l'Isle Briand | G3 | 6 | Nuit De Star |

该子集总计 4 场、42 条 actual-starter rows、31 个唯一马名 query seeds，用于验证 AQPS、`–` 和
non-runner 规则。随后同一缓存已扩大到全 2026 flat。

## 当前全 flat 结果

- held occurrences：52；G1 8、G2 10、G3 34。
- actual-starter rows：405。
- unique name query seeds：288。
- 日期：2026-03-15 至 2026-08-09。
- unmatched/not-due targets：77；不推断 not held。
- 场地关系：51 场等于系列默认；Prix du Bois 的 2026 官方实际场地为 Deauville，target 默认 Chantilly，
  产物保留二者和 `official_result_overrides_target_default`，actual starters 为 6。

扩大解析时发现并关闭两个真实问题：Vaticana 的换行续行 `57 k, h, ...` 曾被误读成名为 `k` 的第 9 匹
马，现已以负磅续行规则排除且继续满足 `8 partants`；Prix du Bois 因官方临时转场产生系列默认/当届
实际场地差异，现分字段保存而不是覆盖或拒绝真实赛果。

## 当前 obstacle 结果

- held occurrences：19；G1 2、G2 4、G3 13。
- actual-starter rows：161。
- unique name query seeds：123。
- 日期：2026-02-23 至 2026-05-30。
- unmatched/not-due targets：43；不推断 not held。
- 与 flat 合并：71 场、566 个实际出赛席位、411 个去重名称 seed。

障碍首轮曾因等级行含 discipline 前缀而得到 0 场；修正后守恒校验又暴露 Christian de Tredern 的
`(691/2 k), h, ...` 负磅续行误识别，旧规则为 `parsed=10 / partants=9` 并停止。当前规则排除该续行后，
19 场全部满足官方 partants 数，未通过降低守恒门槛制造覆盖。

## 产物身份

当前全 flat 发布包（旧 `zl9Ml1/n5puPG` 因 parser 指纹更新而被取代）：

- root：`/Users/mentianlu/.codex/umanews-france-galop-flat-2026-release-current-20260829.YI2GTU`
- proposal manifest SHA-256：
  `81bb9ddce3e0530f18f4d291393b90864d5845e12f972500d00159a4562e6a4b`
- parser SHA-256：
  `d73305c0a6bc536259d500f071913cef16cd09b298dc20e0a4c085772f9a460a`
- `horse-name-seeds`：288 rows，SHA-256
  `ba409b3185689af335ced40240c9a878bf9ae99e06c003a33dd1318692ad8035`
- `occurrences`：52 rows，SHA-256
  `af3fa067f0d71b9ba377088634974c1c7a52f188482635c9338da8f297447394`
- `unmatched`：77 rows，SHA-256
  `dd2a01b5e8affba7dc2af4d2e11a8ce33f8eabf3b130e13d1cad66991adc4ed3`
- 状态：PREPARED，release build 零网络、零 TRA、零数据库写入。

当前独立 audit：

- root：`/Users/mentianlu/.codex/umanews-france-galop-flat-2026-release-audit-current-20260829.WD27Vs`
- audit manifest SHA-256：
  `e9fb188552e28f8de62b8a544c21667f0e2475051fd6fcba7796b51a85e2e53f`
- auditor SHA-256：
  `b04205cb50b965d7277facff0c1cd058c9e7bd590504dd4d34f86eca8ea4e556`
- targeted seed proposal：52 rows，SHA-256
  `7be8e77ce2b6e09ed346bd1a0a8c5e2844d45b2266558194f1ab93c9fb36fda6`
- 状态：AUDITED_REFERENCE_ONLY，`runnable=false`。

当前 obstacle 发布包：

- root：`/Users/mentianlu/.codex/umanews-france-galop-jumps-2026-release-rerun-20260829.DMhbWi`
- proposal manifest SHA-256：
  `0338f1a45e24afbddb1d9caf428957f62e2788f7fe006e3cb176faca861a0736`
- parser SHA-256：
  `d73305c0a6bc536259d500f071913cef16cd09b298dc20e0a4c085772f9a460a`
- `horse-name-seeds`：123 rows，SHA-256
  `83a5e2dea517e0847f7c2490f1e607e66c9807637cd36a01889ee8c048f9fa27`
- `occurrences`：19 rows，SHA-256
  `41bc74d0b5afef845920be9a4adeb43e92f8ab6ef7ace26ffb38017fe05cc4cb`
- `unmatched`：43 rows，SHA-256
  `905d60267e2b9b64a0f84da11bd5bcea2382f25108782ad5faae76ef99e1956a`
- 状态：PREPARED，重放零网络、零 TRA、零数据库写入。

当前 obstacle 独立 audit：

- root：`/Users/mentianlu/.codex/umanews-france-galop-jumps-2026-release-audit-20260829.l29Ggl`
- audit manifest SHA-256：
  `969b233dab5de901cf0755c16f9d70ffae38d2753cbc7b38cc35d17b9c15e9a9`
- targeted seed proposal：19 rows，SHA-256
  `9693b9d34fe9f776e34f2aee19bf96b708ab7bfa47726b5710e8d3389471d0a3`
- 状态：AUDITED_REFERENCE_ONLY，`runnable=false`。

以下 AQPS-only 包是首轮验证历史，已被当前全 flat parser/release/audit 取代：

- root：`/Users/mentianlu/.codex/umanews-france-galop-aqps-2026-release-20260829.R7V4WT`
- proposal manifest SHA-256：
  `defdc294705f9b655c9e2be8404599b1a723afd0cb833bacb638dd0dc267967d`
- parser SHA-256：
  `1cef1b05925ff788ff58fde970fe1dc05b83417dfbed0a17ea67b3ca487a7c05`
- `horse-name-seeds`：31 rows，SHA-256
  `33453e2c5fd677610db8a6a0646ead48d0a73fc638a97ce02dee618c4a22531f`
- `occurrences`：4 rows，SHA-256
  `dd2357129dc477fb1c5380833ef3863fcc8dde37ecd472783ee1b4b7db80c13a`
- `unmatched`：11 rows，SHA-256
  `c1cd3b2dd5407b0d7ae5a14c7b85336dcde9643a1766254502a6715bfba54db9`
- pdfplumber：0.11.9
- 状态：PREPARED，release build 零网络、零 TRA、零数据库写入。

对应独立 audit：

- root：`/Users/mentianlu/.codex/umanews-france-galop-aqps-2026-release-audit-20260829.g4MTg9`
- audit manifest SHA-256：
  `a5d319a848fc398760d385ffb4f469ed897abf70d04da5100db90c191fb23fd3`
- auditor SHA-256：
  `af7d2dff7365f9da0db14f7f5a442568801668ff51cbec4097851899582a6570`
- targeted seed proposal：4 rows，SHA-256
  `32b13e9e2caeb8086c5750b8e8827b9981936d815046fec02a33d40804815418`
- 状态：AUDITED_REFERENCE_ONLY，`runnable=false`。

以下更早目录同样不得继续引用：

- `/Users/mentianlu/.codex/umanews-france-galop-aqps-2026-20260829.Fonm0k`
- `/Users/mentianlu/.codex/umanews-france-galop-aqps-2026-evidenced-20260829.BG9FeQ`
- `/Users/mentianlu/.codex/umanews-france-galop-aqps-2026-final-20260829.xuKfqd`
- `/Users/mentianlu/.codex/umanews-france-galop-aqps-2026-deterministic-20260829.xVPRf6`

全 flat 扩大过程中以下目录因参数或 parser fail-closed 中止，没有 PREPARED marker，不是 artifact：

- `/Users/mentianlu/.codex/umanews-france-galop-flat-2026-release-20260829.E2Hdx9`：错误地把 release root
  传给 `--reuse-source-dir`，读取 PDF 前停止。
- `/Users/mentianlu/.codex/umanews-france-galop-flat-2026-release-20260829.HmozQH`：执行会话中断，未发布。
- `/Users/mentianlu/.codex/umanews-france-galop-flat-2026-release-20260829.Jksqn4`：Sandringham 负磅换行
  被误读，`parsed=9 / partants=8` 后停止。
- `/Users/mentianlu/.codex/umanews-france-galop-flat-2026-release-20260829.W97u5V`：Prix du Bois 实际转场
  与 series 默认场地不同，旧规则停止。

## TRA 两阶段请求链

第一阶段每场只选一匹冠军：

1. `/v1/horses/search?name={winner}` 召回候选；
2. 对 exact-name/country 候选分页读取 `/v1/horses/{hrs_id}/results`；
3. 以日期、地区、马场、赛事名、等级、discipline 和冠军名次唯一确认 `hrs_*`；
4. 从目标 race 返回的完整 runner 列表取得所有 actual-starter `hrs_*`，排除 non-runner。

第二阶段按目标赛事边界补全：

1. 跨目标赛事去重全部 actual-starter `hrs_*`；
2. 每个稳定 ID 直接读取 `/pro`，404 才回退 `/standard`；
3. 全分页读取 `/results`，不走默认 12 个月的批量 `/v1/results`；
4. 按需要读取最多父、母两个 parent profile，深度固定为 1；
5. 逐项确认该 `hrs_*` 在全部来源目标 race 中实际出赛，且 race payload hash 未漂移；
6. career 中其他 race 的 runner 只保存 observation，不递归进入 profile 补全总账。

已新增 `build_target_runner_stable_id_ledger.py`：从完整 targeted batch materialization 生成每个唯一
actual-starter 一条的 `targeted-runner-stable-id-seed.v1`；批次 runner 已支持该 schema，不再 search。
单匹稳定 ID 的保守请求上限为
`max_results_pages + 2(profile fallback) + 2*max_parent_profiles`。真实请求数通常低于上限，但必须以账号级
exclusive budget 为硬门禁。

离线 fake-client 已验证完整路由为 search -> horse results -> pro，以及 target actual starters 守恒；
第二阶段验证按稳定 ID 直取 profile/results、同一马跨两场只生成一个 seed、两个 occurrence 均重新匹配、
且没有 `/horses/search` 请求。

## 历史覆盖边界

冻结当前官方索引可发现的常规公报链接大致为：2015 `24/24`、2016 `25/4`、2017 `24/25`、
2018 `26/26`、2019 `26/26`、2020 `11/11`、2021 `26/25`、2022 `26/25`、2023 `26/26`、
2024 `26/24`、2025 `26/26`、2026 当前 `16/16`（flat/jumps）。这些只是当前索引链接数，不是赛事
完整性证明；2016 jumps 明显需要逐年调查，2020 受赛历中断影响。

- 2021–当前：适合将官方公报作为法国 held-result 主输入之一，仍需处理索引缺链。
- 2015–2020：可逐年利用，不能自动宣称完整。
- 2000–2014：当前索引没有建立系统化覆盖；需要单场官方历史页、受审旧 bundle 或其他许可来源。
- 任何缺公报、404 或未匹配都只形成 source gap，不形成 `not_held`。

## 验证

- France Galop parser/auditor：17/17 通过。
- 项目依赖容器 `runtime/research`：264/264 通过。
- Django TRA/TJCIS/identity/staging + 历史来源相邻组合：252/252。
- Django check、migration drift、py_compile、diff check 通过。
- 所有验证均为离线或 France Galop 低频只读来源读取；没有付费 TRA、数据库写入、commit、push、部署。
