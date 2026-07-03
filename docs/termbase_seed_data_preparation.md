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

## Source Discovery

本轮固定入口如下。实现优先解析稳定 HTML/文本表格，PDF 不纳入首版：

| 来源 | 固定入口 | 用途 | 首版状态 |
| --- | --- | --- | --- |
| HKJC local horses | `https://racing.hkjc.com/en-us/local/information/selecthorse` | 香港本地马英文名、中文名、练马师等入口 | 支持 HTML/表格样本 |
| HKJC former name | `https://racing.hkjc.com/en-us/local/info/horse-former-name` | 来港前名与 pedigree | 支持 HTML/表格样本 |
| HKJC overseas simulcast | `https://racing.hkjc.com/en-us/overseas/` | 海外赛事转播入口 | 支持 HTML/表格样本 |
| HKJC learn racing / terms | `https://racing.hkjc.com/racing/english/learn-racing/learn-question.aspx` | 固定术语、赛绩表达佐证 | 支持 HTML/表格样本 |
| WP Stud home | `https://www.wpstud.com/` | WP Stud 来源说明 | 记录为社区来源 |
| WP Stud horse translation | `https://www.wpstud.com/Translation/Horse/Horse.htm` | 马名日英中对照 | 支持 HTML/表格样本 |
| WP Stud HK horse translation | `https://www.wpstud.com/Translation/Horse/HK/Horse_HK.htm` | 香港马名对照 | 支持 HTML/表格样本 |
| WP Stud Japan famous horses | `https://www.wpstud.com/horseintro/jpnhorse/JpnHorse.htm` | 日本名马和详情入口 | 支持 HTML/表格样本 |

内置 fixture 位于 `server/stable/fixtures/termbase_seed/`，用于无网络 dry-run、测试和解析器回归。

## 输出文件

命令会生成：

- `seed_candidates.csv`：候选主表，严格兼容 `import_terms` 字段。
- `seed_conflicts.csv`：译名冲突与推荐处理，不可直接导入。
- `summary.json`：来源、请求、候选数、冲突数、失败摘要和输出路径。

默认输出目录：

```bash
runtime/termbase_seed/<timestamp>/
```

`seed_candidates.csv` 表头固定为：

```text
term_type,source_language,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade
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

未传 `--allow-network` 时，命令不会请求 HKJC 或 WP Stud 网络页面。

## 审核与导入

1. 打开 `seed_conflicts.csv`，先处理冲突和社区来源候选。
2. 审核 `seed_candidates.csv`，确认 `target_zh` 为简体中文、`notes` 保留证据、类型无误。
3. 使用现有导入器预检：

```bash
python server/manage.py import_terms runtime/termbase_seed/<timestamp>/seed_candidates.csv --dry-run
```

4. 错误数为 `0` 且人工抽检通过后，再按正式术语导入流程导入。

## 安全边界

- 命令不创建、更新或删除 `TermEntry`、`TermAlias`、`TermCandidate`、`ExternalHorse` 或 `ExternalHorseAlias`。
- 命令不派发 Celery 翻译、评分、发布或 QQ 推送任务。
- HKJC 译名优先；WP Stud 只作为社区候选、别名或佐证。
- 只有 WP Stud 命中的候选会在 `notes` 标记 `source_tier=community` 和 `requires_review=true`。
- 触网失败、非 2xx、timeout 或解析失败会写入 `summary.json`，并将本次结果标记为 `incomplete=true`。
