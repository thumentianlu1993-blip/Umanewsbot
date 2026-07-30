# `fix-single-migration-owner` 代码审核交接（REVIEW_HANDOFF）

本文档是独立的代码审核交接：读者不需要任何其他上下文即可理解任务、范围、证据与审核要求。
审核者须全程只读：禁止 commit/push/PR、禁止部署/迁移/启动容器、禁止联网、禁止修改任何文件。

## 1. 仓库与工作区

- 仓库：`/Users/mentianlu/Code/umanews`（Django + PostgreSQL/SQLite + Celery + Redis + Docker Compose 的中文赛马新闻平台）
- 工作区（git worktree）：`/Users/mentianlu/Code/umanews/.worktrees/fix-single-migration-owner`
- 分支：`codex/fix-single-migration-owner`
- HEAD（当前基线）：`6d073dc07cb29201bbc922255923820c872a0467`（= 2026-07-30 re-baseline 后的 origin/main）
- 原 approved parent：`7385f59ab87bcce5193f3313ecca6809b165ad89`（设计/首轮审核基线，已被基线迁移取代）
- 工作流：Codex 原生（见根 `AGENTS.md` 与 `docs/codex_workflow.md` 第 7 节），禁止 OpenSpec
- 本 change 详细规范：同目录 `spec.md`、`design.md`、`test_cases.md`、`tasks.md`、`rollout.md`、`HANDOFF.md`

## 2. 根因（要修的问题）

修复前 main 上数据库迁移有多个执行者，且可真正并发：

- `deploy/docker/start-web.sh`：web 容器启动入口执行 `migrate` + `collectstatic`；
- `deploy/deploy.sh` / `deploy_lowcost.sh`：`compose up -d web` 后再 `compose exec web python manage.py migrate --noinput`（+collectstatic）；
- `deploy/rollback.sh` / `rollback_lowcost.sh`：`up web` 后再 `exec web migrate`。

`compose up -d` 不等待容器入口脚本完成，因此随后的 `exec web migrate` 可与容器主进程里的
`migrate` 并发。两个 MigrationExecutor 可同时判定某 migration 未应用并竞争执行同一 DDL。
真实生产预检曾因此把 additive migration 判为 `DuplicateTable` 风险并安全停止。

## 3. 锁定的实现方案（已实现）

“显式一次性 release task”为唯一 migration owner：

```text
deploy/rollback/manual 顶层入口
  -> 主机级部署锁（mkdir 原子，verify 用 token SHA-256，失败者不装 trap 不碰赢家锁）
  -> historical preflight / build / checkout / contract 校验
  -> 冻结 worker + race_live_worker 运行态
  -> stop beat -> Celery drain（expected node 完整快照）-> stop worker
  ->（原本 running 才）stop race_live_worker -> stop web
  -> deploy/run_release_tasks.sh（验锁后恰好一次
     compose run --rm --no-deps web /app/deploy/docker/run-release-tasks.sh）
       -> 容器内：wait_for_services -> migrate --noinput -> collectstatic --noinput
  -> up -d --no-deps web -> 有界等待精确 "true healthy"（硬门禁）
  -> up -d --no-deps worker beat nginx
  -> race_live_worker 仅按原始 running 状态恢复
```

- `start-web.sh` 只保留 wait_for_services、可选 seed_admin、`exec gunicorn`；
- 通用 rollback 在任何 checkout/停服前用 `git cat-file -e <ref>:deploy/release_contract_v1`
  校验目标 ref 含 contract marker，缺失即拒绝；
- 首次发布回退 pre-contract 版本走 `deploy/rollback_pre_single_owner.sh`：不 checkout 旧 ref、
  不跑新 one-shot，恢复冻结旧 image，旧 image 的单个 web 主进程是唯一 migration owner；
- `deploy/manual_release.sh`：四门应用服务（web/worker/beat/race_live_worker）全部可验证为
  非运行时才允许在锁内调一次 release wrapper，完成后不启动任何服务；
- 文档明确：forward migrate ≠ 数据库回退；`HISTORICAL_RUNNER_INITIAL_INSTALL` 不是
  greenfield 全新站点安装。

## 4. 变更范围（精确全集）

新增（untracked）：

- `deploy/docker/run-release-tasks.sh`（唯一 migration/collectstatic 命令所在）
- `deploy/run_release_tasks.sh`（宿主受保护 wrapper：COMPOSE_FILE allowlist + 锁 token 验证）
- `deploy/deployment_lock.sh`（acquire/verify/release；元数据只含 pid/action/UTC/compose 文件/token SHA-256）
- `deploy/wait_for_compose_service_healthy.sh`（仅 web；精确 `true healthy` 才返回 0）
- `deploy/run_application_release.sh`（共享编排，顺序见上）
- `deploy/manual_release.sh`
- `deploy/resume_stopped_release.sh`（受审服务恢复入口，action=resume-release）
- `deploy/race_live_state.sh`（冻结意图六字段写入/可信校验共享函数）
- `deploy/rollback_pre_single_owner.sh`
- `deploy/release_contract_v1`（空 marker）
- `server/stable/test_single_migration_owner.py`（117 用例，fake docker/git/python + 真实 shell
  harness；re-baseline 后曾为 97 用例）
- `docs/changes/fix-single-migration-owner/`（规划文档 + 本文档）

修改（tracked）：

- `deploy/docker/start-web.sh`（删 migrate/collectstatic 两行）
- `deploy/deploy.sh`、`deploy/deploy_lowcost.sh`（锁 → preflight → pull/build → 共享编排）
- `deploy/rollback.sh`、`deploy/rollback_lowcost.sh`（锁 → ref/marker 校验 → preflight → checkout/build → 共享编排）
- `deploy/wait_for_celery_drain.sh`（新增 EXPECTED_CELERY_WORKERS 精确节点完整性核对）
- `server/stable/test_historical_batch_runner_change.py`（仅 `test_ordinary_deploy_is_no_deps_and_never_bootstraps` 一个方法，断言跟随新架构：入口含 preflight+编排调用，编排含 drain+--no-deps）
- `docs/deploy_production.md`、`docs/rollback_guide.md`、`docs/deploy_runbook.md`、`docs/current_state.md`、`docs/project_status.md`（`docs/decisions.md` 的 diff 为规划阶段既有改动）

明确未触碰：`server/stable/models.py`、`tasks.py`、全部 migrations、两份 Compose 文件、
Celery/Beat 配置、lifecycle/race-live 业务代码。

### 4.1 基线迁移（re-baseline，2026-07-30）

- 原基线 `7385f59ab87bcce5193f3313ecca6809b165ad89` -> 最终基线
  `6d073dc07cb29201bbc922255923820c872a0467`，worktree 原地迁移分三跳完成：
  第一跳 `7385f59` -> `7cd144ab`（main 增量 65 文件，含 race-calendar 日期窗口、
  race-news 质量治理、`harden-celery-p0-admission` 等）；第二跳 `7cd144ab` -> `be1c89bf`
  （PR #47 `fix-p0-queue-snapshot-output`，增量为 p0 脚本与其合同测试及 3 份状态文档）；
  第三跳 `be1c89bf` -> `6d073dc0`（PR #48，纯文档增量：p0 release_report 与
  current_state/deploy_runbook/project_status，无代码变化，p0 例外前提不受影响）。
  三跳均由主线程 reset --mixed + 重叠文档三方合并完成，零冲突。p0 例外前提在最终
  脚本上复核仍成立：1 次 collectstatic、0 migrate、2 次 `verify_migration_plan_zero` 调用。
- 4 份重叠文档（`docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、
  `docs/decisions.md`）的重叠区域已由主线程三方合并完成，本节起仅追加本 change 内容。
- main 新增的 `deploy/deploy_race_live_p0_closed.sh`（race-live P0 closed-admission 一次性
  脚本）含有 `collectstatic --noinput`，与 T02 单一所有者断言冲突；经用户批准登记为
  显式例外（前提：不含 migrate、`verify_migration_plan_zero` 恰好两次、collectstatic 在
  `up web` 之前单进程执行），T01/T02 合同断言已按该批准同步修订。
- p0 合同测试（`harden-celery-p0-admission` 自带）与本套件不冲突：两者各自断言自己
  的脚本集合，p0 侧不扫描本 change 的 release-task 文件，本侧 T01/T02 已豁免该例外文件。
- 迁移后聚焦套件终值为 97 用例；全部 deploy/ 脚本与本 change 语义在增量上重新验证。

## 5. 测试与验证证据

RED/GREEN（命令均在 `server/` 下：`../.venv/bin/python manage.py test stable.test_single_migration_owner`）：

- RED-1（2026-07-28T15:40Z）：70 用例 / 59 failures，全部为真实能力缺口（新脚本缺失、
  migrate 五处 owner、start-web 仍迁移），exit=1；
- GREEN-1：69/70 后修复一处测试 harness 自身命名 bug（fake docker 的 per-container rc 文件名
  与 `set_rc` 约定不一致，已自证注入 load-bearing）→ 70/70 OK；
- RED-2（review findings）：新增 7 用例 / 8 failures（P2-1 ps 探测 fail-open ×3、锁顺序/元数据 ×4、
  manual restarting 死代码 ×1）；
- GREEN-2：77/77 OK，exit 0；
- RED-3（第 3 轮 Codex 原生 review findings）：新增 10 用例 / 16 failures（P1-1 race-live
  跨重试状态 ×2、P1-2 bridge schema 门禁 ×3、P2-3 v1 helper 校验 ×2、P2-4 不可变 OID ×2、
  P2-5 inspect 输出合法性 ×4、P3-6/P3-7 文档同步 ×3）；
- GREEN-3：87/87 OK，exit 0（T12 两个成功用例由主线程补传显式 schema 门禁值后矛盾消除）；
- RED-4（第 4 轮复审 findings）：新增/修订 10 方法 / 14 failures（P1 race-live 重试语义 ×4、
  P2 helper 清单扩 9 路径 ×1、P2 OID 显式格式校验 ×4、P2 OID 绑定断言更新 ×2、P3 文档
  残留 ×3）；
- GREEN-4：14 项 RED 全部修复转绿；剩余 2 项失败为测试文件内部张力——T11 两个成功用例
  （`test_t11_standard/lowcost_rollback_with_contract_uses_shared_release`）未给 fake
  rev-parse 准备 `git-rev-parse-output`（空输出、rc 0），与 malformed-OID 的 `empty`
  子例可观察输入完全相同却期望相反结果，需测试侧为 T11 补固定 OID（同第 3 轮 T12 的
  修法）后即为 **96/96 OK，exit 0**。

主线程验证（全部实际执行）：

| 验证 | 结果 |
|---|---|
| `test_single_migration_owner`（旧基线） | 96/96（T11 两例由主线程补 `git-rev-parse-output` 后转绿） |
| `test_single_migration_owner`（最终基线 6d073dc0，97 用例） | 97/97，主线程复跑确认 |
| `test_single_migration_owner`（第 5 轮 findings 修复后，113 用例） | 113/113 OK |
| `test_race_live_p0_deployment_contract`（p0 套件，含 2 项新锁用例） | 35/35 OK |
| `test_single_migration_owner`（第 6 轮修复后，117 用例） | 117/117 OK（GREEN-6；RED-6 为 117 tests/3 failures） |
| p0 合同套件（`harden-celery-p0-admission` 自带，新基线） | 33/33 OK，主线程确认 |
| 相邻回归（新 main 干净基线对照） | 与新 main 干净基线逐条一致，主线程确认 |
| 相邻回归 `test_historical_batch_runner_change` + `test_historical_race_detail_runner_v2_contract`（99 tests） | 与实现前基线逐条一致（13 errors + 1 failure 均为 pre-existing 环境性失败：`python` 不在 PATH 等，基线清单已存档 `/tmp/smo_baseline_failures.txt` 对照） |
| `sh -n deploy/*.sh deploy/docker/*.sh` | 通过 |
| `manage.py check` | 0 issues |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `git diff --check` | 通过 |
| 唯一 owner 证据：`rg -n "manage\.py migrate --noinput\|manage\.py collectstatic --noinput" . --glob '!docs/**' --glob '!openspec/**' --glob '!.git/**' --glob '!.venv/**'` | 仅命中 `deploy/docker/run-release-tasks.sh:10-11` 各一次（另两处为测试断言字符串） |
| 两份 `compose config`（T16，本机真实 docker CLI + 临时无敏感 env） | 通过 |

明确未验证项：**真实本地 Compose 的正常/重放/失败三路径未执行**。本机 Docker daemon 可用，
隔离环境已准备过（本地镜像 COPY-only 构建 `umanewsbot:prod`、独立 project `smo-local`、
gitignored 临时 dummy `.env`），但执行真实 `manage.py migrate` 被会话权限边界拒绝
（用户当前授权禁止迁移），未绕过；全部临时资源已清理。发布前如需本地彩排需用户显式放行。

## 6. 既有审核轮次

- 方案审核：规划阶段同一 reviewer 三轮，最终 APPROVED，无开放 P0/P1；
- 代码审核第 1 轮（独立 reviewer，未参与实现）：**REVISE**。findings：
  - P2-1（已修复关闭）：三处服务状态探测用 `|| true` 吞掉 `compose ps -q` 失败，
    fail-open 成 not-running；已改为区分 ps 调用失败（fail closed）与空输出；
  - P2-2（接受为残余/后续项）：rollback checkout 替换执行中脚本自身，pre-existing 模式；
  - P3-1（关闭）：manual_release 的 restarting 检测误用 Health.Status 字段（死代码），
    改为 State.Status 第三列；
  - P3-2（关闭）：deploy 两脚本锁 acquire 移到 historical preflight 之前（spec 5.4）；
  - P3-3（关闭）：drain expected node 子串匹配改精确匹配（全等或 `@` 后缀相等）；
  - P3-4（关闭）：五处锁 acquire 均传 COMPOSE_FILE，元数据 compose_file 非空；
  - P3-5（关闭）：pre-contract 桥在停服前 `docker image inspect` 自检冻结 tag；
- 代码审核第 2 轮（同一 reviewer 会话，复审仅覆盖上述 findings 与直接触及路径）：**APPROVED**。
- 代码审核第 3 轮（Codex 原生 review）：**REVISE**。findings 及修复：
  - P1-1（已修复）：race_live 冻结状态写入 `${DEPLOYMENT_LOCK_DIR}.race-live-state`
    （state/node/compose 文件/冻结 UTC 时间），重试时复用不再 probe，成功完成后删除，
    失败保留（`run_application_release.sh` 与 `rollback_pre_single_owner.sh`）；
  - P1-2（已修复）：bridge 的 `SCHEMA_COMPATIBLE_WITH_TARGET` 必须显式为 `true`/`false`，
    未设置/空/其他值在 image inspect 与任何停服/probe 之前非零退出；
  - P2-3（已修复）：两条 rollback 在 checkout 前对全部 8 个 v1 路径逐一
    `git cat-file -e`（marker + 全部 helper），任一缺失零 checkout 零停服；
  - P2-4（已修复）：`TARGET_OID` 一次解析，cat-file 与 checkout 全部绑定不可变 OID；
  - P2-5（已修复）：编排/手工/桥三处 probe 的 running 字段必须为精确 `true`/`false`，
    空串/未知输出 fail closed；
  - P3-6（已修复）：`docs/deploy_production.md` 顺序更正为 获取部署锁 → historical
    preflight；
  - P3-7（已修复）：`spec.md`/`tasks.md`/`deploy_runbook.md`/`current_state.md`/
    `project_status.md`/本文档状态同步（87 用例）。
- 代码审核第 4 轮（同一 reviewer 会话复审）：**REVISE**。findings 及修复：
  - P1（已修复）：race-live 重试语义——冻结状态文件只决定恢复意图；每次尝试仍重新
    probe 当前运行态决定停止与 drain expected nodes，文件存在时 probe 失败同样
    fail closed；frozen=not-running + current=running 时 release/tag 前必须停
    race_live 且当前 node 进 drain，frozen=running + current=not-running 时不重复
    stop、成功后恢复一次（编排与桥同构）；
  - P2（已修复）：v1 helper 校验从 8 扩到 9 个路径（新增
    `deploy/docker/compose-wrapper.sh`）；`TARGET_OID` 必须为单行 40 位小写十六
    进制，空/多行/非 hex/带垃圾行在任何 cat-file、preflight、checkout 之前非零；
  - P3（已修复）：`design.md` §3.6 改为准确描述状态文件重试语义；
    `deploy_runbook.md`/`rollback_guide.md` 的 rollback 描述改为不可变 OID；
    本文档与两份状态文档同步（96 用例）。
- 代码审核第 5 轮（同一 reviewer 会话复审）：**REVISE**。RED-5：owner 套件 113 tests/17
  failures、p0 套件 35 tests/2 failures。findings 及修复：
  - P1-1（已修复）：`deploy/deploy_race_live_p0_closed.sh` 接入共享部署锁（action
    `p0-closed-admission`），acquire 在首个有状态调用之前、成功才装 trap，on_exit 统一
    释放；锁 action allowlist 扩入 `p0-closed-admission` 与 `resume-release`；
  - P1-2（已修复）：新增 `deploy/resume_stopped_release.sh` 受审恢复入口（共享锁、
    四服务停止门禁、web->healthy->下游顺序、绝不调用 one-shot、按可信意图恢复
    race_live，无效意图告警跳过但核心照恢复）；
  - P1-3（已修复）：冻结意图改六字段绑定（state/node/compose_file/action/head/
    frozen_at_utc，mode 600），共享 `deploy/race_live_state.sh` 写入与校验（非
    symlink、当前用户属主、group/other 零权限、compose/head/action 绑定）；编排/桥
    校验失败在任何 stop 前 fail closed；权限校验用 stat 末两位必须为 00（`find -perm
    -0077` 语义过窄，0620 会漏网）。
- 代码审核第 6 轮（同一 reviewer 会话复审）：**REVISE**。findings 及修复：
  - P1（已修复）：resume 对可信意图文件改为全链路消费后删除——通过可信校验的意图
    文件在全部恢复步骤与最终 `ps` 成功之后删除，running 与 not-running 一致；不可信
    文件保留人工核对；中途失败保留（`deploy/resume_stopped_release.sh`）；
  - P2（记录为后续建议，本轮不扩大范围、不改代码）：
    1. `race_live_state.sh` 属主检查 `find` 报错时 fail open（建议显式处理 find 非零）；
    2. 意图六字段未强制唯一完整（建议校验每字段恰好一次且无未知字段）；
    3. 编排 `RELEASE_ACTION` 缺省 deploy 可改必填（建议缺省即 fail closed）；
    4. resume 启动 web 后 healthy 失败会留下运行中 web 的中间态（建议文档化恢复
       路径或失败时可选回停）。
- 注意：前两轮代码审核因本机无 `codex` CLI，原生 `codex review` 命令未执行，
  为人工只读审查 + fingerprint helper；第 3 轮为 Codex 原生 review。

## 7. 指纹（重要）

基线迁移使此前全部冻结指纹失效；新指纹必须在第 7 轮复审确认本 change 在
`6d073dc07cb29201bbc922255923820c872a0467` 上的最终状态后重新冻结，发布授权只针对该新指纹。

第 6 轮 REVISE findings 已修复并通过 117/117；历史各轮修复均已完成，**新指纹尚未冻结**：
需同一 reviewer 会话做第 7 轮复审确认本批修复后重新冻结，发布授权必须针对复审后的新指纹。

历史冻结基线（已失效，仅作记录）：

- FINGERPRINT_SHA256：`7abf5be18a57c25429b566b7f0d9c33045d038d7df7742f726ebbb1007c03fa7`
- content_manifest_sha256：`716f647f98c7d6db3a2e819551055fcbfde9d2ef4cf6344422ccff1c7b581a43`
- head：`7385f59ab87bcce5193f3313ecca6809b165ad89`

本轮审核通过后的新冻结指纹即当前任务最新审核基线，发布授权必须针对该新指纹。

## 8. 残余风险与已知项（非 actionable，供审核者核对是否认可）

1. 部署锁为单宿主 `/tmp` 目录（`DEPLOYMENT_LOCK_DIR` 默认 `/tmp/umanews-deployment.lock`），
   多宿主不互斥；当前生产为单机 Compose，适用；
2. P2-2：rollback checkout 后继续执行当前脚本，sh 增量读取存在理论错位风险（pre-existing，
   marker 保证 checkout 后 helper 存在；后续建议：checkout 后 exec 外部编排）；
3. deploy 存在设计内停机窗口（非零停机架构现状）；
4. rollback 信任目标 ref 的脚本属有意设计；
5. probe 对多副本只取 `ps -q` 首行（pre-existing，drain 完整快照兜底；scale>1 需重审）；
6. git mode 混合：既有 deploy 脚本部分 100644 部分 100755，新增脚本本地为 755，
   commit 时会引入 mode 变化，提交前需用户确认；
7. 真实 Compose 三路径未验证（见第 5 节）。

## 9. 给审核者的审核要求

范围：第 4 节列出的全部新增/修改文件（含本文档之外的 change 文档与测试）。

必须实际执行的步骤：

1. `python3 .codex/scripts/review_fingerprint.py`，保存完整输出（FINGERPRINT_SHA256、head、
   content_manifest_sha256）作为审前基线；
2. 原生 review：`codex review -c 'sandbox_mode="read-only"' --uncommitted`（CLI 环境）；
   记录真实退出码与内层启动头是否报告 `sandbox: read-only`；命令不可用、非零或未覆盖
   完整范围时结论不得为 APPROVED；
3. 逐文件只读审查，重点攻击：
   - 是否还存在任何第二 migration/collectstatic 入口（变体空格、`call_command`、间接脚本）；
   - 两个部署/回滚/手工入口并发：锁是否真互斥（mkdir 原子、失败者不装 trap、verify 先于
     一切 Compose 调用、token 不落盘不打印、非 owner 不能 release）；
   - release task / web healthy 失败是否绝对不启动任何下游服务（`set -eu` 覆盖、
     无 `|| true` 吞错、管道与子 shell 陷阱）；
   - web healthy 是否硬门禁（精确 `true healthy`、超时、unhealthy 立即失败）；
   - rollback 是否误称反向迁移或支持任意 pre-fix ref；contract marker 校验是否在
     checkout/停服之前；
   - race_live_worker 是否跨 migration 运行或被意外启用（状态冻结时机、恢复条件、
     探测失败 fail closed）；
   - manual_release 是否可绕锁、四门服务任一 running/restarting/未知时是否零 compose run；
   - pre-contract 桥是否不调用 one-shot、不 checkout、schema 不兼容在 image 切换前停止；
   - drain 的 EXPECTED_CELERY_WORKERS 透传是否有 shell/python 注入面（字符集白名单、
     精确匹配语义）；
   - 测试真实性：fake harness 是否真跑脚本、断言是否 load-bearing、是否有空转或通过
     降低断言强度达成的 GREEN；
   - shell 通用问题：未引号变量、allowlist 绕过（`../`、符号链接、大小写）、cd/ROOT_DIR 边界；
4. 运行验证（只读，只写临时目录）：
   ```bash
   cd server && ../.venv/bin/python manage.py test stable.test_single_migration_owner 2>&1 | tail -3
   ../.venv/bin/python manage.py test stable.test_historical_batch_runner_change.HistoricalBatchRunnerOperationsContractTests 2>&1 | tail -3
   ```
   （`.venv` 为 worktree 根指向主仓库 venv 的符号链接；相邻回归全量与基线对比见第 5 节，
   如需复跑全量请对照 pre-existing 失败清单，不要把既有环境性失败算入本 change。）
5. 审核结束后立即再次运行步骤 1 的 fingerprint 命令，要求前后 FINGERPRINT_SHA256
   逐字节一致；任何不一致、失败或无法比较 = BLOCKED。

结论格式：

- 审核范围与实际命令（含原生 review 退出码/可用性）；
- 前后 FINGERPRINT_SHA256、head、content_manifest_sha256；
- findings 按 P0/P1/P2/P3（文件:行 + 一句话 + 触发场景）；
- 最终结论：APPROVED / REVISE / BLOCKED；残余风险单独列出；
- 成功标准：原生 review 覆盖完整范围 + 前后指纹一致 + 全部 actionable findings 清零。
