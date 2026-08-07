# 全球赛马数据库源 spike 记录

日期：2026-06-25 / 2026-06-26

关联 旧规格流程 change：`expand-international-racing-coverage`、`start-hkjc-data-import-and-global-spikes`、`connect-real-global-racing-databases`

## 边界

- 本文档先记录小样本技术 spike 结论和后续建议；`2026-06-26` 后续 旧规格流程 change `connect-real-global-racing-databases` 已将英法美从“只读 spike”升级为真实抓取目标。
- `start-hkjc-data-import-and-global-spikes` 阶段没有把 `Equibase`、英国 `Sporting Life + BHA` 或法国 `France Galop` 加入 Celery Beat、生产管理命令调度或正式导入队列。
- 截至英国第一版 dry-run，仍没有向正式 `ExternalRace / ExternalRaceEntry / ExternalRaceResult / ExternalHorse / ExternalHorseAlias` 表写入欧美数据。
- 后续正式导入欧美数据库必须在 `connect-real-global-racing-databases` 下执行，单独满足字段设计、限速、失败恢复、备份、dry-run、锁检查和用户确认门禁。

## 请求边界

- 本轮实现阶段未对欧美站点执行生产式爬取。
- 2026-06-25 spike 样本请求次数：`0` 次生产请求。
- 2026-06-26 read-only spike 样本请求次数：`6` 次公开页面 GET 请求，未写正式数据库。
- 2026-06-26 追加复核请求次数：`18` 次公开页面 GET 请求，未写正式数据库；主要用于复核英国、法国、美国的具体 racecard/result/horse/profile 入口信号。
- 2026-06-26 英国 Sporting Life 真实 dry-run smoke 请求次数：`3` 次公开页面 GET 请求，未写正式数据库；用于验证新 `import_uk_external_data` 管理命令和 parser/importer 链路。
- 2026-06-26 英国 Sporting Life 60 天窗口 smoke 请求次数：`7` 次公开页面 GET 请求，未写正式数据库；用于验证最近 2 个月日期窗口可以找到真实历史比赛。
- 2026-06-26 法国 France Galop 真实 dry-run smoke 请求次数：`3` 次公开页面 GET 请求，未写正式数据库；用于验证赛日、meeting、race detail 和马匹行内详情解析链路。
- 2026-06-26 美国数据库入口复核：Equibase 入口当前返回 `Pardon Our Interruption` 防护页，DRF entries/results 返回 JS 应用壳；Horse Racing Nation track-day 与 horse profile 页面可公开访问，已进入第一版真实 parser/importer dry-run。
- 2026-06-26 美国 Horse Racing Nation 真实 dry-run smoke 请求次数：`2` 次公开页面 GET 请求，未写正式数据库；用于验证 `entries-results/<track>/<date>`、同日赛场链接、runner/result table 和 horse profile 链路。
- 2026-06-26 英国 60 天窗口拆批 dry-run 请求次数：`28` 次公开页面 GET 请求，未写正式数据库；覆盖 `5` 场、`47` 条 entries/results、`46` 匹唯一马，补抓 `10` 个 horse profile。
- 2026-06-26 法国历史日期验证：`/en/racing/other-dates?date=2026-06-20` 和 `/en/racing/other-dates` 当前跳 Microsoft 登录，`/en/racing/calendar` 与 `/en/racing/results` 返回 404 样式页；France Galop 当前只证明 today 链路，最近 2 个月历史入口未通过。
- 2026-06-26 法国 Geny 历史公开源 60 天窗口小批 dry-run 请求次数：`11` 次公开页面 GET 请求，未写正式数据库；覆盖 `5` 场、`57` 条 entries、`52` 条 results、`54` 匹唯一马。`1` 秒间隔曾触发一次 `429`，已补 `stop_reason=rate_limited` 安全停止，后续建议至少 `10` 秒/请求。
- 2026-06-26 美国 HRN 拆批 dry-run 请求次数：`11` 次公开页面 GET 请求，未写正式数据库；同日发现 `16` 个 track 链接，本批实际使用 seed track-day `1` 个，覆盖 `5` 场、`49` 条 entries、`20` 条 results、`49` 匹唯一马，补抓 `10` 个 horse profile。
- 2026-06-27 英国 Sporting Life 60 天窗口续批 dry-run 请求次数：`33` 次公开页面 GET 请求，未写正式数据库；使用 `--skip-races 5` 覆盖下一批 `5` 场、`59` 条 entries/results、`57` 匹唯一马，补抓 `10` 个 horse profile。
- 2026-06-27 英国 Sporting Life 60 天窗口未过滤 plan-only 请求次数：`60` 次日期结果页 GET 请求，未写正式数据库；范围 `2026-04-28..2026-06-26`，枚举到 `47` 场比赛。该结果后续证明混入海外赛场，仅保留为历史证据，不作为当前英国覆盖口径。
- 2026-06-27 英国 Sporting Life 60 天窗口第 3 批 dry-run 请求次数：`47` 次公开页面 GET 请求，未写正式数据库；使用 `--skip-races 10` 覆盖第 3 批 `5` 场、`82` 条 entries/results、`82` 匹唯一马，补抓 `10` 个 horse profile。
- 2026-06-27 英国 Sporting Life 60 天窗口第 4 批 dry-run 请求次数：`75` 次公开页面 GET 请求，未写正式数据库；使用 `--skip-races 15` 和 `2` 秒/请求限速，覆盖第 4 批 `5` 场、`65` 条 entries/results、`65` 匹唯一马，补抓 `10` 个 horse profile。
- 2026-06-27 英国 Sporting Life 范围修正：已按 TDD 增加英国赛场 allowlist，排除 Sporting Life 日期结果页中的爱尔兰、美国、加拿大、法国等海外赛场；过滤后最近 60 天英国赛场为 `35` 场、`7` 批，早先 `47` 场 / `10` 批仅保留为未过滤历史证据。
- 2026-06-27 英国 Sporting Life 精确 `race_urls` 批次 dry-run 请求次数：`15 + 15 + 16` 次公开页面 GET 请求，未写正式数据库；覆盖剩余 `16` 场英国 racecard，使英国最近 60 天 racecard dry-run 达到 `35/35` 场；每批仍只补抓 `10` 个 horse profile，马匹 profile 全量补齐尚未完成。
- 2026-06-27 英国 Sporting Life 全量 profile proof 请求次数：`51 + 64` 次公开页面 GET 请求，未写正式数据库；两组精确 URL proof 分别覆盖 `5` 场 / `46` 匹唯一马和 `5` 场 / `59` 匹唯一马，且 `horse_profiles_fetched` 等于唯一马数量、`completion.is_complete=true`，证明英国 `racecard -> runners/results -> 所有涉及 horse profile` 闭环可用。按用户新边界，本会话不继续英国全量大量爬取。
- 2026-06-27 英国 Sporting Life 本地 commit 能力已按 TDD 补齐证据：命令默认仍 dry-run，显式 `--commit` 才写入；mock/fixture 重复执行完整精确 `race_urls` 批次可幂等写入 `External*` 表、记录成功 `ExternalDataImportRun` 并释放单来源锁；若 profile 被 `--limit-horses` 截断并返回 `completion.is_complete=false`，commit 会被拒绝。该证明不等于生产真实网络 commit，也不等于最近 2 个月完整大量爬取完成。
- 2026-06-27 美国 HRN 60 天窗口 date-range dry-run 请求次数：`12` 次公开页面 GET 请求，未写正式数据库；范围 `2026-04-27..2026-06-25`，首请求为日期索引 `/entries-results/2026-04-27`，覆盖 `5` 场、`37` 条 entries、`20` 条 results、`37` 匹唯一马，补抓 `10` 个 horse profile。
- 2026-06-27 法国 Geny 与美国 HRN 本地 commit 能力已按 TDD 补齐：命令默认仍 dry-run，显式 `--commit` 才写入；mock/fixture 重复执行完整 payload 可幂等写入 `External*` 表、记录成功 `ExternalDataImportRun` 并释放单来源锁。后续又补齐推荐精确批次入口的 commit 证据：法国 `--partants-urls`、美国 `--race-ids` 均可幂等写入；若 `limit_horses`、`limit_races`、`limit_tracks` 或 `rate_limited` 造成 `completion.is_complete=false`，commit 会被拒绝。该证明不等于生产真实网络 commit，也不等于最近 2 个月完整大量爬取完成。
- 2026-06-27 法国 Geny 批次控制能力已按 TDD 补齐：新增 `--plan-only --batch-size` 生成 race 批次计划；既有 `--skip-races` 可按 plan offset 续跑。plan-only 本地测试证明只请求日期页，不请求 partants/results，不写正式表。本轮未执行新的真实网络大量抓取。
- 2026-06-27 法国 Geny 独立 horse profile 入口已用 `1` 次低频公开页面 GET 探针确认，样本为 `https://www.geny.com/fr/cheval/2814630/course/1662144`，页面可解析马名、性别年龄、毛色、父母系、练马师、马主、近走和奖金；TDD 已补 `--limit-horses` 限量 profile 抓取。默认不额外请求 horse profile，只有显式传 `--limit-horses` 时才做 profile proof。
- 2026-06-27 法国 Geny 精确批次能力已按 TDD 补齐：`import_france_external_data --source geny --partants-urls URL1,...` 可按 plan-only 输出直接请求目标 partants/results，并按需限量抓 horse profile，不再重复扫描日期页；本地测试证明请求顺序为 `partants -> results -> horse`，仍默认 dry-run、不写正式表。
- 2026-06-27 美国 HRN 批次控制能力已按 TDD 补齐：新增 `--plan-only --batch-size` 生成 race 批次计划，新增 `--skip-races` 支持 date-range 续跑；本地测试证明 plan-only 不抓 horse profile、不写表，skip-races 可从窗口中第二场继续。本轮未执行新的真实网络大量抓取。
- 2026-06-27 美国 HRN 精确批次能力已按 TDD 补齐：`import_us_external_data --race-ids HRN_track_YYYY-MM-DD_N,...` 可按 plan-only 输出直接请求目标 track-day 并只选中目标 race，不再重复扫描日期索引；本地测试证明请求顺序为 `track_day -> horse`，仍默认 dry-run、不写正式表。
- 2026-06-27 继续复核三地精确批次入口，请求合计 `7` 次公开页面 GET，均为 dry-run、未写正式数据库：
  - 英国 Sporting Life `--race-urls ...SL924407... --limit-horses 1` 请求 `2` 次，racecard 与 horse profile 均返回 `200`，覆盖 `1` 场、`7` 条 entries/results、`7` 匹马，`completion.is_complete=false`、`stop_reason=limit_horses_reached`。
  - 法国 Geny `--partants-urls ...GENY1662144... --limit-horses 1` 请求 `3` 次，partants、results 与 horse profile 均返回 `200`，覆盖 `1` 场、`6` 条 entries/results、`6` 匹马，`completion.is_complete=false`、`stop_reason=limit_horses_reached`。
  - 美国 HRN `--race-ids HRN_churchill-downs_2026-06-25_1 --limit-horses 1` 请求 `2` 次，track-day 与 horse profile 均返回 `200`，覆盖 `1` 场、`12` 条 entries、`4` 条 results、`12` 匹马，`completion.is_complete=false`、`stop_reason=limit_horses_reached`。
  这次复核只证明精确批次入口仍可访问和 parser 仍可解析；因为显式限制 profile 数量，结果被正确标记为 incomplete，不得进入 commit 候选。三份 JSON 已落盘到 `runtime/global_racing_import/proof-20260627/uk/uk-race-url-proof.json`、`runtime/global_racing_import/proof-20260627/france-geny/france-geny-partants-proof.json` 和 `runtime/global_racing_import/proof-20260627/us-hrn/us-hrn-race-id-proof.json`。
- 2026-06-27 追加 proof-only 离线审计：`audit_global_racing_import_outputs --input-dir runtime/global_racing_import/proof-20260627 --pattern "*/*.json" --proof-only --expected-sources sporting_life,geny_france,horse_racing_nation --expected-request-types 'sporting_life:race|horse,geny_france:partants|results|horse,horse_racing_nation:track_day|horse' --fail-on-incomplete` 已通过，输出 `runtime/global_racing_import/proof-20260627-audit.json`；结果为 `handoff_decision=proof_only_ready_not_commit_candidate`、`handoff_decision_reasons=["proof-only audit passed","commit audit still blocked","complete 60-day crawl and commit gate remain required"]`、`proof_ready=true`、`missing_expected_sources=[]`、`missing_proof_request_types=[]`、`proof_file_count=3`、`proof_request_count=7`、`proof_successful_response_count=7`、`proof_blocking_reasons=[]`，同时 `commit_candidate_ready=false`，明确该 proof 不进入生产 commit 候选。审计 JSON 现包含 `audit_parameters`，并在 `proof_sources` 中按来源汇总 `files`、`file_count`、`complete_file_count`、`incomplete_file_count`、`stop_reasons`、`request_count`、`successful_response_count`、`coverage_totals` 和 `request_types`，便于后续完整大量抓取会话快速确认每个来源的接入证明面并回溯到原始 proof JSON；当前三地 proof 均为 `limit_horses_reached` 的受控限量停止。
- 限速建议：后续完整大量爬取应新开会话，从 `10-30 秒/请求` 起步，先单日期、单比赛、单马 profile 小样本，不做一次性历史全量。
- 样本解析保存位置：仅允许仓库文档、隔离 fixture 或临时文件，不允许写正式外部数据表。

## 2026-06-26 英国 Sporting Life 真实抓取 smoke

执行命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=10 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 1 --end-date 2026-06-26 --limit-races 1 --limit-horses 1 --allow-network
```

结果：

- 请求 `3` 次：日期结果页、单场 racecard、单马 profile。
- 样本 URL：`https://www.sportinglife.com/racing/results/2026-06-26`、`/racing/racecards/2026-06-26/cartmel/racecard/924416/holker-homes-handicap-chase`、`/racing/profiles/horse/1048694`。
- 覆盖统计：`coverage_stats={"races":1,"entries":8,"results":8,"horses":8}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，因为本次只补抓 1 匹马 profile。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。

## 2026-06-26 英国 Sporting Life 60 天窗口拆批 dry-run

执行命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=160 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --limit-races 5 --limit-horses 10 --allow-network
```

结果：

- 范围：`2026-04-28..2026-06-26`。
- 请求 `28` 次：`13` 个日期结果页、`5` 个 racecard、`10` 个 horse profile。
- 覆盖统计：`coverage_stats={"races":5,"entries":47,"results":47,"horses":46}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`unique_horses_found=46`，`horse_profiles_fetched=10`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：该批证明英国日期窗口、racecard 和 horse profile 入口可用；后续已由赛场 allowlist、精确 URL 批次和 proof 边界取代，本会话不据此继续全量拆批或生产 commit。

续批 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=180 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --skip-races 5 --limit-races 5 --limit-horses 10 --allow-network
```

结果：

- 请求 `33` 次：`23` 个日期结果页、`5` 个 racecard、`10` 个 horse profile。
- 覆盖统计：`coverage_stats={"races":5,"entries":59,"results":59,"horses":57}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`skip_races=5`，`race_links_found=10`，`race_links_selected=5`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：英国已具备 `skip-races` 续批能力；该能力保留给后续完整大量爬取会话，本会话不继续扩大抓取范围。

60 天窗口 plan-only：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=120 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --plan-only --batch-size 5 --allow-network
```

结果：

- 只请求日期结果页，不请求 racecard 或 horse profile。
- 范围：`2026-04-28..2026-06-26`。
- 请求 `60` 次日期结果页。
- 覆盖统计：`coverage_stats={"races":47,"entries":0,"results":0,"horses":0}`。
- 完整度：`completion.is_complete=true`，`stop_reason=plan_only`，`race_links_found=47`，`batch_size=5`，`batches=10`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：该未过滤 plan-only 仅保留为历史记录；后续已由英国赛场 allowlist、`race_urls` 精确批次和 proof 边界取代。

第 3 批 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=180 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --skip-races 10 --limit-races 5 --limit-horses 10 --allow-network
```

结果：

- 请求 `47` 次：`32` 个日期结果页、`5` 个 racecard、`10` 个 horse profile。
- 选中比赛：`SL918557`、`SL918559`、`SL918561`、`SL919451`、`SL919452`。
- 覆盖统计：`coverage_stats={"races":5,"entries":82,"results":82,"horses":82}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`skip_races=10`，`race_links_found=15`，`race_links_selected=5`，`horse_profiles_fetched=10`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：该 `3/10` 口径为未过滤海外赛场前的历史记录；后续已由英国赛场 allowlist、`race_urls` 精确批次和 proof 边界取代。

第 4 批 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=2 UK_IMPORT_MAX_REQUESTS_PER_RUN=200 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --skip-races 15 --limit-races 5 --limit-horses 10 --allow-network
```

结果：

- 请求 `75` 次：`60` 个日期结果页、`5` 个 racecard、`10` 个 horse profile；本批使用 `2` 秒/请求限速。
- 选中比赛：`SL919453`、`SL919454`、`SL919455`、`SL919456`、`SL924387`。
- 覆盖统计：`coverage_stats={"races":5,"entries":65,"results":65,"horses":65}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`skip_races=15`，`race_links_found=20`，`race_links_selected=5`，`horse_profiles_fetched=10`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：该 `4/10` 口径为未过滤海外赛场前的历史记录；后续已由英国赛场 allowlist、`race_urls` 精确批次和 proof 边界取代。

范围修正与精确 URL 批次：

后续复核发现 Sporting Life 日期结果页会混入爱尔兰、美国、加拿大、法国等海外赛场。英国 importer 已按 TDD 增加英国赛场 allowlist，plan-only batch 输出 `race_urls`，并新增 `--race-urls` 精确批次入口。

过滤后 plan-only：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=120 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --plan-only --batch-size 5 --allow-network
```

结果：

- 请求 `60` 个日期结果页。
- 过滤海外赛场后，`coverage_stats={"races":35,"entries":0,"results":0,"horses":0}`。
- `completion.is_complete=true`，`stop_reason=plan_only`，`race_links_found=35`，`batch_size=5`，`batches=7`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。

精确 URL 批次结果：

- `SL924388,SL924389,SL924390,SL924391,SL924393`：请求 `15` 次，覆盖 `5` 场、`27` 条 entries/results、`27` 匹唯一马，补抓 `10` 个 horse profile。
- `SL924394,SL924395,SL924396,SL924397,SL924418`：请求 `15` 次，覆盖 `5` 场、`37` 条 entries/results、`37` 匹唯一马，补抓 `10` 个 horse profile。
- `SL925053,SL925054,SL925055,SL925056,SL925057,SL925058`：请求 `16` 次，覆盖 `6` 场、`73` 条 entries/results、`73` 匹唯一马，补抓 `10` 个 horse profile。
- 当前判断：英国最近 60 天 racecard dry-run 已覆盖 `35/35` 场。按用户新 proof 边界，本会话不继续补齐全量 profile；生产 commit 仍不讨论，完整大量爬取后续另开会话。

按 2026-06-27 用户新边界，本会话只需证明英国、法国、美国真实接入可用；完整大量爬取后续单独新开会话。英国随后完成两组精确 URL 全量 profile proof：

- `SL915095,SL915096,SL916196,SL916199,SL916198`：请求 `51` 次，覆盖 `5` 场、`47` 条 entries/results、`46` 匹唯一马，`horse_profiles_fetched=46`，`completion.is_complete=true`。
- `SL916197,SL916201,SL916202,SL916200,SL918557`：请求 `64` 次，覆盖 `5` 场、`61` 条 entries/results、`59` 匹唯一马，`horse_profiles_fetched=59`，`completion.is_complete=true`。
- 当前判断：英国真实接入 proof 已足够证明 `racecard -> runners/results -> 所有涉及 horse profile` 闭环可用；本会话不继续英国全量 profile 抓取，也不执行生产 commit。

## 2026-06-26 法国 France Galop 真实抓取 smoke

执行命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=1 FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=20 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_france_external_data --race-date 2026-06-26 --limit-races 1 --allow-network
```

结果：

- 请求 `3` 次：`/en/racing/today`、meeting `UUI1MEN3bUdDZ09lcDluYm41NGxndz09`、race detail `FG2026P-Mk5FdWZLYVplaEljbmRZckU4bEo3UT09`。
- 覆盖统计：`coverage_stats={"races":1,"entries":8,"results":8,"horses":8}`。
- 入口特征：race detail 表格直接包含马匹链接、马名文本、性别/年龄、父母系、owner、trainer、jockey、weight、finish position 和 margin。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_races_reached`，`meetings_found=4`。
- 马匹详情边界：独立 `/en/horse/...` profile 页面当前跳转到 Microsoft 登录；第一版 `horse_profile_source="race_detail_rows"`，只把 race detail 行内可用字段视为马匹详情。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。

历史日期验证：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=1 FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=40 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_france_external_data --race-date 2026-06-20 --limit-races 2 --allow-network
```

结果：

- 请求 `1` 次，最终 URL 跳转到 `francegalopext.ciamlogin.com/.../oauth2/v2.0/authorize`。
- 覆盖统计：`coverage_stats={"races":0,"entries":0,"results":0,"horses":0}`。
- 追加公开页面探针显示 `/en/racing/other-dates` 和 `/en/racing` 当前跳 Microsoft 登录，`/en/racing/calendar` 与 `/en/racing/results` 返回 404 样式页。
- 当前判断：France Galop first version 可抓 today race detail，但官方历史入口未通过；本会话的法国 proof 边界后续由 Geny 60 天窗口小批 dry-run 补足，完整大量爬取仍需后续新会话处理。

## 2026-06-26 法国 Geny 历史公开源 60 天窗口拆批 dry-run

France Galop 官方历史入口受登录门禁影响后，本轮新增 Geny 作为法国历史公开源候选。Geny 日期页会同时列出法国和海外 PMU 会议；parser 当前排除显式海外括号会议，例如 `Happy Valley (Hong Kong)`，并保留法国会议。普通 Geny dry-run 默认不单独请求 horse profile，马匹详情来自 partants/results 行内字段和 profile URL；需要证明独立 profile 时必须显式传 `--limit-horses`，避免默认路径扩大请求量。

执行命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true FRANCE_IMPORT_REQUEST_INTERVAL_SECONDS=10 FRANCE_IMPORT_MAX_REQUESTS_PER_RUN=80 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_france_external_data --source geny --recent-days 60 --end-date 2026-06-26 --limit-races 5 --allow-network
```

结果：

- 范围：`2026-04-28..2026-06-26`。
- 请求 `11` 次：Geny 日期页 `2026-04-28`、`5` 个 partants 页、`5` 个 results 页。
- 覆盖统计：`coverage_stats={"races":5,"entries":57,"results":52,"horses":54}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_races_reached`，`race_links_found=38`，`race_links_selected=5`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 风险与防护：`1` 秒间隔曾触发 `429`，已按 TDD 新增 `test_geny_france_dry_run_stops_safely_on_rate_limit_without_writing`，429 时返回 partial dry-run 证据并保持不写库。后续 Geny 拆批建议至少 `10` 秒/请求，不并发运行。
- 独立 profile proof：追加 `1` 次低频公开页面探针确认 Geny horse profile 可访问，样本 `Zakharova` 页面可解析 `horse_id=2814630`、`sex=Femelle`、`age=4`、`color=bai`、`sire=Zelzal`、`dam=Diva Cattiva`、`trainer/owner=François Belmont`、近走和奖金；本地 TDD 已覆盖 `--limit-horses 1` 时请求顺序为 `race_date -> partants -> results -> horse` 且不写表。
- 当前判断：法国历史公开源已有可拆批真实 dry-run 候选，Geny 小批次已证明最近窗口、出马、赛果和行内马匹详情可解析；显式限量 profile proof 也已证明独立马匹详情入口可用。随后已补本地 `--commit` 幂等写入测试、`--plan-only --batch-size` 批次计划能力和 `--partants-urls` 精确批次入口；按用户新 proof 边界，本会话不继续法国完整两个月大量爬取，也不进入生产真实网络 commit。

## 2026-06-26 美国 Horse Racing Nation 真实抓取 smoke

执行命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true US_IMPORT_REQUEST_INTERVAL_SECONDS=1 US_IMPORT_MAX_REQUESTS_PER_RUN=20 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_us_external_data --race-date 2026-06-25 --seed-track churchill-downs --limit-tracks 1 --limit-races 1 --limit-horses 1 --allow-network
```

结果：

- 请求 `2` 次：HRN track-day `https://entries.horseracingnation.com/entries-results/churchill-downs/2026-06-25` 和 horse profile `https://www.horseracingnation.com/horse/Crystal_Frost`。
- 覆盖统计：`coverage_stats={"races":1,"entries":12,"results":4,"horses":12}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`track_days_found=1`，`horse_profiles_fetched=1`，因为本次只补抓 1 匹马 profile。
- 入口特征：track-day 页面包含同日赛场链接、每场 `Race #` 区块、runner table、payout/results table 和 horse profile 链接；horse profile 页面包含年龄、性别、血统、owner、trainer、bred 和赛绩摘要。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。

拆批 dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true US_IMPORT_REQUEST_INTERVAL_SECONDS=1 US_IMPORT_MAX_REQUESTS_PER_RUN=80 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_us_external_data --race-date 2026-06-25 --seed-track churchill-downs --limit-tracks 3 --limit-races 5 --limit-horses 10 --allow-network
```

结果：

- 请求 `11` 次：`1` 个 HRN track-day 和 `10` 个 horse profile。
- 覆盖统计：`coverage_stats={"races":5,"entries":49,"results":20,"horses":49}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`track_days_found=16`，`track_days_fetched=1`，`horse_profiles_fetched=10`。
- 审计修复：本轮 TDD 新增 `test_us_hrn_dry_run_reports_only_actual_track_days_fetched`，确保 `track_days_fetched` 只统计实际使用/请求过的 track-day 页面，避免把计划中的 track links 误报为已抓取。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：美国 HRN 可按日期、track/race/horse 上限拆批推进；本批已证明 track-day、runner/result table 和 horse profile 入口可用。最近 2 个月完整覆盖策略留给后续大量爬取会话。

60 天窗口 date-range dry-run：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true US_IMPORT_REQUEST_INTERVAL_SECONDS=1 US_IMPORT_MAX_REQUESTS_PER_RUN=80 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_us_external_data --recent-days 60 --end-date 2026-06-25 --seed-track churchill-downs --limit-tracks 3 --limit-races 5 --limit-horses 10 --allow-network
```

结果：

- 范围：`2026-04-27..2026-06-25`。
- 请求 `12` 次：`2` 个 HRN 日期/track-day 页面和 `10` 个 horse profile；首请求为日期索引 `https://entries.horseracingnation.com/entries-results/2026-04-27`。
- 覆盖统计：`coverage_stats={"races":5,"entries":37,"results":20,"horses":37}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，`race_dates_fetched=1`，`track_days_found=6`，`track_days_fetched=1`，`horse_profiles_fetched=10`。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。
- 当前判断：美国已从单日 smoke 升级到 60 天窗口 date-range dry-run；日期范围模式优先用 HRN 日期索引枚举同日 track-day 链接。随后已补本地 `--commit` 幂等写入测试、`--plan-only --batch-size`、`--skip-races` 和 `--race-ids` 精确批次控制能力；按用户新 proof 边界，本会话不继续补完整日期/track 覆盖，也不进入生产真实网络 commit。

## 2026-06-26 美国入口复核更新

复核结论：

- `Equibase`：`/static/entry/index.html`、`/static/chart/summary/index.html`、`/static/chart/pdf/index.html` 和具体 horse profile URL 当前都返回约 `6058` 字节的 `Pardon Our Interruption` 防护页；不应尝试绕过风控。
- `DRF`：`/race-results` 和 `/race-entries` 返回 `200`，但 HTML 主要是 JS 应用壳，静态 HTML 中没有直接 race/horse 数据，需要另找数据 API 才能进入 importer TDD。
- `Horse Racing Nation`：`entries.horseracingnation.com/entries-results/<track>/<date>`、具体 race 页面和 horse profile 页面返回 `200`。Track-day 页包含同日赛场链接、runner/horse/trainer/jockey/odds、payout/result 信号；horse profile 页面公开年龄、性别、血统、owner、trainer、bred 和赛绩摘要。后续完整大量爬取仍需单独设计 seed track / date index 覆盖策略。

当前判断：美国不再以 Equibase 直接 HTML 作为第一候选；第一版真实抓取以 Horse Racing Nation 做受限 importer dry-run。按本会话 proof 边界，不执行美国生产 commit；后续完整大量爬取和生产写入必须另走备份、dry-run 汇总、锁检查和用户确认门禁。
- 当前判断：英国 Sporting Life 已完成真实 parser/importer proof；后续完整大量爬取和生产 commit 确认点留给新会话。

60 天窗口 smoke：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true UK_IMPORT_REQUEST_INTERVAL_SECONDS=1 UK_IMPORT_MAX_REQUESTS_PER_RUN=120 /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py import_uk_external_data --recent-days 60 --end-date 2026-06-26 --limit-races 1 --limit-horses 1 --allow-network
```

结果：

- 范围：`2026-04-28..2026-06-26`。
- 请求 `7` 次：先扫 `2026-04-28` 至 `2026-05-02` 日期结果页，再请求 Goodwood `SL915095` racecard 和 horse profile `1184980`。
- 覆盖统计：`coverage_stats={"races":1,"entries":13,"results":13,"horses":13}`。
- 完整度：`completion.is_complete=false`，`stop_reason=limit_horses_reached`，因为本次只补抓 1 匹马 profile。
- 写库边界：`would_write_formal_tables=false`，未创建 `External*` 正式表记录。

## 2026-06-26 英法美数据库源追加复核

执行方式：

- 请求方式：`requests.get`
- User-Agent：`umanews-spike/0.2`
- 请求总数：`18`
- 请求间隔：约 `1` 秒
- 数据库写入：无

### 请求证据

| 地区 | 样本 URL | 状态 | Content-Type | 长度 | 观察信号 |
| --- | --- | ---: | --- | ---: | --- |
| 美国 | `https://www.equibase.com/static/entry/index.html` | 200 | `text/html` | 613095 | entries/results/racecard/horse/profile/calendar/rating/breeding |
| 美国 | `https://www.equibase.com/static/chart/pdf/index.html` | 200 | `text/html` | 131968 | charts/PDF 索引可访问，含 results/horse/profile/trainer 等信号 |
| 美国 | `https://www.equibase.com/profiles/Results.cfm?rbt=TB&refno=11107564&registry=T&type=Horse` | 200 | `text/html;charset=UTF-8` | 126580 | horse profile 可访问，页面内含 Horse Profile、Entries、Results、Calendar 链接和相关 profile 参数 |
| 英国 | `https://www.sportinglife.com/racing/racecards` | 200 | `text/html; charset=utf-8` | 101995 | racecards/entries/results/horse/runner/trainer/jockey |
| 英国 | `https://www.sportinglife.com/racing/fast-results` | 200 | `text/html; charset=utf-8` | 144003 | 结果页返回具体 racecard 链接和 horse profile 链接，例如 `/racing/racecards/2026-06-26/yarmouth/racecard/924406/...`、`/racing/profiles/horse/1212905` |
| 英国 | `https://www.sportinglife.com/racing/profiles/horse/328651` | 200 | `text/html; charset=utf-8` | 92727 | horse profile 页面可访问，标题为 `Race Record & Horse Form` |
| 英国 | `https://www.britishhorseracing.com/racing/horses/` | 200 | `text/html; charset=UTF-8` | 78411 | BHA horses 页面可访问，暴露 `/racing/horses/feed/`、`/racing/horses/racehorse-search-results/` 等链接 |
| 英国 | `https://www.britishhorseracing.com/racing/fixtures/upcoming/` | 200 | `text/html; charset=UTF-8` | 85972 | BHA fixtures 页面可访问，暴露 entries/racecards/view-races/feed 等链接 |
| 法国 | `https://www.france-galop.com/en` | 200 | `text/html; charset=UTF-8` | 35782 | entries/results/horse/calendar/rating/breeding/trainer/jockey 浅层关键词信号 |
| 法国 | `https://www.france-galop.com/en/understand-the-races/find-out-more` | 200 | `text/html; charset=UTF-8` | 31487 | entries/results/horse/calendar/rating/trainer/jockey 浅层关键词信号 |
| 法国 | `https://www.france-galop.com/en/content/france-galop-launches-mobile-app-transform-horse-racing-experience` | 200 | `text/html; charset=UTF-8` | 37302 | 官方 app 说明页提到 calendar、race card、results，但网页结构化查询参数仍未定位 |

### 追加复核结论

| 地区 | entries/racecards | results/charts | horse profile | 官方补字段 | 当前判断 |
| --- | --- | --- | --- | --- | --- |
| 美国 `Equibase` | 有公开 HTML 索引信号 | chart/PDF 索引可访问 | 具体 horse profile 参数可访问 | Equibase 自身即主候选 | 仍为 `needs_more_spike`；下一步应做单日 entries + 单马 profile + chart/PDF fixture |
| 英国 `Sporting Life + BHA` | Sporting Life racecards 可访问，fast-results 暴露具体 racecard URL | Sporting Life fast-results 有具体 racecard/runner/profile 链接 | Sporting Life horse profile 可访问 | BHA horses/fixtures 200 且暴露 feed/search/racecards 链接 | 英国优先级最高；Sporting Life 可作为正式导入主候选，BHA 作为官方补字段候选，仍需 fixture parser 后再 `ready_for_formal_import` |
| 法国 `France Galop` | 首页和说明页有浅层 race card/calendar 信号 | app/说明页声明 results 能力 | 浅层 horse/profile 关键词信号 | France Galop 官方性强 | 仍为 `needs_more_spike`；必须先定位真实结构化查询参数或可静态解析页面 |

本次追加复核后，英国的可行性最高，美国入口更具体但 PDF/chart 解析成本仍高，法国仍停留在官方页面浅层信号阶段。

## 2026-06-26 英法美数据库源 read-only spike

执行方式：

- 请求方式：`requests.get`
- User-Agent：`umanews-spike/0.1`
- 请求总数：`6`
- 数据库写入：无
- 正式表隔离检查：通过

正式表计数检查使用隔离 SQLite `/tmp/umanews-hkjc-apply.sqlite3`：

| 表 | before | after |
| --- | ---: | ---: |
| `ExternalRace` | 1 | 1 |
| `ExternalRaceEntry` | 2 | 2 |
| `ExternalRaceResult` | 2 | 2 |
| `ExternalHorse` | 2 | 2 |
| `ExternalHorseAlias` | 4 | 4 |

### 请求证据

| 地区 | 样本 URL | 状态 | Content-Type | 长度 | 观察信号 |
| --- | --- | ---: | --- | ---: | --- |
| 美国 | `https://www.equibase.com/static/entry/index.html` | 200 | `text/html` | 623259 | entries/results 有信号，horse profile 未确认 |
| 美国 | `https://www.equibase.com/static/foreign/entry/index.html?SAP=TN` | 200 | `text/html` | 262986 | entries/results 有信号，horse profile 未确认 |
| 英国 | `https://www.sportinglife.com/racing/racecards` | 200 | `text/html; charset=utf-8` | 421762 | racecards/results/horse profile 有信号 |
| 英国 | `https://www.sportinglife.com/racing/fast-results` | 200 | `text/html; charset=utf-8` | 366794 | racecards/results/horse profile 有信号 |
| 法国 | `https://www.france-galop.com/en` | 200 | `text/html; charset=UTF-8` | 34900 | calendar/results/horse profile/runners 有浅层信号 |
| 法国 | `https://www.france-galop.com/en/understand-the-races/find-out-more` | 200 | `text/html; charset=UTF-8` | 31487 | calendar/results/horse profile/runners 有浅层信号 |

未观察到 `access denied`、`forbidden`、`captcha` 或 `Pardon Our Interruption` 等明显访问阻断信号。

### 字段覆盖矩阵

| 地区 | entries/racecards | results | horse profile | 主要缺口 | 准入状态 |
| --- | --- | --- | --- | --- | --- |
| 美国 `Equibase` | 有信号 | 有信号 | 未确认 | horse profile 与 chart/PDF 解析未做；需要更具体的单赛日、单马 URL | `needs_more_spike` |
| 英国 `Sporting Life + BHA` | Sporting Life 有信号 | Sporting Life 有信号 | Sporting Life 有信号 | BHA 官方搜索/监管入口本轮未复验；需要拆分商业页面与官方补字段 | `needs_more_spike` |
| 法国 `France Galop` | 有浅层信号 | 有浅层信号 | 有浅层信号 | 当前只是英文站浅层页面信号；正式结构化赛程/报名/出马/赛果查询参数未确认 | `needs_more_spike` |

### 本轮结论

- 美国 `Equibase`：页面可访问，但 horse profile 和 chart/PDF 仍是关键风险，不建议直接正式导入。
- 英国 `Sporting Life + BHA`：Sporting Life 页面可访问，优先级最高；BHA 作为官方补字段入口需要单独复验。
- 法国 `France Galop`：页面可访问，但必须继续定位结构化查询入口；不进入法语新闻正文链路。
- 三个地区均未写入正式 `External*` 表或 `ExternalHorseAlias`，也未加入 Celery Beat、生产命令队列或正式导入队列。

## 2026-06-25 国际新闻源真实探测

执行命令：

```bash
DB_ENGINE=sqlite python server/manage.py probe_international_news_sources --limit 2 --json
```

该命令只做 dry-run，不写入 `NewsArticle`，每个来源最多解析 2 篇真实新闻详情。

探测结论：

- `Sponichi`：成功解析 2 篇真实新闻，正文长度约 `4979 / 4990`，可作为日本二期新闻源候选。
- `HKJC Racing News`：改用页面公开脚本暴露的 banner API 后，成功解析 2 篇真实新闻，正文长度约 `4261 / 2624`。
- `SCMP Racing`：成功解析 2 篇真实新闻，正文长度约 `3885 / 2993`。
- `BHA`：成功解析 2 篇真实 press release，正文长度约 `1502 / 1270`；需要使用正文容器专用选择器，避免侧栏标题干扰。
- `Sporting Life Racing`：成功解析 2 篇真实新闻，正文长度约 `4883 / 5439`。
- `At The Races`：当前从本地环境请求 `https://www.attheraces.com/news` 返回 `403 Forbidden`，法国英文新闻源上线前需要换入口、放慢探测或改为备用英文来源。
- `Paulick Report`：当前从本地环境请求 `https://paulickreport.com/news/` 返回 `403 Forbidden`，上线前需要确认访问限制或替换来源。
- `BloodHorse`：曾成功解析 2 篇真实新闻；随后同入口返回 `Pardon Our Interruption` 反机器人页，说明该站存在会话/风控波动，不建议未复验前自动启用。

## 美国：Equibase

样本入口建议：

- Entries：`https://www.equibase.com/static/entry/`
- Results：`https://www.equibase.com/static/chart/`
- Charts：`https://www.equibase.com/static/chart/pdf/`
- Horse profile/search：`https://www.equibase.com/profiles/`

字段覆盖预期：

- 比赛：日期、马场、场次、比赛名、等级/条件、距离、场地、跑道、天气/Going、奖金。
- 出马：马名、外部 horse profile、骑师、练马师、档位、负磅、装备、赔率或 morning line。
- 赛果/charts：名次、完成时间、距离差、赔率、分段、沿途位置、骑师、练马师。
- 马匹：英文名、出生年份、性别、父母血统、马主、练马师、近走成绩。

风险：

- 访问限制和反爬风险最高；PDF chart 解析成本较高。
- 页面入口和参数可能随赛日、马场代码变化，需要先建立小样本 URL 矩阵。
- 不建议一期直接正式导入全量历史数据。

建议：

- 后续正式实现前先做 `dry-run + fixture` spike，优先解析单日 entries/results 和 1-3 个 horse profile。
- 如果 PDF chart 是字段最完整来源，应独立评估 PDF 解析稳定性。

## 英国：Sporting Life + BHA

样本入口建议：

- Racecards：`https://www.sportinglife.com/racing/racecards`
- Results：`https://www.sportinglife.com/racing/results`
- Horse profile：`https://www.sportinglife.com/racing/profiles/horse/`
- BHA 官方搜索/监管信息：`https://www.britishhorseracing.com/`

字段覆盖预期：

- `Sporting Life`：racecards、results、horse profile 的可读性较好，适合作为新闻源之外的结构化候选。
- `BHA`：官方性质更强，适合补充官方马匹、赛程、监管和公告信息，但页面/API 入口需要单独确认。

风险：

- `Sporting Life` 页面可能依赖前端渲染或内部 JSON，需要确认是否能稳定慢速抓取。
- BHA 官方数据字段可能分散在搜索、profile、公告和监管页面，字段完整度未确认。

建议：

- 后续先做 racecards/results/horse profile 三类 fixture，不直接写正式表。
- 如果 Sporting Life 字段完整，后续可作为英国正式导入候选；BHA 作为权威校验/补字段来源。

## 法国：France Galop

样本入口建议：

- Calendar / meetings：`https://www.france-galop.com/`
- Declarations / runners：`https://www.france-galop.com/`
- Results：`https://www.france-galop.com/`
- Horse profile/search：`https://www.france-galop.com/`

字段覆盖预期：

- 结构化赛程、报名、出马、赛果和马匹资料具备权威价值。
- 法语字段可作为结构化缓存字段或原始 payload，不进入新闻审核、翻译、自动发布或 QQ 自动推送主链路。

风险：

- 页面可能依赖 JS、会话或查询参数；字段名和页面正文以法语为主。
- 用户明确无法审核法语新闻正文，因此 France Galop 不作为本期新闻源。

建议：

- 后续只评估结构化数据库入口，不抓法语新闻正文。
- 若正式导入，需要在字段层保留原始法语 payload，同时用英文/中文后台标签解释字段含义。

## 后续进入正式导入的优先级

1. `HKJC`：本期已实现正式受控导入入口，可继续用 payload 小样本和后续真实慢速请求验证。
2. 英国 `Sporting Life + BHA`：字段和公开入口较有希望，建议下一期做 fixture spike。
3. 美国 `Equibase`：价值高但限制风险高，建议先做 PDF/HTML 小样本解析评估。
4. 法国 `France Galop`：只保留结构化数据候选，不进入法语新闻审核链路。
