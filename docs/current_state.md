# 当前状态

## 当前结论

项目当前已经完成正式域名 HTTP 接入修复，`umafans.run` 与 `www.umafans.run` 已可访问。  
“自动化内容运营 + AI 编辑改写 MVP”已完成代码侧与生产侧上线，当前处于上线后观察与质量抽检阶段。

`2026-07-07` OpenSpec change `hkjc-ja-alias-article-backfill` 已完成实现并部署生产。新增 `stable.services.term_maintenance`、`merge_hkjc_ja_aliases` 和 `backfill_article_terms`，用于处理 HKJC 日本马日语 alias 概念合并，以及已发布文章中文字段的术语精确回填。概念合并默认 dry-run 输出 `merge_plan.json` / review CSV / summary，正式写入必须使用已审核 `--plan-file`；apply 会重新校验 active owner 占用，只合并同类型、同中文目标、active 日语主术语的安全项，并将冗余日语主术语停用，notes 中记录 `hkjc_ja_alias_merged_into_term_id=<target>`。这也是术语库中一部分 inactive 术语的合理来源：它们不是删除，而是被更完整的正式概念吸收后的历史主术语。文章回填默认只扫描已发布文章，输出完整 before/after JSON 与人工 review CSV；正式写入必须使用已审核 `--diff-file`，或显式提供 term/article/date/source/limit 过滤范围，且默认跳过 `manually_edited_fields` 中的发布字段，不重新翻译、不调用 AI 改写、不改变发布、审核、workflow 或 QQ 推送状态。本地验证已通过 `DB_ENGINE=sqlite python manage.py check`、`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput`（最终 `473` 项）、`openspec validate hkjc-ja-alias-article-backfill --strict` 和 `git diff --check`。生产服务器 `/opt/umanewsbot` 已部署到 `a65c1ed`；部署前备份 `.env` 为 `.env.backup.hkjc-ja-alias-backfill-20260707_184118`，数据库备份为 `backups/db/pre-hkjc-ja-alias-backfill-20260707_184118.sql.gz` 且 `gzip -t` 通过。生产 HKJC alias dry-run 为 `candidate=112 skipped=0`，正式 apply 写入 `112` 条日语 alias 并停用 `112` 条冗余日语主术语；post-apply smoke 为 `candidate=0 scanned=0`。文章回填 dry-run 扫描 `713` 篇日文已发布文章，命中 `7` 篇，计划更新 `29` 个字段、跳过 `2` 个人工字段；正式 apply 为 `updated=29 skipped=2 stale=0`。artifact 已复制到生产宿主机 `runtime/term_backfills/hkjc-ja-article-backfill-20260707_192910/`、`runtime/term_backfills/hkjc-ja-article-backfill-apply-20260707_192931/`、`runtime/term_backfills/hkjc-ja-alias-merge-postapply-smoke-20260707_192810/`。抽检确认 `Kalamatianos / カラマティアノス -> 欢快舞步` 为日本地区 active term `6443` 的 active EN/JA alias，`/news/7117/` 返回 `200` 且页面包含 `欢快舞步`；生产 `manage.py check`、本地和公网 `/healthz/` 均通过。

`2026-07-07` 本地已实现并准备上线 OpenSpec change `expand-france-news-sources`。该变更为法国新增 `tdn_france_broad` 英文补充来源：使用 TDN 公开 WordPress 搜索 API 聚合 `French racing`、`ParisLongchamp`、`Deauville`、`Chantilly` 等关键词，`canonical_source_site=tdn`，通过 URL / source_article_id 复用既有 TDN 去重，默认 `enabled=false`、`production_approved=false`，需灰度启用后才进入生产抓取。真实只读探测显示 `tdn_france_broad` accepted：HTTP `200`、列表 `20` 条、详情样本 `2` 条、最大正文长度 `12735`、重复数 `0`；`at_the_races_france` 当前仍因 HTTP `403 / Client Challenge` 标记为 deferred/access_limited，不生产批准。探测命令已输出 `status/deferred_reason/http_status/final_url/parse_quality/duplicate_ratio/query_errors/sample_errors`，并支持多关键词来源在部分关键词失败时记录 `query_errors`、单篇详情样本失败时记录 `detail_error_count` 后继续采样后续文章；国际新闻来源生产抓取已改为“单篇详情解析失败则跳过并继续处理其他文章，全部详情都失败才将来源标记为 failed”，避免一篇坏详情拖垮整轮来源或把全失败伪装成无新稿。来源同步新增 `MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES=ja,en,zh-hant` 保护，法语源即使误配置 production approved 也会降级为未批准并写 `source_language_not_supported`；法国审计摘要可区分成功无新增、解析失败来源 ID、门禁 blocker 和示例文章。

`2026-07-07` 本地已实现并准备上线 OpenSpec change `fix-english-term-gate-region-filter`。该变更针对香港、英国、美国等英文新闻被 `core_term_missing` 大量误挡的问题：英文发布校验第一版只检查文章同地区术语和 `racing_region=""` 全局术语；`class/content/link/agent/oaks/america/numbers` 等配置化高歧义英文词会降级为 warning，不再默认生成硬 blocker；未配置的短词 / 全大写词只有在非核心命中时才会派生降级，真正同地区 / 全局高可信核心马名、赛事名等缺失仍会阻断自动发布。新增 `reprocess_term_gate_blocked_articles` 管理命令，可对最近发布候选回看窗口内、因术语 blocker 进入人工审核的文章执行 dry-run 或 commit 重校验，commit 只会重新进入 `publish_ready` 候选并写 `ranked_revived_at`，不会直接公开发布文章。生产审计摘要已增加 `articles.gate_issues`，用于区分真实 blocker、高歧义降级和地区排除。上线后需只读验证香港、英国、美国最近窗口的 `core_term_missing` blocker、`publish_ready` 和公开数量。

`2026-07-07` OpenSpec changes `expand-france-news-sources` 与 `fix-english-term-gate-region-filter` 已部署生产。生产因 GitHub HTTPS 连接超时，改用本地 `git bundle` 将提交 `bfc3445` 传入 `/opt/umanewsbot` 并 fast-forward 部署；部署前数据库备份为 `backups/db/pre-france-source-term-gate-20260707_200124.sql.gz`，已执行 `gzip -t`。部署后 `web / worker / beat / db / redis / nginx` 正常，`manage.py check` 通过，本地与公网 `/healthz/` 均返回 `200`。`tdn_france_broad` 生产只读探测 accepted：HTTP `200`、列表 `20` 条、详情样本 `5` 条、详情错误 `0`、重复 `0`；已在生产启用 `NewsSource#21`，设置 `enabled=true`、`production_approved=true`、`effective_crawl_interval_minutes=15`，并把 `tdn_france:access` 与 canonical 入库后的 `tdn:access` 加入 `MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES`。真实人工抓取验证因中途补生产配置重启被打断，已入库法国新来源文章 `7250-7253` 共 `4` 篇；中断的人工 `CrawlJob#9330` 已标记为 failed 并记录 `success_count=4`，错误说明为部署配置重启中断，不代表来源失败。4 篇均已补翻译并重新跑自动化，当前均为 `manual_review_required / pending_review`：其中 `7250-7252` 因真实 `core_term_missing` blocker 转人工，`7253` 因总分 `69` 转人工。最终审计文件位于生产容器 `runtime/multiregion_audit/post-france-source-term-gate-final-20260707_202851.json`：法国来源总数 `4`、启用 `3`、生产批准 `3`、paused/backoff 均为 `0`，今日法国新入库 `4`、公开 `0`，公开为 0 的原因是正常门禁转人工而非抓取或来源白名单失败。英文门禁重处理 dry-run：香港、美国、法国最近 3 小时无可释放 `core_term_missing` 候选；英国有 `1` 篇候选但仍被真实核心术语缺失阻断，未执行 commit。

`2026-07-07 21:00` 线上回归复核：生产仓库 `HEAD=dcb9b90`，容器运行正常，`manage.py check`、本地/公网 `/healthz/`、首页和 `/admin/login/` 均通过；生产开关 `MULTIREGION_PRODUCTION_WINDOWS_*`、`NEWS_SOURCE_POLL_ENABLED` 均为开启，`tdn:access` 与 `tdn_france:access` 均在自动发布来源白名单中。法国新来源 `tdn_france_broad` 再次只读探测 accepted，HTTP `200`、列表 `20`、详情样本 `2`、详情错误 `0`，重复率 `0.5` 是因为自然抓取已写入同批文章。自然窗口已派发 `CrawlJob#9355`，截至复核时仍为 `started`，但已通过 `source_config=21` 入库 `10` 篇法国文章，其中 `9` 篇已翻译、`1` 篇翻译中；Celery active 显示该 crawl task 正在 worker 内运行，worker 日志持续出现 SiliconFlow `200 OK`，因此判断为“单轮处理耗时偏长但仍在推进”，不是来源不可用。最近 90 分钟五地区发布/QQ 窗口均为 succeeded，0 结果均有 `no_ready_candidates / no_eligible_articles / already_sent` 等原因；英文门禁 dry-run 复核为香港/美国无候选、英国 `7242` 仍真实 blocker、法国 `7250/7251/7252` 仍真实 blocker，无可释放误挡文章。

`2026-07-07` 发现法国新来源 `tdn_france_broad` 抓入历史旧文并有旧文自动发布。根因是 TDN `/wp-json/wp/v2/search?search=French%20racing` 返回按相关性排序的历史搜索结果，search item 只有 `id/title/url`，没有 `date/date_gmt`；当前 adapter 复用 `TDNAdapter._api_datetime()`，在缺少日期时兜底为 `timezone.now()`，而详情页解析也未纠正为真实发布时间，导致 2020/2022/2023/2024 旧文被写成 `2026-07-07T14:05:04Z` 并进入发布窗口。已立即暂停生产 `NewsSource#21`：`enabled=false`、`production_approved=false`，`manual_pause_reason=paused 2026-07-07: TDN search endpoint returned historical articles without dates; old articles were stamped as current`。已确认公开受影响旧文包括：`7255` 实际 `2022-03-21`，`7263` 实际 `2020-04-07`，`7264` 实际 `2020-03-16`，`7265` 实际 `2020-03-13`，`7271` 实际 `2024-11-08`。后续修复应改为从 search item 的 `_links.self` / post `id` 二次读取 `/wp-json/wp/v2/posts/<id>` 的真实 `date_gmt`，并在 adapter 或生产抓取层丢弃超过允许新鲜度窗口的文章；修复前不要重新启用该来源。

`2026-07-04` OpenSpec change `race-event-page-mvp` 已按已确认 Stitch 原型完成赛事日历 / 年度赛事详情页 MVP，并已部署生产。新增 `RaceEvent` 产品层模型、别名、出马表、赛果、历史冠军、候选资料和 `ArticleRaceLink`；公开入口为 `/races/` 与 `/races/<year>/<slug>/`，文章详情页会展示已确认关联赛事；业务后台新增 `/admin/race-events/`，支持赛事列表筛选、详情维护、候选资料应用、手动关联/移除新闻和人工移除保护。管理命令新增 `import_race_events`、`fetch_race_event_candidates` 和 `research_live_race_fields`，样例 CSV 位于 `server/stable/data/race_events_seed_sample.csv`。本地 code review 后已修复后台赛事列表筛选翻页丢参问题，并补充回归测试。生产服务器 `/opt/umanewsbot` 已部署提交 `f3c4c46`，迁移 `stable.0020_raceevent_articleracelink_raceeventalias_and_more` 已应用；已正式导入 5 条 P0/P1 赛事种子和 10 条别名，当前 `ArticleRaceLink=0`，后续新闻关联仍需自动匹配或人工维护。第一版不建设马匹数据库、完整赛果库、复杂赛事聚类或赛中实时进度。

`2026-07-04` 本次赛事日历 / HKJC overseas 术语种子上线前，本地验证已通过 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable --noinput`（442 项）、`openspec validate --all`（17 项）和 `git diff --check`。生产部署前确认没有正在运行的外部数据导入和导入锁；备份 `.env` 为 `.env.backup.race-calendar-hkjc-overseas-20260704_182412`，数据库有效备份为 `backups/db/rds_horse_news_race_calendar_manual_20260704_182458.sql.gz` 并通过 `gzip -t`。部署后 `manage.py check` 通过，`showmigrations stable` 显示 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`，`web / worker / beat / db / redis / nginx` 均运行，`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/` 和 `/admin/login/` 均返回 `200`，未登录 `/admin/race-events/` 返回 `302` 到登录链路。生产容器内 HKJC overseas fixture smoke 生成 `candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`，输出目录为 `runtime/termbase_seed/hkjc-overseas-deploy-smoke-20260704_183048`；本次未把 HKJC overseas 候选导入正式术语库。

`2026-07-06` 已按“赛事日历正式填充前先线上验收、再给示例审核”的节奏完成第一步。生产 `/opt/umanewsbot` 当前 `HEAD=c996621`，`web` healthy，`worker / beat / db / redis / nginx` 正常；公网 `umafans.run/healthz/`、`/races/` 与 `/admin/login/` 均返回 `200`，`manage.py check` 通过，`stable.0020_raceevent_articleracelink_raceeventalias_and_more` 已应用。生产当前赛事模块计数为 `RaceEvent=5`、`RaceEventAlias=10`、`RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventDataCandidate=0`、`ArticleRaceLink=0`，五地区各 1 条样例赛事，`ExternalDataImportRun(status="started")=0` 且导入锁为空。已从 JAIRS/JRA 官方英文页抓取 `2025 Japan Cup` 赛后样例审核包，路径为 `runtime/race_event_review_samples/japan-cup-2025-20260706/`，包含 `race_events_sample.csv`、`race_event_candidate_payload.json`、`source_official.html` 和 `README.md`；该样例为日本 G1、非 listed、非地区重赏，解析出基础资料 1 组、出走表 17 匹、正式完赛赛果 16 条。`import_race_events --dry-run` 对该 CSV 通过，候选 JSON 通过 JSON 校验。本次未写生产库；示例中 `visibility_status=draft`，且术语库/官方中文未命中 `Japan Cup` 与 `Tokyo Racecourse` 时按约定保留原文，等待人工审核补全。

`2026-07-06` 赛事日历正式填充已开始写生产库。按用户要求优先使用本地语言官方源：日本批次改用 JRA 日文重赏一覧 `https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`，生成并导入 `runtime/race_event_imports/2026/japan-jra-central-graded-20260706/race_events_japan_jra_2026.csv`；范围为 2026 年 JRA 中央 G1/G2/G3/J-G1/J-G2/J-G3，不含 Listed/Open 和地方交流重赏，生产导入结果为 `created=139 updated=1 aliases=413`，其中 `宝塚記念` 更新原样例 `takarazuka-kinen`，当前 `japan/year=2026` 共 `140` 场，状态分布 `finished=74`、`scheduled=66`。香港批次使用 HKJC 繁中官方源 `https://racing.hkjc.com/zh-hk/international-racing/g2-g3-races/index` 与 `https://campaigns.hkjc.com/racing-event-hub/ch/`，并用 HKJC 本地赛果页补马场、距离和场地，生成并导入 `runtime/race_event_imports/2026/hong-kong-hkjc-pattern-20260706/race_events_hong_kong_hkjc_2026.csv`；范围为 HKJC 当前公开 2025/26 马季内日期落在 2026 年的香港 G1/G2/G3，共 `19` 场，已过滤非单场赛事卡片 `沙田煞科日`，不猜测尚未由 HKJC 公开 2026/27 日期的 2026 年末香港国际赛。香港导入结果为 `created=19 updated=0 aliases=74`；生产当前 `RaceEvent=163`、`RaceEventAlias=497`、香港 2026 共 `20` 条，其中 `19` 条为本批 HKJC 官方源，另 `1` 条为既有香港杯样例。日本与香港详情页均已通过公网 Host 验收；香港默认重点日历页因只显示当前前后 30 天且过滤 P2，需用 `tab=all` 或 `direction=past` 查看本批历史赛事。

`2026-07-06` 继续补齐 2026 目标地区重要赛事并写入生产。日本地方/交流ダートグレード使用 NAR 官方 `https://www.keiba.go.jp/dirtgraderace/2026/racelist/index.html` 与官方 PDF `https://www.keiba.go.jp/pdf/uploads/20251110_01_01.pdf`，导入地方竞马场 JpnⅠ/JpnⅡ/JpnⅢ 与大井东京大赏典 GⅠ 共 `46` 场，结果 `created=46 updated=0 aliases=105`；其中 `22` 场官方给出发走时刻，`24` 场日期确定但时刻待定，前台详情页已验证帝王赏显示 `20:05`、东京大赏典显示“待定”。为支持美国 all-weather/synthetic 赛事，已新增 `RaceEventSurface.SYNTHETIC=synthetic/复合赛道` 并部署生产 `9dc9b4d`，迁移 `stable.0021_alter_raceevent_surface` 已应用。美国使用 TOBA 官方 `https://toba.org/graded-stakes/2026-races/`，导入 2026 American Graded Stakes 表内 Grade 1/2/3 共 `411` 条，结果 `created=411 updated=0 aliases=1550`；其中 `370` 条有日期并公开展示，`41` 条空日期或 `not run` 作为 draft 底表记录保留，Listed `200` 条与其他非分级黑体 `12` 条已排除，Jeff Ruby Steaks 已验证显示“复合赛道”。英国当前可靠导入 BHA Jump 官方 `British_Jump_Pattern_Listed_2526.pdf` 中 2026 年 1-4 月 Grade 1/2 共 `64` 场，结果 `created=64 updated=0 aliases=192`；英国 Flat 官方 2026 PDF 正文页文字层为空，仍需 OCR 或另一官方结构化源；Jump 2026 年 10-12 月需等待 2026/27 官方书或其他官方源。法国使用 France Galop 官方 `groupes_listed_plat_2026_v7.pdf` 与 `groupes_listed_obstacles_2026_v4.pdf`，按逐赛条件页导入 Groupe I/II/III 共 `173` 条，结果 `created=173 updated=0 aliases=519`，其中 Flat `113`、障碍 `60`，Listed 已排除；Prix Ganay 与 Grand Steeple-Chase de Paris 详情页已验证。生产当前 `RaceEvent=857`、`RaceEventAlias=2863`；2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `65`、法国 `174`。剩余缺口主要是香港 2026 年末 HKJC 尚未公开赛期、英国 Flat 2026 官方 PDF 需要 OCR/结构化替代源、英国 Jump 2026 年 10-12 月官方赛季书未确认。

`2026-07-06` 已继续补上英国 Flat Group 赛事。BHA 官方 `British_Flat_Pattern_Listed_2026.pdf` 正文页无可用文本层，本次使用 macOS Vision OCR 识别官方详情页，生成 `runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/race_events_united_kingdom_bha_flat_2026.csv`；范围为英国 2026 Flat `Group 1/2/3`，排除 Listed，共 `138` 场，等级分布 `G1=33`、`G2=42`、`G3=63`，其中 `59` 场按当前日期归为 `finished`、`79` 场为 `scheduled`，复合赛道 `6` 场、草地 `132` 场。距离字段来自 OCR，已对明显残缺值做清理并保留 `data_quality_status=partial`；赛事名、日期、场地和等级来自官方详情页。生产导入前备份为 `backups/db/pre-race-events-uk-bha-flat-2026-20260706_222151.sql.gz`，约 `74M`，`gzip -t` 通过；生产 dry-run 通过后正式导入 `created=138 updated=0 aliases=414`。导入后生产 `RaceEvent=995`、`RaceEventAlias=3277`，2026 五地区计数为日本 `186`、香港 `20`、美国 `412`、英国 `203`、法国 `174`；英国 Flat 页面验收 `/races/2026/uk-bha-flat-2026-0704-058/` 显示 `CORAL-ECLIPSE`，复合赛道样例 `/races/2026/uk-bha-flat-2026-0905-102/` 显示 `UNIBET SEPTEMBER STAKES` 与“复合赛道”。当前剩余缺口收敛为：HKJC 尚未公开 2026/27 马季年末香港本地 G1/G2/G3 日期明细；英国 Jump 2026 年 10-12 月需等待 2026/27 官方书或其他官方结构化来源。

`2026-07-06` 已开始正式填充 2026 赛事详情表，第一批完成 JRA 中央重赏已完赛场次的出走表和赛果。官方来源继续使用 JRA 日文重赏列表和各赛事结果页，产物位于 `runtime/race_event_detail_imports/2026/japan-jra-details-20260706/`，包括 `jra_detail_candidates_2026.jsonl`、`jra_detail_review_2026.csv`、`summary.json` 与页面缓存；生成结果为 `74` 场、`1112` 条出走表、`1106` 条数字名次赛果，另有 `取消=2`、`除外=2`、`中止=2` 保留在出走表状态中。生产写入前备份为 `backups/db/pre-race-event-details-jra-2026-20260706_224953.sql.gz`，约 `75M` 且 `gzip -t` 通过；生产 dry-run 确认 `events=74`、`runners=1112`、`results=1106` 后正式应用 `148` 个候选模块。第一次 apply 因 JRA 同着导致 `finish_position` 唯一约束冲突而中止，已将失败留下的 `1` 条旧 pending 候选标记为 `failed`；修正后用唯一排序位写入 `finish_position`，并在 `source_refs.official_finish_position` 保留 JRA 官方名次。导入后生产 `RaceEventRunner=1112`、`RaceEventResult=1106`、`RaceEventDataCandidate=192`、`AppliedCandidates=191`、`FailedCandidates=1`；宝塚記念详情页显示 `メイショウタバル`、出走表和赛果，安田記念同着马 `ワールズエンド` 与 `ガイアフォース` 前台均显示官方第 `2` 名。为让同着展示立即正确，已将 `views.py` 和两个公开模板热补丁复制进 `web` 容器并重启，同步本地代码已保留但尚未通过 git 镜像部署固化；后续正式部署或容器重建前必须先提交/部署该展示修复，避免热补丁丢失。

`2026-07-06` 已继续补齐日本 NAR/地方交流重赏当前官方可用详情。NAR 使用 `keiba.go.jp` ダートグレード特设页的 `racecard.html` 自动发现 `KeibaWeb/TodayRaceInfo/DebaTable`，已完赛赛事再跳转 `RaceMarkTable`；产物位于 `runtime/race_event_detail_imports/2026/japan-nar-details-20260706/`，包括 `nar_detail_candidates_2026.jsonl`、`nar_detail_review_2026.csv`、`summary.json` 与页面缓存。生成结果为 `21` 场、`256` 条出走表、`242` 条数字名次赛果；其中 `20` 场已完赛写入出走表和赛果，`2026-07-08` スパーキングレディーカップ已公布出走表但未有赛果，仅写入赛前出走表；后续 `25` 场仍停留在 `introduction.html` 且官方未公布出走表，记录为 `racecard_not_published`。生产写入前备份为 `backups/db/pre-race-event-details-nar-2026-20260706_232856.sql.gz`，约 `75M` 且 `gzip -t` 通过；dry-run 确认 `events=21`、`runners=256`、`results=242` 后正式应用 `41` 个候选模块。导入后生产详情表为 `RaceEventRunner=1368`、`RaceEventResult=1348`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=233`、`AppliedCandidates=232`、`FailedCandidates=1`，全部详情行当前仍为日本地区。页面验收：`/races/2026/nar-dirt-2026-0701-20/` 显示帝王賞冠军 `ミッキーファイト`、出走表、赛果和 `2:02.8`；`/races/2026/nar-dirt-2026-0708-21/` 显示スパーキングレディーカップ出走表和 `レクランスリール / アピーリングルック`，未显示赛果区块。当前按用户指定顺序，日本 JRA/NAR 中“官方已公布的出走表/赛果”已补完；JRA 未来 66 场和 NAR 未来 25 场需等官方出走表或赛果发布后刷新。

`2026-07-06/07` 已继续补香港与美国 2026 已完赛重赏详情。香港使用 HKJC 繁中官方 `resultsall` 日汇总页定位 RaceNo，再进入单场 `localresults` 完整赛果页；产物位于 `runtime/race_event_detail_imports/2026/hong-kong-hkjc-details-20260706/`。生成并导入 HKJC 已公开 2026 本地 G1/G2/G3 `19` 场、`182` 条出走表、`181` 条数字名次赛果；`WV` 保留为 `withdrawn` 出走状态但不写赛果，马名/骑师/练马师展示字段已从繁中转简体，原始繁中保存在 `source_refs`。生产写入前备份为 `backups/db/pre-race-event-details-hk-2026-20260706_234317.sql.gz`，约 `75M` 且 `gzip -t` 通过；dry-run 通过后正式应用 `38` 个候选模块。页面验收：`/races/2026/hkjc-2026-0125-05/` 显示董事杯冠军 `浪漫勇士`、完整出走表和赛果，`祝愿 / 阳光勇士` 同为官方第 `4` 名且时间 `1:33.18`；`/races/2026/hkjc-2026-0621-19/` 显示精英碟出走表中 `非惟侥幸` 为取消出走，赛果只保留 `11` 条已确认名次。

美国使用 TOBA 官方分级赛表确定 2026 已完赛范围，并以 TOBA `chart_url` 中的官方 RaceNo 辅助匹配 Horse Racing Nation track-day 页面；Equibase chart HTML/PDF 当前仍返回防护页，因此 HRN 仅作为可访问公开结果源。产物位于 `runtime/race_event_detail_imports/2026/united-states-hrn-details-20260706/`。生成并导入美国 TOBA Grade 1/2/3 已完赛 `195` 场、`1710` 条出走表、`1448` 条可确认赛果；马名展示字段已剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。HRN 对 Kentucky Derby / Kentucky Oaks 等少量大赛页当前只公开出走表、不公开 payout/also-rans 结果块，本批不从 TOBA winner 字段猜完整名次，因此这些赛事可显示出走表但暂无赛果。首次 apply 因 HRN HTML 重复渲染同一出走马导致唯一马号冲突中止，已将旧 pending 候选标记为 failed，并在生成器中按 `horse_number + horse_name + horse_url` 去重后重跑成功。生产写入前备份为 `backups/db/pre-race-event-details-us-hrn-2026-20260707_000230.sql.gz`，约 `75M` 且 `gzip -t` 通过；最终正式应用 `390` 个候选模块。导入后生产详情表为 `RaceEventRunner=3260`、`RaceEventResult=2977`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=992`、`AppliedCandidates=990`、`FailedCandidates=2`、`PendingCandidates=0`；其中美国详情为 `1710` 条出走表和 `1448` 条赛果。页面验收：`/races/2026/us-toba-2026-0108-001/` 显示 Robert J. Frankel S. 冠军 `Paradise Lake`、出走表和赛果；`/races/2026/us-toba-2026-0502-119/` 显示 Kentucky Derby 出走表但因 HRN 未公开结果块暂不显示赛果。当前顺序进度为日本、香港、美国已完成当前可用详情，下一步继续英国、法国，再处理历届冠军。

`2026-06-27` 全球赛马数据库接入当前处于能力确认完成状态：香港 HKJC 已有生产真实 dry-run 批次证据，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 已完成少量真实 proof，证明四地公开入口、parser/importer、马匹详情链路、低频限量抓取和 proof-only 离线审计可用。用户已将本目标完成口径调整为“先保证所有地区的数据爬取能力真实可用”，不再要求本目标内完成最近 2 个月完整大量爬取或生产真实网络 commit。当前主工作树已同步外部缓存底座、HKJC、UK/France/US importer、fixtures、OpenSpec 归档和 proof JSON，用于后续恢复；这些同步内容仍是未提交工作树差异。交接索引见 `docs/global_racing_database_handoff.md`。

同步后本地验证已覆盖 Django check、外部缓存底座、HKJC、UK/France/US importer、global racing isolation、proof-only 离线审计测试、OpenSpec 全量校验和 `git diff --check`；离线 commit 候选审计已加严为要求 plan-only 具备请求证据和成功响应，非 plan 批次具备请求证据、成功响应和非空 `races/entries/results/horses` coverage；四地 importer 的生产写库门禁已加严为只有 `completion.is_complete=true` 的严格布尔完成证明、completion 内部无受限停止或马匹详情缺口、completion 内含可解析 `unique_horses_found` / `horse_profiles_fetched` 计数、且 payload 具备非空 `races/entries/results/horses` coverage 时才允许 commit。HKJC、UK、France Geny、US 的 plan-only 命令均要求显式 `--allow-network`，避免误把最近 60 天拆批计划当成本地无网络操作；新增 `render_global_racing_batch_command` 只读命令，可从 plan JSON 渲染指定批次或全部批次的精确 dry-run/commit 命令，并可根据 `--output-dir` 给出稳定 `suggested_output_path` 和可直接执行的 `tee_command_line`，减少手工复制 `race_ids`、`race_urls` 或 `partants_urls` 以及覆盖批次 JSON 的风险，离线审计会忽略这类命令清单 artifact。详见 `docs/global_racing_database_handoff.md`。当前同步范围清单见 `docs/global_racing_sync_manifest.md`。

`2026-07-03` 生产只读核对多地区术语库与外部马名索引：服务器 `/opt/umanewsbot` 当前 `HEAD=4323d32`，`web/worker/beat/db/redis/nginx` 均在运行。正式术语库 `TermEntry=2054`，全部为 `source_language=ja`，其中 `horse=1884`、`race=153`、`fixed_phrase=15`、`jockey=2`，`TermAlias=2057` 也全部为日文；正式术语的 `racing_region` 仍为空，尚未形成香港、英国、法国、美国分地区正式术语内容。术语候选池 `TermCandidate=3519`、证据 `13725`，当前同样全部为日文候选。外部马名索引 `ExternalHorseAlias=12425`，其中日本 `netkeiba/ja=12421`；香港 HKJC 只有小样本 `en=2`、`zh-hant=2`。外部缓存表中日本仍是主体：`ExternalHorse=12405`、`ExternalRace=4099`、`ExternalRaceEntry=60838`、`ExternalRaceResult=56882`；香港仅有 sample commit 级别的 `ExternalHorse=2`、`ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`；英国、法国、美国当前生产 `External*` 表无写入。结论：多地区新闻源与语言/地区处理链路已上线，但正式术语内容和外部马名识别数据厚度仍明显以日本为主，英法美仍停在 proof/代码能力而非生产数据沉淀。

`2026-07-04` OpenSpec change `prepare-termbase-seed-data` 已完成实现、验证和归档，归档目录为 `openspec/changes/archive/2026-07-03-prepare-termbase-seed-data`，正式规格已同步到 `openspec/specs/termbase-seed-data-preparation/spec.md`，并在 `openspec/specs/termbase-and-race-priority/spec.md` 追加“术语种子候选兼容正式术语导入”要求。本地首版已实现 `prepare_termbase_seed_data` 管理命令与 `stable.services.termbase_seed` 服务层，可从 HKJC/WP Stud fixture 或低频触网入口生成 `seed_candidates.csv`、`seed_conflicts.csv` 和 `summary.json`；内置 fixture smoke 生成 `10` 条候选与 `1` 条冲突，香港候选优先、日本候选最后，中文目标译名经 OpenCC 简体化。该能力边界是从 HKJC 体系和 WP Stud 准备第一批人工审核 CSV：`seed_candidates.csv` 严格兼容现有 `import_terms` 字段，`seed_conflicts.csv` 记录译名冲突；第一版不直接写生产 `TermEntry`、不触发翻译、发布或 QQ 推送。审查后已明确首版不做 HKJC `racecards` PDF/排位表全量抽取，必须先做 HKJC/WP Stud source discovery，默认输出到 `runtime/termbase_seed/<timestamp>/`，并要求网络失败摘要、繁简转换依赖落地和后台术语导入模板同步更新。代码审查修复已将命令内置 dry-run 预检调整为与 `import_terms` 默认一致的 `upsert`，并确保触网达到 `max_requests` 后停止所有后续来源。`2026-07-06` 本地 review 返修进一步修复 `SeedNetworkClient` 的 GET/POST 重试计数：失败重试尝试也会立即写入 request 明细并计入 `--max-requests`，避免超出请求预算，原始 timeout 错误保留在 `summary.requests`；同时为 HKJC/QIDS 马匹候选引入 `source:type:id` 全局实体 key，避免英文同名马误合并，IRE/CAN 等未建模地区保持 `other`，候选证据合并时每条最多保留 `10` 个 evidence sample。上线前本地验证已通过：`TermbaseSeedDataPreparationTests` 6 项、`stable` 全量 354 项、fixture smoke、`openspec validate --all` 和 `git diff --check`；本次 review 返修后追加验证 `TermbaseSeedDataPreparationTests` 21 项、`manage.py check`、`openspec validate --all` 和 `git diff --check` 通过。返修提交 `4b6e840` 已部署生产，部署前备份 `.env.backup.harden-hkjc-termbase-20260706_043557` 与 `backups/db/pre-harden-hkjc-termbase-20260706_043557.sql.gz`（约 `71M`，`gzip -t` 通过）；部署后 `/healthz/`、`manage.py check`、`/`、`/races/`、`/admin/login/` 和公网 `umafans.run/healthz/` 均通过。生产 fixture smoke 输出 `candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`，QIDS 同英文名加拿大马 smoke 已确认不会误合并。本次未导入正式术语，生产计数保持 `TermEntry=15321`、`TermAlias=15537`。

`2026-07-04` 术语种子数据准备已部署生产。服务器 `/opt/umanewsbot` 从 `4323d32` 快进到 `e81733f`，部署前备份 `.env` 为 `.env.backup.termbase-seed-20260704_012005`；因新增 `opencc-python-reimplemented==0.1.7`，本次重建并重启 `web / worker / beat`。部署后迁移显示 `No migrations to apply`，`manage.py check` 通过，生产容器内 fixture smoke 输出 `candidate_count=10`、`conflict_count=1`、`incomplete=false`、`dry_run_error_count=0`，首条候选为 `BEAUTY GENERATION`，末条为 `ディープインパクト`；本地和公网 `/healthz/` 均返回 `200`。本次未导入正式术语，不修改 `TermEntry`、`TermAlias`、`TermCandidate` 或外部马名索引。

`2026-07-04` 已正式导入第一批人工认可格式的术语种子候选。导入文件为生产生成并回传审核的 `imports/termbase-seed-fixture-review-20260704_024950/seed_candidates.csv`；导入前数据库备份为 `backups/db/pre-termbase-seed-import-20260704_030722.sql.gz`，`gzip -t` 校验通过。`import_terms --dry-run` 显示总计 `10` 条、 新增 `8` 条、更新 `2` 条、错误 `0` 条；正式导入结果为新增 `8` 条、更新 `2` 条、跳过 `0` 条。生产正式术语从 `TermEntry=2054` 增至 `2062`，`TermAlias=2057` 增至 `2068`；新增英文术语 `8` 条，日文术语仍为 `2054` 条，其中 `グランアレグリア` 与 `ディープインパクト` 是既有日文术语更新。新增英文术语包括 `BEAUTY GENERATION -> 美丽传承`、`KA YING RISING -> 嘉应高升`、`ROMANTIC WARRIOR -> 浪漫勇士`、`Hong Kong Cup -> 香港杯`、`Zac Purton -> 潘顿`、`John Size -> 蔡约翰`、`Sha Tin -> 沙田马场`、`Declared Starter -> 宣布出赛马匹`。本批首次导入时地区证据只保留在 `notes`，随后已用模型合法地区值执行补写 upsert：备份 `backups/db/pre-termbase-seed-region-upsert-20260704_031950.sql.gz`，短码 `hk/jp` dry-run 因地区不合法被阻断且未写库，改用 `hong_kong/japan` 后 dry-run 为 `10` 条更新、`0` 错误，正式 upsert 为 `10` 条更新、`0` 跳过。补写后地区分布为 `en/hong_kong=8`、`ja/japan=2`、既有旧日文术语空地区 `2052`；公网 `/healthz/` 返回 `200`。

`2026-07-04` WP Stud 第一批全量审核候选已正式导入。已从可直接访问的 WP Stud 页面缓存并转换编码，输出 `runtime/termbase_seed/wpstud-full-review-20260704/seed_candidates.csv`、`seed_candidates_with_region.csv`、`seed_conflicts.csv` 与 `summary.json`；候选共 `210` 条，冲突 `0` 条，全部为 `term_type=horse`、`source_language=ja`、`source_tier=community`、`requires_review=true`，中文译名已转为简体。带地区版本统一设置 `racing_region=hong_kong`，用于描述香港或海外来港赛马候选；生产导入文件为 `/opt/umanewsbot/imports/wpstud-full-review-20260704/seed_candidates_with_region.csv`。本轮与 HKJC 500 条批次共用导入前备份 `backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，`gzip -t` 校验通过；WP Stud 生产 `import_terms --dry-run` 为总计 `210` 条、新增 `210` 条、更新 `0` 条、错误 `0` 条，正式导入为新增 `210`、更新 `0`、跳过 `0`。HKJC 真实页面此前可访问但通用解析器拿不到候选；本地已补 HKJC 专用抽取路径，从 `selecthorse` 发现字母页、从字母页拿 `horseid + 英文名`，再抓繁中马匹详情页对齐中文名，并新增 `--limit-horses` 控制小批马匹数。本轮进一步新增 `--hkjc-letter`，用于按 A-Z 字母拆批抓取，避免无 checkpoint 的全量请求长时间运行。

`2026-07-04` 已开始 HKJC 正式术语候选抓取第一批。为避免后续再手工补地区，生成器已将 `racing_region` 加入 `seed_candidates.csv` 表头，并把 HKJC 候选输出为模型合法值 `hong_kong`。本地低频命令 `--source hkjc --allow-network --limit-pages 1 --limit-horses 100 --max-requests 130 --request-interval-seconds 2 --timeout-seconds 25` 输出到 `runtime/termbase_seed/hkjc-formal-review-20260704_100horses/`，结果为候选 `100` 条、冲突 `0` 条、请求 `103` 次且全部 `200`、`incomplete=false`；全部候选为 `term_type=horse`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`，样例包括 `A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`。临时 SQLite 迁移库已对该 CSV 执行 `import_terms --dry-run`，结果为总计 `100` 条、新增 `100` 条、更新 `0` 条、错误 `0` 条；本批尚未导入生产正式术语库，也尚未部署 HKJC 抽取代码到生产。

`2026-07-04` HKJC 当前本地马官方译名已按 A-Z 字母拆批补齐并导入生产正式术语库。此前 `500` 匹审核包输出目录为 `runtime/termbase_seed/hkjc-formal-review-20260704_500horses/`，结果候选 `500` 条、冲突 `0`、请求 `509` 次全部 `200`、`incomplete=false`，并在生产 dry-run 后正式导入，导入前备份为 `backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`；该批正式导入新增 `500`、更新 `0`。随后发现无 checkpoint 全量命令运行过久，改为新增 `--hkjc-letter` 并按字母拆批：`I` 批候选 `28` 条，备份 `backups/db/pre-hkjc-letter-I-term-import-20260704_185212.sql.gz` 后导入新增 `28`；`J` 批候选 `23` 条，备份 `backups/db/pre-hkjc-letter-J-term-import-20260704_185400.sql.gz` 后导入新增 `23`；`K-Z` 合并候选 `701` 条，生产 dry-run 为新增 `699`、更新 `2`、错误 `0`，备份 `backups/db/pre-hkjc-letters-K-Z-term-import-20260704_191425.sql.gz` 后正式导入；`A-H` 复跑合并候选 `505` 条，生产 dry-run 为新增 `5`、更新 `500`、错误 `0`，备份 `backups/db/pre-hkjc-letters-A-H-term-import-20260704_192843.sql.gz` 后正式导入。导入后生产 `TermEntry=3527`、`TermAlias=3743`，`source_language=en/racing_region=hong_kong` 合计 `1263` 条，其中 HKJC 当前本地马英文术语 `1258` 条；`source_language=ja/racing_region=hong_kong` 的 WP Stud 社区马名术语 `210` 条。公网 `/healthz/` 返回 `200`。当前完成的是 HKJC 当前本地马名单补齐，不等同于“香港赛事/骑手回溯到 2024-01-01”；赛事和骑手仍需从 HKJC Race Card/赛果链路另行抽取。

`2026-07-04` 已继续 HKJC 本地赛果回溯术语导入，用于补齐香港赛果中的历史马名、骑师名和赛事名。生成器新增 `--hkjc-local-results-start-date`、`--hkjc-local-results-end-date`、`--hkjc-local-results-skip-races` 与 `--hkjc-skip-horse-details`，并对 HKJC 赛日首页只直接展示第 1 场、链接从第 2 场开始的结构做了补抓；抓取时会同时请求 `en-us` 与 `zh-hk` 赛果页，对齐输出 `horse / jockey / race` 候选，中文目标译名转为简体。已正式导入 `2024-01` 至 `2024-07`、`2024-09` 至 `2025-07`、`2025-09` 至 `2026-07-04`；`2024-08` 与 `2025-08` 已逐日扫描且候选 `0`、失败 `0`，无需导入。`2024-07` 输出 `647` 条候选（`horse=575`、`race=49`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202407-term-import-20260704_211425.sql.gz` 后导入新增 `74`、更新 `573`；`2024-09` 输出 `626` 条候选（`horse=549`、`race=54`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202409-term-import-20260704_213327.sql.gz` 后导入新增 `62`、更新 `564`；`2024-10` 输出 `834` 条候选（`horse=735`、`race=75`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-202410-term-import-20260704_214522.sql.gz` 后导入新增 `104`、更新 `730`；`2024-11` 输出 `850` 条候选（`horse=757`、`race=69`、`jockey=24`），`2024-11-13 HV Race 7-9` 为 HKJC 双语空壳赛果页，已记录为 `skipped_races/local_result_not_available` 且不导入空数据，备份 `backups/db/pre-hkjc-local-results-202411-term-import-20260704_221006.sql.gz` 后导入新增 `97`、更新 `753`；`2024-12` 输出 `957` 条候选（`horse=832`、`race=78`、`jockey=47`），备份 `backups/db/pre-hkjc-local-results-202412-term-import-20260704_222551.sql.gz` 后导入新增 `135`、更新 `822`；`2025-01` 输出 `913` 条候选（`horse=804`、`race=78`、`jockey=31`），备份 `backups/db/pre-hkjc-local-results-202501-term-import-20260704_224151.sql.gz` 后导入新增 `73`、更新 `840`；`2025-02` 输出 `794` 条候选（`horse=703`、`race=60`、`jockey=31`），备份 `backups/db/pre-hkjc-local-results-202502-term-import-20260704_225443.sql.gz` 后导入新增 `38`、更新 `756`；`2025-03` 输出 `914` 条候选（`horse=803`、`race=78`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202503-term-import-20260704_231134.sql.gz` 后导入新增 `30`、更新 `884`；`2025-04` 输出 `893` 条候选（`horse=782`、`race=78`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202504-term-import-20260704_232559.sql.gz` 后导入新增 `58`、更新 `835`；`2025-05` 输出 `920` 条候选（`horse=816`、`race=79`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202505-term-import-20260704_234206.sql.gz` 后导入新增 `38`、更新 `882`；`2025-06` 输出 `826` 条候选（`horse=741`、`race=63`、`jockey=22`），备份 `backups/db/pre-hkjc-local-results-202506-term-import-20260704_235659.sql.gz` 后导入新增 `44`、更新 `782`；`2025-07` 输出 `675` 条候选（`horse=603`、`race=49`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202507-term-import-20260705_000915.sql.gz` 后导入新增 `19`、更新 `656`；`2025-09` 输出 `632` 条候选（`horse=560`、`race=49`、`jockey=23`），`2025-09-21 ST Race 9-10` 为 HKJC 双语空壳赛果页，已记录为 `skipped_races/local_result_not_available` 且不导入空数据，备份 `backups/db/pre-hkjc-local-results-202509-term-import-20260705_002604.sql.gz` 后导入新增 `17`、更新 `615`；`2025-10` 输出 `882` 条候选（`horse=786`、`race=73`、`jockey=23`），备份 `backups/db/pre-hkjc-local-results-202510-term-import-20260705_004245.sql.gz` 后导入新增 `41`、更新 `841`；`2025-11` 输出 `933` 条候选（`horse=826`、`race=81`、`jockey=26`），备份 `backups/db/pre-hkjc-local-results-202511-term-import-20260705_010022.sql.gz` 后导入新增 `45`、更新 `888`；`2025-12` 输出 `912` 条候选（`horse=803`、`race=68`、`jockey=41`），备份 `backups/db/pre-hkjc-local-results-202512-term-import-20260705_011812.sql.gz` 后导入新增 `42`、更新 `870`；`2026-01` 输出 `978` 条候选（`horse=875`、`race=78`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202601-term-import-20260705_013522.sql.gz` 后导入新增 `28`、更新 `950`；`2026-02` 输出 `930` 条候选（`horse=836`、`race=69`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202602-term-import-20260705_015108.sql.gz` 后导入新增 `18`、更新 `912`；`2026-03` 输出 `944` 条候选（`horse=838`、`race=81`、`jockey=25`），备份 `backups/db/pre-hkjc-local-results-202603-term-import-20260705_020814.sql.gz` 后导入新增 `18`、更新 `926`；`2026-04` 输出 `975` 条候选（`horse=859`、`race=83`、`jockey=33`），备份 `backups/db/pre-hkjc-local-results-202604-term-import-20260705_022703.sql.gz` 后导入新增 `41`、更新 `934`；`2026-05` 输出 `979` 条候选（`horse=873`、`race=80`、`jockey=26`），备份 `backups/db/pre-hkjc-local-results-202605-term-import-20260705_024451.sql.gz` 后导入新增 `33`、更新 `946`；`2026-06` 输出 `844` 条候选（`horse=757`、`race=63`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-202606-term-import-20260705_025830.sql.gz` 后导入新增 `20`、更新 `824`；`2026-07-01` 至 `2026-07-04` 输出 `310` 条候选（`horse=265`、`race=21`、`jockey=24`），备份 `backups/db/pre-hkjc-local-results-20260701-20260704-term-import-20260705_030505.sql.gz` 后导入新增 `5`、更新 `305`。以上新增批次生产 dry-run 均为错误 `0`，正式导入均为跳过 `0`。导入后生产 `TermEntry=5948`、`TermAlias=6164`，`source_language=en/racing_region=hong_kong` 合计中 `horse=2479`、`jockey=70`、`race=1132`，另保留既有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`；`http://127.0.0.1/healthz/` 返回 `200`。当前 HKJC 香港本地赛果已回溯到 `2026-07-04`；仍需另行补 HKJC overseas 与 WP Stud 赛事/骑手缺口。

`2026-07-04` 已创建并完成 plan-eng-review 的 OpenSpec change `prepare-hkjc-overseas-termbase-seeds`，用于把 HKJC overseas simulcast Race Card 扩展为海外马名、骑师和赛事名的官方中文术语种子来源。该 change 已完成 `proposal.md`、`design.md`、`tasks.md` 与 `termbase-seed-data-preparation` delta spec，并通过 `openspec validate prepare-hkjc-overseas-termbase-seeds --strict`；当前本地已完成代码侧实现，新增 `prepare_termbase_seed_data --source hkjc_overseas`、`--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`、`--limit-meetings`、`--limit-races`，输出继续不写正式术语库、不写 `ExternalHorse`，并新增 `source_evidence.json` 记录 Race Card 参数、中英页面 URL、原始繁体、地区映射、horse profile 证据、跳过和失败原因。review 约束已落地：渲染 fallback 默认不引入生产浏览器硬依赖；若无可用渲染器或渲染后缓存，会记录 `render_fallback_unavailable` 并标记 `incomplete=true`。本地 fixture smoke 输出 `runtime/termbase_seed/hkjc-overseas-fixture-smoke-migrated/`，候选 `9` 条、冲突 `0`、`incomplete=false`、`dry_run_error_count=0`，并通过 `import_terms --dry-run`。后续 review 修复已明确术语种子冲突输出规则：同一实体如出现多个中文译名，`seed_candidates.csv` 只保留一个正式 `target_zh`，其他译名进入 `aliases_zh`，同时 `seed_conflicts.csv` 保留冲突证据。用户确认后已执行 HKJC overseas 低上限 live dry-run：命令使用 `--source hkjc_overseas --allow-network --limit-meetings 1 --limit-races 1 --max-requests 6 --request-interval-seconds 3 --timeout-seconds 15`，输出目录为 `runtime/termbase_seed/hkjc-overseas-live-smoke-20260704_174924/`；结果为候选 `0` 条、冲突 `0`、跳过 `0`、请求 `1` 次且入口页 `https://racing.hkjc.com/en-us/overseas/` 返回 `200`，但直接 HTML 未暴露 Race Card 链接，因此记录 `render_fallback_unavailable: no race card links in direct HTML`，`incomplete=true`，`dry_run_error_count=0`。这证明当前实现不会把 HKJC Next.js shell 误当作空数据成功；要批量取得海外 Race Card 正式候选，还需要后续补浏览器渲染缓存或解析 HKJC 前端 API。本能力尚未部署生产，live dry-run 也未写正式术语库。

`2026-07-05` HKJC overseas 术语批量回溯已通过本地 QIDS GraphQL 抽取和生产 `import_terms` 正式导入完成，覆盖 `2024-01-01` 至 `2026-07-04`。生成器新增 `--hkjc-overseas-start-date` 与 `--hkjc-overseas-end-date`，会从 HKJC overseas results 发现转播赛日，再通过 HKJC QIDS `raceMeetingProfile` 对齐海外 Race Card 的英文/繁中 `horse / jockey / race`；该本地代码尚未部署生产，但生成产物已用于生产导入。月度产物合并目录为 `runtime/termbase_seed/hkjc-overseas-qids-merged-20240101-20260704/`，原始行 `11633` 条、候选 `7691` 条、冲突 `3` 条，候选结构为 `horse=6481`、`jockey=847`、`race=363`。生产导入文件为 `/opt/umanewsbot/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`；导入前备份为 `backups/db/pre-hkjc-overseas-qids-term-import-20260705_040238.sql.gz` 并通过 `gzip -t`；生产 dry-run 为总计 `7691`、新增 `7688`、更新 `3`、错误 `0`，正式导入为新增 `7482`、更新 `209`、跳过 `0`。因当前正式术语 upsert 身份是 `term_type + source_language + source_ja`，不是按地区拆分，同名国际骑师会被后导入地区覆盖；已用 `runtime/termbase_seed/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv` 对 HKJC 本地赛果骑师做地区恢复，备份 `backups/db/pre-hkjc-local-jockey-region-restore-20260705_040950.sql.gz`，dry-run 和正式导入均为 `69` 条更新、`0` 错误/跳过。恢复后 HKJC 本地赛果覆盖仍为 `en/hong_kong horse=2479, jockey=69, race=1132`，海外 HKJC 官方来源计数为 `7483`。

`2026-07-05` WP Stud 当前发现的马名、赛事、骑师和马场社区术语已补齐到正式术语库，但不覆盖 HKJC 官方主译名。此前 WP Stud 马名批次已导入 `210` 条 `source_language=ja/racing_region=hong_kong` 社区马名；本次继续抓取 WP Stud `Translation/Race` 下 `21` 个赛事页面、`Translation/jockey.htm` 和 `Translation/racecourse/RaceCourse.htm`，输出目录为 `runtime/termbase_seed/wpstud-race-jockey-racecourse-review-20260705/`，完整候选 `2095` 条、冲突 `17` 条、`incomplete=false`，其中 `race=1392`、`jockey=276`、`racecourse=427`。生产完整 dry-run 显示会新增 `1891`、更新 `204`、错误 `0`；其中 `204` 条更新主要命中 HKJC overseas/HKJC 官方术语，因此已过滤为 `seed_candidates_new_only.csv` 仅导入新增项，并把 `seed_candidates_skipped_existing.csv` 留作人工审核清单。过滤后生产 dry-run 为总计 `1891`、新增 `1891`、更新 `0`、错误 `0`；备份 `backups/db/pre-wpstud-race-jockey-racecourse-term-import-20260705_072047.sql.gz` 通过 `gzip -t`；正式导入新增 `1891`、更新 `0`、跳过 `0`。导入后生产 `TermEntry=15321`、`TermAlias=15537`，`http://127.0.0.1/healthz/` 返回 `200`。本轮后 `source_language=en` 分布已包含香港、英国、法国、美国、日本和 other 的马名/赛事/骑师/马场，其中 HKJC 官方仍保持最高优先级，WP Stud 作为社区候选和佐证使用。

`2026-07-06/07` 已完成 HKJC / WP Stud 术语库清洗、WP Stud HorseList 全量马名补齐和生产正式导入。返修代码让 HKJC overseas 与美国详情来源中的马名去除尾部国别后缀，例如 `A Bit Of Spirit (IRE)` 清洗为 `A Bit Of Spirit`；带年份或替代名称的复合赛事名会拆成独立术语，例如 `International Stakes` 与 `Benson & Hedges Gold Cup Stakes`；WP Stud `HorseList.html` 已作为默认来源，解析日文马名、英文别名和简体中文译名。最终审核产物位于 `runtime/termbase_seed/final-reviewed-import-20260706/`，`seed_candidates_final.csv` 共 `11257` 行，输入覆盖 HKJC `7691`、WP Stud race/jockey/racecourse `1891` 和 WP Stud HorseList `1866`；清洗统计包括去除马名国别后缀 `6481` 次、拆分年份赛事标记 `59` 次、去重 `254` 行，并生成 HKJC 日本地区英文马名日文 alias `907` 行，其中马名 `883` 行已全部找到日文名。生产服务器 `/opt/umanewsbot` 导入时 `HEAD=b1ddb54`，导入前 `TermEntry=15321`、`TermAlias=15537`，备份 `backups/db/pre-final-termbase-review-20260706_234427.sql.gz` 约 `75M` 且 `gzip -t` 通过；正式脚本先清理既有脏 active 术语，再执行 `import_terms`，结果为新增 `1169`、更新 `10088`、错误/跳过 `0`。导入后生产 `TermEntry=16558`、`TermAlias=19293`、active `TermEntry=16428`，active 马名国别后缀术语 `0`、active 赛事年份标记术语 `0`，`ExternalDataImportRun(status="started")=0` 且导入锁为空，`manage.py check`、`127.0.0.1/healthz/` 与 Host `umafans.run` 健康检查均通过。抽检确认 `A Bit Of Spirit (IRE)` 已无 active 词条而 `A Bit Of Spirit -> 点燃斗志` 有效，`International Stakes -> 国际锦标` 与 `Benson & Hedges Gold Cup Stakes -> 宾臣暨赫捷仕金杯` 已拆分，`A Shin Resume / Dragon / Dynamic / Sophia` 等 HKJC 日本马英文词条已挂日文 alias。另有 `26` 个 HKJC 日本马日文 alias 因生产已有同日文 `TermAlias` 或日文主词而未直接挂到英文词条，其中大多数中文目标一致；`Raijin / ライジン` 和 `Scintillation / シンチレーション` 存在既有译名占用，导入脚本按“不强行合并冲突概念”跳过，保留 HKJC 英文主译名。

`2026-07-05` OpenSpec change `prepare-hkjc-overseas-termbase-seeds` 已完成正式规格同步并归档，归档目录为 `openspec/changes/archive/2026-07-05-prepare-hkjc-overseas-termbase-seeds/`。归档前已将 delta spec 合并到 `openspec/specs/termbase-seed-data-preparation/spec.md`：正式规格现在包含 `hkjc_overseas` 来源、Race Card 自动发现与精确参数、马名/骑师/赛事名候选、简体中文目标、官方来源元数据、结构化证据、地区映射以及包含 `racing_region` 的导入兼容表头。归档前 `openspec validate prepare-hkjc-overseas-termbase-seeds --strict && openspec validate --all` 通过，归档后 `openspec validate --all` 通过 `17` 项。
仓库已于 `2026-06-06` 加入 OpenSpec + Codex 协作支持，用于在较大功能、跨模块改动、架构调整和生产高风险变更前先对齐规格，再进入实现。

OpenSpec change `add-term-candidate-discovery` 已完成实现、自动化测试、本地隔离环境浏览器验收，并归档为 `2026-06-06-add-term-candidate-discovery`；正式能力规格已同步到 `openspec/specs/term-candidate-discovery/spec.md`。

`2026-06-30` OpenSpec change `operate-multiregion-news-production` 已完成实现、代码审查返修、生产部署和归档。新增多地区新闻生产只读审计命令 `audit_multiregion_news_production`、通用 enabled 新闻来源轮询任务 `crawl_enabled_news_sources_task`、地区/来源自动发布 allowlist 与地区上限策略、后台 `/admin/regions/` 地区生产概览、来源管理地区筛选、QQ 国际新闻地区标签、地区查询索引和运行手册。返修后，地区生产概览的自动发布、人工发布和公开数量按今日窗口统计，待翻译、翻译失败和待审核保留为当前积压；审计中的来源抓取状态改为按 `NewsSource.last_crawl_status` 当前来源状态聚合，不再累计历史 `CrawlJob` 次数；正式术语 `TermEntry` 增加可选适用地区，空值表示全局通用，术语列表/表单/API/CSV 导入和多地区审计均支持地区口径；自动发布批次在地区每日/每轮上限跳过大量国际候选时，会在主扫描未填满后执行有限的日本候选兜底扫描，避免拖慢符合既有策略的日本文章。生产服务器 `/opt/umanewsbot` 已从 `7b6e51b` 快进到 `62a0f9a` 并执行 `bash ./deploy_lowcost.sh`，部署前备份 `.env` 为 `.env.backup.multiregion-news-20260630_185150`；迁移 `stable.0014_multiregion_news_indexes` 与 `stable.0015_termentry_racing_region` 已应用，`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、首页和后台登录入口均通过。随后已按用户要求开启多地区新闻生产开关，备份 `.env` 为 `.env.backup.enable-all-multiregion-20260630_203647`；当前 `NEWS_SOURCE_POLL_ENABLED=true`、轮询间隔 `30` 分钟、每轮最多 `12` 个来源，覆盖 `japan / hong_kong / united_kingdom / france / united_states` 五个地区；非日本自动发布 allowlist 已开启 `hong_kong / united_kingdom / france / united_states` 四个地区和当前已启用的国际来源，并设置首日护栏上限 `hong_kong:5 / united_kingdom:5 / france:3 / united_states:3`。开关生效后手动执行通用轮询 smoke，已选中并派发 `12` 个 due 来源，固定调度的 netkeiba/JRA 被正确跳过；worker 并发为 `2`，当前先处理 Sponichi 两个任务，其余任务在队列中等待消化。正式 QQ 群仍需显式配置 `PushTarget.allowed_regions` 才接收国际新闻。外部赛马数据库 `External*` importer 不进入新闻常态调度，不自动生成公开新闻或 QQ 推送。归档目录为 `openspec/changes/archive/2026-06-30-operate-multiregion-news-production/`，正式规格已同步到 `openspec/specs/multiregion-news-production/spec.md` 及相关能力规格。

`2026-07-02` OpenSpec change `increase-multiregion-news-volume` 已整体上线到生产。生产 `/opt/umanewsbot` 当前运行 `9e97e8c`，与 `origin/main` 一致；部署前数据库备份为 `backups/db/pre-multiregion-volume-20260702_040811.sql.gz`，`.env` 备份为 `.env.backup.multiregion-volume-20260702_040811`，启用前另备份 `.env.backup.enable-multiregion-volume-20260702_041242`。迁移 `stable.0017_majorraceevent_productionwindow_quotaledger_and_more` 与 `stable.0018_alter_notificationlog_type` 已应用，`web / worker / beat` 运行健康，本地和公网 `/healthz/` 均返回 `200`。本次上线开启 `MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true`、抓取/发布/QQ 三条窗口开关均为 `true`，覆盖 `japan / hong_kong / united_kingdom / france / united_states`；当前 16 个启用新闻源已标记 `production_approved=true`，日常抓取默认 15 分钟，重要赛事窗口默认 5 分钟。上线过程中发现并修复抓取窗口把 Celery `AsyncResult` 写入 JSON payload 导致窗口失败的问题，修复提交为 `9e97e8c`，窗口现在保存 `dispatch_result.task_id`。生产 smoke：20:15 抓取窗口派发 15 个 due 来源，最终 14 个成功、1 个 `Sponichi 新闻ランキング` 因上游 `502 Bad Gateway` 失败且写入明确原因；20:15 发布窗口香港自动发布 1 篇、美国自动发布 3 篇，20:30 发布窗口美国继续发布 1 篇，其他地区为 `no_ready_candidates`；20:15 QQ 窗口美国发送 2 条 delivery，20:30 QQ 窗口美国为 `already_sent`，其他地区为 `no_eligible_articles`。公开首页和地区页浏览器验收通过，首页可见 20:15 窗口新发布的香港/美国文章。ops 摘要通知已配置到 `UmaFans测试群(1026525240)`，`production_summary_task` 已产生 `NotificationLog #13051`，状态 `sent`。因当前为后半夜新闻低峰，用户确认跳过实际 4 个自然窗口等待，改为次日继续观察来源失败、候选质量、0 原因和 QQ 限流情况。

`2026-07-01` 已将 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send` 全部归档，正式规格同步到 `openspec/specs/external-horse-data-import/`、`openspec/specs/international-racing-coverage/` 及相关能力规格；`openspec list` 为空，`openspec validate --all` 12 项通过。本次同时补齐 `ExternalDataSource` 对 `sporting_life / france_galop / geny_france / horse_racing_nation` 的 choices 和迁移 `stable.0016`，避免英法美外部数据导入 source 值与模型枚举不一致。生产服务器 `/opt/umanewsbot` 已从 `538a1a9` 快进到 `8c83708` 并执行 `bash ./deploy_lowcost.sh`，部署前数据库备份为 `backups/db/pre-archive-all-20260701_153301.sql.gz` 且 `gzip -t` 通过；部署后 `web / worker / beat` 已重建，迁移 `stable.0016_alter_externaldataimporterror_source_and_more` 已应用，`manage.py check`、本地和公网 `/healthz/`、首页、后台登录入口和 `/admin/regions/` 均通过。浏览器验收确认首页地区 tab 正常，香港/英国地区页可渲染已发布国际新闻，地区生产页可显示五地区来源与 QQ 状态。生产开关仍为 `NEWS_SOURCE_POLL_ENABLED=true`、轮询间隔 `30` 分钟、每轮最多 `12` 个来源、覆盖五地区，`QQ_PUSH_ENABLED=true` 且 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。来源状态复核显示五地区 enabled 来源多数最近抓取为 `success`；当前仅 `Sponichi 新闻ランキング` 因上游 `502 Bad Gateway` 处于失败状态，属于来源站响应异常，不影响本次部署成立。

`2026-06-07` 已将术语候选发现部署到生产：服务器从 `7123e4e` 拉到 `e2e3e07`，应用迁移 `0006` 新建候选与证据表，`.env` 补入术语发现开关并保持 `TERM_DISCOVERY_ENABLED=false`（灰度，先关后开）。本次部署同时核实线上 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 仍在生效。

仓库已明确长期语言约定：Codex 新增或维护的协作文档、OpenSpec 产物与代理说明默认使用中文；仅保留必要的代码标识符、命令和工具机器语法。

`2026-06-19` 已创建公开首页资讯流升级主 OpenSpec change：`upgrade-public-home-info-feed`。该 change 作为后续前台 Web + 移动 H5 首页子任务的指导规范，目标是把当前 MVP 公开首页从“大说明 + 大卡片网格”升级为成熟资讯流：移动端轻头条 + 高密度新闻列表，桌面端门户式主内容 + 侧栏。`2026-06-21` 已完成 plan-eng-review 与 `/opsx:apply` 本地实现；实施过程按严格 TDD 执行发布过滤、头条选择、普通流去重、热门代理、公开静态资源和详情页结构测试，并已通过本地 Django 测试、OpenSpec 校验和桌面/移动浏览器验收。`2026-06-22` 已将 delta spec 同步为正式规格 `openspec/specs/public-home-info-feed/spec.md`，并归档为 `openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`；同日 PR #1 已合并并部署到生产，服务器运行 `e834f58`，公开首页已切换到 `stable/public.css` 和新资讯流模板。`2026-06-23` PR #2 已合并并部署生产，服务器运行 `04e2ee9`，移动 H5 首屏密度 follow-up 已上线。

`2026-06-24` 已完成自动发布门禁优化 OpenSpec change：`refine-automation-publish-gates` 的实现、PR 合并与生产上线。代码已将自动发布门禁拆为 `blocker / warning / info`：`blocker` 阻断自动发布，`warning` 初期不阻断但记录并对高价值文章邮件告警，`info` 仅用于诊断；同时支持基准翻译稿自动发布、高价值来源评分放行、非马名普通词过滤、关键术语分层校验和重复内容拦截。生产服务器当前运行 PR #4 squash merge 后的提交 `42a4622`，迁移 `stable.0009_automation_publish_gates` 已应用。

`2026-06-25` 已将本轮三个运营改造 change 合并到 `main` 并部署生产：抓取新鲜度与来源健康、后台原文选区快速加入术语库、新增术语后一次性应用到当前稿。服务器 `/opt/umanewsbot` 已从 `268100d` 更新到 `7f54f13`，`web / worker / beat` 已重建，`manage.py check`、`/healthz/` 和首页 HTTP 验证通过。相关 OpenSpec change 已归档并同步正式规格；其中抓取返修的 `fix-crawl-health-running-and-schedule-stagger` 是 change1 的后续规格，随 change1 一并归档。

`2026-06-25` 已将榜单重点新闻 QQ 推送与公开文章 ID URL 改造通过 PR #8 合并并部署生产。服务器 `/opt/umanewsbot` 已更新到 `00e4bd4`，部署前 `.env` 备份为 `.env.backup.qq-ranked-idurl-20260625_191826`；生产 `.env` 已切换为 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。`web / worker / beat` 已重建，`manage.py check`、`http://umafans.run/healthz/`、`http://umafans.run/`、`/news/<article_id>/` 公开详情和旧 slug 到 ID URL 的 `302` 跳转均已验证通过。本次不补推历史公开新闻，后续只等待自然榜单新闻触发测试群推送。

`2026-06-26` 已将国际赛马资讯扩展 OpenSpec change：`expand-international-racing-coverage` 合并到 `main` 并部署生产，服务器 `/opt/umanewsbot` 已从 `2f0c35c` 更新到 `5865e58`，部署前 `.env` 备份为 `.env.backup.international-coverage-20260626_103923`。本次部署应用迁移 `stable.0011`、`0012`、`0013`，`web / worker / beat` 已重建，`manage.py check`、`http://127.0.0.1/healthz/` 和首页 HTTP 验证通过。部署前发现生产 netkeiba 外部马名导入脚本仍在连续运行，已等待当前批次完成并释放 `ExternalDataImportLock` 后再部署；外层脚本 `/opt/umanewsbot/imports/run_horse_import_202504_to_202406_20260626_083946.sh` 已停止，最近两批 `1958 / 1959` 均停在 `paused`，避免部署与导入写库重叠。国际来源已同步并灰度启用第一版清单：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing latest/access`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation latest/access`；生产探测中 `BHA official` 返回 `403`，已暂时停用，`At The Races`、`Paulick Report` 和 `BloodHorse` 仍保留为候选但不启用。测试 QQ 群 `1026525240` 已配置允许 `japan / hong_kong / united_kingdom / france / united_states` 五个地区。首轮手动触发 12 个新增来源抓取任务后，`Sponichi latest` 已完成并入库 `13` 篇新稿、`7` 篇重复稿，`Sponichi access` 与 `HKJC Racing News` 已开始执行，其他国际来源仍在 worker 队列中等待；后续重点观察 `CrawlJob`、翻译结果、自动发布门禁和 QQ 群推送。

`2026-06-26` 已创建新的本地 Codex 工作树 `/Users/mentianlu/.codex/worktrees/openspec-ready-20260626/umanews`，基线为 `origin/main` 的 `4d09d25`。该工作树已带入 `.codex/skills/openspec-*`、`.codex/skills/plan-eng-review`、`.codex/skills/tdd`、`.codex/skills/workflow-spine` 和 `.agents/skills` 镜像，并补齐 `gate-templates.md` 引用副本；已通过 `openspec list`、`openspec validate --all`、`openspec validate expand-international-racing-coverage --strict`、`openspec validate add-netkeiba-horse-data-import --strict`、`openspec status --change expand-international-racing-coverage --json` 和 skill 文件一致性检查。该记录仅描述本地协作工作树准备状态，不代表新的产品或生产部署变更。

`2026-06-26` 已新增并完成计划审查 OpenSpec change `start-hkjc-data-import-and-global-spikes`，用于启动香港 HKJC 外部赛马数据受控导入，并为英国 `Sporting Life + BHA`、美国 `Equibase`、法国 `France Galop` 产出结构化数据库 spike。该 change 明确不续跑日本 netkeiba 外部数据导入，日本导入由其他线程继续；本轮也不实现前台比赛页、赛果页或马匹页。已创建 `proposal.md`、`design.md`、`specs/global-racing-data-import-readiness/spec.md` 和 `tasks.md`，并通过 `/plan-eng-review`；审查后补齐 HKJC 生产 commit 前的隔离库验证、数据库备份、用户显式确认、`HKJC_IMPORT_*` 环境配置入口，以及英法美 spike 前后正式表计数保持不变的验收要求。当前 `.openspec.yaml` 为 `phase: reviewed`，已通过 `openspec validate start-hkjc-data-import-and-global-spikes --strict`、`openspec validate --all` 和 `git diff --check`。随后按 TDD 红灯阶段新增 `openspec/changes/start-hkjc-data-import-and-global-spikes/test_cases.md` 和自动化测试；本轮实现已将 4 个红灯转绿：补齐 `HKJC_IMPORT_*` settings 和 `.env.example`，新增 HKJC `--allow-network` dry-run 请求边界输出，新增英法美只读 spike runner 和正式表 before/after 计数检查。HKJC 最小样本 fixture 已保存到 `server/stable/fixtures/hkjc/`，本地隔离 SQLite `/tmp/umanews-hkjc-apply.sqlite3` 已完成赛日、单场、单马 dry-run/commit，结果写入 `docs/hkjc_data_import_samples.md`；隔离库最终统计为 3 个 import run、1 场比赛、2 个 entries、2 条 results、2 匹马、4 条别名。英法美 read-only spike 已执行 6 次公开页面 GET，请求证据、字段覆盖矩阵和准入判断已写入 `docs/global_racing_data_source_spikes.md`；三地当前均为 `needs_more_spike`，且正式表 before/after 计数保持不变。验证通过：`manage.py check`、HKJC/spike 目标测试 12 项、完整 `stable` 测试 246 项。

`2026-06-26` 已将 `start-hkjc-data-import-and-global-spikes` 实现提交 `b0361cf` 推送到 `main` 并部署生产。服务器 `/opt/umanewsbot` 已从 `4d09d25` 快进到 `b0361cf`，部署前 `.env` 备份为 `.env.backup.hkjc-global-spikes-20260626_164045`。部署前确认生产无运行中 `ExternalDataImportLock`，无 `ExternalDataImportRun(status="started")`；`bash ./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建，`web` healthy。生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`；HKJC 样本命令以 dry-run 方式读取容器内 `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`，返回 `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}` 且 `would_write_formal_tables=false`。部署当时未执行 HKJC commit，也未启用英法美正式导入。

`2026-06-26` 已归档 `start-hkjc-data-import-and-global-spikes`，归档目录为 `openspec/changes/archive/2026-06-26-start-hkjc-data-import-and-global-spikes/`；delta spec 已同步为正式规格 `openspec/specs/global-racing-data-import-readiness/spec.md`。归档后 `openspec validate --all` 通过，`global-racing-data-import-readiness` 正式规格包含 6 个 requirement。归档提交 `db0f3cc` 已推送到 `main` 并在生产 `/opt/umanewsbot` 快进；该提交只移动 OpenSpec/文档，不重建容器，生产服务代码仍为已部署验证过的 `b0361cf` 镜像内容，线上 `/healthz/` 和首页保持 `200`。

`2026-06-26` 已按用户确认启动 HKJC 生产样本导入，但范围仅限仓库 fixture `stable/fixtures/hkjc/2026-06-21-race-date-sample.json`，不是 HKJC 真实网络持续抓取。执行前已在生产服务器创建数据库备份 `backups/db/pre-hkjc-sample-20260626_180646.sql.gz` 并通过 `gzip -t` 校验；预检查显示无运行中 HKJC 导入、无 started run，`web` healthy。生产 dry-run 再次返回 `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}` 且不写正式表；随后执行 `--commit` 成功，`run_id=1960`、`success_count=7`、`failure_count=0`、`skipped_count=0`。提交后生产 HKJC 外部表统计为 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`，马名索引 `STELLAR EXPRESS` 命中 `HKH_STELLAR_EXPRESS`；`ExternalDataImportLock` 仅保留未占用的来源占位记录，未发现仍在运行的 HKJC 导入进程，`http://umafans.run/healthz/` 返回 `200`。真实 HKJC 网络入口仍未确认，不能把这次样本导入理解为已开启自动抓取。

`2026-06-26` 已新建 OpenSpec change `connect-real-global-racing-databases`，目标是按 `香港 -> 英国 -> 法国 -> 美国` 顺序接入真实赛马数据库，抓取每个地区最近 2 个月赛事和涉及马匹详情后停止，不创建公开比赛页或持续调度。香港阶段已定位 HKJC 官方真实 HTML 入口：赛日列表 `localresults`、单场结果 `localresults?racedate=YYYY/MM/DD&Racecourse=HV|ST&RaceNo=N`、马匹详情 `horse?horseid=...`。本地 TDD 已新增 HKJC HTML parser、race link 聚合、recent-days/date-range、马匹详情补抓、限速、请求上限和 `completion` 完成度测试，`HKJCExternalDataImportTests` 21 项通过；真实 HKJC 单场 dry-run `HK20260624HV01` 请求 1 次官方页面并解析 `1` 场、`12` entries、`12` results、`12` unique horses，未写库。随后在隔离 SQLite `/tmp/umanews-hkjc-real-single.sqlite3` 执行同一真实单场 `--commit --allow-network`，成功写入 `ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorseAlias=12`，`run_id=1`、`success_count=25`、`failure_count=0`。同日又完成 HKJC `--recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1` 真实小范围链路：dry-run 请求赛日列表、赛日页、单场结果和马匹详情共 `4` 次，解析 `1` 场、`12` entries、`12` results、`12` unique horses，并返回 `completion.is_complete=false`、`stop_reason=limit_horses_reached`、`meetings_found=28`，明确这是样本而非全量；隔离 SQLite `/tmp/umanews-hkjc-real-range.sqlite3` commit 后写入 `ExternalRace=1`、`ExternalRaceEntry=12`、`ExternalRaceResult=12`、`ExternalHorse=1`、`ExternalHorseAlias=12`，重复执行后正式对象计数不增长。当前仍未部署生产，也未执行生产最近两个月全量 dry-run/commit；下一步需要生产部署前锁检查、备份、用户确认后再低频运行 HKJC 最近两个月范围。

`2026-06-26` 已为 `connect-real-global-racing-databases` 追加英法美只读 spike 复核，共执行 `18` 次公开页面 GET，不写任何 `External*` 表。英国 `Sporting Life` racecards、fast-results 和 horse profile 均返回 `200`，fast-results 暴露具体 racecard 与 horse profile 链接；`BHA` horses/fixtures 返回 `200`，暴露 horses feed、search 和 fixtures/racecards 相关入口，因此英国当前优先级最高，建议后续以 Sporting Life 为正式导入主候选、BHA 为官方补字段候选。美国 `Equibase` entries、chart/PDF index 和具体 horse profile 均返回 `200`，但 chart/PDF 解析成本和访问限制仍需 fixture spike。法国 `France Galop` 官方页面和 app 说明页返回 `200` 并有 race card/results/calendar 浅层信号，但尚未定位稳定结构化查询参数，仍为 `needs_more_spike`。证据已写入 `docs/global_racing_data_source_spikes.md`。

`2026-06-26` 已为 HKJC 增加 `--plan-only`、`--skip-races` 和 `--race-ids` 批次能力，并用真实页面完成本地 plan-only 预检：最近 60 天 HKJC 下拉目标日期页 `28` 个，过滤 overseas simulcast 的 `S*` racecourse 后，本地香港 `HV/ST` 比赛为 `144` 场；按 `limit-races=20` 可拆为 `8` 批。`--skip-races 20 --limit-races 1 --limit-horses 0` 真实 smoke 成功从第 21 场 `HK20260613ST04` 开始，证明日期范围后续批次不会重复第一批；随后 `--race-ids HK20260624HV02,HK20260613ST04 --limit-horses 1` 真实 smoke 只请求 `race/race/horse` 3 个页面，解析 `2` 场、`26` entries、`26` results 和 `26` 匹唯一马，证明可按 plan-only 输出的 race_id 清单执行精确批次。本能力只用于生产全量前规划和拆批；尚未执行生产最近 2 个月全量 dry-run 或 commit。

`2026-06-26` 已将 `connect-real-global-racing-databases` 当前 HKJC 真实网络实现部署到生产，部署前数据库备份为 `backups/db/pre-hkjc-real-network-20260626_202442.sql.gz` 并通过 `gzip -t` 校验。生产 `65d41eb` 部署后 `manage.py check`、本地和公网 `/healthz/`、HKJC 精确 race-id 小样本 dry-run 均通过；生产 plan-only 仍显示最近 60 天本地香港 `HV/ST` 比赛 `144` 场、拆为 `8` 批。随后第 1 批 full dry-run 在马匹 profile 补抓阶段遇到 HKJC `ReadTimeout` / TLS handshake timeout 中断；该次未使用 `--commit`，未写正式表，中断后生产 HKJC 锁为空、`started_runs=0`、HKJC 表计数仍为上次 fixture 样本 `ExternalRace=1`、`ExternalRaceEntry=2`、`ExternalRaceResult=2`、`ExternalHorse=2`、`ExternalHorseAlias=4`。已按 TDD 追加 transient timeout retry 并部署到生产 `04c0444`，单请求最多 `3` 次并记录失败尝试；目前已将前 6 个 plan-only 批次拆成 24 个 5 场小批次完成 full dry-run，累计覆盖 `120` 场、`1522` entries、`1522` results、`1522` 个 horse profile 请求，所有小批次均 `completion.is_complete=true`，未写正式表。3c 首次执行时遇到一次执行容器 `137` 中断，输出文件为 `0` 字节；复查服务、锁和表计数均安全，随后改用一次性 `docker compose run --rm --no-deps web ...` 容器重跑 3c/3d 并完成；5a 出现 `2` 次 transient retry 记录但最终完成。当前停在生产 commit 前确认点，并可继续第 7 批 dry-run。

`2026-06-27` 全球赛马数据库目标已调整并完成“能力真实可用”确认：香港 HKJC 已有生产真实 dry-run 批次证据，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 已完成少量真实 proof，证明四地公开入口、parser/importer、马匹详情链路、低频限量抓取和 proof-only 离线审计可用。本次上线包从 `origin/main` 干净基线单独整理，只包含全球赛马数据库 importer、fixtures、审计工具、批次命令渲染器、OpenSpec 规格/归档、proof 证据和相关文档；刻意排除当前本地大工作树中的 QQ 推送、前台信息流、compose 端口等旁支差异。本目标不再要求本轮完成最近 60 天完整大量爬取或生产 `--commit`；后续完整爬取需另按 `docs/global_racing_next_run_checklist.md` 与 `docs/global_racing_full_crawl_runbook.md` 新开执行窗口。代码提交 `93b7007` 已推送并部署到生产；部署后 `manage.py check` 通过，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`，UK / France / US 导入命令与 batch 渲染命令可用，proof-only 审计通过，`ExternalDataImportRun(status="started")=0` 且 HKJC/netkeiba 锁为空。

`2026-06-30` 已按用户要求开始尝试香港 HKJC 慢速真实 dry-run，但仍未执行生产 `--commit`，也未写正式表。生产服务器 `/opt/umanewsbot` 当前代码为 `7b6e51b`；执行前确认 `docker compose -f docker-compose.prod.lowcost.yml ps` 中 `web/db/redis` healthy、`worker/beat/nginx` 运行，`ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`。最新 `--recent-days 60 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 160 --allow-network` 输出为 `runtime/global_racing_import/hkjc-20260630/hkjc-plan-20260630.json`，显示 `meetings=29`、`races=146`、`estimated_requests_without_horses=176`，拆为 `8` 批；该结果已不同于历史 `144` 场，因此不能把旧的 `120/144` 停点直接当作有效续跑点。随后以 `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`、`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=100` 执行精确 `race_ids=HK20260627ST02,HK20260627ST03` 小批 dry-run，输出 `runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json`：`dry_run=true`、`would_write_formal_tables=false`、`coverage_stats={"races":2,"entries":28,"results":28,"horses":28}`、`completion.is_complete=true`、`stop_reason=complete`、`horse_profiles_fetched=28`、`requests_len=30` 且全部 `status_code=200`。执行后复查 `ExternalDataImportRun(status="started")=0`、HKJC/netkeiba 锁为空，无 `umanewsbot-web-run-*` 临时容器残留，`http://umafans.run/healthz/` 和 `http://127.0.0.1/healthz/` 均返回 `200`。下一步如果继续香港，应按最新 `146` 场 plan 重新切批，从第 1 批剩余 race_ids 或重新渲染批次命令继续，而不是沿用旧 `skip-races=120`。

`2026-06-30` 用户要求继续香港 HKJC 慢速抓取到 `2024-07`。当前仍按 dry-run 执行，不写正式表、不加 `--commit`。生产已运行 `--start-date 2024-07-01 --end-date 2026-06-30 --plan-only --limit-races 20 --max-requests 600 --allow-network`，输出 `runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json`：计划共 `1496` 场、`75` 个 20 场批次，请求日志 `254` 条，其中 `253` 条 HTTP `200`；最后一个 plan 批次覆盖 `2024-09-11` 与 `2024-09-08`，说明 `2024-07-01` 至 `2024-09` 之间没有更早的 HKJC 本地 `HV/ST` 赛日进入该计划。此前已在生产 `runtime/global_racing_import/hkjc-20260701-to-202407/run_hkjc_slow_dryrun_to_202407.sh` 启动后台慢速 dry-run worker，按每 `5` 场一个 mini-batch、`HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`、`HKJC_IMPORT_MAX_REQUESTS_PER_RUN=140`、批次间暂停 `60` 秒执行；`races=3-7/1496` 与 `races=8-12/1496` 已通过校验。为部署 `operate-multiregion-news-production`，已按运行手册先暂停该 dry-run worker 和临时 `umanewsbot-web-run-*` 容器，状态文件 `hkjc-slow-dryrun.state=92`；暂停后 `ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`，未写正式表。后续若继续该长窗口 dry-run，应从 `hkjc-slow-dryrun.state=92` 对应进度恢复或重新渲染剩余批次，避免与生产部署、重建容器或 `git pull` 重叠。

## 已完成内容

- 域名购买与解析
- 正式域名 `umafans.run` / `www.umafans.run` 接入
- 本轮线上问题已修复，正式域名已可访问
- 公网服务器上 `Django + PostgreSQL + Celery + Redis + Docker Compose + Nginx` 主链路已运行
- 基础抓取、翻译、后台、前台链路已具备可继续迭代的基础
- 自动化运营 MVP 代码侧已完成：
  - 翻译成功后可进入自动评分分流
  - 支持 `auto / manual / ignored` 三类分流
  - 支持基准翻译稿与 AI 改写稿双层保存
  - 支持一致性校验、批量自动发布、自动化日志与通知日志
  - 后台候选池、详情页、编辑台、日志页已展示自动化状态与决策留痕
  - 前台展示优先级已调整为人工稿优先，其次改写稿，最后基准翻译稿
- OpenSpec + Codex 工作流已完成仓库级配置：
  - `openspec/config.yaml` 记录真实项目上下文、验证命令和任务域路由
  - `.codex/skills/openspec-*` 提供提案、实现、同步与归档技能
  - `.codex/skills/plan-eng-review` 提供实现前工程计划审查入口；`tdd` 与 `workflow-spine` 作为其配套审查约束与流程参考
  - `.codex/agents/` 提供 `application / integration / operations` 领域代理与只读安全审查代理
  - `AGENTS.md` 已补充规格驱动开发与子代理使用约定
- 专有术语候选发现与待标注池已完成：
  - 支持马名、比赛名、骑手名和马主名发现
  - 支持候选去重、证据聚合、工作人员审核和安全写入正式术语
  - 已完成 69 项测试与本地浏览器功能验收
  - 生产默认关闭，等待灰度启用

## 当前进行中的 OpenSpec change

- `start-hkjc-data-import-and-global-spikes`：已完成实现、生产部署、验证和归档；生产服务镜像来自 `b0361cf`。已在生产执行一次 HKJC fixture 样本 commit（`run_id=1960`），但未启用 HKJC 真实网络持续抓取，也未启用英法美正式导入。
- `connect-real-global-racing-databases`：本轮已按用户调整后的“能力真实可用”口径完成并归档；香港 HKJC 生产真实 dry-run 证据成立，英国 Sporting Life、法国 Geny、美国 Horse Racing Nation 少量真实 proof 成立，四地 importer、低频限量抓取、proof-only 审计和后续完整抓取门禁已可用。最近 60 天完整大量爬取和任何生产 `--commit` 不属于本轮完成口径，后续需要新执行窗口。

## 本轮问题简述

本轮线上问题并不是单一故障，而是多层运行态与仓库预期不一致叠加导致：

- 早期曾出现 DNS 解析未生效或本地查询返回 `NXDOMAIN`
- 服务器曾运行旧版 `nginx` 配置，仍保留 `80 -> 443` 跳转逻辑
- 服务器 `.env` 曾保留旧版 IP + HTTPS 强制配置
- 服务器运行中的 commit 一度与仓库当前预期不一致
- 最终通过对齐服务器代码版本、运行态配置、域名配置，完成正式域名 HTTP 接入修复

## 当前线上状态

- 线上域名已通
- 正式域名 `umafans.run` / `www.umafans.run` 可访问
- 自动化运营 MVP 已上线
- 公开首页资讯流升级已上线生产：`/` 使用公开站点专用 `public.css`、头条、普通新闻流和原站热度模块；移动 H5 已展示头条 + 高密度左文右图列表；移动端首屏密度 follow-up 已上线，390px 视口首屏可见 4 条普通新闻卡
- 自动化能力通过 `.env` 中 `AUTOMATION_ENABLED` 控制，当前已进入灰度运行与质量观察阶段
- 已核实线上 `AUTOMATION_ENABLED=true`、`AUTO_REWRITE_ENABLED=false`、`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`、`AUTOMATION_WARNING_EMAIL_ENABLED=true`，当前按“基准翻译稿自动发布 + 高价值 warning 邮件告警”灰度运行
- 术语候选发现代码已部署到生产（`e2e3e07`，迁移 `0006` 已应用），`TERM_DISCOVERY_ENABLED=false` 默认关闭，等待单篇抽检后灰度开启
- `2026-06-24` 已完成 QQ Bot / OneBot 生产运行态配置：独立 NapCat 容器 `umanewsbot-onebot-1` 已启动，OneBot HTTP 仅绑定服务器 `127.0.0.1:3000` 并通过 Docker 网络别名 `onebot` 给应用访问，测试群 `1026525240` 已写入 `PushTarget`，OneBot 直连与 Django `BotPusher` 均已成功发送测试消息。
- `2026-06-25` 生产服务器运行 `7f54f13`：netkeiba 新着顺 / 访问量榜 / 注目数榜调度已加载为每小时 `00/16/26` 分，后台已具备来源健康摘要；候选详情页和文章编辑台已具备原文选区快速加入术语库，以及新增术语后 15 秒一次性浮层“应用到当前稿”。

## 下一步优先级

1. 继续观察公开首页资讯流生产运行，重点确认 `/`、`/news/<article_id>/`、旧非纯数字 `/news/<slug>/` 跳转、图片、`public.css`、移动 H5 首屏密度和自动发布内容长期表现
2. 生产迁移已于 `2026-06-07` 完成；下一步在生产做单篇手动重新发现并抽检术语候选质量，确认后灰度启用 `TERM_DISCOVERY_ENABLED`
3. 观察自动化发布质量与 `AutomationLog`
4. 补充翻译 warning 可视化和术语库补全流程
5. 继续观察 QQ Bot 测试群灰度推送，必要时通过 `QQ_PUSH_ENABLED=false` 暂停自动发送
6. 继续观察 netkeiba `00/16/26` 分错峰抓取在连续小时内生成 `CrawlJob`，并抽检后台来源健康摘要
7. 对 `expand-international-racing-coverage` 做一次上线前整体 review；后续进入 PR / 部署前，需要重点确认迁移窗口、国际新闻源灰度启用顺序、HKJC payload 小样本和生产外部导入锁状态
8. HTTPS / 证书接入
9. 部署稳定化与监控 / 备份 / 回滚完善
10. 继续低批量观察 `refine-automation-publish-gates` 上线后的 warning 邮件、重复内容阻断、候选池门禁展示和自动发布结果

## 2026-06-25 榜单重点新闻 QQ 推送规划

- 已形成协调总纲：`docs/ranked_news_push_plan.md`。该文档只作为本轮计划说明，不作为 OpenSpec 长期能力规格。
- 本轮拆为三个 OpenSpec 子 change：`elevate-ranked-netkeiba-sources`、`push-ranked-news-to-qq`、`use-article-id-public-urls`。
- 推送策略方向：`QQ_PUSH_SCOPE` 继续表示“全推 / 重点推”，重点推送的判定方式由后续配置承载；本期统一实现 `ranked` 榜单策略，即只推 `netkeiba:access` 与 `netkeiba:attention` 新闻。
- QQ 推送 blocker 判断必须复用现有 `NewsArticle.gate_blockers` / `gate_issues.severity=blocker` 结构化门禁结果，不在 QQ 服务里重新实现一套发布门禁。
- 归档状态：`add-qqbot-auto-push` 已先归档为正式 `qqbot-auto-push` 规格，随后本轮三个子 change 已归档到 `openspec/changes/archive/2026-06-25-*` 并同步正式规格。后续仍建议维护者定期清理其他已完成的 active change。
- `elevate-ranked-netkeiba-sources` 已完成并部署生产：`upsert_article_from_draft()` 会将同一 netkeiba 文章从 `latest` 提升为首次命中的 `access` 或 `attention`，二者之间不互相覆盖，`latest` 也不会覆盖榜单来源；每次命中仍创建 `NewsSnapshot`。入库结果新增 `source_elevated` 稳定信号，且仍兼容旧的 `article, created = ...` 解包方式。
- `push-ranked-news-to-qq` 已完成并部署生产：新增 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`high_value_only` 下只推 `netkeiba:access` / `netkeiba:attention` 且无 blocker 的公开文章；已公开文章被榜单来源提升时会触发 QQ 自动推送编排，并继续依靠 `QQPushDelivery(article, target)` 唯一约束去重。QQ delivery 真正发送前也会复检推送资格，若文章后来出现 blocker 或不再符合范围，会标记为 `skipped/not_eligible`，不会继续发群消息。
- `use-article-id-public-urls` 已完成并部署生产：`NewsArticle.public_path` 改为 `/news/<article_id>/`，公开详情页可通过文章 ID 访问，非纯数字旧 slug URL 会跳转到 ID URL；首页、热门列表、后台前台查看入口和 QQ 自动推送消息均继续通过 `article.public_path` 使用 ID URL。
- 本地已通过完整 `stable` 测试、三个子 change 的严格校验、`openspec validate --all` 和 `git diff --check`；生产已通过容器重建、Django check、外部健康检查、首页检查、ID URL 与旧 slug 跳转 smoke test。

## 当前已知风险与待确认项

- 公开首页资讯流升级已部署生产；后续仍需观察真实访问、图片加载和自动发布内容在首页的长期表现
- 当前正式域名阶段仍以 HTTP 为主，HTTPS 证书尚未接入完成
- 需要把 HTTP 阶段的临时安全配置，在 HTTPS 切换时重新收紧
- 需要继续确认抓取调度、翻译调度、发布链路在正式域名环境下的长期稳定性
- 自动化发布涉及内容安全，生产首轮建议低频、低批量、保守开关启用
- AI 改写真实效果依赖模型配置与术语库质量，需继续通过后台人工抽检
- 邮件通知首版已实现；短信 / 微信通知当前只保留日志与配置位；QQ / OneBot 真实发送网关已在生产配置并通过测试消息，自动推送代码已部署并进入测试群灰度
- 需要补足更标准的部署基线、回滚与备份演练
- QQ Bot 自动推送已在生产开启测试群灰度；如出现 QQ 客户端发送异常，优先通过 `QQ_PUSH_ENABLED=false` 停止自动推送并保留 OneBot 网关排查。

## 2026-06-23 QQ 群自动推送 OpenSpec change

### 当前实现

- 新增 OpenSpec change：`add-qqbot-auto-push`。
- 新增自动 QQ 推送交付模型，以“文章 x QQ 群”为唯一粒度记录状态、尝试次数、最大尝试次数、错误类型、错误信息、OneBot 响应、消息 ID、最后尝试时间和成功时间。
- 自动推送默认关闭：`QQ_PUSH_ENABLED=false`。
- 自动推送默认范围：`QQ_PUSH_SCOPE=high_value_only`，首版高价值口径为 `score_total >= AUTO_REVIEW_THRESHOLD`；也支持 `all_public`。
- 发布入口已接入自动推送入队：人工发布、`publish_article()` helper 和自动发布成功后都会在开关开启时异步进入 QQ 推送编排。
- 推送前检查 `SITE_URL + article.public_path` 是否可访问；URL 不可访问和 OneBot 发送失败分别记录为 `url_unavailable` 与 `send_failed`。
- 自动交付在领取一次发送尝试前会先检查 OneBot `/get_status`，若网关离线、登录态失效或状态检查失败，则记录 `send_failed` 错误摘要并保持可恢复重试状态，不调用 `/send_group_msg`，也不增加 `attempt_count`。
- 自动交付会先原子领取尝试再执行 URL 检查和 OneBot 发送，避免重复任务并发消耗重试次数。
- OneBot HTTP 200 但 JSON 返回业务失败时按 `send_failed` 记录，不会误标记为成功。
- `sending` 状态超过 `QQ_PUSH_SENDING_STALE_SECONDS`（默认 600 秒）后允许后续任务重新领取，避免 worker 异常后长期卡住。
- 自动发送按目标群最近一次尝试时间做最小间隔保护，`QQ_PUSH_MIN_INTERVAL_SECONDS` 默认 60 秒，避免批量发布或补推时压垮 QQ / NapCat 发送通道。
- 自动推送只读取 `PushTarget.is_active=true` 的群；`is_default` 保留给后台手动推送默认目标。
- Django Admin 新增自动交付记录查看入口，并在文章详情中展示交付内联记录。

### 当前启用策略

- 生产已配置 NapCatQQ / OneBot v11 网关、测试群和 access token。
- 生产 `.env` 已设置 `QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，当前只等待自然榜单新闻触发测试群推送。
- 生产已部署迁移 `stable.0010_qqpushdelivery`，并设置 `QQ_PUSH_ENABLED=true` 进入测试群灰度。
- OneBot API 不得公网裸露；优先 Docker 内网 `http://onebot:3000`，临时映射只能绑定 `127.0.0.1`。

### 验收记录

- OneBot 直连和 Django 应用侧短消息均已成功发送到测试群 `1026525240`。
- 生产批量补推 126 篇公开文章时，交付记录成功创建并进入有限重试；NapCat / QQ 客户端随后返回 `网络连接异常`，系统正确记录为 `send_failed` 且未误标为成功。
- 已补充 `QQ_PUSH_MIN_INTERVAL_SECONDS` 节流保护，后续自动任务按目标群最小间隔重排，降低 QQ 风控和客户端异常风险。
- 2026-06-25 重新扫码登录 NapCat 后，Django `BotPusher` 短消息发送成功，`qq_auto_push_article_task -> qq_push_delivery_task -> OneBot` 自动任务链路已用真实公开文章验证成功，`QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=all_public` 在生产 worker 生效。
- 2026-06-25 存量补推按 65 秒间隔运行并成功发送 79 条交付记录；按当前验收判断，不再要求继续补推全部历史公开新闻，剩余历史 `retrying/send_failed` 记录保留用于后台排查，不影响后续新发布文章自动推送。
- 2026-06-25 榜单重点推送部署后，生产 worker 已确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 生效；本次不补推历史公开新闻，后续只等待自然榜单新闻推送。
- 2026-06-26 QQ 推送中断排查确认根因是 NapCat 快速登录态失效，日志出现“登录态已失效，请重新登录 / 你的用户身份已失效”。处理过程为：先把生产 `.env` 临时切到 `QQ_PUSH_ENABLED=false` 并重启 `worker / beat` 暂停自动推送；用户重新扫码登录后，OneBot `/get_status` 返回 `online=true`，`/get_login_info` 返回 QQ `1577955464`，群列表包含 `1026525240`，Django 应用侧测试消息发送成功；随后恢复 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 并重启 `worker / beat`。本次不补推全部已发表新闻，后续只等待自然榜单新闻触发。
- 2026-06-26 已将 OneBot 离线防护部署生产，服务器 `/opt/umanewsbot` 从 `849004c` 更新到 `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`。部署后 `web` healthy，迁移显示 `No migrations to apply`，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `http://umafans.run/healthz/` 均返回 `200`；worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`，`BotPusher().is_online()` 返回 `(True, '')`，测试群 `1026525240` 发送部署验证消息成功，返回 `message_id=1364343902`。

## 2026-06-24 自动发布门禁优化本地实现

- OpenSpec change：`refine-automation-publish-gates`，当前 `tasks.md` 已完成本地实现和验证。
- 新增配置：
  - `AUTO_REWRITE_ENABLED=false`：默认跳过 AI 改写前置。
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`：默认使用基准翻译稿作为自动发布内容源。
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`：访问量榜和注目数榜评分阶段放行。
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`：高价值 warning 初期告警收件人示例。
- 新增数据字段：
  - `NewsArticle.gate_issues` 保存结构化门禁 issue。
  - `WorkflowStatus.DUPLICATE` 描述高度重复内容。
  - `duplicate_of / duplicate_score / duplicate_reason` 保存重复检测解释。
  - `automation_warning_email_signature / automation_warning_email_sent_at` 用于 warning 邮件 24 小时去重。
- 迁移 `0009_automation_publish_gates` 会导入首批非马名普通词固定译法，包括 `タイトル`、`メートル`、`オッズ`、`ハンデ`、`ラジオ`、`ダート`、`マイル`、`スプリント`、`クラス`、`チャンス`、`キャリア`、`イメージ`、`デビュー`、`ゲート`。
- 后台候选列表、候选详情、自动化日志和 Django Admin 已展示 blocker / warning / info、重复检测结果和相似文章信息。
- `2026-06-24` review 返修：
  - 重新校验通过且当前不再重复的文章，会清理旧 `duplicate_of / duplicate_score / duplicate_reason`，并把旧 `duplicate` / `pending_review` 状态恢复为可进入自动发布批次的候选状态，避免显示 `publish_ready` 但被批发布排除。
  - 候选列表与候选详情中的相似文章现在链接到后台候选详情 `/admin/candidates/<id>/`。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AutomationFlowTests stable.tests.ConsoleFlowTests --noinput`：通过，23 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，106 项。
  - `openspec validate refine-automation-publish-gates --strict`：通过。

### 生产上线结果

- PR：GitHub PR #4 `[codex] refine automation publish gates` 已 squash merge。
- 生产提交：服务器 `/opt/umanewsbot` 已从 `71ab966` 更新到 `42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 已设置生产灰度配置：
  - `AUTO_REWRITE_ENABLED=false`
  - `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`
  - `HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention`
  - `HIGH_VALUE_WARNING_SCORE_THRESHOLD=90`
  - `AUTO_DUPLICATE_LOOKBACK_DAYS=7`
  - `AUTO_DUPLICATE_HIGH_THRESHOLD=0.86`
  - `AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72`
  - `AUTOMATION_WARNING_EMAIL_ENABLED=true`
  - `AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com`
  - `AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24`
- 容器：`web` healthy，`db / redis` healthy，`worker / beat` up。
- 迁移：`stable.0009_automation_publish_gates` 已应用；运行时确认 `WorkflowStatus.DUPLICATE=True`，首批 `non_horse_common_word` 普通词种子数量为 `14`。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/` 返回 `200`。
- 部署注意：重启初期日志曾出现一次 `automation_warning_email_sent_at` 字段已存在异常，判断为容器启动自动迁移与手工迁移并发撞车；后续日志显示 `No migrations to apply`，`showmigrations stable` 显示 `0009` 已应用，服务健康检查持续返回 `200`。

## 2026-06-24 抓取新鲜度与 JRA 日期解析本地实现

- OpenSpec change：`fix-crawl-freshness-and-jra-date-parse`，当前已完成本地实现并于 `2026-06-25` 部署生产。
- 修复范围：
  - JRA 官方新闻日期解析兼容 `2026年5月31日`、`5月31日`、零填充和非零填充日期。
  - JRA 无年份日期优先使用列表月份或 URL 年份；缺少上下文时使用当前东京年份，若推断日期晚于当前东京日期超过 7 天则回退上一年。
  - JRA 列表中单条日期异常会跳过该条并继续处理同一列表中其他新闻；整体结构或网络失败仍会记录为 JRA 抓取失败。
  - netkeiba 访问量榜和注目数榜从每天 `00:00/12:00`、`00:05/12:05` 调整为小时级抓取，并在 review 返修后避开新着顺和周日重赏高频补抓：新着顺每小时 `00` 分，访问量榜每小时 `16` 分，注目数榜每小时 `26` 分。
  - 内置来源定义同步更新访问量榜 / 注目数榜 `crawl_interval_minutes=60` 和来源备注，避免后台展示、异常检测与实际调度不一致。
  - 后台工作台和来源列表新增来源健康摘要，区分“运行中”“运行超时”“成功”“成功无新增”“失败”“长时间未运行”，并展示最近新增数、重复数或错误摘要；超过 60 分钟仍未完成的运行中记录会显示为疑似卡住，停用来源不参与“长时间未运行”判定。
  - JRA 单篇详情结构异常被跳过时，跳过摘要会同时写入本轮 `CrawlJob.error_message` 和 `NewsSource.last_crawl_message`，便于事后按 job 追溯。
- 本地验证：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.ConsoleFlowTests stable.tests.CrawlAutoTranslateTests --noinput`：通过，25 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，118 项。
  - `openspec validate fix-crawl-health-running-and-schedule-stagger --strict`：通过。
  - `openspec validate --all`：通过，7 项。
- 生产部署：
  - 服务器 `/opt/umanewsbot` 已于 `2026-06-25` 更新到 `7f54f13`，部署前 `.env` 备份为 `.env.backup.three-changes-20260625_003714`。
  - `web / worker / beat` 已重建，`manage.py check` 通过，`http://127.0.0.1/healthz/` 与 `/` 均返回 `200`。
  - 运行态确认 `crawl-netkeiba-latest-hourly / access / attention` 分钟分别为 `0 / 16 / 26`，内置来源定义中三者 `crawl_interval_minutes=60`。
  - 后续仍需等待自然调度，确认访问量榜 / 注目数榜在连续小时内按 `16 / 26` 分生成新 `CrawlJob`。

## 2026-06-23 前台发布判定代码阅读结论

- 公开前台首页 `/` 与详情页 `/news/<article_id>/` 只展示 `workflow_status=published` 且 `published_to_web_at` 非空的 `NewsArticle`；旧的非纯数字 `/news/<slug>/` 兼容入口会跳转到对应 ID URL。
- 抓取入库的新稿默认是 `workflow_status=pending_translation`，不会因为来自 `netkeiba` 新着、访问榜、注目榜或 `JRA` 官方新闻而直接进入前台。
- 翻译成功后文章进入 `pending_edit`；若 `AUTOMATION_ENABLED=true`，会触发自动化评分、改写与校验链路。
- 自动化评分为 `auto` 的文章也不会立刻公开；必须完成改写、通过一致性校验成为 `automation_status=publish_ready`，再由批量自动发布任务写入 `workflow_status=published` 与 `published_to_web_at` 后才进入前台。
- 自动化硬规则会把重复稿、正文过短或为空、疑似乱码/结构损坏、疑似广告或导航短页直接置为 `ignored`，默认不进入前台。
- 长采访或引语较多、翻译未成功、缺少基准中文翻译等会转为 `manual` / `pending_review`，需要人工审核后发布。
- 人工发布通过运营后台文章编辑页完成时会写入 `workflow_status=published`、`published_to_web_at`、`published_by_mode=manual`；无封面时需要二次确认。Django Admin 或后台 API 若只改 `workflow_status` 而不补 `published_to_web_at`，仍不会被公开前台接收。

## 2026-06-23 外部赛马数据导入 OpenSpec 提案

- 已创建 OpenSpec change：`add-netkeiba-horse-data-import`。
- 提案目标：使用 `keibascraper` / netkeiba 作为低频离线导入来源，先抓取近两年比赛、出走、赛果、赔率、马匹血统和马匹履历数据，保存结构化字段与原始 payload，并派生本地马名索引。
- 关键约束：导入默认关闭，不加入自动全量调度；生产必须人工显式执行、强制限速、随机抖动、小批量、可暂停、可恢复；导入失败不得影响新闻抓取、翻译、自动化发布或公开前台。
- 当前状态：仅完成 proposal、design、delta spec 和 tasks，尚未实现代码，尚未执行真实爬取。

## 2026-06-19 公开首页资讯流升级 OpenSpec 主 change

### 已归档产物

- 正式规格：`openspec/specs/public-home-info-feed/spec.md`
- 归档目录：`openspec/changes/archive/2026-06-22-upgrade-public-home-info-feed/`
- 归档内保留 proposal、design、delta spec、tasks 和 `.openspec.yaml`

### 主范围

- Web 端：首页升级为轻导航、主头条、普通新闻流和右侧热门/重点辅助模块。
- 移动 H5：首页升级为轻顶部、轻量头条和高密度左文右图新闻列表。
- 数据层优先复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，不新增数据库模型。
- 公开站点样式从后台 `console.css` 中解耦，后续实现应新增公开站点专用样式入口。
- 文章详情页与首页共享公开站点视觉体系，并保持已有有效稿件字段优先级。
- 后续实施采用严格 TDD：发布过滤、普通流排序、头条选择、热门代理、详情页字段和公开静态资源必须逐行为执行 RED -> GREEN -> REFACTOR，禁止一次性批量写完全部测试后再实现。
- 热门代理必须在有限候选集内批量读取 `NewsSnapshot` 或使用等价预取方式，避免无上限扫描或逐篇文章查询最近快照。

### 明确非目标

- 不做原生 App、个性化推荐、无限滚动、站内浏览量、站内评论或用户系统。
- 不在本轮新增手工置顶、推荐位、专题、搜索频道或赛事日历模型。
- 不改抓取、翻译、AI 改写、自动发布、QQ 推送或 Docker Compose 主架构。

### 本地实现结果

- 公开首页 `/` 已升级为公开站点专用模板和 `stable/public.css`，不再以后台 `console.css` 作为主要样式入口。
- 首页数据层复用现有 `NewsArticle`、`NewsSnapshot` 与自动评分字段，提供 `headline_article`、`feed_articles`、`latest_articles` 和 `hot_articles`。
- 头条选择按近期范围、赛事优先级、自动评分、封面和发布时间排序；低量内容回退到近 7 天或最新已发布文章。
- 热门代理在有限已发布候选集内批量读取上游访问/注目快照，无快照时按自动评分和发布时间回退；页面只标注“原站热度/原站排行”，不包装为本站评论或浏览量。
- 移动 H5 首页采用轻头条 + 左文右图高密度列表，普通卡片在 390px 视口验收中稳定为约 128px 高，缺图卡不破坏列表布局。
- 详情页复用公开站点 base，继续展示有效标题、摘要、正文、来源、原文链接和发布时间，并完成窄屏阅读排版验收。
- 本轮未新增数据库模型、迁移、生产配置或部署运行手册步骤。

### 校验结果

- `openspec validate upgrade-public-home-info-feed --strict`：归档前通过。
- `openspec validate --all`：归档前通过；归档并同步正式 spec 后再次通过。
- `/plan-eng-review upgrade-public-home-info-feed`：通过。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable.tests.PublicHomeInfoFeedTests`：通过，10 项。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 manage.py test stable`：通过，88 项。
- 本地开发服务器浏览器验收：桌面首页、移动首页、桌面详情页、移动详情页通过；无横向溢出，图片加载正常，移动普通卡高度受控，桌面主列与右侧热门模块不重叠。

### 生产部署结果（2026-06-22）

- GitHub PR #1 从 draft 转为 ready 后合并到 `main`，merge commit 为 `e834f58`，包含实现提交 `1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`；部署前备份 `.env` 为 `.env.backup.20260622_140844`。
- 生产使用低成本 compose 执行 `./deploy_lowcost.sh`：重建 `web/worker/beat`，`migrate` 显示 `No migrations to apply`，`collectstatic` 成功处理 `stable/public.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`。
- 首页 HTML 已引用 `/static/stable/public.2eec24723b45.css`，页面包含 `home-page`、`headline-card`、`news-card` 和“原站热度”；不再引用后台 `console.css`。
- 浏览器生产验收通过：桌面端显示轻导航、头条和热门模块；390px 移动端普通新闻卡约 `128px` 高，首屏头条后可见 3 条普通新闻，无横向溢出；新闻详情页可打开，标题、封面和公开详情结构正常，控制台无错误。

### 移动端首屏密度 follow-up（2026-06-22）

- 在不改变首页数据层、公开 URL、模板结构或普通新闻卡尺寸的前提下，后续小幅收紧移动端首页视觉密度。
- 调整范围仅限 `server/stable/static/stable/public.css` 的 `max-width: 599px` 移动端规则：
  - 顶部和页面内边距略收紧。
  - 移动端头条图片从 `16 / 9` 改为 `16 / 7`。
  - 移动端头条摘要隐藏，仅保留来源时间和两行标题。
  - 普通新闻卡继续保持约 `128px` 高和右侧缩略图结构。
- 本地临时 SQLite + 浏览器验收结果：390px 视口下头条高度约 `250px`，第一张普通新闻卡提前到 `top=381`，首屏可见 4 条普通新闻卡，无横向溢出，控制台无错误。
- 生产部署结果（2026-06-23）：GitHub PR #2 合并到 `main`，merge commit 为 `04e2ee9`；服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`，部署前备份 `.env` 为 `.env.backup.20260623_120201`。
- 生产 `./deploy_lowcost.sh` 执行成功：`migrate` 显示 `No migrations to apply`，`collectstatic` 后首页引用 `/static/stable/public.9aaf4b105424.css`，`web` 容器 healthy。
- 外部健康检查通过：`http://umafans.run/healthz/` 与 `http://umafans.run/` 均返回 `200`；首页包含 `home-page`、`headline-card`、`news-card` 和“原站热度”，不再引用 `console.css`。
- 浏览器生产验收：390px 移动端头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通卡约 `128px` 高，首屏可见 4 条普通新闻卡，无横向溢出；详情页公开结构、封面和标题正常，控制台无错误。

## 2026-06-07 术语候选发现生产部署纪要

### 部署内容

- 服务器 `/opt/umanewsbot`：`git pull origin main` 从 `7123e4e` 快进到 `e2e3e07`
- 迁移 `0006`（纯新增 `TermCandidate` / `TermCandidateEvidence` 两表）已应用；`web` 启动脚本会自动迁移，显式 `migrate` 显示 `No migrations to apply`
- `.env` 追加并保持关闭：`TERM_DISCOVERY_ENABLED=false` / `TERM_DISCOVERY_PROVIDER=rules` / `TERM_DISCOVERY_MIN_CONFIDENCE=60`
- 用低成本 compose `docker-compose.prod.lowcost.yml` 重建 `web/worker/beat`，`db/redis/nginx` 未动

### 迁移前备份（可回滚）

- `.env.backup.20260607_033207`
- 数据库快照 `backups/pre-0006-20260607_033207.sql`（74M，`horse_news` 库，含 `PostgreSQL database dump complete` 标记）

### 上线后验证

- 容器 `web/db` healthy、`worker/beat` up；`manage.py check` 0 issues
- 候选/证据模型可查、计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`
- `worker` 近 200 行日志无报错；核对 `AUTOMATION_ENABLED=true`、`REWRITE_PROVIDER=siliconflow` 未变更

### 回滚方式

- 停用功能：将 `TERM_DISCOVERY_ENABLED=false`（当前即为关闭），重启 `web` 与 `worker` 即可，无需回滚迁移或删除候选数据
- 整体回退：用上面的 `.env` 备份与数据库快照还原

## 最近一次翻译稳定性修复

- 现象：部分文章翻译失败，错误为 `Translation response changed unknown horse names`
- 原因：未知马名校验过于严格；模型没有原样保留疑似未收录马名时，系统会让整篇翻译失败
- 修复：
  - 翻译 prompt 中对未知马名使用 `__UMA_KEEP_n__` 占位符保护
  - 模型返回后将占位符还原为原始日文马名
  - 若模型仍未保留未知马名，不再让整篇失败，而是写入 metadata warning 后接受译文
- 验证：
  - 新增未知马名占位符还原测试
  - 新增未知马名仍缺失但不阻断翻译的测试
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable` 通过，45 项

## 自动化内容运营 MVP 开发纪要

### 本轮新增能力

- `NewsArticle` 增加自动化字段：分流模式、风险等级、自动化状态、评分、决策原因、基准翻译稿、改写稿、自动发布时间与错误信息
- 新增 `AutomationLog`，记录评分、改写、校验、发布、通知各阶段过程
- 新增 `NotificationLog`，记录邮件 / 短信 / QQ / 微信通知状态；MVP 真实发送只启用邮件
- 新增自动化服务：
  - `stable.services.automation`
  - `stable.services.rewriting`
  - `stable.services.validation`
  - `stable.services.notifications`
- 新增 Celery 任务：
  - `process_article_automation_task`
  - `score_article_task`
  - `rewrite_article_task`
  - `validate_rewrite_task`
  - `auto_publish_batch_task`
  - `send_notification_task`
  - `detect_automation_anomalies_task`
  - 新增 Celery Beat 调度：
    - 每 15 分钟批量自动发布
    - 每 30 分钟检测自动化异常
  - 自动发布批量规则已调整为：
    - 常规时段每批最多 4 篇
    - 每周日北京时间 13:00-16:00 每批最多 10 篇
    - 调度频率仍为每 15 分钟一次

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，40 项测试

### 生产启用前注意

- 必须先部署代码并执行迁移 `python manage.py migrate`
- 初次部署建议 `AUTOMATION_ENABLED=false`
- 确认后台可看到自动化字段和日志后，再切换 `AUTOMATION_ENABLED=true`
- 当前自动发布策略为常规每批 4 篇、周日 13:00-16:00 每批 10 篇，并定期人工抽检自动发布稿

## 专有术语候选发现与待标注池

### 当前实现

- 新增 `TermCandidate` 与 `TermCandidateEvidence`，分别保存待审核术语和按文章聚合的来源证据。
- 首版支持马名、比赛名、骑手名和马主名四类实体。
- 新文章入库后可旁路触发发现任务；发现失败不会阻断抓取、翻译、改写或发布。
- 候选会与正式 `TermEntry.source_ja`、日文别名及已有候选去重；停用正式术语也参与去重。
- 后台新增“术语候选”列表、详情、单篇重新发现、接受、修改后接受、合并、拒绝、忽略和保守批量拒绝/忽略。
- 规则或 AI 发现结果不会直接写入正式术语库，只有工作人员明确接受后才创建 `TermEntry`。

### 当前启用策略

- `TERM_DISCOVERY_ENABLED=false`：默认关闭。`2026-06-07` 已在生产应用迁移并部署代码，当前处于“先关后开”灰度阶段，待单篇抽检后再开启。
- `TERM_DISCOVERY_PROVIDER=rules`：首版使用保守规则发现器。
- `TERM_DISCOVERY_MIN_CONFIDENCE=60`：低于阈值的发现结果不进入候选池。

### 当前验证结果

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，69 项。
- `openspec validate --all`：通过。
- 两种生产 Compose 配置基于 `.env.example` 检查通过。
- 已使用独立 SQLite 数据库部署本地验收环境，并通过浏览器完成筛选、单篇重跑、接受、合并、拒绝、忽略、批量操作、操作日志和别名搜索验收。

## 最近一次关键修复纪要

### 现象

- 域名已经解析到服务器 IP
- HTTP 请求被 `301` 跳转到 HTTPS
- HTTPS 请求返回 `400 Bad Request`
- 浏览器无法正常打开正式域名页面

### 排查过程

- 先确认 DNS 是否已经真正打通，排除“域名未解析”的假象
- 再比对仓库当前代码与服务器实际 `HEAD`
- 检查服务器 `.env` 中的 `ALLOWED_HOSTS`、`SITE_URL`、`SECURE_SSL_REDIRECT` 等关键项
- 进入 `nginx` 容器读取真实 `/etc/nginx/conf.d/default.conf`
- 检查 `web` 容器运行态环境变量与日志
- 最终确认线上实际行为与仓库当前预期不一致

### 确认的真实根因

- 服务器并未运行到本地最新域名接入修复版本
- 服务器仍在使用旧版 `nginx` 配置，保留 `80 -> 443` 跳转与启用中的 HTTPS server block
- 服务器 `.env` 仍使用旧版 IP + HTTPS 强制配置
- `ALLOWED_HOSTS` 未包含正式域名，导致域名下请求被 Django 拒绝

### 修复动作

- 备份服务器 `.env`
- 清理或暂存本地未提交运行态差异
- 将服务器代码同步到正确版本
- 更新 `.env`，切换为正式域名 + HTTP 阶段配置
- 重建并启动 `web / worker / beat / db / redis / nginx`
- 进入容器核对真实 `nginx` 配置与环境变量，确保运行态与仓库一致

### 修复后验证结果

- `nginx` 容器加载了新版 `default.conf`
- `80 -> 443` 强制跳转已移除
- 正式域名 `umafans.run` / `www.umafans.run` 页面可打开
- 线上服务恢复到与当前仓库预期一致的状态

### 后续如何避免再次发生

- 每次部署前先确认服务器 `HEAD`，不要只看本地仓库
- 每次域名或安全策略变更时，同时核对：
  - 仓库代码
  - 服务器 `.env`
  - `nginx` 容器内真实配置
  - `web` 容器内真实环境变量
- 不把聊天记录当唯一记忆来源，关键修复过程必须落文档
- 生产问题处理时，坚持“先核对运行态，再给结论”

## 2026-06-23 外部赛马数据导入实现状态

### 本地已实现

- 新增 OpenSpec change：`add-netkeiba-horse-data-import`。
- 新增 `keibascraper==3.1.5` 依赖，并通过管理命令提供 import 冒烟检查入口。
- 新增外部赛马数据表：比赛、出走表、赛果、赔率、马匹、马匹履历、马名索引、导入运行、导入错误和单来源导入锁。
- 新增 `stable.services.external_horse_data`：
  - 包装 `keibascraper.race_list()` 与 `keibascraper.load()`。
  - 项目侧强制执行网络开关、请求间隔、随机抖动。
  - 保存结构化字段与 `raw_payload`。
  - 对比赛、出走、赛果、赔率、马匹、履历做幂等 upsert。
  - 从出走表、赛果、可信单马参数派生 `ExternalHorseAlias`。
  - 单马导入仅在存在可信马名时创建马名索引，避免凭空写入错误马名。
  - 记录覆盖率统计：比赛数、出走数、赛果数、赔率数、马匹数、履历数、唯一马 ID、唯一日文马名、缺失马 ID/马名记录数。
- 新增管理命令 `import_external_horse_data`：
  - 支持默认近两年、指定年月、指定 `race_id`、指定 `horse_id`、`--horse-name`、`--dry-run`。
  - 支持 `--max-races`、`--max-horses`、`--fetch-odds`、`--no-fetch-horse-detail`。
  - 支持 `--lookup-name` 查询本地马名索引。
  - 支持 `--stats-run-id` 查看导入运行统计。
  - 支持 `--check-dependency` 检查 `keibascraper` 是否可 import。
- 新增 Celery 任务 `import_external_horse_data_task`，但未加入默认 Celery Beat 全量调度。

### 当前默认策略

- `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false`。
- `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
- 代码已可部署迁移，但生产不会自动发起 netkeiba 请求。
- 外部数据导入当前不参与新闻抓取、翻译、AI 改写、自动发布或公开前台。

### 本地验证

- `DB_ENGINE=sqlite python manage.py check`：通过。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ExternalHorseDataImportTests`：通过，8 项。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`：通过，96 项。

### 生产执行提醒

- 生产首次真实导入前必须备份数据库。
- 先执行 dry-run 或单月小批量。
- 首次真实请求建议使用 8-10 秒间隔、小批量、低峰时段，不抓赔率。
- 同一来源通过导入锁避免多 worker 并发放大请求。
- 如发现异常，优先关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED` / `EXTERNAL_HORSE_DATA_ALLOW_NETWORK` 并停止任务；新表不参与主新闻链路。

### 生产首轮小批量导入结果

- 生产部署提交：`58a6e82`。
- 部署前 `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- 服务器迁移：`stable.0008_externaldataimportrun_externaldataimportlock_and_more` 已应用。
- 容器内依赖检查：`keibascraper import ok`。
- dry-run：`2026-05` 单月、小批量、最多 10 场，预计 20 个请求。
- 真实导入命令：`2026-05`、`--max-races 10`、`--max-horses 30`、不抓赔率、不补马匹详情、请求间隔 10 秒 + 2 秒抖动。
- 运行结果：`run_id=1`，`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=326`。
- 写入统计：`race_count=10`、`entry_count=151`、`result_count=143`、`horse_count=143`、`unique_horse_id_count=143`、`unique_horse_name_count=143`、`missing_horse_id_or_name_count=16`。
- 样本马名索引已写入，如 `ヴォルスター`、`ファイツオン`、`サトノエピック`。

### 后续继续导入注意

- `2026-06-24` 已补充按月续跑逻辑：再次导入同一月份时会先跳过已落库的 `ExternalRace.race_id`，只处理下一批未导入 race。
- 不建议直接一次性跑近两年全量；应继续按月、小批量、低速运行，并观察失败率和覆盖率。

### 生产第二批续跑结果

- 续跑部署提交：`a61d789`。
- 第二批真实导入：`run_id=2`，同为 `2026-05`，最多 10 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 续跑确认：`parameters.already_imported_race_count=10`，说明第二批已跳过首批落库 race。
- 运行结果：`status=paused`，`success_count=10`，`failure_count=0`，`skipped_count=316`。
- 累计写入统计：`race_count=20`、`entry_count=292`、`result_count=274`、`horse_count=274`、`unique_horse_id_count=274`、`unique_horse_name_count=274`、`missing_horse_id_or_name_count=36`。

### 生产第三批续跑结果

- 第三批真实导入：`run_id=3`，仍为 `2026-05`，最多 30 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 运行结果：`status=paused`，`success_count=30`，`failure_count=0`，`skipped_count=286`。
- 累计写入统计：`race_count=50`、`entry_count=742`、`result_count=695`、`horse_count=695`、`unique_horse_id_count=695`、`unique_horse_name_count=695`、`missing_horse_id_or_name_count=94`。
- 服务器健康检查：`/healthz/` 返回 `200`。

### 生产长循环导入中断记录

- `2026-06-24` 按用户确认启动长循环：从 `2026-05` 到 `2025-06`，每批 25 场，不抓赔率，不补马匹详情，10 秒间隔 + 2 秒抖动。
- 成功完成批次：`run_id=4` 到 `run_id=8`，均为 `2026-05`，每批 25 场，均 `failure_count=0`。
- 中断批次：`run_id=9`，`2026-05`，已成功 7 场后执行进程以退出码 `137` 中断；当时 `web/db` 容器发生重启，但 `OOMKilled=false`。
- 已人工收尾：将 `run_id=9` 标记为 `partial`，写入 `finished_at` 和 coverage，释放 `ExternalDataImportLock`。
- 中断后累计写入：`race_count=182`、`entry_count=2692`、`result_count=2518`、`horse_count=2401`、`unique_horse_id_count=2401`、`unique_horse_name_count=2401`、`missing_horse_id_or_name_count=348`。
- 当前服务状态：`web/db/redis/nginx/worker/beat` 运行，`/healthz/` 返回 `200`。按“报错退出则停止”约定，未继续启动后续导入。

## 后台原文选区快速加入术语库

- OpenSpec change：`add-selection-term-quick-add`。
- 本地分支：`codex/add-selection-term-quick-add`。
- 实现时间：`2026-06-24`。
- 状态：已于 `2026-06-25` 合并到 `main` 并部署生产，OpenSpec 已归档为 `openspec/changes/archive/2026-06-24-add-selection-term-quick-add/`。

### 已实现能力

- 候选详情页和文章编辑台的原文标题、原文正文已标记为可选区来源。
- 两个页面都新增“快速加入术语库”入口；管理员可点击“使用当前选区”填入日文原词，也可手工粘贴作为无 JavaScript fallback。
- 快速表单字段包含日文原词、术语类型、中文译词；术语类型默认 `horse`（马名），但可改为赛事、骑手、调教师、马主、牧场、赛马场、机构、固定译法或其他。
- 后端新增文章上下文 POST 入口 `console-article-quick-term-create`，路径为 `/admin/articles/<article_id>/quick-term/`。
- 创建正式术语时复用 `validate_term_payload()`，继续执行正式术语库的类型、重复、比赛等级、启用状态和优先级校验。
- 快速创建默认写入：`is_active=true`、`priority=0`、`race_grade=""`、`aliases_ja=[]`、`aliases_zh=[]`，并在 `notes` 记录来源文章 ID 和标题。
- 创建成功后留在当前页面并显示成功消息，同时写入 `OperationLog`。
- 创建失败时不写入 `TermEntry`，通过 messages 展示错误；重复术语提示已有术语 ID，并提供已有术语编辑页链接。

### 明确边界

- 快速加入术语库只写入 `TermEntry` 和操作日志。
- 不触发 `translate_article_task`，不触发自动化处理，不修改当前文章的 `title_zh`、`body_zh`、`base_translation_zh` 或 `rewrite_body_zh`。
- “新增术语后自动重新应用术语/重翻译联动”仍属于后续 change，不在本次实现中。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。

### 验证结果

- `DB_ENGINE=sqlite python manage.py check` 已通过（本地使用 Codex bundled Python 执行）。
- `DB_ENGINE=sqlite python manage.py test stable.tests.ConsoleFlowTests --verbosity=2` 已通过；本轮按 OpenSpec 场景补齐非法术语类型、换行误选整段、文章不存在、非联动状态保持和原文选区脚本限制等测试。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --verbosity=2` 已通过，126 个测试全部通过。
- `openspec validate add-selection-term-quick-add --strict` 已通过。
- 本地浏览器验收使用临时 SQLite 后台：
  - 候选详情页可创建术语并返回当前候选页。
  - 候选详情页重复创建同类型同日文原词时显示失败提示和已有术语编辑链接。
  - 编辑台快速术语入口已验证不会提交外层文章编辑表单；提交成功后返回编辑台。
  - 无选区点击“使用当前选区”不会乱填，提示需在原文标题或正文中选择短词。

## 后台快速术语创建后的当前稿联动提案

- OpenSpec change：`reapply-terms-after-quick-add`。
- 创建时间：`2026-06-24`。
- 当前状态：本地实现和验证已完成；review 后的浮层交互和多标签页 session pending 返修已于 `2026-06-25` 完成，并已随 `7f54f13` 部署生产。OpenSpec 已归档为 `openspec/changes/archive/2026-06-24-reapply-terms-after-quick-add/`。
- 目标：在候选详情页或文章编辑台快速创建正式术语后，为当前文章提供明确的后续动作：
  - 一次性“应用该术语到当前稿”：只把刚创建的指定术语应用到当前文章整篇已有中文字段，不调用翻译模型，不重扫整个正式术语库。
  - 页面级“重新翻译”：复用现有 `translate_article_task`，异步重新走翻译链路；不属于术语成功浮层，若页面已有按钮则不新增。
- 关键边界：
  - 不做全站批量重翻译或批量重应用。
  - 快速创建成功后的应用入口只出现一次；刷新、离开页面或错过成功反馈后不补常驻入口。
  - 不自动发布文章，不改变前台发布过滤规则。
  - 默认保护 `manually_edited_fields` 中的人工标题、正文、摘要和推送摘要，不在无确认时覆盖人工稿。
  - 术语应用必须记录文章、用户、来源术语、更新字段和跳过字段；页面级重新翻译继续记录文章、用户和任务触发结果。
- 实现范围：
  - 新增指定术语应用服务函数，只替换刚创建术语的日文原词和日文别名。
  - 新增后台 POST 入口 `/admin/articles/<article_id>/apply-created-term/`。
  - quick-create 成功后通过 session 多 pending 字典提供一次性后续动作上下文；候选详情页和编辑台只消费匹配当前文章与页面上下文的 pending follow-up。
  - `candidate_retranslate` 改为安全返回，并继续作为页面级重新翻译入口记录任务触发结果；术语成功浮层不提供重翻译入口。
  - 候选详情页和编辑台已改为页面上方浮层：`术语【日文名（中文名）】已添加，点击此处立即应用到文章中`；浮层只承载当前术语应用，不承载重新翻译。
  - 旧的术语表单内嵌“刚创建术语”面板和 `retranslate-created-term-*` follow-up 表单/按钮已删除；重新翻译仅保留页面级既有入口。
  - 浮层点击“点击此处”立即应用，不再二次确认；点击关闭 icon、应用成功、当前页面新术语浮层出现、关闭页面或 15 秒超时后消失。
  - 浮层不阻塞选区、滚动、编辑和其他不离开当前页面的点击行为。
  - session follow-up 已从全局单槽改为多 pending 结构，避免多标签页之间互相覆盖；渲染不匹配文章或上下文时不会消费其他 pending follow-up。
  - 后端不额外增加一次性 token 限制；当前后台仅单人可信使用，手工构造接口请求被视为可接受风险。
- TDD 测试：
  - `2026-06-25` 已先在 `server/stable/tests.py` 补充完整测试约束，覆盖浮层文案、关闭/15 秒 DOM 合同、旧内嵌面板不存在、`retranslate-created-term-*` 不存在、多 pending、不匹配页面不消费 pending、同页新术语替换旧浮层，以及应用术语不派发翻译任务。
  - 红灯阶段结果：未实现新交互前，`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ConsoleFlowTests --noinput` 为 31 项中 5 项失败，失败集中在旧内嵌面板和单槽 session。
- 本轮验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.ConsoleFlowTests --noinput`：通过，31 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，135 项。
  - `openspec validate reapply-terms-after-quick-add --strict`：通过。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 三个运营改造 change 合并、部署与归档`。
- 规格校验：`openspec validate reapply-terms-after-quick-add --strict` 已通过。

## 2026-06-25 外部马名索引接入识别链路本地实现

- OpenSpec change：`use-external-horse-alias-for-name-recognition`。
- 创建时间：`2026-06-25`。
- 当前状态：本地实现、验证、OpenSpec 归档和生产部署已完成；归档目录为 `openspec/changes/archive/2026-06-25-use-external-horse-alias-for-name-recognition/`。
- 背景：近两年外部赛马数据已导入 `ExternalHorseAlias`，当前未知马名识别仍主要依赖片假名 token + 上下文打分，无法真正判断没见过的片假名词是不是普通词，容易把 `タイトル` 等普通词误判为马名，也可能漏掉 `マヤノライジン` 等真实马名。
- 核心边界：
  - `TermEntry` 继续表示有中文译名或固定译法的正式术语，参与翻译术语表、译后替换和正式术语校验。
  - `ExternalHorseAlias` 只表示本地外部马名索引，用来确认“这是马名”，不代表已有中文译名，不批量写入 `TermEntry`。
  - 新闻处理链路只查询本地数据库，不在翻译、校验或候选发现阶段实时访问 netkeiba / keibascraper。
- 已实现能力：
  - `server/stable/services/terms.py` 新增结构化马名识别结果，区分 `formal_term`、`external_alias` 和 `heuristic`，并保留旧字符串列表接口兼容既有调用。
  - 识别链路会先提取候选片假名 token，做 NFKC 标准化，再批量查询本地 `ExternalHorseAlias.normalized_name__in`；同一日文名多次出现时按文章出现顺序和长词优先去重。
  - 正式 `TermEntry(term_type=horse)` 优先于外部马名索引；已存在正式中文译名的马名继续走正式术语提示和替换，不再作为未知马名保护。
  - 翻译阶段对外部已知但无中文译名的马名做占位符保护，译后还原为日文原名，不自动替换为中文；翻译 metadata 会记录 `recognized_horse_names` 和 `external_horse_names`。
  - 发布校验阶段把外部已知马名未保留记录为独立 `external_horse_not_preserved` warning，payload 包含日文名、全部外部 horse ID、主展示 ID、来源、置信度和冲突标记；只命中外部索引的马名不触发核心术语或背景术语缺失。
  - 术语候选发现阶段把新闻中出现、外部索引命中但无正式中文译名的马名均作为 `external_horse_alias` 高置信候选来源，包括正文背景段落中的马名；已有正式马名术语或日文别名时不重复建候选。
  - 若片假名文本同时命中普通词过滤表和外部马名索引，必须依赖强马名上下文消歧，不能仅因数据库存在同名马就识别为马名。
  - 同一日文马名对应多个外部 horse ID 时，识别结果和校验 payload 保留全部 ID，不静默只取第一条。
- `2026-06-25` review 返修：
  - `limit` 只限制需要原样保留的外部已知马名和启发式疑似马名，不再让已有中文译名的正式马名占用保护名额。
  - `extract_unknown_horse_names()`、翻译阶段和发布校验阶段均改为先取完整结构化识别结果，再对 `needs_preserve=True` 的名单截断。
  - 新增回归测试覆盖“前面出现多个正式马名，后面出现外部已知但无中文译名马名”时，翻译保护和发布校验仍能命中后者。
- 已创建规格：
  - `external-horse-name-recognition`：新增本地外部马名索引识别能力。
  - `termbase-and-race-priority`：修改翻译链路正式术语命中，并新增外部已知马名保留校验。
  - `term-candidate-discovery`：修改候选发现，使外部马名索引成为高置信来源且不绕过正式术语审核。
- 已同步正式规格：
  - `openspec/specs/external-horse-name-recognition/spec.md`
  - `openspec/specs/termbase-and-race-priority/spec.md`
  - `openspec/specs/term-candidate-discovery/spec.md`
- 验证结果：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests stable.tests.TermCandidateDiscoveryTests --noinput`：通过，49 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests --noinput`：review 返修后通过，39 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：review 返修后通过，147 项。
  - `openspec validate use-external-horse-alias-for-name-recognition --strict`：通过。
  - `openspec validate --all`：归档前后均通过。
- 生产部署结果：
  - GitHub PR #6 `[codex] Use external horse aliases for name recognition` 已 squash merge 到 `main`，merge commit 为 `35b0866`。
  - 服务器 `/opt/umanewsbot` 已从 `817e1c8` 快进到 `35b0866`，部署前 `.env` 备份为 `.env.backup.external-horse-alias-20260625_182936`。
  - `./deploy_lowcost.sh` 执行成功，迁移显示 `No migrations to apply`，`collectstatic` 完成，`web` 容器 healthy，`worker / beat` 已重启。
  - 生产验证通过：`manage.py check` 无问题，`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和 `http://umafans.run/` 均返回 `200`。
  - 生产只读 smoke test：`ExternalHorseAlias` 数量为 `11521`；`recognize_horse_names("ロブチェンが出走", ...)` 返回 `ロブチェン`，来源为 `external_alias`，外部 horse ID 为 `2023107089`。
- 长文样本抽检：
  - 抽检方式：从生产只读导出 5 篇长文、2054 条启用正式术语和 11521 条 `ExternalHorseAlias`，写入本地临时 SQLite 后用当前未部署代码跑识别、候选发现和发布校验；未改生产数据。
  - 样本结果：netkeiba 长文中外部索引可命中多匹真实马名，例如 `ロブチェン`、`パントルナイーフ`、`ミクニインスパイア`、`ドリームコア` 等，并在译文未保留时产生独立 `external_horse_not_preserved` warning。
  - 观察到的后续优化点：JRA 活动公告类长文（例如 `JRA宮崎育成牧場けいばフェスタ`）仍会通过启发式把 `フェスタ`、`ウインズ`、`イベント`、`ポニー`、`オリジナル` 等普通片假名词列为疑似未知马名；外部马名索引能降低真实马名漏报，但不能完全替代后续普通词过滤和启发式收紧。
- 生产部署记录见 `docs/deploy_runbook.md` 的 `2026-06-25 外部马名索引识别链路生产部署`。

## 2026-06-25 国际赛马资讯扩展本地实现

- OpenSpec change：`expand-international-racing-coverage`。
- 当前状态：本地代码、迁移、测试、文档和 review 返修已完成；尚未部署生产，生产仍以已上线的日本新闻源和既有 QQ 推送配置为准。
- 已落地能力：
  - `NewsSource`、`NewsArticle`、外部数据缓存、`TermEntry`、`TermCandidate` 和 `PushTarget` 已增加地区、原文语言、来源类型或群级推送配置字段；现有数据默认回填为 `japan / ja`。
  - 内置来源同步已增加一期国际新闻源最终清单：`Sponichi`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing`、`BHA`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation`。新来源默认 `enabled=false`，需要人工启用或测试抓取；2026-06-26 review 返修后，内置来源同步只更新来源定义，不再覆盖工作人员手动调整的 `enabled` 状态。
  - 已补充排序型入口策略：类似 netkeiba 访问量榜/注目榜的来源，只有在公开 HTML/API 能稳定慢速抓取时才作为独立榜单源接入。本轮确认 `Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓，均作为独立排序/榜单来源加入并保留原站 rank；2026-06-26 review 返修后，同源普通 list 不会覆盖已入库的排序/榜单主来源，普通 list 仍会记录 `NewsSnapshot`；旧候选 `At The Races`、`Paulick Report`、`BloodHorse` 因 403、反爬或空样本风险不进入第一版默认清单。
  - 公开首页新增 `综合 / 日本 / 中国香港 / 英国 / 法国 / 美国` 地区 tab，`/?region=<region>` 过滤头条、信息流和热门列表；地区页翻页会保留当前 `region` 查询参数，不会翻页后跳回综合流；文章详情展示地区、来源和原文语言。
  - 术语库 UI 和服务语义已从“日文原词/日文别名”扩展为“原文/原文别名/原文语言”，并新增 `TermAlias` 作为多语言原文别名表；`TermEntry` 表示正式术语概念和标准中文译名，旧 `source_ja / aliases_ja` 物理字段继续兼容并回填为 `ja` 别名。
  - 翻译、改写、发布校验、候选发现、自动标签和自动化评分会按文章 `source_language` 选择对应 `TermAlias`；日文片假名未知马名启发式只应用于 `ja`，英文和繁中不套日文规则，但会按同语言 `ExternalHorseAlias` 做保守外部马名匹配；英文候选可合并到日文正式术语概念并保存为英文别名。2026-06-26 review 返修后，术语匹配和自动化 P0 马匹命中会按本次候选术语批量加载 `TermAlias`，避免每条术语各查一次别名；英文/繁中外部马名识别会先从文章文本生成候选片段收窄数据库查询，并使用原文中实际出现的大小写/写法作为保护文本；翻译保护、发布校验和候选发现也统一使用真实匹配文本，英文正式术语按大小写不敏感方式命中并记录原文真实写法；最终 review 返修后，自动化 P0 马匹命中、发布校验的核心/背景术语判定、以及“新增术语后应用到当前稿”均复用同一套语言感知匹配，避免 `EQUINOX` 这类大写英文漏判或漏替换。本轮补丁进一步将同语言术语查重、别名去重、导入 upsert、候选合并和术语 API 保存统一为大小写不敏感；同语言大小写变体导入 upsert 会更新正式主原文并同步别名表，跨语言别名 upsert 仍只维护该语言别名、不覆盖概念主原文；后台/API 启停术语时会同步所有语言 `TermAlias` 的启用状态；AI 改写 prompt 的术语表也使用本次文章实际命中的 `matched_text`，避免英文稿看到日文概念主名而漏用标准译名。本次返修明确术语导入 upsert 的目标解析：主原文命中同一术语时才更新；如果只是原文别名命中已有其它术语，预览和提交都会拒绝该行，避免把两个正式概念误合并。
  - 自动化评分已补充英文和繁体中文赛马关键词表，英文 `preview / entries / draw / withdrawn / injury / results / stewards` 等信号会参与分类、高关注命中和重点赛事 fallback，不再只依赖日文关键词。
  - QQ 自动推送保留 `QQ_PUSH_ENABLED` 总开关；每个 `PushTarget` 可配置 `allowed_regions`、`push_scope`、`importance_strategy`。总开关管“能不能推”，群配置管“推什么给谁”；文章地区缺失时返回 `region_missing` 并不自动推送。2026-06-26 review 返修后，`importance_strategy=ranked` 不再只认 netkeiba，也会把 `Sponichi / Sky Sports Racing / Horse Racing Nation` 的排序/榜单稿视为重点新闻；已有群迁移会把空 `allowed_regions` 回填为 `["japan"]`，运行时空地区或非法地区配置也按旧行为仅允许日本，避免旧群或误配置群突然收到全球新闻。
  - HKJC 外部数据新增 `import_hkjc_external_data` 管理命令和 `HKJCExternalDataImporter`，支持 `--race-date`、`--race-id`、`--horse-id`、`--payload-file`、`--commit`、`--lookup-name`、`--stats-run-id`，默认 dry-run；提交只写 External* 缓存表和 `ExternalHorseAlias`，不生成前台赛果页。commit 模式在真实网络抓取实现前必须提供 `--payload-file`，并参考 netkeiba 外部导入使用单来源互斥锁，已有 `STARTED` 导入时拒绝并发写入；payload 超过 `max_races / max_horses` 时直接失败，不静默截断或部分写入。2026-06-26 review 返修后，`max_horses` 会合并统计顶层 `horses`、赛事 `entries` 和 `results` 中可识别的唯一马匹，避免 entries/results 里的大量马绕过批量上限。
  - 公开详情 URL 继续使用 `/news/<NewsArticle.id>/` 全局自增数字 ID；国际新闻源的 `source_article_id` 只作为来源内幂等去重键，使用完整 URL 派生的 `slug-short_hash`，避免同 slug 不同路径碰撞。
  - 国际新闻原始 HTML 只写入 `original_content_html`；`translation_metadata` 和 `NewsSnapshot.snapshot_metadata` 只保留轻量抓取/翻译元信息，不再重复保存整页 HTML；TDN 等列表 API 提供真实发布时间的来源，在详情页缺少日期节点时会回退使用列表时间；`TDN France keyword` 与美国 `TDN` 来自同一站点，入库时使用 `TDN` canonical source site 和同一 `source_article_id` 去重，`NewsSnapshot` 仍记录实际发现来源，法国关键词来源会优先保留法国地区归类。
  - 欧美数据库源 spike 结论已写入 `docs/global_racing_data_source_spikes.md`；本轮 spike 不加入 Celery Beat、生产命令队列或正式导入队列，不写正式外部数据表。
- 本轮新增迁移：
  - `server/stable/migrations/0011_remove_termcandidate_uq_term_candidate_type_normalized_and_more.py`
  - `server/stable/migrations/0012_termalias.py`
  - `server/stable/migrations/0013_alter_newsarticle_source_site_and_more.py`
- 本轮新增/调整的关键入口：
  - 新闻来源同步：`server/stable/services/sources.py`
  - 国际新闻适配器：`server/stable/adapters/international.py`
  - 国际新闻真实探测命令：`server/stable/management/commands/probe_international_news_sources.py`
  - QQ 群级推送判断：`server/stable/services/qq_auto_push.py`
  - HKJC 数据导入：`server/stable/services/external_hkjc_data.py`
  - HKJC 管理命令：`server/stable/management/commands/import_hkjc_external_data.py`
  - 公开首页地区 tab：`server/stable/views.py`、`server/stable/templates/stable/public/feed.html`
- 已完成的本地验证：
  - `openspec/changes/expand-international-racing-coverage/test_cases.md`：已新增完整测试用例矩阵，按 OpenSpec `proposal/design/spec` 拆分，不依据实现代码倒推；覆盖地区/语言、国际新闻源、公开首页、术语多语言、QQ 群级推送、HKJC 导入、欧美数据源 spike、迁移和非目标边界。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.AdapterTests stable.tests.InternationalSourceMetadataTests stable.tests.HKJCExternalDataImportTests stable.tests.AutomationFlowTests --noinput`：通过，35 项。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable.tests.InternationalSourceMetadataTests stable.tests.QQAutoPushTests --verbosity 2`：通过，26 项。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：最终源清单返修前通过，201 项；返修后通过，209 项；2026-06-26 上线前 review 返修后通过，210 项；第二轮 review 返修后通过，214 项，新增覆盖人工来源启用保留、国际榜单来源提升、普通 list 不覆盖榜单主来源、QQ ranked 识别国际榜单稿；本次 review 补丁后通过，217 项，新增覆盖国际榜单来源提升后触发 QQ 自动推送编排、英文外部马名索引识别、术语导入 upsert 命中跨语言别名时保留正式概念主原文；术语批量别名和 HKJC 上限口径返修后通过，219 项；本轮全球范围适配 review 返修后通过，224 项，新增覆盖英文外部马名真实写法保护、非日文外部别名候选查询、旧 QQ 群空地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分；本轮 review 返修后通过，227 项，新增覆盖翻译保护使用英文外部马名真实写法、发布校验不误报已保留真实写法、英文正式术语大小写不敏感匹配与替换；最终 review 补丁后通过，231 项，新增覆盖英文 P0 马匹自动化评分大小写不敏感命中、英文核心术语缺失大小写不敏感阻断、新增英文术语应用当前稿大小写不敏感替换、QQ 群非法地区配置回退日本旧行为；本轮术语生命周期补丁后完整 `stable` 测试通过 236 项，新增覆盖英文重复术语大小写不敏感拒绝、API 创建/更新同步 `TermAlias`、术语启停同步别名状态、候选合并大小写去重、同语言大小写变体导入 upsert 更新主原文，以及 AI 改写 prompt 使用英文实际命中别名；本次上线前返修后完整 `stable` 测试通过 241 项，新增覆盖术语导入 upsert 原文别名冲突预览/提交双重拒绝、`TDN France keyword` canonical 去重并保留法国地区信号、以及术语列表分页保留原文语言筛选。
  - `openspec validate expand-international-racing-coverage --strict`：通过。
  - `openspec validate --all`：通过，9 项。
  - `git diff --check`：通过。
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py makemigrations --check --dry-run`：通过，无额外迁移。
- 国际新闻源 dry-run 探测：
  - `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py probe_international_news_sources --limit 2 --json`：已执行，不写库。
  - 默认第一版矩阵成功解析两篇真实样本：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest`。
  - 榜单/排序入口结论：`Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 可抓并保留原站 rank；`HKJC Racing News`、`SCMP Racing`、`BHA`、`France Galop English News`、`TDN` 当前不按热门榜处理。
  - 旧候选源处理：`At The Races` 当前 403，`Paulick Report` 当前 403，`BloodHorse` 有反机器人/空样本风险；三者仍保留适配器供后续单独探测，但不进入第一版默认清单。
- 生产注意事项：
  - 本变更含数据库迁移，部署前必须确认没有正在运行的外部数据导入。
  - 国际新闻源默认关闭；生产启用前应先完成一次整体 review，再按地区逐个灰度启用，并用后台“测试抓取”或命令行小样本复验页面结构。
  - HKJC 正式网络导入仍应小批量、低频、单来源互斥，并从 `--payload-file --dry-run` 或单场小样本开始；如样本超过 `max_races / max_horses`，应先拆分 payload，而不是依赖程序截断。

## 2026-07-01 多地区新闻增量窗口实现与生产验证

- OpenSpec change：`increase-multiregion-news-volume`，已完成实现、归档、部署生产，并开启抓取 / 发布 / QQ 三条生产窗口。
- 已新增窗口运行模型：`ProductionWindow`、`WindowCandidateDecision`、`WindowTargetDecision`、`QuotaLedger`、`MajorRaceEvent`；`NewsSource` 增加生产批准、有效抓取间隔、backoff、人工暂停、错误分类、连续成功/失败和重要赛事升频字段。
- 已实现日常/重要赛事窗口服务：日常 15 分钟、重要赛事 5 分钟、最多 3 小时回看；重要赛事按地区当地时间录入，开跑前 3 小时到开跑后 1 小时升频，无开跑时间时按当地日期级窗口处理。
- 已实现新抓取窗口：只选择 `enabled=true`、`production_approved=true`、未暂停、未 backoff 的来源；连续失败 3 次自动降频，403/429/验证码类错误使用更保守 backoff，连续成功 3 次恢复默认 15 分钟。
- 已实现新发布窗口：每地区每窗口最多 5 篇；硬门禁不绕过；按内容指纹去重后评分排序；若没有高分稿但存在 45 分以上可发布稿，按保底发 1 篇并标记 `region_minimum_fill` 与 `disable_auto_qq`。
- 已实现新 QQ 窗口：只推高价值/榜单稿；每地区每窗口最多 3 篇；保底文章不自动 QQ；群小时和全站小时配额写入 `QuotaLedger`；0 推送原因写入 `WindowTargetDecision` 和窗口 payload。
- `2026-07-02` review 返修后，抓取和 QQ 补跑都只对最近一个缺失窗口执行真实动作，较早缺失窗口会记录为 `coalesced_to_latest_*_window` 的 `SKIPPED` 窗口，避免停机恢复后集中补抓或集中补推；已有 `SKIPPED/FAILED` QQ delivery 若重新进入发送，也必须先重新占用群小时和全站小时配额，`PENDING/RETRYING/SENDING/SENT` 或已达到最大尝试次数的 delivery 仍不会重复占配额。本轮进一步修正窗口真实状态口径：抓取窗口只在真实抓取任务完成后写 `SUCCEEDED/FAILED`，来源存在 lease 未过期的运行中抓取窗口时不再重复派发；HTTP 403/429 等状态码会进入来源错误分类；QQ 窗口在占配额和创建 delivery 前先检查 OneBot 在线状态，离线时直接在窗口记录 `onebot_offline` 并不派发消息。
- 已扩展 `audit_multiregion_news_production`：输出生产批准来源数、暂停/backoff 来源数、最近窗口结果、0 原因和配额打满记录；新增 `production_summary_task` 每日生成同一份摘要。
- 新窗口 Beat 已接入；生产显式开启后进入五地区常态窗口，不依赖旧 `auto_publish_batch_task` 提高频率。
- 新增管理入口：
  - `MajorRaceEvent`、`ProductionWindow`、`QuotaLedger` 已注册 Django Admin。
  - `NewsSourceAdmin` 显示生产批准、有效间隔、backoff、失败连续次数和错误分类。
  - `import_major_race_events --csv <path>` 支持重要赛事 CSV upsert，主键口径为 `normalized_name + year + racing_region + race_grade`。
- 已完成本地验证：
  - `DB_ENGINE=sqlite manage.py check`：通过。
  - `DB_ENGINE=sqlite manage.py makemigrations --check --dry-run`：通过。
  - 模型/窗口/来源/发布/QQ/重要赛事导入相关目标测试通过。
  - `2026-07-02` review 返修后，窗口相关目标测试 26 项通过，完整 `stable` 测试 399 项通过；`DB_ENGINE=sqlite manage.py check`、`openspec validate increase-multiregion-news-volume --strict`、`openspec validate --all` 和 `git diff --check` 均通过。
  - 临时 SQLite 迁移后 `audit_multiregion_news_production` 可输出有效 JSON。
- 生产运行验证：
  - `2026-07-02` 已部署到生产 `a122130`，容器 `web / worker / beat` 正常，`http://umafans.run/healthz/`、首页和抽检 `/news/<article_id>/` 均返回 `200`，Celery `active/reserved` 为空。
  - 生产配置确认：`MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true`，抓取 / 发布 / QQ 子开关均为 `true`；允许地区为日本、中国香港、英国、法国、美国；日常窗口 `15` 分钟，重要赛事窗口 `5` 分钟；发布每地区每窗口 `1-5` 篇，QQ 每地区每窗口最多 `3` 篇；当前没有地区处于重要赛事升频窗口。
  - `2026-07-02 04:18-10:18` 最近 6 小时窗口复核：发布窗口和 QQ 窗口各地区均产生 `24` 个日常窗口；抓取窗口统计为 `260` 个 `succeeded/completed`，`109` 个 `skipped/coalesced_to_latest_crawl_window`，符合恢复补跑只抓最近窗口的设计。
  - 最近 6 小时发布窗口中，美国 `04:30` 发布 `1` 篇，日本 `04:45` 发布 `2` 篇、`05:30` 发布 `4` 篇、`06:30 / 08:15 / 09:45` 各发布 `1` 篇；所有非零窗口均未超过每地区每窗口 `5` 篇，其余窗口均有 `no_ready_candidates` 原因。该时段 `published_to_web_at` 另包含香港 `1` 篇和美国 `3` 篇上线初始批次 / 旧自动发布文章，不属于本次新窗口发布。
  - 最近 6 小时 QQ 实际发送 `6` 条，目标均为 `UmaFans测试群(1026525240)`；美国 `3` 条，日本 `3` 条，未超过每地区每窗口 `3` 条。0 推送窗口记录为 `no_eligible_articles` 或 `already_sent`。
  - 来源复核显示 16 个生产批准来源最近抓取均为 `success`；`TDN France Galop 关键词英文新闻` 和 `TDN 美国新闻` 虽有已过期 `backoff_until` 残留，但最新 `10:00` 抓取窗口均为 `succeeded/completed`，当前不影响抓取。
  - Ops 通知开关已开启，最近 6 小时产生 `ops_summary` QQ 通知 `2` 条并发送成功；邮件 / 短信 / 微信渠道按 MVP 预留逻辑记录为 `skipped` 或未配置。
  - `2026-07-02 11:07` 继续复核最新 4 个发布窗口（`10:15 / 10:30 / 10:45 / 11:00`）：五地区均未发布新文章。日本有 `18` 条候选决策，全部为 `hard_gate_blocked`，主要来自翻译失败、人工审核要求和核心术语缺失；香港、英国、法国、美国没有进入发布候选的文章。最近 3 小时抓取显示非日本来源均成功运行但新增为 `0`、只命中重复旧稿；`TDN France Galop 关键词英文新闻`、`TDN 美国新闻` 曾在 `08:25-09:05` 超时或 `525`，`10:10` 已恢复成功且失败 streak 为 `0`。因此最新窗口 0 发布的主因是“日本候选被门禁/审核拦住，非日本暂无新稿”，不是生产调度或整体抓取失效。
  - `2026-07-02 15:10` 复核最近 2 小时自然窗口（`13:15` 至 `15:00`）：发布窗口和 QQ 窗口五地区均按 15 分钟节奏生成且状态为 `succeeded`，本时段网页发布 `0` 篇、QQ delivery `0` 条；发布 0 原因为 `no_ready_candidates`，QQ 0 原因为 `no_eligible_articles`。抓取窗口整体正常，最近 2 小时新入库 `8` 篇：日本 `5`、香港 `1`、英国 `2`、法国/美国 `0`；这些新稿当前为翻译失败或 `manual_review_required / pending_review`，未达到自动发布状态。16 个生产批准来源中 14 个最新成功，`TDN France Galop 关键词英文新闻` 与 `TDN 美国新闻` 在 `15:02` 出现 read timeout，`failure_streak=1`，属于同一上游站短时超时，不是整体抓取失效。候选决策当前能记录 `hard_gate_blocked`，但 payload 未展开具体 blocker 明细，后续可作为可观测性改进。
  - `2026-07-03 00:13` 复核今日窗口：因刚过零点，今日目前只有 `00:00` 一个自然窗口。五地区抓取 / 发布 / QQ 窗口均为 `succeeded`；抓取新入库 `1` 篇美国 TDN 新闻，其余来源均为重复旧稿；网页发布 `0` 篇，发布 0 原因为 `no_ready_candidates`；QQ delivery `0` 条，日本 / 美国为 `already_sent`，香港 / 英国 / 法国为 `no_eligible_articles`。16 个生产批准来源最新状态均为 `success`，前一日 TDN 超时已恢复。
  - `2026-07-03` 复核 `2026-07-02` 全日窗口：因多地区生产窗口于 `04:00` 后开始有账本，昨日实际覆盖 `04:00-23:45` 共 `80` 个 15 分钟窗口起点。发布窗口五地区各 `80` 个且全部 `succeeded`，窗口发布日本 `37` 篇、香港 `1` 篇、美国 `10` 篇，英国 / 法国为 `0`，无 failed/partial；0 发布主因仍为 `no_ready_candidates`，未发布候选多为 `hard_gate_blocked`。QQ 窗口五地区各 `80` 个且全部 `succeeded`，窗口派发日本 `3` 条、美国 `5` 条，均无 failed delivery；昨日所有 QQPushDelivery 记录按地区为日本 `15` 条、美国 `9` 条，状态均为 `sent`。抓取窗口无 `failed`，按窗口 payload 统计新增：日本 `79`、香港 `5`、英国 `11`、法国 `1`、美国 `28`，其中日本有 `7` 次榜单唤醒；`coalesced_to_latest_crawl_window` 为恢复/延迟时只补最近窗口的预期跳过。16 个生产批准来源在 `2026-07-03 00:13` 最新状态均为 `success`。
  - `2026-07-03` 地区归属错配只读审计：当时 `NewsArticle.racing_region` 与 `source_config.racing_region` 完全一致，`6598` 篇文章中 `0` 篇偏离“按新闻源地区”的现有逻辑。严格按有地区字段的实体（`ExternalHorseAlias` / 非空 `TermEntry.racing_region`）推断时，可覆盖 `462` 篇文章，且全部为日本文章；按用户提出的“第一种单地区逻辑”和“第二种多地区逻辑”均未发现结构化错配。但该结果只能作为下限：审计当时生产 `TermEntry` 的马/赛事/骑手地区全部为空（马 `1884`、赛事 `153`、骑手 `2`），`MajorRaceEvent` 为空，外部马名/赛事正式缓存只有日本和极少香港，没有英法美实体地区，因此系统无法可靠判断英文新闻中提到的日本 / 英国 / 法国 / 美国马、骑手或赛事。`2026-07-04` 后仅首批 `10` 条术语补写了地区，仍不足以支撑可信实体地区识别。补充关键词粗扫发现 `1213` 篇疑似跨地区提及，其中 `2026-06-30` 以后 `231` 篇、`2026-07-02` `60` 篇，但噪声较高，只能作为后续补实体地区识别的线索。

## 2026-07-02 榜单唤醒未发布文章实现

- OpenSpec change：`revive-ranked-news-for-publish`，当前已完成实现、归档和生产部署。生产服务器 `/opt/umanewsbot` 已部署到 `a774672`，部署前备份 `.env` 为 `.env.backup.ranked-revival-20260702_145529`，数据库备份为 `backups/db/pre-ranked-revival-20260702_145529.sql.gz`。
- 用户确认的产品规则：榜单二次命中不是直接发布按钮，而是“这篇文章值得重新认真看一次”的强信号。未发布文章从普通来源升级为榜单来源时，应允许低分忽略、价值不足转人工、待翻译或翻译失败文章被唤醒；翻译失败或待翻译文章需要自动重试翻译；翻译成功后重新评分，高价值来源信号参与自动发布判断。
- 边界：榜单唤醒不得绕过翻译成功、自动评分、发布校验、发布窗口配额和 QQ 限流；人工拒绝、撤回、已发布、高度重复 blocker、正文缺失、核心术语缺失等硬门禁仍不自动复活。
- 规格影响：修改 `automation-publish-gates` 和 `multiregion-news-production`，新增榜单唤醒、翻译重试、重新评分、按唤醒时间进入发布候选池以及窗口决策留痕要求。
- 代码实现：新增 `NewsArticle.ranked_revived_at` nullable/indexed 字段和迁移 `0019_newsarticle_ranked_revived_at.py`；新增 `revive_article_after_ranked_source_elevation()` 服务，记录 `decision_reason.ranked_revival`，区分 `translation_retry / rescore / blocked / already_retrying_translation`；netkeiba 榜单和国际榜单抓取在 `source_elevated=true` 时对未发布文章执行榜单唤醒，已发布文章继续沿用现有 QQ 补推；发布窗口候选查询支持 `first_seen_at` 或 `ranked_revived_at` 最近 3 小时，并在 `WindowCandidateDecision.payload` 写入榜单唤醒来源和时间。
- 测试进展：已按 TDD RED-GREEN 补充并跑通 `server/stable/tests.py` 中的榜单唤醒测试，覆盖 nullable/indexed `ranked_revived_at` 字段契约、低分 ignored 复活、价值不足人工状态复活、翻译失败/待翻译重试、人工终态/duplicate/blocker 不复活、重复榜单命中幂等、发布窗口按 `ranked_revived_at` 回看、以及 netkeiba/国际榜单抓取对未发布文章走唤醒而非 QQ 直推。
- 验证：`DB_ENGINE=sqlite manage.py check` 通过；`DB_ENGINE=sqlite manage.py makemigrations --check --dry-run` 通过；`DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true manage.py test stable --noinput` 通过，418 项；归档前 `openspec validate revive-ranked-news-for-publish --strict` 通过，归档后 `openspec validate --all` 通过，14 项；`git diff --check` 通过。
- 上线结果：迁移 `stable.0019_newsarticle_ranked_revived_at` 已应用；`manage.py check` 通过；生产模型确认 `ranked_revived_at null=True db_index=True`，榜单唤醒服务可 import；`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页和后台登录入口均返回 `200`；`web / worker / beat` 已重建并运行，Celery `active/reserved` 为空，近 80 行 `web / worker / beat` 日志未见 traceback/error。
- 上线后观察：继续观察发布窗口候选决策中的 `ranked_revival` payload、翻译重试数量、重新评分结果和 QQ 是否仍只推已发布/合格文章。回滚代码后 `ranked_revived_at` 字段可保留不用；如需彻底清理，后续单独做清理迁移。
