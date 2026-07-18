# 准实时赛前 racecard/off time 同步 rollout

## 当前基线

- worktree：`/Users/mentianlu/Code/umanews/.worktrees/realtime-racecard-sync`
- branch：`codex/realtime-racecard-sync`
- base：`origin/main@234358979dea3620d04445bb569b30e4a5b2fe8a`
- 该 base 相对准实时发布收尾包含赛事距离展示单位修复和历史赛事发布 evidence 文档；
  未改变 live 模型、initializer、runner 或队列。

生产准实时基线已经部署，但：

- `RACE_LIVE_SCHEDULER_ENABLED=false`
- `RACE_LIVE_RUNNER_MODE=disabled`
- live queue 和 live 业务表为空
- 未来赛事缺少 `race_datetime`

本变更不读取历史抓取 runtime，不接管历史 runner，不连接生产写入。

## 阶段 1：方案审核

入口：本目录五份 artifacts 完成。

验收：

- 来源字段、唯一匹配、事务边界和 replay 语义明确；
- 不把 manifest prepare 误当自动初始化；
- schema v1 兼容；
- raw/secret/版权边界明确；
- PostgreSQL 竞争与回滚测试完整。
- HostBudget bootstrap/动态复用、registry 路由升级、Europe/London、tracking 状态晋级和
  容器 artifact 闭环可执行。

未通过前不得编写业务实现。

审核结果：同一方案 reviewer 在两轮限定复审后确认 `APPROVED`；HostBudget、registry、
Europe/London、schema v2 CAS/replay、artifact 隔离及 pre-off claim checkpoint 的
actionable findings 已全部关闭。

## 阶段 2：RED

按 `test_cases.md` 先新增 parser、matching、artifact、initializer v2 和 PostgreSQL 测试。
必须看到目标行为缺失导致失败；现有 baseline 或环境失败不能充当 RED。

RED 通过后才交实现 subagent。

## 阶段 3：实现与 GREEN

实现文件预计限定为：

- `server/stable/services/race_live_fixtures.py`
- `server/stable/services/race_live_racecard_sync.py`
- `server/stable/services/race_live_initialization.py`
- `server/stable/services/race_events.py`
- `server/stable/services/race_live_runner.py`
- `server/stable/services/race_live_source_proof.py`
- `server/stable/management/commands/prepare_race_live_racecards.py`
- `server/app/settings.py`
- `docs/changes/realtime-race-results/source_registry_the_racing_api_free.json`
- `Dockerfile`、`.env.example`、三份 Compose
- 新增/变更的准实时测试
- 本 change 与必要状态/决策文档

无模型变化时不新增 migration。若实现发现必须改模型，立即停止并回到 design/测试更新，
不得临时夹带 migration。

实现结果：未新增模型或 migration；SQLite 受影响组合 `203/203`、一次性本地
PostgreSQL 16 `6/6` 通过，registry digest 更新为
`60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。真实网络、生产
prepare/initializer 和开关变更均未执行。

首次代码 review 的两个 P2 已按限定 RED/GREEN 修复：同 run-id 发布采用 root 锁和
device/inode 所有权清理；event 占用检查改为八类固定批量查询。复审必须复用原 reviewer
session，只核对这两项、对应测试及直接触及路径。

## 阶段 4：独立代码审核

- 首次代码审核使用未参与实现的 reviewer subagent。
- 实际命令为：
  `codex review -c 'sandbox_mode="read-only"' --uncommitted`
- review 前后用仓库 helper 对相同 uncommitted scope 计算完整 fingerprint。
- findings 由实现 subagent 修复；复审复用同一 reviewer 会话。

## 阶段 5：发布授权

代码 review 成功后停止，等待用户对本任务最新冻结内容明确授权。

授权前禁止：

- commit/push/PR；
- 部署或重启；
- 生产网络 prepare；
- initializer dry-run/apply/verify；
- 修改生产 flags。

## 阶段 6：代码部署

代码部署本身保持所有准实时开关关闭。验收：

- 镜像 revision 与 reviewed commit 一致；
- secret 仍只挂载给 `race_live_worker`；
- artifact root 只以 rw 挂载给 `race_live_worker`，web/worker/beat 无 secret；
- production expected registry SHA 已更新为镜像内新 tracked registry digest；
- Django check、migration drift、目标测试通过；
- 普通 worker/历史 runner 不受影响；
- healthz 正常。

## 阶段 7：生产受控 prepare

在获准代码上选择显式英国 event IDs，运行 prepare：

- 最多两个 Free 请求；
- 只 bootstrap/更新 HostBudget 控制面，RaceEvent/runner/result/live facts 零写入；
- 输出 manifest/report/requests；
- 审核所有 SHA、唯一匹配依据、participant 数量和 blocker。

出现以下任一条件停止：

- 零命中或多命中；
- source schema/registry/terms drift；
- event baseline/人工锁/时间冲突；
- event status/local date/timezone 不精确，尤其 timezone 非 `Europe/London`；
- runner ID/name/number 缺失或重复；
- 非英国 racecard。

## 阶段 8：Initializer

只有精确 manifest 单独获准后：

1. 默认 dry-run。
2. 核对业务总量与所有 live 表基线。
3. `--apply --confirm-apply`。
4. `--verify` 必须 `ok=true/error_count=0`。
5. 重放 apply 必须零新增。
6. 核对 `RaceEvent` 时间、participant、racecard revision、policy 全为 shadow，
   result observation/revision/publication/incident 和 `RaceEventResult` 仍为零。
7. HostBudget 可保留 prepare 的动态 next-allowed/circuit/counter；只要求固定 host 和
   1050ms 配置正确。

初始化结束后 scheduler/runner 仍关闭。

## 阶段 9：后续英国 shadow

不属于本变更的直接发布动作。另行完成：

- shadow 启动检查；
- runner 切到 `the_racing_api_free`；
- scheduler 开启；
- 至少 10 场、其中 3 场重点赛事；
- P50/P95、identity、完整性、失败降级和前台零泄漏验收。

## 回滚

### 代码部署前

删除未提交 worktree 即可；生产零变化。

### 仅部署代码

保持开关关闭即可，无数据库回滚。

### Prepare 后

保留完成 artifact；赛事业务事实零变化，HostBudget 控制面会保留请求 reservation/outcome。

### Initializer apply 后

- 首先保持 scheduler/runner off。
- 使用现有赛事级 CAS kill switch 停用 tracking。
- 不删除 observation/revision/OperationLog 审计。
- 若初始化事务已成功但 manifest 后续被撤销，必须通过单独受审的 ownership/数据回滚
  方案处理；不得手工删 live 行或把时间字段改回 null。

## 精确生产路径

- 宿主 artifact root：
  `/opt/umanewsbot/runtime/race_live_racecards`，`root:root 0700`。
- 容器 root：
  `/run/race-live/racecards`。
- prepare 只从 one-off `race_live_worker` service 执行，使其同时拥有 secret ro、
  artifact rw、DB/Redis 网络；不得从 web 执行。
- initializer 继续从 one-off web 执行，只 bind 选定的完整 run 目录为 ro，以目录内
  `manifest.json` 为入口并重算 sibling SHA；不挂载 secret。
- 最终生产命令和新 registry SHA 在 `docs/deploy_runbook.md` 于代码 review 前补齐，
  并纳入同一冻结范围。
