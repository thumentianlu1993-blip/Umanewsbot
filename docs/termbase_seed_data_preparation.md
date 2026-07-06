# 术语种子数据准备

## 当前边界

`prepare_termbase_seed_data` 用于从 HKJC 体系与 WP Stud 准备第一批中文术语库种子。它只生成审核文件，不写正式表，不触发翻译、发布、QQ 推送或外部赛马数据库 commit。

首版支持术语类型：

- `horse`
- `race`
- `jockey`
- `trainer`
- `racecourse`
- `fixed_phrase`

首版不支持 HKJC `racecards` PDF、排位表 PDF 或网页排位表全量抽取；这些来源先标记为 deferred，等第一批种子审核后再评估。

HKJC overseas Race Card 已作为独立来源 `hkjc_overseas` 支持，第一版只承诺抽取海外 Race Card 上可中英对齐的：

- `horse`
- `jockey`
- `race`

海外练马师、马主、马场、装备、负磅、评分等字段暂缓。

## Source Discovery

本轮固定入口如下。实现优先解析稳定 HTML/文本表格，PDF 不纳入首版：

| 来源 | 固定入口 | 用途 | 首版状态 |
| --- | --- | --- | --- |
| HKJC local horses | `https://racing.hkjc.com/en-us/local/information/selecthorse` | 香港本地马英文名、中文名、练马师等入口 | 支持 HTML/表格样本 |
| HKJC former name | `https://racing.hkjc.com/en-us/local/info/horse-former-name` | 来港前名与 pedigree | 支持 HTML/表格样本 |
| HKJC overseas simulcast | `https://racing.hkjc.com/en-us/overseas/` / HKJC QIDS GraphQL | 海外赛事转播 Race Card 入口 | 支持 `hkjc_overseas`，Race Card 双语 fixture、精确 Race Card 参数和日期范围 QIDS 抽取 |
| HKJC learn racing / terms | `https://racing.hkjc.com/racing/english/learn-racing/learn-question.aspx` | 固定术语、赛绩表达佐证 | 支持 HTML/表格样本 |
| WP Stud home | `https://www.wpstud.com/` | WP Stud 来源说明 | 记录为社区来源 |
| WP Stud horse translation | `https://www.wpstud.com/Translation/Horse/Horse.htm` | 马名日英中对照 | 支持 HTML/表格样本 |
| WP Stud HorseList | `https://www.wpstud.com/Translation/Horse/HorseList.html` | WP Stud 全量马名日英中对照 | 支持 HTML 表格，输出日文主词、英文别名和简体中文目标 |
| WP Stud HK horse translation | `https://www.wpstud.com/Translation/Horse/HK/Horse_HK.htm` | 香港马名对照 | 支持 HTML/表格样本 |
| WP Stud Japan famous horses | `https://www.wpstud.com/horseintro/jpnhorse/JpnHorse.htm` | 日本名马和详情入口 | 支持 HTML/表格样本 |
| WP Stud race translation | `https://www.wpstud.com/Translation/Race/Race.htm` | 各地赛事名英中对照 | 支持目录页与子页面 HTML 表格 |
| WP Stud jockey translation | `https://www.wpstud.com/Translation/jockey.htm` | 骑师名英中对照 | 支持 HTML 表格 |
| WP Stud racecourse translation | `https://www.wpstud.com/Translation/racecourse/RaceCourse.htm` | 马场名英中对照 | 支持 HTML 表格 |

内置 fixture 位于 `server/stable/fixtures/termbase_seed/`，用于无网络 dry-run、测试和解析器回归。

## 输出文件

命令会生成：

- `seed_candidates.csv`：候选主表，严格兼容 `import_terms` 字段。
- `seed_conflicts.csv`：译名冲突与推荐处理，不可直接导入。
- `summary.json`：来源、请求、候选数、冲突数、失败摘要和输出路径。
- `source_evidence.json`：结构化证据，记录 Race Card 参数、中英页面 URL、原始繁体、地区映射、horse profile 证据、跳过和失败原因。

默认输出目录：

```bash
runtime/termbase_seed/<timestamp>/
```

`seed_candidates.csv` 表头固定为：

```text
term_type,source_language,racing_region,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade
```

所有 `target_zh` 和中文别名必须为简体中文。若来源为繁体中文，原始繁体证据写入 `notes` 或 `seed_conflicts.csv`。

## 使用方式

无网络 fixture 模式：

```bash
DB_ENGINE=sqlite python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --source wpstud
```

指定本地缓存目录：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --source wpstud \
  --input-dir /path/to/html-fixtures \
  --output-dir runtime/termbase_seed/manual-review
```

低频触网模式：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --source wpstud \
  --allow-network \
  --limit-pages 2 \
  --max-requests 4 \
  --request-interval-seconds 8 \
  --timeout-seconds 15
```

HKJC 本地马按字母拆批：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --hkjc-letter I \
  --max-requests 300 \
  --request-interval-seconds 0.2 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-letter-I
```

`--hkjc-letter` 可重复传入，取值为 `A-Z`。该参数只限制 HKJC `selecthorsebychar` 字母页，适合长批次断点续跑；未传时仍按默认路径发现全部字母页。

HKJC 本地赛果按日期范围回溯：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 0 \
  --hkjc-skip-horse-details \
  --hkjc-local-results-start-date 2024-01-01 \
  --hkjc-local-results-end-date 2024-01-31 \
  --max-requests 300 \
  --request-interval-seconds 0.2 \
  --timeout-seconds 25 \
  --output-dir runtime/termbase_seed/hkjc-local-results-202401
```

该模式从 HKJC `localresults` 抓取英文和繁中赛果页，对齐输出 `horse`、`jockey` 和 `race` 候选。建议按月或更小日期段分批运行；补历史赛果时建议同时使用 `--limit-pages 0` 和 `--hkjc-skip-horse-details`，避免重复抓取当前本地马资料。如需从 race 序列中间续跑，可使用 `--hkjc-local-results-skip-races <N>` 配合 `--limit-races <N>`。HKJC 赛日首页常把第 1 场作为当前页展示而只链接第 2 场之后，生成器会自动补抓 `RaceNo=1`。

HKJC overseas fixture 模式：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc_overseas \
  --output-dir runtime/termbase_seed/hkjc-overseas-review
```

HKJC overseas 精确 Race Card：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc_overseas \
  --allow-network \
  --hkjc-overseas-race RaceDate=2026-06-20,Racecourse=S5,RaceNo=1 \
  --max-requests 8 \
  --request-interval-seconds 3 \
  --timeout-seconds 15 \
  --output-dir runtime/termbase_seed/hkjc-overseas-live-smoke
```

HKJC overseas 日期范围回溯：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source hkjc_overseas \
  --allow-network \
  --hkjc-overseas-start-date 2024-01-01 \
  --hkjc-overseas-end-date 2024-01-31 \
  --max-requests 600 \
  --request-interval-seconds 0.2 \
  --timeout-seconds 25 \
  --output-dir runtime/termbase_seed/hkjc-overseas-qids-202401
```

该模式先从 HKJC overseas results 发现转播赛日，再通过 HKJC QIDS GraphQL 抽取 Race Card 中英对照，输出 `horse`、`jockey` 和 `race` 候选。建议按月分批运行并合并审核；如果同一实体跨月份出现不同中文译名，候选主表只保留一个 `target_zh`，其他译名进入 `aliases_zh` 和 `seed_conflicts.csv`。

未指定 `--hkjc-overseas-race` 且未指定日期范围时，`hkjc_overseas` 会尝试从 HKJC overseas 当前页自动发现 Race Card；默认最多处理前 `3` 个 race card，可用 `--limit-meetings` 和 `--limit-races` 收窄范围。

WP Stud 缓存目录模式：

```bash
python server/manage.py prepare_termbase_seed_data \
  --source wpstud \
  --input-dir runtime/termbase_seed/source_cache_wpstud_extra_20260705 \
  --output-dir runtime/termbase_seed/wpstud-race-jockey-racecourse-review
```

`wpstud` 解析器会识别已缓存的马名、赛事、骑师和马场表格。赛事、骑师和马场页面通常是英文原文配中文译名，因此输出 `source_language=en`；HorseList 马名页同时包含日文、英文和中文时，输出 `source_language=ja`，日文名作为 `source_ja`，英文名进入 `aliases_ja`，中文目标统一简体化。WP Stud 仍是社区来源，候选会在 `notes` 标记 `source_tier=community` 和 `requires_review=true`。

未传 `--allow-network` 时，命令不会请求 HKJC 或 WP Stud 网络页面。

## 审核与导入

1. 打开 `seed_conflicts.csv`，先处理冲突和社区来源候选。
2. 审核 `seed_candidates.csv`，确认 `target_zh` 为简体中文、`notes` 保留证据、类型无误。
3. 使用现有导入器预检：

```bash
python server/manage.py import_terms runtime/termbase_seed/<timestamp>/seed_candidates.csv --dry-run
```

4. 错误数为 `0` 且人工抽检通过后，再按正式术语导入流程导入。

社区来源导入前必须先查看 dry-run 的 `更新` 数。如果 WP Stud 候选会更新已有 HKJC 官方术语，应先过滤为只包含新增项的 CSV，例如 `seed_candidates_new_only.csv`，并把被跳过的既有项保存为 `seed_candidates_skipped_existing.csv` 供人工判断别名，不要让社区来源覆盖官方主译名、优先级或地区。

最终合并审核时还需要检查历史脏数据：

- 马名 `source_ja` 尾部国别后缀如 `(JPN)`、`(IRE)`、`(GB)` 不应进入正式主词；原始写法可保留在证据中。
- 赛事名中包含年份或替代名称的复合写法应拆为独立术语，例如 `(1986~) International Stakes (~1985) Benson & Hedges Gold Cup Stakes` 应拆成 `International Stakes` 和 `Benson & Hedges Gold Cup Stakes`。
- 为 HKJC 日本地区英文马名补日文 alias 时，如日文名已被既有日文主词或 alias 占用，不自动强行合并；需要人工确认后单条处理。

## 安全边界

- 命令不创建、更新或删除 `TermEntry`、`TermAlias`、`TermCandidate`、`ExternalHorse` 或 `ExternalHorseAlias`。
- 命令不派发 Celery 翻译、评分、发布或 QQ 推送任务。
- HKJC 译名优先；WP Stud 只作为社区候选、别名或佐证。
- 只有 WP Stud 命中的候选会在 `notes` 标记 `source_tier=community` 和 `requires_review=true`。
- 触网失败、非 2xx、timeout 或解析失败会写入 `summary.json`，并将本次结果标记为 `incomplete=true`。
- HKJC overseas 页面若只返回前端渲染壳且当前环境没有可用渲染器或渲染后缓存，会写入 `render_fallback_unavailable` 并标记 `incomplete=true`；系统不得把这种情况当作空数据成功。
- HKJC overseas Race Card 页面可访问但显示“未有资料”或等价状态时，记录到 `skipped_races`，不单独导致 `incomplete=true`。
- HKJC QIDS GraphQL 属 HKJC 前端使用的公开数据接口；运行时仍应低频、按月或更小窗口分批，并保留请求、失败和输出摘要。
