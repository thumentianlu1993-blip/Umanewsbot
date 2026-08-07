# 单年度分级赛全部参赛马研究测试用例

## 测试原则

- 所有自动化测试使用本地 HTML/JSON fixture 或 fake transport，不访问公网。
- 新行为先写测试并取得真实 RED；RED 必须来自新 collector/契约尚不存在或旧行为仍限制前五名，
  不得用 import 路径、依赖缺失或错误 fixture 伪造。
- 可复用的 checkpoint 基础层不为制造 RED 而故意破坏。

## 年份合同

1. `--year` 缺失时 CLI 拒绝。
2. 1984、历史中间年份和当前 UTC 年份合法。
3. 1983、未来年份、非整数和多个年份表达拒绝。
4. sitemap discovery 只接收 `/races/<exact-year>/`。
5. 页面日期与 CLI year 不一致时不纳入并记录错误。
6. year 漂移、相同目录复用另一年 manifest、跨年 source artifact 均 fail closed。

## 地区与等级

7. 八个规范地区的直接页面标签分别正确映射。
8. “澳洲”收敛到 `australia`；香港别名收敛到 `hong_kong`。
9. 阿联酋、沙特、卡塔尔、巴林收敛到 `middle_east` 并保留 country。
10. 日本扩展等级与其他地区 G1/G2/G3 正确接受，Listed/普通赛拒绝。
11. “其他”页面使用 exact URL region manifest 正确解析。
12. region manifest year、URL、重复项、region/country、symlink 或工作树外路径非法时拒绝。
13. 页面精确标签与 manifest 冲突时拒绝。
14. “其他”无 manifest 命中时记录 `region_unresolved`，不得从赛事名、slug 或马场猜测。
15. incomplete manifest 输出未分类 other URL 数和 `classification_incomplete`；只有
    `classification_complete=true` 且 exact 覆盖所有 other URL 才允许
    `no_public_in_scope_races`。
16. complete manifest 缺失/多出一个 other URL、或 out-of-scope 未留 evidence 时拒绝。

## 全部实际参赛马

17. 12 匹正常完赛 fixture 输出 12 行，而不是前五名。
18. 同着导致重复数字名次时全部保留。
19. DNF、PU、F、UR、RO、BD 和赛后 DSQ 保留并规范化状态。
20. SCR、NR、退赛、取消出赛、除外不纳入 occurrence，并计入 excluded。
21. 只有赛前 runner、没有结果行的马不算参赛。
22. 已完赛范围内赛事没有任何实际参赛行时为解析错误。
23. 同 race 完全重复结果行幂等去重；相同马号不同马名拒绝。
24. 非数字未知结果状态保留原文、标记 unresolved 并排除，不伪造起跑或名次。
25. result rows、included、non-starter、unresolved 与 duplicate 计数满足守恒。
26. 旧“必须恰好五行/名次 1—5”断言在新入口中不存在。

## 多语种名称

27. 中文展示名、日文假名原名、英文拉丁原名分别进入正确字段。
28. 一个混合字符串不会被复制进多个语言字段。
29. 中文缺失允许输出并进入 review queue。
30. 日本/香港英文缺失时 `required_english_status=not_applicable`。
31. 美国、英国、法国、澳大利亚、德国、中东英文缺失分别触发 status=missing，但 occurrence
    和 horse row 不丢失。
32. non-Japan/HK 的拉丁原名满足 required English。
33. 英文完整但中文缺失时 status=complete、name completeness=partial，并同时进入中文复核。
34. 一匹马同时缺中文和必需英文时保留两个 issue code，queue 仍只有一行。
35. 一匹马跨日本与美国参赛时 required English 适用且只计入英文分母一次。
36. 同名多个 profile 为 ambiguous；profile detail transport error 与 not found 分开。
37. 新地区唯一同名 `other` profile 但无原名+出生年/country 证据时 unresolved。
38. 新地区候选 country 不符时 ambiguous；两个目标 `other` 地区同名马不合并。
39. 相同 canonical profile URL 的多次 occurrence 收敛为一匹马。
40. 无 profile URL 的不同地区同名马不跨地区合并。
41. review queue horse key 唯一，并覆盖可组合的名称、ambiguous/error/unresolved 问题；
    profile 五状态总和等于 unique horses，`profile_unresolved>0` 只能产生 partial outcome。

## 删除 Wikipedia/Wikidata

42. 新 collector 不声明 Wikimedia host、WikidataResolver、wiki 字段或 score/match status。
43. workflow 不包含 search/entity/score jobs 或 source stage。
44. fake transport 若收到 Wikimedia URL 立即失败；完整 synthetic 不发生此请求。
45. 最终目录不含三个旧 Wikipedia/top5 文件，只含新 7 文件。

## Checkpoint、合并与 finalize

46. races variable-length item 在 safe-stop 后恢复，item bytes 与不中断基线一致。
47. 完成 stage 即使含 retryable errors 也验证后 byte no-op。
48. verified partial index/index-ahead progress 崩溃窗口按既有保守合同恢复。
49. manifest/input/upstream/item/tool/region-manifest SHA 漂移拒绝。
50. 四 profile shards 稳定覆盖全部 horse keys，fan-in 缺 shard/重复/冲突拒绝。
51. finalize 不构造 HttpClient，只读绑定的 races 和 merged profiles。
52. 重复 finalize 在固定 clock 下逐字节一致。
53. occurrence、unique horse、required English、other URL classification 和 review queue
    不变量错误时拒绝。
54. request count 从 races/profile indexes 聚合，不写死。

## Workflow 静态与 synthetic

55. PR/default run 只有 tests/synthetic，无公网 jobs。
56. `full_network=true` 才运行 races/profiles/finalize DAG。
57. source 三元组部分提供时拒绝；stage 只允许 races/profiles。
58. 每个真实网络 stage 的 75 保持 job failure，`if: always()` 上传 checkpoint。
59. synthetic 首次退出 75，第二次恢复到 finalize，报告 byte equivalence。
60. workflow year 传给所有正式 stage，output 目录按单 year 隔离。
61. collector/test `py_compile`、workflow YAML 解析、现有 workflow contract tests 和
    `git diff --check` 通过。

## RED 证据位置


- RED 命令、运行时间、测试总数和失败/错误数。
- 每个失败对应的目标行为。
- 已经通过的旧 checkpoint 测试，证明没有伪造基础层失败。

### 2026-07-30 第一轮 RED

- 运行时间：`2026-07-30 16:41:05 CST`。
- 测试文件编译命令：
  `python3 -m py_compile runtime/research/test_collect_graded_race_participants.py`；
  结果：通过。
- 聚焦 RED 命令：
  `python3 -m unittest runtime.research.test_collect_graded_race_participants`；
  结果：共 `14` 项，`14 failures / 0 errors`。
- 所有 failure 均为显式 assertion：
  `目标入口 runtime/research/collect_graded_race_participants.py 尚不存在`。没有
  `ImportError`、第三方依赖错误、语法错误或 fixture 解析错误；因此 RED 精确对应新
  collector/API 尚未实现。
- 14 项合同覆盖：
  必填单年与跨年/非法年份拒绝；八地区及别名/中东国家映射；complete/incomplete exact URL
  region manifest；12 匹实际参赛马而非 top5；non-starter 排除与未知状态 fail-closed；
  `profile_resolution_state`、`required_english_status`、`name_completeness` 和可组合 issue
  codes 的正交状态；generic `other` 唯一同名但缺少出生年/country 证据时 unresolved；
  UmaFans-only host/阶段与无 Wikipedia/Wikidata surface；final 精确 7 文件；year、region
  manifest、run manifest、tool 和 checkpoint 漂移拒绝；region manifest symlink/工作树外路径
  拒绝。
- 冻结旧基础层回归命令（从 `c7cb5d7d` 提取到临时目录，仅使用本地缓存，显式
  `uv --offline`，未访问公网）：
  `uv run --offline --no-project --with requests --with beautifulsoup4 --with urllib3 python -m unittest -v runtime.research.test_collect_2026_graded_top5_wikipedia.CheckpointContractTests`；
  结果：`17 tests / OK`。这证明旧 `StageStore`、manifest、稳定分片、safe-stop/resume、
  index/item 漂移和 deterministic merge 基础合同仍通过，本轮没有通过破坏基础层制造 RED。

## 2026-07-30 首轮代码审核与 findings 1–11 修复

- 独立代码 reviewer 首轮结论为 `REVISE`，共 `7 P1 + 4 P2`。findings 1–10 的修复覆盖
  public runner 状态完整匹配、retryable checkpoint 重试、safe-stop artifact 续跑、
  canonical profile merge、地区一致的 profile identity、generic `other` 详情事实重验、
  coverage partial/error、可组合名称 issue、manifest/stage 请求预算和 workflow 显式预算。
- P2-11 要求保留赛事日历历史实际 review 命令，禁止为通过当前合同而反向改写历史。修复后，
  状态文档把该命令放在内容精确匹配的审计块中，明确标注为“旧规则下的历史事实，非当前可执行
  指令”；checker 只剥离这一固定记录后再扫描其余命令。
- workflow contract 的既有 mutation 测试新增三步验证且测试方法总数保持 `26`：现行 workflow
  中删除只读 override 仍失败；把历史记录改成“当前可执行指令”失败；在标记块外新增当前裸命令
  说明仍失败。
- findings 1–11 完成本地修复后进入同一 reviewer 第二轮限定复审；第二轮结论仍为 `REVISE`，
  新增 `2 P1 + 3 P2`：

  1. resume 后累计请求数不得重置，旧 checkpoint 计数漂移须 fail closed；
  2. 当前页面的“暂定赛果”不得作为正式参赛证据；
  3. profile 搜索只接受受控原名别名，不做任意模糊扩展；
  4. profile 搜索须安全遍历分页，并拒绝恶意或循环 next link；
  5. complete other manifest 的 coverage 必须逐地区报告。
- 上述五项完成本地修复后进入同一 reviewer 第三轮限定复审；第三轮仍未通过。
- 同一 reviewer 第三轮限定复审结论仍为 `REVISE`，新增 `4 P1 + 2 P2`：

  1. 请求计数必须使用 crash-safe write-ahead ledger，transport crash 后仍可精确恢复；
  2. profile 详情页必须按 occurrence 二次核验地区和 country；
  3. 非 live 页面只有明确标记为已人工审核的正式赛果才可信；
  4. provisional 必须形成结构化 error，并传播为 partial coverage/outcome；
  5. HTTP 状态必须区分 permanent/retryable，profile 404 按 not found 单独处理；
  6. `errors.json` 必须包含去重、可组合的名称完整性问题。
- 上述六项均已完成本地修复。workflow 同步验证 races discovery/stage 与 profile shard 的
  ledger artifact/restore，并在 README 明确 hard cancellation 或 runner timeout 可能绕过
  `if: always()` post-step，不能保证上传。
- 同一 reviewer 第四轮限定复审结论仍为 `REVISE`，新增 `3 P1`：

  1. pending conflict 必须保持 non-final；
  2. profile 详情缺少真实详情名时禁止以搜索名 fallback；
  3. provisional 必须成为终态 `evidence_gap`，并由正式 DAG 继续产出 partial 的 7 个最终文件。
- 上述三项均已完成本地修复。workflow 同步接受 `evidence_gap`、修正 races index 路径并新增
  完整离线 harness。
- 同一 reviewer 第五轮限定复审结论仍为 `REVISE`，新增 `1 P1 + 3 P2`：

  1. 真实 `HttpClient` 必须严格且仅允许受控 `/horses/?q=&page=` 搜索查询，拒绝其他 host、
     path、参数、重复参数、非法页码、fragment 和编码绕过；
  2. coverage 中 error 必须优先于同地区已有 occurrence，不能误报 `covered`；
  3. unresolved 结构化错误必须保留 region、country 和 source URL；
  4. 没有数据行的三份 CSV 仍须输出各自固定表头。
- 上述四项均已完成本地修复并纳入历史 `53/53`。
- 同一 reviewer 第六轮限定复审结论仍为 `REVISE`，新增 `1 P1 + 1 P2`：

  1. profile country 事实中的目标国家 ISO alpha-2/alpha-3 代码必须受控归一到规范 country，
     同时拒绝非目标国家代码和伪代码；
  2. 当正式结果全部为未知状态时，race 必须成为终态 `evidence_gap`，逐行保留马名、原始状态、
     region、country 和 source URL，完整 DAG 继续完成并产出 partial 7 文件。
- 上述两项均已完成本地修复并纳入历史 `56/56`。
- 同一 reviewer 第七轮限定复审结论仍为 `REVISE`，新增 `2 P1 + 2 P2`：

  1. periodic index 已落盘但 progress 尚未落盘的崩溃窗口，续跑必须以已验证
     index/request ledger 为权威安全重建 progress，并保持预算与不中断基线逐字节一致；
  2. 多条 occurrence 共用一个 profile URL 时，详情 identity 必须逐条校验并保留冲突行证据；
  3. `region_unresolved` 必须完整进入 source manifest、结构化 errors 和 partial coverage；
  4. Middle East occurrence 即使 region 都为 `middle_east`，仍须逐 country 检查 manifest/page
     冲突。
- 上述四项均已完成本地修复并纳入历史 `60/60`。
- 同一 reviewer 第八轮限定复审结论仍为 `REVISE`，新增 `2 P1`：

  1. races discovery 与后续 race fetch、profile fetch/pagination 必须使用同一 stage monotonic
     deadline；discovery 在 deadline 到达时返回安全停止，并精确 checkpoint queue、visited、
     discovered URLs、inflight 和累计请求数，resume 不重放已完成页面；
  2. profile 搜索分页必须在每页前检查共享 deadline；只有第一页搜索 404 可视为空结果，后续页
     404 必须 fail closed。
- workflow 合同同步要求 races checkpoint 无条件包含 `discovery_progress.json`、
  `discovery_request_ledger.json` 和 stage `request_ledger.json`；不得以 run manifest/index
  尚未生成作为跳过上传条件，恢复路径覆盖整个 output dir。
- 上述修复已纳入历史 collector `64/64`、workflow `11/11`。
- 同一 reviewer 第九轮限定复审结论仍为
  `REVISE（P0=0 / P1=0 / P2=1）`，唯一 P2 为：

  1. discovery 遇到 429、5xx 或 transport `RetryableHttpError` 并耗尽内部重试后，不得作为
     未捕获异常丢失续跑语义；必须保存含 queue/inflight/request count 的精确 progress 与
     request ledger，返回 exit `75`，resume 从 inflight URL 继续且不重放已完成页面。确定性
     4xx 仍须抛 permanent error。
- 唯一 P2 已完成本地修复并纳入历史 `66/66`。
- 同一 reviewer 第十轮限定复审结论仍为 `REVISE`，新增 `2 P1 + 1 P2`：

  1. discovery 必须按 XML 根元素区分 `sitemapindex` 与 `urlset`：前者只把 sitemap URL
     入队，后者只收集精确 `/races/<target-year>/` URL；混合类型与其他年份不得污染年度输入；
  2. generic `other` profile 的身份匹配必须要求详情页多语 alias 与 occurrence 受控 alias
     存在交集，并结合出生年、country 等附加 identity 事实，不能只凭搜索候选名；
  3. coverage 必须由实际解析为 in-scope graded 的 race 证据驱动；manifest 命中但页面只有
     Listed/out-of-scope 赛事时不得标记 `covered`。
- 上述三项均已完成本地修复并纳入历史 `69/69`。
- 同一 reviewer 第十一轮限定复审结论仍为 `REVISE（P1=1）`，唯一 P1 为：

  1. Australia/Germany generic `other` profile 在详情 alias 与 occurrence alias 相交且出生年份
     匹配时，可在详情 country 缺失的情况下满足附加身份；出生年份不符仍 unresolved，详情一旦
     提供 country 就必须一致，否则 ambiguous。Middle East 始终要求明确且一致的 country。
- 唯一 P1 已完成本地修复并同时覆盖 direct profile URL 与搜索路径，纳入历史 `70/70`。
- 同一 reviewer 第十二轮限定复审结论仍为 `REVISE（P1=1）`，唯一 P1 为：

  1. direct profile URL 与搜索候选必须调用同一个 canonical group validator，对 group 内每条
     occurrence 分别核验 alias intersection、region、country 和 birth year；不得只用代表行
     放行共享候选。任一 occurrence 冲突时整组 fail closed，并保留每条 occurrence 的
     `identity_reviews` 证据。
- 唯一 P1 已完成本地修复并纳入历史 `71/71`。
- 同一 reviewer 第十三轮限定复审结论仍为 `REVISE`，新增 `1 P1 + 1 P2`：

  1. 搜索路径必须从 canonical group 的全部受控 aliases 生成稳定、去重、顺序无关的 query
     序列，逐 query 收集候选并按 canonical profile URL 去重；任一 query 的请求预算或 deadline
     异常必须传播，不能只查询代表 alias；
  2. profile identity 冲突进入结构化 errors 和最终 `errors.json` 时，必须同时保留
     `expected_*` 与 `actual_*` 两侧的 aliases、region、country、birth year，以及
     profile URL、`conflict_fields` 和 reasons，支持逐 occurrence 审计。
- 上述两项均已完成本地修复并纳入历史 `73/73`。
- 同一 reviewer 第十四轮限定复审结论仍为 `REVISE`，新增 `1 P1 + 1 P2`：

  1. profile URL 必须在 validation、search candidate、direct fetch、canonical group、merge
     和最终 record 全链路收敛为严格、保留受控 scheme 的
     `<http|https>://umafans.run/horses/<id>/`；缺 trailing slash
     与规范形式必须去重，只允许单段数字 ID，query、fragment、编码绕过和额外 path 拒绝；
  2. Middle East 的 expected/actual country 任一侧 missing、uncontrolled 或 mismatch 都必须
     fail closed；identity review、结构化 errors 与最终 `errors.json` 必须保留
     `expected_country_raw/canonical`、`actual_country_raw/canonical`、country
     `conflict_fields` 和明确 reason。
- 上述两项均已完成本地修复并纳入历史 `75/75`。
- 同一 reviewer 第十五轮限定复审结论仍为 `REVISE（P1=1）`，唯一 P1 为：

  1. profile URL 必须先按原始 path 验证为单段正整数真实详情路由，之后才允许规范化缺失的末尾
     slash；`0`、负数、slug、搜索/关注路由、重复 slash、dot segment、percent-encoded ID、
     额外 path、query 和 fragment 均拒绝。canonical horse key、direct fetch、search parser、
     merge 等身份入口必须使用同一验证器，synthetic 必须使用合法数值 ID。
- 唯一 P1 已完成本地修复并纳入历史 `76/76`；synthetic 当前输出
  `/horses/900001/`、`/horses/900002/`。
- 同一 reviewer 第十六轮限定复审结论仍为 `REVISE（P1=1）`，唯一 P1 为：

  1. profile URL 必须直接校验原始 `str`，不能先做 NFKC 或 trim；必须拒绝前后及 path 内的
     Unicode whitespace、Unicode control、全角字符、percent encoding 等绕过，只接受 ASCII
     正整数 `/horses/<id>/` 路由，并在 canonical key、direct fetch、search parser、merge 等
     全部身份入口一致执行。
- 唯一 P1 已完成本地修复并纳入历史 `77/77`。
- 同一 reviewer 第十七轮限定复审结论仍为 `REVISE（2 P1）`：

  1. 所有 profile URL 原始字段必须不经预先 normalize 直接严格校验；race/profile HTML 中的
     profile `href` 必须先由专用严格 resolver 判定，只允许合法相对数值路由或完整严格 URL，
     不能先由 `urljoin` 折叠 dot segment、scheme-relative、反斜线、空白、全角、编码、query
     或 fragment 绕过；
  2. HTTP profile 请求必须禁用自动 redirect；原始 `Location` 必须先按严格 profile href
     解析并限定同 host，响应 final URL 必须直接严格校验，不能先规范化或丢弃异常部分。
- 两项 P1 均已完成本地修复并纳入历史 `79/79`。
- 同一 reviewer 第十八轮限定复审结论仍为 `REVISE（P1=1）`，唯一 P1 为：

  1. absolute profile href 必须与承载它的 race/search 来源页面 hostname 精确一致；
     redirect `Location` 和响应 final URL 必须与原始 profile 请求 hostname 精确一致。
     `umafans.run` 与 `www.umafans.run` 虽均在 allowlist 内，也不得在上述链路相互切换；多
     query 搜索出现 host variant 时必须在发起详情请求前 fail closed。
- 唯一 P1 已完成本地修复并纳入历史 `81/81`。
- 同一 reviewer 第十九轮限定复审已 `APPROVED`，P0/P1/P2=`0/0/0`，session
  `019fb2f6-da26-7463-81b3-0b3c52ed4cf0`。审阅时 HEAD 为
  `6d073dc07cb29201bbc922255923820c872a0467`，fingerprint 为
  `89a8021db567eaaed7003680cd85377ca04ec7ee08d48168ef3212cbcb51d262`，content manifest
  为 `cfb5630c1dc29a0d04b62816a4ce2f296640308e838614d96d57af2d6fbce0a1`；pre/review/post
  均 exit `0` 且只读。该结论现仅作为历史审阅快照，上述 fingerprint 不是最终发布指纹。
- 同一 reviewer 第二十轮最终确认结论为 `REVISE（P2=1）`，唯一 P2 为：

  1. 日本、中国香港、美国、英国、法国五个标准地区的 profile region 已明确匹配时，profile
     country 缺失不应阻断 identity；若 country 存在但与 occurrence 冲突，仍须返回
     `ambiguous` 并 fail closed。Australia、Germany、Middle East 仍执行原附加
     country/birth-year 证据规则，不得放宽。
- 唯一 P2 已完成本地修复并纳入历史 `82/82`。
- 同一 reviewer 第二十一轮最终确认结论仍为 `REVISE（P2=1）`，唯一 P2 为：

  1. profile country 解析与 identity evidence 必须显式保留
     `country_fact_state=missing|controlled|uncontrolled`。空字段才是 `missing`；非空但不在
     受控字典中的值必须保留 `country_raw`、置 canonical 为空并标记 `uncontrolled`，不得按
     profile region 回填为合法 country，且须在 direct/search、identity review 和结构化 errors
     中 fail closed。标准五地区只有真正 `missing` 时可按明确 region 通过；AU/DE/Middle East
     不放宽。
- 唯一 P2 已完成本地修复并纳入当前 `83/83`。
- 同一 reviewer 第二十二轮最终确认已 `APPROVED`，P0/P1/P2=`0/0/0`，session
  `019fb360-79a8-7aa0-8064-b5a604bc7c7e`；pre/review/post=`0/0/0`。approved parent
  `6d073dc07cb29201bbc922255923820c872a0467`，approved fingerprint
  `21a32cf22ef48207d44880d21ec2059ccdd711fe6758a80ee60cb069277f61ce`，content manifest
  SHA-256 `35672bc11172cd5ca7372da53d3ff38de7d31157c952361822c55de27adeffb1`。

## 2026-07-30 当前 GREEN 与离线验证

- 运行时间：`2026-07-30 22:41 CST`；以下命令均在独立 worktree 本地执行，未访问公网。
- 编译：
  `python3 -m py_compile runtime/research/collect_graded_race_participants.py
  runtime/research/test_collect_graded_race_participants.py
  .codex/scripts/test_graded_race_participants_workflow.py
  .codex/scripts/check_workflow_contract.py
  .codex/scripts/test_workflow_contract.py`；结果：通过。
- 聚焦 GREEN：
  `python3 -m unittest runtime.research.test_collect_graded_race_participants -v`；
  结果：`83 tests / OK`。第一至第二十轮 findings 修复后的 `32/32`、`39/39`、`46/46`、
  `49/49`、`53/53`、`56/56`、`60/60`、`64/64`、`66/66`、`69/69`、`70/70`、`71/71`、
  `73/73`、`75/75`、`76/76`、`77/77`、`79/79`、`81/81`、`82/82` 仅作为历史轮次证据；
  当前新增 1 项回归覆盖 missing/controlled/uncontrolled 三态、非空未知 country 不回填、
  direct/search 与 review/errors fail closed，并继续锁定标准五地区 missing 例外及
  AU/DE/Middle East 未放宽。
- workflow 静态合同：
  `python3 .codex/scripts/test_graded_race_participants_workflow.py -v`；
  结果：`11 tests / OK`。除显式请求预算外，合同验证 discovery/request ledger 随整个
  races stage、profile request ledger 随整个 shard artifact 上传和精确路径恢复，并验证
  workflow timeout 留有 post-step 余量、README 明确 hard cancellation 限制；本轮还验证
  `evidence_gap` 继续到 partial finalize、正确 races index 路径及完整离线 harness；其余仍覆盖
  离线 YAML、默认无公网 job、四分片 DAG、续跑输入、最小权限、checkpoint 和精确 7 文件上传。
- 现有 workflow 治理合同：
  `python3 .codex/scripts/test_workflow_contract.py -v`；
  结果：`26 tests / OK`。
- checker 直接验证：
  `python3 .codex/scripts/check_workflow_contract.py`；
  结果：`WORKFLOW_CONTRACT_OK`。
- synthetic 使用新建 `mktemp` 临时目录：首次执行
  `--year 2025 --stage synthetic_smoke --limit 1` 精确 exit `75`；随后以相同目录移除
  `--limit` 再执行，exit `0`，报告 `byte_equivalent=True`、`final_files=7`。最终目录精确为三份
  年度 CSV、`source_manifest.jsonl`、`summary.json`、`errors.json` 和 `README.md`。
- `git diff --check`：通过。

## 尚待验证

- PR #50 `tests` check 已 success（15 秒）。default `main` 的正式离线
  `workflow_dispatch` run `30555834994` 使用 head `d47dd513`、`full_network=false`，
  conclusion=`success`；`tests` job 13 秒，races/profiles/merge/finalize 按设计 skipped。
  artifact `30555834994-1-synthetic-checkpoint-0`（`12957` bytes）已核验包含
  `run_manifest.json`、synthetic report 和 final 严格 7 文件。
- 尚未执行 `workflow_dispatch full_network=true` 或任何其他联网 collector run；因此没有
  真实年份、赛事数、参赛马数或名称完整性结论。
- 生产服务器只读 preflight/health 验证通过，但 HEAD 仍为 `be1c89bf`；本变更未 pull、重建、
  重启、迁移、写 DB 或备份。服务器未更新是本次 GitHub-only 部署的预期边界，不是部署失败，
  也不得被写成服务器已部署新 HEAD。
- 独立代码 reviewer 第十九轮 `APPROVED` 仅为历史快照；第二十轮和第二十一轮
  `REVISE（P2=1）` 的 findings 修复后，第二十二轮最终确认已
  `APPROVED（P0/P1/P2=0/0/0）`。随后用户授权并完成 Git 发布和离线 deployment；正式
  `full_network=true` run 仍需单独授权。
