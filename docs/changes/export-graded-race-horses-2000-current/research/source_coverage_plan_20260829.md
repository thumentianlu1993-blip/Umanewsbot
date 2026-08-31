# 四地区目标赛事来源覆盖计划（2026-08-29）

## 结论

当前 12,047 条 target 已逐条获得机器可读的“来源路径”。旧英法结果按最新 AQPS target 重审后，已有
338 个 target 绑定 372 个 held occurrence；其余仍没有完成赛果证据。
来源路径不是赛果证据，更不是 actual starters 或完整马匹资料已落表。覆盖 artifact 因 target 仍为
`PREPARED`、来源复用条款和 TRA entitlement 未验证而保持 `execution_ready=false`。

## 冻结身份

- target root：`/Users/mentianlu/.codex/umanews-target-aqps-evidenced-20260829.dn99Jz`
- target ledger SHA-256：`88313a59972196ddd6a275c22a09f7c9c7b8ae9b23efc5f67045a34076961a49`
- target manifest SHA-256：`b507d21d0f7bc5eef9785cb9a230200bbdbdb81a63686f5f63476a26add1ec5d`
- coverage root：`/Users/mentianlu/.codex/umanews-source-coverage-plan-terms-v3-20260829.ky1ZW2`
- coverage manifest SHA-256：`3a63780f223a364889b4f2327b0c8f3b3c13a5059f72fa2b0618e4e1c0bc82c8`
- `target-source-plan.jsonl`：12,047 行，SHA-256
  `c50bdecfbbd20b868d6cab7e6989835d0b9af641e26591435cc1fafa4c49e637`
- `coverage-buckets.jsonl`：309 行，SHA-256
  `de7fb8fecb7bde1ae51d6fd9dbd67ca9de259d615c6bf4362459db8dd4751d72`
- `orphaned-evidence.jsonl`：0 行，SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`

## Target 与证据状态

| 地区 | target | current-held target | current-held occurrence | TOBA 待审 held candidate | calendar-only | route-only |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GB | 3,194 | 186 | 186 | 0 | 197 | 2,811 |
| IRE | 1,957 | 0 | 0 | 0 | 0 | 1,957 |
| FR | 1,890 | 152 | 186 | 0 | 95 | 1,643 |
| USA | 5,006 | 0 | 0 | 3,724 | 0 | 1,282 |
| 合计 | 12,047 | 338 | 372 | 3,724 | 292 | 7,693 |

TOBA 冻结页解析 11,223 行，绑定 3,728 个 occurrence / 3,724 个 target；465 个 issue 保留为
12 个 grade conflict、232 个 target match missing、1 个 not unique、16 个 source reused、204 个
source unmatched，不以模糊匹配消除。

旧英法 bundle 已按 current AQPS target 重新审计。英国 186 场/1,683 actual-starter rows、法国
115 场/742 rows 均绑定当前 target，4 个旧 AQPS orphan key 已消除；英国另有 11 个 manual-review
candidate 和 1 个 legacy gap，继续保持未覆盖，不通过改名猜测消除。

## 地区来源路由

| 地区 | 赛事/赛果权威路径 | TRA 路径 | 受控 fallback | 当前主要缺口 |
| --- | --- | --- | --- | --- |
| GB | BHA 赛历/赛果 | bulk `/v1/results` + targeted horse | Sporting Life / Racing Post 的受审存档 | 已重绑 186 current-held；2,811 route-only、197 calendar-only，官方历史 held 分母未闭合 |
| IRE | HRI 赛历/赛果 | bulk + targeted horse | Racing Post / ATR 受审存档 | 1,957 全部仍为 route-only；本地 parser 已支持，但来源尚未落成 held occurrence |
| FR | France Galop 公报/赛历 | bulk + targeted horse | ZEturf/其他第三方仅作 review reference | 152 个 target / 186 occurrences current-held；其余仍需结果或路由执行 |
| USA | TOBA history + Equibase chart | North America entitlement 下 bulk + targeted horse | 无权威 chart 时用 TOBA winner anchor 定向恢复 | 3,724 待人工审核；1,282 route-only；2000–2009 主要依赖 winner-targeted 路径 |

## 条款与自动化边界

| 来源 | 当前公开条款结论 | 本方案允许模式 |
| --- | --- | --- |
| The Racing API | 允许 application、website、data analysis；禁止未经许可直接转售 | 用户已声明完整权限；在 credential/真实 response proof 后作为批量主链 |
| BHA | 明确禁止无许可的商业自动化数据抽取 | frozen human-reviewed reference，或先取得书面 license |
| France Galop | 数据库权利声明禁止实质性抽取及反复、系统性小规模抽取/复用 | frozen human-reviewed reference，或先取得书面授权 |
| Equibase | 页面明确禁止 robot/spider/scraper，并禁止未经同意再发布/传播 | frozen human-reviewed reference，或先取得书面 consent |
| HRI | 当前未找到明确允许系统性商业复用的公开条款 | manual reference，批量前取得书面许可 |
| TOBA | 页面 all rights reserved，未找到明确系统性复用许可 | manual winner/grade reference，批量前取得书面许可 |
| Racing Post / Sporting Life / ATR / ZEturf | 未在本 artifact 记录批量复用许可 | 仅冻结的逐项 human-reviewed reference |

条款证据 URL 已写入每个 target 的 `routes[]`，manifest 汇总 `by_route_terms_status`。技术上可访问不等于
允许批量复用；非 TRA 来源未取得书面许可时，不得被 runner 自动抓取。

## 与“外部名单 -> Racing API 单马导出”的关系

该路径不受 bulk `/v1/results` 默认近 12 个月窗口约束：外部权威/可信来源先提供冠军或参赛马名称及其
目标赛事关系，TRA `/v1/horses/search` 只用于生成候选；随后用候选的
`/v1/horses/{horse_id}/results` 全历史生涯验证唯一目标 occurrence。只有身份和 occurrence 唯一时，
才用该场返回的全体实际出赛 `hrs_*` 建 stable-ID ledger，并直接抓 profile/full career/有界 parent。

Montjeu + 1999 Prix de l'Arc de Triomphe 已有离线 acceptance seed，但实际 `hrs_*`、1999 Arc 是否出现在
账号返回及字段完整率仍是网络 proof 的 unknown，不能用 OpenAPI 描述代替真实 entitlement 证据。

## 重放命令

工具只读本地 artifact，不联网、不写数据库。运行时使用项目依赖容器；输出目录必须是新目录。

```bash
SOURCE_COVERAGE_OUTPUT=$(mktemp -d /Users/mentianlu/.codex/umanews-source-coverage-plan-rerun.XXXXXX)
docker run --rm \
  -v /Users/mentianlu/.codex:/artifacts:ro \
  -v "$SOURCE_COVERAGE_OUTPUT":/output \
  -v /Users/mentianlu/.codex/worktrees/export-graded-race-horses-2000-current/runtime:/app/runtime:ro \
  -w /app umanews-review:race-data-sync \
  python /app/runtime/research/build_graded_race_source_coverage_plan.py \
  --target-root /artifacts/umanews-target-aqps-evidenced-20260829.dn99Jz \
  --current-held-proposal-root /artifacts/umanews-france-galop-flat-2026-release-current-20260829.YI2GTU \
  --current-held-proposal-root /artifacts/umanews-france-galop-jumps-2026-release-rerun-20260829.DMhbWi \
  --legacy-audit-root /artifacts/umanews-legacy-audits-aqps-current-20260829.kZhaDH/uk \
  --legacy-audit-root /artifacts/umanews-legacy-audits-aqps-current-20260829.kZhaDH/fr-base \
  --legacy-audit-root /artifacts/umanews-legacy-audits-aqps-current-20260829.kZhaDH/fr-correction \
  --calendar-audit-root /artifacts/umanews-official-calendar-aqpsfix-2026-20260829.5y4PTf \
  --toba-history /artifacts/umanews-source-conflict-review-proposal-20260829/evidence/umanews-toba-history.html \
  --output-dir /output
```

## 下一步顺序

1. 审核英国 11 个 legacy candidates 与 1 个 gap；对 TOBA 3,724 个 current-bound candidates 完成
   alias/grade/reuse 双向审核。
2. 建立 BHA/HRI/France Galop 历年 actual-held/not-held 输入，优先压缩 IRE 1,957 和 GB 2,811 route-only。
3. 由独立 reviewer 签署 9 个 target blockers，生成 reviewed `COMPLETE` target；不得由实现者自签。
4. 取得精确 G3 后，先 Montjeu 与四地区 entitlement 小样本，真实确认 full historical、North America、
   Pro、字段非空率和请求预算。
5. 按 region/year 分批导出 artifact；通过 identity review、生产 backup、dry-run、apply、verifier 后才算落表。

## 2026-08-30 当前替代 artifact

本页前述 `12,047 / 338 / 3,724 / 292 / 7,693` 是 R1 审核前历史快照，不能再作为当前执行分母。
reviewed COMPLETE target 上的 not-due-aware v4 coverage 已更新为 `12,048 targets = 350 current-held +
3,726 TOBA-review + 113 official not-due + 179 past-calendar-result-required + 7,680 route-only`；manifest
SHA 为 `44fb91ab1e10ad1f992d4fcabca98b7189e7bac60dc6e97a7fd499059b633faf`。详细差分与 113 行 occurrence
non-held input 见 `official_calendar_not_due_conservation_20260830.md`。
