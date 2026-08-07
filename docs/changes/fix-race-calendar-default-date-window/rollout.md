# 赛事日历默认比赛日窗口 rollout

## 当前阶段

本 change 当前仅获准探索、规格、设计和方案审核。尚未获准写测试、修改应用代码、启动实现
subagent、commit、push、PR、部署或生产写入。

独立方案 reviewer 首轮提出 3 项 P1：上海日期未贯穿今天标记、11 日全量赛事缺少 40 卡
边界、移动端锚点初始不可见。方案修订后复用同一 reviewer 会话限定复审，3 项均关闭，
结论为 `VERDICT: APPROVED`。残余实现风险是 ORM 代表赛事排序的跨数据库一致性，以及移动端
`scrollLeft` 真实行为；两项均已进入自动化/浏览器验收门禁。

面向 Claude/新实现 agent 的自包含交接已写入同目录

## 基线

- fetch 时间：2026-07-28；
- 基线：`origin/main@7385f59ab87bcce5193f3313ecca6809b165ad89`；
- worktree：`.worktrees/fix-race-calendar-default-date-window`；
- 分支：`codex/fix-race-calendar-default-date-window`；
- 建立时 HEAD、merge-base 与 `origin/main` 一致，工作树干净。

## 并行任务重叠

- `automate-race-event-lifecycle` 与 phase B worktree 没有修改日历 view、query service、
  template、CSS 或日历测试；阶段 A worktree 有未合并的
  `current_state/decisions/deploy_runbook/project_status` 追加。
- `impl-race-news-quality-20260726` 修改 `views.py`，但 hunk 位于公开新闻 feed，不在
  `_race_calendar_queryset/public_race_calendar`。
- 主仓库脏 worktree 基于旧提交，包含门户级 `views.py`、`race_calendar.html`、
  `public.css` 和测试大改，不能作为本任务基线或被覆盖。

集成顺序：本任务始终基于最新 main 做窄改；若旧门户改动仍需继续，应在本任务合入后 rebase，
再人工适配其模板/CSS，不得把旧版整文件覆盖回 main。生命周期状态文档在各自发布/证据收尾时
基于最新 main 重新追加，避免 cherry-pick 覆盖。

## 生效边界

仅改变动态 `/races/` 默认模式的日期选择，并用最小模板/CSS/内联脚本让横向日期轴的默认
锚点初始可见；40 卡响应体上限保持不变。显式 cursor、year、q 路径保持原产品语义。
不改变数据库、缓存配置、后台、任务调度或生产赛事记录。

## 发布前门禁

1. 用户在本次方案审核通过后明确授权实现；
2. 测试 subagent 取得真实 RED；
3. 实现 subagent 完成最小实现；
4. 主线程完成测试、检查、查询数和浏览器验收；
5. 未参与实现的 reviewer 在只读范围内审核通过并冻结 fingerprint；
6. 用户针对该 fingerprint 明确授权发布。

## 发布验收

- 默认入口以当前上海日期重新计算；
- 今日有赛事锚定今日，无赛事锚定最近未来，无未来回退最近历史；
- 日期栏最多 11 个实际比赛日且与列表公开资格一致；
- 高密度窗口仍最多 40 张卡且每个日期至少一张；
- 显式历史 cursor、year、q 仍有效；
- 跨月/跨年清晰，1440px/390px 锚点初始可见且纵向不跳动；
- 内外 healthz 与严重错误日志正常；
- 无 migration、无赛事业务数据写入。

## 回滚

这是无迁移、无配置、无数据写入的应用代码变更。异常时恢复上一应用 revision/镜像即可；
不恢复数据库。回滚后重新检查 `/races/`、healthz 和日志。
