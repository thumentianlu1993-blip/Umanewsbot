# 英国 racecard 级别后缀精确匹配 rollout

## 基线与边界

- worktree：`/Users/mentianlu/Code/umanews/.worktrees/realtime-racecard-identity-diagnosis`
- branch：`codex/realtime-racecard-identity-diagnosis`
- base：`origin/main@12d76e61850f1f847aba13ac1c07004040191728`
- 上一生产代码：`6646302b80c90cf406075516ab4812f2f4ebee18`
- 上一 evidence commit：`12d76e61850f1f847aba13ac1c07004040191728`

本 change 不复用旧 racecard worktree 的运行产物，不修改历史 runner/runtime，不读取或保存
TRA raw。探索阶段的一次单请求诊断仅输出客观白名单候选摘要，未写数据库或 artifact。

## 当前运行态

- 四个 app service 运行 racecard sync 生产镜像。
- `RACE_LIVE_SCHEDULER_ENABLED=false`。
- `RACE_LIVE_RUNNER_MODE=disabled`。
- `race_live` queue 为 0。
- event 924 prepare blocker run 没有 manifest，initializer 未执行。
- 赛事/runner/result 总量和 live fact 表未因 blocker run 改变；HostBudget 已存在。

## 阶段 1：方案审核

五份 artifacts 完成后进入独立方案审核。重点核对：

- 是否仍为 exact match，而非隐式 fuzzy；
- 级别 token 是否只由 `normalized_grade` 固定映射；
- 已批准名称末尾同级 token 是否只保留一次、异级是否整条排除、无 token 是否才派生；
- 错误级别、额外文字和非 G1-G3 是否 fail closed；
- series canonical 与 MajorRaceEvent 的正向和 active/year/汉字拒绝是否有隔离 RED；
- 是否无模型、migration、registry、parser、initializer 或 Compose 变化；
- event 924 当日窗口过期时的替代生产验收边界。

审核未 `APPROVED` 前不得写测试或业务代码。

方案审核结果：首次审核提出异级末尾 Group token 仍可能直接授权/双级别派生，以及 series
canonical/MajorRaceEvent 测试路径缺失；方案补为同级保留、异级排除、无 token 才派生的
三分支，并补齐隔离测试矩阵。同一 reviewer 限定复审已 `VERDICT: APPROVED`。

## 阶段 2：RED / GREEN

先取得 event 924 同形 `(Group 3)` 测试因现有 exact set 缺少 suffix variant 而失败。再由
实现 subagent 完成最小服务层改动，运行目标、受影响准实时、SQLite 与既有 PostgreSQL 回归。

执行结果：核心 RED 为 `('racecard_not_found',)`；实现只修改 racecard sync 服务并按
三分支生成确定性 suffix 变体。聚焦 `6/6`、racecard sync `19/19`、完整受影响 SQLite
`209/209`、一次性 PostgreSQL 16 `6/6` 通过，Django check、migration drift、语法和 diff
门禁为 0。没有真实联网、生产写入或开关变化。

首次原生代码 review 的唯一 P2 指出非末尾或多个 Group token 仍可能被派生/授权。修复前
新增测试真实 RED 为 3 个 subtest failure；实现改为扫描全部独立 token，只允许唯一、
terminal、同级 token 直接保留。修复后聚焦 `7/7`、racecard sync `20/20`、完整受影响
SQLite `210/210`，静态门禁为 0；等待同一 reviewer 会话限定复审。

## 阶段 3：代码审核与冻结

未参与实现的 reviewer subagent 必须执行原生只读 review。成功后记录 uncommitted scope 的
完整 fingerprint、approved parent 和 content hash；任何受审内容变化回到同一 reviewer 限定

## 阶段 4：生产代码部署

- 先备份并验证恢复点。
- 构建与冻结 commit/review tree 一致的 AMD64 镜像。
- 本变更无 migration，但仍运行 Django check、migration drift 和目标测试。
- web/worker/Beat 不挂 secret/artifact；只有 `race_live_worker` 保持既有挂载。
- scheduler、runner、global/region/source/event public policy 全部保持关闭。

## 阶段 5：受控 prepare

优先条件：

- 若 event 924 仍处于 Europe/London 的 today 窗口且 baseline 未漂移，可用新 run-id 重跑；
- 否则选择下一个 today/tomorrow 内、生产已存在且明确为英国 G1-G3 的 event；
- 只选择已通过只读候选摘要证明 base name + 同级别 Group 后缀的赛事。

prepare 沿用既有固定路由、registry/terms/evidence、最多两个请求、共享 HostBudget 和原子
artifact。零命中、多命中或任一 blocker 均停止。成功只得到待审核 manifest；不自动执行
initializer。

## 回滚与停止条件

- 方案/代码审核失败：不进入下一阶段。
- RED 不是目标能力缺失：修复测试后重新取得真实 RED。
- 任何模型、migration、registry、parser 或网络预算需求：回到 design 并重新方案审核。
- 生产候选级别、日期、赛场或 base name 不精确：不运行 prepare。
- 代码部署异常：保持 flags off，回滚上一镜像。
- prepare blocker：保留 artifact，业务事实零变化。
- manifest 成功：停在单独审核节点；没有新的 manifest apply 授权不得初始化。
