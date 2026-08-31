# G2：四地区多年参赛马回填关闭态基础代码发布

状态：`等待用户明确授权`。本文件不构成 commit、push、merge、部署或 migration 授权。

2026-08-30 已把 Montjeu N1 所需的 exclusive proof generator 拆成独立、零 migration 的 proof-only G2
候选；详见 `g2_proof_only_release_20260830.md`。该子包不取代本文完整 foundation 发布，只先解除 N1
现场 proof 的代码前置门禁；两者都仍为未批准状态。

## 基线

- 当前实现 worktree：`codex/export-graded-race-horses-2000-current`。
- 实现起点：`a063ecf985539fc2d82a27170c7d634e0f7e5fc8`。
- 当前 `origin/main`：`409f2ac6cd15b7e8781dd9ada2903c91a9fc2121`。起点后已有多项 race-data、
  source allowlist、共享 host budget、crawler 和 production stop 修复；完整 foundation 提交前必须从该
  最新基线重放并重新运行全部验证，旧 `324/324` 和完整 stable 失败快照不能替代新基线证据。
- 生产只读观测：`/opt/umanewsbot` checkout 为 `bef0cdc5…495`；实际 web/worker/Beat image revision
  均为 `a063ecf9…fc8`，image SHA 为 `4a5f34b1…78eb`；web/db/redis healthy，migration leaf 为 `0075`；
  horse-data 与 race-data 总开关均为 false。

## 授权后允许的代码动作

1. 在独立 worktree 把本 change 重放到最新 `origin/main`，只解决本 change 与新状态文档的冲突。
2. 重跑全部本 change 聚焦测试、Django check、migration drift、fresh SQLite migration 和 diff/security check。
3. commit、push `codex/export-graded-race-horses-2000-current`、创建 PR；复核最终 diff 后合并。
4. 从精确 merge SHA 建 isolated release/image，在所有 TRA backfill/staging/canonical 写入开关关闭时部署。
5. 运行 additive schema migration `0076`–`0079`，再验证 web/worker/Beat revision/image、migration leaf、
   Django check、Celery/Redis、内部/公网 health 与日志。

## 发布内容

- Ireland RacingRegion、TJCIS flat/jumps parser、Europe/Dublin 时区。
- `ExternalDataSource.THE_RACING_API`、ExternalHorse breeder/damsire/parent IDs。
- `HorseExternalIdentity`、`HorseNameVariant` 及只读 admin。
- artifact-only targeted/bulk/batch runner、严格 HTTP/分页/身份/runner normalizer。
- 账号级独占文件预算、跨 run 内容寻址 pool、External staging dry-run/apply command。
- 独立 `graded_horse_backfill` import layer、target snapshot/historical bridge、reviewed identity
  receipt apply/replay/reverse/verifier；生产写入仍需双开关和后续精确 G3。
- 调研、变更设计、测试矩阵、census、Montjeu seed 与 G2/G3 门禁文档。

## 明确排除

- 不读取或改变 TRA 凭据；不调用任何 TRA endpoint。
- 不写 External staging、HorseProfile、RaceEvent、RaceEventResult 或 HorseRaceRecord。
- 不启用 horse-data、race-data、race-live、发布、QQ、邮件或任何 unattended backfill。
- 不批准 Montjeu proof、四地区批量导出或任一 production apply。
- 不审批剩余 26 个 source conflict，不把 `PREPARED` ledger 改成 `COMPLETE`。

## Migration 与回滚

- `0076` 只扩展 Ireland choices，无数据改写。
- `0077` 增加 TRA source choice、ExternalHorse 可空字段和两个新 identity/name 表；不回填既有行。
- `0078` 只增加历史导入 layer choice；`0079` 增加 identity review receipt，不自动创建 canonical horse。
- 四个 migration 均为 additive；代码回滚优先切回前一镜像并保持新增 schema，不在事故窗口执行破坏性
  reverse migration。若 migration 前 preflight 任一项失败，部署在迁移前停止。

## 当前验证

- 纯 Python：`52/52`。
- Django：TJCIS/Ireland/TRA/identity/staging/bridge/date/detail-source `162/162`；inventory/batch
  相邻回归 `110/110`，本次影响面合计 `324/324`。
- fresh SQLite：全部 migration 到 `0079` 成功。
- Django check、migration drift、compileall、`git diff --check` 通过。完整 `stable` 检查未通过：手工停止前
  `4,445` 项为 `32 failures / 144 errors / 128 skipped`，未完成归因，不作为发布绿灯。

在重放到最新 `origin/main` 后，上述证据必须全部重新生成；旧数字不能替代最终 merge SHA 的发布证据。
