# 已完整赛事中文名翻译与导入交接文档

> 最后更新：2026-07-21（Asia/Shanghai，第三次）  
> 当前状态：Claude Code 等价最终复审两轮完成，结论 **APPROVED、actionable finding 清零**；当前唯一有效候选为 `unified-import-preview-20260720T220245Z`，等待用户对该精确版本重新发布授权  
> 重要结论：尚未写入生产数据库；`T220245Z` 之前的全部候选仍然失效，不得 apply

## 2026-07-21 最终复审第二轮记录（Claude Code，结论 APPROVED）

第二轮聚焦第一轮 8 项修复的 diff 逐项怀疑式复核：计数锚点形状与恒真式消除、空原文前置条件、allowlist 未消费阻断与测试选项隔离、全簿 diff 的 sheet 集合/范围/公式语义、si 引用唯一性（含 off-by-one 修正）、打包器 contentSha 重算与 apply 端等价性（已由真实 bundle 的 CLI 边界验证交叉证明）、布局文案与负向测试、updated_at 断言。复核中发现并顺手修复一处健壮性问题：修订工具的单元格正则未处理自闭合 `<c .../>`，理论上可能把引用错误归并到相邻单元格；已改为同时匹配自闭合形式，重跑真实基线仍精确复现锁定 SHA `e244a0fb…`。该工具不在候选生成路径与 bundle 成员内，候选 `T220245Z` 身份不受影响。

第二轮后复跑：Node `20/20`、XLSX 布局 `6/6`、打包器 `6/6`、SQLite `20+4skip`、`git diff --check` 通过；PostgreSQL 16 `24/24`（含 updated_at 断言与生产规模 `31 queries / 3.093s / 90,914,816 bytes`）已于修复后通过。

复审两轮结论：**APPROVED，actionable finding 清零**。

- 审前指纹（第一轮修复后重生成前）：content_manifest `7512c9d1682edf8f8eba3671b95e678c67db75be4f6594b7f5d6be3b475c4e8d`，tracked_diff `3c8d5d8c725d9ee77c7f740ec5d80c648ef8ba8b3a68a88b8c78d621c4b69f1c`。
- 审后/发布冻结指纹（第二轮结束）：HEAD `353464c76c63d1e43043ccbefe0ebc88274b0888`，content_manifest `467624891617d7d26278277556f5c244393a12c2a5eb89dc7b3d1123a54784aa`，tracked_diff `3c8d5d8c725d9ee77c7f740ec5d80c648ef8ba8b3a68a88b8c78d621c4b69f1c`，status_porcelain `8df363190ad15ec1dec5b8e10a4ceed252fa5ea20b2df2fd4d07b16be522392b`，untracked_manifest `345facdc4ed16f36ad74dab75d4adc120c94db6919159ad00e2ffd4ab24bd209`，conflict=0、staged=0、相对 origin/main 落后 7。

下一步只剩发布门禁：用户对上述精确候选与 bundle（archive `bf28bb90…`、index `72706e95…`、content `014a43c2…`）重新回复“发布吧”或“上线”，然后按 §7 步骤 9 执行 staging/commit/备份/verify-only/apply/verifier/抽检。

## 2026-07-21 最终复审第一轮记录（Claude Code）

复审方式：主审查员精读 apply/verifier/分类核心并直接验证四个聚焦门禁，另派两个只读审查代理分别覆盖生成器/core 与辅助工具/测试，主审查员逐项裁定。

四项聚焦门禁结论（直接验证通过）：全部 1301 个 scope RaceSeries（含非动作源 6019）在 apply/verifier/rollback 三路径均有完整行 CAS；非 allowlist 独立中文名不进入 supplemental（生成层 `continue` + eventScope 完整行 CAS 双保险）；supplemental 同时校验系列 ID/seriesKey/地区，漂移即 conflict 阻断；全部 SSH 调用 `ControlMaster=no/ControlPath=none`，snapshot 前后 metadata 精确比对。

第一轮 finding 与处置（8 项行动项全部修复并补负向测试）：

1. `applyReady` 赛事总数等式为恒真式、supplemental 无锚点（中）：`expectedTotals` 新增 `eventActionCount=8883 / supplementalEventCount=220 / identityCorrectionActionCount=1 / outOfScopeEventCount=2 / crossSeriesDuplicateGroupCount=101`，生成器在产出候选前逐项比对，漂移即 throw fail closed。
2. `original_name` 与 `chinese_name` 同时为空被误判为原文回退（低）：supplemental 回退判定增加原文非空前置条件。
3. 授权 Event 96 未消费时静默丢弃（低）：allowlist 未消费一律显式 `missing` 阻断；`classifyDryRun` 增加测试专用 `authorizedOutOfScopeCorrections` 选项，生产路径仍用锁定常量。
4. 布局工具不比值/公式且生成器精确 diff 只覆盖三个固定矩形（中）：`validateFullWorkbookRevision` 移入 core 并改为全 sheet 完整已用范围的值+公式矩阵 diff，sheet 集合变化、矩形外值变化、任一公式变化均阻断。
5. 修订工具未校验共享字符串 si 仅被 C68 引用（中）：新增全 worksheet 引用扫描，目标 si 必须恰好在 C68 被引用一次；修复过程中发现并修正一处 off-by-one（`<si>` 计数含目标自身开始标签），修复后重跑真实基线精确复现锁定 SHA `e244a0fb…`。
6. 打包器不重算 `contentSha256`、不拒绝重复 files 行、无测试（低-中）：补齐 schemaVersion/contentSha256 重算/行数检查，新增 6 项测试（确定性、篡改、伪造 contentSha、重复行、错误 schema、错误预期 SHA）。
7. 布局工具报错文案夸大 + 负向用例薄（低）：文案改为只声明结构布局，新增合并区域/列宽/冻结窗格/筛选变化四个负向测试。
8. apply 测试缺 `updated_at` 显式断言（低）：apply 后断言 series/event `updated_at == appliedAt`，rollback 后断言 `== rolledBackAt`。

观察项（不行动）：让赛标记连同前导分隔空格删除（"维多利亚 Handicap"→"维多利亚"）符合规则意图，已被测试锁定；工作簿公式错误扫描不 gate 是有意设计（日本基线说明页 2 个 `#NAME?` 兼容问题按"仅改单元格"约束原样保留）。

修复后验证：Node `20/20`、XLSX 布局 `6/6`、打包器 `6/6`、SQLite `20+4skip`、PostgreSQL 16 `24/24`（生产规模 `31 queries / 3.093s / 90,914,816 bytes`）、`openspec validate --all --strict` `31/31`、`git diff --check` 通过。

重生成候选 `unified-import-preview-20260720T220245Z`：`applyReady=true`、blocker 0、全部锚点计数一致（1300/8883/220/1/2/101）、双快照稳定、metadata 一致（HEAD `7ad6ade`、started `2026-07-20T07:28:13Z`）、日本修订仅 C68 一处值差异且公式零差异、`eventScope` 1301/8885；`execution-plan.json` SHA `51736067…` 与上一候选逐字节一致，证明修复未改变业务内容。Excel QA 通过（8 表、公式错误 0）。新 bundle：`runtime/artifacts/race-name-translations/20260721/race-name-translation-bundle.tar.gz`，重复打包逐字节一致，archive SHA `bf28bb90dd9a3880a125d6193e73efe1821711189343430146a82c6cd491e6e4`、bundle-index 原始 SHA `72706e95832a0595f0e7b7177e76fb1865e250f92e7b39e31142481fe8bc333a`、content SHA `014a43c2670f5504c12814a3fea92dde5bedf9f8dea741954a326216361780f4`；apply/verifier CLI 均完成新 bundle 校验并到达预期数据库连接边界。

仍未执行：staging/commit/push、生产备份、verify-only 连接生产、apply、任何生产写入。

## 2026-07-21 进展记录（Claude Code 接手）

- 生产只读访问已恢复并确认：SSH 正常，`/opt/umanewsbot` HEAD `7ad6ade`，`umanewsbot-web-1` image `sha256:af880cd2…` started `2026-07-20T07:28:13Z`，八容器运行，`/healthz/` 200。
- 输入路径变更：四份原锁定在 `/Users/mentianlu/Downloads/` 的输入（日本基线、香港、英国、法国）因 macOS 隐私权限不可读，已由用户同字节复制到 `outputs/translate-race-names-20260719/`；六份输入 SHA-256 全部复核不变，生成器锁定路径与本文 §4.2、`docs/changes/.../spec.md` 输入表已同步更新。
- 生产快照脚本内存修复（将进入最终复审范围）：第一轮快照的 `content` 从不传输但此前与第二轮同时驻留内存，导致容器内进程在 4 GiB 主机被 OOM 杀死（exit 137，失败目录 `unified-import-preview-20260720T205208Z` 已 fail closed、无可用 artifact）。修复为第一轮摘要提取后显式 `del first` + `gc.collect()` 再取第二轮；不改变任何输出语义，客户端仍只接收第二轮完整内容与第一轮摘要。
- 新候选 `unified-import-preview-20260720T205650Z` 验收结果：五输入 SHA 全匹配；分组 SHA `c9c209e6…` 匹配；日本修订 `exactValueDiffCount=1`（仅 C68）且公式零差异、布局一致；生产 snapshot 前后 metadata 一致（HEAD `7ad6ade` / image `af880cd2` / started `2026-07-20T07:28:13Z`）；双轮快照稳定；`applyReady=true`、`blockerCount=0`；系列动作 `1300`、赛事动作 `8883`、身份修正 `1`、范围外仅报告 `2`、跨系列同译名 `101`；`eventScope.series=1301`（含 `beforeRowSha256`）、`eventScope.events=8885`；Event `96`（normalize→京成杯秋季赛）、Event `16446`（6019→5963）、Target `49052` 精确命中。
- Excel QA 通过：8 张表齐全（概览/阻断项/系列动作/年度赛事动作/身份修正/规则调整/跨系列同译名/输入锁），openpyxl 重载无公式错误，布局测试 2/2，概览显示阻断项 0、让赛规则调整 0、原工作簿改动 0；建议中文名无让赛残留（残留仅存在于被更正的 before 值与规则说明文本）。
- deterministic bundle 已重建：`runtime/artifacts/race-name-translations/20260721/race-name-translation-bundle.tar.gz`，重复打包逐字节一致；archive SHA-256 `3ac595c27e1391c3da7458eaef7dcd38d5f3b8e4be6beeafa6292137533f7eb7`，bundle-index 原始 SHA `2877af06f7e165f1051876f87364870ed4e79b8f2f35fd10e5a106c14d98d111`，content SHA `6d188e9c21305a87e259a5fad3d944c58ecdc30346a59524c7316908d3f1190a`，12 成员与 receipt 一致。
- 全量测试通过：Node 16/16、XLSX 2/2、SQLite 20 通过 + 4 项 PG 专项 skip、PostgreSQL 16 24/24（生产规模 fixture：queries=31、elapsed=2.815s、RSS 增量 92,372,992 bytes，均在预算内）、`openspec validate --all --strict` 31/31、`git diff --check` 通过；apply/verifier CLI 均完成 bundle 校验并到达预期数据库连接边界；临时 PG 容器与临时文件已清理。
- 最终复审方式变更（用户 2026-07-21 决定，见 `docs/decisions.md`）：原 codex reviewer 会话无法由 Claude Code 恢复，最终复审改由 Claude Code 对本精确候选做等价完整只读复审，聚焦 §7 步骤 7 的四类回归外加全量常规审查；通过前不得进入授权门禁。
- 2026-07-21 review fingerprint（全部文档回写后重算，作为审前指纹）：HEAD `353464c76c63d1e43043ccbefe0ebc88274b0888`，`content_manifest_sha256=b262ba3c627b4ed7da8a48af2afaccc9648b8275eedff4002f10bbf7109c2a1b`，`tracked_diff_sha256=66fdc9bfa47cca387e58fb182a816c33d066f054aeb2397abe456356193a4c54`，`status_porcelain_v2_sha256=5d324a886a439f452b76ebc6b246e4196764d05e18ff0b60515e574274a89e63`，`untracked_manifest_sha256=08c5b723dc82719ebaabe8b89776e4665fbd1e9516ad30bc07b9043ffcd00b24`，conflict_count=0、staged=0、相对 origin/main 落后 7。
- 尚未执行：staging/commit/push、生产备份、verify-only 连接生产、apply、rollback、任何生产写入。

## 1. 接手后先做什么

新模型开始工作前，依次阅读：

1. 仓库根目录 `AGENTS.md`
2. `docs/session_bootstrap.md`
3. `docs/current_state.md`
4. `docs/project_status.md`
5. `docs/decisions.md`
6. `docs/deploy_runbook.md`
7. `docs/codex_workflow.md`
8. 本文
9. `docs/changes/import-reviewed-race-name-translations/` 下的 `spec.md`、`design.md`、`test_cases.md`、`tasks.md`、`rollout.md`

不要在主工作区继续本任务。固定工作位置为：

- 仓库：`/Users/mentianlu/Code/umanews`
- 专用 worktree：`/Users/mentianlu/Code/umanews/.worktrees/translate-collected-race-horse-names`
- 分支：`codex/translate-collected-race-horse-names`
- 当前 HEAD：`353464c76c63d1e43043ccbefe0ebc88274b0888`
- 上游：`origin/main`
- 当前分支相对 `origin/main` 落后 7 个提交

当前工作树有本任务的大量 tracked/untracked 改动，全部属于用户资产。禁止清理、reset、checkout 覆盖、移动到别的 worktree，或为了“变干净”而删除未跟踪文件。不要在完成当前受审链路前擅自 rebase/merge `origin/main`，否则会改变审核范围和候选工具身份。

## 2. 项目整体背景

Umanews 是面向中文用户的日本赛马新闻与赛事信息平台，正式域名为 `umafans.run` / `www.umafans.run`。主技术栈为：

- Django
- PostgreSQL
- Celery
- Redis
- Docker Compose
- Nginx

产品主链路为：

`抓取 -> 翻译 -> 术语纠偏 -> 人工/自动审核 -> 网页发布 -> QQ 群分发`

本任务不属于新闻正文翻译，而是赛事基础数据治理。赛事数据的主要对象为：

- `RaceSeries`：跨年份赛事系列
- `RaceEvent`：某一年度的具体赛事
- `HistoricalRaceEventTarget`：历史赛事正式目标与完成状态

生产权威入口此前确认是：

- 主机：`root@47.239.167.86`
- 项目目录：`/opt/umanewsbot`
- Web 容器：`umanewsbot-web-1`

生产数据相关工作必须区分：

- 历史正式总账
- 已完整抓取的年度赛事
- 当前/未来赛程
- 身份审核与中文名审核
- dry-run/审核包
- 正式数据库写入

本文所述工作当前只推进到“审核输入、生成工具、受控 dry-run/执行包”层。没有获得最新成功 review 后的新鲜发布授权，也没有执行生产写入。

## 3. 该需求要做什么

用户最初要求：

1. 新建独立 worktree 和分支。
2. 找出当前已经抓取且 `basic/runners/results` 信息完整、但没有独立中文展示名的赛事。
3. 同一 `RaceSeries` 在不同年份的展示名完全一致时合并，不按年份展开。
4. 按地区拆成多个可编辑 XLSX：日本、中国香港、美国、英国、法国。
5. 收齐并验收用户完成的五区翻译。
6. 最终把审核结果形成统一预演，并在安全门禁通过后写入生产。

用户已经明确锁定的业务决定：

- 所有赛事中文展示名均不展示“让赛”属性。
- 原文中的 `(H)`、独立 `H`、`Handicap`、中文“让赛/讓賽”等不得进入最终中文展示名。
- 日本 `Keisei Hai Autumn H` 最终中文名必须是“京成杯秋季赛”，不能是“京成杯秋季让赛”，也不能退回“京成杯秋季”。
- 同系列已公开的 2026 年 `RaceEvent` ID `96` 也必须精确改为“京成杯秋季赛”。
- 香港 `SURFACE Bauhinia Sprint Trophy(H)` 的 2012 年记录是采集头污染：
  - `RaceEvent` ID `16446`
  - `HistoricalRaceEventTarget` ID `49052`
  - 应从污染系列 `6019` 同步改绑到正确系列 `5963`
  - Event 的 `original_name` 保持不变
  - Event 的 `series_key`、`race_series_id`、`chinese_name` 与历史目标的 `race_series_id` 必须同事务更新
- 同系列范围外、仍满足 `RaceEvent.chinese_name == RaceEvent.original_name` 的赛事，应同步使用已审核系列中文名。
- 已有独立中文名的范围外 Event 不得自动覆盖；唯一显式例外是 Event `96`。
- supplemental Event 必须同时匹配 RaceSeries ID、`seriesKey` 和地区。

马名翻译尚未开始。本阶段只处理赛事/赛马比赛名称。

## 4. 原始盘点与审核输入

### 4.1 只读生产盘点口径

完整赛事口径：

- `HistoricalRaceEventTarget.resolution_status=imported`
- `module_statuses.basic=complete`
- `module_statuses.runners=complete`
- `module_statuses.results=complete`

盘点结果：

- 完整年度赛事：`8867`
- 没有独立中文名、仍以原文回退：`8663`
- 已有独立中文名：`204`
- 按 `RaceSeries + 完全一致展示名` 合并后：`2023` 个审核分组
- 涉及源系列：`1301`

地区分组：

- 日本：`176` 组 / `2223` 场
- 中国香港：`91` 组 / `473` 场
- 美国：`724` 组 / `3273` 场
- 英国：`794` 组 / `2042` 场
- 法国：`238` 组 / `652` 场

原始清单：

- `docs/collected_complete_race_names_missing_zh_20260719.md`
- 分组 SHA-256：`c9c209e686bbce669bfdfd161bade5f4dfae357cc899fa649e908a749cfa966d`

### 4.2 五区最终输入

主生成器在 `runtime/tools/build_race_name_translation_import_preview.mjs` 中锁定了输入路径、行数和 SHA。接手时先核对这些文件仍存在，不要自行替换成同名文件。

| 地区 | 行数 | 当前输入 | SHA-256 |
|---|---:|---|---|
| 日本 | 176 | `outputs/translate-race-names-20260719/日本_已完整赛事中文名翻译审核表_20260719_京成杯秋季赛修订.xlsx` | `e244a0fb366ab1cf259b3c2f714cfea2066e8abbf21a79076c64443220b26eb1` |
| 中国香港 | 91 | `outputs/translate-race-names-20260719/中国香港_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，由 `/Users/mentianlu/Downloads/` 同字节复制，SHA 未变） | `20153db5217a8b05ff7b98b0af9640dea52ead58b17a8a91d35eedd154fa705f` |
| 美国 | 724 | `outputs/translate-race-names-20260719/美国_已完整赛事中文名翻译审核表_20260719_已审核.xlsx` | `f2481cdeea456bbf6ac5faf9102928cb5d67d520082d8b5c47ffecd41aa46c00` |
| 英国 | 794 | `outputs/translate-race-names-20260719/英国_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，同字节复制，SHA 未变） | `f0a80a5f55244224698fab6f3d56f0d5a7d776eb01ba02bf75c7d5f33d45488b` |
| 法国 | 238 | `outputs/translate-race-names-20260719/法国_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，同字节复制，SHA 未变） | `8234a68a16dc6c8e13b2cbef7a5eaf91a31ceeb0b0b561fcda4b596d5ffe02da` |

日本修订前基线：

- `outputs/translate-race-names-20260719/日本_已完整赛事中文名翻译审核表_20260719_AI翻译完成.xlsx`（2026-07-21 起为权威路径，由 `/Users/mentianlu/Downloads/` 同字节复制，SHA 未变）
- SHA-256：`57a40984e2723251db554f6a6c7c7a9b2661991fee16ad89b69ed3e902c81fad`
- 只允许 `翻译清单!C68` 从“京成杯秋季让赛”变为“京成杯秋季赛”
- 其他业务值、公式、样式、合并区域、行列尺寸、冻结窗格、筛选、数据验证都必须保持一致

五区 `2023/2023` 行均已由用户审核确认。

## 5. 已经做了什么

### 5.1 盘点和表格交付

- 建立专用 worktree/分支。
- 从生产执行只读 Django 查询，得到上述 `8867/8663/2023/1301` 口径。
- 生成 Markdown 清单。
- 按地区生成五份可编辑审核 XLSX。
- 验收用户交回的日本、香港、美国、英国、法国文件。
- 把美国全部状态改为“已审核/已确认”。
- 对日本工作簿执行单点 OOXML 修订。

### 5.2 统一预演和执行工具

已新增：

- `runtime/tools/race_name_translation_preview_core.mjs`
- `runtime/tools/build_race_name_translation_import_preview.mjs`
- `runtime/tools/revise_japan_race_name_workbook.py`
- `runtime/tools/compare_xlsx_layout.py`
- `runtime/tools/package_race_name_translation_bundle.py`
- `runtime/tools/apply_race_name_translation_manifest.py`
- `runtime/tools/verify_race_name_translation_manifest.py`
- `runtime/tools/test_race_name_translation_preview.mjs`
- `runtime/tools/test_compare_xlsx_layout.py`
- `server/stable/test_race_name_translation_apply.py`

工具链能力：

- 五区 XLSX 同 bytes 哈希与解析
- 日本单格修订 allowlist
- Markdown 分组 SHA 重算
- 让赛标记规范化
- 生产两轮全 concrete-field 只读快照
- 保留 JSON 数值原始词法
- 每行与整体快照 SHA 重算
- snapshot 前后 checkout/image/container started-at 精确比较
- dry-run 分类与阻断报告
- 香港 Event/历史目标同步身份修正
- Event `96` 精确 allowlist
- 219 场原文回退 Event 补充同步
- 非 allowlist 独立中文名只报告、不覆盖
- `eventScope` 父子完整范围围栏
- 默认 verify-only、显式 `--commit`
- 单事务 CAS、manual lock、唯一性与 OperationLog
- 独立 verifier
- after-state CAS 对象级 rollback
- bundle index、deterministic tar.gz、receipt

### 5.3 目标规模

上一个业务快照中的预期目标规模为：

- 审核分组：`2023`
- 源系列：`1301`
- 写入 RaceSeries：`1300`
- 审核表年度 RaceEvent：`8663`
- Event `96`：`1`
- 同系列原文回退补充 Event：`219`
- RaceEvent 写入总数：`8883`
- 完整 Event 围栏：`8885`
- HistoricalRaceEventTarget 写入：`1`
- 香港身份修正：`1`
- 已有独立中文名、只提示不覆盖：`2`
- 跨系列同译名提示：`101` 组

这些是上一次稳定生产快照的业务结果。由于当前需要重新读取生产，下一候选必须重新验证计数；不得把这里的数值当作免检常量。

### 5.4 测试和验证

当前返修代码最近一次结果：

- Node：`16/16`
- XLSX 布局：`2/2`
- SQLite/Django：`20/20`，另有 4 项 PostgreSQL 专项 skip
- PostgreSQL 16：`24/24`
- 生产规模 fixture：
  - queries：`31`
  - elapsed：`2.918s`
  - RSS 增量：`101,470,208 bytes`
- OpenSpec strict：`30/30`
- `git diff --check`：通过

测试过程创建的临时 PostgreSQL 容器与网络已经清理。

### 5.5 连续代码审核

本任务经过多轮原生只读 review。旧候选依次暴露并修复了：

- 香港 HistoricalRaceEventTarget 未同步改绑
- 输入 bytes/hash 漂移风险
- 日本工作簿修订范围与布局风险
- Markdown 分组摘要复用风险
- 让赛标记清理边界
- rollback 审计与 bundle 身份
- Event `96` 遗漏
- JSON 数值词法丢失
- 大 JSON 导致内存超界
- 219 场同系列回退 Event 遗漏
- OperationLog 未绑定当前精确 bundle
- 完整 Event 集未在事务内围栏
- lossless 快照未重算逐行/整体 SHA
- snapshot 后未复核运行时 metadata

最近一次完整 review：

- 外层连续 reviewer 会话：`019f7bfb-2543-7523-aebd-3d496bc96422`
- 内层原生 review session：`019f7e38-ab9f-74e1-8932-f42f9c364a48`
- 命令：`codex review -c 'sandbox_mode="read-only"' --uncommitted`
- 内层启动头：`sandbox: read-only`
- 退出码：`0`
- 审前/审后 fingerprint：`60fdee883515b56fcc932084f58f6bb350054e8967828f96d4bfbdb229f1371b`
- 审前/审后完整 stdout：均 `145108` bytes
- stdout SHA-256：均 `4737811df3f938825f38e5993792f5ac38bca2066817d829a8367b3177ca70af`
- 逐字节一致：`true`
- 结论：`REVISE`

最近 review 的 3 项 finding：

1. P1：非动作源 Series `6019` 只有 ID 围栏，没有完整行 CAS。
2. P2：非 allowlist 的独立中文名如果含让赛标记，仍可能被 supplemental 更新覆盖。
3. P2：supplemental Event 未校验 `seriesKey`。

这三项已经在代码中修复，并补充负向测试：

- 全部 scope RaceSeries 保存 `beforeRowSha256`
- apply、verifier、rollback 都校验非动作父系列完整行
- 非 allowlist 独立中文名一律不进入 supplemental action
- supplemental Event 同时校验 series ID、key、地区

修复后尚未重新生成候选，因此尚未进入下一轮 review。

## 6. 当前真实状态与阻塞

### 6.1 没有可发布候选

`unified-import-preview-20260720T020815Z` 及更早目录都已经失效，不得 apply。尤其不得继续使用：

- 旧 Excel
- 旧 `manifest.json`
- 旧 `production-before.json`
- 旧 `dry-run.json`
- 旧 `rollback-before.json`
- 旧 `execution-plan.json`
- 旧 bundle index
- 旧 deterministic archive/receipt

虽然 `T020815Z` 当时显示 `apply_ready=true`，但后续 review 已证明其安全边界不完整，所以该状态不再有效。

### 6.2 两次新候选生成都安全失败

失败目录：

- `outputs/translate-race-names-20260719/unified-import-preview-20260720T064533Z`
- `outputs/translate-race-names-20260719/unified-import-preview-20260720T065115Z`

两个目录当前为空，不是候选：

- 第一次在完成生产快照后、第二次 runtime metadata SSH 时发生 multiplexed connection broken pipe / banner timeout。
- 工具随后增加 `ControlMaster=no`、`ControlPath=none`，确保前后 metadata 各用独立 SSH 连接。
- 第二次在第一次 runtime metadata SSH 就发生 banner timeout。
- 两次都没有生成 manifest、Excel、bundle 或其他可误用 artifact。

### 6.3 生产主机连接状态

最后检查结果：

- TCP/22：可以建立连接
- SSH：发送本地版本字符串后，服务器不返回 SSH banner，超时
- 从 Docker 容器直接读取 SSH banner：同样超时
- HTTP `/healthz/`：超时
- HTTPS：TLS 连接失败

这表明不是单纯本机 SSH ControlMaster 问题。可能是生产主机、sshd、网络代理或整机负载异常。

当前本机没有可用的 `aliyun` CLI，也没有在本任务中执行云主机重启。重启/控制台修复属于生产运维动作，接手模型不得在没有明确权限和可验证控制台上下文时猜测执行。

### 6.4 Git 状态

当前没有 commit、push、PR，也没有 staging。尚未执行：

- 生产数据库备份
- verify-only 连接生产数据库
- 正式 apply
- rollback
- 术语库写入
- 公开状态修改
- 部署或服务重启

## 7. 下一步要做什么

必须按以下顺序继续，不能跳步。

### 步骤 1：恢复并确认生产只读访问

先确认：

```bash
ssh -o BatchMode=yes \
  -o ConnectTimeout=15 \
  -o ControlMaster=no \
  -o ControlPath=none \
  root@47.239.167.86 'printf ready'
```

然后只读检查：

- `/opt/umanewsbot` checkout HEAD
- `umanewsbot-web-1` image ID/tag/started-at
- `/healthz/`
- 当前是否有外部部署或容器重建

不要为了本数据任务直接重启生产。若必须重启，先按运维文档确认当前 runner、Celery、数据库和其他任务状态，并取得相应权限。

### 步骤 2：重新生成全新候选

在专用 worktree 根目录执行：

```bash
CODEX_WORKSPACE_NODE_MODULES="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules" \
node runtime/tools/build_race_name_translation_import_preview.mjs
```

必须生成新的时间戳目录，不能覆盖或复制旧目录。

验收：

- 五份输入 SHA 全匹配
- 日本修订只出现 `C68` 一处业务变化
- production snapshot 前后 metadata 完全一致
- 两轮生产完整快照 SHA 一致
- lossless 每行 SHA 与整体 SHA 可重算
- `apply_ready=true`
- `blocker_count=0`
- 目标计数与当前生产事实一致
- `eventScope.series` 覆盖全部 `1301` 个父系列并带 `beforeRowSha256`
- `eventScope.events` 覆盖全部相关 Event
- 非 allowlist 独立中文名只在 out-of-scope report 中出现
- Event `96`、Event `16446`、Target `49052` 精确命中

### 步骤 3：重新做 Excel QA

新候选 Excel 应有 8 张表：

- 概览
- 阻断项
- 系列动作
- 年度赛事动作
- 身份修正
- 规则调整
- 跨系列同译名
- 输入锁

执行：

```bash
PYTHONPATH=runtime/tools \
/Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  -m unittest runtime.tools.test_compare_xlsx_layout -v
```

并完成：

- openpyxl 重载
- 公式错误扫描
- 所有工作表关键区域渲染
- 概览、Event 尾段、香港修正、Event `96`、219 场 fallback、完整父系列 scope 的人工抽检

### 步骤 4：重新打包 deterministic bundle

使用新目录的 `bundle-index.json` 原始 SHA，执行：

```bash
python3 runtime/tools/package_race_name_translation_bundle.py \
  --source <新候选目录> \
  --expected-bundle-index-sha256 <新 bundle-index 原始 SHA> \
  --output runtime/artifacts/race-name-translations/20260720/race-name-translation-bundle.tar.gz \
  --receipt runtime/artifacts/race-name-translations/20260720/race-name-translation-bundle.receipt.json
```

至少重复打包一次，证明 archive 逐字节一致。

正式 bundle 预期包含：

1. apply 工具
2. 独立 verifier
3. input lock
4. normalized input
5. manifest
6. production before
7. dry-run
8. rollback before
9. execution metadata
10. execution plan
11. artifact index
12. bundle index

### 步骤 5：重跑完整测试

最少重跑：

- Node 测试
- XLSX 布局测试
- SQLite Django 测试
- PostgreSQL 16 全量测试
- 生产规模性能测试
- `openspec validate --all --strict`
- `git diff --check`
- bundle 成员/receipt 校验
- apply/verifier CLI 从入口完成 bundle 校验并至少走到预期数据库连接边界

临时 PostgreSQL 容器和网络在测试结束后清理。

### 步骤 6：更新文档并冻结指纹

更新：

- `docs/current_state.md`
- `docs/project_status.md`
- `docs/decisions.md`（只有新决策时）
- `docs/deploy_runbook.md`
- 本交接文档
- `docs/changes/import-reviewed-race-name-translations/`

然后运行：

```bash
python3 .codex/scripts/review_fingerprint.py
```

### 步骤 7：回到同一 reviewer 连续复审

必须复用同一 reviewer 会话上下文：

- 外层 reviewer session：`019f7bfb-2543-7523-aebd-3d496bc96422`
- 上一内层 session：`019f7e38-ab9f-74e1-8932-f42f9c364a48`

唯一内层审核命令：

```bash
codex review -c 'sandbox_mode="read-only"' --uncommitted
```

审前、审后都运行仓库原生 helper，并逐字节比较完整 stdout。下一轮聚焦：

- 全部 scope RaceSeries 完整行 CAS
- 非 allowlist 独立中文名不覆盖
- supplemental seriesKey 门禁
- SSH non-multiplexing 只作为直接触及生成路径的回归

必须取得 `APPROVED`，且 actionable finding 清零。不能用普通 diff、测试通过或人工判断替代原生 review。

### 步骤 8：review 通过后重新取得用户发布授权

当前用户以前的“授权任何操作”发生在最新成功 review 之前，不能替代发布门禁。

最新 review 成功后，向用户明确报告：

- 新候选目录
- Excel SHA
- manifest/dry-run/rollback SHA
- bundle index/content/archive SHA
- 目标计数
- review session、指纹和结论
- 仍未写生产

然后要求用户针对该精确受审版本重新回复：

- “发布吧”或
- “上线”

没有这次新鲜授权，不得 staging、commit、备份或写生产。

### 步骤 9：获得授权后才进入发布

严格按 `docs/codex_workflow.md` 与 `docs/deploy_runbook.md`：

1. staging transition
2. 创建不可变提交
3. 从该提交导出并核对 bundle
4. 当前 PostgreSQL 16 custom-format 备份
5. 核对权限、大小、SHA、`pg_restore -l`
6. 宿主和容器复算 bundle index
7. verify-only
8. 再次复算 bundle
9. 单事务 apply
10. 独立 verifier
11. OperationLog、目标对象、让赛残留、`/healthz/`、页面抽检
12. evidence-only 文档回写与审核

本任务不需要部署新应用镜像或重启服务；正式动作是一次受控数据写入。若当前生产代码无法运行受审工具，应停止并重新设计发布路径，不能临时复制未提交脚本绕过提交身份。

## 8. 关键安全边界

- 所有旧候选均失效。
- 任何生产快照失败都必须生成 blocked/失败状态或不产出候选，不能复用旧快照。
- 输入哈希与解析必须使用同一份 bytes。
- 香港 Event 与历史目标只能同步更新，不能只改一侧。
- 不能修改 Event `original_name`。
- 不能覆盖已有独立中文名。
- 不能扩大到马名翻译。
- 不能修改赛事公开状态。
- 不能把相同中文名当作自动合并 RaceSeries 的依据。
- manual lock 任一命中都应阻断。
- CAS、唯一性、OperationLog 任一失败必须整批回滚。
- 对象 rollback 只在 after-state 完整匹配时允许；否则转人工事故处置。
- 生产备份、apply、部署属于不同授权层，不得混淆。

## 9. 交接完成标准

接手模型只有在以下全部完成后，才能宣告本任务发布完成：

- 生产只读连接恢复
- 新候选重新生成
- Excel 与 JSON QA 完成
- deterministic bundle 重建
- 全部测试通过
- 同一 reviewer 最新只读 review `APPROVED`
- review 后用户对精确版本重新授权
- staging/commit/bundle identity 一致
- 当前备份通过独立校验
- verify-only、apply、独立 verifier 全通过
- 生产对象、OperationLog、health、页面抽检通过
- 状态文档回写

在此之前，准确状态应表述为：

> 五区赛事中文名翻译输入和安全导入工具已完成，最新 review findings 已修复并通过本地/PostgreSQL 测试；当前等待生产 SSH 恢复以重生成只读候选，尚未形成可发布 bundle，尚未写入生产。
