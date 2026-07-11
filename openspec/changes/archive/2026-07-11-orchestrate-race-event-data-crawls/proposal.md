## Why

现有赛事资料抓取已经证明可行，但抓取器、候选生成、覆盖审计、生产 dry-run 和正式 apply 分散在 `runtime/tools/` 与多个管理命令中，继续做长期历史回填时容易出现重复抓取、覆盖缺口、错误候选覆盖正式资料或生产运行不可续跑的问题。

现在需要把这些已跑通的经验固化为一个正式、可审计、可断点续跑的编排工具；只有该工具通过验收后，才进入日本、香港、英国、法国、美国五个目标地区的分批历史赛事信息回填。

## What Changes

- 新增一个正式赛事信息编排入口，统一管理“计划生成 -> 来源抓取/复用缓存 -> 候选 JSONL 生成 -> review CSV/summary 输出 -> 覆盖审计 -> Django dry-run -> 人工确认后 apply”的流程。
- 将现有 `runtime/tools/prepare_*race_detail_candidates.py`、gap、history winner 生成脚本纳入可被编排工具调用的适配层，保留现有来源解析逻辑，不在第一版重写所有地区抓取器。
- 新增批次运行目录规范，要求每次运行产出 plan、source cache、candidate JSONL、review CSV、summary、coverage audit、dry-run/apply 记录和可恢复 state。
- 为长期历史回填增加地区、来源、赛事系列、年份范围和模块维度的拆批能力，支持先生成计划和命令清单，后低频执行具体批次。
- 第一版编排目标限定为 `RaceEvent*` 产品层，不写入 `ExternalRace*` 外部数据库缓存层。
- 第一版必须覆盖 `runners`、`results`、`history_winners` 三个模块；历史回填时三类数据的目标历史深度必须一致，不能只把历届冠军追到深历史而把出走表/赛果停在浅层。
- 第一版目标地区为日本、香港、英国、法国、美国；第一验收批次必须每个地区各抽少数核心赛事系列参与，防止只在单一地区跑通。
- 目标赛事集合第一阶段只包含核心 Group/Grade/Jpn/交流分级/障碍分级等重点赛事，不包含 `Listed / Listed Race`，也不追所有普通比赛。
- 日本范围包括 JRA 中央平地分级、JRA 障碍分级 `JG1/JG2/JG3`、NAR/地方交流重赏、ダートグレード和 `Jpn1/Jpn2/Jpn3`，并在 plan/coverage 中分开统计。
- 历史赛事系列必须通过显式 `series_key` / mapping 绑定；名称模糊匹配只能生成待审候选，不得直接写入正式 `RaceEventRunner`、`RaceEventResult` 或 `RaceEventHistoryWinner`。
- 官方源优先，但允许受控使用高可访问第三方源；每个候选和审计摘要必须显式记录来源权威等级，不得把第三方源伪装成官方源。
- 对生产写入保持强门禁：正式 apply 前必须通过覆盖审计、无重复/无跨源污染检查、Django dry-run、外部导入锁检查、数据库备份与人工确认。
- 验收通过前不得开启长周期历史回填；验收通过后，使用该工具分阶段回填历史赛事出走表、赛果和历届冠军。日本历史方向为追溯至分级制度建立时；香港、英国、法国、美国的历史起点在第一验收批次完成后，按来源可访问性、赛事制度边界和 series mapping 结果分别锁定。
- 第一版不新增公开页面形态，不改变新闻抓取、翻译、自动发布或 QQ 推送策略。

## Grill-Locked Boundaries

- 数据层：第一版只服务 `RaceEvent*` 产品层；`ExternalRace*` 继续属于外部数据库导入体系，不在本变更中写入。
- 模块：`runners`、`results`、`history_winners` 均为第一版范围，且同一目标赛事范围内三者历史深度一致。
- 缺口：允许部分候选存在，但 coverage audit 必须把缺 `runners`、缺 `results`、缺 `history_winners` 的赛事年份标为 incomplete/gap，不得伪装为完成。
- 范围：五个目标地区为日本、香港、英国、法国、美国；第一阶段不包含 Listed，不覆盖所有普通比赛。
- 验收：每个目标地区都要选择少数核心赛事系列参与第一批验收，并同时跑通三模块 plan、candidate、coverage audit 和 dry-run 门禁。
- 运行：长周期历史抓取默认通过手动分批或一次性容器执行，不加入 Celery Beat，也不做常驻后台自动调度。
- 写入：每个“地区 + 来源 + 模块组合”的首批必须人工确认；后续同组合批次可在全绿门禁下继续执行显式 apply 命令，但不得无人值守自动 apply。
- 覆盖：已有正式数据默认进入 diff/review；任何覆盖必须按模块、来源权威性、完整性和人工确认判断。
- 可见性：补充到已公开 `RaceEvent` 的结构化数据可以随现有页面展示；新建或新匹配的年度赛事不自动公开，编排工具不改变赛事可见性。

## Capabilities

### New Capabilities

- `race-event-data-crawl-orchestration`: 规范赛事信息抓取编排、批次产物、覆盖审计、断点续跑、dry-run/apply 门禁和历史回填执行边界。

### Modified Capabilities

- `race-event-pages`: 明确赛事详情候选资料批量生成与应用必须通过编排工具或等价审计产物，避免未审计候选覆盖公开赛事资料。
- `real-global-racing-data-ingestion`: 明确长期历史赛事信息回填与真实外部数据库抓取共享限速、锁、dry-run、备份和 proof/commit 边界，但回填 `RaceEvent*` 产品层数据不得被误认为写入 `External*` 外部缓存。

## Impact

- 代码范围：
  - `server/stable/management/commands/`：新增或扩展赛事抓取编排管理命令。
  - `server/stable/services/`：新增编排、审计、批次状态和适配器封装服务。
  - `runtime/tools/`：保留现有抓取/候选生成脚本，必要时做最小接口化调整。
  - `server/stable/tests/`：补充计划生成、覆盖审计、dry-run 门禁、断点续跑和安全失败测试。
- 数据范围：
  - 默认产物写入 `runtime/race_event_crawl_runs/` 或等价运行目录。
  - 生产正式写入仍通过现有 `RaceEventDataCandidate`、`RaceEventRunner`、`RaceEventResult`、`RaceEventHistoryWinner` 应用链路完成。
- 运维范围：
  - 更新 `docs/current_state.md`、`docs/project_status.md` 和 `docs/deploy_runbook.md`，记录工具验收、生产门禁和后续历史回填运行策略。
  - 长周期抓取必须低频、可暂停、可恢复，不得与部署、外部数据导入或生产窗口高峰重叠。
