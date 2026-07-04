## Context

当前 `prepare_termbase_seed_data` 已能为 HKJC 本地马与 WP Stud 生成术语审核文件，但 HKJC 本地马主要覆盖香港马匹，不能补齐海外马、海外骑师和海外赛事的中文译名。HKJC overseas simulcast Race Card 同时提供英文与繁中页面，是补充海外官方中文译名的高价值来源。

这次变更只扩展“术语种子数据准备”流程：生成可人工审核、可导入的本地文件，不直接写正式术语库，也不写外部马名索引。

## Goals

- 在现有 `prepare_termbase_seed_data` 命令中新增 `hkjc_overseas` 来源。
- 支持自动发现 HKJC overseas 当前可见 Race Card，并支持精确指定 `RaceDate/Racecourse/RaceNo` 作为可复现输入。
- 第一版抽取 `horse`、`jockey` 和 `race` 三类候选。
- 输出 `seed_candidates.csv`、`seed_conflicts.csv`、`summary.json` 和 `source_evidence.json`。
- 将 `target_zh` 与中文别名统一输出为简体中文，同时保留 HKJC 原始繁体证据。
- 保持现有术语导入边界：本任务不导入正式术语、不触发翻译发布、不触发 QQ 推送。

## Non-Goals

- 不导入 `TermEntry`、`TermAlias`、`ExternalHorse` 或 `ExternalHorseAlias`。
- 不在本变更中抽取海外练马师、马主、马场、装备、负磅、评分等字段。
- 不扩展 `RacingRegion` 枚举；缺失地区先映射到 `other`。
- 不把 HKJC overseas 抓取加入 Celery 例行任务。
- 不承诺全历史覆盖，也不处理 PDF、新闻正文或非 Race Card 页面的译名抽取。

## Decisions

### 复用现有命令

扩展 `prepare_termbase_seed_data --source hkjc_overseas`，而不是新增单独命令。这样可以复用现有输出目录、导入预检、触网开关、请求边界和审核文件格式。

### 自动发现与精确输入并存

默认流程必须能自动发现当前 HKJC overseas Race Card。为了降低触网风险，默认只抓取前 3 个 race card，并继续支持 `--limit-meetings`、`--limit-races`、`--max-requests` 和 `--request-interval-seconds` 等边界参数。

同时保留精确输入能力，例如重复传入 `--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`。这让测试、复跑和人工补采都能复现同一批页面。实现时应把该参数解析成结构化 race key；解析失败必须在命令层报错，而不是静默忽略。

### 中英文对齐策略

实现应优先抓取同一 Race Card 的英文页与繁中页：

- 马名以英文页马名作为 `source_language=en` 的原文，以繁中页马名转换后的简体作为 `target_zh`。
- horse profile 中的 `h` 或 `simulcastHorseId` 仅作为证据和辅助对齐信息，不作为术语去重主键。
- 骑师与赛事以同一 Race Card 上的行号、马号、赛事参数或稳定页面结构进行对齐，并在证据文件中记录对齐依据。
- 本变更不为繁中原文额外生成 `source_language=zh-hant` 候选行。

### 渲染 fallback

HKJC overseas 页面可能由前端运行时渲染。实现必须优先使用稳定的 HTML、脚本数据或公开请求入口；当直接请求拿不到 Race Card 内容时，允许使用渲染后缓存或可选浏览器渲染 fallback。

本变更不默认把 Playwright、浏览器二进制或系统图形依赖加入生产镜像。若运行环境没有可用渲染器，命令应记录 `render_fallback_unavailable` 或等价失败原因，并将结果标记为不完整，而不是静默产出空数据或强制要求生产容器安装浏览器。后续如果需要把浏览器渲染做成生产级默认能力，应另起部署/依赖变更或在实现中显式加入 requirements、Docker、运行手册和测试任务。

`source_evidence.json` 必须记录每条证据的抓取方式，便于以后判断页面结构变化或抓取成本。

### CSV 与证据分层

`seed_candidates.csv` 保持可被现有 `import_terms --dry-run` 预检的导入字段，不新增无法导入的列。结构化证据放入 `source_evidence.json`，包括 Race Card 参数、语言页面 URL、原始繁体中文、地区映射、抓取方式、horse profile 证据和跳过原因。

当前主规格中旧文字曾写明候选 CSV 不包含 `racing_region`，但项目当前导入格式已经包含该字段。本变更同步修正规格，使候选主表与当前导入器保持一致。

### 地区映射

不新增 `RacingRegion` 枚举。英国、法国、美国、日本等已有地区映射到现有值；南非、德国、澳洲、爱尔兰、韩国、阿联酋、新西兰等当前缺少枚举的地区先映射到 `other`，并在 `notes` 与 `source_evidence.json` 保留原始国家/地区代码。

### 跳过与失败

Race Card 页面能访问但显示“未有资料”或等价状态时，记录为 `skipped_races`，原因使用 `race_card_not_available`，不把整批结果标记为失败。

真正的请求失败、解析失败、超过请求上限或指定 race 无法取得时，必须写入失败摘要；如果这导致选定来源或指定 race 未完整处理，则 `summary.json` 标记 `incomplete=true`。

## Risks And Mitigations

- HKJC 页面结构变化：用 fixture 覆盖英文页、繁中页、不可用 Race Card 和渲染 fallback，并在证据文件中记录抓取方式。
- 渲染 fallback 成本较高：默认低抓取量，保留请求间隔和请求上限，不进入例行 Celery。
- 地区信息被 `other` 粗化：在 `notes` 与 `source_evidence.json` 保留原始地区，后续可单独提案扩展地区枚举。
- 骑师和赛事对齐不如马匹稳定：测试中覆盖对齐依据；无法可靠对齐的记录进入失败或冲突文件，而不是静默产出。

## Migration Plan

不需要数据库迁移。部署后默认行为不变；只有显式执行 `prepare_termbase_seed_data --source hkjc_overseas` 时才会生成新增产物。

如需回退，只需停止使用 `hkjc_overseas` 来源；已生成的审核文件可直接删除或保留归档，不影响正式表。
