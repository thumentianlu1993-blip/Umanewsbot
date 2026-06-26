## Context

现有外部数据模型已经覆盖比赛、出马、赛果、赔率、马匹、马匹历史、别名、导入 run、错误和单来源锁。上一轮 HKJC 只完成 fixture 样本导入，生产已写入一次 `2026-06-21` 小样本；英法美只完成 read-only spike，均未进入正式外部表。

本目标要求按香港、英国、法国、美国顺序接入真实数据：每个地区抓最近 2 个月赛事，收集所有涉及马匹，再抓取马匹详情，完成后停止。当前最明确的入口是 HKJC 官方 HTML：

- 赛日枚举：`https://racing.hkjc.com/en-us/local/information/localresults`
- 单场结果：`/en-us/local/information/localresults?racedate=YYYY/MM/DD&Racecourse=HV|ST&RaceNo=N`
- 单场 racecard：`/en-us/local/information/racecard?racedate=YYYY/MM/DD&Racecourse=HV|ST&RaceNo=N`
- 马匹详情：`/en-us/local/information/horse?horseid=HK_YYYY_CODE`

## Goals / Non-Goals

**Goals:**

- 建立真实数据导入骨架：低频请求、HTML/JSON 解析、规范 payload、External* 写入、run 统计、错误记录和停止边界。
- 香港阶段使用 HKJC 官方 HTML 页面抓取最近 2 个月赛日、每场结果、所有涉及马匹详情。
- 英国、法国、美国阶段复用同一导入边界，但必须先完成真实入口复核和字段覆盖证明。
- 每个地区完成最近 2 个月赛事与涉及马匹详情后停止，不加入后台持续调度。
- 所有生产 commit 前执行 dry-run、数据库备份、单来源锁检查、健康检查和用户确认。

**Non-Goals:**

- 不续跑日本 netkeiba 外部数据。
- 不在本变更中创建公开比赛页、赛果页、马匹页或今日赛程产品。
- 不把英法美未确认入口直接写入正式外部表。
- 不绕过来源站点访问限制，不进行高并发抓取、登录抓取或规避风控。

## Decisions

### 1. 先用 HTML 解析接入 HKJC，而不是继续寻找未确认 JSON API

HKJC 官方结果页和马匹详情页已直接返回服务端 HTML，字段覆盖足够支撑最近 2 个月赛事与马匹详情导入。相比继续猜测 `consvc.hkjc.com` 或其他内部 API，HTML 入口更可复现、可人工核验，也更适合低频抓取。

替代方案：继续寻找 JSON/API。优点是结构化程度更高；缺点是当前未定位到稳定公开入口，上轮 `--allow-network` 占位 URL 已返回 404。

### 2. 解析层做成纯函数，网络层只负责低频 fetch 和请求证据

HKJC parser 接收 HTML 字符串并输出现有 importer 可消费的规范 payload。网络 client 负责 User-Agent、timeout、请求间隔、请求计数、URL/status 记录和错误包装。这样测试可以使用 fixture HTML 完成 RED/GREEN，不依赖真实网络。

替代方案：在 importer 中边请求边解析边写库。实现更短，但难以测试、难以复用，也更容易在异常时留下半写入。

### 3. 复用现有 External* 表，先不新增迁移

HKJC 结果页可映射到 `ExternalRace`、`ExternalRaceEntry`、`ExternalRaceResult`、`ExternalHorse` 和 `ExternalHorseAlias`。马匹赛绩细节如需要可后续写入 `ExternalHorseHistory`，但第一阶段不因少数字段新增表。

替代方案：新增地区专用表。优点是字段更贴近来源；缺点是会让四地区接入分叉，增加后续前台与术语识别使用成本。

### 4. 管理命令提供日期范围和最近天数，不加入 Celery Beat

本目标是一次性抓最近 2 个月后停止，因此入口以管理命令为主，例如 `--recent-days 60` 或 `--start-date/--end-date`。生产运行由人工在备份和确认后触发，暂不加入周期调度。

替代方案：直接加 Celery Beat 自动持续导入。与“完成后暂时停止任务”的目标冲突，也增加风控和生产运维风险。

### 5. 英法美按顺序只在入口证明后进入正式导入

英国、法国、美国必须先用真实页面或 API 证明最近赛事列表、单场结果和马匹 profile 可稳定解析，再写对应 importer。每个地区必须保留 `needs_more_spike` 到 `ready_for_formal_import` 的文档证据。

替代方案：并行实现四地。速度看似更快，但字段和访问限制差异很大，容易把 HKJC 已证明路径和英法美未知路径混在一起。

## Risks / Trade-offs

- [Risk] HKJC HTML 结构变化导致解析失败。→ Mitigation：解析测试使用真实 fixture，生产 dry-run 记录字段覆盖；解析失败只记录错误，不进入 commit。
- [Risk] 最近 2 个月赛事和马匹数量较多，触发访问限制。→ Mitigation：默认请求间隔保持保守，支持 `max_races`、`max_horses`、`--limit-races`，生产从 dry-run 和小批量 commit 开始。
- [Risk] 单场结果页和马匹详情页字段命名不一致。→ Mitigation：规范 payload 层统一字段，raw_payload 保留来源证据。
- [Risk] 英法美入口存在 JS、PDF 或反爬。→ Mitigation：每地先 spike，无法证明稳定入口时不写正式表。
- [Risk] 导入数据被误认为公开产品已上线。→ Mitigation：文档和规格明确本变更只写外部缓存，不生成公开页面、不改变新闻发布和 QQ 推送。

## Migration Plan

1. 本地创建 HKJC HTML fixture，先写解析和命令测试。
2. 实现 HKJC HTML client/parser，dry-run 不写库。
3. 在隔离 SQLite 跑最近小范围真实 dry-run，确认请求数量、字段覆盖和限速。
4. 生产部署前确认无运行中外部导入，备份数据库，部署代码并 smoke test。
5. 生产先跑 HKJC 最近 2 个月 dry-run；经用户确认后 commit，并记录 run_id、计数、请求边界和停止点。
6. 归档香港阶段证据后进入英国入口复核；法国、美国按同样门禁推进。

Rollback：

- 代码问题按常规回滚到上一提交并重建服务。
- 数据问题优先使用生产执行前备份做整库恢复；如果只需要撤销本次小批量导入，必须先列出本次 `run_id`、source、race_id、horse_id 和 alias 范围，不直接盲删。

## Open Questions

- 英国正式来源是否优先 Sporting Life，BHA 仅补权威字段，还是必须以 BHA 为主来源。
- 法国 France Galop 的稳定结构化入口是否需要登录、JS 或 PDF。
- 美国 Equibase 是否以 HTML chart、PDF chart 或 profile 页面作为主来源。
- 最近 2 个月的计算是否按运行日自然日回溯 60 天，还是按各地区赛季/赛日列表中最近约 2 个月赛日。
