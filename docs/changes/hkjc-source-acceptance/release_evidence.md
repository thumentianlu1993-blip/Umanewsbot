# PR287 / PR288 组合发布记录

## 固定范围与授权

用户于 2026-11-09 明确确认整个发布包，包括 43 场日本策略换绑及香港杯名称、时区标识补正。
人工门禁仅引用根 `AGENTS.md`。

- PR287 合并：`b1feb895c6f84dd54934488a92fe5a216892a3a9`。
- PR288 合并：`9482ff86614431ad56a617f1751a4d2bbd982d7c`；组合 head `8feadc877f73191151cd77989c21b6c85f07532c`。
- 生产基线：`fd5349eff808b2d45740827bb65b28540787a1ad`；固定窄候选：`32cf8e34351b7ffec4a1805b3692ab936c22c2bd`。
- 镜像：`sha256:a6a7edf576c89d1b3714420e4d4fa41e05c5afa96f5d866c328852cd61685cb8`，schema0079，无迁移。
- 发布包 SHA-256：`32831a7683fd11f4a98a38ce82a6f05db485a7edf65c11210ebb918e083502d7`。
- 激活 manifest SHA-256：`decd10f9e1ce649f057b8d6101500fbae84f44c444aafc86be3fe9b0e24f62bf`。
- 来源策略 SHA-256：`82cafe9fe227ffffbfea5dd5d94e6bb502dcbf124e9633b1cc18985aa37018e9`。

发布启用 `HORSE_NAMES_REQUIRE_HKJC_ENABLED`、`RACE_DATA_SYNC_HKJC_PRE_RACE_ENABLED`，HKJC 赛前窗口45天，
providers 追加 hkjc。来源策略保留原 JRA/NAR 路由并增加已审 HKJC 路由；43 场既有日本 v2 登记换绑策略摘要，
保持比赛身份、路由和赛果内容不变。event2 增加 `LONGINES Hong Kong Cup` 官方别名，
时区标识改为 `Asia/Hong_Kong`，该日与原标识同为 UTC+8，不改保存的开赛时刻。

仅重建 web、worker、race_sync_v2_worker、beat；Nginx 检查并 reload。DB、Redis、JRA 浏览器不重建。
QQ 开关保持关闭，历史新闻不重译或改写，本包不包含香港历史赛果回填。

## 已完成发布前验证

- PR287 CI：1,025 项全部通过，零跳过；候选目录外交付核验通过。
- PR288 组合 CI `42507646755`：377 项全部通过，零跳过；test-plan-gate 和候选目录外交付核验通过。
- 窄候选独立 PostgreSQL 252 项、目标镜像内断网46项通过。
- 隔离生产公开赛事快照：精确数据脚本 dry-run 零留存、末项失败整包回滚、43项 apply、重复执行幂等通过；
  四场206条报名、三场尚未发布的断网重放通过。
- 同一独立 reviewer 完成代码、选测和运维复审，无剩余 actionable finding；四条协调器中断/配置漂移恢复用例通过。
- 上述离线回放不代替生产自然调度验收。

## 生产执行与验收

北京时间 2026-11-09 02:57，0079代码发布完成，四应用已运行窄候选。专用备份为935,372,125字节，
SHA-256 `f7151a2e7bd3d36e0676194ccfaa3b51b0e2bfcbdd9f0adca34d2d572e04ff11`，TOC 1,401行。
原 intent SHA-256 为 `00ecc3792a1502b5eec412b03192d038507202f5bf9e8b5d7432dabcb7852f51`。

激活在外置脚本 `django.setup()` 时因导入路径缺少 `/app/server` 失败，未写库。
只读状态回执为 `uncommitted`；恢复程序已还原原配置和四服务，双公网健康检查200，
3,566篇公开新闻、577行赛果、577行出走表、43份赛果版本逐项指纹不变。

修正版仅为两个临时数据脚本进程增加 `PYTHONPATH=/app/server`，没有改候选、镜像、数据manifest或范围。
精确镜像断网RED/GREEN、四路径恢复用例及原独立reviewer复审均通过。
修正版包 SHA-256：`c306dbde2e4fd36d7bffb69fe4fceb8ff63720cbd4cf9a8266edf6a595419037`。
用户明确确认修正版后，以 `resume-activation` 续跑，于北京时间03:09:17完成。
生产dry-run回滚通过，apply回执为43场登记换绑、event2别名/香港时区补正，新增赛果/出走行均为0；只读核验 `committed`。
四应用运行精确目标镜像及新配置，Web healthy、重启0、无OOM，两个worker分别消费celery和race_sync_v2队列并回应ping；共享发布锁释放。

56个受影响赛事页（43场日本、13场香港）HTTP全部200。公开JBC雌马经典赛保留“杏饴”、其他未验证译名回原文；
JBC经典赛隐藏“超越射程”并展示“アウトレンジ”，天皇赏保留“北十字星”；马匹54页面显示原文和“中文译名待补”。
15,180条译名符合来源规则，6,417条公开回退；3,566篇历史新闻与577行赛果/出走表、43份版本逐项不变。
北京时间03:17自然任务 `8c56d8e0-fd78-4a91-93f8-2b4423f82ece` 自动运行，03:17:36返回SUCCESS，
HKJC `checked=7/attempted=7`。七场状态及公开页复核：香港杯72、香港一哩锦标54、香港短途锦标21、香港瓶59，
共206条registration；另外三场为not_published。四个名单公开标题为“报名名单”，更新时间03:17，
没有马号/闸位/骑师时保持空白；七个HTTP页面与候选行数一致。香港杯报名区、JBC赛果和马匹54已做真实浏览器验收。
全过程未手动执行发现任务冒充自然调度。

因此本发布包的激活、运行、自然赛前采集与公开展示验收完成；下述数据完整性缺口仍保留。

## 中断恢复边界

同一协调者同时持有生产 flock 与共享 deployment lock，锁覆盖受保护0079入口、备份、服务切换及激活。
发布阶段中断沿原 intent、SHA、镜像执行 `resume-release`；激活阶段以数据库只读回执判定事务状态，
使用同包 `resume-activation`。未提交时恢复已验证的原配置；已提交时只允许精确目标配置并恢复服务。
配置漂移或数据状态未知时停止 writers，不以进程退出码推断是否提交。

停用新功能时可关闭马名/HKJC开关并移除 hkjc provider，但必须保持来源 policy 与43场登记摘要一致。
不得只恢复旧 policy 摘要、随意退回旧镜像或整库覆盖并行业务；代码问题优先同 schema 前向修复。

## 验收范围限制

- 香港杯页面的日期/时间仍待定、距离仍待核实。发布前数据库快照已有 `race_datetime=null`，激活后03:12首次HTTP验收页仍显示待定；
  本包只新增官方名称别名、调整时区标识及接入报名，不补写日期/距离，不宣称该页基础信息完整。
- 香港9–12月13场中，六场已结束赛事只有首场原有生产赛果；其余五场仍缺生产赛果，本包不回填。
- 尚未公布的正式出马表，以及下一场赛后的自然状态更新，按用户已接受的安排留待实况回归。
- 来源验收取得的六场57行结果，不等于本次向生产新增57行。

证据目录：本机 `/Users/mentianlu/.codex/runtime/hkjc-combined-release-20261109/`；
生产固定工作目录 `/opt/umanews-release-32cf8e34-hkjc-20261109/umanewsbot`，
外部发布文件目录 `/opt/umanews-external-staging/hkjc-combined-32cf8e34`。

## 证据索引

运行目录中保留 `release-package.json`、`production-backup-receipt.json`、`production-activation-applied.json`、
`services-final.json`、`worker-readiness.json`、`production-acceptance-final.json`、`data-integrity-acceptance.json`、
`natural-task-result.json`、`natural-acceptance.json`、`natural-public-report.json`、`public-http-report.json`、
`public-health.json` 和 `browser-acceptance.json`。原失败包保留于 `approved-v1/`，未覆盖历史证据。
