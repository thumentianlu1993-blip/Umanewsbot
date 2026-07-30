# 项目状态文档

## 2026-07-30 单年度八地区分级赛研究执行面已离线发布

- `collect-yearly-graded-race-participants` 方案已通过同一独立 reviewer 三轮审核。计划把旧
  研究分支的固定 2026/五地区/前五名/Wikipedia 流水线改为显式单年度、八地区、全部实际参赛马、
  中日英名称、无 Wikipedia/Wikidata，并保留 checkpoint 和精确恢复；当前离线候选已经实现。
- 新增地区使用 SHA 绑定的年度 URL classification manifest；未知赛果状态和 generic `other`
  profile 均 fail closed。第一至第二十轮 findings 修复后的 `32/32`、`39/39`、`46/46`、
  `49/49`、`53/53`、`56/56`、`60/60`、`64/64`、`66/66`、`69/69`、`70/70`、`71/71`、
  `73/73`、`75/75`、`76/76`、`77/77`、`79/79`、`81/81`、`82/82` 为历史轮次；当前离线
  复验为 collector `83/83`、
  workflow 静态合同 `11/11`、
  现有 workflow contract `26/26`；synthetic 首次 exit `75`，同目录续跑 exit `0`、
  `byte_equivalent=True` 并精确生成 7 文件。
- 独立代码 review 首轮为 `REVISE（7 P1 + 4 P2）`；findings 1–11 已全部完成
  本地修复与上述离线复验。P2-11 的历史实际命令已恢复，checker 只识别明确标注为旧规则、
  非执行性的精确历史记录，当前命令门禁没有放宽。同一 reviewer 第二轮限定复审仍为
  `REVISE（2 P1 + 3 P2）`，resume 累计预算、暂定赛果门禁、受控别名、搜索分页和逐地区
  coverage 五项均已修复。同一 reviewer 第三轮仍为 `REVISE（4 P1 + 2 P2）`；write-ahead
  ledger、详情地区二次核验、人工审核赛果、provisional error/coverage/outcome、HTTP 错误分类
  和 `errors.json` 名称完整性六项均已修复。同一 reviewer 第四轮仍为
  `REVISE（3 P1）`：pending conflict non-final、profile 缺真实详情名禁止 fallback，以及
  provisional 终态 `evidence_gap` 继续正式 DAG 并产出 partial 7 文件；workflow 同步接受
  `evidence_gap`、修正 races index 路径并新增完整离线 harness。上述三项均已本地修复。
  同一 reviewer 第五轮仍为 `REVISE（1 P1 + 3 P2）`：真实 `HttpClient` 严格允许受控
  `/horses/?q=&page=`、coverage error 优先、unresolved 错误保留 region/country/source URL、
  空 CSV 固定表头。四项均已本地修复。同一 reviewer 第六轮仍为
  `REVISE（1 P1 + 1 P2）`：受控 ISO alpha-2/alpha-3 国家代码归一化；全部未知状态行形成终态
  `evidence_gap`、保留逐行证据并由完整 DAG 产出 partial 7 文件。两项均已本地修复。
  同一 reviewer 第七轮仍为 `REVISE（2 P1 + 2 P2）`：index/request ledger 权威且 progress
  可安全重建；共享 profile URL 逐 occurrence identity 校验；`region_unresolved` 进入
  source/errors/partial coverage；Middle East 同 region 仍逐 country 冲突检查。四项均已本地
  修复。同一 reviewer 第八轮仍为 `REVISE（2 P1）`：统一 stage monotonic deadline；
  `discovery_progress.json` 精确 checkpoint/resume queue、visited、discovered、inflight 与请求
  计数；profile 分页检查 deadline 且后续页 404 fail closed。workflow 合同同步锁定
  discovery progress/request ledger 在无 manifest 时仍上传恢复。修复已本地验证。同一
  reviewer 第九轮仍为 `REVISE（P0=0 / P1=0 / P2=1）`：discovery retryable 错误重试耗尽后
  保存 progress/ledger 并 exit `75`，resume 从 inflight URL 精确继续；确定性 4xx 仍为
  permanent。唯一 P2 已本地修复。同一 reviewer 第十轮仍为 `REVISE（2 P1 + 1 P2）`：
  sitemapindex/urlset 类型与目标年份过滤；generic `other` profile 多语 alias 交集加附加
  identity；coverage 只由实际 in-scope graded 证据驱动，Listed-only 不得 `covered`。三项均已
  本地修复。同一 reviewer 第十一轮仍为 `REVISE（P1=1）`：AU/DE generic `other` 可由 alias
  交集加出生年份满足附加身份；若详情存在 country 则必须一致；Middle East 仍强制 country。
  唯一 P1 已本地修复。同一 reviewer 第十二轮仍为 `REVISE（P1=1）`：direct/search 共用公共
  group validator，逐 occurrence 校验 alias/region/country/birth year，任一冲突整组
  fail closed 并保留 review。唯一 P1 已本地修复。同一 reviewer 第十三轮仍为
  `REVISE（1 P1 + 1 P2）`：canonical group 全 aliases 确定性多 query、候选 profile URL 去重；
  冲突 error 保留 expected/actual 双侧 aliases/region/country/birth，以及
  profile URL/conflict fields。两项均已本地修复。同一 reviewer 第十四轮仍为
  `REVISE（1 P1 + 1 P2）`：profile URL 全链路严格 canonical trailing slash；Middle East
  country missing/uncontrolled/mismatch 均保留 expected/actual raw/canonical 事实和明确 reason。
  两项均已本地修复。同一 reviewer 第十五轮仍为 `REVISE（P1=1）`：profile URL 以原始 path
  只接受正整数真实路由，拒绝重复 slash、slug、dot/编码绕过等，synthetic 同步改用合法数值
  ID。唯一 P1 已本地修复。同一 reviewer 第十六轮仍为 `REVISE（P1=1）`：验证器不得先做
  NFKC 或 trim，必须基于原始 `str` 拒绝 Unicode whitespace/control、全角字符、
  percent encoding 等绕过，只接受 ASCII 正整数 profile 路由，并在全部身份入口一致执行。
  唯一 P1 已本地修复。同一 reviewer 第十七轮仍为 `REVISE（2 P1）`：所有 profile URL
  原始字段不得预先 normalize；HTML profile `href` 必须由严格 resolver 在拼接前校验；
  HTTP profile 请求须禁用自动 redirect，对原始 `Location` 严格解析并限定同 host，final URL
  也须直接严格校验。两项 P1 已本地修复。同一 reviewer 第十八轮仍为
  `REVISE（P1=1）`：absolute profile href、redirect `Location` 和 final URL 必须与对应
  来源页面或原始请求的 hostname 精确一致，allowlist 内的 bare/`www` hostname 也不得互换。
  唯一 P1 已本地修复。同一 reviewer 第十九轮已 `APPROVED`，P0/P1/P2=`0/0/0`，session
  `019fb2f6-da26-7463-81b3-0b3c52ed4cf0`；审阅时 fingerprint
  `89a8021db567eaaed7003680cd85377ca04ec7ee08d48168ef3212cbcb51d262`、content manifest
  `cfb5630c1dc29a0d04b62816a4ce2f296640308e838614d96d57af2d6fbce0a1`，pre/review/post
  均 exit `0` 且只读。该 fingerprint 仅标识第十九轮历史审阅快照，不代表当前候选已批准。
  同一 reviewer 第二十轮最终确认仍为 `REVISE（P2=1）`：标准五地区的 profile region 明确
  匹配时允许 country 缺失，但存在 country 冲突仍 fail closed；AU/DE/Middle East 不放宽。
  唯一 P2 已本地修复并纳入历史 `82/82`。同一 reviewer 第二十一轮最终确认仍为
  `REVISE（P2=1）`：country fact 必须区分 missing/controlled/uncontrolled，非空未知值不得由
  region 回填且须 fail closed；标准五地区仅 missing 可按明确 region 通过，AU/DE/Middle East
  不放宽。唯一 P2 已本地修复并纳入 `83/83`。同一 reviewer 第二十二轮最终确认已
  `APPROVED（P0/P1/P2=0/0/0）`，session
  `019fb360-79a8-7aa0-8064-b5a604bc7c7e`；pre/review/post=`0/0/0`，approved parent
  `6d073dc07cb29201bbc922255923820c872a0467`，approved fingerprint
  `21a32cf22ef48207d44880d21ec2059ccdd711fe6758a80ee60cb069277f61ce`，content manifest
  SHA-256 `35672bc11172cd5ca7372da53d3ff38de7d31157c952361822c55de27adeffb1`。
- 用户已授权 Git 发布与本变更生产部署。feature commit
  `34626865d5cfe336a97fd7a375238e76c8afbec2` 经
  [PR #50](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/50) 合并为
  `main@d47dd513e666874243815c2feee7cc755ce483ba`；PR tests success（15 秒）。
  default `main` 的
  [离线 dispatch 30555834994](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/30555834994)
  在 head `d47dd513` 上 success，`tests` job 13 秒；网络 DAG 按
  `full_network=false` 设计 skipped，synthetic artifact `30555834994-1-synthetic-checkpoint-0`
  为 `12957` bytes，含 run manifest、report 和严格 final 7 文件。
- 本变更生产部署定义仅为 GitHub research workflow 进入 default `main` 并成功离线 dispatch。
  生产服务器 `/opt/umanewsbot` 仍为 `be1c89bf` 且存在长期 dirty deploy scripts/运行产物；
  健康检查通过，但未 pull、重建、重启、迁移、写 DB 或备份。不得宣称服务器 HEAD 已更新。
  `full_network=true` 未授权、未执行。

## 2026-07-30 Celery race-live P0 已完成关闭态发布

- 初始 `start-beat` 因 Django auto-import banner 污染严格 queue snapshot，在真正启动 Beat
  前 fail closed。final fix 使用 `shell --no-imports -c` 且不放宽 parser，部署合同
  `33/33`、四组聚焦 `64/64` 通过；限定复审 `APPROVED` 和
  `INDEX_TRANSITION_OK` 后，commit `24a49c2a` 经 PR `#47` 合并为
  `main@be1c89bf`。
- 生产重新完整执行 `prepare`：Django check、historical runner preflight、两次 migration
  plan `0/0` 与关闭态 settings 全通过；最终 image 为
  `sha256:c3197503...b5f5`，本窗口 rollback tag
  `umanewsbot:rollback-race-live-p0-20260730T043615Z` 指向上一候选
  `sha256:17562c52...acea7`。
- `start-beat` 五轮全部通过。`race_live=6574 / selector=0 / monitor=6574` 相对启动前
  基线每轮不变；普通 `celery` 队列为 `36/35/30/28/30`。最终生产
  HEAD=`be1c89bf`，web/worker/beat image 一致且运行；`race_live_worker=Created`，
  flags 与两个目标 schedule entry 保持关闭，目标 Beat 日志计数 `0`，普通 worker 只监听
  `celery` 且 ping 正常。
- 终验队列为 `celery=23 / race_live=6574`，内外 HTTP healthz 200、OneBot running、
  最近 15 分钟无 OOM；没有清理、迁移、消费或重放历史 `race_live` 积压。临时 2 GiB swap
  仍启用且全空闲，最终 `MemAvailable=1576148 KiB`，资源余量很窄；swap 移除仍须单独授权。

## 2026-07-30 Celery race-live P0 部分部署停在安全检查点，修复待复审/重新授权

- 初始实现 `611c6aab` 已经 PR `#46` 合并为 `main@7cd144ab`；生产仓库从
  `4221affa` fast-forward 到 `7cd144ab`，既有 `12` 个 deploy 脚本 mode-only dirty
  差异保留。
- 生产预检为 Compose `5.1.2`、flags `false/false/disabled`、
  `race_live_worker=Created`、`celery=0`；首次 active/reserved/scheduled 均为 `0`。
  `race_live` 从 `6055` 增至 prepare 前 `6574`，全部是 monitor task。
- `MemAvailable=867284 KiB / SwapFree=0 KiB` 首次触发 NO-GO。经额外授权创建并启用
  `/swapfile-umanews-p0-20260730`（`2 GiB`、`0600`、不写 fstab），空闲普通 worker
  优雅重启；临时停止的 OneBot 已恢复 running。
- `prepare` 已成功：drain active `2→0`，rollback tag
  `umanewsbot:rollback-race-live-p0-20260730T030255Z` 绑定旧 image
  `sha256:7d730634...8774`，候选为 `sha256:17562c52...acea7`；两次 migration `0`，
  settings closed，web/worker/nginx 与内外 healthz `200`，Beat exited，
  `race_live_worker=Created`。
- `start-beat` 在 `up beat` 前因 Django 的
  `105 objects imported automatically...` 污染 machine snapshot stdout 而 fail closed。
  OneBot 已恢复 running，Beat 仍 exited，队列后验 `6574`，五轮观察未开始；发布未完成。
- 本地 final fix 只增加 `shell --no-imports -c`，parser 不放宽。部署合同
  `33/33 / 56.236s`、四组聚焦 `64/64 / 57.693s`，均 exit `0`；Django、迁移、shell 语法
  和 diff 门禁通过。当前必须由同一 reviewer 限定复审并重新取得发布授权，再拉取 final
  fix、重跑 `prepare` 构建最终 image、执行 `start-beat` 五轮；禁止热补丁或手工启动 Beat。

## 2026-07-29 赛事新闻质量治理已上线（默认关闭 + shadow）

- PR `#42`（实现 `497590e0` + main 合并 `7ad0994a`）已合并部署，生产 checkout
  `main@8440b897`；migration `0063–0066` 已应用，`web/worker/beat/nginx` 全部恢复。
- 代码经十轮限定复审收敛至零开放问题；部署验证：Django check、迁移零漂移、
  公网首页/healthz 200、所有新开关保持默认（enforce 全关、shadow 全开）。
- 部署插曲：主机内存压力致部署脚本 exit 137，collectstatic 与 worker/beat 由人工补跑完成，
  nginx 上游缓存导致短暂 502 已随 restart 恢复；详情见 deploy_runbook 部署记录。

## 2026-07-28 赛事日历默认比赛日窗口已上线生产

- `fix-race-calendar-default-date-window` 根因是自然日 ±30 天与前 40 场截断共同造成陈旧
  日期轴；已按已审方案实现：上海时区今日锚点（今日→最近未来→最近历史）、最多 11 个
  实际比赛日的 5+1+5 平衡窗口、保留 40 卡上限且每日期至少一卡、移动端锚点
  `scrollLeft` 水平居中；显式 cursor/year/q 语义不变。无迁移、无配置、无数据写入。
- 测试先行取得真实 RED 后实现 GREEN：新增 41 个聚焦用例全通过；既有日历测试窄改
  预算断言（10/14/22）与 A6/A8 适配；主线程回归、查询预算（+2 条有界聚合，实测
  5/14/14）与 1440px/390px/320px 真实浏览器验收均通过。
- 复审与发布：两轮独立代码 review（首轮会话 + 全新 Codex 会话
  `019fa932-ca46-7b23-a2d6-c9fc9381cca7`）共 3 项 P2 修复后均 APPROVED；用户针对冻结
  fingerprint（approved content hash `632eb5258c…b66e57`）明确授权发布，
  `INDEX_TRANSITION_OK` 后合并 PR `#43` 为 `main@c8508b4e` 并部署生产。生产验证：
  内外 healthz 200，`/races/` 日期栏 11 个实际比赛日、当天 2026-07-29 为唯一锚点，
  显式模式不变，390px/1440px 浏览器正常，零迁移零业务数据写入。事实证据见
  `docs/changes/fix-race-calendar-default-date-window/release_report.md`。

## 2026-07-28 定时赛果审核已上线，自动来源发现仍未闭环

- PR `#39` 与补跑 JSON 窄修 PR `#40` 已合并并部署，生产为
  `main@ca22c9fa`；migration `0062`、持久卷、Beat 双时点和 Codex 同 slot 备用触发均已启用。
- 首次 run `26` 已生成并发送 bundle `07e7f223…f4d47`，重复运行命中
  `already_claimed` 且没有重复邮件；赛果行数和赛事状态计数未变化。
- 首轮 13 场均因 `route_missing` 阻断，候选为 0。当前状态不能宣称“自动收集完整赛果”
  已验收；下一步必须补齐通用来源身份发现和官方/受控参考 route，之后重新 prepare，
  以 `candidate > 0`、完整数字名次和 `blocker=0` 作为产品闭环证据。

## 2026-07-27 赛果 gap-v2 唯一 blocker 已完成本地窄修

- 正式只读 prepare 已取得 40 场候选、319 条数值名次，39 场完整；唯一缺口是 event 80
  的 JRA 官方 `中止` 被旧代码误判为未知缺马。
- 本地修复将 `中止` 保留并规范化为 `pulled_up`，不生成数值名次；受控非完赛状态计入
  参赛者守恒，`Also Ran/unknown/declared` 仍 fail closed。赛果恢复模块 `40/40` 通过。
- 当前仍未提交、PR、部署或重跑正式 prepare，生产赛果零写入。下一步是独立复审与发布，
  然后在新授权下重跑 prepare，确认 40/40、`blocker=0` 后再生成生产写入审批包。

## 2026-07-27 P0 URL 定时任务已重新启用

- 后续部署曾把 P0 开关恢复为关闭，导致当日 `18:30` 自然调度未运行；现已在用户精确授权下
  以生产 `5fed1a96` 恢复 worker/beat 开关并补跑一次。
- 补跑成功，`TaskExecutionLog=3`，当前 generation 为 `19679c03…8612`；BHA 日期索引
  仍为 3，Equibase 两个目标仍连接失败，精确 found 仍为 0。
- 五张赛事业务表更新均为 0，Django check、artifact verifier 和内外 healthz 通过；下一次
  自然调度为上海时间每日 `06:30/18:30`。

## 2026-07-27 P0 官方出马页 URL 发现已生产启用

- `main@cfba7151` 已部署，worker/beat 的
  `P0_RACECARD_URL_DISCOVERY_ENABLED=true`，上海时间每日 `06:30/18:30` 运行。
- 两次受控运行均生成可验证的持久化 generation：当前未来目标 6 场、时间不足 orphan 5 场；
  BHA 日期索引 3、精确 found 0、暂无 8。任务未写赛事/出马/赛果业务表。
- Equibase DMR/CNL 在生产香港网络连接超时，当前为 fail-closed 降级；调度继续低频重试，
  不把这两场报告为成功或已确认 URL。France Galop、日本、香港及 NAR 继续保持既定
  provider 门禁。
- 生产 healthz、Django check、artifact verifier 通过；两个恢复点均为 `0600`。详细证据见
  `docs/changes/schedule-p0-official-racecard-url-discovery/release_report.md`。

- 2026-07-27: 已在 `main@cfba7151` 上建立草稿 PR `#33`，完成非 JRA recovery mode、target
  `event_id` 回传与全来源完整名次 fail-closed 修复；新增门禁覆盖缺参赛名单、缺马、重复身份、
  无效名次及 discovery-only。首轮固定 head `1b11f985` 独立复审返回两个 P1：英美
  Sporting Life 标准输出覆盖、coverage 未绑定受控 combined artifact/target 来源；两项已补
  RED 并在同一分支修复，相关回归 `141 passed / 1 skipped`、OpenSpec `38/38` 通过；同一
  reviewer 对固定 head `c4ce802c` closure review 为 `APPROVED`、无 findings。Eddie Read 完整候选顺序
  已由 Racing Post 与 DRF 交叉确认，但 Del Mar 官方 chart 尚不可用，仍不得 confirmed。
  PR 尚未合并、发布或部署，生产状态不变。
- 2026-07-27: 用户授权后已写入 event `426` 的 Del Mar 官方 post time
  `2026-07-27T01:10:00Z`，不含赛果写入。新 inventory 仍为 59 行/50 组和精确 40 场缺口；
  一次性 prepare 实际使用 `12/75` 请求，仅 4 场 JRA 形成赛果候选。Sporting Life/ZEturf
  因 scheduled 过滤静默空跑，TOBA 返回 403，故 task 4.3 仍未完成。Eddie Read 人工复核前四
  为 Gold Phoenix、Cabo Spirit、Formidable Man、Stay Hot，但尚未进入受审 candidate/receipt。
  常驻开关仍全关，生产赛果仍零写入。
- 2026-07-27: 联网 prepare 阻断修复已由 PR `#30` 合并并关闭态部署到
  `main@e2ae3efe`、镜像 `sha256:e0a2d3d6…61a3`。联网 prepare 的
  recovery expected-target、source-scoped adapter input 和 JRA list/受控请求上下文已在独立
  分支完成测试先行修复；两轮复审的 4 个 P1 已修复，包括强制当前
  `source_map_version` 与精确 40 场映射，受影响范围
  `100 passed / 3 skipped`；同一原生只读 reviewer 已对 fingerprint `db0e38b2…5135`
  给出 `VERDICT: APPROVED`。四个应用容器统一镜像，race-live worker 停止，网络、scheduler、
  monitor、lifecycle、historical backfill 与 publication policy 全关闭；本次未运行 prepare，
  candidate/source cache 和赛果业务写入仍为 0。
- 2026-07-27: 赛果恢复 PR `#28` 已关闭态部署到生产 `dfbd24e1`，迁移 `0060` 与
  59 行/50 组只读 inventory 通过；有界联网 prepare 因 recovery plan 的
  `expected_target_empty` 实现缺口在 transport 前阻断，请求数为 0，尚无候选或赛果写入。
- 2026-07-26: 赛事新闻质量治理代码实现完成，待独立代码 review 和发布授权。
- 2026-07-24: 首页人工头条与 AI 编辑推荐控制代码实现完成，待独立代码 review 和发布授权。

## 2026-07-27 赛果缺口恢复方案

- 生产 inventory 已精确确认 59 条 event row 对应 50 个 race group；分类为 40 missing、
  9 duplicate-zero、9 duplicate-confirmed 和 event 924 一条 provisional。
- 方案采用双层 inventory、结果专用编排、人工官方路由、projection owner/revision arbitration、
  `RaceEventProductCanonicalLink`、精确 SHA apply/rollback 和 `blocker=0` 完成定义。
- 代码与空表迁移已部署，全部相关运行开关关闭，未写赛果。下一步不是绕过 runner 抓取，而是修复
  recovery event-ID snapshot/JRA 受控输入，重新 review 和发布后再取得新的精确联网授权。

## 2026-07-24 首页编辑控制方案审核通过，待确认实现

- `add-editorial-headline-control` 已在最新 `origin/main@10f341e6` 的独立 worktree 完成只读探索和
  `spec/design/test_cases/tasks/rollout`。
- 现状仍为算法化单头条；规划方案把人工唯一选择与 AI 编辑推荐分开持久化，人工有效时优先，否则保留现有
  72 小时/7 天/全部文章窗口与排序，并统一排除未来网页时间或空有效内容。推荐不会自动发布或覆盖人工选择。
- 前序公开导航/来源隐藏 change 已合入；本任务预计不改公开 headline partial 和 `public.css`，实现前仍须
  通过可恢复 stash 门禁 rebase 最新主干，并重新检查 `admin.py`、`views.py`、模板和测试重叠。
- 同一独立方案 reviewer 三轮收敛，首轮 6 项 finding 已全部关闭，最终
  `VERDICT: APPROVED`，无剩余 P0/P1/P2 finding。
- 已提供自包含 `docs/changes/add-editorial-headline-control/handoff.md`，后续 Claude 可从该文件恢复
  需求、设计、Git 基线、测试先行、subagent、review 和发布授权门禁。
- 当前未实现、未迁移、未发布；已停下等待用户明确确认实现。

## 2026-07-24 英文单词型马名语境分类已部署为 shadow

- CORE review 已基于 fingerprint `7ff685325de9…` 通过；PR
  [#14](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/14) 合并为
  `main@2a3c249f`，生产四应用统一运行镜像 `sha256:316e4563…`，无 migration。
- Django、migration drift、四类 HTTP 入口、Celery 两节点、容器镜像、外部导入锁和磁盘
  验收通过。article `9595` 的只读进程内 enforce dry-run 未产生 horse alert，正式译名
  `Logician` 保留，`Africa/East` 保持普通词；没有保存、重处理、通知或生产数据写入。
- 生产仍为 `ENGLISH_TERM_CONTEXT_MODE=shadow`，实际发布门禁尚未切换。启用
  `enforce` 需独立明确授权；deferred P2 继续由后续 change 处理。
- 完整发布证据见
  `docs/changes/fix-external-english-horse-context-gate/release_report.md`。

## 2026-07-24 P0 task 5.4 已完成

- 空胜绩窄修以 `044f3d57` 部署，正式 candidate `6dc853a2…`、artifact `b1e123fa…`、
  release `8c6f2dc8…` 已成功写入生产；61 匹全部严格完整，39 个 blocker 未进入。
- 实际新增 1,490 条履历、244 条模块审计、1 条 completion run、61 条 P0 source；profile、
  公开马和 OperationLog 净增均为 0。61 匹原本均已公开，因此新增公开为 0。
- 幂等重放剩余动作全 0；61 个公开详情页、healthz、日本马匹列表、四应用统一镜像和网络 false
  均通过。task 5.4 不再处于待写入状态。

## 2026-07-24 P0 task 5.4 空胜绩门禁已本地修复

- 只有 applied、approved、payload 精确为空且具有执行人/时间的 `major_wins` 证据可表达
  “确认无胜绩”；未审核、非空 payload 或 conflict 仍 fail closed。
- artifact/candidate 新增完整度策略版本绑定，旧 candidate `8ef0f718...` 在新代码下不可复用，
  必须重新生成 SHA 并重新授权。
- 本地关键测试已转绿；312 项组合中 308 通过，4 个失败与修复前基线完全一致；排除基线失败后
  最终 P0 相关集合 `247/247`，Django、迁移、OpenSpec `37/37` 与 diff check 通过。尚未独立
  review、push、部署或触碰生产。
- 冻结输入下预估净增：0 匹新马、1,490 条履历、244 条模块审计、1 条 completion run、0 条新
  P0 source、0 匹新增公开；61 个 profile 和 61 条既有 source 将更新/upsert。
- 两项审查 P1 已修复：不再接受 applied 的非空 payload 作为“无胜绩”，也不再让新 v2 策略
  破坏历史 v1 artifact 的只读复验；当前策略只在 v2 发布链路强制。
- 后续直接路径复审补齐 v1 只读边界和手工审核稳定性：v1 commit 在写库前拒绝；无胜绩马的
  手工 ready 审计继续保存空列表，后续完整度不会反转。生产链路 246 项与三项新增测试共
  `249/249` 通过。
- 用户表达了持续确认新 SHA 的意愿，但仓库发布门禁要求授权必须发生在最新成功 review 之后；
  review 成功后仍须请求当前任务发布授权。candidate 对象、动作或公开范围漂移则停止。

## 2026-07-24 P0 task 5.4 因“已审核无胜场”语义缺口安全回滚

- 精确 candidate 已生成唯一 v2 正式批准，但数据库事务在首个无胜场对象的 strict-complete
  复验处失败；61 行中共有 10 匹真实无胜场。
- 数据库整批零写、自动首发未运行、网络保持 false。正式 release SHA 为
  `5320c33c44d387b14e827b109353ffe5068d997bd9c62d9df903cb5de91e0c90`。
- 当前不能伪造胜场或跳过门禁。下一步需确认是否实施“approved empty major-wins 表示已核实
  暂无胜绩”的窄修；修复后必须重新 review、部署、prepare-release，并针对新 SHA 再授权。

## 2026-07-24 P0 task 5.3 生产候选已冻结

- `main@4972a6b2` 已部署，四个应用服务同镜像且马匹网络开关全部为 false。
- 已审核的 61 匹生成 release candidate
  `8ef0f718803f7772db5b498925a71651e5c68cb331aeafa50f03dc831f8848fe`；
  39 个 blocker 零命中。预计更新 61 份 profile、创建 1,490 条履历、upsert 61 条 P0 source、
  写 244 条 module audit。
- 61 匹当前均已公开，冻结自动首发范围为 0。重复 prepare-release SHA 不变、账本不重复；
  马匹业务表、OperationLog 和公开计数不变，未产生批准或正式 release manifest。
- 当前停在 task 5.4 前。任何数据库 commit 都必须取得针对该 candidate SHA 的新授权。

## 2026-07-24 P0 prepare-release service 并发边界返修完成

- prepare-release service 已补齐 `execution -> state` 锁顺序，锁内复读 manifest/state；direct caller
  与 command caller 现在共享同一 commit/abandon 串行边界。
- commit 或 abandon 完成后，等待中的 prepare-release 零写拒绝。新增 commit DB window 与
  abandon window 两项线程时序测试；P0 三模块 `270/270` 通过。
- 变更尚未提交、推送或部署，生产授权范围未扩大，仍需 fresh read-only review。

## 2026-07-24 P0 completed 重放证据链返修完成

- prepare/commit 同批竞态已由共享 execution lock 关闭；completed commit 重放改为在任何
  dry-run/DB apply/publish 前验证完整冻结证据和精确 v2 publish ledger。
- 成功重放为严格零写；账本缺失或计数不匹配时要求人工审计并保持 state/ledger/数据库不变。
  新增 3 项测试，P0 三模块 `266/266` 通过。
- 变更尚未提交、推送或部署，生产 task 5.3/5.4 边界不变，仍需 fresh read-only review。

## 2026-07-24 P0 重复 commit 发布幂等 P1 已本地修复

- completed publish 的相同 candidate 普通重放只返回冻结报告，不重新发布；publish 失败或未完成
  时普通重放拒绝并指向 `--retry-publish`。人工降级和 gate 放宽不会把一次授权变成再次公开。
- focused 3 项、auto-publish `72/72`、P0 三模块 `263/263` 通过；当前补丁未提交、未部署，仍须
  fresh read-only review。生产 task 5.3/5.4 授权边界未扩大。

## 2026-07-24 P0 task 5.3 已形成最新主线集成提交（待复审）

- 已把受审实现提交为 `ffa12214`，并显式合并
  `origin/main@97dd2350a193c74d5063bf7432a283e4d47f6d0a`，当前集成提交为 `8e3716bc`。
  合并仅在四份追加式文档发生冲突，双方状态记录全部保留，行为代码无冲突。
- P0 `263/263`、主线相邻 `90/90`（1 skip）、Django、迁移、OpenSpec `37/37` 和 diff check
  通过。完整 stable 对照为主线 `2784 / 21F / 67E / 59S`、集成
  `2882 / 21F / 67E / 59S`，新增 98 项且失败/错误/跳过增量均为 0。
- 用户已授权继续到无写入 task 5.3；当前仍未 push/deploy/bundle/prepare-release。必须先完成
  精确集成提交的原生只读复审；成功后部署保持网络 false，生成 candidate 后再次停下等待
  task 5.4 授权。

## 2026-07-23 task 5.3 发布候选门禁本地完成（待授权提交与部署）

- 用户已确认 `p0batch-20b59bda0608` 的 61 个完整对象可以继续，39 个 blocker 保持排除。
  本地新增 `--prepare-release`，可在零业务写、零公开、零正式批准事件下冻结 deterministic
  commit artifact、expected actions、publish scope 与精确 candidate SHA。
- 正式 rolling release 升级为 v2 并强制加载真实 candidate；通用 apply、batch commit、retry 与
  abandon 共享 supersede/abandoned/ledger/锁门禁。自动首发只处理 artifact 已复审且冻结为
  attempt 的对象，不再把整个 Japan 100 匹 manifest 当发布范围。
- 第十轮 full-diff review 的 2 个 P1 已完成 RED→GREEN：standalone v2 validation 到数据库事务
  全程持有可重入 execution lock；未落库时复验 current batch/combined SHA，只有精确
  artifact path+SHA 的 committed-run 可跳过 current 漂移并从不可变 snapshot 恢复。
- 相关 `260/260` 通过；完整 stable 相对 `21610ae8` 新增 88 项，最终对照为
  `2836 tests / 21 failures / 67 errors / 57 skipped`，failure/error/skipped 增量均为 0。
  Django check、迁移、OpenSpec `37/37`、diff check 通过。第十一轮 native full-diff review
  `APPROVED`，P0/P1/P2 为 0，session
  `019f901d-7b9f-77e3-96e0-792546d3eb4f`，审查前后 fingerprint
  `60cf62da1514f00fce451c89aa39b46146d20a4ef5245bdc84651a037559e164` 一致。
- 当前仍未 commit/push/deploy，生产网络 false，未运行 bundle/prepare-release，马匹数据与公开
  计数未变化。下一步先取得最终精确集成版本的提交/推送/部署授权；获批部署后仅执行无写入
  task 5.3，展示 candidate SHA 与清单并再次停下等待 task 5.4 授权。

## 2026-07-23 task 5.2 v3 精确触网验收完成

- 受审提交 `5eec316f073a3107d2887f724e95762f76f27ae2` 与当前生产
  `17d7757aec764755394339400eb2523eae896fa5` 已分叉。本轮以 revision label 固定的独立镜像
  `sha256:e543065ce08033b9d1b871478a85141c8b728334ec662bf6ea17fd2dcb1323f9` 执行批任务，
  未切换生产 HEAD、未重建在线服务。
- `p0batch-20b59bda0608` 通过 Japan 100/100 Netkeiba 唯一身份审核，批准 SHA 为
  `51ac349ebd45848abb89c9f29545e695a760d245e09e72fcecc0de4bfaefa44f`。prepare 发出 300 次
  8 秒节流请求，结果 61 完整、39 blocker：32 个候选身份期望字段不全、6 个来源履历证据不足、
  1 个生涯场次缺口。
- v3 核心验收通过：`unexpected_adapter_error=0`，旧误判
  `netkeiba_profile_structure/title_status/title_sex/title_color=0`。xlsx SHA-256 为
  `bee158e6d70c099c550102df6f9221b2d6bbb5fb75697d50a06d6d87b61cbc9f`。
- 未 bundle、未 commit、未自动发布，公开马保持 2797（日本 2463）。一次性联网容器已删除，
  宿主和四个在线应用的网络开关均为 false，healthz 通过。后续仍需人工审核 xlsx；任何 bundle、
  数据库 commit 或自动首发都必须绑定新 artifact/hash 再单独授权。
## 2026-07-24 HRN 新采集正文边界已部署

- 生产已运行 `main@0e4a3520`，四个应用服务同镜像；Django、migration drift、队列、日志和内外
  healthz 验收通过。
- `9623` 的真实来源页在生产镜像中只读解析为 `.article-body`，已知框架文本命中 0。部署后两个
  HRN 自然抓取窗口成功，但没有全新文章，Gate A 的新稿翻译/公开验收仍待自然样本。
- 自然重复抓取只更新了旧文章原文层；`9623` 的历史中文公开正文仍含污染，本次未重译或重处理。
  历史识别和历史修复继续是独立授权门禁。
- 发布证据：
  `docs/changes/fix-news-body-extraction-boundaries/release_report.md`。

## 2026-07-23 2026 赛事系列双卡片治理只读审核包已生成（待人工定稿）

- 已确认问题来自 2026 临时系列与历史系列身份断开，不是赛事中文名缺失。生产只读探索发现
  401 条 2026 target 尚未关联，其中 226 条为唯一名称匹配、11 条歧义、162 条无匹配、2 条未举办。
- 方案确定完整导出全部未关联总账，但首批只处理人工批准、证据完整且兼容既有引擎的唯一匹配项；
  其余保留为只读审核总账，不为清零放宽条件。
- 方案评审通过后已完成测试先行和本地实现：新增只读审核包生成/安全回读命令，复用既有身份归并
  写入引擎，不增加 migration、配置、调度或第二套 commit 路径。
- SQLite、真实 PostgreSQL 16 并发、等价规模、工作簿视觉、Compose 和完整套件主线增量验证均完成；
  独立原生只读代码 review 已通过。
- 提交 `17d7757a` 已推送并部署到生产，只读导出的五分类计数与探索基线一致：1,085 条
  target 中 684 已关联、226 唯一名称匹配、11 歧义、162 无匹配、2 未举办，异常 0。正式
  manifest SHA-256 为 `9d0df5da1e942f77bbabe9df7c84a921ea9325564ce821ab5f17ebf2f13eee47`。
  由于没有 identity-set digest，该计数证据不能排除集合等量替换。当前没有生成或应用任何归并
  decisions，也没有生产业务数据写入；下一门禁是人工审核工作簿。

## 2026-07-24 HRN 新闻正文边界已迁移至最新 main，等待复审

- 公开文章 `9623` 与 `9519` 已只读确认存在同源页面框架污染；根因是 HRN 适配器在页面没有
  `<article>` 时选择整个 `<main>`，而真实正文容器为 `.article-body`。污染发生在翻译前的详情解析层，
  不是公开模板拼接。
- 已从核对过的 `origin/main@d64c692` 建立独立 `codex/fix-news-body-extraction-boundaries` worktree，现已因
  上游前进而迁移至 `origin/main@45ded083`，
  完成探索和 `docs/changes/fix-news-body-extraction-boundaries/` 五份规格。计划复用现有正文清理、原始 HTML
  和离线 repair 能力，新增 HRN 来源级可信容器与只读历史候选识别。
- 独立方案 reviewer 首轮 findings 已在规格中修正，并由同一会话限定复审通过；审核后发现的 workflow checker
  直接路径也完成补充复审，T16 GREEN 与 `26/26` inventory 两项 P1 已关闭（最终 `VERDICT: APPROVED`）。
- 用户确认实现后已按测试先行和 subagent 文件边界完成代码：HRN `.article-body`、upsert 前失败阻断、只读历史
  scope、批准 manifest/hash 原子 repair 与八阶段 checker。正文边界 `43/43`、相邻抓取 `13/13`、workflow
  `26/26` 及 Django/static 检查通过。
- 独立原生 code review 首轮四项 P2 已按测试 RED 修复：扫描独立记账、风险状态/QQ 数、CrawlJob 详情失败数、
  manifest/SHA runbook。修复后全部本地验证继续通过，等待同一 reviewer 会话限定复审。
- 第一次限定复审确认两项关闭，并纠正 `CrawlJob.fail_count` 既有 duplicate 语义与 dry-run 审核证据缺口；第二轮
  RED/修复现使用 `detail_failures=N` 持久 token，并由同一 dry-run artifact 提供首尾摘要及全部审核状态。完整
  本地验证再次通过。
- 发布前 fingerprint 正确阻止了旧审核版本 staging；当前无生产变更。最新集成 review 发现 manifest 未绑定
  全部持久化输出这一项 P2，现已按有效 RED 升级为绑定标题、原始正文、标准化正文和解析元数据的 v2 契约。
  正文边界与相邻抓取回归 `58/58`、workflow `26/26`、Django check、compileall 和 diff check 已通过；
  仍须复用原 reviewer 会话复审，
  之后再取得当前精确版本的新发布授权。历史识别、历史重处理和代码部署仍是三个独立门禁。
## 2026-07-23 2026 赛历赛事中文名补齐已发布

- 发布时执行证据记录：573 场 2026 年已发布赛事的中文名已单事务写入，
  `written=573`、`veto=0`，写后 verify 通过；发布时全量复扫和五地区卡片核验未发现原文回退。
- 发布时详情页只保留 4 场抽查记录，低于 spec 要求的至少 5 场，该数量验收项未满足。
- 治理证据也不完整：历史 Claude Code「等价复审」不等于 Codex 原生只读 review；
  授权版本 `bd03b100` 与最终部署的 `6167b6c0` 不同，现存记录不能证明集成版本经合格复审
  并在此后重新授权。这不否定已发生的成功生产写入，但该治理门禁不可证。
- 本轮只复核公网 HTTP：`/healthz/` 返回 `{"status":"ok"}`，2026 赛历页抽样标题为中文；
  HTTPS 因本地代理握手失败未在本轮验证。
- 发布报告：`docs/changes/translate-2026-race-display-names/release_report.md`。

## 2026-07-23 publish_ready 积压治理已部署（历史清单已收敛，新 24 小时观察中）

- 已补发布资格时间，解决“文章入库超过 3 小时后才完成翻译/校验，发布窗口永远看不到”的根因；
  实时/积压双通道均有 200 条默认上限，同篇去重后继续走原门禁、评分和配额。
- 0–24 小时可自动消费，24–72 小时仅人工复核，>72 小时和历史无时间稿禁止自动公开；后台和
  告警均能看到积压年龄。历史处置使用 reviewer + decisions + SHA manifest，默认保持人工；
  已审核稿也可显式重新校验或标记 ignored，apply 不直接发布或发 QQ。
- 含舍弃动作的专项 20/20；此前合计 118 项相关/相邻回归完成。发现的 3 个旧测试数据缺少新
  资格时间、1 个后台查询预算回归已修正并复验。此前完整套件相对 `origin/main` 新增 19 项、
  失败/错误/跳过增量均为 0；PostgreSQL 16 的 1,000
  条积压测试为 2 条候选 SQL、0.456 秒。迁移往返、Django、Compose、OpenSpec 和静态检查通过。
- 生产已到 `7a6f30d8`，四应用统一镜像 `sha256:fa2fdf9bb952…`，`0053` 已应用。此前关闭态
  五区只读候选预览与零写入验收通过。香港单区 `17:45 / 18:00 / 18:15 / 18:30`
  四个真实窗口全部成功，无候选/无发布/无决策与地区配额写入，性能与抓取稳定。
  后直接扩到五区并通过首个自然窗口。首轮观察中 13 篇新鲜候选正常公开、最大 ready 年龄
  `0.625h`，但约 `23:00` 被并行 P0 容器重建打断，已按批准方案关闭积压通道并恢复运行态，
  因连续性失效不计为完整 24 小时通过。
- 用户确认的精确 21 篇已通过新增 `discard_ignored` 和 SHA manifest 全部收敛：快照漂移 0，
  首次 `discarded=21`，幂等重放 `already_applied=21`，最终 21/21 三层 ignored、公开 0、QQ 0。
  完整审计记录绑定 manifest SHA `860fbec26c89…`。
- 清空部署后到期抓取队列并排空 worker 后，五地区积压通道于 `2026-07-23 00:22:19` 重新开启；
  实际配置为五地区 allowlist、24h、limit 200，开启时五区 backlog 0、healthz 200。新的最终观察
  截止 `2026-07-24 00:22:19`，由 heartbeat `publish-ready-24-restart` 继续；5.4 尚未完成。

## 2026-07-22 新闻生产完整性修复进展

- 生产新闻 `public_slug` B-tree 索引已完成受控 REINDEX、三层验证和满 60 分钟生产观察：`77` 次抓取全部成功，同类索引错误 `0`，真实新增 `2` 篇、正常公开 `1` 篇，索引修复门禁正式 PASS。
- 条件终态、SHA manifest 收敛、滚动来源健康和 P0 告警已部署到生产 `HEAD=7ff968c0`，四个应用容器统一为镜像 `sha256:712a5da8…`。执行时 manifest `c4cc4f49…` 的 `32` 条全部安全收敛，stale started `32→0`；文章、公开、QQ 和来源最近状态前后不变，幂等重放更新 `0`，新 dry-run 为 `0`。部署后 60 分钟内 `61` 次抓取全部成功、新稿 `1`、新 stale/迟到覆盖/索引错误/异常日志均为 `0`；P0 信号和 6h 冷却生产实证通过。本 change 全部门禁 PASS，下一步进入 publish_ready 积压修复。

P0 马信息补全专项的模型交接文档见
`docs/p0_horse_information_completion_handoff.md`。后续接手应从该文档进入，并以
`docs/current_state.md` 和生产实时核验校正可能漂移的运行数据。

## 2026-07-23 netkeiba 第二轮返修进入代码验证

- 首个日本 netkeiba 批次现已 prepare 完成，但结果为 `27/100` 完整、`73/100` 阻断；
  未 bundle、未 commit、未自动首发。主要缺陷是 62 个已注销马标题使用 `抹消`；另有
  10 个部分 expected identity 预期阻断和 1 个证据不足履历行。
- 生产网络开关已实际恢复 false，web/Nginx/worker 与公开健康页通过；已公开仍为
  `2,797` 匹。旧批只保留证据，返修部署后 abandon 并重新 select/approve。
- 本地已实现 `抹消` 精确解析、字段级身份 blocker、parser version fingerprint/cache
  guard；首次独立 review 发现的 stale cache 无法覆盖 P1 已用 sidecar lock + 原子替换修复。
  同一 reviewer 连续复审已清零 actionable finding。修复随后重放到最新
  `origin/main@0dcdbdab`；集成候选的精确提交与内容身份由最终 base review 报告固定，
  不在提交正文中记录会因 amend 自失效的 SHA。P0 聚焦 `285/285`、OpenSpec `37/37`
  通过，完整 `stable 2741` 与主线基线 `2726` 的失败计数均为
  `21 failures + 70 errors + 57 skipped`。集成版本最终 review 以 HEAD `15645b05`、
  fingerprint `43313e31…2441` 通过并取得精确部署授权；生产已切换为该 HEAD 和统一应用
  镜像 `sha256:07f46301…176ef`。网络在 `.env`、四应用容器与 Django setting 均为 false，
  HTTP 验收通过，公开马计数仍为 `2,797/日本2,463`；本步未触网、未写马匹数据。下一步
  触网 prepare 仍需单独授权。

## 2026-07-23 netkeiba task 5.2 首次触网结果

- 首次受控 prepare 已完成并立即关网：正式批 `p0batch-5802d72da799` 使用 `300` 次请求，
  产出 xlsx，但只有 `45/100` 完整；`20` 条页面合法省略状态触发 `title_status`，另有
  `2` 条已知 `partial_career` 被误归为 unexpected，因此未通过验收并已 abandon。
- 未 bundle、未 commit、未自动公开；公开马仍为 `2,797/日本 2,463`。网络开关在宿主、
  四应用容器和 Django setting 均恢复 false，全部 worker、healthz 和日本马匹页正常。
- 本地已形成 parser v3 返修并通过四套件 `292/292`、OpenSpec `37/37` 和完整基线逐数
  对照；独立 review 修正 1 个真实 validator 包装路径 P1 后最终 `APPROVED`、0 actionable
  findings。尚未部署；task 5.2 仍未完成，下一次生产操作必须绑定新的受审精确版本。

## 2026-07-22 netkeiba 马匹客户端专项完成本地实现（未部署）

- OpenSpec change `add-netkeiba-horse-client` 完成 tasks `0.1-4.2`：`_NetkeibaClient`
  ID 直取（3 页/马，provider-bound 身份 + 四字段 + 完整生涯）、日本 dispatcher、
  select netkeiba 偏好、预算 3→4；解析全 fail closed。
- plan-eng-review 1 P0 与独立 code review 2 P1 全部修复；专项 25/25、补全套件
  266/266、完整回归与基线逐数一致；sqlite 端到端含自动首发全通。
- 剩余：tasks `5.1-5.2` 生产执行（分步用户授权）——部署后重跑首个日本滚动批次
  （触网 + xlsx 人工复审），核验批次自动首发，闭环 `publish-p0-horses-basic-tier`
  tasks 7.2；随后两 change 一并评估归档。

## 2026-07-22 P0 BASIC 层自动首发专项完成本地实现（未部署）

- OpenSpec change `publish-p0-horses-basic-tier` 完成 tasks `0.1-6.2`：BASIC 发布门禁
  （只信 verified provenance）、批次 commit 复验后自动首发（含 create_new、四通道
  审计、发布失败阻断 committed 终态 + `--retry-publish` 恢复）、存量发布命令
  （dry-run → 批准 → 分批 commit）、前台「资料补全中」徽章。
- plan-eng-review 2 P0 与独立 code review 3 P1 全部修复并回归；目标测试全绿，
  完整套件与分支基线逐数一致（14F+70E，零新增）。
- 剩余：tasks `7.1-7.4` 生产执行（分步用户授权）：部署 → 重跑已批准回填 manifest
  补 provenance → 首个日本滚动批次（触网 prepare）→ 存量发布 japan/hong_kong →
  恢复服务并归档评估。操作手册见 `docs/deploy_runbook.md` 顶部。

## 2026-07-22 赛事去让赛清理已发布并验收

- 提交 `5b491561` 随 `cce280a7` 部署：168 条去让赛清理单事务写入生产（19 赛历 +
  149 术语），kept 1550 / review 2 零改动，verify 与前台抽检通过。审核链：首轮复审
  REVISE（term 5087 混合标记 P1）→ 守卫修复 → 同一 reviewer 限定复审 APPROVED。
- 发布报告：`docs/changes/remove-handicap-markers-from-race-names/release_report.md`。

## 2026-07-22 P0 身份回填专项已完成本地实现与生产执行

- OpenSpec change `enrich-p0-horse-external-identity` tasks `0.1-6.5` 全部完成：四离线
  证据源统一候选、唯一强匹配 fail-closed 写入门禁、dry-run → 批准 → 分批 commit、
  冲突聚合与批量裁决建议通道、批次视角前后对比度量；`_participant_identity_keys`
  支持 `horse_url`/`horse_slug` 同源 ID 提取。独立 code review 的 1 P0 + 5 P1 已
  全部修复；专项测试 `57/57`，完整套件零新增失败。
- 生产已部署 `349c822f` 并经用户批准后写入：日本 2,462 netkeiba key（覆盖率
  0%→21.1%）、香港 327 hkjc key（385 匹 7.9%）、法国 1,773 条 zeturf 证据
  （4,097 条来源）、英美无新增；幂等与 sync 证据保留均生产实证；滚动批次日本
  前 100 匹抽样 100/100 带 key。执行记录见 `docs/deploy_runbook.md` 顶部。
- 后续方向：四字段数据源专项（生产 netkeiba ExternalHorse 无父母/出生日期，日本
  候选尚不能过批次四字段锁）；15,446 组 `needs_admin_review` 冲突的管理员治理；
  美国来源（HRN 仅 slug，需明确授权来源）。本 change 可评估归档。

## 2026-07-21 P0 滚动批次产品化已完成本地实现（未部署）

- OpenSpec change `productize-p0-horse-batch-completion` 已完成 plan-eng-review 与全部
  代码实现，覆盖 `complete-p0-horse-profile-data` 的 tasks `4.2` 长期版本：
  队列选批（默认 100/地区、500/批、无界 fail closed）、批次 manifest 人工批准 +
  append-only 台账、抓取 checkpoint/resume、按地区持久请求预算与 per-host 限速、
  瞬时失败有限重试、每批单独复审 xlsx（openpyxl 新依赖）、确定性 research v3 转换器、
  批准回写（美国滚动批次 fail closed）、滚动 release manifest 台账通道、
  每地区独立 commit artifact + 串行窗口 + 自动幂等复验。
- 端到端 sqlite 证据：select → approve → prepare → bundle → release → dry-run →
  commit → 幂等复验全通；专项测试 `82/82`，既有 P0 adapter 与赛事编排回归通过。
- 本 change 尚未部署生产、未触网、未写马匹资料；操作手册见 `docs/deploy_runbook.md`
  顶部。`6.7` 公开验收在其上线后立即单独执行；`complete-p0-horse-profile-data`
  仅剩 `6.7` 未完成。

## 2026-07-20 P0 首批五地区 50 匹生产数据已落地

- 首批五地区各 `10` 匹已按精确审核 artifact 完成生产提交：`50` 个完整档案、
  `1439` 条完整生涯履历、`50` 条 P0 来源、`200` 条模块审核；实际出赛
  `1432`、未出赛 `7`、海外出赛 `4`、实际出赛未知结果 `0`。
- 提交后幂等审计修正 `7` 条来源地区，现 `HorseP0Source` 五地区各 `10`；
  既有 `HorseProfile` 地区未覆盖。run 保留首次 `1739` 业务写入摘要，并单独保存
  `7` 条元数据修复证明；最终 dry-run 的新增/更新计划全部为 `0`。
- 生产当前运行 revision 为 `7ad6adeb`，镜像
  `sha256:af880cd208198c1e2ab960d8f39bd60539bdafa422cfb98890d0befbd90ff862`；
  数据库恢复点、Django/migration、内外健康页、Celery 和日志检查均通过。
- 本批没有创建普通比赛 `RaceEvent`，也没有自动发布马匹。当前 `25` 个待译马名继续保留
  原文；人工首次发布和公开页面验收尚未执行，不能把“资料已落库”写成“50 匹已公开”。
- 下一批暂继续五地区各 `10` 匹的滚动范围；完成首批人工公开验收后，再依据来源阻断率和审核
  负担决定是否扩大单批数量。

## 2026-07-20 历史节点：P0 Phase A 迁移失败已安全回滚

- 旧 `0049` 因同一 PostgreSQL 原子迁移内先数据更新、后 `CREATE INDEX`，触发
  `pending trigger events`；整笔迁移已回滚，生产仍停在 `0048`，旧服务已恢复。
- 修复后的唯一迁移链为 `0049` 字段 -> `0050` 回填 -> `0051` 索引/约束 ->
  `0052` authority/降级，全部保持原子；二次 Phase A 尚未执行。

## 2026-07-20 历史节点：P0 美国组合来源审核通过

- 用户/项目负责人已确认当前冻结批次的美国组合来源满足项目严格标准：HRN 主记录；
  Fort George 使用 HRN `6` + Sporting Life `6` + Racing Post `1`；Equibase 只用于官方
  总出赛数及身份、颜色对账。其余美国 `9` 匹为 HRN-only，美国合计 `198` 条逐场。该决定
  不等于 Equibase 官方逐场履历，也不全局放宽 HRN 或
  `count_aligned_records_unverified`。
- 三层状态必须分开：
  - 冻结 v1/v2 未修改：v1 SHA-256
    `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`，v2 SHA-256
    `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`；冻结 v2 保留
    原口径严格完整 `40/50`。
  - 审核研究层：pending 准备稿 SHA-256
    `8aba561b856ffbdcd03c2a59228b166315174b539f20aef4ae6412bfe03b1b61`，独立批准 manifest
    SHA-256 `29091d69573bab907cda2e9a081ae4684838b92d1f9b052a7601b6109a541077`，v3 研究派生物
    SHA-256 `98a7019a400f10a4bf961d869f38f770e9e98afab76b557a3c784d4eff6e470e`，研究层
    严格完整 `50/50`。research module review SHA-256 为
    `1440550a3e4d203b604b9dba74b89b2f49ee7075bc168f35e756e54830f31db1`。
  - 生产层：readiness report SHA-256
    `8cc36106091708827852401927a791a5575f2d6d490d1a306297e450612ed2c5` 仅为
    `static_schema_compatibility_check`，`safe_simulation_performed=false`、
    `commit_artifact_compatible=false`、`decision=blocked`、`database_write_count=0`。
- 当前 blockers 精确为 `not_horse_profile_completion_plan`、
  `missing_production_profile_ids`、`missing_production_reviewer_id`、
  `missing_commit_compatible_module_approvals`。正式 commit artifact 与 formal production
  dry-run 均未完成；无网络、无数据库写入、无部署发布，生产保持 **NO-GO / blocked**。
- prepare 只能输出 pending；apply 绑定固定 v2 SHA、可信 manifest SHA、调用方显式 SHA 和
  实际文件 SHA，记录、身份、来源、计数漂移或重复记录一律 fail closed。用户本次“继续推进”
  不构成生产写入授权。
- 本轮验证为工具与转换器 `48/48`、相关 Django `223/223`、Node `2/2`、OpenSpec
  `30/30`；Django check、migration drift、`git diff --check` clean，独立 reviewer 第三轮
  `APPROVED`。下方历史 `282/282` 继续作为旧轮次记录，不代表本轮重新运行。

## 2026-07-19 P0 马五地区 50 匹研究解析与三代血统补证

- 五地区各 `10` 匹已完成一次性只读研究解析和本轮人工审核返修，产出 `50` 匹资料、
  `2050` 条逐字段证据、`1439` 条逐场履历和 `2679` 条逐场字段三层证据；没有生产数据库写入、
  马匹发布或普通比赛 `RaceEvent` 创建。
- 五地区 13 个基础/三代血统硬字段均为 `130/130`。50 匹的父、母、父父、父母、母父、母母
  现为 `300/300`；其中原 `120` 个祖父母缺口由父母实体安全反查自动补齐 `89` 个、逐项人工
  证据补齐 `31` 个。法国/英国产地与育马者、中国香港精确出生日期与育马者共 `60` 个基础字段
  也已按严格身份锁补齐；应用前缺口快照被冻结，重复执行不得覆盖。
- 履历层当前为：日本 `200 records = 199 actual + 1 withdrawn / gap 0`；法国
  `250 actual / 11 official abnormal / 0 unknown / gap 0`；英国
  `412 records = 409 actual + 3 non-start / 10 official abnormal / 0 unknown / gap 0`；中国香港
  `379 records = 376 actual + 3 non-start`，其中 `4` 次 Overseas，来源总数缺口为 `0`。
- 数量对账已拆成“缺少实际出赛”和“多采/待去重”两个方向；本批两项均为 `0`，总差异为 `0`。
- 香港真实 `Overseas` 纯文本行已纳入并与下方重复表去重：SOUTHERN LEGEND
  `48 records = 47 actual + 1 WV`，其中 `3` 次海外；BEAUTY ONLY `47 actual`，其中
  `1` 次海外；TIME WARP `46 records = 44 actual + 2 WV`。三匹均与 HKJC 总数对齐。
- 法国 Sporting Life 的 `12` 条 `N/A` 已全部拆分并由 France Galop 官方公报补证为正式
  名次或 `arr/tbé/t.j`；Kentucky Wood `2026-05-30` 的 `arr` 按实际出赛未完成比赛计数。
  Sporting Life 直接展示、
  法国标准原始值和内部归一化值分层保存；Class/Grade 与英制距离不得无证据映射为
  Groupe/官方米制。
- 英国 Edwardstone 的 `2024-12-07 F`、`2024-03-13 F`、`2022-12-27 UR`、
  `2021-11-05 BD`、`2020-12-29 UR` 已从 `casualty.reason` 还原，全部按实际出赛未完赛计数。
  另 `8` 条 Sporting Life `N/A` 已核验为 `5` 条正式名次和 `3` 条未实际出赛；Paisley Park
  为 `33 visible = 31 actual + 2 non-start`，The New One 为
  `41 visible = 40 actual + 1 abandoned-meeting non-start`。
- 美国 `10/10` 匹 Equibase `Career Starts` 和毛色均已人工核验。HRN 原始 `197` 行合并
  `6` 条同场重复后为 `191` 次已采集实际出赛；Fort George 原缺 `7` 场已从 Sporting Life/
  Racing Post 结果页补齐，现全批 `198/198` 数量对齐、已知缺口为 `0`。但这不等于 Equibase
  官方逐场完整，全部美国样本仍为“数量已对齐、逐场官方性待确认”。禁止用浏览器绕过 Incapsula
  做生产爬虫，长期需要授权数据或人工 Full Charts/Lifetime PP。
- 当前严格完整门禁为日本、法国、中国香港、英国 `40/40`，总体 `40/50`；美国 10 匹不因数量
  对齐而进入逐场权威完整状态。
- HRN 正式 client、缓存复放和研究解析均要求马名、父名、母名、出生年份四项完整一致；同名
  slug、缺字段或出生年份不一致一律阻断。迁移会把权威状态未知的旧 `complete` 履历降为
  `needs_review`，并同步撤销 `complete_profile_full` 聚合完整状态；跨来源同场的正式赛果可补齐
  `unknown` 并重建标准/归一化证据，但不同正式结果仍保持冲突。
- source cache 已升级到 `v2`：所有地区都必须由缓存中的原始马名或 alias 绑定请求马，来源总数
  必须具备来源名、URL 和带时区核验时间。五地区网络 client 关闭自动重定向，只允许登记的
  JBIS、HKJC、Sporting Life、Geny、HRN HTTPS 主机，跨主机跳转在发出下一次请求前阻断。
- 跨 provider 资料补全必须由候选提供并匹配完整四字段身份，不能只凭同名或 alias；数据库
  生涯 evaluator 和整匹马 evaluator 都独立复核总数证据。研究 JSON/Excel 只对白名单
  `source_records_verified` 显示完整；官方总数为 `0` 时可保存空履历快照。
- 日本授权离线 replay 的 10 匹现全部真实重建并复算数量；同 provider 名大小写规范化后仍要求
  external ID 精确一致。总数 URL 使用 Django 严格校验；ignore 审计不会覆盖此前 APPLIED
  完整证据，conflict/pending 仍保持阻断。
- 普通未上名统一写入模型合法的 `unplaced`；年份精度履历可保留但不能通过完整门禁。人工基础
  资料、血统、逐场赛果、官方总数及佐证 URL 均使用严格 HTTP(S) 校验。
- 自动补充来源只有同 provider external ID 精确一致，或双方完整四字段身份一致时才能并入；
  审核 apply、source client 和数据库 evaluator 使用同一严格 URL 门禁。总数证据四字段原子
  更新，cache 硬字段验证类型和 ISO 日期，最终数量缺口优先按官方总数计算。
- 父母实体唯一同名结果不再自动采用；external ID 按不透明原值精确比较。旧 name-only 血统
  和 name + known sire 证据已升级为 `116` 行 manifest、`55` 个唯一父母来源身份；全部
  `source_identity` 现含马名、父名、母名和出生年。出生年来自
  `reviewed_by=codex_manual_source_review` 的独立 approved artifact，不是项目负责人逐字段
  审核 `55` 个出生年。对应 `89` 个补入字段与 `27` 条既有字段确认，旧 JSON/Excel 原字节继续保留。
- 冻结 v1 JSON / workbook SHA-256 为
  `55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd` /
  `4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`；最终 v2 JSON /
  birth-year evidence / parent identity manifest SHA-256 为
  `a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7` /
  `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54` /
  `b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b`。
- Kentucky Wood 的正确父系为 Racing Post `595446` 的 2001 年 Balko（Pistolet Bleu /
  Ella Royale）；旧 Netkeiba `000a02bd3f` 是 1925 年同名马，只保留在 v1。自动 Netkeiba
  父母候选使用严格详情 URL；工作簿 builder 默认 v2 输入/输出/预览并拒绝覆盖 frozen v1。
- 审核工作簿：
  `outputs/019f481e-4133-7f43-9844-e7a59b33ba9a/P0马五地区50匹完整解析与字段可用性审核-v2.xlsx`
  （SHA-256 `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`；
  人工证据应用 ID `3d5ab289cc5590e3cc405a4f28e532b98c86466f1b8da656e01183ca1fb2508c`）。
- 真实页面形状、模型/页面、50 匹产物最终化、字段身份消歧和既有完整档案整类回归已从
  `277/277` 增至 `282/282` 通过；Node summary/path、Django check、迁移无漂移、Python
  `compileall`、OpenSpec change strict 通过、all strict `30/30`、工作簿公式错误扫描和 `9` 张
  预览均通过。美国逐场官方性等剩余语义继续按
  `missing/partial/source_blocked/parser_gap` 保留，不猜值；生产仍为 `NO-GO`，没有生产写入、
  部署、发布或网络 career crawl。

## 2026-07-18 P0 马日本首批：网络重跑与无网络复放均为 10/10

- 审核候选 dry-run 已具备显式地区网络入口，并采用 CLI flag、CLI 冻结 SHA、服务端冻结 SHA
  与实际 manifest 字节门禁；三方 SHA 必须一致，manifest 在解析和创建 client 前绑定审核 CSV
  的 basename、SHA、大小和行数；
  未选地区保持离线，每个选中地区复用一个受控 client，按日本 `3`、香港 `1`、英国 `1`、
  法国 `2`、美国 `3` 的单马请求预算处理每区最多 10 匹。
- source payload 仍必须通过完整身份、硬字段、二代血统和完整生涯门禁后才能进入原子 cache；
  单马失败继续整批。manifest 与 summary 已补齐审核输入绑定、总体/地区网络请求和 cache
  hit/miss 统计，同时保持只读和数据库零写入；整批在 staging 校验、`fsync` 后原子发布。
- 批次入口 8 个合同与后续来源 blocker 分类合同均先取得真实 RED；当前
  `P0HorseSourceBlocked` 会保留异常类型、消息和请求数并归入来源错误，编程错误不受影响；
  地区 client 的请求计数由逐候选代理隔离，无效 cache 不会继承上一匹计数，底层只读计数
  属性也无需改写；请求预算逐马重置，限速时间跨候选保留。Docker `--network none` 下
  JBIS 只有 finish 为 `**` 且第 13 列精确为 `除外/取消` 时才保留为 non-start；赛事名、
  缺列或未知状态不得触发。transport 异常也在调用前记为一次请求尝试，并保留跨候选限速。
  source-client 为 `48/48（0.450s）`，四模块组合为 `102/102（1.040s）`；
  Django check、迁移无漂移、相关 Python 编译和 diff check 均通过。
- 日本 10 匹首批已在
  `runtime/horse_profile_completion/p0-reviewed-japan-network-20260718-083707/` 完成受控网络
  dry-run，manifest 为 `bf8dbda389e5ffc3b9efa1f361a8cbb7b8ad5392b2e1c11c86b25d8600db49e2`；
  该次历史结果为 `9/10 complete / 30 requests / 9 个新生成 cache / 0 cache hits / DB 0`。
  コントラポスト因 `22 actual + 1 除外` 的旧解析被阻断。
- 修复后重跑目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-network-rerun-20260718-091156/`，
  manifest 为 `9682ceebddb53a796ff058bb79a3455e89a4ad03b01ddeed7beed947dd1106b5`；
  日本为 `10/10 complete / 9 cache hits / 1 cache miss / 3 requests / DB 0`，未选地区请求数
  全为 `0`。コントラポスト保留 `23` 条履历，但实际出赛完整度正确记为 `22/22`。
- Docker `--network none` 复放目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-offline-replay-20260718-0913/`，
  manifest 为 `472785d50e5e6e7343d1ec0285cc68921a12ca7303556fa58dd21ffcc1af22c2`；
  日本为 `10/10 complete / 10 cache hits / 0 requests / DB 0`。当前首批总体为
  `10/50` 来源完整；task 4.2 继续未完成。
- 上述网络重跑与首次离线复放形成于审核 manifest 强绑定修复之前。加固后复放目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-hardened-offline-replay-20260718-094427/`，
  manifest 为 `4834e9f9f47b67a57bb1c11ee7cdc0b8338673b7e96d575a56ef1e5164332ecb`；
  它在 Docker `--network none` 中以网络门禁模式绑定冻结审核 manifest 与 CSV，日本
  `10/10 complete / 10 cache hits / 0 requests / DB 0`，最终目录完整且无 staging 残留；
  但它形成于外部冻结 SHA 信任锚修复之前，只是中间验证。
- 最终授权复放目录为
  `runtime/horse_profile_completion/p0-reviewed-japan-authorized-offline-replay-20260718-100440/`，
  manifest 为 `96ebef63ae74fa787ff786b262cebebc252f6e3c536c2aa89fc920c8d8e91210`；
  Docker `--network none` 中 CLI、服务端和实际审核 manifest SHA 三方一致，清单记录
  `authorized_by_setting=true`。日本 `10/10 complete / 10 cache hits / 0 requests / DB 0`，
  最终目录完整且无 staging 残留。
- 同一独立 reviewer 对本审计段落追加前的完整差异最终 `APPROVED`，无 actionable finding；
  approved HEAD 为 `c2c30aeed73619767c1ca6dfb440b43c8f824d11`，fingerprint 为
  `4dfaaaff01f38c5062a29a2225ac0f7fe8371d3ceccfd12e5182731cbaf99221`，reviewer stdout
  SHA-256 为 `0780293905b1c1cdd953a02bd2386c25902021709c9144b2c466bf93ad062631`，helper raw
  stdout SHA-256 为 `8a000524fd6228570e0ac2cb036d1d475e50701a3adb5806a5130cd91fbb632c`。
  旧 fingerprint 不覆盖这段随后追加的审计文字；该文字以追加后的限定只读复核为准。该批准
  不构成生产写入、发布或部署授权。

## 2026-07-18 P0 马真实来源：单马探针 1/5，批次闭环未完成

- 当前代码已离线兼容 Sporting Life、HKJC、JBIS、HRN 的保存真实页面 shape，并保留法国
  Geny 的 429/login/部分履历 fail-closed。cache 并发发布为同目录临时文件加
  `os.link` no-clobber，调用方最终重读 canonical cache。canonical cache 读写边界严格拒绝
  人工 outcome、人工 provenance、人工 supplemental source 和 raw manual rows；人工内容只在
  本批工作副本中存在。
- 历史 `66/66` 只属于合成 fixture scaffold，不是“真实客户端最终 GREEN”；相关实现者
  reviewer `APPROVED`/fingerprint 完成声明已撤销。当前候选已在真正的 Docker
  `--network none` 中完成 source-client `20/20`（`0.057s`）与四模块 `74/74`
  （`0.693s`）最终回归；Django check、迁移漂移、`PYTHONPYCACHEPREFIX=/tmp/pycache`
  下两个 service `py_compile` 和 `git diff --check` 全部通过。
- 首次真实探针曾为 `0/5`；修复后不落缓存、不写数据库的新鲜探针为 `1/5`。日本
  オーロラエックス从 JBIS 取得并通过 `15 starts / 15 records`；香港缺
  `birth_date/trainer_name/breeder_name`，英国缺 `country/breeder_name`，法国仍为 HTTP
  429，美国缺来源明确 `Starts`。后四项均为 fail-closed blocker。
- 首批 50 匹只是“审核纳入批次”，不是“资料已补全”；日本当前为 `10/10`，首批总体为
  `10/50`。
  任务 4.2 未完成，HKJC/Sporting Life/HRN 需要补充来源或人工字段，法国需解除 429 后受控复验。
- 同一独立原生 reviewer 已定向复审并 `APPROVED`，审前审后 fingerprint 一致，无剩余
  actionable finding。该结论只覆盖批准时的代码和既有 finding，不覆盖随后新增的状态文档，
  也不授权批量抓取、生产写入或发布。
- 后续人工补录加固已增加冻结输入与 outcome 的一一对账：候选、字段、完整证据指纹和状态必须
  唯一对应，`applied/already_applied/blocked/ignored` 之外的状态、缺失、重复、证据漂移及
  无输入旧 outcome 均在 staging 前阻断。canonical payload 同时只接受严格 JSON 类型，避免
  tuple 等容器在 JSON 序列化时变形后才暴露人工标记。迭代 validator 同时检测循环和最大深度，
  不泄漏裸 `RecursionError`；真实审核批次覆盖 tuple/set/非字符串键/NaN/Infinity/循环/过深
  7 类非法候选，并证明另外 3 匹继续及 cache 无临时残留。严格形状检查在 `deepcopy` 前执行，
  磁盘 JSON 解码的深度异常也包装为来源错误；1200 层内存对象和 cache 都不会泄漏裸异常。
  容器只接受精确内置 `dict/list`，字符串枚举等 JSON 标量兼容类型在校验后经 JSON round-trip
  规范为纯内置类型；异常或篡改型容器子类无法触发复制钩子。坏 cache 的原目录和逐文件字节
  在批次前后完全一致。规范化副本会再次检查人工标记，自动多来源和人工补录两个合并 helper
  也先规范化主 payload 与补充行，独立 canonical purity gate 同样检查规范化副本；欺骗型
  字符串值/键及异常/篡改型直接输入均阻断，实际 adapter 路径不落 cache。
  最新 source-client `68/68`、四模块 `123/123`，
  Django check、迁移无漂移、OpenSpec `30/30` 和 diff check 均通过。
- 同一独立 reviewer 第十一轮最终 `APPROVED`，无 actionable findings；审前/审后 fingerprint
  `9d2a7a276236306d3468e7a302df46e448ecfee257c64763db4700197edc8303`，reviewer stdout
  SHA-256 `b124808e0a93c4662687790b11f87dd192f29d9dff53692ff9383d96edb8ed8a`。该结论不改变
  当前 `10/50` 真实完成度，也不授权网络批次、生产写入、发布、合并或部署。

## 2026-07-18 P0 马首批完整资料补全

- 五地区各 10 匹、共 50 匹已由项目负责人全部确认纳入；审核 artifact 已冻结。
- 统一完整资料 payload、完整生涯履历 payload、离线批次 artifact 和模块审核审计已在 P0 worktree 完成本地实现。
- 首次空缓存 dry-run 为 `0 complete / 50 blocked`，网络请求与数据库写入均为 0；日本后续已
  通过受控网络和无网络复放达到 `10/10`，当前总体为 `10 complete / 40 blocked`。
- 当前不属于生产已上线能力。香港、英国、法国、美国的补充来源/人工字段、逐马人工复核、
  生产 commit 和公开验收仍未完成。

## 2026-07-18 P0 马候选提取：生产只读 5×10 样本已生成
## P0 马候选提取与完整生涯专项

- 已实现五地区重点赛事参赛马只读候选提取、强身份连通聚合、五地区人工样本和完整生涯独立状态。
- 候选提取不写术语、马匹、P0 来源或身份冲突；仅马名证据保持 `needs_identity_enrichment`。
- 历史生产只读样本为五地区各 10 匹；未因此授权资料网络抓取、生产 P0 写入或自动公开。

## 2026-07-20 五地区准实时 Beta Gate 修复已上线

- 冻结提交 `58f00961f2cd9750d1285f7d6229494903e975a5` 已进入生产；四个 app service
  统一运行 AMD64 image
  `sha256:f9681a60f5072c39ae7cc66bad9881e719a7d24698050b4ae57858f94b310eef`，
  `stable.0048`、Django check、migration drift、静态文件和 HTTP healthz 均通过。
- 写前数据库、环境和旧 image 恢复点已验证。新 root-only rollback manifest SHA-256
  为 `e6e3e1ef…609f5`；四层 maintenance、两次 validator、coarse restore 和 event
  restore 演练完整通过。event `924` 已恢复同一 provisional revision `2` 和 7 条赛果，
  tracking 继续关闭。
- scheduler/monitor=false、enabled regions 为空、active claim 和 race-live queue 均为
  0。event `924` 详情继续公开“暂定赛果”；没有扩大其他赛事。
- 法国 event `733–735` 的真实重验不再触发 coupled-entry
  `racecard_schema_invalid`，但只匹配 1/3，整批以 `racecard_not_found` fail-closed。
  因此未生成 manifest 或初始化法国；五地区自动轮询和全面公开仍未开启。本次完成的是
  已授权 Gate 修复代码发布与安全降级验证，不是五地区来源覆盖全部验收通过。

## 2026-07-19 event 924 kill-switch 演练完成

- event `924` 的预生成 disable 和 restore manifest 均重新完成
  dry-run/apply/verify，所有步骤 `ok=true`、唯一 event `[924]`、零网络请求。
- disable 后详情隐藏全部 live result 标识，日历保留赛事但隐藏赛果摘要；restore 后中文
  暂定标识、1–7 详情和日历前五摘要恢复。两次切换均保留 revision、publication、legacy
  result、observation、marker evidence 和 resolved incident。
- 最终 event policy 为 `provisional_public v4`，allowlist 仍只有 event `924`；
  scheduler false、tracking 停止、两个 Celery 队列为 0，live worker active/reserved
  为空，健康检查 200。当前灰度继续公开，未扩展其他赛事。
- event `924` 的 promotion 后 15 分钟新 probe 仍未发生，不能追溯补证。用户已决定由
  下一场获准公开灰度赛事重新执行该 SLA 验收；下一场未通过前不得把本次记录解释为
  15 分钟能力已验收。

## 2026-07-19 event 924 暂定赛果单赛事公开灰度首次上线记录

- 冻结提交 `91cf50ad677a1b8c9b253528c9db98481fd1031a` 已进入生产，四个 app service
  统一运行 image `sha256:700ea786…087ef`；`stable.0046`、健康检查和回滚点均已验证。
- QQ SMTP 真实投递成功后，event `924` promotion dry-run/apply/verify 全部通过。
  当前仅 event `924` allowlist 生效，四层 policy 为 `provisional_public v2`，
  scheduler 仍为 false，tracking 已停止，不会扩展到其他赛事。
- promotion 前 BHA 截图中的官方 1–7 名次与 TRA 暂定结果一致；其 receipt 在 promotion
  后应用并把 incident 写为 resolved，但截图早于 promotion，不能证明“promotion 后
  15 分钟内新浏览器探测”。该 SLA 验收仍未完成，页面继续明确标记“暂定赛果”。
- 首次上线收口点的详情页和日历 HTTP 验收通过；当时 disable kill-switch 只完成
  dry-run，尚未实际隐藏、验证和 restore。后续完整演练现已完成，结果见上方最新状态；
  historical runner 仍为 `migration_safe`，常驻历史开关关闭，race-live queue 为空。

## 2026-07-19 event 924 代码 review finding 已修复，待限定复审

- 候选变更基于当前 `origin/main@353464c7` 的独立 worktree，实现 event `924` 已存
  shadow result 的无网络 promotion、精确 disable/restore、页面“冠军 · 暂定”、客观
  racecard fallback，以及 BHA manual official receipt 的 match/conflict/unavailable
  闭环。
- operator promotion 与 runner 复用同一 admission core，但不伪造 claim/checkpoint；
  policy、allowlist、projection、incident 和 tracking stop 位于同一事务。scheduler
  默认仍为 false，Compose 没有增加 worker 或扩大赛事范围。
- 首次独立 code review 结论为 `REVISE`；2 项 P1、1 项 P2 已完成真实 RED/GREEN：
  receipt 硬限 event 924、unavailable 真实邮件 SENT/FAILED/retry、manual dry-run/apply
  共用 locked planner。随后两项直接 P1 也已用真实 RED/GREEN 修复：告警按 incident 跨
  receipt 去重；probe/receipt operation/QUEUED intent 先原子 commit，SMTP 后置于独立
  delivery transaction，主事务晚期写入或 commit 失败均零 SMTP。
- SQLite 合并聚焦 `226` 项（`224` 通过、`2` 项 PostgreSQL-only 跳过）；PostgreSQL
  durable intent/并发新增 `2/2`、既有锁/竞争 `22/22`；migration `0046` 往返、
  Django/migration drift 和三份 Compose 校验均通过。
- 这是“全部已知 finding 已修复、待同一 reviewer 限定复审”的状态，不是生产发布或
  event `924` 已公开。
  当前未提交、未部署、未联网、未写生产；最新成功代码 review 和其后的精确发布授权仍是
  后续硬门禁。

## 2026-07-18 event 924 首个 TRA shadow 赛果到达

- 已在 scheduler false、四层 policy shadow、tracking/allowlist 仅 `[924]` 的边界内完成
  有界手动轮询。写前恢复点 `efa68a76…fd13b` 已通过 `pg_restore -l`。
- generation 2–14 为 `13` 次无网络 `pre_off_wait`；generation 15–18 在预计开跑后按
  3 分钟窗口返回 `result_not_found`；generation 19 的 task `9615a5f6…432b` 于
  `14:14:42.301344Z` 获得首个 shadow result，距 `14:02:00Z` 预计开跑
  `12` 分 `42.301` 秒，控制循环随即停止。
- observation ID `1`、result revision ID `2` 已写入，7 匹均为 finished 且名次 1–7
  完整，无 parse warning；tracking 为 `provisional_result / shadow_applied`。
- publication、legacy result、official marker/incident 均为 0；公网仍无 participant 或
  赛果标签，healthz 为 200，live queue/worker/one-off 为空。scheduler 仍为 false，
  `14:24:42Z` 后续探针不会自动执行。
- 上述“worker 为空”只表示 live worker 的 active/reserved task set 均为 0；
  `race_live_worker` 节点本身仍在线并运行 `the_racing_api_free`。
- 本轮授权已消费；下一步须先审核本次真实 observation，再对后续复核或 provisional public
  灰度取得精确授权，不得扩展其他赛事。

## 2026-07-18 event 924 TRA shadow worker 启动检查通过

- 已只为 `race_live_worker` 启用 `the_racing_api_free`，scheduler 继续 false；tracking 和
  allowlist 唯一 ID 均为 `924`。写前数据库备份 `bc06babe…6207` 与逐字节一致的 `.env`
  备份已验证。
- 在合法 due 点后，实际 Celery task `7ba0699c…7ff0` 通过 live queue 执行并返回
  `SUCCESS / pre_off_wait`；claim 已释放，next poll 为 `11:33:04Z`，HostBudget 未变，
  因而没有提前请求 API。
- 赛果、observation、publication、incident 和公网 shadow 泄漏均为 0，队列/active/
  reserved/one-off 为空，healthz 为 200。下一步需单独授权 event 924 的有界 shadow
  轮询；scheduler 关闭期间不会自动执行 next poll。

## 2026-07-18 event 924 shadow baseline 初始化完成

- 精确 manifest `ee9d0d43…1432` 的 initializer dry-run、单次 apply 和独立 verify 均为
  `ok=true / error_count=0 / 1 event / 7 participants / replayed=0`；新写前备份
  `e57218e7…70fe` 为 custom-format、`0600` 且通过 `pg_restore -l`。
- event `924` 已获得 London `15:02` 开赛时间、live owner generation 1、7 匹 approved
  participant、1 个未发布 racecard revision 和四层 shadow policy；赛果、observation、
  publication、official marker/incident 仍为 0。
- 公网页面只新增客观开赛时间，不泄漏 shadow 出马表或赛果标识。scheduler false、runner
  disabled、live queue/one-off 为 0；下一门禁是单独授权 event 924 的 TRA shadow
  runner 启动检查，不得重复 initializer 或直接公开。

## 2026-07-18 event 924 已生成成功 racecard manifest，尚未初始化

- 用户授权的单次退避重试已完成；有效 run
  `production-racecard-gb-924-grade-retry-20260718T093207Z` 的 today/tomorrow GB
  请求均为 200，`completed=true / request_count=2 / blockers=[]`。
- manifest SHA-256 为 `ee9d0d43…1432`，精确绑定 event `924`、
  `rac_13000002795`、伦敦时间 `15:02` 和 `7` 匹 declared participant；companion
  hashes、`0700/0600` 权限和禁止字段检查通过。
- prepare 没有修改 event 或 live 业务事实：`9,867 / 100,132 / 91,897` 守恒，全部 live
  事实表、policy/allowlist、队列和 one-off 为 0；HostBudget 的 429 失败状态已清零。
  initializer、shadow、scheduler、runner 和公开仍未执行或开启，下一步需对精确 manifest
  单独授权。

## 2026-07-18 英国 Group 后缀修复已生产发布，prepare 被 429 阻断

- 冻结提交 `ebab4aa8` 已快进 `main` 并部署，四个 app service 统一运行 AMD64 image
  `sha256:4443a9c…55dc`；Django、迁移、镜像 racecard sync `20/20`、挂载隔离、内外
  healthz 与 Celery ping 通过。写前备份 SHA-256 为 `17ba9ccb…db0`，`pg_restore -l`
  通过，旧镜像与环境回滚点已保留。
- scheduler false、runner disabled、公开 policy/allowlist 为 0、live queue 为 0。生产
  `9,867 events / 100,132 runners / 91,897 results` 和全部 live fact 表均未改变。
- event `924` 新 prepare 的 today GB 请求为 200，tomorrow GB 请求为 429，因此
  `completed=false / blocker=http_429`。blocker artifact 无 manifest，未执行 initializer
  或公开；下一次联网重试需要新授权，成功 manifest 仍进入单独审核。

## 2026-07-18 英国 Group 后缀精确匹配实现完成

- 只读生产镜像诊断确认 event `924` 的 TRA 唯一候选存在，上一轮零命中的唯一身份格式差异
  是来源赛事名末尾 `(Group 3)`，不是 API 覆盖缺口；诊断没有保存 raw、写数据库或生成
  可 apply artifact。
- 新增行为只覆盖英国 `normalized_grade=G1/G2/G3`：从既有获准名称精确派生
  `group 1/2/3` suffix；零 token 才派生，唯一 terminal 同级 token 不重复，异级、非末尾
  或多个 token 整条排除，非 G1-G3 和其他地区维持原语义。
  精确匹配、日期、赛场、唯一性、HostBudget、artifact 和 initializer 门禁均未放宽。
- 真实 RED 为 `racecard_not_found`；首次代码 review 的非末尾/多 Group token P2 也已先补
  3 个失败 subtest 再修复。GREEN 后聚焦 `7/7`、完整受影响 SQLite `210/210`、临时
  PostgreSQL 16 锁/竞争 `6/6`，Django、迁移、语法和 diff 门禁通过。当前待同一 reviewer
  限定复审；未提交、未部署、未重跑生产 prepare，全部准实时与公开开关仍关闭。

## 2026-07-18 准实时 racecard 增量已生产发布，英国首轮 prepare fail closed

- 冻结提交 `6646302b80c90cf406075516ab4812f2f4ebee18` 已进入 `main` 并部署生产，四个
  app service 统一运行 image
  `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`；新 registry
  digest `60fcc081...ad402`、artifact/secret 挂载隔离、Django/migration/model drift、镜像
  目标测试 `20/20`、Celery ping 与内外 healthz 均通过。
- scheduler/runner/public policy 继续关闭。英国 event `924` 的受控 production prepare
  请求 today/tomorrow GB racecards 均为 200，但严格身份匹配返回
  `racecard_not_found`；blocker run 没有 manifest，因此没有运行 initializer，也没有写入
  赛事时间、participant、racecard、tracking 或赛果。
- 生产业务总量保持 `9,867 / 100,132 / 91,897`，全部 live 事实表仍为 0，仅 HostBudget
  为 1。下一步是对 event 924 的来源覆盖或赛事别名做独立身份审核；修复后重新 prepare，
  成功 manifest 仍需单独批准才可 initializer apply。

## 2026-07-18 准实时赛前 racecard/off time 同步实现完成

- 基于最新 `main@23435897` 的独立 change 已实现英国 TRA Free today/tomorrow racecard
  prepare、精确赛事绑定、Europe/London 开赛时间、schema v2 原子初始化、动态
  HostBudget、companion SHA 和 pre-off claim checkpoint；方案审核已 `APPROVED`。
- SQLite 准实时/初始化/来源/相邻历史组合为 `203/203`，一次性本地 PostgreSQL 16 的
  新旧初始化、竞争 manifest 与 runner 锁语义为 `6/6`；Django、迁移、Compose、语法和
  registry SHA 门禁通过。新 registry digest 为 `60fcc081...ad402`，无模型或迁移变化。
- 首次代码 review 的 artifact 并发误删与 event 占用 N+1 两个 P2 已用新 RED 修复：
  发布失败只清理本调用拥有的 inode，40 场占用检查改为固定批量查询；限定复审待执行。
- 本变更仍处于独立代码 review 前：未提交、未发布、未真实联网、未连接生产写入，也未
  开启 scheduler、runner 或 provisional public。生产仍运行上一安全基线，首次英国
  prepare 和 schema v2 初始化必须等最新 review 后的新用户授权。

## 2026-07-18 历史赛事公开状态

- `8,867` 个已导入且完整的历史目标已全部公开，五区分布为日本 `2,239`、中国香港 `473`、英国 `2,144`、法国 `652`、美国 `3,359`；eligibility、dry-run、apply 和独立 verifier 均为零错误。
- 生产当前为 `9,867 events / 9,820 published / 8,867 published+complete / 100,132 runners / 91,897 results`。五区浏览器验收、移动端、出马表顺序、赛果、历届、中文术语展示和距离单位展示通过。
- 最终运行 revision 为 `4af5e20a`，四个 app 服务统一使用 image `sha256:111dbe46...8d7a`；公网 healthz、赛事列表和详情为 200，队列为空。历史常驻写门和网络门、准实时 scheduler/runner 继续关闭。
- 正式总账仍为 `30,917` 条，其中另有 `20,544 pending / 1,467 source_unavailable / 31 identity_review_required / 8 ready`。这部分是后续抓取范围，不影响本轮 `8,867` 场已完成赛事的公开状态。

## 2026-07-18 准实时赛果生产安全基线已发布

- 用户授权的最新整合冻结版本 `4f11b227` 已部署；生产 tree `277cb10a...54c8`，web/普通 worker/Beat/独立 `race_live_worker` 均运行 image `sha256:c2b9e15e...03966`，迁移已从 `stable.0032` 前进至 `stable.0045`。
- 写前数据库备份 SHA-256 为 `f81a11ec...2a01`，`pg_restore -l` 通过；旧 image `sha256:63cdfc13...7329`、环境备份和精确回滚标签已保留。Django check、migration drift、镜像聚焦 `13/13`、registry/no-secret 检查及 HTTP healthz 通过。
- live scheduler 与 runner 分别保持 `false / disabled`，live 业务表和 `race_live` 队列均为 `0`；来源 proof 的 3 个固定端点均为 200，当前得到 `55 regions / 69 racecards / 50 results`，未保存 raw payload 或写业务 DB。
- 首轮 shadow 因生产赛程时间缺口未启动：未来 `428` 条赛事、英国 `72` 条的 `race_datetime` 非空数均为 `0`。严格初始化器会拒绝无法精确匹配开赛时间的 manifest；下一步必须先以独立受审增量补齐赛前 racecard/开赛时间同步，不能手工猜时间或直接打开 runner。

## 2026-07-18 AI 赛事身份决定已生产完成

- `267` 条 AI 初审决定已经受控落库：`228` 个正向关联、`24` 个去重负向系列对，另完成 John C. Harris Stakes 草地修正。业务 manifest `cf5e220e...a0147`、actions `9622460e...f53da1` 和 approval `f02b0e4c...0584` 保持不变。
- 首次 PostgreSQL apply 在任何业务写入前暴露 nullable outer join 锁错误；零写入核验后完成基表定向锁修复、真实 RED、相关 `52/52`、生产只读锁 smoke 和同一 reviewer 限定复审。最终 revision `f396d048`，生产三服务统一运行 image `sha256:63cdfc13...7329`，无迁移。
- 最终写前备份 SHA-256 为 `640791685f14d82cd8a47a9c83ce2b6fb4a361e8edafa824c9c2e6338c892707`，`pg_restore -l` 通过；apply result `20fb0462...3365`、rollback ledger `0a37af37...31e5`、独立 verifier `ok=true / error_count=0`。
- 写后为 `9,867 events / 100,132 runners / 91,897 results / 9,103 linked targets / 228 relations`；前三项完全守恒，OperationLog ID `96353`。John C. Harris event `507` 为 `turf`。
- web/worker/beat、内外 HTTP healthz、worker ping、队列、事务和日志均正常；历史公开、常驻历史网络和写入开关继续关闭。生产磁盘清理后约剩 `3.07 GiB`。

## 2026-07-18 准实时赛果生产 shadow 初始化器已完成

- 新增严格 manifest 驱动的 `initialize_race_live_events`：默认 dry-run、显式 apply、独立 verify、全事务和精确 replay；初始化范围仅为 shadow 的 control/tracking/source/participant/racecard/host budget/policy/allowlist/audit，不在 migration 隐式回填。
- shadow runner 的 `shadow_only` 现在是成功 checkpoint，不再累计失败；仍保持公开物化、publication 和 official incident 为零。SQLite 聚焦 `13/13`、PostgreSQL 初始化并发及既有锁语义 `5/5`。
- 首次成功原生完整 review 关闭既有 findings，另发现赛事日历 live read gate 的直接 P1：40 场页面为 `525` 次查询。真实 RED 后已改为固定批量读取，新增硬门禁 `<=12`；公开状态 `6/6`、准实时/来源 proof/初始化 SQLite `160/160`、临时 PostgreSQL `5/5` 通过，同一 reviewer 限定复审 `APPROVED`。因 `main` 随后新增赛事身份生产修复与证据，当前基于 `ccb56f7d` 的整合树仍需复审和新授权；生产未迁移、未初始化、未启动 live worker、未公开。
- 合并前候选镜像 `sha256:4a281e426e32...5b099` 已通过镜像内 check、初始化器+TRA runner `13/13`、registry SHA 和无凭据检查；三份 Compose、worker shell、迁移漂移与 diff check 在完整源码树通过。部署契约测试依赖仓库根 Compose/源 registry，继续只在完整源码树运行，不为镜像自测复制非运行时文件。
- 基于最新 `main@ccb56f7d` 的单父整合已完成：SQLite 准实时/来源/初始化/赛事身份组合 `180/180`（1 项 PostgreSQL 专用 skip），临时 PostgreSQL 精确目标 `6/6`；整合候选 image `sha256:87f8603320f8...73bcf` 的 check、初始化器+TRA runner `13/13`、registry/no-secret 检查通过。等待同一 reviewer 对 main 增量、冲突解法和直接路径复审。

## 2026-07-17 AI 赛事身份初审已形成生产候选

- 已正式采用 AI 初审的 `267` 条决定：`228` 条合并并关联、`21` 条保持独立、`18` 条非同赛／忽略；John C. Harris Stakes 另有一条 `surface=turf` 修复。正向决定保留来源系列，负向决定写入双向禁止自动合并规则。
- 执行代码 commit 为 `8b9b9755`，最终相关测试 `50/50`、Django check、迁移和 diff 检查通过；同一 reviewer 最终批准，无剩余直接 P0/P1。
- 生产只读 prepare 已完成：artifact 为 `/opt/umanewsbot/runtime/race_series_identity_review/prepare-8b9b9755-20260717_205349/artifact`，manifest `cf5e220e...a0147`、actions `9622460e...f53da1`，verifier 为 `ok=true / error_count=0`。对 228 个正向系列对的只读审计无同年目标冲突、既有关联冲突或第三方占用。
- 当前仍是 pending approval，生产数据库没有执行本轮写入；生产运行镜像仍为 `213a818c`。待用户针对当前 commit+manifest+actions 明确授权后，执行精确部署、新备份、dry-run、串行 apply 和逐项 verifier；历史公开保持关闭。

## 2026-07-17 赛事总账/公开赛程关联工具已发布，关联写入待身份审核

- 已完成 `reconcile-race-event-coverage` 本地实现和零问题复审：允许 `not_due` 安全采用唯一既有赛程，新增历史/当前/赛果三层报告、不可变 artifact、approval 双 SHA、原子 apply/rollback 和 verifier。
- 相关测试 `101/101`、Django check、迁移漂移和 diff check 通过；无模型或迁移变化。
- commit `213a818c` 已合入 `main` 并部署；生产 web/worker/beat 统一运行 image `sha256:f3b2d4625322e7f96554288d4b710723ff9d01323dd3be654bcbc2ba0281a9d9`，无迁移，healthz 与赛事页正常。部署前数据库备份 SHA-256 为 `7958873ff243f5a3c1bb85075f74fa0daec6a040f33688b31f63db71e1eb0e3b`。
- 有效生产只读 manifest 为 `5caee7d0ed093605aede28c2834d3acf8a75f9f20e2d88679924c3670f3c6a51`，verifier 无错误；`30,917` 个目标分为 `8,875 already_linked / 46 identity_conflict / 21,537 missing_event / 459 status_conflict / 0 exact_link`。因此 approval 保持 pending，本轮没有数据 apply。
- `7` 是 not_due，不是未举办总数；全账本另有 `459 not_held / 15 cancelled`，2026 还有 `630 missing_event`。东海锦标等线上赛程与英文总账被拆为不同系列，另有跨地区同名误命中，需先完成系列身份审核。
- 可读审核入口为 `outputs/race_event_reconciliation_20260717/生产赛事身份审核_213a818c_20260717.xlsx` 与 HTML，包含 46 条明确冲突、221 条别名/跨语言候选、冠军马、1号马、来源和线上页面。身份确认后重新生成具有明确动作的新 manifest，再执行备份、串行 apply 和逐目标 verifier；历史公开继续关闭。
## 2026-07-17 准实时赛果来源路由产品口径修正

- The Racing API 调整为覆盖范围内的暂定赛果公开主链：完整结果通过身份/字段门禁后可在官方二次复核前发布，并明确标注 provisional。
- JRA/NAR/HKJC 等官方来源继续异步复核并决定 official/corrected；TRA 不获得 official authority，空结果、缺马、身份冲突、人工锁、条款和发布 mode 门禁不放宽。
- 首轮方案复审提出的唯一 publication admission/read gate、TRA supplemental 数据库约束、racecard 全集完整性、不可变 official marker、异步 incident 闭环和 `0041` 迁移口径均已补齐；同一 reviewer 限定复审逐项关闭并给出 `APPROVED`。用户已授权进入测试先行、实现、shadow 与上线准备；实际生产发布仍须在最新成功代码 review 后取得一次新授权。当前没有本轮新增的网络 adapter、生产写入、部署或公开开关变化。

## 2026-07-17 准实时赛果首个 TRA Free 来源 proof 已完成

- 新增受控、脱敏、业务 DB 零写入的 The Racing API Free proof runner；仓库外 `0600` secret 已验证可用，不进入工作树/镜像/日志/artifact。
- 首个成功窗口完成 3 个 Free 请求：regions 55、racecards 10、results 0，均 HTTP 200。reviewer P2 指出的 proof/长期 automation 许可耦合已用真实 RED 修复并通过限定复审；完成时间与 unknown 状态两个后续建议也已按 RED 修复，无效时钟和无 partial artifact 契约已补自动化。离线 proof + 准实时 `126/126`，合并 latest-main 相邻历史回归 `262/262`（1 skip）。
- 当前只确认认证、端点与 schema；尚未取得已完赛样本或四赛日数据，覆盖、暂定/正式分类、p50/p95 和 Basic 升级门槛均未通过。无部署、生产写入、订阅采购或公开开关变化。
- proof runner 与后续时钟/unknown 状态增量已完成复审。已启用本地 `tra-free-proof` 每日低频 automation 收集四个不同赛事日期；达到四日且至少一个非空 results 窗口后不再联网，等待主任务汇总。automation 不写 tracked 文件或业务 DB。

## 2026-07-16 第一期历史赛事正式详情总账完成

- `1998–2026` 正式详情范围已固定为 `8032`，最终 `6534 complete + 1491 evidence gap + 7 not_due`；生产共有 `6534 events / 70314 runners / 65227 results / 6534 winners`，global verifier 为 `8032 checked / 0 errors`。日本、中国香港、法国 hard 范围完整；英国历史 hard 为 `708 complete + 45 evidence gap`，英国新正式为 `94 complete + 1 gap + 4 future`，美国新正式为 `195 complete + 1 future`；英美历史 G2/G3 按批准的 best-effort 口径收口。
- France 14 场和 UK 6 场补包已完成备份、dry-run/apply/replay/verifier；France manifest 为 `7e8f2906...eeb`，UK bundle 为 `fd3438be...081`。UK 6 场为 `46 runners / 40 results / 6 winners`，包含 `40 declared + 4 pulled_up + 2 withdrawn`；UK 场地修正 apply 与两次 verifier 均为 `4/4`。UK 6 场与 gap 裁决统一写前备份为 `189338143` bytes，SHA-256 `c5006b15bee22dd17d0d6fb7913f7c376a0799eeb37f3d6dc42b9199444c1410`，权限 `0600`，mtime `2026-07-16 23:04:32 +0800`，`pg_restore -l` 通过。
- resolution manifest `d5291268...c90f` 的 `1498` 条记录已 apply 并通过两次独立 verify，对应 `1498` 条唯一 `OperationLog`；原因为 `1467 source_unavailable + 31 identity_review_required`，按日期最终归入 `1491 gap + 7 not_due`。target `53349=2026-09-05`、`53418=2026-07-26`。
- 最终审核产物位于 `runtime/race_event_crawl_runs/final-detail-coverage-ledger-v5-20260716`，manifest `692b089b...584ea`、ledger `83399595...8fe9`，review 为 `approved`。生产 formal `published=0 / featured=0`，历史 enabled/network 均为 false，无 runner 或 running batch；历史公开仍关闭。
- 生产已统一到 image `sha256:c8c49780ac9dca4799e4834b052f7e05ca75ff61945343b2c19bf0ef2ab561ab` / revision `6b596befa0eea9ef0ba45acbb5384195829cc144`，无迁移；Django check、两域 healthz 200、worker ping 与日志检查通过。即时回滚标签和 `.env` 备份已保留。删除未使用旧 tag 后磁盘从 `2.6 GiB` 回升至 `4.0 GiB`，仍低于 `5 GiB` 门槛，服务器后续 crawl 为 no-go，重型抓取继续放在本地 Docker。
- 第一期正式详情总账的数据写入已完成，完成口径是“完整或证据化 gap/not_due”，不是“全部 complete”或“已经公开”。

## 2026-07-16 英国 Sporting Life 197 场增量详情已写入生产

- 用户按 commit `2a7352c8` 与 manifest `3c6a4d11...831c` 授权后，已完成独立备份、全量 dry-run、两块串行 apply 和逐目标 replay verifier。写前备份 SHA-256 为 `a942e2dad092bdf0af9e0546030a73c75dfeebb1c89ee888d704e8244d7f0d6c`，两个 verifier 均 `error_count=0`。
- 本包范围为 `198 = 197 complete + 1 evidence gap`；新增 `197 events / 2027 runners / 1794 results / 197 first-place winners`。唯一 gap 为 target `57633`，未伪造为 complete。197 个完整目标均为 imported，basic/runners/results 全部 complete。
- 全部新增赛事仍为 `draft + incomplete`、公开 0、featured 0。生产 web/worker/beat 已恢复并统一运行 `sha256:97b49b...397473` / revision `700a2a96`，HTTP 内外 healthz 正常，historical runner 为 `migration_safe`，常驻历史网络/写入和公开开关保持关闭。
- 生产累计 historical imported target/event 当前为 `7182`，但一期 master ledger 尚未全部完成；后续继续处理剩余分片和统一 gap/review ledger，不重跑本包已验收目标。

## 2026-07-16 4652 场历史详情已写入生产，公开门禁保持关闭

- 审核基线 `94360245...892a`、content `a353f2f8...748f`、commit `700a2a96` 与 manifest `dfb86ee8...14d9` 已按授权发布。生产 web/worker/beat 统一运行可复现 AMD64 镜像 `sha256:97b49b0226ce6de844de7e26ecbd51851c38fd2b0146c471f6f27767be397473`；镜像内测试 `30/30`、Django check、迁移状态和运行健康检查通过。
- 正式 bundle 为 `4930 = 4652 complete + 278 gap`。4652 场已写入 `51191 runners / 48413 results / 4652 winners`，地区为法国 `15`、香港 `19`、日本 `1586`、英国 `171`、美国 `2861`；截至 2024 年 `4351` 场，2026 当前到期范围 `301` 场。
- 首次 dry-run 发现 `stable_raceevent_series_key_6e15e445` 物理索引损坏，事务回滚且无 receipt；在独立备份后以 concurrent reindex 修复，再从头 full dry-run 20/20。正式写前备份 SHA-256 为 `6c7d8f326c4c6a10f685a7be1a0625027cf6732729bcbc6904eba3aa45964b54`，apply 20/20、replay verifier 20/20，最终错误、缺来源和缺日期均为 0。
- 全部新事件仍为 `draft + incomplete`、`published=0`；历史模块完整表示详情已写入，事件级 `incomplete` 表示尚未通过独立公开验收。常驻历史写入、网络和公开能力均关闭，草稿 URL 返回 404，HTTP healthz 正常，队列和历史 runner 为空。
- batch006 和本次 4652 场不再重跑。278 个 gap 继续保留在统一审核账本；remaining `28126` targets 仍按 `8857 historical hard / 18173 historical best-effort / 1096 new formal` 推进。收口时生产约 `4.5 GiB` 可用，低于既有重型 crawler 的 5 GiB 门槛，本次没有启动新的生产 crawler。

## 2026-07-16 France runner v2 单目标 smoke 待重新生成 descriptor

- 本地固定镜像与独立 run/host-lock 根已核验，但 France `48498` descriptor 的 mounts/outputs 仍绑定 plan root，和批准的 runtime 根不一致。
- `discover` 在容器创建前 fail closed；请求、缓存、阶段产物和残留容器均为 0，后续四阶段未运行，生产与数据库未接触。
- 下一步由计划生成侧提供绑定独立 runtime 根的新不可变 descriptor，再从 `discover` 重跑；不得绕过路径身份门禁。

## 2026-07-16 日本 runner v2 单目标 smoke 待重新生成 descriptor

- 本地固定镜像与独立 run/共享 host-lock 根已核验，但 Japan `50556` descriptor 的 mounts/outputs 仍绑定 plan root，和本次批准的 runtime 根不一致。
- `discover` 在容器创建前 fail closed；请求、缓存、阶段产物和残留容器均为 `0`，后续四阶段未运行，生产与数据库未接触。
- 下一步由计划生成侧提供绑定独立 runtime 根的新不可变 descriptor，或经明确审批改用 descriptor 原批准路径，再从 `discover` 重跑；不得绕过路径身份门禁。

## 2026-07-16 准实时赛事赛果 latest-main 复审通过，进入离线测试先行

- 独立专项初始 PLAN 基于 `9b617702`，离线 TDD 期间持续安全快进，当前 `HEAD == origin/main@283bacf2`；专项经 stash、`ff-only`、恢复后保留主线与专项双方文档事实并解决四份文档顶部冲突，代码仅有 `race_events.py` 的新增 re-export 与专项追加内容自动合并。五份 durable artifacts 位于 `docs/changes/realtime-race-results/`。
- 目标是重点赛事完赛后数分钟展示明确标注的暂定赛果，再由官方来源确认/更正；不提供逐秒位置，不接管历史回填。
- 已完成计划、latest-main 复用审计和第一批离线 TDD：发布 mode resolver 的 5 项目标测试与 3 项相邻赛事回归共 `8/8` 通过。首次原生代码 review 的 terms permission 缺失 fail-closed 和状态记录两项 P2 已修复，同一 reviewer 限定复审 `APPROVED`。The Racing API 仍采用 Free 先 proof，且历史 handoff 前不联网。
- 第二个离线 TDD 切片已完成六态状态机纯函数 RED -> GREEN：只允许审核设计中的 7 条边，准实时模块与 3 项相邻赛事回归共 `10/10` 通过，同一代码 reviewer 完整只读复审 `APPROVED`；持久化 revision/ownership 尚未实现。
- 第三个离线 TDD 切片已完成严格 JSON canonical SHA-256 RED -> GREEN；review P2 指出的等价数字 hash 抖动已按新增 RED 修复，五种 approved phase 均明确排除于内容 hash。准实时模块与 3 项相邻赛事回归共 `15/15` 通过，同一 reviewer 限定复审已关闭唯一 P2并 `APPROVED`；尚未接入 revision/CAS。
- 第四个离线 TDD 切片已新增 ProjectionControl 基础一对一模型与 `0033` migration，不自动回填或接管既有赛事；完整 review 对本模型无 finding，既有 mode resolver 的 event allowlist P2 已按新增 RED 修复并由同一 reviewer 限定复审关闭。latest-main 上 SQLite 专项、相邻赛事及历史 chunk/receipt/import primitive 回归 `49/49`，check/migration drift 通过。revision pointer、owner transfer/CAS 和 importer 接入仍未实现。
- reviewer 后续建议的 revision counter 0 风险也已按真实 RED 修复：模型与未发布 `0033` 增加两个 `>=1` 数据库约束；组合回归 `50/50`，等待限定复审。
- 离线数据与调度骨架继续按真实 RED -> GREEN 推进：`0034` 至 `0038` 已覆盖 LiveTracking、身份、append-only revision/evidence、current/LKG pointers 和共享 HostBudget；owner transfer、revision allocator、source permission、时间窗、claim、host reservation、checkpoint 双 CAS 已实现。reviewer 的过期 claim P1 已分别补齐过期与缺失 expiry 的真实 RED 并修复，latest-main 组合回归 `105/105`；PostgreSQL 并发层仍待执行。未联网、启 worker、初始化 tracking、写生产、部署或购买订阅。
- 新一批离线控制面已完成 due-selector、host circuit、默认关闭的 Beat selector、`race_live` poll route、The Racing API Free 合成 fixture contract和 append-only observation recorder；并按 reviewer finding 将损坏 claim lease 改为 fail closed、host outcome 改为 reservation version CAS。准实时 `85/85`、与 historical detail chunk/import receipt/import primitives 组合 `122/122`，check/migration drift/diff check 通过。poll runner 仍 fail closed，专用 worker/真实 HTTP/revision apply/PostgreSQL 并发未完成，等待同一 reviewer 限定复审；Compose 解析因 worktree 无 `.env` 未完成，未借用主工作区 secret。
- 三份 Compose 的独立 `race_live` worker 也已按真实 RED -> GREEN 完成：普通/live queue 显式隔离，live 默认并发 1、prefetch 1、45/60 秒软硬时限，scheduler 默认关闭；准实时 `88/88`、与 historical detail chunk/import receipt/import primitives 组合 `125/125`，Compose 解析与脚本检查通过。尚未连接真实 broker/worker，poll runner 仍 fail closed。
- 赛果 conflict policy、observation -> immutable revision/items/evidence、current/LKG pointer 与 shadow/public projection apply 已完成；official authority 已绑定持久且 approved 的 source identity，shadow 可通过唯一 publication audit 单向晋级。公开赛事页已区分 provisional/official/corrected/conflict/stale，shadow 不泄漏。SQLite 准实时 `103/103`、相邻历史组合 `140/140`。真实 PostgreSQL 16 identity/apply/并发直接路径 `15/15`，覆盖 `skip_locked`、host 串行预约、同 claim 单 revision/replay、deferred pointer/supersedes guards 与 shadow promotion；`0039`/`0040` 迁移往返通过。仍未连接真实 broker、HTTP 或生产。
- 完全离线 TRA fixture runner 已完成受控文件 parse -> observation -> shadow revision -> checkpoint，使用实际文件 bytes SHA、失败 bounded retry、成功有限窗口/T+7d 停止，并强制 offline 永不公开。SQLite 准实时 `108/108`、相邻历史组合 `145/145`；仍未连接真实 Redis broker、HTTP 或生产。
- 临时 PostgreSQL+Redis 的真实 broker smoke 已证明 selector -> live worker 端到端与普通队列隔离：1 observation、1 revision、成功 checkpoint、shadow result 0，普通 `celery` 消息未被消费；临时资源已全清。生产 broker、HTTP 和 shadow 仍未启用。
- 后台已具备 live 模型只读观测面与赛事级 CAS kill switch；停用会立即失效在途 claim 并写审计，真实 Django admin POST 通过。manual correction 未开放。准实时 `113/113`、相邻历史组合 `150/150`。
- latest-main 组合回归 `249/249`（1 skip）通过；完整 `stable` 的 `2 failures / 13 errors / 23 skipped` 已在干净 `origin/main@c40a8c2b` 精确复现为相同 15 项主线基线问题。Django check、migration drift、三份 Compose、脚本语法和 diff check 通过。
- 最终 full review 的 2 项 P1、1 项 P2 已按真实 RED 修复：TRA non-finisher 状态保真，非完赛公开显示不再 fallback 内部顺序，两份生产 live worker 增加 0.25 CPU/384M 默认限制，并新增 `0041` choices migration。准实时 `116/116`、latest-main 组合 `252/252`（1 skip）和静态/迁移门禁通过，等待限定复审。
- 计划采用共享写入所有权仲裁、稳定 participant、append-only racecard/result revision、现有当前投影、独立 `race_live` Celery queue/worker 和按 host 共享限速；网络任务使用短 claim、无锁联网、短 CAS/apply。
- 原方案和用户修正范围均已 `APPROVED`；最新主线已把第一期历史详情正式分母收口为 `8032 = 6534 complete + 1491 gap + 7 not_due`，global verifier `errors=0`，历史 runner 为空且网络/功能开关关闭。来源 proof 的“历史先完成”条件已满足，但 proof 必须业务 DB 零写入；任何 shadow 仍需精确 event ownership allowlist、无 active lease/checkpoint、source registry digest 和共享 host/资源窗口的 SHA handoff。当前未联网、部署、购买、连接生产或开启公开展示。
- The Racing API Free 暂定赛果核心链已完成：安全网络 runner -> append-only observation -> shadow revision -> 持久 admission -> 暂定赛果投影 -> 官方复核 incident；公开读取门、只读后台、独立 Celery queue、容器 secret 隔离和默认关闭配置均已落地。当前 registry digest 为 `1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`，专项回归 `149/149`。仍未生产迁移或初始化任何 event；最新成功代码 review 和其后的用户发布授权仍是硬门，官方结果自动复核不计入首轮完成范围。

## 2026-07-15 Codex 原生工作流迁移已进入 `main`

- durable change 位于 `docs/changes/codex-native-workflow-migration/`；方案审核与代码审核均为 `APPROVED`，用户在最新成功代码 review 后回复“确认上线”。
- 受审 feature commit `55b6cebc14eef067c929b01ce3cea5515416c5ef` 已通过 [PR #10](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/10) 合并到远端 `main@96810fcc288f92b41971f4f825105732967798c2`。merge parents 为 `d6d6f58b...`、`55b6cebc...`，merge tree 与受审 feature tree 一致。
- 本迁移五份 durable artifacts 已随 PR 合并；发布验证为 fingerprint `24/24`、transition/index `10/10`、workflow contract tests `26/26`，workflow checker 与 `git diff --check` 通过。
- 本次仅发布仓库治理文档、skills/agents/scripts 和历史 skill 归档，不含 Django/runtime config/migration/生产数据变化；未构建或部署生产镜像，未重启、重建、迁移生产容器，线上业务运行态保持不变。
- 本次验收以远端 `main` 合并完成为准，无需生产部署。发布证据和回滚方式记录在 `docs/changes/codex-native-workflow-migration/release_report.md`。
- 原合并前记录中的“尚未发布”状态现已由上述 `main` 合并证据取代，不表示当前仍未发布。

## 2026-07-15 batch006 五地区详情抓取冲刺

- 1061 场正式 selection 的年度日期已达到 `1050 complete + 11 evidence gap`，完整记账率 100%。零星日美缺口继续累计到最终审核，不中断地区或年代分片。
- 日本、美国、英国、香港详情分别完成 `248/248`、`241/241`、`250/250`、`61/61`；对应出马/赛果为 `3704/3671`、`2181/1885`、`2570/2105`、`660/645`。法国详情已启动 checkpoint 续跑，本检查点完成 61 场且无解析错误。
- 英国距离单位歧义、香港同日同前缀赛事的一对一解析和跨 shard 共享 host 限速已修复，完整 stable `1528/1528`（11 skip）通过，最终 review 无 actionable finding。
- 生产 SSH 因此前重型 France verify 后持续握手超时，赛事 apply 暂停；所有重解析留在本地。主机恢复后先做事故清理与健康核验，再按 dry-run、独立备份、apply、只读 verifier 串行推进。历史公开开关继续关闭。
- 日、美、港正式详情包已分别生成 `248/241/61` 场且 gap=0；英国 250 条真实赛果 URL 已形成 date fragment，待日期和详情来源阶段写入后重新绑定 target SHA。共享 host limiter 已让法国两个本地 worker 在独立 shard 预算下严格保持跨容器至少 1 秒启动间隔。
- 最新已提交修复的 AMD64 候选为 `sha256:f1098223...06c3`、revision `f9e76b88`，镜像内 check/migration/赛事专项通过；生产不可达期间不部署。

## 2026-07-15 batch006 年度赛历流水线已部署

- 正式年度赛历 request/cache/parse 流水线已完成实现和零问题 review：支持全量或分片 ledger、共享 URL 去重、partial 终态、缓存身份复核、五地区 parser、complete/gap 分母及 runner 目录 checkpoint；完整 stable `1524/1524`（11 skip），专项 `118/118`（1 skip）、runner `70/70`、性能 `3/3`、OpenSpec `30/30`。
- 法国真实官方来源已达到 2023 `120/120`、2024 `130/130`、issues=0；香港现有覆盖 `61/61`、日本 `248/250`、英国 `250/250`、美国 `241/250`，剩余日美缺口继续进入统一审核账本。
- 生产 web/worker/beat 已统一到 `main@ccfee75f` / image `sha256:e86c2339...773d`；迁移、Django check、runner provisioning、crawl/apply 隔离、暂停/恢复和最终空锁验收均通过。写前备份 SHA-256 为 `898c9a4ab3a06847023d189aed830553cbe733bf4c8e92a4ed636dd8231fa55f`，历史常驻与公开开关继续关闭。
- batch006 仍为 1061 场 approved selection，按 11 个地区×届次年 scope 执行：FR `120/130`、HK `35/26`、JP `88/138/24`、UK `196/54`、US `83/167`。正式网络请求与赛事业务表写入尚未开始；下一步生成不可变 descriptor/shards/runner plans 后逐 scope crawl，并把日美少量 gap 累计到最终统一审核。

## 2026-07-15 historical runner 新镜像已部署，batch006 待正式审批与分片 crawl

- 生产已统一切换到 `main@c4087e6c` / image `sha256:5eb6471c8c1e96c90198e519c4d02f1b74316d6a13dbc93e9b63c0981ad22600`，写前数据库备份 SHA-256 为 `60331b0840a98e00370f2a5c10724d2e0e9ee370724ac572be8b0cd54781e341`，旧镜像回滚标签已保留。
- runner provisioning、crawl 最小权限、apply 无公网出口、暂停/恢复不重复、资源限制、迁移 preflight 和生产工具根 fail-closed smoke 均通过；伪造 artifact 子目录工具根时未创建数据库 run。
- 历史公开、常驻网络和常驻写入继续关闭，归属 mode 仍为 off；收口时队列、active/reserved、翻译/归属/历史运行和事务均为空，生产约 7.49 GiB 可用。
- batch006 已有 1061 场 selection，但正式审批与 runner plan 尚未固化，未发出网络请求、未写赛事业务表。下一步按请求预算拆分 crawl，并只使用镜像内白名单工具。

## 2026-07-15 新闻质量修复与 7 月 13 日起存量重跑完成

- 三类新闻质量缺陷已上线：正文边界/博彩噪声、实体语境/完整未知马名保护、日文普通词/产驹/追切/访谈/出马表固定格式。
- 冻结范围 `357` 篇，`343` 篇可处理、`14` 篇重复；最终 `218 published / 105 pending_review / 20 ignored`，点名 19 篇全部公开且 HTTP 200。
- 生产 web/worker/beat 已统一到 revision `bdc0eeff78e111d7fa8a697cbb3557888f864fb8`、image `sha256:c975a4faf979a1f78cdb203b810d4f5726aca114175007fc01c176044f13841c`；最终任务、队列、翻译状态和数据库事务均为空，healthz 正常。
- OpenSpec 相关 change 已归档且全量校验通过。历史 batch006 因生产可用磁盘约 `3.0 GiB < 5 GiB` 继续关闭，不属于新闻发布完成状态。

最后更新时间：`2026-07-16`
当前版本：`v0.0.1`（正式域名 HTTP 接入已修复，自动化运营 MVP、公开首页资讯流、抓取新鲜度修复、后台快速术语创建与当前稿术语应用、外部马名索引识别链路、榜单重点 QQ 推送、公开文章 ID URL、国际赛马资讯扩展、多地区生产窗口、术语种子数据准备、赛事日历 MVP 和马匹详情页 MVP 均已部署生产）

## 2026-07-14 多地区归属 V3 首轮生产审计 no-go

- 首轮候选在生产 72 小时只读范围内完成 `596` 篇审计，约 `29.36s`；Gold 有效 156 条，主地区准确率 `96.15%`、相关 precision `100%`、recall `52%`，机器门槛合格。
- 人工全量复核主地区变化与 `needs_review` 仍发现 7 类错标，涉及普通单词马名、赛事与马来源优先级、日本当前成就/海外梦想、机构名嵌套赛事词及正文历史背景。因此生产继续 `off`，没有开始 Shadow。
- 反例已固化并完成规则修复；专项 117、完整 stable 1404、真实 PostgreSQL 250 篇性能、Django/迁移和 OpenSpec 29/29 均通过。下一步是第二候选的生产只读重跑和同口径人工验收，不以旧 `qualified=true` 直接上线。

## 2026-07-14 多地区归属 V3 生产审计性能修复

- 生产首个 72 小时全量 run 已覆盖 597 篇，但旧报告阶段因逐篇发布门禁超过 30 分钟而中断。当前分支已把全量归属报告与门禁复核拆开，并支持从持久 run 原子重建审核 JSON；缺失/漂移文章自动必审，run 内容漂移直接拒绝。
- 159 条单审 Gold 当前有 21 条正文 SHA 漂移；原审核快照对账预计可安全续签 18 条，标题变化、正文异常缩短和推断变化各 1 条继续阻断。该结果尚待新代码部署后在生产只读命令中生成正式 artifact 与 SHA。
- France Galop 已补星期前缀英文日期解析和 probe 时间证据字段；部署后应能把真实官方日期标为 verified，而不是使用抓取时间。当前生产多地区 mode 与相关查询仍关闭，尚未进入 24 小时 Shadow。
- 本地专项 109 项、完整 stable 1396 项、一次性 PostgreSQL 250 篇性能契约和 OpenSpec 29/29 均通过。下一步是提交/构建安全关闭候选，生产只读重建 Gold 与 72 小时报告，再依据完整清单决定是否开始 Shadow。

> 角色说明：
> 本文档用于保留项目级概览与摘要信息。
> 当前真实工作状态、最近一次关键修复、线上实际进展，请以 [docs/current_state.md](E:/Codex/docs/current_state.md) 为准。

## 2026-07-14 batch006 前置能力已部署，资源门禁补丁待上线

- `scale-and-isolate-historical-race-batches` 已把 batch006+ 单地区标准上限统一为 250，并将可恢复的独立 historical runner、迁移 `0031`、最小权限 provisioning、隔离 smoke、迁移暂停 preflight 和独立 infrastructure bootstrap 部署到生产。当前生产镜像为 `sha256:33055eb8...25385` / revision `8741de98`。
- runner 使用数据库租约 + runtime 文件锁、30 秒心跳/180 秒租约、固定镜像与 plan/input/output SHA checkpoint；crawl 只有网络和控制账本权限，apply 只有内部数据库写入权限，全部历史 RaceEvent 继续保持 draft。
- 生产 runner smoke、双锁、暂停/恢复、越权拒绝和普通部署不干扰均已通过；batch006 selection 已生成 `1061` 场，五地区为 `250/61/250/250/250`，与前四个有效批次零重叠。正式网络抓取尚未启动。
- smoke 后发现直接 `python_tool` 未强制继承请求/cache/磁盘预算，且生产仅余约 2.8 GiB，低于 5 GiB 门禁。已按 OpenSpec 补充宿主与 Django 双层校验、共享账本、失败/强杀 checkpoint、显式赛事工具白名单及嵌套 AdapterRunner 收紧继承；第七轮 review 无问题，本地 runner `64/64`、historical 组合 `200/200`。最终合入最新主线后交叉专项 `208/208`（跳过 1）、完整 `stable 1417/1417` 通过（跳过 7）。释放生产空间、部署候选和强化 smoke 完成后才允许启动 batch006。
- 最终组合提交 `84217c56` 的两个独立本地 AMD64 构建 image ID 一致为 `sha256:2e8bd05f...28b31e`；候选 tag `umanewsbot:main-84217c56-amd64-20260714-2220`，OCI revision 精确匹配真实 Git 对象，镜像内 check、migration drift、runtime 专项 `239/239` 通过（跳过 1）。旧 `82fa4a3f` 候选及 revision 标签错误的 `sha256:119f59e3...` 均明确作废。仍未 retag `prod`、未部署、未连接生产、未启动 batch006；必须等待新闻维护窗口重新交还后先治理磁盘并执行 hardened smoke。
## 2026-07-14 多地区归属 V3 性能与审核策略

- 已用临时 PostgreSQL 16 和真实校准规模完成 250 篇基准。首次发现来源配置 N+1 导致 254 SQL；批上下文增加 17 个来源一次预加载后，五轮稳定为 5 SQL、1.66–2.14 秒、约 49 MiB，性能门槛已通过。
- 单审身份不再自动 no-go：首发覆盖门槛为有效样本至少 150、五个运营地区各至少 10、跨地区至少 20；达到全部质量/性能门槛后可进入生产 shadow。至少 24 小时 shadow 和全量差异复核通过后，才允许仅新文章 enforce；多人审核冲突仍须裁决。
- 现有 159 条单审 Gold Set 的最少运营地区样本为法国 11、跨地区 24，主地区准确率 98.11%、相关地区 precision 100%、recall 54.84%、过度扩散 0%，已达到进入 Shadow 的覆盖与质量线。Gold Set 后续持续吸收新增来源、规则改版、shadow 误判和运营争议；生产归属和相关地区查询尚未开启，本轮没有生产操作。
- Gold 生成器与评估器已共用可配置的 `150/10/20` 默认门槛；合并 `origin/main@9d6dec34` 并补齐全量审计契约后，完整 `stable` 1327 项通过（1 项按设计跳过），159 条 Gold 仍为合格，OpenSpec strict/all 28/28 通过。
- 上线前补齐了生产审计入口：`--scope all_articles` 才表示最近窗口全量有效文章（包含已发布稿），默认 `gate_candidates` 继续只服务术语门禁补跑。全量审计输出全部主地区变化、全部 `needs_review/locked_skip` 和五地区可重复分层样本；显式 limit 导致不完整时会明确阻断验收。当前改动尚未部署，生产 dry-run 与 24 小时 Shadow 仍待执行。
- 代码已推送 main `7f0827ad`，可复现 AMD64 候选为 `sha256:6ad16e36...af9a1`，镜像内专项通过。生产切换因正在运行的 186 篇受控翻译重试 one-off 暂停；生产仍是旧镜像，归属 mode=off、相关查询关闭，尚无 72 小时归属 run。

## 2026-07-14 生产 DB/Redis 意外重建恢复

- `01:22` 的误用 `docker compose run` 意外重建 DB/Redis，造成短时连接中断、Redis 待消费任务丢失、新闻索引异常和 4 组重复 article identity。web 镜像未变化，PostgreSQL 为干净关闭后从原目录恢复。
- 已通过停 beat/排空 worker、完整备份、5 条重复记录受控合并、`stable_newsarticle` 全部 17 个索引并发重建和 `VACUUM ANALYZE` 完成恢复；最终 8312 行、重复 0、无效索引 0、dead row 0。
- 最新备份为 `pre-newsarticle-dedup-reindex-20260714_020918.sql.gz`，SHA-256 `f37ff4835fe13d4c2a016beac433940ef995677e690711dc68ca59f42b149a9e`。`02:15` 自然窗口 17 个来源、五地区发布和 QQ 全部成功，公网健康检查正常。

## 2026-07-13 多地区归属单审校准结果（已由 V3 复评更新）

- 审稿人 1 已完成部分抽样标注：159 条有效、1 条排除、90 条未选中忽略。没有第二位审核人这一事实继续以 `provisional_single_review` 保留，不伪造 reviewer B；2026-07-14 起单审身份本身不再自动 no-go。
- 当日生产只读旧规则评估有效分母 154，主地区准确率 81.17%、相关地区 precision 6.90%、recall 6.67%，属于历史基线。冻结 159 条完整分母上的 V3 复评已提升到主地区 98.11%、相关 precision 100%、recall 54.84%，并达到 `150/10/20` 首发覆盖门槛。
- 已补充单审固化/只读评估、原始值规范化审计和正则模式复用。逐篇结果保存在 `outputs/20260713-multiregion-gold-final/multiregion_gold_set_final_20260713.xlsx`；当前只取得进入 Shadow 的资格，归属 enforce 与相关查询仍不得直接开启。

## 2026-07-13 多地区归属 Gold Set 标注包

- 已从生产库只读生成 `multiregion-gold-v1-20260713` 双人盲标包：共 `250` 篇，五地区各 `50`，覆盖 `17` 个来源，URL 和输入 SHA 各自全量唯一，manifest SHA-256 为 `1836a9d896ca5b6e09da6da7ed07a2fb3f66f0a02f387010fe4b56475bf5c1ea`。
- 已补齐抽样与合并命令，能阻止同一审核人重复充当双审、正文/身份漂移、未裁决冲突和样本结构不足；正文审核包不进入 Git，正式 Gold Labels 才进入版本控制。
- 本段是原始候选包记录。用户后续明确不再补第二审核人，OpenSpec `5.1` 已按 159 条单审 Gold Set 完成；若未来增加多人审核，仍需合并冲突并裁决。多地区归属和相关地区查询继续关闭，下一步是生产 Gold/dry-run 与 Shadow 验收。
- 本分支已同步 `origin/main@693db30e`，最新组合回归 `1139 passed / 1 skipped`，Django、迁移、OpenSpec strict 和 diff 检查通过。
## 2026-07-14 日文赛马翻译与固定格式上线

- `standardize-japanese-racing-translation` 已部署 `main@873845da` 并归档。普通片假名、完整未知马名、产驹、追切、访谈、骑手未定及三语机构术语均进入确定性翻译契约；种子术语恢复会处理明确边界重复，英文术语中文目标不会反向污染日文普通词。
- 11 篇目标文章全部保持原公开身份并通过逐篇正文验收；随机样本 `8337/8366/8356/8307/8367` 无占位符或假马标签。最终本地完整 `stable 1295` 项通过（跳过 1），候选 PostgreSQL 关联 84 项和最终零问题 review 通过。
- web/worker/beat 统一镜像为 `sha256:d3f602de4459158bc372e45bb35f3730a7be21f284dfea32de5535681bd6d791`；HTTP、空队列、术语唯一性、历史安全开关和日志验收正常。最新写前备份为 `pre-873845da-20260714_124940.dump`，SHA-256 `413718143809a09686ea18710a4cd8b8f9a9f7643fb6b769cee5daf23ca485a6`。

## 2026-07-14 新闻实体语境修复上线

- `contextualize-news-entity-resolution` 已部署 `main@dc1e5ec5`；统一文章级实体解析覆盖翻译、标签、校验和自动关联，解决英文人物/普通词误作马名、姓氏回指以及日文完整马名被内部短术语拆分。
- 11 篇问题文章已修复并保持原公开状态、发布时间与 QQ 幂等；随机六篇及最终 worker 新处理两篇通过回归。最终验证为目标 `51`、完整 `stable 1249` 项通过（跳过 1），第 18 轮 review 无问题。
- web/worker/beat 统一镜像为 `sha256:5b06821610f0d2214cb24692e58beac4ffda731ddb84674a8855b2a1d4dbb470`；HTTP 健康、目标详情、空队列及错误日志正常。最近有效写前备份为 `pre-main-624dd5b9-20260714-071014.dump`，SHA-256 `21cdce21f52ded3b48e7c083f2f536eb694130f71ad6a1e38e067620f817fa75`。

## 2026-07-14 第五标准批次 250 场导入完成

- batch005 五地区各 50 场已完成日期、详情来源、出马表和赛果正式导入，最终逐场验收 `0 errors`；新增 `2583 runners / 2364 results`。
- 最终详情候选 SHA-256 为 `269c65e646b11be0a1edef70c8c088e5b4b9a2b0a69527ca0efc6242cb84d6e3`；最终写前备份为 `pre-batch005-final-20260714_055856.dump`，SHA-256 `82908208d5a32f751c1b7c258c54e3ac66993798d27b66ff6d1405393a10ffa9`，`pg_restore -l` 通过。
- 生产累计为 `1291 imported / 29626 pending`、`13507 runners / 12167 results`；全部历史赛事仍为 draft，published 0，常驻历史网络/写入开关 false。
- batch006 前先建设每地区最多 250 场与独立 historical batch runner，完成 OpenSpec、工程审查、测试、实现、零问题 review 和部署验收后再继续抓取。

## 2026-07-14 国际新闻正文边界修复上线

- `tighten-international-article-content-boundaries` 已完成完整 OpenSpec 流程并部署 `main@514af8a2`；web/worker/beat 同为镜像 `sha256:954673cc74049d4b882e492ec29b072aba01aeb1a3ae440cc85415209c8a2f8a`。
- Sporting Life/TDN 现在只从可信正文容器解析，并清理站点框架、社交/推荐、编辑注、结果/活动链接、责任博彩、博彩推广、独立跳转 URL 与行动 CTA；赔率和赛事/马主专名中的博彩公司名称继续保留。
- 目标文章 `8086/8267/8316/8318` 已修复、重译并保持原公开状态/发布时间，QQ 零重复；随机抽检 `8306/8311/8326/8331/8336` 的保存正文、当前重解析和译文均通过，噪声标记为 0。
- 最终验证为目标测试 `27`、完整 `stable 1198` 项通过（跳过 1）；内外 healthz、目标详情、容器、空队列和日志正常。最新可读数据库备份为 `pre-main-514af8a2-20260714-051127.sql.gz`，SHA-256 `9fc72efba29ee8d32c9709665809d259ca49e47a217c43626c99b084d99d4b0a`。

## 2026-07-14 历史批次已耗尽地区门禁修正

- 标准批次进度护栏改为只比较本批后仍有未排除可抓 pending due 目标的地区；低容量地区抓空后退出比较，其他未完成地区仍严格遵守 100 场领先上限。
- 待审 selection snapshot 排除项继续保留总账和 remaining pending 分母，不会被技术修复伪装成完成；artifact summary 新增可抓分母和实际护栏地区，便于审批追溯。
- OpenSpec、测试优先实现和最终 review 已完成；专项 `66` 项、完整 `stable 1171` 项通过，`1` 项按设计跳过。代码已合入 `main@614f810e`，尚待可复现 AMD64 镜像切换；生产历史开关和公开展示保持关闭。

## 2026-07-14 第四标准批次 250 场导入完成

- batch004 五地区各 50 场已完成日期、详情来源、出马表和赛果正式导入；新增 `2563 runners / 2311 results`，500 个模块候选全部 applied，逐场验收无重复非空马号或重复名次。
- 最终详情候选 SHA-256 为 `ddd1f8256cef0b17aabc33ea66f7a0638a2d6498c2d23342daff8835b10a5156`；最终写前有效备份 SHA-256 为 `e50bd095bfa141ea0f05bf77fda68a508808dcddac4cbacb8fdb4ce3860e758a`。
- NSA 官方 PDF 不提供 `target_id=74171` 的马号，8 条 runners 与 7 条 results 保留空号并进入最终统一审核，不阻断后续批次。
- 226 场存在术语库暂缺中文映射的非阻断记录；原文出马表和赛果已完整入库，术语补全待总账数据收集完成后统一审核。
- 生产累计为 `1041 imported / 29876 pending / 0 ready`；本批全部 draft，历史 published 0，常驻写入/网络开关 false。batch005 等待 `main@614f810e` 镜像由生产协调线程切换。

## 2026-07-13 第三标准批次 250 场导入完成

- batch003 五地区各 50 场已完成正式导入，新增 `2638 runners / 2349 results`；写后累计 `791 imported / 30126 pending / 0 ready`、`8361 runners / 7492 results`，全部 draft、published 0。
- 2025 Hampton Novices' Chase 已按 Windsor 移师后的正式赛果收口为 `2025-01-19 / Windsor / 3m53y`，冠军 `Jingko Blue`，Warwick `ABANDONED` 不再视为年度 gap。

## 2026-07-13 标准批次重复选样门禁

- batch002 的 4 个 pending gap 曾再次占用旧 batch003 配额；该旧工件作废，不得审批。
- 批次命令已支持显式引用既有不可变 selection snapshot，在每地区上限前跳过旧目标并补入新目标；排除证据复制进新 artifact 并由 manifest 哈希绑定。
- 排除不会改变 gap 的产品状态或总账分母。实现已通过 42 项聚焦测试、完整 `stable 1157` 项回归和两轮 review，尚待提交、交付 AMD64 镜像并在生产只读重建 batch003。

## 2026-07-13 第二标准批次 246 场导入完成

- 2016–2025 第二标准批次 250 个目标中，246 场已完成日期、直接来源、出马表和赛果正式导入；五地区分别为日本 50、美国 48、香港 50、英国 48、法国 50。写后逐场验收 error 0。
- 生产历史累计为 `541 imported / 30376 pending`、`5723 runners / 5143 results`，541 个历史赛事仍全部未公开，published 为 0。常驻历史写入与网络开关保持 false。
- 4 个未导入目标继续保留为产品待审缺口：美国 2 场 `not run`、英国 2 场 `ABANDONED`。本批没有借技术导入自动改变其 `held/not_held/cancelled` 口径。
- 日期、来源、最终详情三阶段均有独立校验与写前备份；最终详情候选 SHA-256 为 `735ec0dacafd9c388adb678b93ab402e45f991cb0e143c89a6fe067e606fc459`。下一步继续生成同年代带后续均衡批次，不提前跳到更早年代。

## 2026-07-13 可复现主线镜像上线

- 历史源码已全部提交到 `main@304ebdb6`，不再依赖未提交构建上下文。源码完整回归为 `1128 passed / 1 skipped`。
- 生产 `web / worker / beat` 已切换到从干净 `main` 两次一致构建的 AMD64 镜像 `sha256:e7ab7af0061d7362ad0582224baffc79eda07bd6d8f6467bfa573f760853877d`；迁移、64 models、历史命令、安全开关、HTTP 和自然生产窗口验收通过。
- 法国/香港/英国各 `50` 场日期 target 仍为 `ready/draft`，详情未写，历史公开数为 `0`。镜像不可复现风险已清除，新闻调度/翻译的既有运营问题仍按下节跟踪。

## 2026-07-13 组合镜像恢复后窗口验收

- 最新完整窗口已证明 17 个生产来源全部抓取成功，发布/QQ 窗口无失败，最近日志无 schema 约束错误；镜像与 `0029` 不兼容造成的新闻写入故障已解除。
- 尚不宣称完全正常：当前调度会常态将跨 bucket 到期的旧窗口合并到最新窗口；3 篇翻译失败稿不会在当前安全关闭配置下自愈；JRA 有 1 个固定 PDF 解析跳过；28 条历史 CrawlJob `started` 脏记录会干扰观测。
- 当前来源是每 5 分钟检查、按上次完成时间滚动到期，15 分钟配置在线上体现为约 15–20 分钟，不能用“每个 bucket 都有 17 条”作为验收口径。

## 2026-07-13 法国新鲜度与多地区归属本地实现（历史状态）

- change 保持 `implementing`：本地已完成 TDN 日期查询、France Galop 可信时间、翻译失败有界恢复、多地区归属 run/manifest/灰度和运营可观测性，生产尚未部署。
- 三轮 review/返修后专项 `120` 项全部通过；完整 `stable` 回归 `968` 项通过，PostgreSQL 专项性能契约 `1` 项在 SQLite 按设计跳过，最终 review 无待修复问题。
- 配置默认保持归属 `off`、相关地区查询关闭、翻译自动重试关闭。该日 OpenSpec 为 `57/68`；双审与 `250/40/50` 门槛已由 2026-07-14 的单审及 `150/10/20` 决策取代，当前进度和资格以本文顶部为准。
- 因此代码已具备灰度基础，但功能尚未在线，也不能据本地合成测试宣称多地区归属已达到生产准确率。
- 终态翻译失败将向 `754652181@qq.com` 发送包含文章、失败分类和后台快速入口的邮件；生产部署仍须确认 SMTP 配置。测试群通过 `PushTarget.multiregion_test_enabled` 显式标记，默认关闭，避免 `web_test_groups` 阶段影响正式群。

## 2026-07-13 法国新鲜度与多地区归属方案完成工程评审（历史状态）

- OpenSpec change `fix-france-news-freshness-and-multiregion-attribution` 当日已完成两轮 full review 并进入 `reviewed`；后续代码已安全关闭部署，当前仍待生产 dry-run 与 Shadow 验收。
- 方案覆盖 TDN 日期倒序抓取、France Galop 可信发布时间、瞬时翻译失败有界重试、多地区归属准确度和分阶段上线。
- 上线前必须通过版本化 gold set、真实生产 dry-run、250 篇批处理性能门槛和单次发布/QQ 交付幂等测试；归属默认 `off`，相关地区查询默认关闭。

最新生产状态：提交 `f221c7df` 已部署。英文术语命中级上下文门禁、运行账本和高性能重处理已在线，迁移 `0028` 已应用，`web/worker/beat` 统一处于 `shadow`。`2026-07-12` 已对四个锁定 dry-run 执行受控 commit，并由两个自然窗口公开 24 篇；复核发现其中法国 5 篇来自 TDN France 日期修复前的污染批次，已撤回该批次全部 20 篇以阻止再次复活，最终保留香港 7、英国 3、美国 9，共 19 篇，QQ 交付 0。至少观察 24 小时且人工抽检通过前不切全局 `enforce`。赛事历史主干能力和 P0 马资料补全基础代码继续在线，网络补全、P0 全量来源写入、多地区归属开关和自动首次发布仍保持关闭。

法国新闻低产出排查确认不是 3 天门禁过严，而是 TDN 关键词入口按相关度返回历史稿、France Galop 未解析真实发布时间、两篇最新稿因翻译供应商 `429/503` 且没有周期重试，以及多地区归属开关仍关闭四项叠加。TDN 按日期 posts 搜索在 `2026-07-09` 以来可找到 `12` 篇宽口径候选；本次仅记录证据，尚未改代码、重试文章或开启归属。

上述四类问题已纳入 OpenSpec change `fix-france-news-freshness-and-multiregion-attribution`。该 change 同时要求提高多地区归属准确度，以真实五地区 Gold Set 和明确 precision/recall/过度扩散门槛控制生产资格，并按 shadow、仅写入、网页/测试群、72 小时回填、正式群五阶段启用。该段为早期规划记录；当前代码已部署为安全关闭，159 条首发 Gold 已达标，生产多地区开关仍为关闭。

历史首批45个目标当前为 `33 imported / 3 ready / 9 pending`。法国2012/2025六场已通过独立补充来源审批链导入 `70` 条出马和 `41` 条赛果；36个已materialize历史赛事仍全部为draft，历史回填与网络开关继续保持false，线上未公开。下一步补法国2000、英国2000和美国2000/2012来源缺口。

历史赛事回填已完成1998–2026全部身份审核：`102` 个同名簇临时Key先归并为 `58` 条正式赛事线，随后 `15` 对高相似名称合并为名称变体，Prince of Wales's与Princess of Wales's保持独立。最终v12总账包含 `30,917` 个年度目标和 `2,334` 条正式赛事线。京都雌马2005–2009、Bristol 2001届、Louisville 2008、Keeneland First Lady 2000和NYRA Matron 2018等异常已修正；Ascot约3m金杯线中文主名确认为 `阿斯科特秋季金杯让磅障碍追逐赛`。原始v10和同名簇v11均保留作审计。生产已开始按批准总账分批写入详情，历史公开开关继续关闭。

五地区详情抓取来源口径已补充：日本 JRA/netkeiba/JBIS，中国香港 HKJC，英国 Racing Post/Sky Sports/BHA，法国 France Galop/PMU，美国 Equibase/BRISnet/DRF/BloodHorse及障碍赛NSA。后续抓取必须分别处理赛前声明出马表、实际出走、退出马与赛果，不能互相替代。

`2026-07-12` 的审前逐届证据表保留 `687` 个原始年度行、冠军 `474` 行和1号马 `164` 行，现仅作为审计快照；其同名簇结论与京都雌马冲突已由 `2026-07-13` 的结论版和 v11 总账取代。生产现有 `992` 场赛事中，出马表存在覆盖约 `50.9%`、赛果存在覆盖约 `50.7%`；以 `503` 场已完赛赛事为分母时，两项覆盖均为 `100%`。

## 1. 项目背景

目标是构建一个面向中文用户的日本赛马新闻系统，形成：

`采集 -> 翻译 -> 自动分流/改写 -> 人工编辑 / 自动发布 -> 发布 -> QQ 群自动推送`

当前阶段重点是让站点进入“可持续自动更新”的内容运营阶段，同时继续保证真实上线稳定性。

## 2. 当前技术方案

- 后端：`Django + Celery`
- 数据库：`PostgreSQL / SQLite`
- 队列：`Redis`
- 翻译：`OpenAI-compatible`（已支持 SiliconFlow）
- 媒体存储：`local / OSS` 双后端
- 推送：`OneBot`
- 部署：`Docker Compose`

## 3. 已完成（业务能力）

- `netkeiba` 与 `JRA` 采集
- 新闻/图片/快照/术语/推送/日志等数据模型
- 翻译状态机与失败重试
- 未收录马名保留日文、翻译完整性校验
- 未收录马名翻译保护已增强：使用占位符保留原文名，模型仍漏保留时记录 warning 但不阻断整篇翻译
- 外部马名索引识别链路已部署生产：`ExternalHorseAlias` 可参与马名识别、翻译保护、发布校验和候选发现；外部马名只用于确认“这是马名”，不批量写入正式术语库 `TermEntry`
- 术语工作台与批量导入
- 候选池、编辑台、发布流
- 自动化内容运营 MVP：
  - 自动评分分流 `auto / manual / ignored`
  - AI 编辑改写稿与基准翻译稿双层保存
  - 一致性校验、批量自动发布、自动化日志
  - 自动发布批量规则：常规每批 4 篇，周日北京时间 13:00-16:00 每批 10 篇
  - 邮件通知 MVP 与通知日志
- 前台信息流与详情页已升级为公开站点专用 Web + 移动 H5 资讯流
- QQ 推送链路：已新增并部署自动推送实现，支持重点优先/全公开、多群、去重、有限重试、OneBot 业务失败识别、OneBot 离线发送前预检、`sending` 陈旧恢复、后台交付记录和按群限速；生产 OneBot / NapCat 网关已登录并在测试群验证发送，当前生产 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 已生效。
- 抓取新鲜度与来源健康：netkeiba 新着顺 / 访问量榜 / 注目数榜已切换为每小时 `00/16/26` 分错峰抓取，JRA 无年份日期解析已修复，后台来源健康摘要已上线
- 榜单来源提升：已部署 `netkeiba:latest -> access/attention` 主来源提升，访问量榜和注目数榜不互相覆盖，并为 QQ 榜单推送暴露 `source_elevated` 信号。
- 榜单重点推送：已部署 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`QQ_PUSH_SCOPE=high_value_only` 下只推 netkeiba 访问量榜 / 注目数榜且无 blocker 的公开文章。
- 公开文章 ID URL：已部署公开详情主路径 `/news/<article_id>/`，非纯数字旧 slug URL 跳转到 ID URL，QQ 消息链接不再包含标题全文。
- 赛事日历 / 年度赛事页 MVP：已部署生产 `f3c4c46`。已实现 `RaceEvent` 产品层、公开 `/races/` 赛事日历、年度详情页、后台 `/admin/race-events/` 工作台、CSV 种子导入、候选资料写入/应用、新闻自动/手动关联和人工移除保护；生产已导入 5 条 P0/P1 赛事种子与 10 条别名，第一版不建设马匹数据库或完整赛果库。
- 马匹详情页 MVP：`2026-07-10` 已更新部署到生产 `65988b0`，OpenSpec change `horse-profile-page-mvp` 已归档到 `openspec/changes/archive/2026-07-08-horse-profile-page-mvp/`，正式规格已同步到 `horse-profile-pages`、`horse-profile-data-completion` 和 `public-home-info-feed`。新增 `HorseProfile`、候选资料、参赛履历、马-赛事/新闻关联和匿名关注模型；公开 `/horses/`、`/horses/<id>/`、`/horses/follows/` 已实现，后台 `/admin/horse-profiles/` 支持审核发布、字段锁定、候选 diff、参赛履历和新闻关联维护。P0 马已默认生成 `21596` 个草稿，前台默认不可见，管理员可强制发布空壳；外部补全走本地缓存 dry-run artifact + 人工审核 commit，公开请求路径不访问第三方。`2026-07-08` 已补审查修复：全量 dry-run 默认不截断、马名和术语匹配大小写不敏感、关注面过滤未发布马匹、补全 commit 保留写库前 diff、资料保存不能绕过发布审计、按地区输出补全比例、stale 扫描任务不扩大范围。生产全地区补全 dry-run artifact 位于 `runtime/horse_profile_completion/dry-run-20260708_041343/`，当前完整二代 `0/21596`，未补全占比 `100%`，主要原因是本地外部缓存无匹配或来源不可用；本次未 commit 补全结果。线上已发布样本 `春秋分` `/horses/13113/` 与 `北十字星` `/horses/3873/`，均为完整二代血统，参赛履历分别 `10` / `11` 条，相关新闻各 `5` 篇；浏览器验收确认详情页、新闻 tag 点击、关注 / 取消关注、关注页新闻流、英文大小写搜索和移动端一级导航 / 地区筛选布局均通过。
- P0 马资料补全专项：`2026-07-10` 已在独立 worktree `/Users/mentianlu/.codex/worktrees/p0-horse-info-completion/umanews` 创建并重写 OpenSpec change `complete-p0-horse-profile-data`，并对齐旧线程最终提交 `d78fab0`。新版 P0 范围扩展为“当前 active 且有中文译名的 horse `TermEntry` + 五大地区全部历史与未来重点赛事参赛马”，重点赛事等级限定为 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ`；暂无中文译名的 P0 马允许补全和人工发布，翻译命中时保留原文。首批验收为日本、中国香港、英国、法国、美国各 10 匹完整资料马，完整资料硬门槛包括 P0 来源证据、基础事实字段、二代血统、完整赛事履历、主胜鞍、来源 URL 和人工审核记录。计划工程审查已重新完成，`.openspec.yaml` 当前 `phase=reviewed`。核心骨架已完成三轮审查返修：马匹地区不属于身份键，来源内 external horse ID 可直接定位；跨来源归并数据库已有马必须完整唯一命中经术语库多语种归一的“马名 + 父名 + 母名 + 出生年份”，歧义写候选并每天通知管理员；同一原名对应多个马术语时保留原文且禁止任意替换。管理员可从冲突筛选列表进入详情填写处理说明；P0 普通同步只增量刷新，显式全量对账才执行 revoked，待处理歧义不会误撤销仍在输入中的来源；artifact 使用顶层/行级/模块级审核；完整资料按最新模块审核结论、在役马同步新鲜度、退役马最新赛绩、逐条赛绩来源和四模块审计判断。定向 P0 回归 `35` 项、系统/迁移检查和 OpenSpec 校验通过；完整 `stable` `549` 项仅剩 `3` 个随日期漂移的既有 TDN France 时效 fixture 失败。当前尚未执行五地区真实 adapter 扩展、每地区 10 匹 dry-run、生产 commit 或人工公开验收。
- P0 第四轮审查返修：同场同名参赛马改按马号/来源身份拆分，URL 暂缺的仍存在来源不会在完整对账中误撤销；非 pending 候选不能通过通用应用入口改为 applied；人工完整审核必须提供明确整匹马资料 URL。身份歧义采用专用 `HorseIdentityConflict`，可在无 profile 时保存多个候选术语、身份原始证据和人工解决状态；resolved 必须选择最终资料页，后续同步按人工结论建立 P0 来源。每日运营通知链接到 Django Admin pending 列表。定向术语/P0/旧马匹页回归 `79` 项通过；完整 `stable` `556` 项仅剩 `3` 个随日期漂移的既有 TDN France fixture 失败。
- P0 第五轮审查返修：`HorseP0Source.participant_key` 持久化同场参赛身份，runner/result 按马号、来源 ID、赛事内唯一马名配对；无外部 ID 的同场同名马可按不同马号稳定拆分，重复同步不增生，身份纠正保留 revoked 旧绑定。P0 artifact 与通用人工候选统一调用共享赛绩幂等 upsert，并强制完整来源名/URL。定向旧马匹页/P0 回归 `59` 项通过；完整 `stable` `560` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。
- P0 第六轮审查返修：参赛键从 external identity 升级到马号时迁移既有 active 来源，不保留重复 active；runner/result 非空马号冲突时禁止按 external ID 降级合并并写身份冲突证据；后台手工新增/编辑赛绩统一走共享幂等服务，编辑后重算键且来源 URL 双层必填。定向旧马匹页/P0 回归 `63` 项通过；完整 `stable` `564` 项仅有既知 `3` 个 TDN France 固定日期 fixture 失败；并发争用按用户决定不在本轮处理。
- P0 第七轮审查返修：同一来源 identity 对应多个马号时，runner-result、两条 runner、两条 result 都汇总成单条身份冲突并停止写 active 来源；后台编辑保留 importer 的 `source_refs/raw_payload`，修改 diff 写操作日志；完整度与后台待刷新筛选统一使用配置化新鲜度截止日期。定向旧马匹页/P0 回归 `67` 项通过；完整 `stable` `568` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。
- P0 第八轮审查返修：马号冲突 resolved 必须同时选择最终资料页和候选马号，后续只绑定该马号记录；冲突 evidence 保存全部成员与 URL，完全无 URL 也落库，fingerprint 排除可变 URL；imported 赛绩人工编辑继续沿用 external ID 和原 source namespace 幂等键。定向旧马匹页/P0 回归 `69` 项通过；完整 `stable` `570` 项仍仅有既知 `3` 个 TDN France 固定日期 fixture 失败。
- P0 第九轮审查返修：迁移回填同时读取 `raw_payload/source_refs` 的 external ID；共享任一身份键的参赛记录按完整连通组生成单条冲突，交叉身份不会丢成员；resolved 马号必须具备成员或赛事 URL，URL 后续缺失时同步恢复 pending、清空无效选择并记录原因，确保继续通知管理员。定向回归 `96` 项通过；完整 `stable` `573` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败，当前仍未部署。
- P0 第十轮审查返修：人工 P0 来源按马匹独立 upsert 并增加唯一约束；resolved 马号成员无法定位时统一恢复 pending 并重新通知；旧空键赛绩优先按 external identity 接管或报告多记录歧义，不再因事实字段变化新增第三条。定向回归 `99` 项通过；完整 `stable` `576` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败，当前仍未部署。
- P0 连续审查收敛：按用户要求持续执行审查与返修，第五轮纯审查无可操作发现。旧赛绩来源命名空间支持从证据回填并统一大小写/空格，external ID 统一去空格，importer 与后台编辑都会阻断多条旧 external identity；补全队列按真实资料缺口和刷新需求排序，再综合人工、候选、近期新闻、重点赛事、外部身份和术语优先级，完整马不再挤占未完成样本限额。OpenSpec `6.2` 因五地区 adapter/artifact 尚未完成而恢复未勾选。定向回归 `104` 项通过；完整 `stable` `581` 项仅剩既知 `3` 个 TDN France 固定日期 fixture 失败，当前仍未提交或部署。
- 2026 五地区重要赛事填充：已按官方来源导入日本 JRA/NAR、香港 HKJC 当前公开 2025/26 马季内香港 G1/G2/G3、美国 TOBA Grade 1/2/3、英国 BHA Flat Group 1/2/3 与 Jump 2026 年 1-4 月 Grade 1/2、法国 France Galop Groupe I/II/III。当前生产 `RaceEvent=995`、`RaceEventAlias=3277`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`。剩余缺口是 HKJC 尚未公开 2026/27 年末香港本地分级赛日期，以及英国 Jump 2026 年 10-12 月仍需下一季官方书或其他官方结构化来源。
- 赛事信息编排工具：`2026-07-11` 已完成第四轮技术返修，在既有独立应到清单、run 级候选汇总、共享请求预算和全阶段 state 基础上，新增实际 apply scope 对账与逐组合确认、按哈希命名的 approved candidate、importer 执行时 `--expected-sha256` 复核、严格 adapter manifest，以及 `complete_with_warnings` 行状态。独立赛事编排专项测试 `41` 项、完整 `stable` 测试 `581` 项、Django check 和迁移漂移检查均通过；当前尚未运行真实抓取、未写生产数据。
- 国际赛马资讯扩展：已部署多地区新闻源、公开首页地区 tab、多语言术语别名、群级 QQ 地区配置和 HKJC 受控导入；生产第一版已启用 `Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`，其中 `BHA` 因生产探测返回 `403` 暂停启用。
- 全球赛马数据库抓取能力：香港 HKJC、英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 的受控 importer 能力已部署；`2026-06-30` 已开始香港 HKJC 慢速真实 dry-run，最新 plan 为 `146` 场且前两场完整 dry-run 成功，仍未执行生产 `--commit`。
- 香港 HKJC 长窗口 dry-run：`2026-06-30` 已按用户要求启动到 `2024-07-01` 的慢速后台抓取计划，plan 共 `1496` 场；为部署多地区新闻常态生产，当前 dry-run worker 已暂停在 `hkjc-slow-dryrun.state=92`，仍未写正式表。
- 多地区正式术语库补齐：`2026-07-04` 已导入 WP Stud 香港/来港社区马名 `210` 条、HKJC 当前本地马 A-Z 官方译名 `1258` 条，并从 HKJC 本地赛果回溯香港历史马名、骑师名和赛事名到 `2026-07-04`。`2026-07-05` 已继续完成 HKJC overseas 官方 Race Card/QIDS 术语回溯，覆盖 `2024-01-01` 至 `2026-07-04`，正式导入海外 `horse / jockey / race` 候选 `7691` 条中的新增/更新项；同时补齐当前发现的 WP Stud 赛事、骑师和马场社区术语，正式新增 `1891` 条。`2026-07-06/07` 已完成最终清洗与 WP Stud HorseList 全量马名补齐：最终 `seed_candidates_final.csv` 共 `11257` 行，生产正式导入新增 `1169`、更新 `10088`、错误/跳过 `0`，并修复既有马名国别后缀和赛事年份标记脏数据。当前生产正式术语为 `TermEntry=16558`、`TermAlias=19293`，active 马名国别后缀术语 `0`、active 赛事年份标记术语 `0`；`source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，HKJC 官方仍保持最高优先级，WP Stud 只作为社区来源和人工审核佐证。
- HKJC 日语 alias 合并与文章术语回填工具：`2026-07-07` change `hkjc-ja-alias-article-backfill` 已实现并部署生产 `a65c1ed`。新增 `merge_hkjc_ja_aliases` 用于把同中文目标的日语主术语安全并入 HKJC 英文概念并停用冗余日语主术语；新增 `backfill_article_terms` 用于对已发布文章中文字段执行可审计术语回填。生产已合并 `112` 条 HKJC 日语 alias，文章回填扫描 `713` 篇日文已发布文章并更新 `29` 个字段、跳过 `2` 个人工字段；`/news/7117/` 已确认显示 `欢快舞步`。
- 多地区新闻常态生产：`operate-multiregion-news-production` 已实现、部署生产并归档；`2026-07-01` 已继续归档 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send`，生产服务器运行 `8c83708`，已具备只读审计、通用 enabled 新闻来源轮询、非日本默认人工审核、地区/来源自动发布灰度、后台地区生产概览、QQ 国际新闻地区标签和运行手册。当前 `NEWS_SOURCE_POLL_ENABLED=true`，轮询覆盖五个地区，每轮最多 12 个来源；非日本自动发布 allowlist 已开启香港、英国、法国、美国四个地区并保留每日小上限护栏，正式群仍需显式配置地区。
- 法国新闻源扩展：`2026-07-07` OpenSpec change `expand-france-news-sources` 已部署生产提交 `bfc3445`。新增 `tdn_france_broad` 英文补充来源，生产只读探测 accepted：HTTP `200`、列表 `20`、详情样本 `5`、详情错误 `0`、重复 `0`。生产已启用 `NewsSource#21`，`enabled=true`、`production_approved=true`、有效轮询 `15` 分钟；发布白名单已加入 `tdn_france:access` 和 canonical 入库使用的 `tdn:access`。真实抓取验证已入库法国新来源文章 `4` 篇，均完成翻译并进入正常人工复核，当前无来源白名单或抓取失败阻断。
- 英文术语门禁误挡修复：`2026-07-07` OpenSpec change `fix-english-term-gate-region-filter` 已部署生产提交 `bfc3445`。英文发布校验第一版改为同地区 + 全局术语范围，配置化高歧义英文词降级为 warning；新增近期误挡文章重处理命令和生产审计 `gate_issues` 摘要。上线后 dry-run 验证：香港、美国、法国最近 3 小时无可释放 `core_term_missing` 候选；英国有 `1` 篇候选但仍是真实核心术语缺失，未执行 commit。
- 非术语门禁误挡修复：`2026-07-10` 本地已按候选池 raw 分类检查 `is_likely_term=yes/no/review`。`yes` 共 `369` 条均已存在正式术语 ID，生产只读核对对应 `350` 个唯一 `TermEntry` 全部存在且 active，无需补库；`no` 共 `89` 条已确认为非术语，代码新增 `MULTIREGION_TERM_GATE_IGNORED_SOURCE_TERMS` 默认列表，发布校验命中后写 `non_term_gate_ignored` / `info` 且不生成核心术语 blocker；`review` 类暂不批量建词。当前已通过本地目标测试和 `manage.py check`，尚未部署生产。
- `2026-07-07 21:00` 线上回归复核：生产 `HEAD=dcb9b90`，服务健康；`tdn_france_broad` 再次探测 accepted，生产自然窗口已通过 `source_config=21` 入库法国文章 `10` 篇，其中 `9` 篇已翻译、`1` 篇翻译中。该来源当前 `CrawlJob#9355` 仍在运行，Celery 日志显示模型接口持续 `200 OK`，结论为单轮处理耗时偏长但仍在推进；最近 90 分钟发布/QQ 窗口均有成功账本和明确 0 原因。英文门禁 dry-run 未发现可释放误挡文章。
- `2026-07-07` 已修复并重新启用 `tdn_france_broad`：该来源此前使用 TDN WordPress search API，返回历史相关性结果且不带发布时间，adapter 将缺失日期兜底为当前时间，导致 2020/2022/2023/2024 旧文被当作当天新闻入库并有 5 篇自动发布。OpenSpec change `fix-tdn-france-search-date-freshness` 已部署生产 `ad587ce`，现在会二次读取 TDN post API 的真实 `date_gmt/date`，缺失日期或超过 3 天新鲜度窗口的条目会跳过且写入抓取摘要。已将误发布旧文 `7255/7263/7264/7265/7271` 撤回公开，公网详情均返回 `404`；生产 `NewsSource#21` 已恢复 `enabled=true`、`production_approved=true`。线上真实抓取 `CrawlJob#9445` 成功，`new_count=0`、`seen_count=0`、`skipped_count=80`，无新增旧文。
- 后台术语运营：候选详情页和文章编辑台支持原文选区快速加入术语库；新增术语成功后可一次性将该术语应用到当前文章已有中文稿
- 前后台移动端适配

## 3.1 已完成并部署生产（体验升级）

- 公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`
  - Web 端已实现：轻导航、主头条、普通新闻流、右侧热门/重点辅助模块
  - 移动 H5 已实现：轻顶部、轻量头条、高密度左文右图新闻列表
  - 实施方式：严格 TDD，按可测试行为逐轮执行 RED -> GREEN -> REFACTOR；热门代理使用有限候选集与批量快照读取
  - 首版不做原生 App、手工置顶、搜索频道、专题、赛事日历、站内评论或站内浏览量
  - 当前状态：本地实现、Django 测试、OpenSpec 校验、桌面/移动浏览器验收和 OpenSpec 归档已完成；`2026-06-22` 已通过 PR #1 合并并部署到生产 `e834f58`
- 移动端首页密度 follow-up：
  - 已小幅压缩移动端头条区域，隐藏头条摘要并收紧顶部间距
  - 390px 浏览器验收中，首屏普通新闻卡可见数量从生产基线的 3 条提升到 4 条
  - 当前状态：`2026-06-23` 已通过 PR #2 合并并部署到生产 `04e2ee9`

## 4. 已完成（上线准备）

### 4.1 生产配置

- 安全配置：`DEBUG`、`ALLOWED_HOSTS`、`CSRF_TRUSTED_ORIGINS`、Cookie、HSTS、反代头
- 日志配置：控制台 + 可选文件日志
- 数据库配置：支持 RDS 参数（超时、连接复用、sslmode）

### 4.2 后台入口与路由

- 后台入口：`/admin/`
- 后台登录：`/admin/login/`
- Django Admin：`/django-admin/`
- 兼容跳转：
  - `/login/` -> `/admin/login/`
  - `/console/` -> `/admin/`

### 4.3 OSS 媒体存储

- 新增 OSS 存储后端：`stable.services.oss_storage.AliyunOSSStorage`
- 图片本地化、封面上传统一走 `default_storage`
- URL 解析兼容本地与 OSS

### 4.4 部署资产

- 标准模式（RDS）：`docker-compose.prod.yml`
- 低成本模式（本机 PG）：`docker-compose.prod.lowcost.yml`
- Compose 兼容包装脚本：`deploy/docker/compose-wrapper.sh`
- Docker 与启动脚本：
  - `Dockerfile`
  - `deploy/docker/start-web.sh`
  - `deploy/docker/start-worker.sh`
  - `deploy/docker/start-beat.sh`
  - `deploy/docker/wait_for_services.py`
- Nginx：`deploy/nginx/nginx.conf`
- 部署脚本：
  - `deploy.sh`
  - `deploy_lowcost.sh`
  - `deploy/deploy.sh`
  - `deploy/deploy_lowcost.sh`
- 回滚脚本：
  - `deploy/rollback.sh`
  - `deploy/rollback_lowcost.sh`
- 备份恢复脚本：
  - `deploy/backup_db.sh`
  - `deploy/upload_backup_to_oss.py`
  - `deploy/restore_db.sh`

### 4.5 文档资产

- [生产部署指南](E:/Codex/docs/deploy_production.md)
- [阿里云香港手把手指南](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
- [回滚指南](E:/Codex/docs/rollback_guide.md)
- [备份与恢复指南](E:/Codex/docs/backup_recovery.md)
- [生产检查清单](E:/Codex/docs/production_checklist.md)
- [后台使用说明](E:/Codex/docs/backend_usage.md)
- [PRD 归档说明](E:/Codex/docs/PRD/README.md)

### 4.6 Codex 协作资产

- 当前规则入口：`AGENTS.md`、`docs/codex_workflow.md`
- 新任务持久规格：`docs/changes/<slug>/`
- 工程计划审核 fallback：`.codex/skills/plan-eng-review`
- Codex 领域代理：`application`、`integration`、`operations`
- Codex 只读审核代理：`reviewer`、`security-scanner`
- OpenSpec legacy 配置与历史/在途 artifacts：`openspec/config.yaml`、`openspec/specs/`、`openspec/changes/`；相关 skills 与 workflow-spine 已停用，不作为新流程入口或门禁
- 当前流程为“探索 -> spec/design -> 方案审核 -> 测试先行 -> 子代理实现 -> 新子代理 `/review` -> 用户授权后发布”
- `start-hkjc-data-import-and-global-spikes` 已完成 `/plan-eng-review`、TDD 红灯测试、最小实现、read-only spike、生产部署、验证和归档；生产服务镜像来自 `b0361cf`。2026-06-26 已在生产执行一次 HKJC fixture 样本 commit（`run_id=1960`），写入 `1` 场、`2` 条报名、`2` 条成绩、`2` 匹马和 `4` 条别名；该样本不来自真实网络抓取，也不生成公开比赛页。英法美三地当前均为 `needs_more_spike`。正式规格已同步到 `openspec/specs/global-racing-data-import-readiness/spec.md`；后续如要正式导入英法美或真实 HKJC 网络适配，应另起 change。
- `connect-real-global-racing-databases` 已创建并通过 OpenSpec 严格校验；目标按香港、英国、法国、美国顺序接入真实赛马数据库，每地抓最近 2 个月赛事和涉及马匹详情后停止。当前香港阶段已完成 HKJC 官方 HTML 单场真实 dry-run 和隔离 SQLite commit：`HK20260624HV01` 解析并写入 `1` 场、`12` 条报名、`12` 条成绩、`12` 条英文别名；并已完成 recent-days/date-range 小范围真实链路，`--recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1` dry-run 请求 `4` 次官方页面，返回 `completion.is_complete=false`、`meetings_found=28`，隔离 SQLite commit 写入 `1` 场、`12` 条报名、`12` 条成绩、`1` 匹马 profile 和 `12` 条别名，重复执行正式对象计数不增长。HKJC 追加 plan-only 批次预检：过滤 overseas `S*` racecourse 后，最近 60 天本地香港 `HV/ST` 比赛为 `144` 场，可按每批 `20` 场拆为 `8` 批；已通过 `--skip-races 20` 真实 smoke 证明日期范围后续批次可从第 21 场开始，并通过 `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 真实 smoke 证明可按指定 race_id 精确批次只请求目标比赛和受限马匹详情。英法美已追加 `18` 次只读入口复核：英国 `Sporting Life + BHA` 可行性最高，美国 `Equibase` 入口更具体但 chart/PDF 仍需 fixture spike，法国 `France Galop` 仍未定位稳定结构化查询参数。下一步仍需部署后执行 HKJC 生产最近 2 个月全量 dry-run/commit，香港完成后再按顺序进入英国正式 parser/importer TDD。
- 生产 HKJC 真实网络运行状态：`connect-real-global-racing-databases` 当前实现已部署到生产 `04c0444`，备份 `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz` 通过校验，部署后 check/healthz/小样本 dry-run 通过，生产 plan-only 仍为 `144` 场、`8` 批；第 1 批 full dry-run 曾在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout 中断，该次未 commit、未写表，HKJC 锁为空且表计数仍为上次 fixture 样本 `1/2/2/2/4`。已按 TDD 补 transient timeout retry 并重新部署，随后将前 6 个 plan-only 批次拆成 24 个 5 场小批次 dry-run，均 `completion.is_complete=true`，累计覆盖 `120` 场、`1522` 条 entries、`1522` 条 results 和 `1522` 个 horse profile 请求，当前停在生产 commit 前确认点。
- `connect-real-global-racing-databases` 的本轮目标已在 `2026-06-27` 调整为确认四地真实抓取能力可用，并按该口径完成：HKJC 生产真实 dry-run 证据成立，UK / France / US 少量真实 proof 证明 Sporting Life、Geny、Horse Racing Nation 的赛事、赛果和马匹详情入口可访问并可解析；新增 importer、审计命令、batch command 渲染器、fixtures、OpenSpec 规格/归档和 proof 文档已从干净 `origin/main` 基线整理为独立上线包。代码提交 `93b7007` 已部署生产，check/healthz/首页/命令入口/proof-only 审计和导入锁状态均通过；最近 60 天完整大量爬取和生产 `--commit` 保持为后续单独执行窗口。

## 5. 当前验证结果

- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，147 项
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项
- `openspec validate use-external-horse-alias-for-name-recognition --strict`：通过
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项
- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过
- `openspec validate --all`：归档前通过；同步正式规格并归档后再次通过
- 公开首页资讯流浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；移动普通卡约 128px 高，无横向溢出，图片加载正常
- 公开首页资讯流生产验收：服务器 HEAD `e834f58`，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，首页引用 `/static/stable/public.2eec24723b45.css`，390px 移动端普通新闻卡约 `128px` 高且首屏头条后可见 3 条普通新闻
- 移动端首页密度 follow-up 生产验收：服务器 HEAD `04e2ee9`，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，首页引用 `/static/stable/public.9aaf4b105424.css`，390px 视口下头条约 `257px` 高，第一张普通新闻卡 `top=388`，首屏可见 4 条普通新闻卡，普通卡仍约 `128px` 高，无横向溢出
- 自动发布门禁优化生产验收：服务器 HEAD `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用，`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true` 已生效，`http://umafans.run/healthz/` 与 `/` 均返回 `200`
- 三个运营改造 change 生产验收：服务器 HEAD `7f54f13`，`web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`；运行态确认 netkeiba 新着顺 / 访问量榜 / 注目数榜调度分钟为 `00/16/26`，OpenSpec 归档后 `openspec validate --all` 通过
- 外部马名索引识别链路生产验收：服务器 HEAD `35b0866`，`manage.py check` 通过，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `/` 均返回 `200`；生产只读 smoke test 确认 `ExternalHorseAlias=11521`，`ロブチェン` 可识别为 `external_alias`
- 榜单重点 QQ 推送与公开文章 ID URL 生产验收：服务器 HEAD `00e4bd4`，生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；`manage.py check` 通过，`http://umafans.run/healthz/` 与 `/` 均返回 `200`，抽检 `/news/<article_id>/` 返回 `200`，旧 slug URL 返回 `302` 并跳转到 ID URL
- 榜单重点 QQ 推送相关 OpenSpec 归档：`add-qqbot-auto-push`、`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls` 已归档并同步正式规格，归档后 `openspec validate --all` 通过
- QQ Bot 登录态恢复与离线防护本地验证：2026-06-26 排查确认 NapCat 登录态失效会导致 OneBot 无法发送；重新扫码登录后 `/get_status online=true`、测试群消息发送成功，并恢复 `QQ_PUSH_ENABLED=true`。本轮补充自动推送发送前 OneBot 在线预检，离线或状态检查失败时不调用发送接口、不增加 `attempt_count`，完整 `stable` 测试通过 268 项。
- QQ Bot 离线防护生产验收：服务器 HEAD `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`；部署后 `manage.py check` 通过，本地和公网 `/healthz/` 均返回 `200`，worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`BotPusher().is_online()` 返回 `(True, '')`，测试群 `1026525240` 发送部署验证消息成功。
- `docker compose -f docker-compose.prod.yml config`：通过
- `docker compose -f docker-compose.prod.lowcost.yml config`：通过

说明：本地 `.env` 若指向不存在的 `postgres@db`，测试建库会失败，这是本地环境问题。

## 6. 当前待办（项目级摘要）

- 观察公开首页资讯流生产运行，重点看首页、详情页、图片、静态资源和移动端首屏密度
- 下一轮数据续抓建议优先补结构化赛事数据：先补英国 / 法国赛事详情与五地区历届冠军，再恢复 HKJC 长窗口 dry-run，最后按 `global_racing_full_crawl_runbook` 推进英国、法国、美国最近 60 天外部赛马数据库完整 dry-run。`2026-07-10` 已只读校验英法赛事详情候选：英国基础赛事 `202` 场、已完赛 `123` 场、规范候选 `122` 场；法国基础赛事 `173` 场、已完赛 `74` 场、规范候选 `74` 场，原始 ZEturf 候选 `80` 条中的 `6` 个重复 slug 已在规范包中去重。随后生产复核显示英法详情已经正式导入，英国 `Jane Seymour Nov. Hurdle` 在线状态为 `cancelled` 不需补赛果；本次仅修复 `GRAND PRIX DE SAINT-CLOUD` 历史冠军当前年残留误配，将 `2026` 冠军从 `ZELMAN` 修为 `CALANDAGAN`，生产备份为 `backups/db/pre-race-detail-gpsc-history-repair-20260710_025949.sql.gz`。
- 赛事日历正式填充：`2026-07-06` 已按“官方源优先、本地语言优先、先 CSV/JSONL dry-run 再正式导入”的流程批量写入 2026 目标地区重要赛事。生产当前 `RaceEvent=995`、`RaceEventAlias=3277`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`。已完成基础表：日本 JRA 中央重赏 `140` 场、日本 NAR/交流ダートグレード `46` 场、香港 HKJC 已公开 2026 分级赛 `19` 场、美国 TOBA Grade 1/2/3 `411` 条、英国 BHA Flat Group 1/2/3 `138` 场、英国 BHA Jump 2026 年 1-4 月 Grade 1/2 `64` 场、法国 France Galop Groupe I/II/III `173` 条。详情表已导入日本、香港、美国当前可用批次：JRA 已完赛中央重赏 `74` 场、NAR 已完赛 `20` 场、NAR `2026-07-08` 已公布赛前出走表 `1` 场、HKJC 已公开香港分级赛 `19` 场、美国 TOBA 已完赛 Grade 1/2/3 `195` 场；生产 `RaceEventRunner=3260`、`RaceEventResult=2977`、`RaceEventHistoryWinner=0`。`取消/除外/中止/空白着顺/WV` 保留在出走表状态中，同着用唯一排序位写库并在 `source_refs.official_finish_position` 保留官方名次，前台已热补丁为展示官方名次。美国 Equibase chart 当前仍返回防护页，因此美国赛果暂用 HRN track-day 可见结果顺序；Kentucky Derby / Oaks 等 HRN 未公开结果块的场次只显示出走表。剩余详情缺口：JRA 未来 66 场、NAR 未来 25 场需等官方出走表或赛果发布，英国/法国详情来源解析，以及五地区历届冠军。
- 多地区术语库与外部马名索引：`2026-07-03` 生产只读核对显示，正式术语库和术语候选池仍主要是日文。`2026-07-04` 至 `2026-07-07` 已连续导入术语种子：第一批 fixture 候选、WP Stud 香港/海外来港社区马名、HKJC 当前本地马 A-Z 官方英文马名、HKJC 本地赛果 `2024-01-01` 至 `2026-07-04` 候选、HKJC overseas `2024-01-01` 至 `2026-07-04` 官方 `horse / jockey / race` 候选、WP Stud 赛事/骑师/马场社区候选，以及 WP Stud HorseList 全量马名。当前生产为 `TermEntry=16558`、`TermAlias=19293`；`source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，active 马名国别后缀和赛事年份标记脏数据均为 `0`。外部马名索引仍以日本 `netkeiba` 为主体；英国、法国、美国当前生产 `External*` 表无写入。当前应把多地区识别能力理解为“正式术语库已大幅补齐，尤其 HKJC 官方本地/海外术语可用于英文新闻识别”，仍不等同于英法美外部赛马数据库正式落库。
- 术语种子数据准备：OpenSpec change `prepare-termbase-seed-data` 已完成实现、验证和归档；本地首版已新增 `prepare_termbase_seed_data` 管理命令、`stable.services.termbase_seed` 服务层、HKJC/WP Stud fixture、操作文档和后台术语导入模板更新；内置 fixture smoke 可生成 `seed_candidates.csv`、`seed_conflicts.csv` 与 `summary.json`，候选主表严格兼容现有 `import_terms` 字段，中文目标译名统一简体化。HKJC 专用抽取已从真实页面打通 `selecthorse -> selecthorsebychar -> zh-hk horse detail`，并新增 `--hkjc-letter` 支持按 A-Z 拆批；本地赛果路径已支持日期范围、跳过马匹详情页、双语空壳赛果页进入 `skipped_races`。OpenSpec change `prepare-hkjc-overseas-termbase-seeds` 已完成本地实现、正式规格同步和归档，归档目录为 `openspec/changes/archive/2026-07-05-prepare-hkjc-overseas-termbase-seeds/`；正式规格已包含 `hkjc_overseas` 来源、Race Card 自动发现/精确参数、QIDS 日期范围抽取、官方来源元数据、结构化证据、地区映射和 `racing_region` 导入表头。`2026-07-05` 已用该路径生成并导入 `2024-01-01` 至 `2026-07-04` 海外术语。WP Stud 解析器已扩展到赛事、骑师、马场和 HorseList 马名表；生产导入时遇到既有 HKJC 官方术语或既有日文 alias 占用时，不覆盖官方主译名，不强行合并冲突概念。`2026-07-06/07` 最终返修已验证 WP Stud HorseList 触网解析、HKJC 马名国别后缀清洗、复合年份赛事拆分和 HKJC 日本马日文 alias 补充；正式导入后生产计数为 `TermEntry=16558`、`TermAlias=19293`。
- 观察自动发布质量与自动化日志
- 补充翻译 warning 可视化和术语库补全流程
- 继续评审 OpenSpec change `expand-international-racing-coverage` 的本地实现：多地区新闻源、公开首页地区 tab、`TermEntry + TermAlias` 多语言术语概念模型、群级 QQ 推送配置、HKJC 外部数据导入和全球数据源 spike 已完成本地实现与 review 返修；上线前 review 已补齐快照 metadata 不保存整页 HTML、TDN 缺详情日期时保留列表 API 时间、英文外部马名索引识别、跨语言术语 upsert 主原文保护、术语批量别名匹配、HKJC entries/results 马匹上限统计、英文术语生命周期大小写不敏感、术语启停同步别名状态、术语导入别名冲突保护、TDN/TDN France canonical 去重和术语列表语言筛选翻页保留，尚未部署生产
- 观察外部马名索引识别链路生产效果，重点抽检 `external_horse_not_preserved` warning、候选池 `external_horse_alias` 来源质量和 JRA 活动公告类启发式误报
- 推进 HTTPS / 证书接入
- 做部署稳定化
- 完善监控、备份与回滚流程
- 观察 QQ Bot 测试群灰度；OneBot 已接通并开启 `QQ_PUSH_ENABLED=true`，当前按 `QQ_PUSH_SCOPE=high_value_only` + `QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 只等待自然榜单新闻自动推送。存量公开新闻已完成部分限速补推，剩余历史失败记录暂不继续补推。
- 验证并评审 `operate-multiregion-news-production` 本地实现；部署前必须执行只读审计、`.env` 备份、通用轮询默认关闭检查、测试群地区配置核验和至少一个自然调度窗口观察。

## 6.1 国际赛马资讯扩展规划状态

- OpenSpec change：`expand-international-racing-coverage`
- 当前状态：已完成 proposal、design、tasks、delta specs 和本地实现；尚未部署生产
- 一期新闻源本地接入最终清单：
  - 日本：`Sponichi`
  - 中国香港：`HKJC Racing News`、`SCMP Racing`
  - 英国：`Sporting Life Racing`、`Sky Sports Racing`，官方补充 `BHA`
  - 法国：仅接英文来源 `France Galop English News`、`TDN France keyword`，不接法语新闻正文
  - 美国：`TDN`、`Horse Racing Nation`
- 一期数据库实现：新增 HKJC 受控导入命令 `import_hkjc_external_data`，默认 dry-run，支持 payload 小样本提交、统计查询和马名索引查询；commit 模式必须提供 `--payload-file`，使用单来源互斥锁防止并发写入，并在超过 `max_races / max_horses` 时直接失败；`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹；`Equibase`、英国 `Sporting Life + BHA`、法国 `France Galop` 已形成 spike 文档 `docs/global_racing_data_source_spikes.md`
- 排序型入口：本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可公开抓取，已作为独立排序/榜单源加入并保留原站 rank；review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，QQ `ranked` 重点策略也会识别这些国际榜单稿；`At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险保留为候选，不进入第一版默认清单
- 前台实现：公开首页增加 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，综合流第一期使用已发布文章倒序；地区页翻页保留 `region` 查询参数；公开详情继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID，国际来源去重键与公开 ID 分离
- 后台实现：术语库支持 `TermEntry` 正式术语概念 + `TermAlias` 多语言原文别名，先保留 `source_ja / aliases_ja` 现有物理字段兼容；翻译、改写、自动标签和自动化评分的术语命中按文章原文语言选择别名，并批量加载参与匹配术语的别名，避免每条术语各查一次；英文/繁中外部马名索引按同语言参与识别，先按文章候选片段收窄查询，并使用原文真实写法做保护和校验；英文正式术语按大小写不敏感方式命中并保留原文真实 matched_text；最终 review 返修后，自动化 P0 马匹命中、发布校验核心/背景术语判定和“新增术语后应用当前稿”也统一复用语言感知匹配，避免英文大小写漏判或漏替换；本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感，并让后台/API 启停术语同步所有语言 `TermAlias` 状态；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，术语导入 upsert 命中跨语言别名时仍只维护该语言别名、不覆盖正式概念主原文；本次返修又补齐别名冲突保护，只有主原文命中时才允许 upsert，别名撞到其它术语会报错；AI 改写 prompt 的术语表使用文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名；自动化评分补充英文/繁中赛马关键词；QQ 推送从全局范围配置扩展为群级地区 / 范围 / 重点策略配置，旧群空地区或非法地区配置按日本兼容；内置来源同步保留人工 `enabled` 状态，支持后续按来源灰度启用
- 测试用例：`openspec/changes/expand-international-racing-coverage/test_cases.md` 已按 OpenSpec `proposal/design/spec` 建立完整验收矩阵，覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界
- 真实新闻源探测：`probe_international_news_sources` dry-run 默认探测第一版最终矩阵；`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest` 均已成功解析两篇真实样本
- 验证：新增测试用例矩阵和最终源清单返修后，本地 `manage.py check`、完整 `stable` 测试、`makemigrations --check --dry-run`、`openspec validate expand-international-racing-coverage --strict`、`openspec validate --all` 和 `git diff --check` 均已通过；2026-06-26 最终 review 返修后完整 `stable` 测试通过 231 项，已覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别与真实写法保护、翻译保护和发布校验使用真实 matched_text、英文正式术语大小写不敏感匹配与当前稿替换、英文 P0 马匹评分、跨语言术语 upsert 主原文保护、术语别名批量匹配、HKJC entries/results 马匹上限统计、旧 QQ 群空/非法地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步别名、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选

## 7. 当前上线进展（摘要）

- 2026-07-10 `classify-english-term-gate-context` 已部署生产 `43898ff` 并归档到 `openspec/changes/archive/2026-07-10-classify-english-term-gate-context/`，正式规格已同步到 `automation-publish-gates`：英文术语门禁会在生成 `core_term_missing` 前按上下文输出 `common_word / proper_noun / uncertain`；普通英文词种子默认降级为 warning，只有 `wins / returns / runs / targets / entered` 等强动作上下文才继续保守阻断；`Classic`、`Contact and live updates from York`、`Live stable updates` 等普通语境均有回归测试覆盖。重校验命令已支持有界候选、批量术语/alias 预加载、文章级英文分类明细和地区 summary。上线前后已通过本地 check、11 项目标测试、OpenSpec 严格校验、语法检查、生产 `manage.py check` 和内外 `/healthz/` smoke。生产只读完整 dry-run 产物在 `runtime/multiregion_candidate_audit/reprocess_full_dryrun_20260710_030944/`：四地区旧 `core_term_missing` 候选合计 `146` 篇，完整门禁通过可恢复候选 `37` 篇（香港 `3`、英国 `5`、美国 `22`、法国 `7`），仍阻断 `109` 篇；本次未执行 `--commit`。
- 2026-07-10 `support-multiregion-news-attribution-and-english-gates` 已完成本地实现：文章从单地区扩展为“主地区 + 关联地区”，英文术语门禁改为使用文章地区集合，公开地区 tab / QQ / 运营汇总按关联地区可见，发布配额仍只由主地区消耗；站内编辑页和 Django Admin 支持人工修正并锁定归属。新增 `reprocess_multiregion_attribution_gates` 命令用于 dry-run/commit 重算归属与门禁，commit 不直接发布。新增配置 `MULTIREGION_ATTRIBUTION_ENABLED`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED`、`MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`；关联地区查询开关关闭时，公开卡片和详情也只显示主地区，不删除关联数据。本地目标测试 20 项、完整 `stable` 回归 540 项通过，线上前仍需执行生产 dry-run 抽样。
- 2026-07-10 未提交改动复审已补齐 `stable.0023_multiregion_news_attribution` 迁移，并修正新内容类别的下游兼容：赛事关联识别 `preview / tips / result_brief`，AI 改写覆盖全部新类别，同时保留旧类别；SQLite 测试库已实际应用迁移并新增类别映射回归测试，完整 `stable` 测试 `522` 项通过。本次未部署或执行生产迁移。
- 2026-07-10 多地区 change 代码审查返修已完成：赛事/赛场与一般地区上下文分层，多个模糊上下文回退主来源，来源 URL 不参与归属，重复来源抓取使用文章最终主来源；单地区回退开关覆盖 QQ 即时推送；人工归属锁定可取消；重处理 dry-run 与 commit 对锁定文章保持一致；`other` 默认不进入 QQ。相关测试组 `123` 项、完整 `stable` 回归 `529` 项通过，生产抽样任务仍保持未完成。
- 2026-07-10 第二轮审查返修已完成：编辑页可清空全部关联地区，Admin 非法主/关联地区重复改为字段级错误，重处理 `--limit` 按有效候选计数并输出扫描/截断状态，网页和 QQ 明确区分主地区与关联地区。目标测试 `19` 项、相关链路 `129` 项、完整 `stable` 回归 `534` 项通过；生产抽样任务仍未完成。
- 2026-07-01 本地新增 `increase-multiregion-news-volume` 实现：以 `ProductionWindow` 为抓取、发布和 QQ 推送的统一窗口账本；日常 15 分钟、重要赛事 5 分钟；每地区发布窗口最多 5 篇、保底 1 篇且不绕硬门禁；QQ 每地区每窗口最多 3 篇并保留群/全站小时配额。2026-07-02 review 返修后，抓取和 QQ 恢复补跑只执行最近缺失窗口，历史窗口记为合并跳过；可重试 QQ delivery 重新发送前必须占用配额；抓取窗口由真实抓取完成后回写成功/失败，HTTP 403/429 进入来源错误分类，QQ 窗口会在创建 delivery 前检查 OneBot 在线状态。新窗口生产开关默认关闭，需审计通过后再在生产显式启用。
- 2026-07-02 `increase-multiregion-news-volume` 已上线生产：生产运行 `9e97e8c`，迁移 `0017/0018` 已应用，新窗口抓取/发布/QQ 开关均已开启，16 个启用新闻源已 `production_approved=true`。生产 smoke 显示 20:15 抓取窗口 14 成功、1 个 Sponichi 上游 502 失败；20:15 发布窗口香港 1 篇、美国 3 篇，20:30 美国继续发布 1 篇，其余地区均有 `no_ready_candidates` 原因；20:15 QQ 美国发送 2 条，20:30 美国为 `already_sent`，其余地区为 `no_eligible_articles`。公开首页和地区页浏览器验收通过，ops 摘要通知已发送到测试群 `1026525240`。因当前为后半夜新闻低峰，用户确认实际 4 个自然窗口验证延期到次日继续。
- 2026-07-02 白天复核最近 6 小时自然窗口：生产已运行 `a122130`，公网 `/healthz/`、首页和抽检文章页均返回 `200`，Celery 队列为空。发布 / QQ 各地区均有 `24` 个 15 分钟日常窗口；抓取窗口 `260` 个成功、`109` 个因恢复补跑合并跳过。新窗口实际发布美国 `1` 篇、日本 `9` 篇，所有非零窗口均未超过每地区 `5` 篇；QQ 实际发送美国 `3` 条、日本 `3` 条，未超过每地区每窗口 `3` 条；其余 0 发布 / 0 推送窗口均有 `no_ready_candidates`、`no_eligible_articles` 或 `already_sent` 原因。16 个生产批准来源最新抓取均为 `success`。
- 2026-07-02 11:07 追加按地区拆因：最新 4 个发布窗口五地区均 0 发布；日本有候选但全部被 `hard_gate_blocked`（翻译失败、人工审核要求、核心术语缺失），香港 / 英国 / 法国 / 美国没有进入发布候选的文章。最近 3 小时非日本来源抓取成功但新增为 0、只命中重复旧稿；TDN France / TDN 美国早间短暂超时后已恢复，当前不是 0 发布主因。
- 2026-07-02 15:10 复核最近 2 小时窗口：五地区发布 / QQ 窗口均按 15 分钟节奏成功运行；网页发布 0 篇、QQ delivery 0 条，原因分别为 `no_ready_candidates` / `no_eligible_articles`。最近 2 小时抓取新入库 8 篇（日本 5、香港 1、英国 2），但均处于翻译失败或人工审核要求状态，未达到自动发布条件；TDN France 与 TDN 美国 15:02 各出现一次 read timeout，failure streak 为 1，属于上游短时超时。
- 2026-07-03 00:13 今日窗口复核：今日目前只有 `00:00` 一个自然窗口，抓取 / 发布 / QQ 均正常生成并成功；新入库 1 篇美国 TDN 新闻，发布 0 篇、QQ 0 条，原因分别为 `no_ready_candidates` 和 `already_sent / no_eligible_articles`；16 个生产批准来源最新状态均为 `success`。
- 2026-07-03 复核 2026-07-02 全日窗口：昨日实际覆盖 `04:00-23:45` 共 80 个 15 分钟窗口起点；发布窗口五地区各 80 个且全部成功，窗口发布日本 37、香港 1、美国 10，英国/法国 0；QQ 窗口五地区各 80 个且全部成功，窗口派发日本 3、美国 5，所有昨日 QQPushDelivery 记录均为 sent；抓取窗口无 failed，窗口 payload 新增日本 79、香港 5、英国 11、法国 1、美国 28，日本榜单唤醒 7 次。
- 2026-07-03 地区归属错配审计：现有 `NewsArticle.racing_region` 与新闻源地区完全一致，6598 篇中 0 篇偏离“按新闻源地区”。严格实体地区口径只覆盖 462 篇且均为日本文章，按用户提出的第一种/第二种逻辑未发现结构化错配；但生产实体地区数据不足，审计当时 `TermEntry.racing_region` 全为空，英法美外部马名/赛事正式缓存未落库，因此该 0 只能视为下限。2026-07-04 仅补写了首批 `10` 条术语地区，仍不足以支撑可信实体地区识别。关键词粗扫有 1213 篇疑似跨地区提及，需后续做实体地区识别改造后才能给出可信错配数。
- 2026-07-02 OpenSpec change `revive-ranked-news-for-publish` 已完成本地实现：未发布文章从普通来源升级为榜单来源时会写入 `ranked_revived_at` 和 `decision_reason.ranked_revival`；低分 ignored、价值不足人工状态、翻译失败和待翻译文章可被唤醒，翻译未完成先重试，已翻译文章重新进入自动化评分；人工拒绝、撤回、重复 blocker 和硬门禁不绕过。发布窗口候选回看同时支持 `first_seen_at` 与 `ranked_revived_at`，候选决策 payload 会记录榜单唤醒来源和时间；已发布文章仍只沿用现有 QQ 补推，不重复发布。
- 2026-07-02 `revive-ranked-news-for-publish` 验证与上线：目标榜单唤醒测试通过，完整 `stable` 测试通过 418 项；`manage.py check`、`makemigrations --check --dry-run`、OpenSpec 严格校验、全量 OpenSpec 校验和 `git diff --check` 均通过。OpenSpec change 已归档并部署生产 `a774672`，迁移 `0019_newsarticle_ranked_revived_at` 已应用；生产 `/healthz/`、首页、后台登录入口、容器状态、Celery 队列和日志 smoke 均通过。
- 目标服务器：阿里云香港 ECS，采用低成本部署方案（本机 PostgreSQL + OSS）
- 仓库线上基线：`main` 分支已包含生产化改造与低成本部署脚本
- 已发现并修复一项部署兼容性风险：
  - 部分 Ubuntu 镜像仅提供 `docker-compose`
  - 项目部署/回滚脚本现已兼容 `docker compose` 与 `docker-compose`
  - 兼容包装脚本已调整为优先使用 `docker-compose`，避免旧环境误判
- 已发现并修复一项镜像拉取风险：
  - `worker / beat` 使用本地构建镜像 `umanewsbot:prod`
  - 部署脚本已改为仅拉取外部依赖镜像，避免误向公共仓库拉取业务镜像失败
- 已发现并修复一项健康检查风险：
  - 容器内 `curl http://127.0.0.1:8000/healthz/` 会命中 Django `DisallowedHost`
  - 应用现已自动允许回环地址进入 `ALLOWED_HOSTS`，兼容 Docker 健康检查
- 已识别一项远端编排兼容性风险：
  - 服务器自带 `docker-compose 1.29.2` 在重建带卷容器时会触发 `KeyError: 'ContainerConfig'`
  - 部署策略调整为优先使用 `docker compose` v2 插件，必要时在 ECS 上手动安装官方 CLI plugin
- 已开始域名接入准备：
  - 目标域名为 `umafans.run` 与 `www.umafans.run`
  - 当前阶段正式域名 HTTP 接入修复已完成
  - 下一阶段进入 HTTPS / 证书接入与部署稳定化
- 已拿到生产所需核心密钥：
  - `SILICONFLOW_API_KEY`
  - `OSS_ACCESS_KEY_ID`
  - `OSS_ACCESS_KEY_SECRET`
  - `OSS_BUCKET_NAME`
- 当前下一步：
  - 观察自动化发布质量，重点看 warning 邮件、重复内容阻断和候选池门禁展示
  - 生产灰度前先评审外部赛马数据导入配置，执行 dry-run 和单月小批量验证
  - 补充翻译 warning 可视化和术语库补全流程
  - 推进 HTTPS / 证书接入
  - 做部署稳定化
  - 完善监控、备份与回滚流程

## 8. 协作约定

1. 每次开始项目前优先阅读 [docs/current_state.md](E:/Codex/docs/current_state.md) 与 [AGENTS.md](E:/Codex/AGENTS.md)，本文档作为项目级摘要辅助阅读。  
2. 每次更新完成后同步回写本文件与 [docs/current_state.md](E:/Codex/docs/current_state.md)。  
3. 每次收到新 PRD 归档到 `E:/Codex/docs/PRD/`。  
4. 每次阶段性收工时同步更新 [docs/work_log.md](E:/Codex/docs/work_log.md)。

## 9. 专有术语候选发现状态

- 已完成四类实体候选发现：马名、比赛名、骑手名、马主名。
- 已完成正式术语去重、已有候选聚合、按文章证据留存和跨类型冲突提示。
- 已完成工作人员候选审核后台与单篇重新发现入口。
- 已完成接受、修改后接受、合并、拒绝、忽略和保守批量操作。
- `2026-06-07` 已部署生产并应用迁移 `0006`（服务器到 `e2e3e07`），生产默认关闭，待单篇抽检后通过 `TERM_DISCOVERY_ENABLED` 灰度启用。
- 当前验证：Django 检查通过，`stable` 69 项测试通过，两种生产 Compose 配置检查通过，并完成本地隔离环境浏览器功能验收。

## 10. 外部赛马数据导入状态

- 已实现 `add-netkeiba-horse-data-import` OpenSpec change 的首版代码。
- 新增外部比赛、出走、赛果、赔率、马匹、履历、马名索引、导入运行、错误记录和单来源锁模型。
- 新增 `import_external_horse_data` 管理命令和 `import_external_horse_data_task` Celery 任务。
- 生产默认关闭：`EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`、`EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 当前能力只维护本地外部赛马数据缓存，不改变新闻抓取、翻译、改写、自动发布或公开前台。
- 当前验证：Django check 通过，`stable` 147 项测试通过。
- 生产首轮小批量已完成：`run_id=1`，`2026-05` 前 10 场，成功 10、失败 0，写入 143 个唯一马 ID/马名索引。
- `2026-06-24` 已补充按月续跑跳过已落库 race 的逻辑，后续可继续对 `2026-05` 做小批量下一批导入。
- 生产第二批续跑已完成：`run_id=2`，累计 20 场比赛、274 个唯一马 ID/马名索引，失败 0。
- 生产第三批续跑已完成：`run_id=3`，累计 50 场比赛、695 个唯一马 ID/马名索引，失败 0。
- 生产长循环导入在 `run_id=9` 以退出码 `137` 中断；已停止继续导入、释放锁并标记 partial。当前累计 182 场比赛、2401 个唯一马 ID/马名索引，服务健康。
- 外部马名索引已接入生产识别链路：翻译阶段保护外部已知但无中文译名的马名，发布校验输出独立 `external_horse_not_preserved` warning，术语候选发现会把新闻中出现且缺少正式中文译名的外部马名以 `external_horse_alias` 来源送入候选池；同名普通词需要强马名上下文才会被识别为马名；review 返修后，保护名单 `limit` 不再被已有中文译名的正式马名占用。OpenSpec change `use-external-horse-alias-for-name-recognition` 已归档到 `openspec/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`，正式规格已同步，并已通过 PR #6 部署到生产 `35b0866`。
- 长文样本抽检显示：netkeiba 长文可有效命中外部马名索引，但 JRA 活动公告类长文仍会通过启发式误报普通片假名词，后续需要继续补普通词过滤或收紧启发式马名规则。

## 11. 2026-07-11 未提交变更状态

- 当前分支已快进到最新 `origin/main`，保留并整合多地区新闻归属、英文门禁和赛事历史抓取编排两组未提交改动。
- 多地区新闻迁移已调整为 `0023_multiregion_news_attribution`，依赖主干 horse profile `0022`，本轮未执行生产迁移。
- 赛事抓取编排已补齐应到审批、地区专属 adapter 输入、空内容与来源 URL 门禁、应到身份复核、真实 gzip 校验和完整人工批准元数据。
- 目标测试 `48` 项、完整 `stable` 回归 `588` 项通过；Django check、迁移漂移、两个 change 严格校验、OpenSpec 全量 `21` 项和 `git diff --check` 均通过。
- 后续 review 中纯技术问题由 Codex 直接判断修复；产品能力、运营口径和交互变化仍由用户审核。
- 2026-07-11 第六轮赛事抓取返修：批量 importer 已整批事务化；应到快照保存完整 adapter 输入且审批后 `RaceEvent` 漂移会阻断；pending 混合来源确认不再提供策略 SHA。按用户决定暂不强制哈希参数、暂不增加请求预算并发锁。目标测试 `67` 项、完整 `stable` 回归 `589` 项通过，Django/迁移/OpenSpec/diff 校验均通过；`orchestrate-race-event-data-crawls` 已同步正式规格并归档。
- 2026-07-11 生产部署前发现多地区归属开关关闭后仍扫描完整术语库，导致 crawl worker 高 CPU；已增加禁用/人工锁定短路，目标测试 `30` 项、完整回归 `591` 项通过。归属开关保持关闭，五地区产品抽样仍待修正口径后重验。
- 2026-07-11 已部署生产提交 `6e2cc92`：赛事历史抓取编排已归档并上线，多地区归属模型/迁移已上线但两个功能开关继续关闭。部署前 `.env` 与数据库备份均已完成并校验；归属短路热修复使 worker CPU 从持续高占用恢复至空闲约 `0.04%`。Django、容器、Celery、健康检查、首页、法国/英国频道、赛事日历及后台登录页回归通过。`support-multiregion-news-attribution-and-english-gates` 仍待五地区产品口径验收，不得开启开关或提交历史重算。
- 2026-07-11 `support-multiregion-news-attribution-and-english-gates` 已在用户接受任务 `9.6` 未完成警告后归档；六组 delta spec 已同步到正式规格，OpenSpec 全量 `21` 项通过，当前无 active change。归档不代表五地区产品归属验收通过，多地区生产开关仍须保持关闭。
- 2026-07-11 已生成赛事编排第一批五地区应到清单：日本德比、富卫保险女皇杯、BETFRED DERBY、PRIX DE DIANE LONGINES、KENTUCKY DERBY PRESENTED BY WOODFORD RESERVE 各 1 场，三模块齐全且 5 行预检均为 `ready`。run 审批仍为 `pending`、网络关闭，等待用户审核 `expected_targets_review.csv`，尚未开始真实抓取。
- 用户已批准上述清单；网络版 run 与原清单逐字段一致。prepare 前检查发现生产镜像遗漏 `runtime/tools` adapter 脚本，当前先修复 Docker 构建内容并部署，尚未发出网络请求。
- 第一批网络抓取 v2 已由覆盖审计安全阻断且未写库：香港、英国、法国完整，日本详情错配到中山金杯，美国缺 Equibase 赛果与可用 TOBA 历届冠军。JRA 已改为按赛事名称唯一匹配；v3 不改变已批准五场赛事，只新增美国 Equibase 赛果适配器，并复用已验证 TOBA 年度页缓存。必须先取得五地区三模块完整覆盖，才进入 dry-run。
- v3 已在 `60/60` 请求预算内完成日港英法抓取；HRN 通过同源留存页恢复出 24 匹参赛马。Equibase 执行暴露生产镜像缺少 `pdfplumber`，当前补齐依赖后从失败状态 resume；尚未 dry-run 或写库。
- `pdfplumber` 部署后 11 个 adapter 均完成，Equibase 产出 Kentucky Derby 18 条正式赛果。coverage 仍阻断法国空历史和美国空 HRN 赛果与非空 Equibase 赛果的误重复；审计已修为“非空候选优先、只有空候选仍阻断”，法国待用留存 Wikipedia 原件 resume。尚未 dry-run 或写库。
- 法国恢复后 coverage 已达 `5/5` 且 blocker 为 0，首轮 dry-run 通过。正式 apply 前又发现 combined candidate 仍携带 HRN 空赛果模块；当前增加聚合层空模块剔除并重新生成证据，避免 apply scope 与实际候选不一致。尚未正式写库。
- 空模块剔除后的 coverage/dry-run 已通过，但字段级 review 发现 JRA 当届历史冠军会丢练马师和完赛时间。当前已增加关键字段完整性阻断，并让 JRA history 从同批 detail 补齐当届冠军；真实缓存 smoke 通过。尚未正式写库。
- 最终候选 `2dd40a...8eac5` 已通过 coverage `5/5` 和 dry-run，JRA 字段退化已消除。剩余业务变化为英国补 2020 冠军及 2021 时间、法国练马师/冠军人名规范化及完赛时间补充；等待用户确认 mixed-source 与覆盖变化后进入 apply-check，尚未写库。
- 用户确认后第一批五地区赛事已正式写入：apply-check 8 个 scope 全绿，15 个候选全部 applied；写后合计 runners 75、results 64、history winners 47，服务健康。写前 105M 数据库备份已通过 gzip/SHA 校验，最终运行证据已同步到生产宿主机和本地审核目录。
- 2026-07-11 国际新闻生产验收未通过：最近 24 小时英文稿 `50` 篇中 `25` 篇仍有 `core_term_missing`；`America/Oaks` 等已降级，但一批被错误登记为马名的普通词仍作为 proper noun 阻断。地区新增/公开为日本 `114/21`、香港 `3/0`、英国 `12/2`、法国 `1/0`、美国 `34/13`；法国宽关键词新源 24 小时新增 `0`，香港/英国/美国后续扩源尚未实施。重处理 dry-run 即使 `limit=5` 也存在长时间满核问题，修复前不得在生产批量运行。
- 2026-07-12 已部署赛事公开页展示修复 `d071952`：出马表、赛果、历史冠军和赛事日历前列赛果中的马名/骑师名会精确关联 active 正式术语及别名，命中时显示中文译名、未命中保留原文；出马表按马号自然升序，缺号回退闸位，不再沿用赛果来源行序。目标测试 `23` 项、完整回归 `612` 项通过；线上排序已生效。首批术语覆盖不均，日本德比当前马名仅命中 `1/18`、骑师 `0/18`，后续应补正式术语库。
- 2026-07-12 已启动五地区赛事统一追溯至 1984 年的新目标，并创建 OpenSpec change `backfill-race-events-to-1984`。生产基线 `RaceEvent=995` 且全部集中在 2026 年；按当前目录机械外推为约 `42,785` 个年度对象，但真实分母必须由逐年目录和系列 timeline 生成。proposal、design、4 份 delta spec、82 项 tasks 和 22 轮问答决策已完成；两轮 `/plan-eng-review` 最终 APPROVED。当前下一门禁是编写完整测试用例，尚未实现、触网或写历史赛事。
- 用户已确认范围选择 A：覆盖五地区当前全部 graded/pattern 系列，不扩展到普通赛、让赛或未胜利赛。
- 用户已确认完整系列史口径：入选系列从 1984 年或实际创办年起收录，成为分级赛之前的年度届次也纳入，等级使用各年真实值。
- 用户已确认历史独有系列也纳入：凡 1984 年以来任一年进入 graded/pattern 体系，即使后来停办或降级退出，也进入系列目录。
- 用户已确认缺届口径：排期后取消创建 cancelled 年度赛事；当年未举办只记 `not_held` 证据，不创建虚假赛事。
- 用户已确认历史出马表可从可信完整赛果派生，必须保留派生来源且不得填造缺失字段。
- 用户已确认历届冠军采用系列动态汇总：年度正式赛果为主，缺完整赛果时才以冠军证据补位，不在每届重复整张历史表。
- 用户已确认稳定系列按权威沿革治理，冠名/场地/等级变化可连续，合并拆分必须人工确认并保留关系。
- 用户已确认多来源采用字段级权威规则，低级来源仅补空，同级或高级冲突阻断写入并人工审核。
- 用户已确认第一批跨年代验收约 45 场：五地区各 3 个系列，每系列抽 1980 年代、2000 年前后和近年 3 个年度。
- 用户已确认完整目标可先分批写入，暂时不可得或身份待审目标继续挂账且不计完成。
- 用户已确认永久不可得必须有官方/监管档案加独立可信来源的双来源证据，并经人工批准。
- 用户已确认当前年度未到期赛事使用 `not_due`，进入清单但不影响历史缺失率，到期后再纳入详情应到。
- 用户已确认历史赛事按质量门槛公开：完整且通过批准批次可自动 published，冲突/不足保持 draft，确认取消可公开说明。
- 用户已确认历史数据可受控增量修正，必须经新 diff/批准批次并保护人工锁，保留完整审计和回滚证据。
- 用户已确认中文术语缺口不阻止历史赛事结构化写入，未命中时保留原文并挂术语待办，不自动造词。
- 用户已确认全量按年代带从新到旧、五地区同步推进，禁止单地区长期领先。
- 用户已确认最终验收采用 accounted/data-complete 双指标，全部目标须有结论，永久缺档单列披露。
- 用户已确认历史赛事回填不自动创建马匹资料页，未识别人马只进入候选/术语缺口。
- 用户已确认不新增赛事系列页，前台继续使用年度赛事详情页。
- 用户已确认赛事日历增加年份筛选和赛事名称搜索，作为历史年度赛事入口。
- 用户已确认 artifact 为唯一批量审批/apply 凭证，同时增加后台汇总和冲突查看入口。
- 用户已确认达标 published 历史赛事允许被搜索引擎收录，使用分片 sitemap 排除草稿/冲突/空壳/not_held。
- OpenSpec 文档已通过两轮 Full 工程审核并获得 APPROVED；`test_cases.md` 已建立 160 个唯一用例。代码实现、clean review、生产部署和 2026 mapping 已完成，生产历史功能和网络门禁仍关闭。

### 2026-07-12 历史赛事工具上线与系列身份基线

- 历史赛事编排工具已随 `c3b66a6` 部署，模型、只读 inventory、五地区 catalog parser、批次 importer、年份搜索、分片 sitemap 与共享 Redis 缓存均已上线；历史功能和网络开关仍关闭。
- 2026 mapping 已完成审核和提交：清理 3 条确认重复赛事后，现有 `992` 场赛事全部绑定 `992` 个稳定系列，五地区 `review_required=0 / conflict=0 / unbound=0`，幂等复跑无新增写入。
- 当前尚未创建历史年度总账或 1984–2025 赛事。下一阶段只推进五地区 1984–当前官方逐年目录 source cache、系列 timeline 和只读总账审批，不能从 2026 现役系列机械外推历史分母。

### 2026-07-12 历史赛事回填实现进度

- 已完成 `/opsx:apply`、完整测试、反复 review、生产迁移和 2026 系列 mapping；稳定赛事系列、年度应到总账、official finish position、并列冠军迁移，以及离线 inventory artifact/审批/幂等 commit 基础能力均已上线。
- 历史功能和网络开关继续默认关闭；生产当前只有 2026 系列绑定，没有历史年度总账、1984–2025 赛事或历史公开数据。
- 后续仍需完成五地区逐年官方 source cache、年度总账审批、首批详情验收和分年代带回填；所有写入继续走既定 artifact、coverage、备份和写后核验门禁。
- 当前 OpenSpec 任务进度 `62/82`；代码与自动化测试任务已完成，包含五地区目录 cache parser、标准候选命令、共享预算/缓存锁、历史网络日志、批次 importer、公开搜索、动态冠军、sitemap 缓存与索引。完整 `stable` 回归最终 `743/743`，Django/迁移/OpenSpec/Compose/实际 Docker 镜像检查通过。
- 多轮代码 review 的全部技术 finding 已修复并逐轮复审，最终 review clean。剩余 `20` 项均为生产 mapping、官方逐年 source cache、总账审批、首批及四年代带抓取落库和最终审计；生产功能和网络开关继续关闭，尚未部署或写入本变更的历史数据。

### 2026-07-12 历史目录年鉴解析器就绪

- TJCIS International Cataloguing Standards 1998–2026 整本年鉴已确定为五地区共同年度 graded/group 目录骨架；原始 PDF、派生 CSV 和逐行 provenance 受共享预算/cache 门禁管理。
- 解析器已完成 1998 老版和 2016 中版真实样本迭代；1998 年鉴本身存在正文与页尾汇总矛盾，不能视为通过。专项回归与多轮 review 已通过，生产 source cache 已执行。
- 1984–1997 仍是任务 `8.3` 正式缺口。1998–2026 候选只形成部分只读总账，不批准完整 manifest、不创建历史 `RaceEvent`，直到旧年代来源和身份 timeline 补齐。

### 2026-07-12 历史目录生产抓取阶段结果

- 1998–2026 共 29 本 TJCIS 年鉴已经完整缓存并在生产校验 SHA；严格验收仅 `2016 / 2020 / 2021` 通过，25 个年份保留明确错误，1984–1997 尚未覆盖。
- clean 部分候选为 `3,252` 行，部分 inventory 为 `1,313` 个系列、`3,252` 个年度目标候选、`82` 个身份冲突；所有 artifact 均未批准或写库。
- 任务 `8.3` 继续未完成，详情抓取尚未开始。生产数据库仍无历史总账和 2026 年前赛事，公开开关继续关闭。

### 2026-07-12 1998–2026 年度目录修复进展

- TJCIS 全书解析修复后，严格直接通过年份从 `3/29` 提升为 `11/29`，2015 美国截断和 2022 英国同名障碍赛碰撞已解决。
- 全地区审计发现 `22` 个年份共 `31` 项正文/声明小计冲突；当前已生成逐项 JSON/CSV 和 29 年页文本诊断缓存，正在关联 JRA、BHA、France Galop、TOBA/AGSC 等地区来源。
- 尚未批准或写入 1998–2026 总账，尚未启动历史详情抓取或公开。生产历史功能/网络开关继续关闭。
## 2026-07-13 法国新鲜度与归属能力部署状态

- `fix-france-news-freshness-and-multiregion-attribution` 的代码和 `stable.0029` 已部署到生产 commit `badc10e0`，容器、迁移、HTTP 健康检查、首页、法国频道、详情页及法国三来源只读 probe 均通过。
- 新归属、相关地区查询、翻译自动重试和失败邮件仍全部关闭；这是安全部署，不是功能灰度完成。现有 159 条 Gold Set 已取得 Shadow 资格，但生产 dry-run、至少 24 小时 shadow、全量变化复核及后续灰度未完成前不得开启 enforce 或归档 change。
- 法国来源实时探测已能命中近期英文稿，未复现 2020/2022 历史稿；邮件通知因生产没有 SMTP 配置暂不可用，HTTPS 证书接入仍是独立待办。
### 2026-07-13 历史赛事第一批详情生产进展

- 此前 1998–2026 总账已完成审核和受控写入；第一批五地区 45 场验收样本现已完成日期发现和首轮详情落库：27 场详情正式导入，9 场法国赛事已有日期但等待完整详情，英国 2000 年 3 场和美国 2000/2012 年 6 场等待日期来源。
- 已导入 297 条出马表、287 条赛果和 54 条已应用候选；36 个已建年度赛事全部保持 draft，线上历史展示开关继续关闭。
- 生产详情写入前备份、候选/缓存 SHA 核验、dry-run、正式 apply、逐目标写后计数、容量检查和服务健康检查均已通过。下一步优先补齐本批 18 个显式缺口，再做五地区前台验收和扩大年代带抓取。

- 法国补源已向前推进：2012/2025 六场 ZEturf 详情离线解析完成，共 70 条 runners、41 条官方名次；旧页面兼容和同名误配已修复，826 项完整回归通过。该批仍停在本地候选阶段，必须先完成详情来源补充 artifact 和 target URL 绑定，不能直接写生产。法国 2000 三场仍待其他可信来源。
- 英法IrishRacing备用源与美国Equibase单场PDF能力已完成测试、反复review和生产部署；最终完整`stable`回归 `848` 项通过，OpenSpec strict/all、Django check、迁移漂移和diff检查均通过。
- 第一批五地区45个历史目标现已全部完成生产写入：`45/45 imported`，合计 `468 runners / 429 results`，全部保持draft且历史published为0。美国最后六场写入 `58 runners / 58 results`，候选SHA-256为 `94b62febe849b9a0562e5ab641d87671ae3468a202355b5336a7f4405e8abe75`；长期历史抓取/网络开关继续关闭。
- 2016–2025 首个标准批次已批准 250 场。日本和美国 100 场日期已写入，其中 98 场完整详情已 imported，新增 `1157 runners / 1080 results`；两场 NSA 障碍赛待详情，法国、香港、英国各 50 场仍处于日期来源缺口。公开开关继续关闭。

- 两场 NSA 官方 PDF 已补齐并正式写入，标准批次日美达到 `100/100 imported`、`1172 runners / 1094 results`；法国、香港、英国各 50 场仍是下一批日期/详情来源缺口，历史公开开关保持关闭。
- 生产曾被未合入 `stable.0027–0029` 对应应用代码的历史旧底座镜像覆盖，导致 netkeiba 新增违反 `attribution_rule_version` 非空约束。P0 后历史线程已停止所有生产动作；本地已合入最新 main 并通过 1093 项完整组合回归，等待生产协调解除构建冻结后再准备 AMD64 兼容镜像。
- 生产已短时回滚并验证 9 篇 netkeiba 新增/翻译恢复。AMD64 兼容镜像 `sha256:383a36c1c986143805c0985e6286c77726a5dad8af516dc9bb080f011939c7b4` 已独立构建并通过镜像内 check；尚未切换生产，后续由单一生产协调线程完成替换与验收。
- 上述兼容镜像现已由协调线程正式切换并完成生产验收，历史数据写入冻结解除；历史线程继续使用该镜像，不重建或重启生产。
- 2016–2025 标准批次的法国、香港、英国各 50 场已完成日期与详情证据，合计 150 个来源 URL 全局唯一；英国 47 条紧凑/裸数字距离证据已显式补单位。日期 artifact 已在备份后提交，150 场均为 ready/draft；详情导入暂停，优先把全部历史源码提交、推送并合入 main，避免下一次构建丢失能力。公开开关继续关闭。
- 历史赛事镜像曾以旧代码底座覆盖生产，造成已应用 `0029` 的数据库与旧应用不兼容并阻断 netkeiba 新稿。新闻写入先由临时组合镜像恢复，随后历史实现已完整提交到 Git，生产也已切换到 `main@304ebdb6` 的可复现镜像 `sha256:e7ab7af0...877d`；“仓库 HEAD 与运行镜像内容不同”的发布风险已解除。
- 法港英 150 场详情导入前只读复核发现原始赛事字段丢失地区距离单位，并有少量场地/surface 需要按已审核权威证据校正。新的整文件 SHA 锁定字段批次命令、RaceEvent 并发锁、整批回滚和旧详情候选失效门禁已完成，完整 `stable` 回归 `1136` 项通过；生产写入暂停，先把本轮源码合入 `main` 并重新交付可复现 AMD64 镜像。
- 上述门禁已提交到 `main@df2732c3` 并切换为可复现 AMD64 镜像 `sha256:27d5d51c...bf13`；切换前备份、排空 worker、无迁移检查、三容器一致性、五地区页面和首个自然窗口均通过。历史仍为 `145 imported + 150 ready`、published 0，本轮未执行字段或详情写入。

## 2026-07-14 多地区归属 V3 校准状态

- 现有 Gold Set 以用户完成的 `159` 条单审标签固定校准，不再补第二审核人；审核来源始终保留为 `provisional_single_review`。该身份本身不再禁止进入生产 Shadow；只有生产全量 dry-run、至少 24 小时 Shadow 和全量差异复核也通过后，才允许仅对新文章 enforce。
- 本地冻结快照对比：旧规则主地区 `81.76%`，V3 为 `98.11%`；V3 的日本/香港/英国/美国均 `100%`、法国 `90.91%`，相关 precision `100%`、recall `54.84%`，过度扩散 `0%`。低 recall 主要是文章未提供的历史参赛地区，不自动猜测。
- 术语候选索引把 159 篇纯推断降到约 `0.8` 秒；相关目标测试 `82` 项通过，最终完整 `stable` 回归 `1156 passed / 1 skipped`，Django/迁移/编译/OpenSpec strict/all 均通过。生产归属、相关地区查询仍关闭，本轮未部署或写生产数据。
- 下一门禁是 PostgreSQL 250 篇性能基准、生产 72 小时只读 dry-run 和运营复核；未满足前不得归档本 change。
- 法港英 150 场已完成权威字段校正、旧候选失效验证、重新导出、0-gap 打包、dry-run、第二次备份、正式导入和写后核验。新增 `1534 runners / 1294 results`，标准批次累计 250 场全部 imported；生产历史合计 295 场、3174 runners、2817 results，全部 draft、published 0，常驻历史写入/网络开关保持关闭。
- 2016–2025 第二标准批次已固定五地区各 50 场并完成日美离线来源发现：日本 50、美国 48 个候选对应 98 个唯一 URL；Brooklyn 与 Cougar II 的 2025 届被 TOBA 明确标为 `not run`，保留为产品审核项。来源匹配技术修复完整 `stable` 1141 项通过，尚未开始本批生产网络抓取或写入。
- 历史赛事完整源码和来源匹配修复已合入 `main@58786b91`，生产已切换到由该主线两次一致构建的 AMD64 镜像 `sha256:c6a3670f...4691`。迁移、64 个模型、五地区页面、健康检查和日志通过；生产历史仍为 295 场、3174 runners、2817 results，全部 draft、published 0，常驻历史写入/网络开关关闭。
- 新镜像切换后的 14:45 自然窗口已完成：17 个抓取、5 个发布、5 个 QQ 窗口全部成功，seen 472/new 3，新增 NULL 归属版本为 0。当前“主线源码、可复现镜像、生产数据库”重新一致。
- 第二标准批次五地区详情证据已收敛为 `246/250`：日本 50、美国 48、香港 50、英国 48、法国 50，246 个详情 URL 全局唯一且来源缓存身份可核验。两场美国 `not run` 和两场英国 `ABANDONED` 保留为显式缺口；香港跨年字段及英国紧凑英制距离解析修复已完成 `stable 1149` 项回归和 clean review，等待合入 main、交付可复现 AMD64 镜像后重新构建日期 artifact。尚未执行本批生产写入，历史公开开关继续关闭。
- 紧凑英制距离修复已合入 `main@d8b65fe7` 并切换生产镜像 `sha256:77eb1138...c3da0`；web/worker/beat 镜像一致，迁移无变化，Django、健康检查、页面和日志验收通过。新镜像只读重建 batch002 得到预期 `246 candidate / 4 gap`，manifest 尚未审批或写入；历史常驻写入、网络和公开开关保持关闭。
- 第三标准批次首次只读快照为 249 场、`2,635 runners / 2,346 results`，曾把 Hampton 的 Warwick 原场次 `ABANDONED` 误作年度 gap；该快照已隔离，不得审批。
- 用户提供 Windsor 正式结果后，batch003 已修正为 `250 candidate / 0 gap`、`2638 runners / 2349 results`，并完成 250/250 正式导入。NAR、Zone-Turf、ZEturf URL 身份和 surface 门禁修复继续有效。
- batch003 来源门禁已合入 `main@3939992c` 并由可复现 AMD64 镜像 `sha256:87c435cf...e78ec` 执行；正式写入后的最终状态以上方“第三标准批次 250 场导入完成”为准，公开状态继续关闭。
## 2026-07-18 P0 马详细资料补全进度

- 首批五地区 50 匹均已通过“纳入本批”身份审核。
- 日本 10 匹已完成真实来源缓存和离线重放；整体完成度为 `10/50`。
- 中国香港、英国、法国、美国已完成单马真实源审计，但均有字段、身份、访问或完整生涯阻断，尚未批准地区 10 匹批跑。
- 已实现只填空、冲突阻断的多来源合并，以及带证据 URL、录入人和独立复核人的人工字段补录入口。
- 已交付 50 匹队列与 70 个待审核字段的 Excel 工作簿。生产写入、发布和四地区历史履历网络抓取仍未开始。

## 2026-07-19 P0 马血统补证与审核包更新

- 50 匹六项三代血统已从原 `180/300` 提升为 `300/300`：父母实体安全反查自动补 `89` 个字段，
  对 `22` 个歧义/未命中父母查询人工查证并补 `31` 个字段。
- 血统人工证据逐行保留目标马身份条件、来源 URL、核验方式和说明；系统只填空，身份不符或非空
  值冲突直接失败。二级来源值不得冒充 Weatherbys、IFCE SIRE、原产地 Stud Book 或 Equineline
  官方值。
- 更新后的审核工作簿 SHA-256 为
  `ae1ef88ecd2213cec7e5721522bda16cfc74a3cbd30a1534fadef62fbf43145c`。剩余基础字段为法国/英国
  产地与育马者、中国香港完整出生日期与育马者、美国毛色；履历结果和美国官方总数边界不变。
- 本轮未写生产数据、未部署。严格整匹马完成门禁仍需同时满足基础资料、生涯完整度和逐场权威性，
  不能因祖父母已补齐就把总体完成度从 `10/50` 提升。
- 离线组合回归 `142/142`、Django check、迁移漂移检查、OpenSpec strict/all 和工作簿公式扫描
  均通过。

## 2026-07-19 五地区准实时赛果公开 Beta 候选状态

- 五地区代码、配置、additive migration、SLA 告警、manual official evidence、正式授权、
  前台 read gate 和 frozen-image rollback 控制面已进入 review 前候选。
- 首次独立 review 的四项 finding 已按 RED→GREEN 修复；当前验证为 SQLite 相关
  `353 tests OK (14 skipped)`、本地 PostgreSQL 16 `25 tests OK`，
  测试数据库和容器已删除，Django、migration、compileall、Compose、JSON 与 diff
  静态门禁均通过；本地复审候选镜像
  `sha256:7764a332fba2991be4a4c2f70814d727ba910c68005f19de579e4900c962960c`
  的容器内 check、时间参数和 registry/rollback 文件检查通过。
  受审内容已变化，旧候选镜像与旧 review 结论均不能用于发布，当前等待同一 reviewer
  限定复审。
- 当前发布状态是
  `code candidate / changes fixed / re-review pending / not authorized / not deployed`。
  各地区真实 `racecard_seen/shadow_result_seen/public_eligible` 仍须按 event 取得证据；
  代码完成不得写成五地区来源已经上线。

## 2026-07-19 五地区准实时公开 Beta 代码层已发布

- 冻结 commit `85948707c7b2bf3c62a66b09b2ddb202adf2d1ee` 已部署，生产
  `web / worker / race_live_worker / beat` 统一运行镜像
  `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`。
  additive migration、备份、健康检查、worker、队列和 event 924 回归均通过。
- 新范围仍为 fail-closed：scheduler/monitor 关闭、enabled regions 为空、claim 和
  live queue 为 0。Free 有界 proof 成功，但法国真实 coupled-entry 编号揭示解析缺口；
  日美当前 racecard 未命中，英港尚待自然赛程。当前准确状态是
  `code deployed / five-region source proof incomplete / only existing event 924 remains public`。

### 2026-07-19 回滚就绪度更正

- 数据库、旧镜像和环境回滚锚点已验证；filtered rollback env 已冻结。
- 专用 one-shot business rollback manifest 尚未生成，因此不得把本轮状态写成完整
  frozen-image rollback ready。

### 2026-07-19 发布门禁更正

- 原 Gate D 要求发布 artifact 已包含 rollback manifest；当前事实是该门禁未满足、
  release closure 不完整。新范围
  保持全部 off，后续只能通过独立受审和授权的补救操作关闭此缺口。

## 2026-07-19 准实时 Beta Gate 修复候选

- coupled-entry parser、legacy runner external identity、严格 rollback bundle 和
  maintenance/restore 阶段机已完成本地实现；法国同号码不同马匹不再整页阻塞，号码
  本身仍按来源事实展示。
- 首次独立原生 review 的 3 个 P1、3 个 P2 及首次限定复审新增的 2 个 P1、3 个直接
  P2 均已按真实 RED→GREEN 修复；新增关闭 result/runner coupled 配对、`source_key`
  身份空间、current revision restore CAS、validator 后台开关和 racecard legacy 身份
  冲突零写缺口。主代理最新复跑准实时 SQLite `432/432`（2 项环境跳过）和临时
  PostgreSQL 16 `71/71`；Django、迁移、编译、三份 Compose 和 diff 门禁通过，当前
  等待同一 reviewer 再次限定复审；尚无新 fingerprint 或发布授权。
- 生产未随本地候选变化：仍只有 event 924 公开，scheduler/monitor 和 enabled regions
  全关。新的 `0048` migration、rollback bundle、maintenance 演练及法国重验均未在
  生产执行。

## 2026-07-20 P0 马生产范围同步

- 五地区重点赛事参赛来源和全部已有中文名 active 马名术语已批量写入生产：
  `56745` 条有效来源，对应 `46318` 匹唯一 P0 马；translated horse term 缺失来源为 `0`。
- 详情完成度仍为独立维度：`50` 匹完整、`2` 匹具完整二代血统但生涯部分、`46266` 匹详情
  尚未采集。当前准确状态是
  `P0 scope committed / detail completion backlog created / identity conflicts fail closed`。
- 首次全量单事务触发 OOM 但完整回滚；后续使用地区事务和固定批量安全完成。生产健康、
  migration 和 Django check 均通过，后台 worker 已恢复。

## 2026-07-23 公开门户整合上线

- P1 新闻首页、P2 赛事日历/详情、P3 马匹档案/关注体验已整体部署到生产，发布提交为
  `bc7e2df047a20a997de1620688f1c7de4a5c52c4`。
- 生产四个应用服务镜像一致，健康检查和主要公开路由通过；1440px/390px 真实浏览器验收无
  横向溢出，字体、桌面导航和移动底栏正常。
- 实时赛果公开门禁保持不变；本次是前台展示发布，不代表扩大赛事实时来源或公开授权范围。

## 2026-07-24 赛事日历响应式细节修复上线

- PR `#17` 已部署为生产 HEAD `3772256e606e3f62081eecec162fecedbd1aa23d`。
- 日期导航现明确显示月份；移动端 G1、G2、JPN1 等级徽标保持 `42×42px`，长赛事名由标题区域换行。
- 四个应用服务统一运行镜像 `sha256:90c98db7...0e49`；Django、迁移、健康检查、主要 HTTP
  路由和 1440px/390px/320px 浏览器验收通过。本次没有迁移或业务数据写入。

## 2026-07-24 跨地区赛事与履历字段归一化待实现

- change `normalize-race-and-career-fields` 的规格、设计、测试矩阵、任务和 rollout 已经独立方案
  review 通过；完整接手入口为 `docs/changes/normalize-race-and-career-fields/HANDOFF.md`。
- 当前仅完成方案与 Claude 交接，没有实现、迁移、发布或生产数据写入；必须等待用户新的明确
  “确认实现/开始实现/继续实现”，再按测试先行和 subagent 流程推进。

## 2026-07-25 HRN 剩余正文污染修复候选待代码审核

- HRN 正文内 `role="dialog"` 视频控件残留与美国 `The Jockey Club` 被套用英国机构译名的
  修复已按真实 RED 完成本地实现。
- 受影响回归 `290/290`、Django check、migration drift 和 diff 检查通过，无 migration。
- 当前未 commit、未发布、未写生产，也未重新处理剩余 36 篇；必须先完成独立原生只读 code
  review，再取得针对该精确版本的新发布授权。

## 2026-07-26 HRN 剩余正文污染修复已生产收口

- PR `#22` 已部署到生产 revision `8cbee3e7`；HRN dialog 结构清洗和来源级“美国赛马会”
  确定性译名已生效，本次无 migration。
- 冻结 36 篇为 `12 applied / 18 translation_failed / 6 review_rejected`；部署后另发现并
  修复同结构污染 8 篇，总计 `20 applied + verified`。
- 282 篇 HRN cohort 的 ID-set 不变，最终 `183 source_clean / 99 source_changed /
  0 source_blocked`。所有写入均有 candidate、approved manifest、receipt、rollback 和 SHA；
  失败或内容截断文章未写库。
- 20 篇 QQ delivery 与公开状态零漂移；已发送 QQ 未重发。完整证据见
  `docs/changes/fix-hrn-residual-boundaries-and-jockey-club-term/release_report.md`。

# 2026-07-26 赛事生命周期阶段 A 已实现（代码审查中）

- 阶段 A（纯时间推进）新增 4 模型、2 migration、服务/task/admin/管理命令、56 项测试。
- 当前：代码审查进行中；未部署、未写生产。

## 2026-07-26 TRA schema v2 proof runner 本地修复审核通过

- schema v2 proof 已改为显式 region 和固定三路由，v1 兼容；测试先行 RED 已转 GREEN。
- 主线程相关回归 55/55，通过 Django、迁移和静态检查。
- 独立 reviewer 已给出 `APPROVED`，无开放 P0/P1/P2。当前没有联网、提交、发布或生产写入；
  最多 3 次只读 API 请求仍需针对最终 fingerprint 的单独授权。

## 2026-07-27 未来七天重点赛事官方赛前数据方案审核通过

- 冻结七天窗口内生产重点赛事超集为 19 场：英国 8、美国 10、法国 1；当前均无时刻和 runner。
- 官方赛程已证实，但现有许可/route 不支持这些地区的自动化 official entries；当前可 apply
  为 0，每日无人值守任务暂为 NO-GO。
- 独立方案 reviewer 已在同一会话关闭 3 high、2 medium finding并给出
  `VERDICT: APPROVED`。本轮只完成只读盘点和方案文档；没有应用代码、测试、数据库写入、
  调度或公开影响，当前停在“确认实现”门禁。

## 2026-07-27 P0 官方出马页 URL 定时发现正在规划

- 新范围仅保存未来七天全部 P0 赛事的官方出马页面 URL，计划上海时间每天
  `06:30/18:30` 更新宿主持久化文档；无页面时显示“暂无”，同一赛事只保留最新 URL。
- 计划覆盖 JRA、NAR、HKJC、英国、法国、美国 adapter，并保持逐 provider 自动访问门禁。
- 规格、设计、测试、任务和 rollout 已通过独立方案审核；首次 1 blocker、4 high、3 medium
  已在同一 reviewer 会话两轮限定复审中全部关闭，最终 `VERDICT: APPROVED`。
- 已获确认实现并完成本地代码与 TDD；首次 code review 的 CGNAT DNS P1 与 soft timeout P2，
  以及限定复审的 3 个 path/计数/归因 P2 均已按真实 RED 修复。聚焦 40 项、相关回归 104 项
  通过，Django/迁移/Compose/registry/OpenSpec/diff 检查通过。
- 一轮复审曾因 fingerprint helper raw 捕获不一致而 fail closed；随后 helper 恢复逐字节稳定，
  五项 findings 全部关闭，原生代码 review 最终 `VERDICT: APPROVED`。
- 当前只剩代码审核状态文档的同 reviewer 复审与最终 fingerprint 冻结；仍未取得发布授权。
- 当前未联网、部署、写生产或启用调度；六 provider route 仍全部 fail closed，仅打开总开关
  不会抓取 URL。

## 2026-07-27 P0 官方出马页 URL provider route 本地候选

- BHA 与 Equibase 的零正文 HEAD route 已完成 TDD 实现；France Galop/JRA/NAR/HKJC 继续
  fail closed 或保留未来适配。
- task 日志漏记 `listing_reachable` finding 已完成 RED→GREEN；修复后的 v3 bounded proof
  为：Equibase 精确 race card index `2` 场、
  BHA 官方日期 listing `3` 场、France Galop “暂无” `1` 场；精确 3 次 HEAD，响应正文、
  数据库与服务器 `current` 文档写入均为 0。v3 artifact SHA-256 为
  `7e4886a8ff9f02a9c39ef1e8e3e414692ad61528e184dbadb2d4b3c37b9f4b94`；首次与 v2 proof
  已被 supersede。同一 reviewer 已确认无自引用绑定与日志 finding 关闭，限定复审
  `APPROVED`；三个新 P2 仅列后续建议。
- 总功能开关仍为 false，尚未部署或启用 06:30/18:30 调度；当前只等待审核事实文档的限定
  复审和其后的精确发布授权。
## 2026-07-27 赛果缺口已有逐场来源图

- 7 月 8 日至 27 日按真实赛事去重后缺 `40` 场赛果：日本 6、英国 11、法国 4、美国 19。
- 日本可直接使用 JRA/NAR 官方结果；英国以 Sporting Life 预采、BHA 人工确认；法国以
  ZEturf 预采、France Galop 人工确认；美国 12 场已有 TOBA→Equibase 精确 chart，
  其余 7 场以 Sporting Life 预采、Equibase 人工确认。
- 本阶段只完成来源与可用性调研，未采集候选、未写库。逐场映射见 change 内
  `source_research_20260727.md`。

## 2026-07-27 赛果缺口恢复本地候选已实现

- 已完成 inventory、地区化结果候选、官方 receipt、canonical 去重、逐场原子 apply /
  rollback / verify 和历史批处理 allowlist；冻结范围仍为 40 场真实缺口、9 组重复赛事及
  单独保留 live owner 的 event 924。
- 恢复专属 SQLite `45/45` 与 PostgreSQL `2/2` 测试通过；完整候选相对同环境干净主线没有新增红项，
  且修复一个既有日历查询数失败。OpenSpec、Django、迁移、Compose、编译和 diff 门禁通过。
- 首次独立原生只读审核的 6 项 finding 已修复，正在由同一 reviewer 限定复审。当前仍是
  未提交本地实现；尚未部署、联网生成 candidate、人工批准 official receipt 或写生产库。
## 2026-07-27 赛事生命周期阶段 B0.1 赛后内部参考源规划

- 阶段 A 已在生产关闭态部署并完成 35 场零写 dry-run；`false/off` 未改变。
- TRA schema v2 runner 修复已随 PR `#27` 合入 `main`，但没有因此授权新的联网或 provider
  启用。
- Sporting Life、ZEturf、HRN 现固定为内部参考源：解析器保留，新增观察不公开、不 apply、
  不产生 official/provisional projection，也不触发新闻或 QQ。
- 阶段 B0.1 只处理现有 parser 的 finished 赛后入口，采用 run/payload/receipt 和逐日
  one-shot，不增加 Celery/Beat。
- 阶段 B0.1 spec/design/test/tasks/rollout 与自包含实现交接正在方案审核；当前没有新测试、
  代码、迁移、配置、联网、生产写入或发布。
- 独立 reviewer 前两轮 `REVISE` findings 已全部反映到修订稿；同一会话第三轮
  `APPROVED`，无开放 P0/P1/P2。当前等待用户实现授权。

## 2026-07-27 赛事生命周期阶段 B0.1 已通过第十七轮 review，最新 main 集成待复审

- 已按真实 RED 完成三源内部 reference 的 run/payload/receipt、只读 Admin、parse-only
  parser、安全 HTTP 和四个 one-shot 管理命令；没有 Celery/Beat/worker 或公开写入链。
- B0.1 首轮 SQLite `41/41`；代码 review 的 4 项 P2 均先补真实 RED 后修复，当前
  首轮为 `45/45`。第二轮限定复审另 4 项 P2 也按真实 RED 修复，当前 SQLite `49/49`、
  第三轮新增 1 项 P1 与 3 项 P2 修复后为 SQLite `53/53`，第四轮剩余 2 项 P2 修复后为
  SQLite `60/60`，第五轮新增 4 项 P2 修复后为 SQLite `64/64`，第六轮新增 5 项 P2
  修复后为 SQLite `69/69`，第七轮新增 3 项 P2 修复后为 SQLite `78/78`，第八轮为
  `80/80`，第九轮为 `82/82`，第十轮为 `84/84`，第十一轮为 `87/87`，第十二轮为
  `89/89`，第十三轮为 `93/93`，第十四轮为 `96/96`，第十五轮为 `98/98`，第十六轮为
  `104/104`；临时 PostgreSQL reference `3/3`、
  lifecycle PostgreSQL `5/5` 通过，历史 HTTP/parser 回归
  `82/82 GREEN / 4 conditional skips`。临时 PostgreSQL 16 容器已删除，未连接生产库。
- 两组 `141` 项扩展回归各有 1 项纯 `origin/main` 可复现的既有失败；historical batch
  扩展矩阵的 `18 errors / 7 skips` 也可在纯主线复现，代表性原因为 macOS
  `/var` 与 `/private/var` 规范化差异。
- Django、migration drift、编译、diff 与 workflow contract 通过。Compose 因隔离 worktree
  缺 `.env` 尚未完成；本轮没有 Compose 配置变更。
- 独立 reviewer session `019fa021-3552-7f23-a17f-2cae48ccc4bb` 对原 fingerprint
  `f2463878ffa4011aa91cf5b3cd7c5fe817b66157691e9eaf6e309640623695cd`
  给出 `VERDICT: REVISE`，P0/P1 均为 0，4 项 P2 为 collect 误绑定、ZEturf `R/C` 证明、
  `source_only` `KeyError` 和 report 多日指标。
- 同一 reviewer 第二轮 inner session `019fa02f-1976-7d10-b177-a18a0216591e` 对
  fingerprint `561cdbf66dd3a26c702366bd113d2aed197dc98446eec34856d2c2c1350e9200`
  仍给出 `REVISE`，4 项直接 P2 为 record racecourse 独立重验、report frozen event/date
  过滤和默认开发 Compose parser 可见性。四项已用真实 RED 修复，parser 单一实现已迁至
  `server/stable` 并由 compat wrapper/历史 CLI 复用；该轮修复后进入第三轮限定复审。
- 第三轮 inner session `019fa044-4483-72e1-b836-53e6900df34c` 对 fingerprint
  `22675d91cb097737bb678bd547874cce1ae1d7c481f416710911740a24981f06`
  确认上一轮 4 项 P2 全部关闭，但仍给出 `REVISE`：1 项 P1 是全局 HTML MIME 破坏
  PDF/JSON/XML，3 项 P2 是 ZEturf `NP`、HRN 国家后缀与 Sporting Life 下划线状态。
  修复已测试先行完成：MIME opt-in、collect 显式 HTML/XHTML、三 parser 规范化并保留 raw；
  该轮修复后进入第四轮限定复审。
- 第四轮 inner session `019fa051-bcf9-7e71-bd04-f11090fe8112` 对 fingerprint
  `a3f862fd93041831250fe855e383ee911843f6eb940433604c5a08b1f835b63b`
  关闭第三轮 3 项 finding、部分关闭 Sporting Life description，仍以 2 项 P2 返回
  `REVISE`：`ride_description` 下划线和 manifest parser identity 未绑定实际模块。两项均已
  先补真实 RED 后修复；service/build/collect/record 现按实际 stable 模块常量 fail closed。
  该轮修复后进入第五轮限定复审。
- 第五轮 inner session `019fa062-e917-76e2-aacd-e807fb0f1f9b` 对 fingerprint
  `50b50866f19853534daad66c9a2cd18650d4d74cafbfebec106b09c8b36c274d`
  确认第四轮 2 项 P2 全部关闭，但新增 4 项 P2 并返回 `REVISE`：transport-only circuit、
  parse failure raw、HRN race block 与固定 15 秒 timeout。四项均已先补真实 RED 并修复，
  该轮修复后进入第六轮限定复审。
- 第六轮 inner session `019fa071-ca82-7b80-9af1-d4725efb6c` 对 fingerprint
  `41307729d9896c7fbd721b2e8864177990a7d190d3c25011b53a0bf284db0d87`
  确认第五轮 4 项 P2 全部关闭，但新增 5 项 P2 并返回 `REVISE`：失败请求计数、HRN alias、
  ZEturf `FR + NP`、重复指标与 event-filtered run count。五项均已先补真实 RED 并修复，
  该轮修复后进入第七轮限定复审。
- 第七轮 inner session `019fa07f-90e2-7f60-b08d-125e01d55ba3` 对 fingerprint
  `6dd68951fe0ff90847c74f3873fb0539eec8226441473c294e7c444591ebba1a`
  确认第六轮 5 项 P2 全部关闭，但新增 3 项 P2 并返回 `REVISE`：ledger 完整性、
  unknown completeness 和 matched receipt `SET_NULL` 约束。三项均已先补真实 RED 并修复，
  该轮修复后进入第八轮限定复审。
- 第八轮 review session `019fa08e-e782-7d31-9cbc-921bb3b4efbd`、fingerprint 前缀
  `d98034f…` 的唯一 P2 是 runtime safe HTTP 会被默认开发 bind mount 遮蔽。3 项真实 RED
  后已改为 stable 唯一实现、runtime 兼容 wrapper、collect 直接 import stable；当前
  B0.1 `80/80`、历史 HTTP/parser `81/81`（4 skip）。
- Django、migration drift、编译、workflow 与 diff 通过；错误的整仓/app 容器挂载失败是
  验证环境误用，不是产品失败。Compose config 因 worktree 缺 `.env` 仍未执行成功。
- 第九轮 session `019fa09e-88c5-7180-a678-39874ff6e045` 对 fingerprint
  `84e8f4fafc4db634911c9aa18f6f473bdba12078e2957072a660434505c5ce6f`
  返回 `REVISE`（1 P1、3 P2）：runtime CLI `sys.path`、event/raw 逐场绑定、
  `error_summary` 与无 receipt 失败 run 报告。四项真实 RED 后已修复，当前 B0.1
  `82/82`、历史 HTTP/parser `82/82`（4 skip），项目 venv CLI `--help=0`。
- 第十轮 session `019fa0ad-c024-7a21-8ebb-31b19df760ab` 对 fingerprint
  `abbc00318318447abb86627ffe29a076012f8eceee4aa1b8d3f6c0c157dc4b20`
  仍返回 `REVISE`，唯一 P2 是 observations 必须与 `outcome=parsed` ledger event 精确
  一一对应，`parse_error` 必须零 observation。2 项真实 RED 后已最小修复，既有正向
  fixture 改为合法 `parsed + observation` 且 replay 继续验证；当前 B0.1 `84/84`、历史
  HTTP/parser `82/82`（4 skip），Django、migration drift、编译、workflow 与 diff 通过。
- 第十一轮 session `019fa0b9-b2c8-77d0-9473-7caff58d87eb` 对 fingerprint
  `ef778594f1d471a239432c6bd65054dcb2491fb918c46a660ea321436a827b0d`
  仍返回 `REVISE`（2 P2）：共享 safe HTTP 默认 `4MiB / 2 跳` 破坏 legacy 大
  PDF/redirect，跨日 run 的单日报告错误误归。纯 `origin/main` 调查确认旧 transport
  无 body cap 且 `urllib` 默认处理 redirect；3 项真实 RED 后，legacy 默认不自定义这些
  限制，collect 显式保留 `4MiB / 2 跳`，report 按 event/date 归属并单列
  `unattributed_errors`。当前 B0.1 `87/87`、历史 HTTP/parser `82/82`（4 skip），Django、
  migration drift、编译、workflow 与 diff 通过。
- 第十二轮 session `019fa0c7-7f55-7960-9f5d-5b81ba13437c` 对 fingerprint
  `6b0246db6647786e351492822d86f70a8dd15dbb272a19a6a34a324f15ca7b3b`
  仍返回 `REVISE`（2 P2）：matched 未核对来源赛事名，单日无 receipt 错误未回退 run
  唯一日期。反例 RED 后复用 race-live exact normalized alias 合同，manifest 冻结
  `normalized_accepted_race_names` 并纳入 snapshot SHA，record 要求 exact membership；
  single-day fallback 已补齐，过时 fixture 已修正。当前 B0.1 `89/89`、race-live
  `23/23`、历史 HTTP/parser `82/82`（4 skip），真实 PostgreSQL 并发/锁 `2/2`、
  `SET_NULL` `1/1` 且临时容器已删除；Django、migration drift、编译、workflow 与 diff 通过。
- 第十三轮 session `019fa0db-0a80-72c0-a6ad-bb1142432a83` 对 fingerprint
  `384ef97820f9e6d9c0c8f6df7190f1fb546746570aff018379b742a41e3b0c00`
  仍返回 `REVISE`（3 P2）：collect 异名未降 `source_only`、多日错误 detail 缺
  `local_date`、`--event-id` 漏无 receipt 匹配错误 run。3 项真实 RED 后，collect 改为
  exact frozen name 分类，ledger 逐 event 冻结日期并由 record 核验，event filter 按错误
  detail 纳入 run 且隔离其他错误；6 个旧 fixture 已补字段。当前 B0.1 `93/93`、
  race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL `3/3` 且临时
  容器已删除；Django、migration drift、编译、workflow 与 diff 通过。
- 第十四轮 session `019fa0ea-65a3-7383-b208-c0f571e7b98a` 对 fingerprint
  `18ac8b531f2d123b132fbe45104999feeea814315087ac6e4cdc0d043a4baeae`
  仍返回 `REVISE`（2 P2）：record 丢 artifact 采集窗口，无 receipt 失败 run 不计
  `duplicate_runs`。RED 锁定最早 ledger `fetched_at` 至 artifact `completed_at`，拒绝
  逆序/naive/显著未来，并覆盖同 event/day 重复失败 run；修复增加 5 分钟 clock skew、
  原子保存签名窗口，并统一 receipt/error-detail run membership。当前 B0.1 `96/96`、
  race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL `3/3` 且临时
  容器已删除；Django、migration drift、编译、workflow 与 diff 通过。
- 第十五轮 session `019fa0fa-b908-7d43-9f7e-807bf132a9a3` 对 fingerprint
  `59ffcb96972cef74dcff8df87e5a9d1b0f3923ecf59f5f5b594e58e48594424f`
  仍返回 `REVISE`（2 P2）：只校验最早 ledger 时间，observation provenance 的
  `fetched_at/final_url` 未逐 event 绑定。重签 artifact 反例 RED 后，record 要求
  `max(ledger fetched_at) <= artifact.completed_at`，且 observation 的 URL、时间及
  raw/ref/hash 与 manifest、parse ledger、response 逐 event 精确一致。当前 B0.1
  `98/98`、race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL
  `3/3` 且临时容器已删除；Django、migration drift、编译、workflow 与 diff 通过。
- 第十六轮 session `019fa106-3b52-7a02-b756-31f718ffe4d0` 对 fingerprint
  `571664940ea3e77b60368fe4ddf72292404060fedfb27f281d6b7f7d1f815cc7`
  仍返回 `REVISE`（唯一 P2）：Payload/Receipt
  `QuerySet.update/bulk_update/delete` 可绕过 append-only。6 项真实 RED 和 5 项实例/
  `SET_NULL` 正例后，专用 QuerySet/Manager 拒绝 Payload 全部批量变更；Receipt 仅允许
  Collector 精确清空 event FK，其他均拒绝；无需迁移。当前 B0.1 `104/104`、race-live
  `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL `3/3` 且临时容器已删除；
  Django、migration drift、编译、workflow 与 diff 通过。
- 第十七轮 session `019fa113-9c02-7c63-b48d-466c40d323cf` 对 fingerprint
  `5095a06e326a9cef470f4ef5d2111c87e8daa77a45fbc9507a27b024369edea7`
  给出 `APPROVED`，P0/P1/P2/P3 为 0，审前审后 fingerprint 一致。
- 用户授权发布后，fetch 发现 `origin/main` 已前进到 `6ac08e40`。候选已迁移到该最新主线，
  同时保留上游 recovery-mode/结果完整度与 B0.1 stable parser 委托。集成后 B0.1
  `104/104`、race-live `23/23`、历史 HTTP/parser `82/82`（4 skip）、真实 PostgreSQL
  `3/3` 通过；上游新增组合的 `14/87` macOS 路径错误在纯最新 main 精确复现。
- 系统 Python 缺 `bs4` 属于环境误用，不是产品失败；Compose 仍未验证。
- 当前未联网、未 commit/push/PR、未部署、未执行生产迁移或生产写入；latest-main 集成版本
  必须先复用同一 reviewer 完整只读复审，再针对新 fingerprint 取得发布授权。

# 2026-07-27 赛果恢复候选覆盖达到 40/40

- 初次 prepare 的 13 场缺口已通过 NAR 官方更新入口和 Sporting Life 补齐；审阅层现有
  40 场、319 条连续数字名次，无 `Also Ran` 代替顺序。
- 生产赛果仍为 0；美国 12 场 provider 调整与 NAR 后发布入口修复已在
  `codex/fix-race-result-gap-source-map` 完成，并以提交 `787d6a1e` 推送至草稿 PR `#36`。
  重基后恢复聚焦测试 `39/39`，历史 adapter 与 B0.1 相关回归 `192 passed / 4 skipped`。
- PR `#36` 尚未合并，gap-v2 尚未部署；下一门禁是取得独立合并授权，部署时保持全部开关
  关闭，随后再以单独联网授权重跑正式 prepare 并人工核验 Equibase。

# 2026-07-27 定时赛果审核进入代码审核门禁

- 72 小时新目标、14 天 pending、双时点调度、不可变审核包、稳定 Message-ID 邮件重试和
  exact reviewed bundle apply/verify 已在隔离分支完成，默认关闭。
- 四张治理表 migration 与生产 artifact 持久卷已补齐；`94/94` 相关测试及静态门禁通过。
- 尚未发布或启用；独立代码审核、发布授权、关闭态部署和首次受控 prepare 仍是独立门禁。

- 首次独立 review 的 4 项 P1 已全部完成真实 RED -> GREEN；SQLite 聚焦与相邻回归
  `107/107`、PostgreSQL 并发锁 `2/2` 通过。当前仍为未发布、默认关闭状态，待同一 reviewer
  限定复审。
- 同一 reviewer 已确认原四项关闭；后续发现的 verify 空 scope 与 apply 部分失败退出 0
  两项 P1 也已完成真实 RED -> GREEN。最新聚焦 `19/19`、直接相邻组合 `109/109`；
  继续等待限定复审，发布状态不变。

# 2026-07-28 部署 migration 单一 owner 方案已建立

- 最新 main 的标准/低成本 deploy、两条 rollback 和 web 启动入口存在重复 migration owner；
  `up -d web` 与随后的 `exec web migrate` 可能并发，是后续带 migration change 的共同发布
  blocker。
- 独立 change `fix-single-migration-owner` 已完成 Codex 原生 spec/design/test/tasks/rollout
  与自包含实现交接。推荐使用唯一 Compose one-shot release task、host-local 部署锁和 web
  healthy 下游启动门禁。
- 当前仅为文档设计，未实现、未提交、未部署、未连接生产。先独立方案审核，再等待用户明确
  实现授权。
- 同一独立方案 reviewer 三轮已关闭 race-live migration 窗口、owner token、pre-contract
  rollback bridge、greenfield 非目标、manual release 停服门禁和权威 runbook 一致性问题，
  最终 `APPROVED`，开放 P0/P1 为 0。当前已停在用户实现确认门禁。

# 2026-07-29 部署 migration 单一 owner 实现完成（待复审）

- 隔离分支 `codex/fix-single-migration-owner` 已完成全部脚本实现：migration/
  collectstatic 收敛为唯一 Compose one-shot release task，deploy/rollback/manual
  release 共享 host-local 部署锁与同一 release 编排，web healthy 前下游零启动，
  race_live_worker 仅按原始运行态停/恢复，pre-contract 回滚走独立兼容桥。
- 协调复审裁决后已在两条 rollback 的 ref 校验与 checkout 之间恢复 historical
  runner preflight；实现 review 六项 findings（ps 探测 fail closed、锁覆盖
  preflight、锁元数据 COMPOSE_FILE、manual restarting 检测列、drain 精确节点匹配、
  桥镜像自检）已全部修复。第 3 轮 Codex 原生 REVISE 的七项 findings（race-live
  状态跨重试持久化、bridge schema 显式门禁、v1 helper 全量 cat-file + 不可变 OID、
  probe 输出合法性、文档同步）也已修复。第 4 轮复审 findings（恢复意图与当前态
  probe 分离的重试语义、helper 扩 9 路径、OID 格式显式校验、文档 OID 化）已修复，
  14 项 RED 全绿；剩 2 项为测试侧张力（T11 成功用例需补 `git-rev-parse-output`）。
  相邻 historical runner 回归 `11/11`、shell 语法检查与 diff 检查通过。
- 未发布、未部署、未连接生产；等待测试侧修正与同一 reviewer 第 5 轮复审后冻结新指纹。

# 2026-07-30 部署 migration 单一 owner 完成 re-baseline

- 基线迁至 `6d073dc07cb29201bbc922255923820c872a0467`，分三跳：`7385f59` -> `7cd144ab`
  （main 增量 65 文件：race-calendar 日期窗口、race-news 质量、harden-celery-p0-admission 等）
  -> `be1c89bf`（PR #47 fix-p0-queue-snapshot-output）-> `6d073dc0`（PR #48，纯文档增量，
  无代码变化）；重叠文档均由主线程三方合并，零冲突。
- p0 closed-admission 脚本的 collectstatic 经用户批准登记为显式例外，最终基线上前提复核
  仍成立（1 次 collectstatic、0 migrate、2 次 `verify_migration_plan_zero`）；T01/T02 合同断言
  同步修订；聚焦套件终值 97 用例。
- 未发布、未部署、未连接生产；旧指纹失效，等待第 5 轮复审在新基线上冻结新指纹。

# 2026-07-30 部署 migration 单一 owner 第 5 轮 findings 修复完成

- p0 脚本接入共享部署锁、新增 resume 受审恢复入口、race-live 意图六字段可信绑定三组
  findings 已修复；owner 套件 `113/113`、p0 套件 `35/35`、相邻回归 `11/11` 通过。
- 未发布、未部署、未连接生产；等待同一 reviewer 第 5 轮复审并冻结新指纹。

# 2026-07-30 部署 migration 单一 owner 第 6 轮修复完成

- resume 可信意图消费后删除的 P1 已修复；四项 P2 建议记录在案不改代码。owner 套件
  `117/117`、p0 套件 `35/35` 通过。未发布、未部署、未连接生产；等待第 7 轮复审冻结新指纹。
