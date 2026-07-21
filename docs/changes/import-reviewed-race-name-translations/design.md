# 已审核赛事中文名统一导入与生产写入设计

## 现状

审核工作簿以 `RaceSeries + 完全一致当前展示名` 合并年份。模型中 `RaceSeries.chinese_name` 是系列级中文名，`RaceEvent.chinese_name` 是年度赛事实际展示名；当前缺口赛事的后者多数等于 `original_name`，不能把“非空”误判为已有翻译。

## 产物与数据流

```text
五份锁定 XLSX
  + 原始只读 Markdown 分组清单
  -> artifact-tool 读取、逐行身份对照与结构校验
  -> 显式应用“让赛不展示”规则并保留 before/after
  -> normalized-input.json
  -> manifest.json（系列动作 + 分组/年份动作 + 显式身份修正）
  -> SSH 内生产 Django 只读事务导出目标当前值
  -> production-before.json
  -> dry-run.json + rollback-before.json
  -> 统一导入预演.xlsx
  -> apply/verifier + execution metadata/plan + 十一项成员 bundle-index.json
  -> 当前 custom-format 数据库备份 + SHA-256 + pg_restore -l
  -> 一次性 apply 工具（默认 verify-only，显式 --commit）
  -> 单事务 CAS + 批量更新 + OperationLog
  -> 独立写后 verifier + health/page smoke
```

所有本地产物写入新的时间戳目录，旧目录不覆盖。输入路径和 SHA 写入 manifest；美国使用已经把 724 行状态改为 `已确认` 的审核版。

## 字段分工

### RaceSeries

- 同一系列所有审核行中文名一致时，产生一条系列动作。
- before 字段：使用 `RaceSeries._meta.concrete_fields` 枚举当前模型所有具体数据库字段（包括 `manual_lock_flags`、`source_refs`、状态、时间戳等），按字段名排序规范化，并保存逐行 SHA-256；不得维护一份可能漏字段的手写白名单。
- after 字段：只包含 `chinese_name`。
- 不改变 canonical original、review status、manual lock、source refs 或系列关系。
- `manual_lock_flags.chinese_name` 为真时分类为 conflict。

### RaceEvent

- 普通动作以工作簿中的系列 ID、年份范围和当前展示名精确定位。
- before 字段：使用 `RaceEvent._meta.concrete_fields` 枚举当前模型所有具体数据库字段（外键使用数据库 attname，例如 `race_series_id`），按字段名排序规范化，并保存逐行 SHA-256；覆盖身份、状态、来源、公开、关联、锁和时间字段。
- after 字段：普通动作只包含 `chinese_name`。
- 香港修正动作额外把 `race_series_id / series_key` 指向 ID `5963`；原文保留污染文本，避免无授权覆盖来源事实。
- 普通动作遵守 `manual_lock_flags.chinese_name`；香港修正还要求 `race_series / series_key / identity` 均未锁定。

### HistoricalRaceEventTarget

- 只把香港修正 Event `16446` 唯一关联的 HistoricalRaceEventTarget `49052` 纳入动作；普通翻译不改变历史目标。
- before 字段同样枚举模型全部 concrete database fields 并保存完整行 SHA。
- after 只包含目标 `race_series_id=5963`；必须验证 target 的 event、year、地区与当前 RaceEvent 一致，且目标系列/年份不存在另一历史目标。

## 身份基线对照

- 重新解析 `docs/collected_complete_race_names_missing_zh_20260719.md` 的五区表格。
- 最终工作簿的序号、原文展示名、年份表达、年度赛事数、RaceSeries Key / ID 必须与对应地区基线逐行一致。
- 基线总计、地区计数和分组 SHA 必须与锁定值一致；任何身份列差异在读取阶段直接失败，不能进入 dry-run 分类。

## 年份解析

支持单年、逗号/顿号分隔和闭区间，例如 `2013、2017–2026`。解析结果必须去重、升序，展开总数必须等于工作簿“年度赛事数”；否则整批失败。

## 让赛展示规则

- 先保存工作簿原始 `reviewed_chinese_name`，再仅删除 `让赛 / 讓賽 / 让步赛 / 讓步賽` 及删除后形成的空括号。
- 不将删除内容替换为“锦标”“大赛”等新词，避免超出用户确认内容。
- 调整记录进入 manifest 和 Excel“规则调整”表；原工作簿不回写。
- 调整后中文名为空、无中文字符或仍含让赛字样时 fail closed。

## 日本单元格修订真实性

- 修订前工作簿以 SHA-256 `57a40984…1fad` 为不可变来源基线；先用 artifact-tool 导入和渲染，再复制为新的最终输入，绝不覆盖用户原文件。
- 比较两份工作簿的表名、used range、全部业务单元格值/公式、样式、合并区域、行列尺寸、冻结窗格、筛选和数据验证。
- 业务值差异 allowlist 精确为“翻译清单”中序号 64 的“建议中文名”单元格：`京成杯秋季让赛 -> 京成杯秋季赛`。不允许改变来源、状态、备注或任何身份列；保存实现造成的非业务 OOXML 元数据差异不作为授权扩展。
- 输出机器可读差异报告和修订后 SHA；生成 manifest 前再次执行同一验证。测试将额外篡改任一其他业务单元格并断言失败。

## 生产只读快照

- 只使用权威服务器 `root@47.239.167.86` 和已有容器 `umanewsbot-web-1`。
- 使用 `docker exec`，不得使用 `docker compose run`。
- Django 查询置于数据库只读事务；只查询 manifest 涉及的 RaceSeries、其年度赛事及历史目标。
- 在同一只读事务中按主键排序导出全部目标字段，并对规范 JSON 计算 SHA-256；本地接收后再次查询一次，前后目标摘要、计数和行内容必须完全一致。任何差异都标为 snapshot drift。
- 不在服务器创建文件，不上传输入，不执行 `save/update/bulk_update`。

## 分类

系列与年度赛事分别分类：

- `would_update`：当前值满足覆盖前提且与建议值不同。
- `already_applied`：当前值已等于建议值。
- `conflict`：当前已有不同人工中文名、ID/Key/地区不符或香港目标年冲突。
- `locked`：目标字段存在人工锁；作为阻断分类，不允许覆盖。
- `missing`：manifest 目标无法唯一定位。
- `out_of_scope`：生产返回了未在工作簿年份中的相同显示名，仅报告不写。

只要存在 `conflict`、`locked`、`missing`、输入错误、摘要漂移或香港修正不唯一，顶层 `apply_ready=false`。

## 跨系列同译名

跨系列同译名只进入提示表；它既不阻断当前中文名写入，也不触发自动合并。香港 `SURFACE` 行是唯一显式例外，其身份修正由用户点名复查并有单独固定规则。

## 安全、幂等与回滚

- 相同输入 SHA 和相同生产 before 快照应产生相同业务 manifest 内容；运行时间、目录名等易变字段不进入内容 identity。
- 后续 apply 必须逐对象比较 manifest 中的完整行 before SHA 和 `updated_at`，不一致即停止；完整快照的标量、日期时间、日期、时间、Decimal、UUID、bytes、JSON 和空值使用版本化规范序列化。
- `rollback-before.json` 保存每个拟变更对象的完整 before、预期 after 与逐行 SHA；正式 apply 前仍须创建并独立校验数据库备份。
- apply 工具位于 `runtime/tools/`，复制到现有 web 容器临时目录执行，不修改服务器 checkout、不构建镜像、不重启服务；临时脚本和 JSON 在验收后删除。
- 工具默认 verify-only；`--commit` 才进入单个 `transaction.atomic()`，先设置 PostgreSQL `lock_timeout='5s'`、`statement_timeout='120s'`，再锁定并逐行 CAS `eventScope` 的全部父 RaceSeries（包括非动作源 Series 6019），查询锁定这些系列下完整 RaceEvent 集，随后锁定历史目标。精确比较完整父子集合、系列 ID/key/地区、逐对象完整行 SHA、`updated_at`、人工锁和目标身份；父行锁阻止并发插入/改绑子 Event。锁超时、集合差异或任一不一致整批回滚。
- 更新使用固定目标集合：RaceSeries 只改 `chinese_name/updated_at`；RaceEvent 只改 `chinese_name/updated_at`，香港单条额外改 `race_series_id/series_key`；对应 HistoricalRaceEventTarget 只改 `race_series_id/updated_at`。事务内写一条 `OperationLog`，detail 记录 manifest、production-before、dry-run、rollback 和备份 SHA。
- `bulk_update` 固定 `batch_size=500`；脚本显式写入同一个 `timezone.now()` 到 `updated_at`。香港 Event 与历史目标同步改绑，写前分别检查目标系列/年份唯一性，并验证 target/event 关联、年份及当前系列一致。
- 独立 verifier 是与 apply 不同的脚本，在新事务重新读取完整目标并逐对象比较 after SHA；失败立即停止后续动作。
- apply 工具提供显式 `--rollback-commit`。它要求唯一 apply OperationLog、完整 bundle 一致，并锁定全部目标后做 after-state 完整行 CAS；成功时仅恢复本批改变字段及新的 `updated_at`，写一条 rollback OperationLog，再由独立 verifier 的 rollback 模式核对 before 业务值。CAS 漂移时禁止对象级强制回滚，升级为人工事故决策。
- 数据库 custom-format 备份是灾难恢复点，对象级 rollback 是首选快速恢复路径，两者不能互相替代；整库恢复只在停写、事故前再备份并明确评估期间合法数据后人工执行。

## 执行包与审核冻结

受审 bundle 精确包含：

1. `apply_race_name_translation_manifest.py`
2. `verify_race_name_translation_manifest.py`
3. `input-lock.json`
4. `normalized-input.json`
5. `manifest.json`
6. `production-before.json`
7. `dry-run.json`
8. `rollback-before.json`
9. `execution-metadata.json`
10. `execution-plan.json`
11. `artifact-index.json`
12. `bundle-index.json`

`bundle-index.json` 记录前十一个文件的 basename、字节数和 SHA-256，并以排除自身 `contentSha256` 字段后的规范 JSON 计算内容身份。十二项 bundle 进一步打成 mtime/uid/gid/mode 固定的确定性 `tar.gz`，归档和 receipt 纳入 review/fingerprint，避免把约 150 MiB 重复 JSON 以散文件写入 Git。成功代码 review 后记录完整 fingerprint、approved parent/content hash；用户在该 review 后授权，先完成 staging transition 校验并创建不可变提交，再从该提交取出归档、核对 archive SHA、解包并核对 bundle-index SHA。宿主、容器内、verify-only、commit、verifier 与 rollback 都必须传入同一个 `--expected-bundle-index-sha256` 并重算全部成员。生产写入后只追加工作流允许的 evidence-only 文档，不更换脚本或数据。

## 审计契约

- apply 成功恰写一条 `OperationLog`：`action_type=race_name_translations_applied`、`target_type=race_name_translation_batch`、`target_id=<manifest contentSha256 前 32 位>`、`admin=NULL`。
- `detail` 是版本化 JSON，固定包含 batch ID、operator=`mentianlu_via_codex`、authorization ref/time、commit OID、bundle/index/tool/verifier/manifest/before/after/dry-run/rollback/backup SHA、备份大小、系列/赛事/身份修正计数和完成时间。
- rollback 成功恰写一条 `action_type=race_name_translations_rolled_back` 日志并引用原 apply log ID；重复 apply、verify-only 或失败事务不得新增日志。脚本先检查同 batch apply 日志不存在，避免重复提交。

## 生产执行顺序

1. 重新生成日本修订工作簿并锁定五份 SHA；重新生成 dry-run，确认业务计数和生产 before 未漂移。
2. 最新内容完成同一 reviewer 只读复审；随后取得用户针对该受审版本的明确发布授权。
3. 按 rollout 中的固定命令由 lowcost `db` 容器创建服务器 custom-format 备份，等待 `pg_dump` 正常结束，再核对权限、大小、SHA-256、PostgreSQL 版本和 `pg_restore -l`。
4. 从审核后不可变提交导出完整 bundle，上传到服务器临时目录并复制到现有 web 容器；宿主和容器重算全部 SHA。
5. 先以明确的 bundle-index SHA 运行 verify-only；输出必须仍为 `apply_ready=true`。commit 前再次重算相同目录，随后以同一套字节显式 `--commit`，单事务写入。
6. 独立运行 post-apply verifier、OperationLog 查询、让赛标记检查、生产快照计数、`/healthz/` 和代表性页面抽检。
7. 删除服务器和容器临时文件；只按 evidence-only allowlist 回写运行证据并完成对应审核/推送，不部署或重启应用。

## 性能

目标规模固定为 `1301` 个源系列、`1300` 个系列写入、`8663` 个审核表年度赛事写入、`1` 个获授权的范围外公开赛事纠正和 `219` 个同系列原文回退 Event 对齐，即 RaceEvent 写入总数 `8883`；完整 Event 围栏为 `8885` 场。生产查询与锁定按 scope 批量读取，写入固定 `batch_size=500`；整个写入仍处于同一事务。PostgreSQL 16 生产规模 fixture 验收上界为：总查询数不超过 `40`、commit 路径不超过 `60s`、进程 RSS 增量不超过 `256 MiB`，并记录实际值；超界即阻断生产执行。

## 文档

完成后更新：

- `docs/current_state.md`
- `docs/project_status.md`
- `docs/decisions.md`（仅新增实际决策时）
- `docs/deploy_runbook.md`（仅在形成未来 apply/rollback 操作步骤时）
